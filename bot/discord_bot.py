"""
Bot Discord principal Agent Email conversationnel.
"""
import asyncio
import logging
import os

import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

# Import des modules de l'agent
from bot.conversation import clear_context, get_context
from bot.formatter import (
    format_draft,
    format_email_detail,
    format_email_list,
    format_error,
    format_help,
    format_success,
)
from bot.intent import detect_intent, generate_chat_response
from src.agent import categorize_email, draft_reply, summarize_email
from src.gmail_client import (
    build_service_from_token,
    get_email,
    get_gmail_service,
    list_emails,
    mark_as_read,
    send_reply,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("discord_bot")

# Configuration 
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
ALLOWED_USER_ID = os.getenv("DISCORD_USER_ID")

# Gmail Service
def _get_gmail_service():
    """Retourne le service Gmail local"""
    return get_gmail_service()

# Discord Bot Setup
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

# Cache de la dernière liste d'emails par utilisateur
_email_cache: dict[int, list[dict]] = {}


# Events

@bot.event
async def on_ready():
    logger.info(f" Bot connecté en tant que {bot.user} (ID: {bot.user.id})")
    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.watching,
            name="ta boîte Gmail",
        )
    )


@bot.event
async def on_message(message: discord.Message):
    # Ignorer les messages du bot lui-même
    if message.author.bot:
        return

    # Restriction optionnelle à un seul utilisateur
    if ALLOWED_USER_ID and str(message.author.id) != ALLOWED_USER_ID:
        return

    # Traiter les commandes préfixées
    await bot.process_commands(message)

    # Ignorer si c'est une commande préfixée
    if message.content.startswith("!"):
        return

    # Traitement conversationnel
    await handle_conversation(message)


# Handler principal

async def handle_conversation(message: discord.Message):
    """Cœur du bot : détecte l'intention et exécute l'action."""
    user_id = message.author.id
    ctx = get_context(user_id)
    user_text = message.content.strip()

    # Ajout au contexte
    ctx.add_to_history("user", user_text)

    # Action en attente : l'utilisateur fournit le texte de réponse
    if ctx.pending_action == "awaiting_reply_body":
        await _handle_awaiting_reply(message, ctx, user_text)
        return

    # Détection d'intention via Groq
    async with message.channel.typing():
        intent = await asyncio.get_event_loop().run_in_executor(
            None, detect_intent, user_text, ctx.history[:-1]
        )

    action = intent.get("action", "unknown")
    params = intent.get("params", {})

    logger.info(f"[{message.author}] intent={action} params={params}")

    # Dispatch des actions
    try:
        if action == "list_emails":
            await _action_list_emails(message, ctx, params)

        elif action == "read_email" or action == "summarize_email":
            await _action_read_email(message, ctx, params, summarize=(action == "summarize_email"))

        elif action == "draft_reply":
            await _action_draft_reply(message, ctx, params)

        elif action == "send_reply":
            await _action_send_reply(message, ctx, params)

        elif action == "confirm_send":
            await _action_confirm_send(message, ctx)

        elif action == "cancel":
            await _action_cancel(message, ctx)

        elif action == "mark_read":
            await _action_mark_read(message, ctx)

        elif action == "search_emails":
            await _action_list_emails(message, ctx, params)

        elif action == "help":
            await message.channel.send(embed=format_help())

        elif action == "reset":
            clear_context(user_id)
            _email_cache.pop(user_id, None)
            await message.channel.send(embed=format_success("Conversation réinitialisée ! Que puis-je faire pour toi ?"))

        elif action == "greet" or action == "chat":
            async with message.channel.typing():
                reply = await asyncio.get_event_loop().run_in_executor(
                    None, generate_chat_response, user_text, ctx.history[:-1]
                )
            ctx.add_to_history("assistant", reply)
            await message.channel.send(reply)

        else:
            # Fallback : on laisse le LLM répondre naturellement
            async with message.channel.typing():
                reply = await asyncio.get_event_loop().run_in_executor(
                    None, generate_chat_response, user_text, ctx.history[:-1]
                )
            ctx.add_to_history("assistant", reply)
            await message.channel.send(reply)

    except Exception as e:
        logger.error(f"Error in action {action}: {e}", exc_info=True)
        await message.channel.send(embed=format_error(f"Une erreur s'est produite : {e}"))


# Actions

async def _action_list_emails(message: discord.Message, ctx, params: dict):
    query = params.get("query", "is:inbox")
    max_results = min(int(params.get("max_results", 5)), 10)

    async with message.channel.typing():
        service = await asyncio.get_event_loop().run_in_executor(None, _get_gmail_service)
        emails = await asyncio.get_event_loop().run_in_executor(
            None, list_emails, service, max_results, query
        )

    _email_cache[message.author.id] = emails
    ctx.add_to_history("assistant", f"J'ai affiché {len(emails)} emails.")

    title_map = {
        "is:unread": " Emails non lus",
        "is:inbox":  " Boîte de réception",
    }
    title = title_map.get(query, f" Résultats : {query}")
    await message.channel.send(embed=format_email_list(emails, title=title))


async def _action_read_email(message: discord.Message, ctx, params: dict, summarize: bool = True):
    email_id = params.get("email_id")
    index = params.get("index")
    user_id = message.author.id

    # Résolution par index dans le cache
    if email_id is None and index is not None:
        cache = _email_cache.get(user_id, [])

        # Pas de cache, on va chercher la liste automatiquement
        if not cache:
            async with message.channel.typing():
                service = await asyncio.get_event_loop().run_in_executor(None, _get_gmail_service)
                cache = await asyncio.get_event_loop().run_in_executor(
                    None, list_emails, service, 10, "is:inbox"
                )
                _email_cache[user_id] = cache

        try:
            email_id = cache[int(index)]["id"]
        except (IndexError, KeyError):
            await message.channel.send(embed=format_error(
                f"Je ne trouve pas l'email #{int(index)+1} (j'ai {len(cache)} emails en mémoire)."
            ))
            return

    if not email_id:
        # Si un email est actif, on l'utilise
        if ctx.active_email_id:
            email_id = ctx.active_email_id
        else:
            # Aucun contexte, on prend le dernier email de la boîte
            async with message.channel.typing():
                service = await asyncio.get_event_loop().run_in_executor(None, _get_gmail_service)
                cache = await asyncio.get_event_loop().run_in_executor(
                    None, list_emails, service, 1, "is:inbox"
                )
                if not cache:
                    await message.channel.send("📭 Ta boîte est vide !")
                    return
                _email_cache[user_id] = cache
                email_id = cache[0]["id"]

    async with message.channel.typing():
        service = await asyncio.get_event_loop().run_in_executor(None, _get_gmail_service)
        email = await asyncio.get_event_loop().run_in_executor(None, get_email, service, email_id)

        summary = None
        classification = None
        if summarize:
            try:
                summary = await asyncio.get_event_loop().run_in_executor(None, summarize_email, email)
                classification = await asyncio.get_event_loop().run_in_executor(None, categorize_email, email)
            except Exception as e:
                logger.warning(f"AI summarize/classify failed: {e}")

    ctx.set_active_email(email)
    ctx.add_to_history("assistant", f"J'ai affiché l'email '{email.get('subject')}' de {email.get('sender_email')}.")

    await message.channel.send(embed=format_email_detail(email, summary=summary, classification=classification))


async def _action_draft_reply(message: discord.Message, ctx, params: dict):
    email_id = params.get("email_id") or ctx.active_email_id
    instructions = params.get("instructions", "")

    if not email_id:
        await message.channel.send(" Quel email veux-tu répondre ? Lis d'abord un email.")
        return

    async with message.channel.typing():
        service = await asyncio.get_event_loop().run_in_executor(None, _get_gmail_service)
        email = await asyncio.get_event_loop().run_in_executor(None, get_email, service, email_id)
        draft = await asyncio.get_event_loop().run_in_executor(None, draft_reply, email, instructions)

    ctx.set_active_email(email)
    ctx.pending_draft = draft
    ctx.pending_action = None
    ctx.add_to_history("assistant", f"J'ai généré un brouillon de réponse.")

    await message.channel.send(embed=format_draft(
        draft=draft,
        subject=email.get("subject", ""),
        to=email.get("sender_email", ""),
    ))


async def _action_send_reply(message: discord.Message, ctx, params: dict):
    """Envoi direct (sans passer par un brouillon)."""
    email_id = params.get("email_id") or ctx.active_email_id
    body = params.get("body", "")

    if not email_id or not body:
        # On demande le corps si absent
        ctx.pending_action = "awaiting_reply_body"
        await message.channel.send("Que souhaites-tu dire dans ta réponse ?")
        return

    async with message.channel.typing():
        service = await asyncio.get_event_loop().run_in_executor(None, _get_gmail_service)
        email = await asyncio.get_event_loop().run_in_executor(None, get_email, service, email_id)
        await asyncio.get_event_loop().run_in_executor(None, send_reply, service, email, body)
        await asyncio.get_event_loop().run_in_executor(None, mark_as_read, service, email_id)

    ctx.clear_active_email()
    ctx.add_to_history("assistant", "Réponse envoyée avec succès.")
    await message.channel.send(embed=format_success(f"Réponse envoyée à **{email.get('sender_email')}** !"))


async def _action_confirm_send(message: discord.Message, ctx):
    """Envoie le brouillon en attente."""
    if not ctx.pending_draft or not ctx.active_email_id:
        await message.channel.send(" Pas de brouillon en attente. Génère d'abord un brouillon avec 'réponds'.")
        return

    email_id = ctx.active_email_id
    draft = ctx.pending_draft

    async with message.channel.typing():
        service = await asyncio.get_event_loop().run_in_executor(None, _get_gmail_service)
        email = await asyncio.get_event_loop().run_in_executor(None, get_email, service, email_id)
        await asyncio.get_event_loop().run_in_executor(None, send_reply, service, email, draft)
        await asyncio.get_event_loop().run_in_executor(None, mark_as_read, service, email_id)

    ctx.clear_active_email()
    ctx.add_to_history("assistant", "Brouillon envoyé avec succès.")
    await message.channel.send(embed=format_success(f" Email envoyé à **{email.get('sender_email')}** !"))


async def _action_cancel(message: discord.Message, ctx):
    ctx.pending_action = None
    ctx.pending_draft = None
    ctx.add_to_history("assistant", "Action annulée.")
    await message.channel.send(" Action annulée. Que puis-je faire d'autre ?")


async def _action_mark_read(message: discord.Message, ctx):
    email_id = ctx.active_email_id
    if not email_id:
        await message.channel.send(" Aucun email actif. Lis d'abord un email.")
        return

    async with message.channel.typing():
        service = await asyncio.get_event_loop().run_in_executor(None, _get_gmail_service)
        await asyncio.get_event_loop().run_in_executor(None, mark_as_read, service, email_id)

    await message.channel.send(embed=format_success("Email marqué comme lu "))


async def _handle_awaiting_reply(message: discord.Message, ctx, text: str):
    """Gère la réponse quand le bot attend le corps du message."""
    email_id = ctx.active_email_id
    if not email_id:
        ctx.pending_action = None
        await message.channel.send(" Aucun email actif. Recommence.")
        return

    ctx.pending_action = None
    async with message.channel.typing():
        service = await asyncio.get_event_loop().run_in_executor(None, _get_gmail_service)
        email = await asyncio.get_event_loop().run_in_executor(None, get_email, service, email_id)
        await asyncio.get_event_loop().run_in_executor(None, send_reply, service, email, text)
        await asyncio.get_event_loop().run_in_executor(None, mark_as_read, service, email_id)

    ctx.clear_active_email()
    ctx.add_to_history("assistant", "Réponse envoyée.")
    await message.channel.send(embed=format_success(f" Réponse envoyée à **{email.get('sender_email')}** !"))


# Commandes préfixées
@bot.command(name="reset")
async def cmd_reset(ctx: commands.Context):
    """!reset — Réinitialise la conversation."""
    clear_context(ctx.author.id)
    _email_cache.pop(ctx.author.id, None)
    await ctx.send(embed=format_success("Conversation réinitialisée !"))


@bot.command(name="aide", aliases=["help_cmd"])
async def cmd_help(ctx: commands.Context):
    """!aide — Affiche l'aide."""
    await ctx.send(embed=format_help())


# Lancement

def run():
    bot.run(TOKEN)


if __name__ == "__main__":
    run()

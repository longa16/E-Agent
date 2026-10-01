"""
Formatters Discord : transforme les données email en Discord Embeds.
"""
import discord
from datetime import datetime


# Couleurs selon la priorité / catégorie
CATEGORY_COLORS = {
    "urgent":      discord.Color.red(),
    "important":   discord.Color.orange(),
    "meeting":     discord.Color.blue(),
    "newsletter":  discord.Color.greyple(),
    "spam":        discord.Color.dark_grey(),
    "default":     discord.Color.from_rgb(88, 101, 242),  # Bleu Discord
}

CATEGORY_EMOJI = {
    "urgent":     "🔴",
    "important":  "🟠",
    "meeting":    "📅",
    "newsletter": "📰",
    "spam":       "🗑️",
    "default":    "📧",
}


def _truncate(text: str, max_len: int = 1024) -> str:
    """Tronque le texte avec ellipsis si trop long."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def format_email_list(emails: list[dict], title: str = " Emails") -> discord.Embed:
    """Embed listant plusieurs emails avec numéro pour référence."""
    embed = discord.Embed(
        title=title,
        color=discord.Color.from_rgb(88, 101, 242),
        timestamp=datetime.utcnow(),
    )

    if not emails:
        embed.description = "_Aucun email trouvé._"
        return embed

    for i, email in enumerate(emails, start=1):
        read_icon = "✉️" if not email.get("is_read") else "📖"
        subject = email.get("subject", "(sans objet)")
        sender = email.get("sender_name") or email.get("sender_email", "?")
        snippet = _truncate(email.get("snippet", ""), 80)

        embed.add_field(
            name=f"{read_icon} `#{i}` {_truncate(subject, 50)}",
            value=f"**De :** {sender}\n_{snippet}_",
            inline=False,
        )

    embed.set_footer(text=f"{len(emails)} email(s) • Dis '#1', 'lis le 2ème', 'résume le 3', etc.")
    return embed


def format_email_detail(email: dict, summary: str = None, classification: dict = None) -> discord.Embed:
    """Embed détaillé pour un seul email."""
    category = (classification or {}).get("category", "default")
    color = CATEGORY_COLORS.get(category, CATEGORY_COLORS["default"])
    emoji = CATEGORY_EMOJI.get(category, "📧")

    subject = email.get("subject", "(sans objet)")
    embed = discord.Embed(
        title=f"{emoji} {_truncate(subject, 200)}",
        color=color,
        timestamp=datetime.utcnow(),
    )

    embed.add_field(name="De", value=email.get("sender_name", "?"), inline=True)
    embed.add_field(name="Email", value=email.get("sender_email", "?"), inline=True)
    embed.add_field(name="Date", value=_truncate(email.get("date", "?"), 50), inline=True)

    if summary:
        embed.add_field(name=" Résumé IA", value=_truncate(summary, 1024), inline=False)

    if classification:
        priority = classification.get("priority", "?")
        reason = classification.get("reason", "")
        embed.add_field(
            name=f" Catégorie : {category} | Priorité : {priority}",
            value=_truncate(reason, 256),
            inline=False,
        )

    body = _truncate(email.get("body", ""), 500)
    if body:
        embed.add_field(name=" Contenu (extrait)", value=f"```{body}```", inline=False)

    embed.set_footer(text=f"ID: {email.get('id', '?')} • Tape 'réponds' ou 'brouillon' pour répondre")
    return embed


def format_draft(draft: str, subject: str, to: str) -> discord.Embed:
    """Embed affichant un brouillon de réponse généré par l'IA."""
    embed = discord.Embed(
        title=" Brouillon généré par l'IA",
        color=discord.Color.gold(),
        timestamp=datetime.utcnow(),
    )
    embed.add_field(name="À", value=to, inline=True)
    embed.add_field(name="Objet", value=f"Re: {_truncate(subject, 100)}", inline=True)
    embed.add_field(name="Message", value=_truncate(draft, 1024), inline=False)
    embed.set_footer(text=" 'envoie' pour envoyer •  'modifie + instructions' •  'annule'")
    return embed


def format_success(message: str) -> discord.Embed:
    """Embed de confirmation."""
    return discord.Embed(
        title=" Succès",
        description=message,
        color=discord.Color.green(),
        timestamp=datetime.utcnow(),
    )


def format_error(message: str) -> discord.Embed:
    """Embed d'erreur."""
    return discord.Embed(
        title=" Erreur",
        description=message,
        color=discord.Color.red(),
        timestamp=datetime.utcnow(),
    )


def format_help() -> discord.Embed:
    """Embed d'aide listant les commandes disponibles."""
    embed = discord.Embed(
        title=" Email Agent — Aide",
        description="Je suis ton assistant Gmail intelligent. Parle-moi naturellement !",
        color=discord.Color.from_rgb(88, 101, 242),
    )
    embed.add_field(
        name=" Lire les emails",
        value=(
            "• `montre mes emails`\n"
            "• `emails non lus`\n"
            "• `emails de john@example.com`\n"
            "• `cherche les emails avec 'entretien'`"
        ),
        inline=False,
    )
    embed.add_field(
        name="Consulter un email",
        value=(
            "• `lis le 1er` / `ouvre le #2`\n"
            "• `résume cet email`\n"
            "• `plus de détails`"
        ),
        inline=False,
    )
    embed.add_field(
        name="Répondre",
        value=(
            "• `réponds` → brouillon IA automatique\n"
            "• `réponds en disant que je confirme`\n"
            "• `envoie` → confirmer l'envoi\n"
            "• `annule` → annuler"
        ),
        inline=False,
    )
    embed.add_field(
        name="Autres",
        value=(
            "• `reset` → recommencer\n"
            "• `aide` / `help` → cette aide"
        ),
        inline=False,
    )
    embed.set_footer(text="Tip : tu peux parler naturellement, je comprends le français !")
    return embed

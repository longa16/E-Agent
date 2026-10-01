"""
Détection d'intention via Groq LLM.
Transforme un message utilisateur en action structurée.
"""
import json
import logging
import os

from groq import Groq

logger = logging.getLogger(__name__)

# Mêmes modèles que src/agent.py
MODEL = "qwen/qwen3.8-27b"
FALLBACK_MODEL = "llama-3.1-8b-instant"

# Initialisation paresseuse
_groq_client: Groq | None = None


def _get_groq() -> Groq:
    global _groq_client
    if _groq_client is None:
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError("GROQ_API_KEY manquant ! Vérifie ton fichier .env.")
        _groq_client = Groq(api_key=api_key)
    return _groq_client

SYSTEM_PROMPT = """Tu es l'assistant IA d'un agent email Gmail intégré à Discord.
Tu analyses les messages de l'utilisateur et tu retournes UNIQUEMENT un JSON structuré représentant l'intention détectée.

Actions disponibles :
- greet          : salutation, message d'accueil, bavardage général
- list_emails    : lister, afficher, montrer des emails (params: query, max_results)
- read_email     : lire, ouvrir, voir un email précis (params: index OU email_id)
- summarize_email: résumer un email (params: index OU email_id)
- draft_reply    : générer un brouillon de réponse IA (params: instructions)
- send_reply     : envoyer une réponse (params: body)
- confirm_send   : confirmer l'envoi du brouillon en attente
- cancel         : annuler l'action en cours
- mark_read      : marquer comme lu
- search_emails  : rechercher des emails (params: query)
- help           : demander de l'aide
- reset          : réinitialiser / recommencer
- chat           : conversation générale sans lien avec les emails (répondre naturellement)

Règles CRITIQUES :
- Réponds TOUJOURS en JSON valide, sans markdown, sans explication.
- Format EXACT : {"action": "...", "params": {...}, "confidence": 0.0-1.0}
- N'utilise JAMAIS "unknown". Si tu ne sais pas, utilise "chat" ou "greet".
- Pour les salutations (bonjour, salut, hey, coucou, bonsoir) → "greet"
- Pour les questions générales sur les emails → "list_emails" ou "read_email"
- "oui", "ok", "vas-y", "envoie", "go", "c'est bon", "parfait" → "confirm_send"
- "non", "annule", "stop", "laisse tomber", "pas maintenant" → "cancel"
- Pour query Gmail : "is:unread", "is:inbox", "from:x@y.com", "subject:mot"
- index est 0-based (le 1er = 0, le 2ème = 1, le dernier = 0 avec query triée)
- max_results par défaut : 5

Exemples (couvre les formulations naturelles en français) :

User: "bonjour"
→ {"action": "greet", "params": {}, "confidence": 1.0}

User: "salut !"
→ {"action": "greet", "params": {}, "confidence": 1.0}

User: "bonjour, comment ça va ?"
→ {"action": "greet", "params": {}, "confidence": 1.0}

User: "c'est quoi le dernier mail que j'ai reçu ?"
→ {"action": "list_emails", "params": {"query": "is:inbox", "max_results": 1}, "confidence": 0.95}

User: "montre mes emails non lus"
→ {"action": "list_emails", "params": {"query": "is:unread", "max_results": 5}, "confidence": 0.97}

User: "j'ai quoi dans ma boite mail ?"
→ {"action": "list_emails", "params": {"query": "is:inbox", "max_results": 5}, "confidence": 0.93}

User: "est-ce que j'ai des nouveaux mails ?"
→ {"action": "list_emails", "params": {"query": "is:unread", "max_results": 5}, "confidence": 0.95}

User: "montre-moi mes 10 derniers emails"
→ {"action": "list_emails", "params": {"query": "is:inbox", "max_results": 10}, "confidence": 0.97}

User: "lis le premier"
→ {"action": "read_email", "params": {"index": 0}, "confidence": 0.95}

User: "ouvre le 2ème"
→ {"action": "read_email", "params": {"index": 1}, "confidence": 0.95}

User: "montre-moi le dernier"
→ {"action": "read_email", "params": {"index": 0}, "confidence": 0.90}

User: "c'est quoi le premier ?"
→ {"action": "read_email", "params": {"index": 0}, "confidence": 0.92}

User: "résume-le"
→ {"action": "summarize_email", "params": {}, "confidence": 0.93}

User: "résume le 2ème mail"
→ {"action": "summarize_email", "params": {"index": 1}, "confidence": 0.95}

User: "de quoi parle cet email ?"
→ {"action": "summarize_email", "params": {}, "confidence": 0.90}

User: "réponds-lui"
→ {"action": "draft_reply", "params": {"instructions": ""}, "confidence": 0.92}

User: "réponds en disant que je confirme l'entretien jeudi"
→ {"action": "draft_reply", "params": {"instructions": "confirmer l'entretien jeudi"}, "confidence": 0.95}

User: "rédige une réponse professionnelle"
→ {"action": "draft_reply", "params": {"instructions": "ton professionnel"}, "confidence": 0.93}

User: "dis-lui que je ne suis pas disponible"
→ {"action": "draft_reply", "params": {"instructions": "indiquer que je ne suis pas disponible"}, "confidence": 0.95}

User: "oui envoie"
→ {"action": "confirm_send", "params": {}, "confidence": 0.99}

User: "c'est bon, envoie"
→ {"action": "confirm_send", "params": {}, "confidence": 0.99}

User: "annule"
→ {"action": "cancel", "params": {}, "confidence": 0.99}

User: "cherche les mails de john@example.com"
→ {"action": "search_emails", "params": {"query": "from:john@example.com"}, "confidence": 0.95}

User: "tu peux quoi faire ?"
→ {"action": "help", "params": {}, "confidence": 0.95}

User: "aide"
→ {"action": "help", "params": {}, "confidence": 1.0}

User: "merci"
→ {"action": "chat", "params": {"message": "merci"}, "confidence": 0.90}

User: "c'est cool"
→ {"action": "chat", "params": {"message": "c'est cool"}, "confidence": 0.90}
"""


def detect_intent(user_message: str, conversation_history: list[dict]) -> dict:
    """
    Analyse le message utilisateur et retourne l'intention détectée.
    Returns: dict with keys: action, params, confidence
    """
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages += conversation_history[-10:]  # Contexte récent
    messages.append({"role": "user", "content": user_message})

    for model in [MODEL, FALLBACK_MODEL]:
        try:
            response = _get_groq().chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.1,
                max_tokens=200,
            )
            raw = response.choices[0].message.content.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            try:
                result = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning(f"Intent JSON parse failed: {raw!r}")
                return {"action": "chat", "params": {}, "confidence": 0.0}
            if result.get("action") == "unknown":
                result["action"] = "chat"
            return result
        except Exception as e:
            logger.warning(f"detect_intent failed with {model}: {e}")
            continue
    # Tous les modèles ont échoué on laisse le handler afficher l'erreur
    raise RuntimeError(f"Groq API indisponible. Vérifie ta clé API ou réessaie.")


def generate_chat_response(user_message: str, conversation_history: list[dict]) -> str:
    """
    Génère une réponse conversationnelle naturelle pour les messages
    qui ne correspondent à aucune action
    """
    system = (
        "Tu es E-Agent, un assistant IA sympa et décontracté intégré à Discord. "
        "Tu gères la boîte email Gmail de l'utilisateur. "
        "Réponds en français de façon naturelle et chaleureuse. "
        "Si l'utilisateur dit bonjour ou fait la conversation, réponds poliment "
        "et rappelle brièvement ce que tu peux faire (lire emails, résumer, répondre). "
        "Sois concis (2-3 phrases max)."
    )
    messages = [{"role": "system", "content": system}]
    messages += conversation_history[-6:]
    messages.append({"role": "user", "content": user_message})

    for model in [MODEL, FALLBACK_MODEL]:
        try:
            response = _get_groq().chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.7,
                max_tokens=200,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.warning(f"generate_chat_response failed with {model}: {e}")
            continue
    raise RuntimeError("Groq API indisponible pour la réponse conversationnelle.")

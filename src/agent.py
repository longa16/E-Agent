"""
Agent IA  Résumé, 
classification et rédaction de réponses via Groq.
Retry automatique avec backoff exponentiel.
"""
import json
import logging
import os
import re
import time

from dotenv import load_dotenv
from groq import Groq

load_dotenv()

logger = logging.getLogger(__name__)

_client = Groq(
    api_key=os.getenv("GROQ_API_KEY"),
    timeout=30.0,
)
# modèle principal + fallback
MODEL = "openai/gpt-oss-120b"
FALLBACK_MODEL = "llama-3.1-8b-instant"
MAX_RETRIES = 3


def _chat(prompt: str) -> str:
    """Envoie un message au modèle avec retry automatique et fallback."""
    last_error = None
    models_to_try = [MODEL, FALLBACK_MODEL]

    for model in models_to_try:
        for attempt in range(MAX_RETRIES):
            try:
                response = _client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.3,
                )
                return response.choices[0].message.content.strip()
            except Exception as e:
                last_error = e
                error_str = str(e).lower()
                # Retry sur erreurs transitoires (rate limit, 500, 503, timeout)
                is_retryable = any(kw in error_str for kw in [
                    "rate_limit", "429", "500", "502", "503",
                    "timeout", "overloaded", "unavailable",
                    "internal", "capacity",
                ])
                if is_retryable and attempt < MAX_RETRIES - 1:
                    wait = (2 ** attempt) + 0.5  # 1.5s, 2.5s, 4.5s
                    logger.warning(
                        f"Groq API error (model={model}, attempt={attempt+1}): {e}. "
                        f"Retrying in {wait}s..."
                    )
                    time.sleep(wait)
                    continue
                elif not is_retryable:
                    # Erreur non-retryable (auth, bad request) → essayer le fallback
                    logger.warning(f"Non-retryable error with {model}: {e}")
                    break
                else:
                    # Dernier retry échoué → essayer le fallback model
                    logger.warning(f"All retries exhausted for {model}: {e}")
                    break

    # Si tous les modèles ont échoué
    raise Exception(f"Échec API IA après plusieurs tentatives : {last_error}")


# Fonctions de l'agent

def summarize_email(email: dict) -> str:
    """Résume un email."""
    prompt = f"""Résume cet email en 2-3 phrases maximum.
             Mets en avant les informations clés et les actions requises. 
             Réponds directement sans introduction.

De : {email['sender_name']} <{email['sender_email']}>
Objet : {email['subject']}
Date : {email['date']}

Corps :
{email['body'][:3000]}"""

    return _chat(prompt)


def categorize_email(email: dict) -> dict:
    """Classifie un email et détermine sa priorité."""
    prompt = f"""Analyse cet email et réponds UNIQUEMENT avec un objet JSON valide, 
                sans markdown, sans texte autour :
{{
  "category": "<important | reply_needed | newsletter | notification | spam | promotional>",
  "priority": "<high | medium | low>",
  "reason": "<une phrase expliquant la classification>"
}}

De : {email['sender_name']} <{email['sender_email']}>
Objet : {email['subject']}
Aperçu : {email['snippet']}"""

    response = _chat(prompt)

    try:
        text = re.sub(r"```(?:json)?", "", response).strip().rstrip("`").strip()
        return json.loads(text)
    except Exception:
        return {"category": "important", "priority": "medium", "reason": "Classification impossible"}


def draft_reply(email: dict, instructions: str = "") -> str:
    """Rédige une ébauche de réponse professionnelle à un email."""
    extra = f"\nConsignes supplémentaires : {instructions}" if instructions else ""

    prompt = f"""Rédige une réponse professionnelle et bienveillante à cet email.{extra}
            Réponds uniquement avec le corps du message,
            dans la même langue que l'email original. Sans ligne "Objet :".

Email original :
De : {email['sender_name']} <{email['sender_email']}>
Objet : {email['subject']}
Date : {email['date']}

{email['body'][:3000]}"""

    return _chat(prompt)


def process_inbox(emails: list) -> list:
    """Traite une liste d'emails : résumé + classification pour chacun."""
    processed = []

    for email in emails:
        try:
            summary = summarize_email(email)
            classification = categorize_email(email)

            processed.append({
                **email,
                "summary": summary,
                "category": classification.get("category", "important"),
                "priority": classification.get("priority", "medium"),
                "reason": classification.get("reason", ""),
            })
        except Exception as e:
            processed.append({
                **email,
                "summary": email.get("snippet", ""),
                "category": "important",
                "priority": "medium",
                "reason": f"Erreur de traitement : {e}",
            })

    return processed

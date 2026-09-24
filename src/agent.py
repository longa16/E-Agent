"""
Agent IA  Résumé, 
classification et rédaction de réponses via Groq qwen3.8.
"""
import json
import os
import re

from dotenv import load_dotenv
from groq import Groq

load_dotenv()

_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
# modèle 
MODEL = "qwen/qwen3.8-27b"  


def _chat(prompt: str) -> str:
    """Envoie un message au modèle et retourne la réponse texte."""
    response = _client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
    )
    return response.choices[0].message.content.strip()


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

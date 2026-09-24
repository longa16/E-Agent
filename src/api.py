"""
API FastAPI
 Routes de l'agent email Gmail.
"""
import os
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from groq import Groq
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()
_groq = Groq(api_key=os.getenv("GROQ_API_KEY"))

from src.agent import categorize_email, draft_reply, process_inbox, summarize_email
from src.gmail_client import (
    get_email,
    get_gmail_service,
    list_emails,
    mark_as_read,
    send_reply,
)

app = FastAPI(
    title="Email Agent API",
    description="Agent IA pour gérer votre boîte Gmail : lecture, résumé, tri et réponse automatique.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Servir les fichiers statiques
STATIC_DIR = Path(__file__).parent.parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Service Gmail initialisé une seule fois au démarrage
_gmail_service = None


def get_service():
    global _gmail_service
    if _gmail_service is None:
        _gmail_service = get_gmail_service()
    return _gmail_service


# Schémas

class ReplyRequest(BaseModel):
    body: str


class DraftRequest(BaseModel):
    instructions: Optional[str] = ""


class SpeakRequest(BaseModel):
    text: str
    voice: str = "hannah"


# Routes

@app.get("/", response_class=HTMLResponse, tags=["Interface"])
def root():
    """Sert l'interface web de l'agent email."""
    index_path = STATIC_DIR / "index.html"
    return HTMLResponse(content=index_path.read_text(encoding="utf-8"))


@app.get("/health", tags=["Statut"])
def health():
    return {"status": "ok", "message": "Email Agent API opérationnel"}


@app.get("/emails", tags=["Emails"])
def get_emails(
    max_results: int = Query(10, ge=1, le=50, description="Nombre d'emails à récupérer"),
    query: str = Query("is:inbox", description="Filtre Gmail (ex: is:unread, from:boss@company.com)"),
    process: bool = Query(False, description="Activer le traitement IA (résumé + classification)"),
):
    """
    Liste les emails de la boîte Gmail.
    
    - `query` supporte toute la syntaxe Gmail : `is:unread`, `from:x@y.com`, `subject:facture`, etc.
    - `process=true` active le résumé et la classification IA.
    """
    try:
        service = get_service()
        emails = list_emails(service, max_results=max_results, query=query)

        if process:
            emails = process_inbox(emails)

        return {"count": len(emails), "emails": emails}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/emails/{email_id}", tags=["Emails"])
def get_single_email(
    email_id: str,
    summarize: bool = Query(True, description="Générer un résumé IA"),
):
    """Récupère un email complet avec résumé et classification IA optionnels."""
    try:
        service = get_service()
        email = get_email(service, email_id)

        result: dict = {"email": email}

        if summarize:
            result["summary"] = summarize_email(email)
            result["classification"] = categorize_email(email)

        return result

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/emails/{email_id}/reply", tags=["Actions"])
def reply_to_email(email_id: str, request: ReplyRequest):
    """Envoie une réponse à un email et le marque comme lu."""
    try:
        service = get_service()
        email = get_email(service, email_id)
        msg_id = send_reply(service, email, request.body)
        mark_as_read(service, email_id)
        return {"success": True, "sent_message_id": msg_id}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/emails/{email_id}/draft-reply", tags=["Actions"])
def draft_reply_for_email(email_id: str, request: DraftRequest):
    """Génère une ébauche de réponse rédigée par l'IA."""
    try:
        service = get_service()
        email = get_email(service, email_id)
        draft = draft_reply(email, instructions=request.instructions or "")
        return {
            "draft": draft,
            "subject": email["subject"],
            "to": email["sender_email"],
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.patch("/emails/{email_id}/read", tags=["Actions"])
def mark_email_as_read(email_id: str):
    """Marque un email comme lu."""
    try:
        service = get_service()
        mark_as_read(service, email_id)
        return {"success": True}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/emails/search/{query}", tags=["Emails"])
def search(
    query: str,
    max_results: int = Query(10, ge=1, le=50),
):
    """Recherche des emails avec un filtre Gmail."""
    try:
        service = get_service()
        emails = list_emails(service, max_results=max_results, query=query)
        return {"count": len(emails), "query": query, "emails": emails}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/transcribe", tags=["STT"])
async def transcribe(file: UploadFile = File(...)):
    """
    Transcrit un fichier audio en texte via Groq Whisper.
    Accepte : webm, mp4, wav, mp3, ogg, m4a.
    """
    try:
        audio_bytes = await file.read()
        filename = file.filename or "audio.webm"

        # renvoyer un tuple à groq
        transcription = _groq.audio.transcriptions.create(
            file=(filename, audio_bytes),
            model="whisper-large-v3-turbo",
            language="fr",
            response_format="text",
        )
        return {"text": transcription}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/speak", tags=["TTS"])
async def speak(request: SpeakRequest):
    """
    Synthèse vocale via Groq Orpheus.
    Retourne un flux audio WAV à jouer directement dans le navigateur.
    Voix disponibles : tara, leah, jess, leo, dan, mia, zac, zoe
    """
    try:
        response = _groq.audio.speech.create(
            model="canopylabs/orpheus-v1-english",
            voice=request.voice,
            input=request.text[:4000],
            response_format="wav",
        )
        audio_bytes = response.read()
        return Response(
            content=audio_bytes,
            media_type="audio/wav",
            headers={"Content-Disposition": "inline"},
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


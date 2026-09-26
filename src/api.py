"""
API FastAPI
 Routes de l'agent email Gmail.
 Supporte le mode local et le mode web.
"""
import logging
import os
import secrets
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from groq import Groq
from pydantic import BaseModel
from dotenv import load_dotenv
from starlette.middleware.sessions import SessionMiddleware

load_dotenv()

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

try:
    _groq = Groq(api_key=os.getenv("GROQ_API_KEY"))
except Exception as e:
    logger.warning(f"Groq client init failed (TTS/STT will be unavailable): {e}")
    _groq = None

from src.agent import categorize_email, draft_reply, process_inbox, summarize_email
from src.gmail_client import (
    build_service_from_token,
    exchange_code,
    get_auth_url,
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

# Session middleware qui stocke un session ID signé dans un cookie
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SESSION_SECRET", secrets.token_hex(32)),
    session_cookie="eagent_session",
    max_age=7 * 24 * 3600,  # 7 jours
    same_site="lax",
    https_only=os.getenv("RAILWAY_ENVIRONMENT") is not None,  # HTTPS only en production
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

# In-memory token store
_user_tokens: dict[str, dict] = {}

# Service Gmail local
_local_service = None


def _get_service(request: Request):
    """
    Returns a Gmail service for the current user.
    Priority: 1) Per-user session token → 2) Local token.json
    Raises HTTP 401 for auth issues, not 500.
    """
    global _local_service

    # Web mode: check session
    sid = request.session.get("sid")
    if sid and sid in _user_tokens:
        try:
            service = build_service_from_token(_user_tokens[sid])
            # Quick validation: test the service works
            service.users().getProfile(userId="me").execute()
            return service
        except Exception as e:
            logger.warning(f"Token invalid for session {sid[:8]}...: {e}")
            # Token expired or invalid, clear session
            _user_tokens.pop(sid, None)
            request.session.clear()
            raise HTTPException(
                status_code=401,
                detail="Session expirée. Veuillez vous reconnecter."
            )

    # Local mode: fallback to token.json
    if os.path.exists("token.json"):
        try:
            if _local_service is None:
                _local_service = get_gmail_service()
            return _local_service
        except Exception as e:
            logger.error(f"Local token.json error: {e}")
            _local_service = None
            raise HTTPException(
                status_code=401,
                detail="Token local invalide. Veuillez vous reconnecter."
            )

    raise HTTPException(status_code=401, detail="Non authentifié. Connectez-vous avec Gmail.")


def _build_redirect_uri(request: Request) -> str:
    """Builds the OAuth callback URI, respecting reverse proxy headers."""
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("host", request.url.netloc)
    return f"{scheme}://{host}/auth/callback"


# Schémas

class ReplyRequest(BaseModel):
    body: str


class DraftRequest(BaseModel):
    instructions: Optional[str] = ""


class SpeakRequest(BaseModel):
    text: str
    voice: str = "hannah"


#  Auth routes

@app.get("/auth/login", tags=["Auth"])
def auth_login(request: Request):
    redirect_uri = _build_redirect_uri(request)
    auth_url, state, code_verifier = get_auth_url(redirect_uri)
    request.session["oauth_state"] = state
    request.session["oauth_code_verifier"] = code_verifier   # <- stocké en session
    return RedirectResponse(auth_url)

@app.get("/auth/callback", tags=["Auth"])
def auth_callback(request: Request, state: str = "", code: str = ""):
    redirect_uri = _build_redirect_uri(request)
    auth_response_url = str(request.url)
    code_verifier = request.session.get("oauth_code_verifier")

    try:
        token_data = exchange_code(auth_response_url, redirect_uri, code_verifier)
        sid = secrets.token_hex(16)
        _user_tokens[sid] = token_data
        request.session["sid"] = sid
        request.session.pop("oauth_state", None)
        request.session.pop("oauth_code_verifier", None)
        return RedirectResponse("/")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Erreur d'authentification : {e}")


@app.get("/auth/status", tags=["Auth"])
def auth_status(request: Request):
    """Vérifie si l'utilisateur est authentifié."""
    # Check web session
    sid = request.session.get("sid")
    if sid and sid in _user_tokens:
        try:
            service = build_service_from_token(_user_tokens[sid])
            profile = service.users().getProfile(userId="me").execute()
            return {"authenticated": True, "email": profile["emailAddress"]}
        except Exception:
            pass

    # Check local token.json
    if os.path.exists("token.json"):
        try:
            from src.gmail_client import get_gmail_service as _get_local
            service = _get_local()
            profile = service.users().getProfile(userId="me").execute()
            return {"authenticated": True, "email": profile["emailAddress"], "local": True}
        except Exception:
            pass

    return {"authenticated": False}


@app.get("/auth/logout", tags=["Auth"])
def auth_logout(request: Request):
    """Déconnecte l'utilisateur."""
    sid = request.session.get("sid")
    if sid and sid in _user_tokens:
        del _user_tokens[sid]
    request.session.clear()
    return RedirectResponse("/")


# Routes principales

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
    request: Request,
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
        service = _get_service(request)
        emails = list_emails(service, max_results=max_results, query=query)

        if process:
            emails = process_inbox(emails)

        return {"count": len(emails), "emails": emails}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/emails/{email_id}", tags=["Emails"])
def get_single_email(
    request: Request,
    email_id: str,
    summarize: bool = Query(True, description="Générer un résumé IA"),
):
    """Récupère un email complet avec résumé et classification IA optionnels."""
    try:
        service = _get_service(request)
        email = get_email(service, email_id)

        result: dict = {"email": email}

        if summarize:
            try:
                result["summary"] = summarize_email(email)
            except Exception as e:
                logger.error(f"Summarize failed for {email_id}: {e}")
                result["summary"] = email.get("snippet", "Résumé temporairement indisponible.")
            try:
                result["classification"] = categorize_email(email)
            except Exception as e:
                logger.error(f"Categorize failed for {email_id}: {e}")
                result["classification"] = {
                    "category": "important",
                    "priority": "medium",
                    "reason": "Classification temporairement indisponible",
                }

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"get_single_email error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/emails/{email_id}/reply", tags=["Actions"])
def reply_to_email(request: Request, email_id: str, req: ReplyRequest):
    """Envoie une réponse à un email et le marque comme lu."""
    try:
        service = _get_service(request)
        email = get_email(service, email_id)
        msg_id = send_reply(service, email, req.body)
        mark_as_read(service, email_id)
        return {"success": True, "sent_message_id": msg_id}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/emails/{email_id}/draft-reply", tags=["Actions"])
def draft_reply_for_email(request: Request, email_id: str, req: DraftRequest):
    """Génère une ébauche de réponse rédigée par l'IA."""
    try:
        service = _get_service(request)
        email = get_email(service, email_id)
        draft = draft_reply(email, instructions=req.instructions or "")
        return {
            "draft": draft,
            "subject": email["subject"],
            "to": email["sender_email"],
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.patch("/emails/{email_id}/read", tags=["Actions"])
def mark_email_as_read(request: Request, email_id: str):
    """Marque un email comme lu."""
    try:
        service = _get_service(request)
        mark_as_read(service, email_id)
        return {"success": True}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/emails/search/{query}", tags=["Emails"])
def search(
    request: Request,
    query: str,
    max_results: int = Query(10, ge=1, le=50),
):
    """Recherche des emails avec un filtre Gmail."""
    try:
        service = _get_service(request)
        emails = list_emails(service, max_results=max_results, query=query)
        return {"count": len(emails), "query": query, "emails": emails}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/transcribe", tags=["STT"])
async def transcribe(file: UploadFile = File(...)):
    """
    Transcrit un fichier audio en texte via Groq Whisper.
    Accepte : webm, mp4, wav, mp3, ogg, m4a.
    """
    try:
        if _groq is None:
            raise HTTPException(status_code=503, detail="Service STT indisponible (clé API manquante)")
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
async def speak(request_body: SpeakRequest):
    """
    Synthèse vocale via Groq Orpheus.
    Retourne un flux audio WAV à jouer directement dans le navigateur.
    Voix disponibles : tara, leah, jess, leo, dan, mia, zac, zoe
    """
    try:
        if _groq is None:
            raise HTTPException(status_code=503, detail="Service TTS indisponible (clé API manquante)")
        response = _groq.audio.speech.create(
            model="canopylabs/orpheus-v1-english",
            voice=request_body.voice,
            input=request_body.text[:4000],
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

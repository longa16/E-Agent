"""
Gmail Client Authentification OAuth2 et opérations Gmail.
Supporte le mode local et le mode web.
"""
import json
import os
import base64
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List, Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow, Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Scopes lecture, envoi et modification 
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
]

TOKEN_PATH = "token.json"
CREDENTIALS_PATH = "credentials.json"


# Credentials helpers

def _get_credentials_config() -> dict:
    """Reads Google OAuth credentials from env var or file."""
    env_creds = os.getenv("GOOGLE_CREDENTIALS")
    if env_creds:
        return json.loads(env_creds)
    if os.path.exists(CREDENTIALS_PATH):
        with open(CREDENTIALS_PATH) as f:
            return json.load(f)
    raise FileNotFoundError(
        "No Google credentials found. Set GOOGLE_CREDENTIALS env var "
        "or place credentials.json at the project root."
    )


# Local auth

def get_gmail_service():
    """Authentifie via token.json local."""
    creds = None

    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
            creds = flow.run_local_server(port=0)

        with open(TOKEN_PATH, "w") as token:
            token.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)


# Web auth

def get_auth_url(redirect_uri: str) -> tuple[str, str, str]:
    """Generates a Google OAuth consent URL for web flow."""
    config = _get_credentials_config()
    # Normalize: accept both "web" and "installed" credential types
    if "installed" in config and "web" not in config:
        installed = config["installed"]
        config = {
            "web": {
                "client_id": installed["client_id"],
                "client_secret": installed["client_secret"],
                "auth_uri": installed.get("auth_uri", "https://accounts.google.com/o/oauth2/auth"),
                "token_uri": installed.get("token_uri", "https://oauth2.googleapis.com/token"),
                "redirect_uris": [redirect_uri],
            }
        }

    flow = Flow.from_client_config(config, scopes=SCOPES, redirect_uri=redirect_uri)
    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    return auth_url, state, flow.code_verifier


def exchange_code(authorization_response: str, redirect_uri: str, code_verifier: str) -> dict:
    """Exchanges an authorization code for credentials. Returns token data as dict."""
    config = _get_credentials_config()
    if "installed" in config and "web" not in config:
        installed = config["installed"]
        config = {
            "web": {
                "client_id": installed["client_id"],
                "client_secret": installed["client_secret"],
                "auth_uri": installed.get("auth_uri", "https://accounts.google.com/o/oauth2/auth"),
                "token_uri": installed.get("token_uri", "https://oauth2.googleapis.com/token"),
                "redirect_uris": [redirect_uri],
            }
        }

    flow = Flow.from_client_config(
        config, scopes=SCOPES, redirect_uri=redirect_uri,
        code_verifier=code_verifier,             # <- on réinjecte le même verifier
    )
    flow.fetch_token(authorization_response=authorization_response)
    return json.loads(flow.credentials.to_json())

def build_service_from_token(token_data: dict):
    """Builds a Gmail service from stored token data (web mode).
    
    Raises Exception if credentials are expired and cannot be refreshed.
    """
    creds = Credentials.from_authorized_user_info(token_data, SCOPES)
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            # Update the stored token data with refreshed credentials
            refreshed = json.loads(creds.to_json())
            token_data.update(refreshed)
        except Exception as e:
            raise Exception(f"Impossible de rafraîchir le token : {e}")
    elif creds and creds.expired and not creds.refresh_token:
        raise Exception("Token expiré sans refresh token. Reconnexion nécessaire.")
    return build("gmail", "v1", credentials=creds)


# Helpers

def _get_header(headers: list, name: str) -> str:
    """Extrait la valeur d'un header par son nom."""
    for h in headers:
        if h["name"].lower() == name.lower():
            return h["value"]
    return ""


def _parse_sender(from_header: str) -> tuple[str, str]:
    """Sépare le nom et l'email depuis le champ From."""
    if "<" in from_header:
        name = from_header.split("<")[0].strip().strip('"')
        email = from_header.split("<")[-1].strip(">").strip()
    else:
        name = from_header
        email = from_header
    return name, email


def _extract_body(payload: dict) -> str:
    """Extrait récursivement le corps texte d'un email."""
    mime_type = payload.get("mimeType", "")
    body_data = payload.get("body", {}).get("data", "")

    if mime_type == "text/plain" and body_data:
        return base64.urlsafe_b64decode(body_data).decode("utf-8", errors="ignore")

    for part in payload.get("parts", []):
        result = _extract_body(part)
        if result:
            return result

    # Fallback sur HTML si pas de texte brut
    if mime_type == "text/html" and body_data:
        return base64.urlsafe_b64decode(body_data).decode("utf-8", errors="ignore")

    return ""


def _format_message(msg_data: dict) -> dict:
    """Convertit un message Gmail brut en dict structuré."""
    headers = msg_data["payload"].get("headers", [])
    from_header = _get_header(headers, "From")
    sender_name, sender_email = _parse_sender(from_header)

    return {
        "id": msg_data["id"],
        "thread_id": msg_data["threadId"],
        "subject": _get_header(headers, "Subject") or "(Sans objet)",
        "sender_name": sender_name,
        "sender_email": sender_email,
        "date": _get_header(headers, "Date"),
        "snippet": msg_data.get("snippet", ""),
        "body": _extract_body(msg_data["payload"]),
        "is_read": "UNREAD" not in msg_data.get("labelIds", []),
        "labels": msg_data.get("labelIds", []),
        "message_id_header": _get_header(headers, "Message-ID"),
    }


# Opérations Gmail

def list_emails(service, max_results: int = 10, query: str = "is:inbox") -> List[dict]:
    """Liste les emails selon une requête Gmail."""
    try:
        results = service.users().messages().list(
            userId="me",
            maxResults=max_results,
            q=query,
        ).execute()

        messages = results.get("messages", [])
        emails = []

        for msg in messages:
            msg_data = service.users().messages().get(
                userId="me",
                id=msg["id"],
                format="full",
            ).execute()
            emails.append(_format_message(msg_data))

        return emails

    except HttpError as e:
        raise Exception(f"Erreur API Gmail : {e}")


def get_email(service, email_id: str) -> dict:
    """Récupère un email spécifique par son ID."""
    try:
        msg_data = service.users().messages().get(
            userId="me",
            id=email_id,
            format="full",
        ).execute()
        return _format_message(msg_data)

    except HttpError as e:
        raise Exception(f"Erreur API Gmail : {e}")


def send_reply(service, email: dict, reply_body: str) -> str:
    """Envoie une réponse à un email existant."""
    try:
        message = MIMEMultipart()
        message["To"] = email["sender_email"]
        message["Subject"] = f"Re: {email['subject']}"
        message["In-Reply-To"] = email.get("message_id_header", "")
        message["References"] = email.get("message_id_header", "")
        message.attach(MIMEText(reply_body, "plain", "utf-8"))

        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()

        result = service.users().messages().send(
            userId="me",
            body={"raw": raw, "threadId": email["thread_id"]},
        ).execute()

        return result["id"]

    except HttpError as e:
        raise Exception(f"Erreur lors de l'envoi : {e}")


def mark_as_read(service, email_id: str) -> None:
    """Marque un email comme lu."""
    try:
        service.users().messages().modify(
            userId="me",
            id=email_id,
            body={"removeLabelIds": ["UNREAD"]},
        ).execute()
    except HttpError as e:
        raise Exception(f"Erreur lors du marquage comme lu : {e}")


def search_emails(service, query: str, max_results: int = 10) -> List[dict]:
    """Recherche des emails avec un filtre Gmail."""
    return list_emails(service, max_results=max_results, query=query)

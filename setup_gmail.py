"""
Script de configuration initiale — Authentifie l'accès Gmail et génère token.json.
À exécuter UNE SEULE FOIS (ou quand le token expire).
"""
import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Scopes complets : lecture + envoi + modification
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
]

TOKEN_PATH = "token.json"
CREDENTIALS_PATH = "credentials.json"


def main():
    """Authentifie l'utilisateur et vérifie l'accès Gmail."""
    creds = None

    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("🔄 Rafraîchissement du token...")
            creds.refresh(Request())
        else:
            print("🔐 Ouverture du navigateur pour l'authentification Gmail...")
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
            creds = flow.run_local_server(port=0)

        with open(TOKEN_PATH, "w") as token:
            token.write(creds.to_json())
        print(f"✅ Token sauvegardé dans {TOKEN_PATH}")

    # Vérification de l'accès
    try:
        service = build("gmail", "v1", credentials=creds)
        profile = service.users().getProfile(userId="me").execute()
        print(f"\n✅ Connexion réussie !")
        print(f"   Compte    : {profile['emailAddress']}")
        print(f"   Messages  : {profile['messagesTotal']:,}")
        print(f"   Threads   : {profile['threadsTotal']:,}")
        print(f"\n🚀 Tu peux maintenant lancer l'agent : uv run python main.py")

    except HttpError as e:
        print(f"❌ Erreur : {e}")


if __name__ == "__main__":
    main()
# E-Agent : Assistant Email IA

E-agent est un agent IA. Il intègre des modèles de langage avancés via **Groq** pour vous aider à trier, résumer et répondre à vos courriels.

## Fonctionnalités

- **Lecture et tri intelligent :** Récupération de votre boîte de réception Gmail avec l'API officielle.
- **Résumés IA :** Analyse automatique de vos emails avec `Qwen 3.8 27B` pour aller directement à l'essentiel.
- **Classification automatique :** Détection de l'urgence et de l'intention (Important, À répondre, Newsletter, etc.).
- **Génération de réponses :** Brouillons rédigés automatiquement selon le contexte de la conversation.
- **Dictée vocale:** Dictez vos réponses directement au micro grâce à **Groq Whisper** (`whisper-large-v3-turbo`).
- **Lecture audio :** Écoutez les résumés générés par l'IA grâce au modèle **Groq Orpheus** (`canopylabs/orpheus-v1-english`).
- **Design premium :** Interface web moderne, épurée, sans fioritures inutiles.

## Stack Technique

- **Backend :** Python, FastAPI, Uvicorn.
- **Frontend :** HTML5, Vanilla JavaScript, CSS.
- **Intégrations :** 
  - `google-api-python-client` (OAuth2 & API Gmail).
  - `groq`.

##  Installation & Lancement

### 1. Prérequis
- [Python 3.10+](https://www.python.org/downloads/)
- [uv](https://github.com/astral-sh/uv)

### 2. Clés requises
- **Google Cloud :** Obtenez un fichier `credentials.json` (OAuth 2.0 Client IDs de type "Application de bureau") depuis la [Console Google Cloud](https://console.cloud.google.com/) et placez-le à la racine du projet. *N'oubliez pas d'activer l'API Gmail pour votre projet.*
- **Groq :** Obtenez une clé API sur [GroqConsole](https://console.groq.com/).

### 3. Configuration

Clé l'API Groq dans un fichier `.env` à la racine :
```env
GROQ_API_KEY=votre_cle_api_groq_ici
```

Installez les dépendances :
```bash
uv sync
```
*(Si vous n'utilisez pas `uv`, vous pouvez installer les dépendances manuellement via pip : `pip install fastapi uvicorn google-api-python-client google-auth-httplib2 google-auth-oauthlib groq python-dotenv python-multipart`)*

### 4. Authentification Gmail
Exécutez le script de configuration pour vous authentifier avec votre compte Google et générer le jeton local (`token.json`) :
```bash
uv run python setup_gmail.py
```
*Une fenêtre de navigateur s'ouvrira pour autoriser l'application.*

### 5. Lancer l'Application
Lancez le serveur backend FastAPI :
```bash
uv run python main.py
```
L'interface web est alors accessible sur : **[http://localhost:8000](http://localhost:8000)**

## Structure du projet

```
Email-agent/
├── src/
│   ├── api.py            # Routes FastAPI & serve des fichiers
│   ├── agent.py          # Logique IA
│   └── gmail_client.py   # Wrapper de l'API Gmail
├── static/
│   ├── index.html        # Structure de l'interface
│   ├── style.css         # Design system
│   └── app.js            # Logique frontend
├── main.py               # Point d'entrée pour démarrer Uvicorn
├── setup_gmail.py        # Script OAuth de première connexion à Gmail
├── .env                  # Variables d'environnement
└── token.json            # Jeton d'accès Gmail généré
```

## Licence
Projet privé / expérimental.

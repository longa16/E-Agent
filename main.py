"""
Point d'entrée principal.
Lance le serveur API Gmail.
"""
import uvicorn

if __name__ == "__main__":
    uvicorn.run("src.api:app", host="0.0.0.0", port=8000, reload=True)

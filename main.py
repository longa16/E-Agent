"""
Point d'entrée principal.
Lance le serveur API Gmail.
"""
import os
import uvicorn

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(
        "src.api:app",
        host="0.0.0.0",
        port=port,
        reload=os.getenv("RAILWAY_ENVIRONMENT") is None,  # reload only in dev
    )

"""
Gestion du contexte conversationnel par utilisateur Discord.
Maintient l'état entre les messages email actif, historique, action en attente.
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class UserContext:
    """État de la conversation pour un utilisateur donné."""

    # Email en cours de consultation
    active_email_id: Optional[str] = None
    active_email_subject: Optional[str] = None
    active_email_sender: Optional[str] = None

    # Action en attente d'une réponse utilisateur
    pending_action: Optional[str] = None

    # Brouillon généré en attente de confirmation
    pending_draft: Optional[str] = None

    # Historique des messages pour le LLM
    history: list[dict] = field(default_factory=list)

    def set_active_email(self, email: dict) -> None:
        self.active_email_id = email["id"]
        self.active_email_subject = email.get("subject", "(sans objet)")
        self.active_email_sender = email.get("sender_email", "")

    def clear_active_email(self) -> None:
        self.active_email_id = None
        self.active_email_subject = None
        self.active_email_sender = None
        self.pending_action = None
        self.pending_draft = None

    def add_to_history(self, role: str, content: str) -> None:
        self.history.append({"role": role, "content": content})
        # Garde les 20 derniers messages pour ne pas dépasser le contexte
        if len(self.history) > 20:
            self.history = self.history[-20:]

    def reset(self) -> None:
        self.history.clear()
        self.clear_active_email()


# Stockage en mémoire : user_id (int) → UserContext
_contexts: dict[int, UserContext] = {}


def get_context(user_id: int) -> UserContext:
    """Retourne le contexte de l'utilisateur, en le créant si nécessaire."""
    if user_id not in _contexts:
        _contexts[user_id] = UserContext()
    return _contexts[user_id]


def clear_context(user_id: int) -> None:
    """Réinitialise complètement le contexte d'un utilisateur."""
    if user_id in _contexts:
        _contexts[user_id].reset()

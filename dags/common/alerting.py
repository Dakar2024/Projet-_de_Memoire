"""Alerte par e-mail à l'échec d'une tâche (SMTP et destinataires lus dans l'environnement)."""
from __future__ import annotations

import os


def alert_args() -> dict:
    """Renvoie les arguments d'alerte d'un DAG : e-mail à l'échec si `ALERT_EMAIL` est défini, jamais aux relances."""
    destinataires = [a.strip() for a in os.environ.get("ALERT_EMAIL", "").split(",") if a.strip()]
    return {
        "email": destinataires,
        "email_on_failure": bool(destinataires),
        "email_on_retry": False,
    }

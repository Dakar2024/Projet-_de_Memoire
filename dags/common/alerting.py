"""Alerte par e-mail à l'échec d'une tâche, via la connection SMTP `smtp_default` (relais Resend)."""
from __future__ import annotations

import os

from airflow.providers.smtp.notifications.smtp import SmtpNotifier

from dags.common.emails import FAILURE_HTML, FAILURE_SUBJECT


def alert_recipients() -> list[str]:
    """Renvoie les destinataires de `ALERT_EMAIL` (séparés par des virgules), vide si non défini."""
    return [a.strip() for a in os.environ.get("ALERT_EMAIL", "").split(",") if a.strip()]


def alert_args() -> dict:
    """Renvoie les arguments d'alerte d'un DAG : e-mail à l'échec définitif si `ALERT_EMAIL` est défini.

    `on_failure_callback` ne part qu'à l'état FAILED, jamais aux relances (UP_FOR_RETRY).
    Remplace `email`/`email_on_failure`, dépréciés depuis Airflow 3 au profit de SmtpNotifier.
    """
    destinataires = alert_recipients()
    if not destinataires:
        return {}
    return {
        "on_failure_callback": SmtpNotifier(
            to=destinataires, subject=FAILURE_SUBJECT, html_content=FAILURE_HTML
        )
    }

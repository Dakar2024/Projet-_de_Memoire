"""Alerte par e-mail à l'échec d'une tâche, via la connection SMTP `smtp_default` (relais Resend)."""
from __future__ import annotations

import os

from airflow.sdk import BaseNotifier
from airflow.sdk.exceptions import AirflowFailException

from dags.common.emails import Failure, failure_email


def alert_recipients() -> list[str]:
    """Renvoie les destinataires de `ALERT_EMAIL` (séparés par des virgules), vide si non défini."""
    return [a.strip() for a in os.environ.get("ALERT_EMAIL", "").split(",") if a.strip()]


class FailureNotifier(BaseNotifier):
    """Envoie l'e-mail d'échec d'une tâche, avec le gabarit des autres e-mails du pipeline."""

    def __init__(self, to: list[str]) -> None:
        super().__init__()
        self.to = to

    def notify(self, context) -> None:
        from dags.common import mailer

        ti = context["ti"]
        exception = context.get("exception")
        dag = context.get("dag")
        failure = Failure(
            dag_id=ti.dag_id,
            dag_description=getattr(dag, "description", None),
            task_id=ti.task_id,
            run_id=ti.run_id,
            try_number=ti.try_number,
            definitive=isinstance(exception, AirflowFailException),
            error=str(exception) if exception else "aucun message (tâche arrêtée ou délai dépassé)",
            log_url=getattr(ti, "log_url", None),
        )
        mailer.send_email(self.to, failure_email(failure))


def alert_args() -> dict:
    """Renvoie les arguments d'alerte d'un DAG : e-mail à l'échec définitif si `ALERT_EMAIL` est défini.

    `on_failure_callback` ne part qu'à l'état FAILED, jamais aux relances (UP_FOR_RETRY).
    Remplace `email`/`email_on_failure`, dépréciés depuis Airflow 3.
    """
    destinataires = alert_recipients()
    if not destinataires:
        return {}
    return {"on_failure_callback": FailureNotifier(to=destinataires)}

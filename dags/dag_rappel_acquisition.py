"""Rappels du run mensuel d'acquisition, à J-2 et le jour J, avec les contrôles à corriger avant."""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from airflow.sdk import DAG, task
from airflow.sdk.exceptions import AirflowSkipException
from airflow.timetables.trigger import MultipleCronTriggerTimetable

from dags.common.alerting import alert_args, alert_recipients
from dags.common.schedule import REMINDER_DAY_OF_CRON, REMINDER_EARLY_CRON

with DAG(
    dag_id="dag_rappel_acquisition",
    description="Rappel du run du 10 à J-2 et le jour J, avec les contrôles préalables",
    schedule=MultipleCronTriggerTimetable(
        REMINDER_EARLY_CRON, REMINDER_DAY_OF_CRON, timezone="UTC"
    ),
    start_date=dt.datetime(2026, 1, 1),
    catchup=False,
    max_active_runs=1,
    # Un échec SMTP passager ne doit pas faire perdre le rappel.
    default_args={**alert_args(), "retries": 2, "retry_delay": dt.timedelta(minutes=10)},
    tags=["maintenance", "alerte"],
) as dag:

    @task(task_id="envoyer_rappel")
    def envoyer_rappel(**context) -> str:
        """Lance les contrôles et envoie le rappel ; renvoie l'état global."""
        from airflow.providers.smtp.hooks.smtp import SmtpHook

        from dags.common import preflight
        from dags.common.emails import reminder_html, reminder_subject
        from ingestion.config import DATA_EXTERNAL_DIR
        from ingestion.maintenance import free_bytes
        from ingestion.storage import layer_reachable

        destinataires = alert_recipients()
        if not destinataires:
            raise AirflowSkipException("ALERT_EMAIL vide : aucun rappel envoyé")

        # Un run manuel n'a pas de date logique en Airflow 3 : on se rabat sur run_after.
        when = context.get("logical_date") or context["dag_run"].run_after
        reminder = preflight.reminder_at(when, preflight.utcnow())
        if reminder is None:
            run_date = preflight.reminder_for(when.date()).run_date.strftime("%d/%m/%Y")
            raise AirflowSkipException(f"rappel périmé : le run du {run_date} a déjà démarré")
        checks = [
            preflight.check_clinvar_archive(
                preflight.probe_clinvar_archive(reminder.archive_version),
                reminder.archive_version,
                reminder.is_run_day,
            ),
            preflight.check_free_space(free_bytes(DATA_EXTERNAL_DIR)),
            preflight.check_lake(layer_reachable("raw")),
        ]
        status = preflight.overall(checks)

        with SmtpHook() as smtp:
            smtp.send_email_smtp(
                to=destinataires,
                subject=reminder_subject(reminder, status),
                html_content=reminder_html(reminder, checks, status),
            )
        return status.value

    envoyer_rappel()

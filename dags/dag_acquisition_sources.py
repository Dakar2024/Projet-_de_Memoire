"""DAG mensuel d'acquisition des sources partagées (ClinVar, HPO) : raw puis bronze."""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from airflow.sdk import DAG, task
from airflow.sdk.exceptions import AirflowFailException, AirflowSkipException

from dags.common.alerting import alert_args, alert_recipients
from dags.common.dates import record_sources_date, require_logical_date, should_acquire
from dags.common.panels import HEAVY_CONVERSION_POOL, SHARED_SOURCES, SOURCES_READY
from dags.common.schedule import ACQUISITION_CRON, catch_up_delay
from ingestion.errors import ConfigurationError, SourceSchemaError
from ingestion.storage import assert_partitions_complete
from scripts.ingest_clinvar import ingest_clinvar
from scripts.ingest_hpo_files import ingest_hpo_files
from transformations.raw_to_bronze import raw_to_bronze

DEFAULT_ARGS = {
    **alert_args(),
    "retries": 3,
    "retry_delay": dt.timedelta(minutes=5),
    "execution_timeout": dt.timedelta(hours=2),
}

with DAG(
    dag_id="dag_acquisition_sources",
    description="Sources communes à tous les panels : dépôt raw puis conversion bronze",
    # Le 10 à 6 h UTC, partagé avec les rappels (dags/common/schedule.py).
    schedule=ACQUISITION_CRON,
    start_date=dt.datetime(2026, 1, 1),
    catchup=False,
    # Deux runs écriraient la même partition `raw` partagée.
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    tags=["raw", "bronze", "acquisition"],
) as dag:

    @task(task_id="resolve_logical_date")
    def resolve_logical_date(**context) -> str:
        """Renvoie la date de travail, ou échoue sans relance si elle manque."""
        try:
            return require_logical_date(context.get("ds"))
        except ConfigurationError as exc:
            raise AirflowFailException(str(exc)) from exc

    # Un mois déjà publié ne déclenche pas une seconde fois les panels (cas du 21/10 : sortie de pause
    # puis Trigger manuel). Faux : toute la suite est sautée, donc aucun événement d'Asset.
    @task.short_circuit(task_id="skip_if_already_published", inlets=[SOURCES_READY])
    def skip_if_already_published(acquisition_date: str, **context) -> bool:
        """Laisse passer un mois jamais publié, ou un rejeu `--conf '{"force": true}'`."""
        dag_run = context.get("dag_run")
        return should_acquire(
            context["inlet_events"], SOURCES_READY, acquisition_date, dag_run.conf if dag_run else None
        )

    # Hors du chemin des données : un échec SMTP ne retarde pas l'acquisition.
    @task(task_id="notify_catch_up")
    def notify_catch_up(**context) -> None:
        """Prévient par e-mail qu'un run planifié rattrape une échéance manquée (machine éteinte le 10)."""
        from airflow.providers.smtp.hooks.smtp import SmtpHook

        from dags.common import preflight
        from dags.common.emails import catch_up_html, catch_up_subject

        # Valeur de `DagRunType.SCHEDULED`, que `airflow.sdk` n'expose qu'au typage.
        if context["dag_run"].run_type != "scheduled":
            raise AirflowSkipException("run manuel : pas de rattrapage à signaler")
        scheduled, started = context["logical_date"], preflight.utcnow()
        if catch_up_delay(scheduled, started) is None:
            raise AirflowSkipException("run parti à l'heure")
        destinataires = alert_recipients()
        if not destinataires:
            raise AirflowSkipException("ALERT_EMAIL vide : aucun avis de rattrapage envoyé")
        with SmtpHook() as smtp:
            smtp.send_email_smtp(
                to=destinataires,
                subject=catch_up_subject(scheduled),
                html_content=catch_up_html(scheduled, started),
            )

    # `acquisition_date` et non `logical_date`, clé de contexte réservée par Airflow.
    @task(task_id="download_clinvar_bulk")
    def download_clinvar_bulk(acquisition_date: str) -> str:
        return ingest_clinvar(acquisition_date)

    @task(task_id="download_hpo_files")
    def download_hpo_files(acquisition_date: str) -> str:
        return ingest_hpo_files(acquisition_date)

    @task(task_id="check_raw_shared")
    def check_raw_shared(clinvar_partition: str, hpo_partition: str) -> None:
        assert_partitions_complete([clinvar_partition, hpo_partition])

    @task(task_id="raw_to_bronze_shared", pool=HEAVY_CONVERSION_POOL)
    def raw_to_bronze_shared(acquisition_date: str) -> list[str]:
        try:
            return raw_to_bronze(acquisition_date, SHARED_SOURCES)
        except SourceSchemaError as exc:
            # Une relance relirait le même fichier : échec définitif, message de la source conservé.
            raise AirflowFailException(str(exc)) from exc

    @task(task_id="check_bronze_shared", outlets=[SOURCES_READY])
    def check_bronze_shared(bronze_partitions: list[str], acquisition_date: str, **context) -> None:
        assert_partitions_complete(bronze_partitions)
        # Les DAGs de panel relisent cette date dans l'événement d'Asset.
        record_sources_date(context["outlet_events"], SOURCES_READY, acquisition_date)

    acquisition_date = resolve_logical_date()
    guard = skip_if_already_published(acquisition_date)
    guard >> notify_catch_up()
    clinvar, hpo = download_clinvar_bulk(acquisition_date), download_hpo_files(acquisition_date)
    guard >> [clinvar, hpo]
    checked_raw = check_raw_shared(clinvar, hpo)
    bronze = raw_to_bronze_shared(acquisition_date)
    checked_raw >> bronze
    check_bronze_shared(bronze, acquisition_date)

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO_ROOT / "src"), str(REPO_ROOT)]

from airflow.sdk import DAG, task
from airflow.sdk.exceptions import AirflowFailException

from dags.common.dates import record_sources_date, require_logical_date
from dags.common.panels import SHARED_SOURCES, SOURCES_READY
from ingestion.errors import ConfigurationError
from ingestion.storage import assert_partitions_complete
from scripts.ingest_clinvar import ingest_clinvar
from scripts.ingest_hpo_files import ingest_hpo_files
from transformations.raw_to_bronze import raw_to_bronze

DEFAULT_ARGS = {
    "retries": 3,
    "retry_delay": dt.timedelta(minutes=5),
    "execution_timeout": dt.timedelta(hours=2),
}

with DAG(
    dag_id="dag_acquisition_sources",
    description="Sources communes à tous les panels : dépôt raw puis conversion bronze",
    # Le 10 à 06:00 UTC, pas le 1er : l'archive mensuelle ClinVar paraît entre le 2 et
    # le 6 du mois (Last-Modified observés : 06-04, 07-02, 08-06, 09-03). Un run le 1er
    # la trouverait absente. La date de travail est ramenée au 1er du mois.
    schedule="0 6 10 * *",
    start_date=dt.datetime(2026, 1, 1),
    catchup=False,
    default_args=DEFAULT_ARGS,
    tags=["raw", "bronze", "acquisition"],
) as dag:

    @task(task_id="resolve_logical_date")
    def resolve_logical_date(**context) -> str:
        try:
            return require_logical_date(context.get("ds"))
        except ConfigurationError as exc:
            raise AirflowFailException(str(exc)) from exc

    # Le paramètre ne s'appelle pas `logical_date` : c'est une clé de contexte réservée
    # par Airflow (auto-injectée), et un paramètre TaskFlow de ce nom entre en collision
    # avec elle (`ValueError: The key 'logical_date' in args is ... reserved`, vérifié en
    # exécution réelle). `dag_genomic_pipeline.py` n'a pas ce problème : il utilise déjà
    # `sources_date` pour la même donnée.
    @task(task_id="download_clinvar_bulk")
    def download_clinvar_bulk(acquisition_date: str) -> str:
        return ingest_clinvar(acquisition_date)

    @task(task_id="download_hpo_files")
    def download_hpo_files(acquisition_date: str) -> str:
        return ingest_hpo_files(acquisition_date)

    @task(task_id="check_raw_shared")
    def check_raw_shared(clinvar_partition: str, hpo_partition: str) -> None:
        assert_partitions_complete([clinvar_partition, hpo_partition])

    @task(task_id="raw_to_bronze_shared")
    def raw_to_bronze_shared(acquisition_date: str) -> list[str]:
        return raw_to_bronze(acquisition_date, SHARED_SOURCES)

    @task(task_id="check_bronze_shared", outlets=[SOURCES_READY])
    def check_bronze_shared(bronze_partitions: list[str], acquisition_date: str, **context) -> None:
        assert_partitions_complete(bronze_partitions)
        # Les DAGs de panel sont déclenchés sans date logique : ils relisent celle-ci
        # dans l'événement d'Asset pour travailler sur les mêmes partitions.
        record_sources_date(context["outlet_events"], SOURCES_READY, acquisition_date)

    acquisition_date = resolve_logical_date()
    checked_raw = check_raw_shared(
        download_clinvar_bulk(acquisition_date), download_hpo_files(acquisition_date)
    )
    bronze = raw_to_bronze_shared(acquisition_date)
    checked_raw >> bronze
    check_bronze_shared(bronze, acquisition_date)

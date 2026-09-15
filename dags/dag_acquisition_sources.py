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
    schedule="@monthly",
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

    @task(task_id="download_clinvar_bulk")
    def download_clinvar_bulk(logical_date: str) -> str:
        return ingest_clinvar(logical_date)

    @task(task_id="download_hpo_files")
    def download_hpo_files(logical_date: str) -> str:
        return ingest_hpo_files(logical_date)

    @task(task_id="check_raw_shared")
    def check_raw_shared(clinvar_partition: str, hpo_partition: str) -> None:
        assert_partitions_complete([clinvar_partition, hpo_partition])

    @task(task_id="raw_to_bronze_shared")
    def raw_to_bronze_shared(logical_date: str) -> list[str]:
        return raw_to_bronze(logical_date, SHARED_SOURCES)

    @task(task_id="check_bronze_shared", outlets=[SOURCES_READY])
    def check_bronze_shared(bronze_partitions: list[str], logical_date: str, **context) -> None:
        assert_partitions_complete(bronze_partitions)
        # Les DAGs de panel sont déclenchés sans date logique : ils relisent celle-ci
        # dans l'événement d'Asset pour travailler sur les mêmes partitions.
        record_sources_date(context["outlet_events"], SOURCES_READY, logical_date)

    logical_date = resolve_logical_date()
    checked_raw = check_raw_shared(
        download_clinvar_bulk(logical_date), download_hpo_files(logical_date)
    )
    bronze = raw_to_bronze_shared(logical_date)
    checked_raw >> bronze
    check_bronze_shared(bronze, logical_date)

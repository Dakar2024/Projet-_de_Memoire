from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO_ROOT / "src"), str(REPO_ROOT)]

from airflow.sdk import DAG, task
from airflow.sdk.exceptions import AirflowFailException

from dags.common.dates import resolve_sources_date
from dags.common.panels import (
    NCBI_POOL,
    PANEL_LABELS,
    PANEL_SOURCES,
    PANELS,
    SILVER_WRITE_POOL,
    SOURCES_READY,
)
from ingestion.errors import ConfigurationError
from ingestion.http_client import NcbiClient
from ingestion.storage import assert_partitions_complete
from scripts.ingest_hpo_terms import ingest_hpo_terms
from scripts.ingest_medgen import ingest_medgen
from scripts.ingest_ncbi_gene import build_client, ingest_ncbi_gene
from scripts.ingest_refseq import ingest_refseq
from transformations.bronze_to_silver import bronze_to_silver
from transformations.quality_check_silver import quality_check_silver
from transformations.raw_to_bronze import raw_to_bronze
from transformations.silver_to_gold_analytique import silver_to_gold_analytique
from transformations.silver_to_gold_rag import silver_to_gold_rag

DEFAULT_ARGS = {
    "retries": 3,
    "retry_delay": dt.timedelta(minutes=5),
    "execution_timeout": dt.timedelta(hours=3),
}


def client_or_fail() -> NcbiClient:
    """Construit le client NCBI, ou échoue définitivement.

    Une configuration manquante ne se résout pas en réessayant : `AirflowFailException`
    marque la tâche en échec sans consommer les retries.
    """
    try:
        return build_client()
    except ConfigurationError as exc:
        raise AirflowFailException(str(exc)) from exc


def build_panel_dag(panel: str, genes: list[str]) -> DAG:
    """Construit le DAG médaillon d'un panel de gènes, déclenché par l'Asset
    publié quand le bronze des sources partagées est complet."""
    with DAG(
        dag_id=f"dag_genomic_pipeline_{panel}",
        description=f"Pipeline médaillon — {PANEL_LABELS.get(panel, panel)}",
        schedule=[SOURCES_READY],
        start_date=dt.datetime(2026, 1, 1),
        catchup=False,
        default_args=DEFAULT_ARGS,
        tags=["medaillon", panel],
    ) as dag:

        @task(task_id="resolve_sources_date")
        def task_resolve_sources_date(**context) -> str:
            """Date des sources partagées : relue dans l'événement d'Asset, ou fournie
            par `--conf` lors d'un déclenchement manuel. Un run de panel n'a pas de date
            logique propre dans Airflow 3."""
            dag_run = context.get("dag_run")
            try:
                return resolve_sources_date(
                    context.get("triggering_asset_events"),
                    SOURCES_READY,
                    dag_run.conf if dag_run else None,
                )
            except ConfigurationError as exc:
                raise AirflowFailException(str(exc)) from exc

        # Les trois ingestions NCBI passent par un pool à un slot : le limiteur de débit
        # est par processus, il ne protège pas contre des tâches parallèles. Les termes
        # HPO interrogent ontology.jax.org et restent hors du pool.
        @task(task_id="ingest_ncbi_gene", pool=NCBI_POOL)
        def task_ncbi_gene(sources_date: str) -> str:
            return ingest_ncbi_gene(sources_date, panel, genes, client_or_fail())

        @task(task_id="ingest_refseq", pool=NCBI_POOL)
        def task_refseq(sources_date: str) -> str:
            return ingest_refseq(sources_date, panel, genes, client_or_fail())

        @task(task_id="ingest_hpo_terms")
        def task_hpo_terms(sources_date: str) -> str:
            return ingest_hpo_terms(sources_date, panel, genes)

        @task(task_id="ingest_medgen", pool=NCBI_POOL)
        def task_medgen(sources_date: str) -> str:
            return ingest_medgen(sources_date, panel, genes, client_or_fail())

        @task(task_id="check_raw")
        def task_check_raw(
            ncbi_gene_partition: str,
            refseq_partition: str,
            hpo_terms_partition: str,
            medgen_partition: str,
        ) -> None:
            assert_partitions_complete([
                ncbi_gene_partition,
                refseq_partition,
                hpo_terms_partition,
                medgen_partition,
            ])

        @task(task_id="raw_to_bronze")
        def task_raw_to_bronze(sources_date: str) -> list[str]:
            return raw_to_bronze(sources_date, PANEL_SOURCES, panel=panel)

        @task(task_id="check_bronze")
        def task_check_bronze(bronze_partitions: list[str]) -> None:
            assert_partitions_complete(bronze_partitions)

        @task(task_id="bronze_to_silver", pool=SILVER_WRITE_POOL)
        def task_bronze_to_silver(sources_date: str) -> None:
            bronze_to_silver(sources_date, panel)

        @task(task_id="quality_check_silver")
        def task_quality_check_silver(sources_date: str) -> None:
            quality_check_silver(sources_date, panel)

        @task(task_id="silver_to_gold_rag")
        def task_silver_to_gold_rag(sources_date: str) -> None:
            silver_to_gold_rag(sources_date, panel)

        @task(task_id="silver_to_gold_analytique")
        def task_silver_to_gold_analytique(sources_date: str) -> None:
            silver_to_gold_analytique(sources_date, panel)

        sources_date = task_resolve_sources_date()
        checked_raw = task_check_raw(
            task_ncbi_gene(sources_date),
            task_refseq(sources_date),
            task_hpo_terms(sources_date),
            task_medgen(sources_date),
        )
        bronze = task_raw_to_bronze(sources_date)
        checked_raw >> bronze
        checked_bronze = task_check_bronze(bronze)
        silver = task_bronze_to_silver(sources_date)
        quality = task_quality_check_silver(sources_date)
        checked_bronze >> silver >> quality >> [
            task_silver_to_gold_rag(sources_date),
            task_silver_to_gold_analytique(sources_date),
        ]

    return dag


dag_genomic_pipeline_brca = build_panel_dag("brca", PANELS["brca"])
dag_genomic_pipeline_sickle = build_panel_dag("sickle", PANELS["sickle"])

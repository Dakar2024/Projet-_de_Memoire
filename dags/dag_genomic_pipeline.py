from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO_ROOT / "src"), str(REPO_ROOT)]

from airflow.sdk import DAG, task
from airflow.sdk.exceptions import AirflowFailException

from dags.common.panels import PANEL_LABELS, PANEL_SOURCES, PANELS, SOURCES_READY
from ingestion.errors import ConfigurationError
from ingestion.http_client import NcbiClient
from ingestion.storage import assert_partitions_complete
from scripts.ingest_hpo_terms import ingest_hpo_terms
from scripts.ingest_medgen import ingest_medgen
from scripts.ingest_ncbi_gene import build_client, ingest_ncbi_gene
from scripts.ingest_refseq import ingest_refseq
from transformations.bronze_to_silver import bronze_to_silver
from transformations import SPEC
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

        @task(task_id="ingest_ncbi_gene")
        def task_ncbi_gene(**context) -> str:
            return ingest_ncbi_gene(context["ds"], panel, genes, client_or_fail())

        @task(task_id="ingest_refseq")
        def task_refseq(**context) -> str:
            return ingest_refseq(context["ds"], panel, genes, client_or_fail())

        @task(task_id="ingest_hpo_terms")
        def task_hpo_terms(**context) -> str:
            return ingest_hpo_terms(context["ds"], panel, genes)

        @task(task_id="ingest_medgen")
        def task_medgen(**context) -> str:
            return ingest_medgen(context["ds"], panel, genes, client_or_fail())

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
        def task_raw_to_bronze(**context) -> list[str]:
            return raw_to_bronze(context["ds"], PANEL_SOURCES, panel=panel)

        @task(task_id="check_bronze")
        def task_check_bronze(bronze_partitions: list[str]) -> None:
            assert_partitions_complete(bronze_partitions)

        @task(task_id="bronze_to_silver")
        def task_bronze_to_silver(**context) -> None:
            bronze_to_silver(context["ds"], panel)

        @task(task_id="quality_check_silver")
        def task_quality_check_silver(**context) -> None:
            raise NotImplementedError(
                f"quality_check_silver : implémenté par le sous-projet C ({SPEC}, §7)"
            )

        @task(task_id="silver_to_gold_rag")
        def task_silver_to_gold_rag(**context) -> None:
            silver_to_gold_rag(context["ds"], panel)

        @task(task_id="silver_to_gold_analytique")
        def task_silver_to_gold_analytique(**context) -> None:
            silver_to_gold_analytique(context["ds"], panel)

        checked_raw = task_check_raw(
            task_ncbi_gene(), task_refseq(), task_hpo_terms(), task_medgen()
        )
        bronze = task_raw_to_bronze()
        checked_raw >> bronze
        checked_bronze = task_check_bronze(bronze)
        silver = task_bronze_to_silver()
        quality = task_quality_check_silver()
        checked_bronze >> silver >> quality >> [
            task_silver_to_gold_rag(),
            task_silver_to_gold_analytique(),
        ]

    return dag


dag_genomic_pipeline_brca = build_panel_dag("brca", PANELS["brca"])
dag_genomic_pipeline_sickle = build_panel_dag("sickle", PANELS["sickle"])

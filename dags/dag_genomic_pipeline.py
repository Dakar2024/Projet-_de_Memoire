"""DAG médaillon d'un panel : raw → bronze → silver → gold, puis indexation RAG."""
from __future__ import annotations

import dataclasses
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from airflow.sdk import DAG, task
from airflow.sdk.exceptions import AirflowFailException, AirflowSkipException

from dags.common.alerting import alert_args, alert_recipients
from dags.common.dates import resolve_sources_date
from dags.common.panels import (
    HEAVY_CONVERSION_POOL,
    NCBI_POOL,
    PANEL_LABELS,
    PANEL_SOURCES,
    PANELS,
    RAG_INDEX_POOL,
    SHARED_SOURCES,
    SOURCES_READY,
)
from ingestion.config import BRONZE
from ingestion.errors import ConfigurationError, OutOfOrderMonthError
from ingestion.http_client import NcbiClient
from ingestion.storage import IncompletePartitionError, assert_partitions_complete, partition_uri
from scripts.ingest_hpo_terms import ingest_hpo_terms
from scripts.ingest_medgen import ingest_medgen
from scripts.ingest_ncbi_gene import build_client, ingest_ncbi_gene
from scripts.ingest_refseq import ingest_refseq
from transformations.bronze_to_silver import bronze_to_silver
from transformations.delta_maintenance import vacuum_delta_tables
from transformations.quality_check_gold import quality_check_gold
from transformations.quality_check_silver import quality_check_silver
from transformations.raw_to_bronze import raw_to_bronze
from transformations.silver_to_gold_analytique import silver_to_gold_analytique
from transformations.silver_to_gold_rag import silver_to_gold_rag

DEFAULT_ARGS = {
    **alert_args(),
    "retries": 3,
    "retry_delay": dt.timedelta(minutes=5),
    "execution_timeout": dt.timedelta(hours=3),
}


# Tâches les plus longues citées par l'e-mail de succès.
SUCCESS_LONGEST_TASKS = 3


def client_or_fail() -> NcbiClient:
    """Construit le client NCBI, ou fait échouer la tâche sans relance si la configuration manque."""
    try:
        return build_client()
    except ConfigurationError as exc:
        raise AirflowFailException(str(exc)) from exc


def build_panel_dag(panel: str, genes: list[str]) -> DAG:
    """Construit le DAG médaillon d'un panel, déclenché par l'Asset des sources partagées."""
    with DAG(
        dag_id=f"dag_genomic_pipeline_{panel}",
        description=f"Pipeline médaillon — {PANEL_LABELS.get(panel, panel)}",
        schedule=[SOURCES_READY],
        start_date=dt.datetime(2026, 1, 1),
        catchup=False,
        # Deux runs du même panel écriraient la même partition `raw`.
        max_active_runs=1,
        default_args=DEFAULT_ARGS,
        tags=["medaillon", panel],
    ) as dag:

        @task(task_id="resolve_sources_date")
        def task_resolve_sources_date(**context) -> str:
            """Renvoie la date des sources (événement d'Asset ou `--conf`, mois en cours) une fois
            vérifié que l'acquisition de ce mois a publié son bronze partagé."""
            dag_run = context["dag_run"]
            try:
                sources_date = resolve_sources_date(
                    context.get("triggering_asset_events"),
                    SOURCES_READY,
                    dag_run.conf,
                    started_at=dag_run.start_date,
                )
            except ConfigurationError as exc:
                raise AirflowFailException(str(exc)) from exc
            # D-E3b-2 : sans ce contrôle, un mois sans acquisition échouait sur un `NoSuchKey`
            # brut dans bronze_to_silver, après trois relances et toutes les ingestions NCBI.
            try:
                assert_partitions_complete(
                    [partition_uri(BRONZE, source, sources_date) for source in SHARED_SOURCES]
                )
            except IncompletePartitionError as exc:
                raise AirflowFailException(
                    f"{exc} — lancer d'abord dag_acquisition_sources pour ce mois"
                ) from exc
            return sources_date

        # Les ingestions NCBI passent par le pool à un slot ; HPO (ontology.jax.org) reste hors pool.
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

        @task(task_id="raw_to_bronze", pool=HEAVY_CONVERSION_POOL)
        def task_raw_to_bronze(sources_date: str) -> list[str]:
            return raw_to_bronze(sources_date, PANEL_SOURCES, panel=panel)

        @task(task_id="check_bronze")
        def task_check_bronze(bronze_partitions: list[str]) -> None:
            assert_partitions_complete(bronze_partitions)

        @task(task_id="bronze_to_silver", pool=HEAVY_CONVERSION_POOL)
        def task_bronze_to_silver(sources_date: str) -> None:
            try:
                bronze_to_silver(sources_date, panel)
            except OutOfOrderMonthError as exc:
                # Une relance lirait le même historique : échec définitif, avec la marche à suivre.
                raise AirflowFailException(str(exc)) from exc

        @task(task_id="quality_check_silver")
        def task_quality_check_silver(sources_date: str) -> None:
            quality_check_silver(sources_date, panel)

        @task(task_id="silver_to_gold_rag", pool=HEAVY_CONVERSION_POOL)
        def task_silver_to_gold_rag(sources_date: str) -> None:
            silver_to_gold_rag(sources_date, panel)

        @task(task_id="silver_to_gold_analytique", pool=HEAVY_CONVERSION_POOL)
        def task_silver_to_gold_analytique(sources_date: str) -> None:
            silver_to_gold_analytique(sources_date, panel)

        @task(task_id="quality_check_gold")
        def task_quality_check_gold(sources_date: str) -> None:
            quality_check_gold(sources_date, panel)

        # Tables partagées entre panels : une écriture à la fois, comme les conversions.
        @task(task_id="vacuum_delta_tables", pool=HEAVY_CONVERSION_POOL)
        def task_vacuum_delta_tables() -> None:
            vacuum_delta_tables()

        # Réindexation complète ~4 h sur CPU : délai de 6 h ; erreurs permanentes sans relance.
        @task(
            task_id="index_rag_documents",
            pool=RAG_INDEX_POOL,
            execution_timeout=dt.timedelta(hours=6),
        )
        def task_index_rag_documents() -> dict:
            """Indexe le Gold du panel et renvoie le bilan, repris par l'e-mail de succès."""
            # Import ici : une dépendance RAG manquante ne casse que cette tâche, pas l'analyse de tous les DAGs.
            from RAG.src.ingestion.indexer import run_index
            from RAG.src.utils.errors import RagPermanentError

            try:
                return dataclasses.asdict(run_index(panel))
            except RagPermanentError as exc:
                raise AirflowFailException(str(exc)) from exc

        # Dernière tâche : ne part que si tout le reste a réussi, y compris après une relance.
        @task(task_id="notify_run_success")
        def task_notify_run_success(sources_date: str, index_report: dict | None, **context) -> None:
            """Envoie l'e-mail de succès du run : chaque mois, un succès ou un échec, jamais de silence."""
            from dags.common import mailer, preflight
            from dags.common.emails import RunSuccess, success_email

            destinataires = alert_recipients()
            if not destinataires:
                raise AirflowSkipException("ALERT_EMAIL vide : aucun e-mail de succès envoyé")
            ti, dag_run = context["ti"], context["dag_run"]
            durations = [
                (crumb["task_id"], crumb["duration"])
                for crumb in ti.get_task_breadcrumbs(ti.dag_id, ti.run_id)
                if crumb.get("duration")
            ]
            success = RunSuccess(
                dag_id=ti.dag_id,
                dag_description=getattr(context.get("dag"), "description", None),
                run_id=ti.run_id,
                month=sources_date,
                started=dag_run.start_date,
                ended=preflight.utcnow(),
                clear_number=dag_run.clear_number,
                index=index_report,
                longest=sorted(durations, key=lambda d: d[1], reverse=True)[:SUCCESS_LONGEST_TASKS],
                # Lien du run, tiré de celui du journal : même base d'URL que les e-mails d'échec.
                run_url=ti.log_url.split("/tasks/")[0] if getattr(ti, "log_url", None) else None,
            )
            mailer.send_email(destinataires, success_email(success))

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
        gold_rag = task_silver_to_gold_rag(sources_date)
        gold_analytique = task_silver_to_gold_analytique(sources_date)
        checked_bronze >> silver >> quality >> [gold_rag, gold_analytique]
        checked_gold = task_quality_check_gold(sources_date)
        [gold_rag, gold_analytique] >> checked_gold
        index_report = task_index_rag_documents()
        vacuum = task_vacuum_delta_tables()
        checked_gold >> [index_report, vacuum]
        vacuum >> task_notify_run_success(sources_date, index_report)

    return dag


dag_genomic_pipeline_brca = build_panel_dag("brca", PANELS["brca"])
dag_genomic_pipeline_sickle = build_panel_dag("sickle", PANELS["sickle"])

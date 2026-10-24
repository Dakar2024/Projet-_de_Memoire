import datetime as dt
from types import SimpleNamespace

import pytest

from dags.common.panels import (
    HEAVY_CONVERSION_POOL,
    NCBI_POOL,
    RAG_INDEX_POOL,
    SOURCES_READY,
)
from dags.dag_genomic_pipeline import build_panel_dag

INGESTIONS = {"ingest_ncbi_gene", "ingest_refseq", "ingest_hpo_terms", "ingest_medgen"}


@pytest.fixture
def dag():
    return build_panel_dag("brca", ["BRCA1", "BRCA2"])


def test_panel_dag_is_triggered_by_the_shared_sources_asset(dag):
    assert dag.schedule == [SOURCES_READY]
    assert dag.catchup is False


def test_panel_dag_allows_a_single_active_run(dag):
    """Deux runs du même panel écriraient la même partition `raw` (P5)."""
    assert dag.max_active_runs == 1


def test_panel_dag_has_the_expected_tasks(dag):
    assert sorted(t.task_id for t in dag.tasks) == sorted(INGESTIONS | {
        "resolve_sources_date",
        "check_raw",
        "raw_to_bronze",
        "check_bronze",
        "bronze_to_silver",
        "quality_check_silver",
        "silver_to_gold_rag",
        "silver_to_gold_analytique",
        "quality_check_gold",
        "index_rag_documents",
        "vacuum_delta_tables",
        "notify_run_success",
    })


def test_the_four_ingestions_run_in_parallel_on_the_resolved_sources_date(dag):
    """MedGen et les termes HPO lisent les partitions raw partagées : ils doivent
    utiliser la date de l'acquisition, résolue une fois, et non une date propre au run."""
    for task_id in INGESTIONS:
        assert dag.get_task(task_id).upstream_task_ids == {"resolve_sources_date"}


def test_check_raw_waits_for_all_four_ingestions(dag):
    assert dag.get_task("check_raw").upstream_task_ids == INGESTIONS


def test_the_layers_are_strictly_sequential(dag):
    assert dag.get_task("raw_to_bronze").upstream_task_ids == {"check_raw", "resolve_sources_date"}
    assert dag.get_task("check_bronze").upstream_task_ids == {"raw_to_bronze"}
    assert dag.get_task("bronze_to_silver").upstream_task_ids == {"check_bronze", "resolve_sources_date"}
    assert dag.get_task("quality_check_silver").upstream_task_ids == {"bronze_to_silver", "resolve_sources_date"}


def test_the_two_gold_outputs_read_silver_not_each_other(dag):
    assert dag.get_task("silver_to_gold_rag").upstream_task_ids == {
        "quality_check_silver",
        "resolve_sources_date",
    }
    assert dag.get_task("silver_to_gold_analytique").upstream_task_ids == {
        "quality_check_silver",
        "resolve_sources_date",
    }


def test_ncbi_ingestions_share_a_single_slot_pool(dag):
    """Le limiteur de débit NCBI est par processus : deux panels en parallèle
    dépasseraient la limite globale. Le pool sérialise les tâches E-utilities ;
    les termes HPO interrogent ontology.jax.org et n'y ont pas leur place."""
    assert NCBI_POOL == "ncbi"
    for task_id in ("ingest_ncbi_gene", "ingest_refseq", "ingest_medgen"):
        assert dag.get_task(task_id).pool == NCBI_POOL
    assert dag.get_task("ingest_hpo_terms").pool != NCBI_POOL


def test_heavy_conversions_share_a_single_slot_pool(dag):
    """Conversion ClinVar ≈ 2 Go, bronze_to_silver 1,37 Go, sous un plafond de 3 Go (P7) :
    un pool unique les sérialise entre panels, et garde la sérialisation des écritures
    Delta partagées (Silver et Gold) qu'assuraient silver_write et gold_write."""
    assert HEAVY_CONVERSION_POOL == "conversion_lourde"
    for task_id in ("raw_to_bronze", "bronze_to_silver", "silver_to_gold_rag", "silver_to_gold_analytique"):
        assert dag.get_task(task_id).pool == HEAVY_CONVERSION_POOL


def test_quality_check_gold_runs_after_both_gold_tasks(dag):
    upstream = dag.get_task("quality_check_gold").upstream_task_ids

    assert upstream == {
        "resolve_sources_date",
        "silver_to_gold_rag",
        "silver_to_gold_analytique",
    }


def test_transient_failures_are_retried(dag):
    assert dag.get_task("ingest_ncbi_gene").retries == 3


def test_configuration_errors_fail_without_consuming_retries(monkeypatch):
    """Une configuration manquante est permanente : AirflowFailException échoue la
    tâche immédiatement, sans passer par les trois retries."""
    from airflow.sdk.exceptions import AirflowFailException

    from dags import dag_genomic_pipeline
    from ingestion.errors import ConfigurationError

    def refuser():
        raise ConfigurationError("NCBI_EMAIL manquant")

    monkeypatch.setattr(dag_genomic_pipeline, "build_client", refuser)

    with pytest.raises(AirflowFailException, match="NCBI_EMAIL"):
        dag_genomic_pipeline.client_or_fail()


def test_both_panel_dags_are_exposed_at_module_level():
    from dags import dag_genomic_pipeline

    assert dag_genomic_pipeline.dag_genomic_pipeline_brca.dag_id == "dag_genomic_pipeline_brca"
    assert dag_genomic_pipeline.dag_genomic_pipeline_sickle.dag_id == "dag_genomic_pipeline_sickle"


NOW = dt.datetime(2026, 10, 24, 15, tzinfo=dt.UTC)


@pytest.fixture
def shared_bronze(monkeypatch):
    """Remplace le contrôle des partitions partagées : enregistre les partitions demandées."""
    from dags import dag_genomic_pipeline

    checked = []
    monkeypatch.setenv("LAKE_URI", "s3://")
    monkeypatch.setattr(dag_genomic_pipeline, "assert_partitions_complete", checked.extend)
    return checked


def _resolve(dag, conf):
    dag_run = SimpleNamespace(conf=conf, start_date=NOW)
    return dag.get_task("resolve_sources_date").python_callable(dag_run=dag_run)


def test_a_manual_run_without_sources_date_fails_with_instructions(dag, shared_bronze):
    """Un run de panel n'a pas de date logique dans Airflow 3. Sans événement d'Asset ni
    `--conf`, la résolution échoue définitivement en disant comment relancer."""
    from airflow.sdk.exceptions import AirflowFailException

    with pytest.raises(AirflowFailException, match="--conf"):
        _resolve(dag, conf=None)


def test_a_manual_run_on_a_past_month_fails_without_consuming_retries(dag, shared_bronze):
    from airflow.sdk.exceptions import AirflowFailException

    with pytest.raises(AirflowFailException, match="mois en cours"):
        _resolve(dag, conf={"sources_date": "2026-09-01"})


def test_the_shared_sources_of_the_month_are_checked_before_any_ingestion(dag, shared_bronze):
    """D-E3b-2 : sans ce contrôle, un mois sans acquisition échouait plus loin sur un
    `NoSuchKey` brut, relancé trois fois."""
    assert _resolve(dag, conf={"sources_date": "2026-10-01"}) == "2026-10-01"
    assert shared_bronze == [
        "s3://bronze/clinvar/dt=2026-10-01",
        "s3://bronze/hpo/dt=2026-10-01",
    ]


def test_missing_shared_sources_fail_without_consuming_retries(dag, monkeypatch):
    from airflow.sdk.exceptions import AirflowFailException

    from dags import dag_genomic_pipeline
    from ingestion.storage import IncompletePartitionError

    def absent(partitions):
        raise IncompletePartitionError("partitions incomplètes ou vides : s3://bronze/clinvar/dt=2026-10-01")

    monkeypatch.setattr(dag_genomic_pipeline, "assert_partitions_complete", absent)

    with pytest.raises(AirflowFailException, match="dag_acquisition_sources"):
        _resolve(dag, conf={"sources_date": "2026-10-01"})


def test_the_success_email_is_the_last_task_after_the_index_and_the_vacuum(dag):
    """Envoyé seulement si tout le reste a réussi (règle par défaut `all_success`)."""
    task = dag.get_task("notify_run_success")

    assert task.upstream_task_ids == {
        "index_rag_documents", "vacuum_delta_tables", "resolve_sources_date",
    }
    assert task.downstream_task_ids == set()
    assert task.trigger_rule == "all_success"


def _notify_success(dag, clear_number=0):
    ti = SimpleNamespace(
        dag_id="dag_genomic_pipeline_brca", run_id="manual__2026-10-24",
        log_url="http://localhost:8080/dags/dag_genomic_pipeline_brca/runs/manual__2026-10-24/tasks/notify_run_success?try_number=1",
        get_task_breadcrumbs=lambda dag_id, run_id: [
            {"task_id": "ingest_medgen", "duration": 260.0},
            {"task_id": "bronze_to_silver", "duration": 8.0},
            {"task_id": "check_raw", "duration": None},
        ],
    )
    dag_run = SimpleNamespace(start_date=NOW, clear_number=clear_number)
    report = {"panel": "brca", "embedded": 2, "deleted": 0, "unchanged": 10, "canary_cosine": 1.0}
    return dag.get_task("notify_run_success").python_callable(
        "2026-10-01", report, ti=ti, dag_run=dag_run, dag=dag,
    )


def test_a_successful_run_sends_the_success_email(dag, smtp_outbox):
    _notify_success(dag)

    assert smtp_outbox[0]["to"] == ["alerte@example.test"]
    assert smtp_outbox[0]["subject"] == "[genomique] Succès dag_genomic_pipeline_brca — 10/2026"
    text = smtp_outbox[0]["email"].text
    assert "ingest_medgen" in text
    assert "2 vectorisés" in text
    assert "http://localhost:8080/dags/dag_genomic_pipeline_brca/runs/manual__2026-10-24" in text
    assert "/tasks/" not in text


def test_a_relaunched_run_sends_a_success_after_relaunch(dag, smtp_outbox):
    _notify_success(dag, clear_number=1)

    assert smtp_outbox[0]["subject"].endswith("après relance")


def test_no_recipient_sends_no_success_email(dag, smtp_outbox, monkeypatch):
    from airflow.sdk.exceptions import AirflowSkipException

    monkeypatch.setenv("ALERT_EMAIL", "")

    with pytest.raises(AirflowSkipException, match="ALERT_EMAIL"):
        _notify_success(dag)
    assert smtp_outbox == []


def test_the_index_task_returns_its_report_for_the_success_email(dag, monkeypatch):
    from RAG.src.ingestion import indexer
    from RAG.src.ingestion.indexer import IndexReport

    monkeypatch.setattr(indexer, "run_index", lambda panel: IndexReport(panel, 1, 2, 3, 0.99))

    assert dag.get_task("index_rag_documents").python_callable() == {
        "panel": "brca", "deleted": 1, "embedded": 2, "unchanged": 3, "canary_cosine": 0.99,
    }


def test_task_failures_are_emailed(dag):
    """Un pipeline mensuel sans surveillance : sans alerte, un échec ne se voit que
    si quelqu'un ouvre l'interface. Le destinataire vient de l'environnement pour
    ne pas figer une adresse dans le dépôt."""
    from dags.common.alerting import FailureNotifier

    notifier = dag.default_args["on_failure_callback"]

    assert isinstance(notifier, FailureNotifier)
    assert notifier.to == ["alerte@example.test"]
    assert "on_retry_callback" not in dag.default_args


def test_rag_indexing_runs_last_on_checked_gold_only(dag):
    """On n'indexe que des documents contrôlés : jamais avant quality_check_gold. Seul le mail
    de succès vient après."""
    assert dag.get_task("index_rag_documents").upstream_task_ids == {"quality_check_gold"}
    assert dag.get_task("index_rag_documents").downstream_task_ids == {"notify_run_success"}


def test_rag_indexing_is_serialised_and_has_room_for_a_full_cpu_run(dag):
    """Une réindexation complète sur CPU dure ~4 h (mesure du 30/09/2026) : le délai
    de 3 h des autres tâches la couperait. Le pool évite deux indexations en
    parallèle sur un service d'embedding qui sature déjà le processeur."""
    task = dag.get_task("index_rag_documents")
    assert RAG_INDEX_POOL == "rag_index"
    assert task.pool == RAG_INDEX_POOL
    assert task.execution_timeout == dt.timedelta(hours=6)


def test_permanent_rag_errors_fail_without_consuming_retries(dag, monkeypatch):
    from airflow.sdk.exceptions import AirflowFailException

    from RAG.src.ingestion import indexer
    from RAG.src.utils.errors import CanaryMismatchError

    def refuser(panel):
        raise CanaryMismatchError("le service ne sert pas le modèle attendu")

    monkeypatch.setattr(indexer, "run_index", refuser)

    with pytest.raises(AirflowFailException, match="modèle attendu"):
        dag.get_task("index_rag_documents").python_callable()


def test_transient_rag_errors_are_left_to_the_retries(dag, monkeypatch):
    from RAG.src.ingestion import indexer
    from RAG.src.utils.errors import EmbeddingServiceError

    def indisponible(panel):
        raise EmbeddingServiceError("503")

    monkeypatch.setattr(indexer, "run_index", indisponible)

    with pytest.raises(EmbeddingServiceError):
        dag.get_task("index_rag_documents").python_callable()


def test_panel_dag_parses_without_the_rag_dependencies():
    """Une dépendance RAG manquante ne doit casser que la tâche d'indexation, pas l'analyse des DAGs."""
    import subprocess
    import sys

    code = (
        "import sys; sys.modules['RAG.src.ingestion.indexer'] = None; "
        "sys.modules['RAG.src.utils.errors'] = None; "
        "from dags.dag_genomic_pipeline import build_panel_dag; build_panel_dag('brca', ['BRCA1'])"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr[-500:]


def test_delta_vacuum_runs_after_gold_is_checked_in_the_heavy_pool(dag):
    """VACUUM touche les tables partagées entre panels : après le contrôle Gold, une écriture à la fois."""
    task = dag.get_task("vacuum_delta_tables")
    assert task.upstream_task_ids == {"quality_check_gold"}
    assert task.pool == HEAVY_CONVERSION_POOL


def test_an_out_of_order_month_fails_without_consuming_retries(monkeypatch):
    """Un mois antérieur à l'historique Silver le restera à chaque relance : échec définitif, message conservé."""
    from airflow.sdk.exceptions import AirflowFailException

    from dags import dag_genomic_pipeline
    from ingestion.errors import OutOfOrderMonthError

    def out_of_order(sources_date, panel):
        raise OutOfOrderMonthError("clinvar_variant (brca) contient déjà le mois 2026-12-01")

    monkeypatch.setattr(dag_genomic_pipeline, "bronze_to_silver", out_of_order)
    dag = build_panel_dag("brca", ["BRCA1", "BRCA2"])

    with pytest.raises(AirflowFailException, match="2026-12-01"):
        dag.get_task("bronze_to_silver").python_callable("2026-11-01")

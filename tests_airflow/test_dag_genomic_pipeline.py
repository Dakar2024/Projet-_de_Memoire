import pytest

from dags.common.panels import GOLD_WRITE_POOL, NCBI_POOL, SILVER_WRITE_POOL, SOURCES_READY
from dags.dag_genomic_pipeline import build_panel_dag

INGESTIONS = {"ingest_ncbi_gene", "ingest_refseq", "ingest_hpo_terms", "ingest_medgen"}


@pytest.fixture
def dag():
    return build_panel_dag("brca", ["BRCA1", "BRCA2"])


def test_panel_dag_is_triggered_by_the_shared_sources_asset(dag):
    assert dag.schedule == [SOURCES_READY]
    assert dag.catchup is False


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


def test_bronze_to_silver_uses_a_single_slot_pool(dag):
    """Les neuf tables Silver sont partagées entre les deux panels ; ce pool sérialise
    bronze_to_silver pour empêcher une création de table Delta concurrente entre les
    deux DAGs de panel, déclenchés sur le même Asset SOURCES_READY."""
    assert SILVER_WRITE_POOL == "silver_write"
    assert dag.get_task("bronze_to_silver").pool == SILVER_WRITE_POOL


def test_gold_tasks_share_a_single_slot_pool(dag):
    """Les tables Gold sont partagées entre les deux panels, dont les runs se
    chevauchent : sans ce pool, deux écritures concurrentes sur la même table Delta
    peuvent se perdre."""
    for task_id in ("silver_to_gold_rag", "silver_to_gold_analytique"):
        assert dag.get_task(task_id).pool == GOLD_WRITE_POOL


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


def test_a_manual_run_without_sources_date_fails_with_instructions(dag):
    """Un run de panel n'a pas de date logique dans Airflow 3. Sans événement d'Asset ni
    `--conf`, la résolution échoue définitivement en disant comment relancer."""
    from airflow.sdk.exceptions import AirflowFailException

    with pytest.raises(AirflowFailException, match="--conf"):
        dag.get_task("resolve_sources_date").python_callable()

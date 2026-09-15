import pytest

from dags.common.panels import SOURCES_READY
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
        "check_raw",
        "raw_to_bronze",
        "check_bronze",
        "bronze_to_silver",
        "quality_check_silver",
        "silver_to_gold_rag",
        "silver_to_gold_analytique",
    })


def test_the_four_ingestions_run_in_parallel(dag):
    """MedGen dépend du bulk ClinVar brut, mais celui-ci est déposé par le DAG
    d'acquisition, qui a terminé avant de publier l'Asset."""
    for task_id in INGESTIONS:
        assert dag.get_task(task_id).upstream_task_ids == set()


def test_check_raw_waits_for_all_four_ingestions(dag):
    assert dag.get_task("check_raw").upstream_task_ids == INGESTIONS


def test_the_layers_are_strictly_sequential(dag):
    assert dag.get_task("raw_to_bronze").upstream_task_ids == {"check_raw"}
    assert dag.get_task("check_bronze").upstream_task_ids == {"raw_to_bronze"}
    assert dag.get_task("bronze_to_silver").upstream_task_ids == {"check_bronze"}
    assert dag.get_task("quality_check_silver").upstream_task_ids == {"bronze_to_silver"}


def test_the_two_gold_outputs_read_silver_not_each_other(dag):
    assert dag.get_task("silver_to_gold_rag").upstream_task_ids == {"quality_check_silver"}
    assert dag.get_task("silver_to_gold_analytique").upstream_task_ids == {"quality_check_silver"}


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

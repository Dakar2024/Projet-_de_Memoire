from dags.common.panels import SOURCES_READY
from dags.dag_acquisition_sources import dag


def test_acquisition_dag_runs_monthly_without_catchup():
    assert dag.schedule == "@monthly"
    assert dag.catchup is False


def test_acquisition_dag_has_the_expected_tasks():
    assert sorted(t.task_id for t in dag.tasks) == [
        "check_bronze_shared",
        "check_raw_shared",
        "download_clinvar_bulk",
        "download_hpo_files",
        "raw_to_bronze_shared",
    ]


def test_both_downloads_run_in_parallel_then_gate_on_check_raw():
    assert dag.get_task("download_clinvar_bulk").upstream_task_ids == set()
    assert dag.get_task("download_hpo_files").upstream_task_ids == set()
    assert dag.get_task("check_raw_shared").upstream_task_ids == {
        "download_clinvar_bulk",
        "download_hpo_files",
    }


def test_bronze_conversion_is_gated_on_both_sides():
    assert dag.get_task("raw_to_bronze_shared").upstream_task_ids == {"check_raw_shared"}
    assert dag.get_task("check_bronze_shared").upstream_task_ids == {"raw_to_bronze_shared"}


def test_the_asset_is_published_only_once_bronze_is_complete():
    """Les DAGs de panel lisent le bronze des sources partagées : les déclencher
    après check_raw les ferait démarrer avant que ce bronze existe."""
    assert SOURCES_READY in dag.get_task("check_bronze_shared").outlets
    assert SOURCES_READY not in dag.get_task("check_raw_shared").outlets

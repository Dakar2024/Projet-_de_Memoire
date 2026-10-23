import datetime as dt
from types import SimpleNamespace

import pytest
from airflow.sdk.exceptions import AirflowFailException, AirflowSkipException

from dags.common.panels import HEAVY_CONVERSION_POOL, SOURCES_READY
from dags.dag_acquisition_sources import dag


def test_acquisition_dag_runs_monthly_after_the_clinvar_archive_is_published():
    """L'archive ClinVar du mois paraît entre le 2 et le 6 : un run le 1er la
    trouverait absente."""
    assert dag.schedule == "0 6 10 * *"
    assert dag.catchup is False


def test_acquisition_dag_allows_a_single_active_run():
    """Deux runs écriraient la même partition `raw` partagée (P5)."""
    assert dag.max_active_runs == 1


def test_clinvar_conversion_shares_the_heavy_conversion_pool():
    """La conversion du bulk ClinVar (≈ 2 Go) ne doit pas croiser une conversion de panel (P7)."""
    assert dag.get_task("raw_to_bronze_shared").pool == HEAVY_CONVERSION_POOL


def test_acquisition_dag_has_the_expected_tasks():
    assert sorted(t.task_id for t in dag.tasks) == [
        "check_bronze_shared",
        "check_raw_shared",
        "download_clinvar_bulk",
        "download_hpo_files",
        "notify_catch_up",
        "raw_to_bronze_shared",
        "resolve_logical_date",
        "skip_if_already_published",
    ]


def test_both_downloads_run_in_parallel_then_gate_on_check_raw():
    for task_id in ("download_clinvar_bulk", "download_hpo_files"):
        assert dag.get_task(task_id).upstream_task_ids == {
            "resolve_logical_date",
            "skip_if_already_published",
        }
    assert dag.get_task("check_raw_shared").upstream_task_ids == {
        "download_clinvar_bulk",
        "download_hpo_files",
    }


def test_bronze_conversion_is_gated_on_both_sides():
    assert dag.get_task("raw_to_bronze_shared").upstream_task_ids == {
        "check_raw_shared",
        "resolve_logical_date",
    }
    assert dag.get_task("check_bronze_shared").upstream_task_ids == {
        "raw_to_bronze_shared",
        "resolve_logical_date",
    }


def test_the_asset_is_published_only_once_bronze_is_complete():
    """Les DAGs de panel lisent le bronze des sources partagées : les déclencher
    après check_raw les ferait démarrer avant que ce bronze existe."""
    assert SOURCES_READY in dag.get_task("check_bronze_shared").outlets
    assert SOURCES_READY not in dag.get_task("check_raw_shared").outlets


def test_a_manual_run_without_logical_date_fails_with_instructions():
    """Dans Airflow 3, un run manuel sans --logical-date n'a pas de `ds` : la résolution
    échoue définitivement, sans consommer les retries, en disant comment relancer."""
    with pytest.raises(AirflowFailException, match="--logical-date"):
        dag.get_task("resolve_logical_date").python_callable()


def test_a_changed_source_schema_fails_without_consuming_retries(monkeypatch):
    """Une relance relirait le même fichier : l'erreur de schéma est définitive (P13)."""
    from dags import dag_acquisition_sources
    from ingestion.errors import SourceSchemaError

    def schema_change(logical_date, sources):
        raise SourceSchemaError("clinvar : colonnes manquantes ['GeneSymbol']")

    monkeypatch.setattr(dag_acquisition_sources, "raw_to_bronze", schema_change)

    with pytest.raises(AirflowFailException, match="GeneSymbol"):
        dag.get_task("raw_to_bronze_shared").python_callable("2026-09-10")


UTC = dt.UTC
SCHEDULED = dt.datetime(2026, 11, 10, 6, tzinfo=UTC)


class FakeInletEvents:
    """Imite `inlet_events` : indexé par Asset, renvoie l'historique de ses événements."""

    def __init__(self, *sources_dates):
        self._events = [SimpleNamespace(extra={"sources_date": d}) for d in sources_dates]

    def __getitem__(self, asset):
        assert asset == SOURCES_READY
        return self._events


def _guard(*published, conf=None):
    context = {"inlet_events": FakeInletEvents(*published), "dag_run": SimpleNamespace(conf=conf)}
    return dag.get_task("skip_if_already_published").python_callable("2026-10-01", **context)


def test_the_guard_runs_before_any_download_and_reads_the_asset_history():
    guard = dag.get_task("skip_if_already_published")

    assert guard.upstream_task_ids == {"resolve_logical_date"}
    assert SOURCES_READY in guard.inlets
    assert guard.ignore_downstream_trigger_rules is True


def test_the_guard_lets_an_unpublished_month_through():
    assert _guard("2026-09-01") is True


def test_the_guard_stops_a_second_acquisition_of_the_same_month():
    """Cas du 21/10 : deux runs d'octobre publiaient deux événements, donc deux runs par panel."""
    assert _guard("2026-10-01") is False


def test_the_guard_lets_a_forced_reacquisition_through():
    assert _guard("2026-10-01", conf={"force": True}) is True


def test_the_catch_up_notice_follows_the_guard_without_blocking_the_downloads():
    """Un mois déjà publié ne doit pas annoncer de rattrapage ; un échec SMTP ne doit pas bloquer les données."""
    assert dag.get_task("notify_catch_up").upstream_task_ids == {"skip_if_already_published"}
    assert dag.get_task("notify_catch_up").downstream_task_ids == set()


@pytest.fixture
def clock(monkeypatch):
    from dags.common import preflight

    frozen = {}
    monkeypatch.setattr(preflight, "utcnow", lambda: frozen["now"])
    return frozen


def _notify(clock, now, run_type="scheduled"):
    clock["now"] = now
    context = {"logical_date": SCHEDULED, "dag_run": SimpleNamespace(run_type=run_type)}
    dag.get_task("notify_catch_up").python_callable(**context)


def test_a_late_scheduled_run_sends_a_catch_up_notice(smtp_outbox, clock):
    _notify(clock, dt.datetime(2026, 11, 15, 9, 12, tzinfo=UTC))

    assert smtp_outbox[0]["to"] == ["alerte@example.test"]
    assert smtp_outbox[0]["subject"] == "[genomique] Rattrapage : run du 10/11/2026 lancé en retard"


def test_an_on_time_scheduled_run_sends_nothing(smtp_outbox, clock):
    with pytest.raises(AirflowSkipException, match="à l'heure"):
        _notify(clock, SCHEDULED + dt.timedelta(minutes=2))
    assert smtp_outbox == []


def test_a_manual_run_is_never_a_catch_up(smtp_outbox, clock):
    """Un rejeu manuel porte une date logique passée (--logical-date) : ce n'est pas un retard."""
    with pytest.raises(AirflowSkipException, match="manuel"):
        _notify(clock, dt.datetime(2026, 11, 15, tzinfo=UTC), run_type="manual")
    assert smtp_outbox == []


def test_no_recipient_sends_no_catch_up_notice(smtp_outbox, clock, monkeypatch):
    monkeypatch.setenv("ALERT_EMAIL", "")

    with pytest.raises(AirflowSkipException, match="ALERT_EMAIL"):
        _notify(clock, dt.datetime(2026, 11, 15, tzinfo=UTC))
    assert smtp_outbox == []

import datetime as dt
from types import SimpleNamespace

import pytest

from dags.common.preflight import Status
from dags.common.schedule import ACQUISITION_CRON
from dags.dag_acquisition_sources import dag as acquisition_dag
from dags.dag_rappel_acquisition import dag

UTC = dt.UTC


def _next_runs(timetable, after: dt.datetime, count: int) -> list[dt.datetime]:
    from airflow.timetables.base import TimeRestriction

    runs, last = [], None
    restriction = TimeRestriction(earliest=after, latest=None, catchup=True)
    for _ in range(count):
        info = timetable.next_dagrun_info(last_automated_data_interval=last, restriction=restriction)
        runs.append(info.run_after)
        last = info.data_interval
    return runs


def test_reminders_fire_two_days_before_and_one_hour_before_the_run():
    runs = _next_runs(dag.timetable, dt.datetime(2026, 11, 1, tzinfo=UTC), 2)

    assert runs == [
        dt.datetime(2026, 11, 8, 8, tzinfo=UTC),
        dt.datetime(2026, 11, 10, 5, tzinfo=UTC),
    ]


def test_acquisition_runs_on_the_shared_schedule():
    """Rappels et run lisent le même calendrier : ils ne peuvent pas se décaler."""
    assert acquisition_dag.schedule == ACQUISITION_CRON == "0 6 10 * *"


@pytest.fixture
def sent(monkeypatch):
    """Remplace les sondes et le SMTP : capture les mails au lieu de les envoyer."""
    import airflow.providers.smtp.hooks.smtp as smtp_module

    from dags.common import preflight
    from ingestion import maintenance, storage

    mails = []

    class FakeSmtpHook:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def send_email_smtp(self, **kwargs):
            mails.append(kwargs)

    monkeypatch.setattr(smtp_module, "SmtpHook", FakeSmtpHook)
    monkeypatch.setattr(preflight, "probe_clinvar_archive", lambda version: 404)
    monkeypatch.setattr(maintenance, "free_bytes", lambda path: 50 * 1024**3)
    monkeypatch.setattr(storage, "layer_reachable", lambda layer: True)
    return mails


@pytest.fixture
def clock(monkeypatch):
    """Fige l'heure vue par le rappel ; par défaut, l'heure de l'échéance (envoi à l'heure)."""
    from dags.common import preflight

    frozen = {}
    monkeypatch.setattr(preflight, "utcnow", lambda: frozen["now"])
    return frozen


def _run(logical_date, clock, now=None):
    clock["now"] = now or logical_date
    context = {"logical_date": logical_date, "dag_run": SimpleNamespace(run_after=logical_date)}
    return dag.get_task("envoyer_rappel").python_callable(**context)


def test_early_reminder_flags_a_missing_archive_as_a_warning(sent, clock):
    status = _run(dt.datetime(2026, 11, 8, 8, tzinfo=UTC), clock)

    assert status == Status.WARNING.value
    assert sent[0]["to"] == ["alerte@example.test"]
    assert sent[0]["subject"].startswith("[genomique] J-2 : run du 10/11/2026")


def test_run_day_reminder_flags_a_missing_archive_as_blocking(sent, clock):
    assert _run(dt.datetime(2026, 11, 10, 5, tzinfo=UTC), clock) == Status.BLOCKING.value
    assert "Jour J" in sent[0]["subject"]


def test_manual_run_without_logical_date_falls_back_to_run_after(sent, clock):
    clock["now"] = dt.datetime(2026, 11, 8, tzinfo=UTC)
    context = {"logical_date": None, "dag_run": SimpleNamespace(run_after=dt.datetime(2026, 11, 8, tzinfo=UTC))}

    dag.get_task("envoyer_rappel").python_callable(**context)

    assert "J-2" in sent[0]["subject"]


def test_no_recipient_skips_without_sending(sent, clock, monkeypatch):
    from airflow.sdk.exceptions import AirflowSkipException

    monkeypatch.setenv("ALERT_EMAIL", "")

    with pytest.raises(AirflowSkipException):
        _run(dt.datetime(2026, 11, 8, 8, tzinfo=UTC), clock)
    assert sent == []


def test_stale_reminder_replayed_by_airflow_is_skipped(sent, clock):
    """Cas du 21/10 : la sortie de pause a rejoué l'échéance du 10/10, déjà passée."""
    from airflow.sdk.exceptions import AirflowSkipException

    with pytest.raises(AirflowSkipException, match="périmé"):
        _run(dt.datetime(2026, 10, 10, 5, tzinfo=UTC), clock, now=dt.datetime(2026, 10, 21, 13, 39, tzinfo=UTC))
    assert sent == []


def test_late_reminder_is_sent_with_the_actual_countdown(sent, clock):
    _run(dt.datetime(2026, 11, 8, 8, tzinfo=UTC), clock, now=dt.datetime(2026, 11, 9, 7, tzinfo=UTC))

    assert sent[0]["subject"].startswith("[genomique] J-1 : run du 10/11/2026")

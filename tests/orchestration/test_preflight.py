import datetime as dt

import pytest
import requests
import responses

from dags.common import preflight
from dags.common.preflight import Check, Status
from ingestion.clinvar import archive_url_for

GIO = 1024**3


@pytest.mark.parametrize(
    ("today", "run_date", "label"),
    [
        (dt.date(2026, 11, 8), dt.date(2026, 11, 10), "J-2"),
        (dt.date(2026, 11, 10), dt.date(2026, 11, 10), "Jour J"),
        # Après le run du mois, le rappel vise celui du mois suivant (cas d'un run manuel).
        (dt.date(2026, 10, 21), dt.date(2026, 11, 10), "J-20"),
        (dt.date(2026, 12, 21), dt.date(2027, 1, 10), "J-20"),
    ],
)
def test_reminder_targets_the_next_acquisition_run(today, run_date, label):
    reminder = preflight.reminder_for(today)

    assert reminder.run_date == run_date
    assert reminder.label == label
    assert reminder.archive_version == run_date.strftime("%Y-%m")


@pytest.mark.parametrize(
    ("http_status", "is_run_day", "expected"),
    [
        (200, False, Status.OK),
        (200, True, Status.OK),
        # Deux jours avant, NCBI peut encore publier ; le jour J, le run échouera.
        (404, False, Status.WARNING),
        (404, True, Status.BLOCKING),
        (None, True, Status.WARNING),
        (503, False, Status.WARNING),
    ],
)
def test_clinvar_archive_check(http_status, is_run_day, expected):
    assert preflight.check_clinvar_archive(http_status, "2026-11", is_run_day).status is expected


@responses.activate
def test_probe_returns_the_http_status_of_the_monthly_archive():
    responses.head(archive_url_for("2026-11-01"), status=404)

    assert preflight.probe_clinvar_archive("2026-11") == 404


@responses.activate
def test_probe_returns_none_when_ncbi_is_unreachable():
    responses.head(archive_url_for("2026-11-01"), body=requests.ConnectionError("down"))

    assert preflight.probe_clinvar_archive("2026-11") is None


@pytest.mark.parametrize(
    ("free", "expected"),
    [(50 * GIO, Status.OK), (8 * GIO, Status.WARNING), (1 * GIO, Status.BLOCKING)],
)
def test_free_space_warns_early_and_blocks_below_the_run_floor(free, expected):
    """Le seuil bloquant reprend celui sous lequel `ensure_free_space` refuse le run."""
    assert preflight.check_free_space(free).status is expected


def test_lake_check():
    assert preflight.check_lake(True).status is Status.OK
    assert preflight.check_lake(False).status is Status.BLOCKING


def test_overall_status_is_the_most_severe():
    checks = [Check("a", Status.OK, ""), Check("b", Status.BLOCKING, ""), Check("c", Status.WARNING, "")]

    assert preflight.overall(checks) is Status.BLOCKING
    assert preflight.overall([]) is Status.OK


def _utc(*args):
    return dt.datetime(*args, tzinfo=dt.UTC)


@pytest.mark.parametrize(
    ("scheduled", "now", "label"),
    [
        (_utc(2026, 11, 8, 8), _utc(2026, 11, 8, 8, 1), "J-2"),
        (_utc(2026, 11, 10, 5), _utc(2026, 11, 10, 5, 1), "Jour J"),
        # Machine rallumée le 9 : le rappel du 8 part, avec le bon décompte.
        (_utc(2026, 11, 8, 8), _utc(2026, 11, 9, 7), "J-1"),
    ],
)
def test_reminder_counts_days_from_the_actual_send_time(scheduled, now, label):
    reminder = preflight.reminder_at(scheduled, now)

    assert reminder.run_date == dt.date(2026, 11, 10)
    assert reminder.label == label


@pytest.mark.parametrize(
    "now",
    [
        # Cas réel du 21/10 : sortie de pause, Airflow rejoue l'échéance du 10/10 à 05:00.
        _utc(2026, 10, 21, 13, 39),
        # Run déjà démarré le jour même.
        _utc(2026, 10, 10, 6),
    ],
)
def test_reminder_is_stale_once_its_run_has_started(now):
    assert preflight.reminder_at(_utc(2026, 10, 10, 5), now) is None

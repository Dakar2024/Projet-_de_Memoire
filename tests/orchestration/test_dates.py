import datetime as dt
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from dags.common.dates import (
    acquisition_month,
    record_sources_date,
    resolve_sources_date,
    should_acquire,
)
from ingestion.errors import ConfigurationError

ASSET = "s3://bronze/_sources_pretes"


class FakeEvents:
    """Imite l'accesseur `triggering_asset_events` : indexé par Asset, liste d'événements."""

    def __init__(self, events):
        self._events = events

    def __getitem__(self, asset):
        return self._events


def _event(sources_date, minute):
    return SimpleNamespace(
        timestamp=dt.datetime(2026, 9, 15, 12, minute, tzinfo=dt.UTC),
        extra={"sources_date": sources_date},
    )


def _utc(*args):
    return dt.datetime(*args, tzinfo=dt.UTC)


def test_scheduled_run_takes_the_month_it_runs_in_not_its_tick():
    """Pile activée le 4 décembre : Airflow crée le run de l'échéance du 10 novembre, mais seul
    le mois en cours est ingéré, jamais un mois passé."""
    month = acquisition_month(_utc(2026, 12, 4, 9), ds="2026-11-10", scheduled=True)

    assert month == "2026-12-01"


def test_scheduled_run_on_the_10th_takes_its_own_month():
    assert acquisition_month(_utc(2026, 12, 10, 6), ds="2026-12-10", scheduled=True) == "2026-12-01"


def test_manual_run_without_date_takes_the_current_month():
    """Airflow 3 ne donne pas de `ds` à un Trigger manuel sans --logical-date."""
    assert acquisition_month(_utc(2026, 10, 24, 15), ds=None, scheduled=False) == "2026-10-01"


@pytest.mark.parametrize("ds", ["2026-10-01", "2026-10-31"])
def test_manual_run_accepts_any_day_of_the_current_month(ds):
    assert acquisition_month(_utc(2026, 10, 24, 15), ds=ds, scheduled=False) == "2026-10-01"


@pytest.mark.parametrize("ds", ["2026-09-10", "2026-11-10", "2025-10-10"])
def test_manual_run_refuses_a_month_other_than_the_current_one(ds):
    """Un mois passé n'est jamais rejoué ; un mois futur n'a pas encore de sources."""
    with pytest.raises(ConfigurationError, match="mois en cours"):
        acquisition_month(_utc(2026, 10, 24, 15), ds=ds, scheduled=False)


@pytest.mark.parametrize("malformed", ["2026/10/10", "2026-10", "10-10-2026"])
def test_manual_run_rejects_a_malformed_date(malformed):
    with pytest.raises(ConfigurationError, match="AAAA-MM-JJ"):
        acquisition_month(_utc(2026, 10, 24, 15), ds=malformed, scheduled=False)


def test_the_month_is_read_in_utc():
    """Les partitions `dt=` suivent l'UTC, comme les échéances : 00:30 à Paris le 1er décembre
    est encore le 30 novembre."""
    paris = dt.timezone(dt.timedelta(hours=1))
    started = dt.datetime(2026, 12, 1, 0, 30, tzinfo=paris)

    assert acquisition_month(started, ds=None, scheduled=False) == "2026-11-01"


def test_dates_module_does_not_import_polars():
    """Le dag-processor importe ce module à chaque parsing de DAG : il ne doit pas
    tirer `ingestion.clinvar`, qui importe polars."""
    code = (
        "import sys, dags.common.dates; "
        "print('polars' in sys.modules or 'ingestion.clinvar' in sys.modules)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True,
        cwd=Path(__file__).resolve().parents[2], env={"PYTHONPATH": "src:."},
    )
    assert result.stdout.strip() == "False"


def test_record_sources_date_writes_into_the_asset_event_extra():
    outlet_events = {ASSET: SimpleNamespace(extra={})}

    record_sources_date(outlet_events, ASSET, "2026-09-01")

    assert outlet_events[ASSET].extra == {"sources_date": "2026-09-01"}


NOW = _utc(2026, 10, 24, 15)


def test_resolve_sources_date_takes_the_most_recent_event_whatever_the_order():
    """Plusieurs acquisitions depuis le dernier run de panel : la plus récente gagne."""
    events = FakeEvents([_event("2026-09-01", 5), _event("2026-08-01", 1)])

    assert resolve_sources_date(events, ASSET, conf=None, started_at=NOW) == "2026-09-01"


def test_resolve_sources_date_falls_back_to_the_run_conf_when_manual():
    conf = {"sources_date": "2026-10-01"}

    assert resolve_sources_date(FakeEvents([]), ASSET, conf, started_at=NOW) == "2026-10-01"


def test_resolve_sources_date_normalises_a_manual_date_to_the_month():
    """Les partitions partagées sont mensuelles : un jour quelconque saisi à la main
    doit viser `dt=AAAA-MM-01`, pas une partition qui n'existe pas."""
    conf = {"sources_date": "2026-10-15"}

    assert resolve_sources_date(FakeEvents([]), ASSET, conf, started_at=NOW) == "2026-10-01"


@pytest.mark.parametrize("sources_date", ["2026-09-01", "2026-11-01"])
def test_resolve_sources_date_refuses_a_manual_month_other_than_the_current_one(sources_date):
    """Un panel lancé à la main ne rejoue pas un mois passé, même si ses sources sont au lac."""
    with pytest.raises(ConfigurationError, match="mois en cours"):
        resolve_sources_date(FakeEvents([]), ASSET, {"sources_date": sources_date}, started_at=NOW)


@pytest.mark.parametrize("conf", [None, {}, {"sources_date": "2026/10/01"}])
def test_resolve_sources_date_explains_how_to_trigger_manually(conf):
    with pytest.raises(ConfigurationError, match="--conf"):
        resolve_sources_date(FakeEvents([]), ASSET, conf, started_at=NOW)


def test_should_acquire_a_month_never_published():
    assert should_acquire(FakeEvents([]), ASSET, "2026-10-01", conf=None, scheduled=False) is True


def test_should_acquire_a_month_other_than_the_published_ones():
    """Le run du 10/11 suit celui d'octobre : un mois déjà publié ne bloque que lui-même."""
    events = FakeEvents([_event("2026-10-01", 1)])

    assert should_acquire(events, ASSET, "2026-11-01", conf=None, scheduled=False) is True


def test_manual_run_does_not_acquire_a_month_already_published():
    """Cas du 21/10 : la sortie de pause avait déjà publié octobre, le Trigger manuel l'a republié."""
    events = FakeEvents([_event("2026-09-01", 1), _event("2026-10-01", 2)])

    assert should_acquire(events, ASSET, "2026-10-01", conf=None, scheduled=False) is False


def test_should_acquire_a_published_month_again_when_forced():
    """Réacquérir un mois après une correction reste possible, mais seulement sur demande explicite."""
    events = FakeEvents([_event("2026-10-01", 1)])

    assert should_acquire(events, ASSET, "2026-10-01", conf={"force": True}, scheduled=False) is True


@pytest.mark.parametrize("conf", [{"force": "true"}, {"force": 1}, {"force": False}])
def test_only_a_boolean_true_forces_the_acquisition(conf):
    """`--conf '{"force": "false"}'` ne doit pas forcer par simple vérité de la chaîne."""
    events = FakeEvents([_event("2026-10-01", 1)])

    assert should_acquire(events, ASSET, "2026-10-01", conf, scheduled=False) is False


def test_scheduled_run_acquires_a_month_already_published():
    """Pile activée le 4 décembre puis échéance du 10 : le run du 10 relit les sources du mois
    pour prendre ce qui a changé depuis (NCBI Gene, RefSeq, MedGen sont interrogés en direct)."""
    events = FakeEvents([_event("2026-12-01", 1)])

    assert should_acquire(events, ASSET, "2026-12-01", conf=None, scheduled=True) is True

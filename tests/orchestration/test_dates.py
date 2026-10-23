import datetime as dt
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from dags.common.dates import (
    record_sources_date,
    require_logical_date,
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
        timestamp=dt.datetime(2026, 9, 15, 12, minute, tzinfo=dt.timezone.utc),
        extra={"sources_date": sources_date},
    )


def test_require_logical_date_returns_the_scheduled_date():
    assert require_logical_date("2026-09-01") == "2026-09-01"


@pytest.mark.parametrize("ds", ["2026-09-10", "2026-09-30"])
def test_require_logical_date_normalises_to_the_first_day_of_the_month(ds):
    """Un run planifié le 10 et un rejeu manuel du même mois doivent écrire la même
    partition `dt=` : la version des sources ne dépend que du mois."""
    assert require_logical_date(ds) == "2026-09-01"


@pytest.mark.parametrize("malformed", ["2026/09/10", "2026-09", "10-09-2026"])
def test_require_logical_date_rejects_a_malformed_date(malformed):
    with pytest.raises(ConfigurationError, match="AAAA-MM-JJ"):
        require_logical_date(malformed)


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


@pytest.mark.parametrize("absent", [None, ""])
def test_require_logical_date_explains_how_to_trigger_manually(absent):
    """Un run manuel sans --logical-date n'a pas de `ds` dans Airflow 3 : l'erreur doit
    dire comment relancer, pas lever un KeyError."""
    with pytest.raises(ConfigurationError, match="--logical-date"):
        require_logical_date(absent)


def test_record_sources_date_writes_into_the_asset_event_extra():
    outlet_events = {ASSET: SimpleNamespace(extra={})}

    record_sources_date(outlet_events, ASSET, "2026-09-01")

    assert outlet_events[ASSET].extra == {"sources_date": "2026-09-01"}


def test_resolve_sources_date_takes_the_most_recent_event_whatever_the_order():
    """Plusieurs acquisitions depuis le dernier run de panel : la plus récente gagne."""
    events = FakeEvents([_event("2026-09-01", 5), _event("2026-08-01", 1)])

    assert resolve_sources_date(events, ASSET, conf=None) == "2026-09-01"


def test_resolve_sources_date_falls_back_to_the_run_conf_when_manual():
    assert resolve_sources_date(FakeEvents([]), ASSET, {"sources_date": "2026-08-01"}) == "2026-08-01"


def test_resolve_sources_date_normalises_a_manual_date_to_the_month():
    """Les partitions partagées sont mensuelles : un jour quelconque saisi à la main
    doit viser `dt=AAAA-MM-01`, pas une partition qui n'existe pas."""
    assert resolve_sources_date(FakeEvents([]), ASSET, {"sources_date": "2026-08-15"}) == "2026-08-01"


@pytest.mark.parametrize("conf", [None, {}, {"sources_date": "2026/08/01"}])
def test_resolve_sources_date_explains_how_to_trigger_manually(conf):
    with pytest.raises(ConfigurationError, match="--conf"):
        resolve_sources_date(FakeEvents([]), ASSET, conf)


def test_should_acquire_a_month_never_published():
    assert should_acquire(FakeEvents([]), ASSET, "2026-10-01", conf=None) is True


def test_should_acquire_a_month_other_than_the_published_ones():
    """Le run du 10/11 suit celui d'octobre : un mois déjà publié ne bloque que lui-même."""
    events = FakeEvents([_event("2026-10-01", 1)])

    assert should_acquire(events, ASSET, "2026-11-01", conf=None) is True


def test_should_not_acquire_a_month_already_published():
    """Cas du 21/10 : la sortie de pause avait déjà publié octobre, le Trigger manuel l'a republié."""
    events = FakeEvents([_event("2026-09-01", 1), _event("2026-10-01", 2)])

    assert should_acquire(events, ASSET, "2026-10-01", conf=None) is False


def test_should_acquire_a_published_month_again_when_forced():
    """Réacquérir un mois après une correction reste possible, mais seulement sur demande explicite."""
    events = FakeEvents([_event("2026-10-01", 1)])

    assert should_acquire(events, ASSET, "2026-10-01", conf={"force": True}) is True


@pytest.mark.parametrize("conf", [{"force": "true"}, {"force": 1}, {"force": False}])
def test_only_a_boolean_true_forces_the_acquisition(conf):
    """`--conf '{"force": "false"}'` ne doit pas forcer par simple vérité de la chaîne."""
    events = FakeEvents([_event("2026-10-01", 1)])

    assert should_acquire(events, ASSET, "2026-10-01", conf) is False

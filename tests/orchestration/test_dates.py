import datetime as dt
from types import SimpleNamespace

import pytest

from dags.common.dates import record_sources_date, require_logical_date, resolve_sources_date
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


@pytest.mark.parametrize("conf", [None, {}, {"sources_date": "2026/08/01"}])
def test_resolve_sources_date_explains_how_to_trigger_manually(conf):
    with pytest.raises(ConfigurationError, match="--conf"):
        resolve_sources_date(FakeEvents([]), ASSET, conf)

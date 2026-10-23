"""Date de travail des DAGs, résolue explicitement (Airflow 3 n'en donne qu'aux runs planifiés)."""
from __future__ import annotations

from typing import Any

from ingestion.config import LOGICAL_DATE_PATTERN
from ingestion.errors import ConfigurationError

SOURCES_DATE_KEY = "sources_date"
FORCE_KEY = "force"


def require_logical_date(ds: str | None) -> str:
    """Valide la date du DAG d'acquisition et la ramène au premier du mois (partition `dt=AAAA-MM-01`)."""
    if not ds:
        raise ConfigurationError(
            "date logique absente : un run manuel du DAG d'acquisition doit être "
            "déclenché avec --logical-date AAAA-MM-JJ"
        )
    if not LOGICAL_DATE_PATTERN.match(ds):
        raise ConfigurationError(
            f"date logique invalide : {ds!r} — format attendu AAAA-MM-JJ"
        )
    return _first_of_month(ds)


def _first_of_month(date: str) -> str:
    """Ramène une date `AAAA-MM-JJ` au premier du mois."""
    return f"{date[:7]}-01"


def record_sources_date(outlet_events: Any, asset: Any, sources_date: str) -> None:
    """Inscrit la date des sources dans l'événement d'Asset publié par l'acquisition."""
    outlet_events[asset].extra[SOURCES_DATE_KEY] = sources_date


def should_acquire(inlet_events: Any, asset: Any, sources_date: str, conf: dict | None) -> bool:
    """Vrai si ce mois de sources n'a pas encore été publié, ou si le run demande `force` (`true` JSON)."""
    if (conf or {}).get(FORCE_KEY) is True:
        return True
    return all(event.extra.get(SOURCES_DATE_KEY) != sources_date for event in inlet_events[asset])


def resolve_sources_date(triggering_events: Any, asset: Any, conf: dict | None) -> str:
    """Renvoie la date des sources d'un run de panel : événement d'Asset le plus récent, sinon `--conf`."""
    events = triggering_events[asset] if triggering_events is not None else []
    dated = [
        (event.timestamp, event.extra[SOURCES_DATE_KEY])
        for event in events
        if event.extra.get(SOURCES_DATE_KEY)
    ]
    if dated:
        return max(dated)[1]
    candidate = (conf or {}).get(SOURCES_DATE_KEY)
    if candidate and LOGICAL_DATE_PATTERN.match(candidate):
        return _first_of_month(candidate)
    raise ConfigurationError(
        "date des sources absente : un run de panel lancé à la main doit fournir "
        "--conf '{\"sources_date\": \"AAAA-MM-JJ\"}'"
    )

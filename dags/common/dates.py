"""Date de travail des DAGs, résolue explicitement (Airflow 3 n'en donne qu'aux runs planifiés)."""
from __future__ import annotations

import datetime as dt
from typing import Any

from ingestion.config import LOGICAL_DATE_PATTERN
from ingestion.errors import ConfigurationError

SOURCES_DATE_KEY = "sources_date"
FORCE_KEY = "force"


def acquisition_month(started_at: dt.datetime, ds: str | None, scheduled: bool) -> str:
    """Renvoie le mois du démarrage réel du run (`AAAA-MM-01`, UTC), jamais celui de son échéance.

    Une pile activée le 4 décembre exécute l'échéance du 10 novembre : elle doit ingérer décembre.
    Un run manuel peut préciser une date, mais seulement dans le mois en cours.
    """
    month = _month_of(started_at)
    if not scheduled and ds:
        _require_current_month(ds, month, "--logical-date")
    return month


def _month_of(moment: dt.datetime) -> str:
    """Ramène un instant au premier de son mois en UTC (partitions et échéances suivent l'UTC)."""
    return moment.astimezone(dt.UTC).strftime("%Y-%m-01")


def _require_current_month(date: str, current_month: str, option: str) -> None:
    """Refuse une date mal formée ou hors du mois en cours : un mois passé n'est jamais rejoué."""
    if not LOGICAL_DATE_PATTERN.match(date):
        raise ConfigurationError(f"{option} invalide : {date!r} — format attendu AAAA-MM-JJ")
    if _first_of_month(date) != current_month:
        raise ConfigurationError(
            f"{option} {date} hors du mois en cours ({current_month[:7]}) : "
            "le pipeline ne traite que le mois en cours"
        )


def _first_of_month(date: str) -> str:
    """Ramène une date `AAAA-MM-JJ` au premier du mois."""
    return f"{date[:7]}-01"


def record_sources_date(outlet_events: Any, asset: Any, sources_date: str) -> None:
    """Inscrit la date des sources dans l'événement d'Asset publié par l'acquisition."""
    outlet_events[asset].extra[SOURCES_DATE_KEY] = sources_date


def should_acquire(
    inlet_events: Any, asset: Any, sources_date: str, conf: dict | None, scheduled: bool
) -> bool:
    """Vrai pour un run planifié (il relit le mois pour en prendre les changements), sinon si ce mois
    n'a pas encore été publié ou si le run demande `force` (`true` JSON)."""
    if scheduled or (conf or {}).get(FORCE_KEY) is True:
        return True
    return all(event.extra.get(SOURCES_DATE_KEY) != sources_date for event in inlet_events[asset])


def resolve_sources_date(
    triggering_events: Any, asset: Any, conf: dict | None, started_at: dt.datetime
) -> str:
    """Renvoie la date des sources d'un run de panel : événement d'Asset le plus récent, sinon
    `--conf`, limité au mois en cours."""
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
        _require_current_month(candidate, _month_of(started_at), SOURCES_DATE_KEY)
        return _first_of_month(candidate)
    raise ConfigurationError(
        "date des sources absente : un run de panel lancé à la main doit fournir "
        "--conf '{\"sources_date\": \"AAAA-MM-JJ\"}'"
    )

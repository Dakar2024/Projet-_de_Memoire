"""Date de travail des DAGs, quel que soit le mode de déclenchement.

Dans Airflow 3, seuls les runs planifiés ont une date logique. Un run déclenché par un
Asset, ou lancé à la main sans `--logical-date`, a `logical_date = None` : la clé `ds`
est alors absente du contexte. La date doit donc être résolue explicitement.

Ce module n'importe pas Airflow : sa logique se teste dans la passe rapide.
"""

from __future__ import annotations

from typing import Any

from ingestion.config import LOGICAL_DATE_PATTERN
from ingestion.errors import ConfigurationError

SOURCES_DATE_KEY = "sources_date"


def require_logical_date(ds: str | None) -> str:
    """Date de travail du DAG d'acquisition, ramenée au premier jour du mois.

    Le run planifié tombe le 10 (le temps que l'archive ClinVar du mois paraisse), un
    rejeu manuel peut porter n'importe quel jour : tous deux doivent écrire la même
    partition `dt=AAAA-MM-01`, d'autant que `archive_version_for` ne dépend que du mois.
    """
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
    return f"{date[:7]}-01"


def record_sources_date(outlet_events: Any, asset: Any, sources_date: str) -> None:
    """Inscrit la date des sources dans l'événement d'Asset publié par l'acquisition."""
    outlet_events[asset].extra[SOURCES_DATE_KEY] = sources_date


def resolve_sources_date(triggering_events: Any, asset: Any, conf: dict | None) -> str:
    """Date des sources partagées sur laquelle travaille un run de panel.

    Priorité à l'événement d'Asset le plus récent qui porte une date : plusieurs
    événements s'accumulent si plusieurs acquisitions ont eu lieu depuis le dernier run
    de panel. À défaut (déclenchement manuel), `sources_date` de la configuration du
    run, au format AAAA-MM-JJ, ramenée au premier du mois comme la date d'acquisition.
    """
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

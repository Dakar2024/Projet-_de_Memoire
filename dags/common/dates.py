"""Date de travail des DAGs, quel que soit le mode de déclenchement.

Dans Airflow 3, seuls les runs planifiés ont une date logique. Un run déclenché par un
Asset, ou lancé à la main sans `--logical-date`, a `logical_date = None` : la clé `ds`
est alors absente du contexte. La date doit donc être résolue explicitement.

Ce module n'importe pas Airflow : sa logique se teste dans la passe rapide.
"""

from __future__ import annotations

from typing import Any

from ingestion.clinvar import LOGICAL_DATE_PATTERN
from ingestion.errors import ConfigurationError

SOURCES_DATE_KEY = "sources_date"


def require_logical_date(ds: str | None) -> str:
    """Date logique du DAG d'acquisition, ou erreur de configuration explicite."""
    if not ds:
        raise ConfigurationError(
            "date logique absente : un run manuel du DAG d'acquisition doit être "
            "déclenché avec --logical-date AAAA-MM-JJ"
        )
    return ds


def record_sources_date(outlet_events: Any, asset: Any, sources_date: str) -> None:
    """Inscrit la date des sources dans l'événement d'Asset publié par l'acquisition."""
    outlet_events[asset].extra[SOURCES_DATE_KEY] = sources_date


def resolve_sources_date(triggering_events: Any, asset: Any, conf: dict | None) -> str:
    """Date des sources partagées sur laquelle travaille un run de panel.

    Priorité à l'événement d'Asset le plus récent qui porte une date : plusieurs
    événements s'accumulent si plusieurs acquisitions ont eu lieu depuis le dernier run
    de panel. À défaut (déclenchement manuel), `sources_date` de la configuration du
    run, au format AAAA-MM-JJ.
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
        return candidate
    raise ConfigurationError(
        "date des sources absente : un run de panel lancé à la main doit fournir "
        "--conf '{\"sources_date\": \"AAAA-MM-JJ\"}'"
    )

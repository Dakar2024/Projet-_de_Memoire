"""Nettoyage des tables Delta Silver et Gold (VACUUM) : seuls partent les fichiers retirés depuis 30 jours."""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Protocol

from deltalake import DeltaTable

from ingestion.storage import find_delta_tables, layer_uri, storage_options

log = logging.getLogger(__name__)

# 30 jours (choix du 16/10/2026) : une erreur vue au run mensuel suivant reste rattrapable par l'historique Delta.
VACUUM_RETENTION_HOURS = 30 * 24
# `raw` et `bronze` ne sont pas des tables Delta.
VACUUMED_LAYERS = ("silver", "gold")


class _VacuumableTable(Protocol):
    """Ce dont VACUUM a besoin d'une table : `DeltaTable` en service, un double en test."""

    def vacuum(self, *, retention_hours: int, dry_run: bool) -> list[str]: ...


def vacuum_delta_tables(
    lake_uri: str | None = None,
    retention_hours: int = VACUUM_RETENTION_HOURS,
    open_table: Callable[..., _VacuumableTable] = DeltaTable,
) -> dict[str, int]:
    """Lance VACUUM sur chaque table Delta Silver et Gold, et renvoie le nombre de fichiers supprimés par table."""
    removed: dict[str, int] = {}
    for layer in VACUUMED_LAYERS:
        for uri in find_delta_tables(layer_uri(layer, lake_uri)):
            table = open_table(uri, storage_options=storage_options(uri))
            removed[uri] = len(table.vacuum(retention_hours=retention_hours, dry_run=False))
            log.info("VACUUM %s : %d fichiers supprimés", uri, removed[uri])
    return removed

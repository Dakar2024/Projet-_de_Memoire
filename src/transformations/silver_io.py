"""Lecture des tables Silver, partagée par le contrôle qualité Silver et les transformations Gold."""
from __future__ import annotations

import polars as pl

from ingestion.storage import layer_uri, storage_options


def silver_table_uri(table: str, lake_uri: str | None = None) -> str:
    """Renvoie l'URI d'une table Silver (chemin direct sous la couche, sans date ni panel)."""
    return f"{layer_uri('silver', lake_uri=lake_uri)}/{table}"


def read_silver(table: str, panel: str | None = None, lake_uri: str | None = None) -> pl.DataFrame:
    """Lit une table Silver, filtrée sur `panel` si fourni."""
    uri = silver_table_uri(table, lake_uri)
    df = pl.read_delta(uri, storage_options=storage_options(uri))
    return df if panel is None else df.filter(pl.col("panel") == panel)

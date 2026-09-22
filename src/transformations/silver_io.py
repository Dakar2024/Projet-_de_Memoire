"""Lecture des tables Silver : seul point d'entrée, partagé par le contrôle qualité
Silver et les deux transformations Gold."""

from __future__ import annotations

import polars as pl

from ingestion.storage import layer_uri, storage_options


def silver_table_uri(table: str, lake_uri: str | None = None) -> str:
    """URI d'une table Silver : une table est un chemin direct sous la couche, sans
    date ni panel (contrairement à `partition_uri`, conçue pour raw/bronze)."""
    return f"{layer_uri('silver', lake_uri=lake_uri)}/{table}"


def read_silver(table: str, panel: str | None = None, lake_uri: str | None = None) -> pl.DataFrame:
    uri = silver_table_uri(table, lake_uri)
    df = pl.read_delta(uri, storage_options=storage_options(uri))
    return df if panel is None else df.filter(pl.col("panel") == panel)

"""VACUUM des tables Delta Silver et Gold : retention de 30 jours, aucune donnée courante perdue."""
from __future__ import annotations

import polars as pl

from transformations.delta_maintenance import VACUUM_RETENTION_HOURS, vacuum_delta_tables


def _write(uri: str, values: list[int]) -> None:
    pl.DataFrame({"x": values}).write_delta(uri, mode="overwrite")


def test_vacuum_keeps_recently_removed_files_and_the_current_data(tmp_path):
    """Un fichier retiré il y a moins de 30 jours reste : une erreur vue au run suivant se rattrape."""
    lake = f"file://{tmp_path}/lake"
    table = f"{lake}/silver/clinvar_variant"
    _write(table, [1])
    _write(table, [2])

    removed = vacuum_delta_tables(lake)

    assert removed == {table: 0}
    assert pl.read_delta(table)["x"].to_list() == [2]
    assert pl.read_delta(table, version=0)["x"].to_list() == [1]


def test_vacuum_covers_silver_and_nested_gold_tables_with_thirty_days(tmp_path):
    lake = f"file://{tmp_path}/lake"
    for table in ("silver/hpo_term", "gold/analytique/fact_variant", "gold/rag/documents"):
        _write(f"{lake}/{table}", [1])
    calls: list[tuple[str, dict]] = []

    class _Table:
        def __init__(self, uri, storage_options=None):
            self.uri = uri

        def vacuum(self, **kwargs):
            calls.append((self.uri, kwargs))
            return ["ancien.parquet"]

    removed = vacuum_delta_tables(lake, open_table=_Table)

    assert sorted(uri for uri, _ in calls) == sorted(removed) == sorted(
        f"{lake}/{t}" for t in ("silver/hpo_term", "gold/analytique/fact_variant", "gold/rag/documents")
    )
    assert all(kwargs == {"retention_hours": 30 * 24, "dry_run": False} for _, kwargs in calls)
    assert VACUUM_RETENTION_HOURS == 720
    assert set(removed.values()) == {1}

"""Comparaison d'un lac restauré à sa sauvegarde : mêmes tables Delta, mêmes nombres de lignes."""
from __future__ import annotations

import polars as pl

from scripts.verifier_restauration_lac import compare_lakes


def _table(lake: str, table: str, rows: int) -> None:
    pl.DataFrame({"x": list(range(rows))}).write_delta(f"{lake}/{table}", mode="overwrite")


def _lake(root, tables: dict[str, int]) -> str:
    lake = f"file://{root}"
    for table, rows in tables.items():
        _table(lake, table, rows)
    return lake


TABLES = {"silver/clinvar_variant": 3, "gold/rag/documents": 5}


def test_identical_lakes_have_no_gap(tmp_path):
    reference = _lake(tmp_path / "sauvegarde", TABLES)
    restored = _lake(tmp_path / "restaure", TABLES)
    assert compare_lakes(restored, reference) == []


def test_a_row_count_gap_is_reported(tmp_path):
    reference = _lake(tmp_path / "sauvegarde", TABLES)
    restored = _lake(tmp_path / "restaure", {**TABLES, "gold/rag/documents": 4})
    assert compare_lakes(restored, reference) == ["gold/rag/documents : 4 lignes restaurées, 5 sauvegardées"]


def test_a_missing_or_extra_table_is_reported(tmp_path):
    reference = _lake(tmp_path / "sauvegarde", TABLES)
    restored = _lake(tmp_path / "restaure", {"silver/clinvar_variant": 3, "silver/hpo_term": 1})
    assert compare_lakes(restored, reference) == [
        "gold/rag/documents : absente du lac restauré",
        "silver/hpo_term : absente de la sauvegarde",
    ]


def test_an_unreadable_table_is_reported_by_name(tmp_path):
    """Un fichier Parquet abîmé dans la sauvegarde : écart nommé, pas une trace Python."""
    reference = _lake(tmp_path / "sauvegarde", TABLES)
    restored = _lake(tmp_path / "restaure", TABLES)
    [part] = list((tmp_path / "restaure" / "gold" / "rag" / "documents").glob("*.parquet"))
    part.write_bytes(part.read_bytes()[:-10])

    [gap] = compare_lakes(restored, reference)

    assert gap.startswith("gold/rag/documents : illisible")

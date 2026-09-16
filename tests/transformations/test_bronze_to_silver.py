import io

import polars as pl

from ingestion.storage import put_bytes
from transformations.bronze_to_silver import _read_bronze_table, _write_silver_snapshot


def _seed_bronze_parquet(tmp_path, source, panel, df: pl.DataFrame) -> str:
    partition = f"file://{tmp_path}/lake/bronze/{source}/dt=2026-09-01"
    if panel:
        partition += f"/panel={panel}"
    buf = io.BytesIO()
    df.write_parquet(buf)
    put_bytes(f"{partition}/data.parquet", buf.getvalue())
    return partition


def test_read_bronze_table_reads_back_the_parquet_file(tmp_path):
    df = pl.DataFrame({"gene_symbol": ["BRCA1"], "esummary_json": ["{}"]})
    partition = _seed_bronze_parquet(tmp_path, "ncbi_gene", "brca", df)

    result = _read_bronze_table(partition)

    assert result["gene_symbol"].to_list() == ["BRCA1"]


def test_read_bronze_table_drops_bronze_technical_columns(tmp_path):
    """Ces colonnes ne doivent jamais atteindre une table Silver (contrainte globale
    de ce plan) — retirées ici, au point de lecture unique de toutes les sources."""
    df = pl.DataFrame({
        "gene_symbol": ["BRCA1"], "esummary_json": ["{}"],
        "_source_version": ["2026-09-01"], "_logical_date": ["2026-09-01"],
        "_ingested_at": ["2026-09-01T00:00:00+00:00"],
    })
    partition = _seed_bronze_parquet(tmp_path, "ncbi_gene", "brca", df)

    result = _read_bronze_table(partition)

    assert result.columns == ["gene_symbol", "esummary_json"]


def test_write_silver_snapshot_only_replaces_the_given_panel(tmp_path):
    uri = f"file://{tmp_path}/lake/silver/ncbi_gene"

    _write_silver_snapshot(
        pl.DataFrame({"gene_symbol": ["BRCA1"], "panel": ["brca"]}), uri, "brca"
    )
    _write_silver_snapshot(
        pl.DataFrame({"gene_symbol": ["HBB"], "panel": ["sickle"]}), uri, "sickle"
    )
    # Un second run sur brca ne doit pas toucher les lignes sickle.
    _write_silver_snapshot(
        pl.DataFrame({"gene_symbol": ["BRCA1", "BRCA2"], "panel": ["brca", "brca"]}),
        uri,
        "brca",
    )

    result = pl.read_delta(uri).sort(["panel", "gene_symbol"])
    assert result["gene_symbol"].to_list() == ["BRCA1", "BRCA2", "HBB"]
    assert result["panel"].to_list() == ["brca", "brca", "sickle"]

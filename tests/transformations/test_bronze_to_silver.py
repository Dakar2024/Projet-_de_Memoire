import io

import polars as pl

from ingestion.storage import put_bytes
from transformations.bronze_to_silver import (
    _build_clinvar_variant_gene,
    _build_clinvar_variant_rows,
    _read_bronze_table,
    _write_clinvar_variant,
    _write_silver_snapshot,
)


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


CLINVAR_ROWS = pl.DataFrame({
    "alleleid": ["1", "2", "3"],
    "genesymbol": ["BRCA1", "ATM;PTEN", "HBB"],
    "assembly": ["GRCh38", "GRCh38", "GRCh38"],
})


def _seed_clinvar_bronze(tmp_path, df: pl.DataFrame = CLINVAR_ROWS) -> str:
    return _seed_bronze_parquet(tmp_path, "clinvar", None, df)


def test_build_clinvar_variant_gene_explodes_multi_gene_rows(tmp_path):
    partition = _seed_clinvar_bronze(tmp_path)

    result = _build_clinvar_variant_gene(partition, ["BRCA1", "ATM", "PTEN"])

    pairs = sorted(zip(result["alleleid"].to_list(), result["gene_symbol"].to_list()))
    assert pairs == [("1", "BRCA1"), ("2", "ATM"), ("2", "PTEN")]


def test_build_clinvar_variant_gene_excludes_genes_outside_the_panel(tmp_path):
    partition = _seed_clinvar_bronze(tmp_path)

    result = _build_clinvar_variant_gene(partition, ["BRCA1"])

    assert result["gene_symbol"].to_list() == ["BRCA1"]


REFSEQ_ROWS = pl.DataFrame({
    "gene_symbol": ["AP5Z1"],
    "accession": ["NM_014855"],
    "version": [3],
})


def test_build_clinvar_variant_rows_keeps_only_grch38(tmp_path):
    df = pl.DataFrame({
        "alleleid": ["1", "1"],
        "genesymbol": ["AP5Z1", "AP5Z1"],
        "assembly": ["GRCh37", "GRCh38"],
        "clinicalsignificance": ["Benign", "Benign"],
        "reviewstatus": ["criteria provided", "criteria provided"],
        "lastevaluated": ["2026-08-01", "2026-08-01"],
        "rs_dbsnp": ["397704705", "397704705"],
        "name": [
            "NM_014855.3(AP5Z1):c.80_83delinsTGCTG",
            "NM_014855.3(AP5Z1):c.80_83delinsTGCTG",
        ],
    })
    partition = _seed_clinvar_bronze(tmp_path, df)
    variant_gene = _build_clinvar_variant_gene(partition, ["AP5Z1"])

    result = _build_clinvar_variant_rows(partition, REFSEQ_ROWS, variant_gene)

    assert result["alleleid"].to_list() == ["1"]
    assert result["assembly"].to_list() == ["GRCh38"]


def test_build_clinvar_variant_rows_deduplicates_on_alleleid(tmp_path):
    df = pl.DataFrame({
        "alleleid": ["1", "1"],
        "genesymbol": ["AP5Z1", "AP5Z1"],
        "assembly": ["GRCh38", "GRCh38"],
        "clinicalsignificance": ["Benign", "Benign"],
        "reviewstatus": ["criteria provided", "criteria provided"],
        "lastevaluated": ["2026-08-01", "2026-08-01"],
        "rs_dbsnp": ["-1", "-1"],
        "name": ["NM_014855.3(AP5Z1):c.1A>G", "NM_014855.3(AP5Z1):c.1A>G"],
    })
    partition = _seed_clinvar_bronze(tmp_path, df)
    variant_gene = _build_clinvar_variant_gene(partition, ["AP5Z1"])

    result = _build_clinvar_variant_rows(partition, REFSEQ_ROWS, variant_gene)

    assert len(result) == 1


def test_build_clinvar_variant_rows_casts_rs_dbsnp_to_integer_with_sentinel(tmp_path):
    df = pl.DataFrame({
        "alleleid": ["1"], "genesymbol": ["AP5Z1"], "assembly": ["GRCh38"],
        "clinicalsignificance": ["Benign"], "reviewstatus": ["criteria provided"],
        "lastevaluated": ["2026-08-01"], "rs_dbsnp": ["-1"],
        "name": ["NM_014855.3(AP5Z1):c.1A>G"],
    })
    partition = _seed_clinvar_bronze(tmp_path, df)
    variant_gene = _build_clinvar_variant_gene(partition, ["AP5Z1"])

    result = _build_clinvar_variant_rows(partition, REFSEQ_ROWS, variant_gene)

    assert result["rs_dbsnp"].to_list() == [-1]
    assert result.schema["rs_dbsnp"] == pl.Int64


def test_build_clinvar_variant_rows_parses_hgvs_and_validates_against_refseq(tmp_path):
    df = pl.DataFrame({
        "alleleid": ["1"], "genesymbol": ["AP5Z1"], "assembly": ["GRCh38"],
        "clinicalsignificance": ["Benign"], "reviewstatus": ["criteria provided"],
        "lastevaluated": ["2026-08-01"], "rs_dbsnp": ["-1"],
        "name": ["NM_014855.3(AP5Z1):c.80_83delinsTGCTG"],
    })
    partition = _seed_clinvar_bronze(tmp_path, df)
    variant_gene = _build_clinvar_variant_gene(partition, ["AP5Z1"])

    result = _build_clinvar_variant_rows(partition, REFSEQ_ROWS, variant_gene)
    row = result.row(0, named=True)

    assert row["refseq_accession"] == "NM_014855"
    assert row["refseq_version"] == 3
    assert row["hgvs_c"] == "c.80_83delinsTGCTG"
    assert row["hgvs_p"] is None
    assert row["refseq_accession_known"] is True


def test_build_clinvar_variant_rows_keeps_a_row_with_irregular_hgvs(tmp_path):
    df = pl.DataFrame({
        "alleleid": ["1"], "genesymbol": ["AP5Z1"], "assembly": ["GRCh38"],
        "clinicalsignificance": ["Benign"], "reviewstatus": ["criteria provided"],
        "lastevaluated": ["2026-08-01"], "rs_dbsnp": ["-1"],
        "name": ["forme HGVS non reconnue"],
    })
    partition = _seed_clinvar_bronze(tmp_path, df)
    variant_gene = _build_clinvar_variant_gene(partition, ["AP5Z1"])

    result = _build_clinvar_variant_rows(partition, REFSEQ_ROWS, variant_gene)
    row = result.row(0, named=True)

    assert row["name"] == "forme HGVS non reconnue"
    assert row["refseq_accession"] is None
    assert row["refseq_accession_known"] is False


def _rows(alleleid, panel, significance, review="criteria provided", evaluated="2026-08-01"):
    return pl.DataFrame({
        "alleleid": [alleleid], "panel": [panel],
        "clinicalsignificance": [significance], "reviewstatus": [review],
        "lastevaluated": [evaluated],
    })


def test_write_clinvar_variant_creates_the_table_on_first_run(tmp_path):
    uri = f"file://{tmp_path}/lake/silver/clinvar_variant"

    _write_clinvar_variant(_rows("1", "brca", "Benign"), uri, "brca", "2026-08-01")

    result = pl.read_delta(uri)
    assert result["is_current"].to_list() == [True]
    assert result["valid_from"].to_list() == ["2026-08-01"]
    assert result["valid_to"].to_list() == [None]


def test_write_clinvar_variant_closes_and_reopens_on_a_real_change(tmp_path):
    uri = f"file://{tmp_path}/lake/silver/clinvar_variant"
    _write_clinvar_variant(_rows("1", "brca", "Pathogenic"), uri, "brca", "2026-08-01")

    _write_clinvar_variant(
        _rows("1", "brca", "Pathogenic/Likely pathogenic"), uri, "brca", "2026-09-01"
    )

    result = pl.read_delta(uri).sort("valid_from")
    assert result["is_current"].to_list() == [False, True]
    assert result["valid_to"].to_list() == ["2026-09-01", None]
    assert result["clinicalsignificance"].to_list() == [
        "Pathogenic", "Pathogenic/Likely pathogenic",
    ]


def test_write_clinvar_variant_replay_is_idempotent(tmp_path):
    """Rejouer le même mois avec les mêmes valeurs ne doit créer aucune ligne."""
    uri = f"file://{tmp_path}/lake/silver/clinvar_variant"
    _write_clinvar_variant(_rows("1", "brca", "Benign"), uri, "brca", "2026-08-01")
    _write_clinvar_variant(_rows("1", "brca", "Pathogenic"), uri, "brca", "2026-09-01")

    _write_clinvar_variant(_rows("1", "brca", "Pathogenic"), uri, "brca", "2026-09-01")

    assert len(pl.read_delta(uri)) == 2


def test_write_clinvar_variant_ignores_unwatched_field_changes(tmp_path):
    """Un champ hors liste surveillée (ex. `name`) ne doit pas déclencher de nouvelle
    version — seuls clinical_significance/review_status/last_evaluated comptent."""
    uri = f"file://{tmp_path}/lake/silver/clinvar_variant"
    first = _rows("1", "brca", "Benign").with_columns(pl.lit("Name v1").alias("name"))
    _write_clinvar_variant(first, uri, "brca", "2026-08-01")

    second = _rows("1", "brca", "Benign").with_columns(pl.lit("Name v2").alias("name"))
    _write_clinvar_variant(second, uri, "brca", "2026-09-01")

    assert len(pl.read_delta(uri)) == 1


def test_write_clinvar_variant_does_not_touch_the_other_panel(tmp_path):
    uri = f"file://{tmp_path}/lake/silver/clinvar_variant"
    _write_clinvar_variant(_rows("1", "sickle", "Benign"), uri, "sickle", "2026-08-01")

    _write_clinvar_variant(_rows("2", "brca", "Pathogenic"), uri, "brca", "2026-08-01")

    result = pl.read_delta(uri).sort("panel")
    assert result["panel"].to_list() == ["brca", "sickle"]
    assert result.filter(pl.col("panel") == "sickle")["clinicalsignificance"].to_list() == ["Benign"]

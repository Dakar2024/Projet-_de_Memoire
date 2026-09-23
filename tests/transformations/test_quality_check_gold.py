import polars as pl
import pytest

from tests.transformations.test_silver_to_gold_rag import _seed_silver
from transformations.quality_check_gold import GoldQualityError, quality_check_gold
from transformations.silver_to_gold_analytique import gold_table_uri, silver_to_gold_analytique
from transformations.silver_to_gold_rag import documents_uri, silver_to_gold_rag


def _seed_gold(tmp_path):
    lake = _seed_silver(f"file://{tmp_path}/lake")
    silver_to_gold_rag("2026-09-01", "brca", lake_uri=lake)
    silver_to_gold_analytique("2026-09-01", "brca", lake_uri=lake)
    return lake


def test_quality_check_gold_passes_on_a_complete_run(tmp_path):
    lake = _seed_gold(tmp_path)

    quality_check_gold("2026-09-01", "brca", lake_uri=lake)   # ne lève pas


def test_quality_check_gold_detects_a_lost_variant(tmp_path):
    lake = _seed_gold(tmp_path)
    fact = pl.read_delta(gold_table_uri("fact_variant", lake)).head(0)
    fact.write_delta(gold_table_uri("fact_variant", lake), mode="overwrite")

    with pytest.raises(GoldQualityError, match="fact_variant"):
        quality_check_gold("2026-09-01", "brca", lake_uri=lake)


def test_quality_check_gold_detects_a_missing_document(tmp_path):
    lake = _seed_gold(tmp_path)
    docs = pl.read_delta(documents_uri(lake)).filter(pl.col("doc_type") != "variant")
    docs.write_delta(documents_uri(lake), mode="overwrite")

    with pytest.raises(GoldQualityError, match="documents"):
        quality_check_gold("2026-09-01", "brca", lake_uri=lake)


def test_quality_check_gold_detects_a_duplicate_doc_id(tmp_path):
    lake = _seed_gold(tmp_path)
    docs = pl.read_delta(documents_uri(lake))
    pl.concat([docs, docs.head(1)]).write_delta(documents_uri(lake), mode="overwrite")

    with pytest.raises(GoldQualityError, match="doc_id"):
        quality_check_gold("2026-09-01", "brca", lake_uri=lake)


def test_quality_check_gold_detects_an_oversized_document(tmp_path):
    lake = _seed_gold(tmp_path)
    docs = pl.read_delta(documents_uri(lake)).with_columns(
        pl.when(pl.col("doc_type") == "variant").then(pl.lit("x" * 5000))
        .otherwise(pl.col("text")).alias("text"))
    docs.write_delta(documents_uri(lake), mode="overwrite")

    with pytest.raises(GoldQualityError, match="caractères"):
        quality_check_gold("2026-09-01", "brca", lake_uri=lake)


def test_quality_check_gold_detects_a_gene_missing_from_dim_gene(tmp_path):
    lake = _seed_gold(tmp_path)
    pl.read_delta(gold_table_uri("dim_gene", lake)).head(0).write_delta(
        gold_table_uri("dim_gene", lake), mode="overwrite")

    with pytest.raises(GoldQualityError, match="dim_gene"):
        quality_check_gold("2026-09-01", "brca", lake_uri=lake)


def test_quality_check_gold_reports_every_problem_at_once(tmp_path):
    lake = _seed_gold(tmp_path)
    pl.read_delta(gold_table_uri("fact_variant", lake)).head(0).write_delta(
        gold_table_uri("fact_variant", lake), mode="overwrite")
    pl.read_delta(gold_table_uri("dim_gene", lake)).head(0).write_delta(
        gold_table_uri("dim_gene", lake), mode="overwrite")

    with pytest.raises(GoldQualityError) as raised:
        quality_check_gold("2026-09-01", "brca", lake_uri=lake)

    assert "fact_variant" in str(raised.value) and "dim_gene" in str(raised.value)

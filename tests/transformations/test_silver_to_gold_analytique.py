import polars as pl

from transformations.silver_to_gold_analytique import (
    build_fact_reclassification,
    build_fact_variant,
    build_fact_variant_disease,
    gold_table_uri,
)

VARIANTS = pl.DataFrame([
    {"alleleid": "1", "clinicalsignificance": "Pathogenic", "clinsigsimple": "1",
     "reviewstatus": "criteria provided", "chromosome": "17", "type": "SNV",
     "genesymbol": "BRCA1", "panel": "brca", "valid_from": "2026-08-01",
     "valid_to": "2026-09-01", "is_current": False},
    {"alleleid": "1", "clinicalsignificance": "Pathogenic/Likely pathogenic", "clinsigsimple": "1",
     "reviewstatus": "criteria provided", "chromosome": "17", "type": "SNV",
     "genesymbol": "BRCA1", "panel": "brca", "valid_from": "2026-09-01",
     "valid_to": None, "is_current": True},
    {"alleleid": "2", "clinicalsignificance": "Benign", "clinsigsimple": "0",
     "reviewstatus": "no assertion criteria provided", "chromosome": "17", "type": "SNV",
     "genesymbol": "BRCA1", "panel": "brca", "valid_from": "2026-09-01",
     "valid_to": None, "is_current": True},
])
VARIANT_GENE = pl.DataFrame([
    {"alleleid": "1", "gene_symbol": "BRCA1", "panel": "brca"},
    {"alleleid": "2", "gene_symbol": "BRCA1", "panel": "brca"},
])


def test_gold_table_uri_points_under_the_analytique_prefix():
    assert gold_table_uri("fact_variant", "file:///lake") == "file:///lake/gold/analytique/fact_variant"


def test_build_fact_variant_keeps_one_row_per_current_variant():
    fact = build_fact_variant(VARIANTS, VARIANT_GENE, "2026-09")

    assert sorted(fact["alleleid"].to_list()) == ["1", "2"]
    assert fact.filter(pl.col("alleleid") == "1")["clinical_significance"].to_list() == [
        "Pathogenic/Likely pathogenic"
    ]
    assert fact["month"].unique().to_list() == ["2026-09"]


def test_build_fact_variant_disease_does_not_inflate_the_variant_count():
    variant_disease = pl.DataFrame([
        {"alleleid": "1", "disease_name": "A", "medgen_cui": "C1", "panel": "brca"},
        {"alleleid": "1", "disease_name": "B", "medgen_cui": "C2", "panel": "brca"},
    ])

    fact = build_fact_variant_disease(variant_disease, VARIANT_GENE, "2026-09")

    assert fact.height == 2
    assert fact["alleleid"].n_unique() == 1
    assert fact["gene_symbol"].unique().to_list() == ["BRCA1"]


def test_build_fact_reclassification_pairs_a_closed_row_with_its_successor():
    fact = build_fact_reclassification(VARIANTS)

    assert fact.height == 1
    row = fact.row(0, named=True)
    assert row["significance_from"] == "Pathogenic"
    assert row["significance_to"] == "Pathogenic/Likely pathogenic"
    assert row["changed_on"] == "2026-09-01"


def test_build_fact_reclassification_is_empty_without_history():
    only_current = VARIANTS.filter(pl.col("is_current"))

    assert build_fact_reclassification(only_current).height == 0

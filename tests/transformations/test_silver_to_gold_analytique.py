import polars as pl

from transformations.silver_to_gold_analytique import (
    build_dimensions,
    build_fact_reclassification,
    build_fact_variant,
    build_fact_variant_disease,
    gold_table_uri,
)

# Vocabulaire ClinVar documenté pour `reviewstatus`, avec le rang étoile attendu.
# "-" (aucun statut donné par ClinVar) en est délibérément exclu : couvert à part,
# il doit rester nul plutôt que de se voir attribuer 0 étoile.
REVIEW_STATUSES_WITH_STARS = {
    "practice guideline": 4,
    "reviewed by expert panel": 3,
    "criteria provided, multiple submitters, no conflicts": 2,
    "criteria provided, single submitter": 1,
    "criteria provided, conflicting classifications": 1,
    "no assertion criteria provided": 0,
    "no assertion provided": 0,
    "no classification provided": 0,
    "no classification for the single variant": 0,
    "no classifications from unflagged records": 0,
}


def _minimal_dimension_inputs():
    """Entrées minimales et valides de `build_dimensions`, pour les tests qui ne
    portent que sur une partie du résultat."""
    genes = pl.DataFrame([
        {"gene_symbol": "BRCA1", "name": "BRCA1", "description": "d",
         "maplocation": "17q21", "summary": "s", "panel": "brca"},
    ])
    variant_disease = pl.DataFrame([
        {"medgen_cui": "C1", "disease_name": "A", "omim_id": None, "orpha_id": None,
         "mondo_id": None, "panel": "brca"},
    ])
    inheritance = pl.DataFrame([
        {"cui": "C1", "panel": "brca", "mode_inheritance": "Autosomal dominant"},
    ])
    concepts = pl.DataFrame([
        {"cui": "C1", "clinical_summary": "sum", "panel": "brca"},
    ])
    hpo_term = pl.DataFrame([
        {"hpo_id": "HP:1", "hpo_name": "n", "definition": "d", "synonyms": ["a"],
         "panel": "brca"},
    ])
    gene_phenotype = pl.DataFrame([
        {"gene_symbol": "BRCA1", "hpo_id": "HP:1", "frequency": "f",
         "disease_id": "OMIM:1", "panel": "brca"},
    ])
    return genes, variant_disease, inheritance, concepts, hpo_term, gene_phenotype

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


def test_build_fact_variant_fans_out_a_variant_mapped_to_two_panel_genes():
    """Comportement voulu et pinné : le contrôle qualité (tâche 7) compare des
    `alleleid` distincts, pas des lignes, donc ce fan-out est sans danger."""
    variant_gene_two_genes = pl.DataFrame([
        {"alleleid": "1", "gene_symbol": "BRCA1", "panel": "brca"},
        {"alleleid": "1", "gene_symbol": "BRCA2", "panel": "brca"},
        {"alleleid": "2", "gene_symbol": "BRCA1", "panel": "brca"},
    ])

    fact = build_fact_variant(VARIANTS, variant_gene_two_genes, "2026-09")
    rows_for_allele_1 = fact.filter(pl.col("alleleid") == "1")

    assert rows_for_allele_1.height == 2
    assert rows_for_allele_1["alleleid"].unique().to_list() == ["1"]
    assert sorted(rows_for_allele_1["gene_symbol"].to_list()) == ["BRCA1", "BRCA2"]


def test_dim_review_status_covers_the_documented_clinvar_vocabulary():
    statuses = [*REVIEW_STATUSES_WITH_STARS, "-"]
    fact_variant = pl.DataFrame([
        {"alleleid": str(i), "gene_symbol": "BRCA1", "clinical_significance": "Pathogenic",
         "clinsig_simple": "1", "review_status": status, "chromosome": "17",
         "variant_type": "SNV", "panel": "brca", "month": "2026-09"}
        for i, status in enumerate(statuses)
    ])
    genes, variant_disease, inheritance, concepts, hpo_term, gene_phenotype = (
        _minimal_dimension_inputs()
    )

    dims = build_dimensions(
        genes, variant_disease, inheritance, concepts, hpo_term, gene_phenotype,
        fact_variant, "2026-09",
    )

    stars_by_status = dict(
        dims["dim_review_status"].select("review_status", "stars").iter_rows()
    )
    for status, expected_stars in REVIEW_STATUSES_WITH_STARS.items():
        assert stars_by_status[status] == expected_stars
    assert stars_by_status["-"] is None


def test_build_dimensions_joins_inheritance_modes_and_computes_the_quarter():
    variant_disease = pl.DataFrame([
        {"medgen_cui": "C1", "disease_name": "A", "omim_id": None, "orpha_id": None,
         "mondo_id": None, "panel": "brca"},
        {"medgen_cui": "C2", "disease_name": "B", "omim_id": None, "orpha_id": None,
         "mondo_id": None, "panel": "brca"},
    ])
    inheritance = pl.DataFrame([
        {"cui": "C1", "panel": "brca", "mode_inheritance": "Autosomal recessive"},
        {"cui": "C1", "panel": "brca", "mode_inheritance": "Autosomal dominant"},
        {"cui": "C1", "panel": "brca", "mode_inheritance": None},
        # C2 n'a aucune ligne d'hérédité : doit rester nul, pas disparaître.
    ])
    concepts = pl.DataFrame([
        {"cui": "C1", "clinical_summary": "sum", "panel": "brca"},
    ])
    genes, _, _, _, hpo_term, gene_phenotype = _minimal_dimension_inputs()
    fact_variant = pl.DataFrame([
        {"alleleid": "1", "gene_symbol": "BRCA1", "clinical_significance": "Pathogenic",
         "clinsig_simple": "1", "review_status": "criteria provided, single submitter",
         "chromosome": "17", "variant_type": "SNV", "panel": "brca", "month": "2026-11"},
    ])

    dims = build_dimensions(
        genes, variant_disease, inheritance, concepts, hpo_term, gene_phenotype,
        fact_variant, "2026-11",
    )

    dim_disease = dims["dim_disease"]
    row_c1 = dim_disease.filter(pl.col("medgen_cui") == "C1").row(0, named=True)
    assert row_c1["modes_inheritance"] == "Autosomal dominant; Autosomal recessive"
    row_c2 = dim_disease.filter(pl.col("medgen_cui") == "C2").row(0, named=True)
    assert row_c2["modes_inheritance"] is None

    dim_month = dims["dim_month"]
    row = dim_month.row(0, named=True)
    assert row["month"] == "2026-11"
    assert row["quarter"] == 4

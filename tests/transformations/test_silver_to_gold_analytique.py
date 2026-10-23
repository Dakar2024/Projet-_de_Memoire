import polars as pl

from tests.transformations.test_silver_to_gold_rag import _seed_silver
from transformations.silver_to_gold_analytique import (
    _write_gold_snapshot,
    build_aggregates,
    build_dimensions,
    build_fact_reclassification,
    build_fact_variant,
    build_fact_variant_disease,
    gold_table_uri,
    silver_to_gold_analytique,
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


def _empty_fact_reclassification() -> pl.DataFrame:
    """`build_dimensions` reads `changed_on` off `fact_reclassification` to widen
    `dim_month`; tests that do not exercise that history pass this instead."""
    return pl.DataFrame(schema={"changed_on": pl.Utf8})

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
    fact = build_fact_reclassification(VARIANTS, VARIANT_GENE)

    assert fact.height == 1
    row = fact.row(0, named=True)
    assert row["significance_from"] == "Pathogenic"
    assert row["significance_to"] == "Pathogenic/Likely pathogenic"
    assert row["changed_on"] == "2026-09-01"
    assert row["gene_symbol"] == "BRCA1"


def test_build_fact_reclassification_is_empty_without_history():
    only_current = VARIANTS.filter(pl.col("is_current"))

    assert build_fact_reclassification(only_current, VARIANT_GENE).height == 0


def test_build_fact_reclassification_sources_gene_symbol_from_clinvar_variant_gene():
    """`genesymbol` on the Silver `clinvar_variant` row is ClinVar's raw, possibly
    multi-gene string (e.g. "ATM;C11orf65") — exactly why `clinvar_variant_gene`
    explodes it on ";". `fact_reclassification.gene_symbol` must come from that
    exploded table, like `build_fact_variant` already does, or it joins to nothing
    in `dim_gene`."""
    variants = pl.DataFrame([
        {"alleleid": "1", "clinicalsignificance": "Pathogenic", "clinsigsimple": "1",
         "reviewstatus": "criteria provided", "chromosome": "11", "type": "SNV",
         "genesymbol": "ATM;C11orf65", "panel": "brca", "valid_from": "2026-08-01",
         "valid_to": "2026-09-01", "is_current": False},
        {"alleleid": "1", "clinicalsignificance": "Benign", "clinsigsimple": "0",
         "reviewstatus": "criteria provided", "chromosome": "11", "type": "SNV",
         "genesymbol": "ATM;C11orf65", "panel": "brca", "valid_from": "2026-09-01",
         "valid_to": None, "is_current": True},
    ])
    variant_gene = pl.DataFrame([
        {"alleleid": "1", "gene_symbol": "ATM", "panel": "brca"},
    ])

    fact = build_fact_reclassification(variants, variant_gene)

    assert fact["gene_symbol"].to_list() == ["ATM"]


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
        fact_variant, _empty_fact_reclassification(), "2026-09",
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
        fact_variant, _empty_fact_reclassification(), "2026-11",
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


def test_dim_month_covers_every_month_present_in_the_reclassification_history():
    """`fact_reclassification` retains every past transition (Silver's full SCD2
    history), but a naive `dim_month` build only ever wrote the current run's
    month — past months a report might group by would have no dimension row at
    all. `dim_month` must cover the current month plus every month appearing in
    `fact_reclassification.changed_on`."""
    genes, variant_disease, inheritance, concepts, hpo_term, gene_phenotype = (
        _minimal_dimension_inputs()
    )
    fact_variant = pl.DataFrame([
        {"alleleid": "1", "gene_symbol": "BRCA1", "clinical_significance": "Pathogenic",
         "clinsig_simple": "1", "review_status": "criteria provided, single submitter",
         "chromosome": "17", "variant_type": "SNV", "panel": "brca", "month": "2026-09"},
    ])
    fact_reclassification = pl.DataFrame([
        {"alleleid": "1", "gene_symbol": "BRCA1", "significance_from": "Pathogenic",
         "significance_to": "Benign", "review_status_to": "criteria provided",
         "changed_on": "2026-07-15", "panel": "brca"},
        {"alleleid": "2", "gene_symbol": "BRCA1", "significance_from": "Benign",
         "significance_to": "Pathogenic", "review_status_to": "criteria provided",
         "changed_on": "2026-08-03", "panel": "brca"},
    ])

    dims = build_dimensions(
        genes, variant_disease, inheritance, concepts, hpo_term, gene_phenotype,
        fact_variant, fact_reclassification, "2026-09",
    )

    months = sorted(dims["dim_month"]["month"].to_list())
    assert months == ["2026-07", "2026-08", "2026-09"]
    row_july = dims["dim_month"].filter(pl.col("month") == "2026-07").row(0, named=True)
    assert row_july["year"] == 2026
    assert row_july["month_number"] == 7
    assert row_july["quarter"] == 3


def test_dim_disease_is_unique_on_medgen_cui():
    """The spec keys `dim_disease` on `medgen_cui` alone (§5.3). A CUI carrying two
    ClinVar disease labels must not produce two dimension rows — that would let a
    `fact_variant_disease -> dim_disease` join double-count variants for that
    disease. Rows with a null CUI are dropped from the dimension (they carry no
    key to join on); `fact_variant_disease` keeps them regardless."""
    genes, _, inheritance, concepts, hpo_term, gene_phenotype = _minimal_dimension_inputs()
    fact_variant = pl.DataFrame([
        {"alleleid": "1", "gene_symbol": "BRCA1", "clinical_significance": "Pathogenic",
         "clinsig_simple": "1", "review_status": "criteria provided", "chromosome": "17",
         "variant_type": "SNV", "panel": "brca", "month": "2026-09"},
    ])
    variant_disease = pl.DataFrame([
        {"medgen_cui": "C1", "disease_name": "Hereditary cancer", "omim_id": "1",
         "orpha_id": None, "mondo_id": None, "panel": "brca"},
        {"medgen_cui": "C1", "disease_name": "Breast neoplasm", "omim_id": "2",
         "orpha_id": None, "mondo_id": None, "panel": "brca"},
        {"medgen_cui": None, "disease_name": "Unresolved condition", "omim_id": None,
         "orpha_id": None, "mondo_id": None, "panel": "brca"},
    ])

    dims = build_dimensions(
        genes, variant_disease, inheritance, concepts, hpo_term, gene_phenotype,
        fact_variant, _empty_fact_reclassification(), "2026-09",
    )

    dim_disease = dims["dim_disease"]
    assert dim_disease.height == 1
    assert dim_disease["medgen_cui"].to_list() == ["C1"]


def test_dim_clinical_significance_is_unique_on_clinical_significance():
    """Same defect as `dim_disease`, one column over: a `clinical_significance`
    label that carries both `clinsigsimple` values in the data (e.g. "Conflicting
    classifications of pathogenicity") must still yield one dimension row, not
    one per `clinsig_simple` value."""
    genes, variant_disease, inheritance, concepts, hpo_term, gene_phenotype = (
        _minimal_dimension_inputs()
    )
    fact_variant = pl.DataFrame([
        {"alleleid": "1", "gene_symbol": "BRCA1",
         "clinical_significance": "Conflicting classifications of pathogenicity",
         "clinsig_simple": "0", "review_status": "criteria provided", "chromosome": "17",
         "variant_type": "SNV", "panel": "brca", "month": "2026-09"},
        {"alleleid": "2", "gene_symbol": "BRCA1",
         "clinical_significance": "Conflicting classifications of pathogenicity",
         "clinsig_simple": "1", "review_status": "criteria provided", "chromosome": "17",
         "variant_type": "SNV", "panel": "brca", "month": "2026-09"},
    ])

    dims = build_dimensions(
        genes, variant_disease, inheritance, concepts, hpo_term, gene_phenotype,
        fact_variant, _empty_fact_reclassification(), "2026-09",
    )

    dim_significance = dims["dim_clinical_significance"]
    assert dim_significance.height == 1
    assert dim_significance["clinical_significance"].to_list() == [
        "Conflicting classifications of pathogenicity"
    ]


def test_build_aggregates_counts_variants_by_gene_and_significance():
    fact = build_fact_variant(VARIANTS, VARIANT_GENE, "2026-09")

    aggregates = build_aggregates(fact, build_fact_reclassification(VARIANTS, VARIANT_GENE))

    counts = aggregates["agg_variants_by_gene_significance"].sort("clinical_significance")
    assert counts["variant_count"].to_list() == [1, 1]
    assert aggregates["agg_reclassifications_by_month"]["reclassification_count"].to_list() == [1]


def test_agg_reclassifications_by_month_buckets_by_month_not_exact_day():
    """The aggregate must group on the `YYYY-MM` month, which is what
    `dim_month.month` carries — grouping on the exact `changed_on` date (as
    before) never joins `dim_month` at all, and splits one month's
    reclassifications into as many rows as there were distinct days."""
    fact_variant = build_fact_variant(VARIANTS, VARIANT_GENE, "2026-09")
    fact_reclassification = pl.DataFrame([
        {"alleleid": "1", "gene_symbol": "BRCA1", "significance_from": "Pathogenic",
         "significance_to": "Pathogenic/Likely pathogenic", "review_status_to": "criteria provided",
         "changed_on": "2026-09-01", "panel": "brca"},
        {"alleleid": "2", "gene_symbol": "BRCA1", "significance_from": "Benign",
         "significance_to": "Pathogenic", "review_status_to": "criteria provided",
         "changed_on": "2026-09-28", "panel": "brca"},
    ])

    aggregates = build_aggregates(fact_variant, fact_reclassification)

    agg = aggregates["agg_reclassifications_by_month"]
    assert agg.height == 1
    row = agg.row(0, named=True)
    assert row["month"] == "2026-09"
    assert row["reclassification_count"] == 2


def test_silver_to_gold_analytique_writes_every_table(tmp_path):
    lake = _seed_silver(f"file://{tmp_path}/lake")

    silver_to_gold_analytique("2026-09-01", "brca", lake_uri=lake)

    for table in ["fact_variant", "fact_variant_disease", "fact_reclassification",
                  "dim_gene", "dim_disease", "dim_phenotype", "bridge_gene_phenotype",
                  "dim_clinical_significance", "dim_review_status", "dim_month",
                  "agg_variants_by_gene_significance", "agg_review_status",
                  "agg_reclassifications_by_month"]:
        pl.read_delta(gold_table_uri(table, lake))   # ne lève pas
    assert pl.read_delta(gold_table_uri("fact_variant", lake))["alleleid"].to_list() == ["1"]


def test_silver_to_gold_analytique_replay_is_idempotent_and_panel_scoped(tmp_path):
    """`height == 1` after two identical single-panel runs would hold even under a
    naive full-table overwrite with no `predicate` at all, since only one panel's
    data would ever exist. Proving scoped idempotence needs another panel present
    *before* the replay, and a full-frame comparison after: the replay must not
    duplicate `brca`'s own rows, and must not touch `sickle`'s row at all."""
    lake = _seed_silver(f"file://{tmp_path}/lake")
    silver_to_gold_analytique("2026-09-01", "brca", lake_uri=lake)
    sickle_row = pl.read_delta(gold_table_uri("fact_variant", lake)).with_columns(
        pl.lit("sickle").alias("panel"), pl.lit("99").alias("alleleid"))
    sickle_row.write_delta(gold_table_uri("fact_variant", lake), mode="append")
    before = pl.read_delta(gold_table_uri("fact_variant", lake)).sort("panel", "alleleid")

    silver_to_gold_analytique("2026-09-01", "brca", lake_uri=lake)

    after = pl.read_delta(gold_table_uri("fact_variant", lake)).sort("panel", "alleleid")
    assert after.equals(before)


def test_silver_to_gold_analytique_leaves_the_other_panel_untouched(tmp_path):
    lake = _seed_silver(f"file://{tmp_path}/lake")
    silver_to_gold_analytique("2026-09-01", "brca", lake_uri=lake)
    other = pl.read_delta(gold_table_uri("fact_variant", lake)).with_columns(
        pl.lit("sickle").alias("panel"), pl.lit("99").alias("alleleid"))
    other.write_delta(gold_table_uri("fact_variant", lake), mode="append")

    silver_to_gold_analytique("2026-09-01", "brca", lake_uri=lake)

    fact = pl.read_delta(gold_table_uri("fact_variant", lake))
    assert "99" in fact["alleleid"].to_list()


def test_write_gold_snapshot_clears_a_panel_that_becomes_empty(tmp_path):
    """A panel's reclassification history can go from non-empty to empty (e.g. no
    transition happened this month). The per-panel overwrite must clear that
    panel's old rows rather than leaving them stranded forever, while another
    panel's rows must survive untouched. Exercises `_write_gold_snapshot`
    directly, since it is the piece that carries this guarantee."""
    lake = f"file://{tmp_path}/lake"
    non_empty_brca = pl.DataFrame([
        {"alleleid": "1", "gene_symbol": "BRCA1", "panel": "brca"},
    ])
    non_empty_sickle = pl.DataFrame([
        {"alleleid": "99", "gene_symbol": "HBB", "panel": "sickle"},
    ])
    _write_gold_snapshot(non_empty_brca, "fact_reclassification", "brca", lake)
    _write_gold_snapshot(non_empty_sickle, "fact_reclassification", "sickle", lake)

    _write_gold_snapshot(non_empty_brca.clear(), "fact_reclassification", "brca", lake)

    fact = pl.read_delta(gold_table_uri("fact_reclassification", lake))
    assert fact.filter(pl.col("panel") == "brca").height == 0
    assert fact.filter(pl.col("panel") == "sickle")["alleleid"].to_list() == ["99"]


def _dim_disease(variant_disease: pl.DataFrame) -> pl.DataFrame:
    genes, _, inheritance, concepts, hpo_term, gene_phenotype = _minimal_dimension_inputs()
    fact_variant = pl.DataFrame([
        {"alleleid": "1", "gene_symbol": "BRCA1", "clinical_significance": "Pathogenic",
         "clinsig_simple": "1", "review_status": "criteria provided", "chromosome": "17",
         "variant_type": "SNV", "panel": "brca", "month": "2026-10"},
    ])
    dims = build_dimensions(
        genes, variant_disease, inheritance, concepts, hpo_term, gene_phenotype,
        fact_variant, _empty_fact_reclassification(), "2026-10",
    )
    return dims["dim_disease"].sort("medgen_cui", "panel")


# Cas réel du rejeu E3b (défaut D-E3b-1) : même CUI, même nom, une ligne avec ses identifiants, une sans.
GASTRIC_CANCER = [
    {"medgen_cui": "C0024623", "disease_name": "Gastric cancer", "omim_id": "613659",
     "orpha_id": None, "mondo_id": "MONDO:0001056", "panel": "brca"},
    {"medgen_cui": "C0024623", "disease_name": "Gastric cancer", "omim_id": None,
     "orpha_id": None, "mondo_id": None, "panel": "brca"},
]


def test_dim_disease_keeps_the_ids_of_a_same_name_row_whatever_the_row_order():
    """Le rejeu d'octobre a perdu OMIM et MONDO de 13 maladies : entre deux lignes de même nom,
    la première gardée dépendait d'un ordre que rien ne garantit."""
    for rows in (GASTRIC_CANCER, GASTRIC_CANCER[::-1]):
        row = _dim_disease(pl.DataFrame(rows)).row(0, named=True)

        assert (row["disease_name"], row["omim_id"], row["mondo_id"]) == (
            "Gastric cancer", "613659", "MONDO:0001056",
        )


def test_dim_disease_is_identical_for_every_order_of_its_input_rows():
    rows = GASTRIC_CANCER + [
        {"medgen_cui": "C1", "disease_name": "Hereditary cancer", "omim_id": "1",
         "orpha_id": "10", "mondo_id": None, "panel": "brca"},
        {"medgen_cui": "C1", "disease_name": "Breast neoplasm", "omim_id": "2",
         "orpha_id": None, "mondo_id": None, "panel": "brca"},
        {"medgen_cui": "C1", "disease_name": "Breast neoplasm", "omim_id": None,
         "orpha_id": None, "mondo_id": "MONDO:3", "panel": "brca"},
    ]
    attendu = _dim_disease(pl.DataFrame(rows))

    for graine in range(20):
        assert _dim_disease(pl.DataFrame(rows).sample(fraction=1.0, shuffle=True, seed=graine)).equals(attendu)


def test_dim_disease_never_pairs_a_name_with_the_ids_of_another_name():
    """Les identifiants ne sont réunis qu'entre lignes du nom retenu : OMIM 1 appartient à
    « Hereditary cancer », pas au nom retenu « Breast neoplasm »."""
    row = _dim_disease(pl.DataFrame([
        {"medgen_cui": "C1", "disease_name": "Hereditary cancer", "omim_id": "1",
         "orpha_id": "10", "mondo_id": None, "panel": "brca"},
        {"medgen_cui": "C1", "disease_name": "Breast neoplasm", "omim_id": None,
         "orpha_id": None, "mondo_id": "MONDO:3", "panel": "brca"},
    ])).row(0, named=True)

    assert (row["disease_name"], row["omim_id"], row["orpha_id"], row["mondo_id"]) == (
        "Breast neoplasm", None, None, "MONDO:3",
    )


def test_dim_disease_prefers_a_real_name_to_a_null_one():
    """Un nom nul (groupe ClinVar désaligné) passait devant au tri : la dimension perdait son libellé."""
    row = _dim_disease(pl.DataFrame([
        {"medgen_cui": "C1", "disease_name": None, "omim_id": "1",
         "orpha_id": None, "mondo_id": None, "panel": "brca"},
        {"medgen_cui": "C1", "disease_name": "Breast neoplasm", "omim_id": "2",
         "orpha_id": None, "mondo_id": None, "panel": "brca"},
    ])).row(0, named=True)

    assert (row["disease_name"], row["omim_id"]) == ("Breast neoplasm", "2")


def test_dim_disease_keeps_a_cui_whose_names_are_all_null():
    rows = _dim_disease(pl.DataFrame([
        {"medgen_cui": "C1", "disease_name": None, "omim_id": "1",
         "orpha_id": None, "mondo_id": None, "panel": "brca"},
    ], schema_overrides={"disease_name": pl.Utf8}))

    assert rows.select("medgen_cui", "disease_name", "omim_id").rows() == [("C1", None, "1")]

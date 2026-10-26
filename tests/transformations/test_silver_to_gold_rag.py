import polars as pl
import pytest

from ingestion.config import BREAST_CANCER_GENES
from transformations.bronze_to_silver import _write_silver_snapshot
from transformations.silver_to_gold_rag import (
    MAX_PHENOTYPES,
    MAX_SUMMARY_CHARS,
    _previous_significance,
    build_documents,
    chunk_id,
    documents_uri,
    format_list,
    render_gene_document,
    render_variant_document,
    silver_to_gold_rag,
)

VARIANT = {
    "alleleid": "45948",
    "name": "NM_007294.4(BRCA1):c.116G>A (p.Cys39Tyr)",
    "gene_symbol": "BRCA1",
    "cytogenetic": "17q21.31",
    "rs_dbsnp": 80357498,
    "variationid": "37392",
    "type": "single nucleotide variant",
    "clinicalsignificance": "Pathogenic/Likely pathogenic",
    "reviewstatus": "criteria provided, multiple submitters, no conflicts",
    "numbersubmitters": "21",
    "lastevaluated": "Jul 14, 2026",
}
DISEASES = [
    {"disease_name": "Hereditary breast ovarian cancer syndrome", "omim_id": "604370",
     "mode_inheritance": "Autosomal dominant"},
    {"disease_name": "Breast neoplasm", "omim_id": None, "mode_inheritance": None},
]


def test_render_variant_document_contains_every_citable_field():
    text = render_variant_document(VARIANT, DISEASES, ["Breast carcinoma"], None)

    assert "NM_007294.4(BRCA1):c.116G>A (p.Cys39Tyr)" in text
    assert "rs80357498" in text
    assert "ClinVar Variation ID 37392" in text
    assert "Clinical significance: Pathogenic/Likely pathogenic." in text
    assert "21 submitters" in text
    assert "Hereditary breast ovarian cancer syndrome (OMIM 604370, inheritance: Autosomal dominant)" in text
    assert "Related phenotypes (HPO): Breast carcinoma." in text


def test_render_variant_document_states_the_reclassification_history():
    text = render_variant_document(VARIANT, DISEASES, [], ("Pathogenic", "2026-09-01"))

    assert "Classification history: previously Pathogenic until 2026-09-01." in text


def test_previous_significance_omits_entries_whose_classification_did_not_really_change():
    """Silver's SCD2 closes a row when `clinicalsignificance`, `reviewstatus` or
    `lastevaluated` changes — not only on a real reclassification. Allele 1's
    review status refreshed but its classification stayed "Pathogenic" in both
    rows: it must not show up as reclassification history. Allele 2's
    classification genuinely changed and must."""
    variants = pl.DataFrame([
        {"alleleid": "1", "clinicalsignificance": "Pathogenic",
         "valid_from": "2026-08-01", "valid_to": "2026-09-01", "is_current": False},
        {"alleleid": "1", "clinicalsignificance": "Pathogenic",
         "valid_from": "2026-09-01", "valid_to": None, "is_current": True},
        {"alleleid": "2", "clinicalsignificance": "Pathogenic",
         "valid_from": "2026-08-01", "valid_to": "2026-09-01", "is_current": False},
        {"alleleid": "2", "clinicalsignificance": "Benign",
         "valid_from": "2026-09-01", "valid_to": None, "is_current": True},
    ])

    history = _previous_significance(variants)

    assert "1" not in history
    assert history["2"] == ("Pathogenic", "2026-09-01")


def test_render_variant_document_omits_sections_that_have_no_content():
    text = render_variant_document(VARIANT, [], [], None)

    assert "Associated conditions" not in text
    assert "Related phenotypes" not in text
    assert "Classification history" not in text


def test_render_variant_document_omits_the_dbsnp_clause_for_the_minus_one_sentinel():
    """Silver deliberately keeps ClinVar's `-1` sentinel for "no dbSNP id". Printing
    it literally would read "dbSNP rs-1.", which is wrong; the clause must be
    omitted instead, while the rest of the line (ClinVar Variation ID, Type) stays."""
    variant = {**VARIANT, "rs_dbsnp": -1}

    text = render_variant_document(variant, [], [], None)

    assert "dbSNP" not in text
    assert "rs-1" not in text
    assert "ClinVar Variation ID 37392" in text


def test_render_variant_document_omits_last_evaluated_when_it_is_the_dash_sentinel():
    variant = {**VARIANT, "lastevaluated": "-"}

    text = render_variant_document(variant, [], [], None)

    assert "Last evaluated" not in text


def test_render_variant_document_omits_review_status_when_it_is_the_dash_sentinel():
    variant = {**VARIANT, "reviewstatus": "-"}

    text = render_variant_document(variant, [], [], None)

    assert "Review status" not in text


def test_render_variant_document_omits_clinical_significance_when_it_is_the_dash_sentinel():
    variant = {**VARIANT, "clinicalsignificance": "-"}

    text = render_variant_document(variant, [], [], None)

    assert "Clinical significance" not in text


def test_render_variant_document_omits_the_chromosome_clause_when_cytogenetic_is_null():
    variant = {**VARIANT, "cytogenetic": None}

    text = render_variant_document(variant, [], [], None)

    assert "chromosome" not in text
    assert "None" not in text


def test_format_list_caps_and_counts_the_remainder():
    values = [f"P{i}" for i in range(MAX_PHENOTYPES + 3)]

    assert format_list(values, MAX_PHENOTYPES).endswith("; and 3 more")
    assert format_list(["A", "B"], MAX_PHENOTYPES) == "A; B"
    assert format_list([], MAX_PHENOTYPES) == ""


def test_chunk_id_changes_only_when_the_text_changes():
    first = render_variant_document(VARIANT, DISEASES, [], None)
    same = render_variant_document(VARIANT, DISEASES, [], None)
    reclassified = render_variant_document({**VARIANT, "clinicalsignificance": "Benign"}, DISEASES, [], None)

    assert chunk_id(first) == chunk_id(same)
    assert chunk_id(first) != chunk_id(reclassified)
    assert len(chunk_id(first)) == 64


def test_render_gene_document_mentions_the_gene_and_its_context():
    gene = {
        "gene_symbol": "BRCA1", "name": "BRCA1", "description": "BRCA1 DNA repair associated",
        "maplocation": "17q21.31", "summary": "This gene encodes a nuclear phosphoprotein.",
    }

    text = render_gene_document(gene, ["Hereditary breast ovarian cancer syndrome"], ["Breast carcinoma"])

    assert "Gene BRCA1" in text
    assert "This gene encodes a nuclear phosphoprotein." in text
    assert "Hereditary breast ovarian cancer syndrome" in text


def test_render_gene_document_truncates_a_long_summary_on_a_word_boundary():
    # "banana " has a 7-char period, which does not divide MAX_SUMMARY_CHARS (800)
    # evenly (800 = 114*7 + 2): character 800 falls 2 letters into the 115th
    # "banana", i.e. mid-token, so the backward search for a space is genuinely
    # exercised (unlike a period that divides 800 evenly, where the cut would
    # already land on a space).
    long_summary = "banana " * 150  # 1050 chars
    gene = {
        "gene_symbol": "BRCA1", "description": "BRCA1 DNA repair associated",
        "maplocation": "17q21.31", "summary": long_summary.strip(),
    }

    text = render_gene_document(gene, [], [])
    summary_line = text.split("\n")[1]

    assert summary_line.endswith(" …")
    assert len(summary_line) <= MAX_SUMMARY_CHARS + len(" …")
    assert not summary_line[: -len(" …")].endswith(" ")
    # Pin the exact cut point: 114 full "banana" words, trimmed of the trailing
    # partial "ba" from the 115th occurrence.
    assert summary_line == ("banana " * 114).rstrip() + " …"


def test_render_gene_document_truncates_at_the_char_cap_when_no_space_exists():
    # No space anywhere in the summary: there is no word boundary to honour within
    # MAX_SUMMARY_CHARS, so the documented fallback is a hard cut at the character
    # cap, still followed by the ellipsis.
    long_summary = "x" * 850
    gene = {
        "gene_symbol": "BRCA1", "description": "BRCA1 DNA repair associated",
        "maplocation": "17q21.31", "summary": long_summary,
    }

    text = render_gene_document(gene, [], [])
    summary_line = text.split("\n")[1]

    assert summary_line == ("x" * MAX_SUMMARY_CHARS) + " …"


def test_render_gene_document_summary_at_exactly_the_cap_is_untouched():
    exact_summary = "a" * MAX_SUMMARY_CHARS
    gene = {
        "gene_symbol": "BRCA1", "description": "BRCA1 DNA repair associated",
        "maplocation": "17q21.31", "summary": exact_summary,
    }

    text = render_gene_document(gene, [], [])
    summary_line = text.split("\n")[1]

    assert summary_line == exact_summary
    assert "…" not in summary_line


def test_render_gene_document_leaves_a_short_summary_untouched():
    gene = {
        "gene_symbol": "BRCA1", "description": "BRCA1 DNA repair associated",
        "maplocation": "17q21.31", "summary": "This gene encodes a nuclear phosphoprotein.",
    }

    text = render_gene_document(gene, [], [])

    assert "This gene encodes a nuclear phosphoprotein." in text
    assert "…" not in text


def test_render_gene_document_truncation_is_deterministic():
    gene = {
        "gene_symbol": "BRCA1", "description": "BRCA1 DNA repair associated",
        "maplocation": "17q21.31", "summary": "word " * 200,
    }

    first = render_gene_document(gene, [], [])
    second = render_gene_document(gene, [], [])

    assert first == second


def test_previous_significance_ties_are_broken_by_maintain_order_not_arbitrarily():
    """Two closed rows for the same allele, tied on `valid_to`: `sort(...,
    maintain_order=True).group_by(..., maintain_order=True).last()` guarantees the
    row that appears last in `variants`' own row order wins, not whichever row an
    unordered hash-based group_by happens to visit last. Pins the deterministic
    contract so the chosen tie-break can never silently flip and churn the
    document hash for ~97 000 documents on a replay."""
    variants = pl.DataFrame([
        {"alleleid": "1", "clinicalsignificance": "Pathogenic",
         "valid_from": "2026-08-01", "valid_to": "2026-09-01", "is_current": False},
        {"alleleid": "1", "clinicalsignificance": "Likely pathogenic",
         "valid_from": "2026-08-15", "valid_to": "2026-09-01", "is_current": False},
        {"alleleid": "1", "clinicalsignificance": "Benign",
         "valid_from": "2026-09-01", "valid_to": None, "is_current": True},
    ])

    history = _previous_significance(variants)

    assert history["1"] == ("Likely pathogenic", "2026-09-01")


def _seed_silver(
    lake, panel="brca", significance="Pathogenic", extra_variant=False,
    inheritance_modes=("Autosomal dominant",),
):
    """Silver minimal mais complet pour un run Gold : un variant, sa maladie, son
    gène, un phénotype."""
    gene = BREAST_CANCER_GENES[0]
    variants = [{
        "alleleid": "1", "name": f"NM_007294.4({gene}):c.116G>A", "genesymbol": gene,
        "cytogenetic": "17q21.31", "chromosome": "17", "rs_dbsnp": 80357498,
        "variationid": "37392",
        "type": "single nucleotide variant", "clinicalsignificance": significance,
        "clinsigsimple": "1",
        "reviewstatus": "criteria provided", "numbersubmitters": "21",
        "lastevaluated": "Jul 14, 2026", "hgvs_c": "c.116G>A", "hgvs_p": "p.Cys39Tyr",
        "panel": panel, "valid_from": "2026-09-01", "valid_to": None, "is_current": True,
    }]
    if extra_variant:
        variants.append({**variants[0], "alleleid": "2", "variationid": "37393"})
    # `schema_overrides` : sur ce fixture d'un seul variant (par défaut), une colonne
    # entièrement `None` (`valid_to`) s'infère en `Null`, type que `write_delta`
    # refuse — même raison que documentée dans `bronze_to_silver.py` pour les
    # colonnes Silver réelles ; non mentionné dans la maquette du brief, corrigé ici
    # pour que le fixture écrive réellement.
    _write_silver_snapshot(
        pl.DataFrame(variants, schema_overrides={"valid_to": pl.Utf8}),
        f"{lake}/silver/clinvar_variant", panel)
    _write_silver_snapshot(
        pl.DataFrame([{"alleleid": v["alleleid"], "gene_symbol": gene, "panel": panel} for v in variants]),
        f"{lake}/silver/clinvar_variant_gene", panel)
    _write_silver_snapshot(
        pl.DataFrame(
            [{"alleleid": "1", "disease_name": "Hereditary cancer", "medgen_cui": "C1",
              "omim_id": "604370", "orpha_id": None, "mondo_id": None, "panel": panel}],
            schema_overrides={"orpha_id": pl.Utf8, "mondo_id": pl.Utf8}),
        f"{lake}/silver/clinvar_variant_disease", panel)
    _write_silver_snapshot(
        pl.DataFrame(
            [{"cui": "C1", "mode_inheritance": mode, "panel": panel} for mode in inheritance_modes],
            schema_overrides={"mode_inheritance": pl.Utf8}),
        f"{lake}/silver/medgen_inheritance", panel)
    # Ruling coordinateur (tâche 4) : la tâche 6 (silver_to_gold_analytique) réutilise
    # ce même fixture et lit medgen_concept pour la dimension maladie. Semé ici pour
    # que ce fixture reste le point d'entrée unique des deux cibles Gold.
    _write_silver_snapshot(
        pl.DataFrame([{"cui": "C1", "clinical_summary": "A hereditary cancer predisposition syndrome.",
                       "panel": panel}]),
        f"{lake}/silver/medgen_concept", panel)
    _write_silver_snapshot(
        pl.DataFrame([{"gene_symbol": gene, "name": gene, "description": "BRCA1 DNA repair associated",
                       "maplocation": "17q21.31", "summary": "Encodes a nuclear phosphoprotein.",
                       "panel": panel}]),
        f"{lake}/silver/ncbi_gene", panel)
    _write_silver_snapshot(
        pl.DataFrame(
            [{"gene_symbol": gene, "hpo_id": "HP:0003002", "hpo_name": "Breast carcinoma",
              "disease_id": "OMIM:604370", "frequency": None, "ncbi_gene_id": "672",
              "panel": panel}],
            schema_overrides={"frequency": pl.Utf8}),
        f"{lake}/silver/hpo_gene_phenotype", panel)
    _write_silver_snapshot(
        pl.DataFrame(
            [{"gene_symbol": gene, "hpo_id": "HP:0003002", "hpo_name": "Breast carcinoma",
              "definition": "A tumor of the breast.", "synonyms": [], "xrefs": [],
              "panel": panel}],
            schema_overrides={"synonyms": pl.List(pl.Utf8), "xrefs": pl.List(pl.Utf8)}),
        f"{lake}/silver/hpo_term", panel)
    return lake


def test_silver_to_gold_rag_writes_one_document_per_variant_and_gene(tmp_path):
    lake = _seed_silver(f"file://{tmp_path}/lake")

    silver_to_gold_rag("2026-09-01", "brca", lake_uri=lake)

    docs = pl.read_delta(documents_uri(lake))
    assert docs.filter(pl.col("doc_type") == "variant")["doc_id"].to_list() == ["clinvar:1"]
    assert docs.filter(pl.col("doc_type") == "gene").height == len(BREAST_CANCER_GENES)
    variant = docs.filter(pl.col("doc_id") == "clinvar:1").row(0, named=True)
    assert variant["clinvar_url"] == "https://www.ncbi.nlm.nih.gov/clinvar/variation/37392/"
    assert variant["source_version"] == "2026-09"
    assert "Hereditary cancer (OMIM 604370, inheritance: Autosomal dominant)" in variant["text"]
    assert "Breast carcinoma" in variant["text"]


def test_silver_to_gold_rag_replay_changes_nothing(tmp_path):
    lake = _seed_silver(f"file://{tmp_path}/lake")
    silver_to_gold_rag("2026-09-01", "brca", lake_uri=lake)
    before = pl.read_delta(documents_uri(lake)).sort("doc_id")

    silver_to_gold_rag("2026-09-01", "brca", lake_uri=lake)

    assert pl.read_delta(documents_uri(lake)).sort("doc_id").equals(before)


def test_build_documents_disease_order_is_stable_across_calls_with_tied_sort_keys(tmp_path):
    """`diseases_of` sorts `clinvar_variant_disease` on (disease_name, medgen_cui)
    before folding it into a per-allele list; that order feeds directly into the
    rendered "Associated conditions" clause and therefore the document hash. Two
    rows tied on both sort keys (same disease, same CUI, different OMIM id) must
    keep a fixed relative order across repeated builds — an unstable tie-break
    would churn the hash of every document carrying that disease on every replay,
    for no content reason."""
    lake = f"file://{tmp_path}/lake"
    _seed_silver(lake)
    tied_diseases = pl.DataFrame(
        [
            {"alleleid": "1", "disease_name": "Hereditary cancer", "medgen_cui": "C1",
             "omim_id": "604370", "orpha_id": None, "mondo_id": None, "panel": "brca"},
            {"alleleid": "1", "disease_name": "Hereditary cancer", "medgen_cui": "C1",
             "omim_id": "999999", "orpha_id": None, "mondo_id": None, "panel": "brca"},
        ],
        schema_overrides={"orpha_id": pl.Utf8, "mondo_id": pl.Utf8},
    )
    _write_silver_snapshot(tied_diseases, f"{lake}/silver/clinvar_variant_disease", "brca")

    first = build_documents("2026-09-01", "brca", lake_uri=lake)
    second = build_documents("2026-09-01", "brca", lake_uri=lake)

    first_text = first.filter(pl.col("doc_id") == "clinvar:1").row(0, named=True)["text"]
    second_text = second.filter(pl.col("doc_id") == "clinvar:1").row(0, named=True)["text"]
    assert first_text == second_text


def test_silver_to_gold_rag_updates_a_reclassified_variant_in_place(tmp_path):
    lake = _seed_silver(f"file://{tmp_path}/lake")
    silver_to_gold_rag("2026-09-01", "brca", lake_uri=lake)
    _seed_silver(lake, significance="Benign")

    silver_to_gold_rag("2026-10-01", "brca", lake_uri=lake)

    docs = pl.read_delta(documents_uri(lake)).filter(pl.col("doc_id") == "clinvar:1")
    assert docs.height == 1
    assert "Benign" in docs.row(0, named=True)["text"]


def test_silver_to_gold_rag_deletes_documents_whose_variant_disappeared(tmp_path):
    lake = _seed_silver(f"file://{tmp_path}/lake", extra_variant=True)
    silver_to_gold_rag("2026-09-01", "brca", lake_uri=lake)
    _seed_silver(lake, extra_variant=False)

    silver_to_gold_rag("2026-10-01", "brca", lake_uri=lake)

    docs = pl.read_delta(documents_uri(lake))
    assert "clinvar:2" not in docs["doc_id"].to_list()


def test_silver_to_gold_rag_leaves_the_other_panel_untouched(tmp_path):
    lake = _seed_silver(f"file://{tmp_path}/lake")
    silver_to_gold_rag("2026-09-01", "brca", lake_uri=lake)
    documents = pl.read_delta(documents_uri(lake))
    sickle = documents.head(1).with_columns(
        pl.lit("sickle").alias("panel"), pl.lit("clinvar:999").alias("doc_id"))
    sickle.write_delta(documents_uri(lake), mode="append")

    silver_to_gold_rag("2026-10-01", "brca", lake_uri=lake)

    assert "clinvar:999" in pl.read_delta(documents_uri(lake))["doc_id"].to_list()


@pytest.mark.parametrize(
    "modes",
    [
        ("Autosomal recessive inheritance", "Autosomal dominant inheritance"),
        ("Autosomal dominant inheritance", "Autosomal recessive inheritance"),
    ],
)
def test_build_documents_cites_every_inheritance_mode_whatever_the_row_order(tmp_path, modes):
    # D-E3b-4 : la bêta-thalassémie (C0005283) a deux modes dans MedGen ; un `dict` ne gardait
    # que le dernier lu, donc un mode choisi par l'ordre des lignes.
    lake = _seed_silver(f"file://{tmp_path}/lake", inheritance_modes=modes)

    docs = build_documents("2026-09-01", "brca", lake_uri=lake)

    text = docs.filter(pl.col("doc_id") == "clinvar:1")["text"].item()
    assert (
        "Hereditary cancer (OMIM 604370, inheritance: "
        "Autosomal dominant inheritance; Autosomal recessive inheritance)"
    ) in text


def test_build_documents_ignores_a_null_inheritance_mode(tmp_path):
    lake = _seed_silver(f"file://{tmp_path}/lake", inheritance_modes=(None, "Autosomal dominant"))

    docs = build_documents("2026-09-01", "brca", lake_uri=lake)

    text = docs.filter(pl.col("doc_id") == "clinvar:1")["text"].item()
    assert "Hereditary cancer (OMIM 604370, inheritance: Autosomal dominant)" in text


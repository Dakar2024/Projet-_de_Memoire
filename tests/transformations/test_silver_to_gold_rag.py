import pytest

from transformations.silver_to_gold_rag import (
    MAX_PHENOTYPES,
    MAX_SUMMARY_CHARS,
    chunk_id,
    format_list,
    render_gene_document,
    render_variant_document,
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


def test_render_variant_document_omits_sections_that_have_no_content():
    text = render_variant_document(VARIANT, [], [], None)

    assert "Associated conditions" not in text
    assert "Related phenotypes" not in text
    assert "Classification history" not in text


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

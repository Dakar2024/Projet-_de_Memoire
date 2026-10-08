import pytest

from RAG.src.generation.checks import check_citations, check_identifiers, check_significances
from RAG.src.retrieval.retriever import RetrievedDocument
from RAG.src.utils.errors import GenerationRejectedError

TEXT = ("Variant NM_007294.4(BRCA1):c.5266dup (p.Gln1756fs), gene BRCA1. dbSNP rs80357906. "
        "ClinVar Variation ID 17677. Clinical significance: Pathogenic. "
        "Classification history: previously Uncertain significance until 2015-01.")


def doc(doc_id="clinvar:32716", text=TEXT, sig="Pathogenic"):
    return RetrievedDocument(doc_id=doc_id, doc_type="variant", text=text, gene_symbol="BRCA1",
                             clinical_significance=sig, review_status=None, rs_dbsnp=80357906,
                             hgvs_c="c.5266dup", hgvs_p="p.Gln1756fs", clinvar_variation_id="17677",
                             clinvar_url=None, source_version="2026-09", similarity=0.9, stage="exact")


def _reason(fn, *args):
    with pytest.raises(GenerationRejectedError) as excinfo:
        fn(*args)
    return str(excinfo.value)


def test_invented_citation_is_rejected():
    assert _reason(check_citations, ["clinvar:999"], [doc()], "answered") == "citation_not_transmitted"


def test_answered_without_citation_is_rejected():
    assert _reason(check_citations, [], [doc()], "partial") == "no_citation"


def test_not_in_sources_may_cite_nothing():
    check_citations([], [doc()], "not_in_sources")


def test_invented_rs_is_rejected():
    answer = "Le variant rs80357906 (aussi rs12345) est pathogène."
    assert _reason(check_identifiers, answer, [doc()]) == "identifier_not_in_sources"


@pytest.mark.parametrize("answer", [
    "Le variant c.5266dup (p.Gln1756fs), rs80357906, est pathogène.",
    "NM_007294.4(BRCA1):c.5266dupC est décrit (ClinVar 17677).",
    "Aucun identifiant ici.",
])
def test_identifiers_present_in_documents_pass(answer):
    check_identifiers(answer, [doc()])


def test_invented_hgvs_and_variation_id_are_rejected():
    assert _reason(check_identifiers, "Voir c.68_69del.", [doc()]) == "identifier_not_in_sources"
    assert _reason(check_identifiers, "Variation ID 99999.", [doc()]) == "identifier_not_in_sources"


@pytest.mark.parametrize("answer", [
    "Ce variant est classé pathogène.",
    "Il était auparavant de signification incertaine.",
    "Pathogène selon ClinVar ; classé de signification incertaine jusqu'en 2015.",
])
def test_significances_present_in_cited_documents_pass(answer):
    check_significances(answer, [doc()])


def test_significance_not_in_cited_documents_is_rejected():
    assert _reason(check_significances, "Ce variant est bénin.", [doc()]) == "significance_not_in_sources"


def test_probably_pathogenic_is_not_confused_with_pathogenic():
    likely = doc(text="Clinical significance: Likely pathogenic.", sig="Likely pathogenic")
    check_significances("Il est probablement pathogène.", [likely])
    assert _reason(check_significances, "Il est pathogène.", [likely]) == "significance_not_in_sources"


def test_plural_and_feminine_forms_are_recognised():
    benign = doc(text="Clinical significance: Benign.", sig="Benign")
    check_significances("Ces variants sont bénins.", [benign])
    assert _reason(check_significances, "Ces variants sont pathogènes.", [benign]) == "significance_not_in_sources"


# --- tour de correction 1 ---

def _doc_text(text, sig="Pathogenic", gene="BRCA1", doc_id="clinvar:1"):
    return RetrievedDocument(doc_id=doc_id, doc_type="variant", text=text, gene_symbol=gene,
                             clinical_significance=sig, review_status=None, rs_dbsnp=None,
                             hgvs_c="c.68A>G", hgvs_p=None, clinvar_variation_id="17677",
                             clinvar_url=None, source_version="2026-09", similarity=0.9, stage="exact")


def test_escaped_gt_in_answer_is_unescaped_before_checking():
    d = _doc_text("Variant c.68A>G. Clinical significance: Pathogenic.")
    check_identifiers("Le variant c.68A&gt;G est décrit.", [d])
    assert _reason(check_identifiers, "Le variant c.69A&gt;G est décrit.", [d]) == "identifier_not_in_sources"


HISTORY_TEXT = ("Variant c.5266dup.\nClinical significance: Pathogenic.\n"
                "Classification history: previously Uncertain significance until 2015-01.")


@pytest.mark.parametrize("answer", [
    "Ce variant est de signification incertaine.",
    "Ce variant est un VUS.",
    "Ce variant est neutre.",
    "Ce variant est non pathogène.",
    "Ce variant n'est pas pathogène.",
    "Sa signification est indéterminée.",
    "Il est à risque.",
    "Il est délétère.",
    "Classé Benign.",
    "Classé Likely benign.",
    "C'est un facteur de risque.",
    "Il est pathogénique.",
    "Il est vraisemblablement pathogène.",
    "Les interprétations sont contradictoires.",
    "Ce variant n'a jamais été pathogène.",
])
def test_off_table_or_wrong_significances_are_rejected(answer):
    assert _reason(check_significances, answer, [_doc_text(HISTORY_TEXT)]) == "significance_not_in_sources"


def test_double_space_probably_pathogenic_is_not_pathogenic():
    likely = _doc_text("Clinical significance: Likely pathogenic.", sig="Likely pathogenic")
    check_significances("Il est probablement  pathogène.", [likely])
    assert _reason(check_significances, "Il est pathogène.", [likely]) == "significance_not_in_sources"


def test_history_label_allowed_only_in_a_history_sentence():
    d = _doc_text(HISTORY_TEXT)
    check_significances("Il est pathogène. Il était auparavant de signification incertaine.", [d])
    check_significances("Il a été reclassé : signification incertaine jusqu'en 2015.", [d])


def test_labels_elsewhere_in_text_are_not_allowed():
    d = _doc_text("Gene summary mentions Benign variants.\nClinical significance: Pathogenic.")
    assert _reason(check_significances, "Ce variant est bénin.", [d]) == "significance_not_in_sources"


def test_english_label_matching_the_document_passes():
    check_significances("Classé Pathogenic.", [_doc_text(HISTORY_TEXT)])


def test_conflicting_interpretations_pass_when_documented():
    d = _doc_text("Clinical significance: Conflicting classifications of pathogenicity.",
                  sig="Conflicting classifications of pathogenicity")
    check_significances("Les interprétations sont contradictoires.", [d])


@pytest.mark.parametrize("answer", ["ClinVar ID 17678", "Fiche ClinVar n° 17678", "Variation 17678",
                                    "https://www.ncbi.nlm.nih.gov/clinvar/variation/17678/"])
def test_invented_variation_ids_in_other_forms_are_rejected(answer):
    assert _reason(check_identifiers, answer, [_doc_text(HISTORY_TEXT)]) == "identifier_not_in_sources"


@pytest.mark.parametrize("answer", ["Selon ClinVar 2026, c'est décrit.", "ClinVar : 45 soumetteurs.",
                                    "Données ClinVar 2016-10-20.", "Variation ID 17677 et ClinVar ID 17677."])
def test_years_counts_and_dates_are_not_variation_ids(answer):
    check_identifiers(answer, [_doc_text(HISTORY_TEXT)])


@pytest.mark.parametrize("answer", ["Voir «c.5267dup» ici.", "Voir c.5267dup’ ici.", "Voir c.5267dup… ici.",
                                    "Voir c.5267dup ici.", "Voir « c.5267dup ».", "Voir « c.5267dup »."])
def test_french_typography_does_not_hide_invented_identifiers(answer):
    assert _reason(check_identifiers, answer, [_doc_text(HISTORY_TEXT)]) == "identifier_not_in_sources"


def test_gene_must_belong_to_a_transmitted_document():
    d = _doc_text(HISTORY_TEXT, gene="BRCA1")
    check_identifiers("Le gène BRCA1 est concerné.", [d])
    assert _reason(check_identifiers, "Le gène BRCA2 est concerné.", [d]) == "identifier_not_in_sources"


def test_out_of_panel_gene_rejected_when_answered_only():
    d = _doc_text(HISTORY_TEXT)
    assert _reason(check_identifiers, "Le gène MLH1 est concerné.", [d], "answered") == "identifier_not_in_sources"
    check_identifiers("Le gène MLH1 est hors panel.", [d], "not_in_sources")


# --- tour de correction 2 ---

def _gene_doc(text, gene, doc_id="clinvar:7"):
    return _doc_text(text, gene=gene, doc_id=doc_id)


@pytest.mark.parametrize("text, gene, answer", [
    ("Condition: Fanconi anemia, complementation group D1.", "BRCA2",
     "La maladie est Fanconi anemia, complementation group D1."),
    ("Gene summary: the protein binds RAD51 and PALB2.", "BRCA2",
     "Le gène BRCA2 se lie à RAD51 et à PALB2."),
    ("Phenotype: Decreased CD4+ T cell count.", "BRCA1",
     "Phénotype : Decreased CD4+ T cell count."),
])
def test_genes_copied_from_documents_pass(text, gene, answer):
    check_identifiers(answer, [_gene_doc(text, gene)])


def test_gene_absent_from_documents_is_rejected():
    d = _gene_doc("Variant on BRCA1.", "BRCA1")
    assert _reason(check_identifiers, "Le gène BRCA2 est concerné.", [d]) == "identifier_not_in_sources"
    assert _reason(check_identifiers, "Le gène MLH1 est concerné.", [d]) == "identifier_not_in_sources"


H = _doc_text(HISTORY_TEXT)


@pytest.mark.parametrize("answer", [
    "Ce variant est de signification incertaine, sans reclassement.",
    "Il était auparavant pathogène, il est maintenant de signification incertaine.",
    "Classé de signification incertaine avant 2019. Il est aujourd'hui pathogène.",
])
def test_history_label_needs_a_marker_before_it_in_the_same_clause(answer):
    assert _reason(check_significances, answer, [H]) == "significance_not_in_sources"


@pytest.mark.parametrize("answer", [
    "Il a d'abord été classé de signification incertaine, puis pathogène.",
    "Il était initialement de signification incertaine.",
])
def test_history_label_after_a_marker_passes(answer):
    check_significances(answer, [H])


@pytest.mark.parametrize("answer", ["Sa signification reste incertaine.", "Signification : incertaine."])
def test_uncertain_wordings_are_recognised(answer):
    assert _reason(check_significances, answer, [H]) == "significance_not_in_sources"
    uncertain = _doc_text("Clinical significance: Uncertain significance.", sig="Uncertain significance")
    check_significances(answer, [uncertain])


def test_zero_width_and_decomposed_text_cannot_hide_anything():
    assert _reason(check_identifiers, "Voir rs​12345.", [H]) == "identifier_not_in_sources"
    assert _reason(check_significances, "Il est bénin.", [H]) == "significance_not_in_sources"

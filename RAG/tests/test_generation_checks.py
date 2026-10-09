import pytest

from RAG.src.generation.checks import (
    check_citations, check_identifiers, check_no_history_narration, check_significances,
)
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
    "Ces variants sont Pathogènes.",
    "Pathogène selon ClinVar.",
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


def test_history_label_is_rejected_even_in_a_history_sentence():
    # Tour 4 : l'historique est restitué par le code, jamais raconté par le LLM.
    d = _doc_text(HISTORY_TEXT)
    for answer in ("Il est pathogène. Il était auparavant de signification incertaine.",
                   "Il a été reclassé : signification incertaine jusqu'en 2015."):
        assert _reason(check_significances, answer, [d]) == "significance_not_in_sources"


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


@pytest.mark.parametrize("answer", ["Sa signification reste incertaine.", "Signification : incertaine."])
def test_uncertain_wordings_are_recognised(answer):
    assert _reason(check_significances, answer, [H]) == "significance_not_in_sources"
    uncertain = _doc_text("Clinical significance: Uncertain significance.", sig="Uncertain significance")
    check_significances(answer, [uncertain])


def test_zero_width_and_decomposed_text_cannot_hide_anything():
    assert _reason(check_identifiers, "Voir rs​12345.", [H]) == "identifier_not_in_sources"
    assert _reason(check_significances, "Il est bénin.", [H]) == "significance_not_in_sources"


# --- tour de correction 3 ---

@pytest.mark.parametrize("answer", [
    "Sa signification clinique est encore incertaine.",
    "La signification de ce variant, incertaine, est discutée.",
])
def test_lone_uncertain_in_a_significance_sentence_is_checked(answer):
    assert _reason(check_significances, answer, [H]) == "significance_not_in_sources"


@pytest.mark.parametrize("answer", ["Sa signification clinique est encore incertaine.",
                                    "La signification de ce variant, incertaine, est discutée."])
def test_standalone_uncertain_is_accepted_for_an_uncertain_document(answer):
    check_significances(answer, [_doc_text("Clinical significance: Uncertain significance.",
                                           sig="Uncertain significance")])


@pytest.mark.parametrize("answer", ["Il est b⁠énin.", "Il est bé­nin.", "Voir ｒｓ12345."])
def test_compatibility_and_format_characters_cannot_hide_anything(answer):
    if "12345" in answer:
        assert _reason(check_identifiers, answer, [H]) == "identifier_not_in_sources"
    else:
        assert _reason(check_significances, answer, [H]) == "significance_not_in_sources"


def test_soft_hyphen_and_word_joiner_inside_rs_are_rejected():
    for answer in ("Voir rs⁠12345.", "Voir rs­12345."):
        assert _reason(check_identifiers, answer, [H]) == "identifier_not_in_sources"


# --- tour 4 : l'historique est restitué par le code, plus par le LLM ---

@pytest.mark.parametrize("answer", [
    "Il était auparavant de signification incertaine.",
    "Pathogène selon ClinVar ; classé de signification incertaine jusqu'en 2015.",
    "Ce variant est de signification incertaine jusqu'en 2015.",
    "Il fut de signification incertaine jusqu'en 2015-01.",
    "Il fut de signification incertaine jusqu'au 1er janvier 2015.",
    "Il fut de signification incertaine jusqu'en septembre 2016.",
    "Avant 2015, il était classé de signification incertaine.",
    "Auparavant, il était classé de signification incertaine.",
    "Jusqu'en 2015-01, il était de signification incertaine.",
    "Il a d'abord été classé de signification incertaine, puis pathogène.",
    "Il était initialement de signification incertaine.",
    "Comme indiqué précédemment, il est de signification incertaine.",
    "Il était auparavant pathogène, il est maintenant de signification incertaine.",
    "Ce variant a été reclassé en signification incertaine.",
    "Historique : previously Uncertain significance until 2015-01.",
])
def test_narrated_classification_history_is_rejected(answer):
    assert _reason(check_significances, answer, [H]) == "significance_not_in_sources"


def test_current_significance_passes_although_the_document_has_a_history():
    check_significances("Ce variant est pathogène, classé Pathogenic.", [H])


def test_composite_significance_is_split():
    d = _doc_text("Clinical significance: Pathogenic/Likely pathogenic.", sig="Pathogenic/Likely pathogenic")
    check_significances("Il est pathogène ou probablement pathogène.", [d])
    assert _reason(check_significances, "Il est bénin.", [d]) == "significance_not_in_sources"


@pytest.mark.parametrize("dash", ["\u2010", "\u2011", "\u2012", "\u2013", "\u2014", "\u2015", "\u2212",
                                  "\u2e3a", "\u2e3b", "\u02d7", "\u2796", "\ufe58"])
def test_unicode_dashes_cannot_hide_an_invented_intronic_hgvs(dash):
    d = _doc_text("Variant NM_007294.4(BRCA1):c.68-2A>G. Clinical significance: Pathogenic.")
    check_identifiers(f"Le variant c.68{dash}2A>G est décrit.", [d])
    answer = f"Le variant c.5266{dash}2A>G est décrit."
    assert _reason(check_identifiers, answer, [d]) == "identifier_not_in_sources"


@pytest.mark.parametrize("answer", [
    "Il était auparavant pathogène jusqu'en 2015-01.",
    "Il a été reclassé pathogène en 2019.",
    "Il était classé ainsi jusqu’au 2015-01.",
    "Initialement, la classification différait.",
    "Comme indiqué précédemment, il est pathogène.",
    "Une classification antérieure existe.",
    "Il était anciennement décrit autrement.",
    "Il est Re­classé.",
])
def test_narrated_history_is_rejected(answer):
    # « comme indiqué précédemment » est rejeté aussi : choix prudent, accepté.
    assert _reason(check_no_history_narration, answer) == "history_narrated"


@pytest.mark.parametrize("answer", [
    "Le variant rs80357906 est pathogène (Pathogenic), revu par un panel d'experts.",
    "Ce variant est associé au cancer du sein héréditaire, évalué en 2019.",
])
def test_neutral_answer_passes_the_history_check(answer):
    check_no_history_narration(answer)


# --- vague finale : négation n'importe où dans la phrase, qualificatifs hors table ---

PATHOGENIC = _doc_text("Clinical significance: Pathogenic.")


@pytest.mark.parametrize("answer", [
    "Ce variant est inoffensif.",
    "Ce variant est sans danger.",
    "Ce variant est sans risque pour la patiente.",
    "Ce variant est sans conséquence.",
    "Ce variant est anodin.",
    "Ce variant est bénéfique.",
    "Il ne s'agit en aucun cas d'un variant pathogène.",
    "Ce variant n'a rien de pathogène.",
    "Ce variant est pathogène selon un laboratoire, mais pas selon les autres.",
    "Ce variant pathogène ne l'est que chez l'homme.",
    "Ce variant est classé incertain.",
    "Son effet reste incertain, il est pathogène.",
    "Classé Uncertain-significance.",
    "Classé Uncertain_significance.",
    "Classé Likely-benign.",
])
def test_negations_anywhere_and_off_table_qualifiers_are_rejected(answer):
    assert _reason(check_significances, answer, [PATHOGENIC]) == "significance_not_in_sources"


@pytest.mark.parametrize("answer", [
    "Ce variant est classé pathogène (statut de revue : reviewed by expert panel).",
    "Le variant rs80357906 est pathogène. ClinVar ne documente pas de phénotype pour ce variant.",
    "Pathogène selon ClinVar.",
    "Classé Pathogenic.",
])
def test_typical_correct_answers_are_still_accepted(answer):
    check_significances(answer, [PATHOGENIC])


def test_lone_uncertain_matches_an_uncertain_document_and_english_label_with_dash():
    uncertain = _doc_text("Clinical significance: Uncertain significance.", sig="Uncertain significance")
    check_significances("Ce variant est classé incertain.", [uncertain])
    check_significances("Classé Uncertain-significance.", [uncertain])


# --- correctifs résiduels : formules de statut ClinVar masquées avant le test de négation ---

REVIEWED = _doc_text("Clinical significance: Pathogenic. "
                     "Review status: criteria provided, multiple submitters, no conflicts.")
NON_SPHEROCYTIC = _doc_text("Clinical significance: Pathogenic. "
                            "Condition: Anemia, nonspherocytic hemolytic.", gene="G6PD")


@pytest.mark.parametrize("answer", [
    "Ce variant est pathogène (statut : critères fournis, plusieurs soumissionnaires, aucun conflit).",
    "Le variant est pathogène, sans conflit. ClinVar ne documente pas de phénotype pour ce variant.",
    "Le variant est pathogène, sans conflits.",
    "Variants pathogènes : c.5266dup, c.68A>G (et d'autres variantes non listées ici)",
    "Variants pathogènes : c.5266dup (et d’autres variants non listés ici)",
    "Pathogène (aucun critère d'évaluation fourni).",
    "Pathogène, aucun critère fourni.",
    "Pathogène, aucune critères d’évaluation fournies.",
    "Pathogène, ClinVar ne documente pas de phénotypes pour ce variant",
])
def test_clinvar_review_status_phrases_do_not_trigger_the_negation_rule(answer):
    check_significances(answer, [REVIEWED])


def test_non_spherocytic_disease_name_does_not_trigger_the_negation_rule():
    check_significances("Variant pathogène associé à l'anémie hémolytique non sphérocytaire.", [NON_SPHEROCYTIC])
    check_significances("Variant pathogène associé à l'anémie hémolytique non-sphérocytaire.", [NON_SPHEROCYTIC])


@pytest.mark.parametrize("answer", [
    "Ce variant est inoffensif.",
    "Ce variant est sans danger.",
    "Il ne s'agit en aucun cas d'un variant pathogène.",
    "Ce variant n'a rien de pathogène.",
    "Ce variant est pathogène selon un laboratoire, mais pas selon les autres.",
    "Ce variant est classé incertain.",
    "Classé Uncertain-significance.",
    "Ce variant n'est pas pathogène.",
    "Ce variant est non listé comme pathogène.",
    "Aucun conflit, il n'est pas pathogène.",
    "Aucun conflit : il est non pathogène.",
    "Sans conflit, ce variant n'est pas listé comme pathogène.",
])
def test_negations_are_still_rejected_next_to_masked_phrases(answer):
    assert _reason(check_significances, answer, [REVIEWED]) == "significance_not_in_sources"

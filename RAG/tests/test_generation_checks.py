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
    "Variants pathogènes : c.5266dup et d'autres variants non listés ici.",
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
    "Ce variant non listé ici comme pathogène par ClinVar.",
    "Ce variant est un des variants non listés ici comme pathogènes.",
    "Les variants non listés ici comme pathogènes incluent ce variant.",
])
def test_negations_are_still_rejected_next_to_masked_phrases(answer):
    assert _reason(check_significances, answer, [REVIEWED]) == "significance_not_in_sources"


# --- Éléments déclencheurs attachés aux rejets (diagnostic hors ligne) ---------------------

def _detail(fn, *args, **kwargs):
    with pytest.raises(GenerationRejectedError) as excinfo:
        fn(*args, **kwargs)
    return str(excinfo.value), excinfo.value.detail


def test_detail_lists_the_untransmitted_citation():
    code, detail = _detail(check_citations, ["clinvar:32716", "clinvar:999"], [doc()], "answered")
    assert (code, detail) == ("citation_not_transmitted", ["clinvar:999"])


def test_detail_lists_the_invented_identifiers():
    code, detail = _detail(check_identifiers, "Le variant rs80357906 (aussi rs12345) est pathogène.", [doc()])
    assert code == "identifier_not_in_sources"
    assert detail == ["rs12345"]


def test_detail_lists_the_invented_variation_id_and_gene():
    _, detail = _detail(check_identifiers, "ClinVar Variation ID 99999 du variant.", [doc()])
    assert detail == ["ClinVar 99999"]
    _, detail = _detail(check_identifiers, "Le gène TP53 est concerné.", [doc()])
    assert detail == ["gène TP53"]


def test_detail_gives_the_sentence_with_the_negation():
    _, detail = _detail(check_significances, "Ce variant n'est pas pathogène.", [doc()])
    assert len(detail) == 1 and "n'est pas pathogène" in detail[0] and "négation" in detail[0]


def test_detail_names_the_unsourced_significance_term():
    _, detail = _detail(check_significances, "Ce variant est bénin.", [doc()])
    assert len(detail) == 1 and "bénin" in detail[0] and "Ce variant est bénin" in detail[0]


def test_detail_names_the_off_table_qualifier():
    _, detail = _detail(check_significances, "Ce variant est délétère.", [doc()])
    assert detail == ["qualificatif hors table : délétère"]


def test_detail_names_the_history_marker():
    _, detail = _detail(check_no_history_narration, "Il était auparavant incertain.")
    assert detail == ["marqueur d'historique : auparavant"]


def test_explain_rejection_matches_the_check_chain():
    from RAG.src.generation.checks import explain_rejection
    d = doc()
    assert explain_rejection("Le variant est pathogène.", [d], ["clinvar:32716"], "answered") is None
    assert explain_rejection("Le variant rs12345 est pathogène.", [d], ["clinvar:32716"], "answered") == {
        "reason": "identifier_not_in_sources", "detail": ["rs12345"]}
    assert explain_rejection("Aucun document.", [d], [], "answered")["reason"] == "no_citation"
    # not_in_sources : texte libre contrôlé contre aucun document, sans exigence de citation.
    assert explain_rejection("Voir rs80357906.", [d], [], "not_in_sources") == {
        "reason": "identifier_not_in_sources", "detail": ["rs80357906"]}
    assert explain_rejection("   ", [d], [], "answered") == {"reason": "empty_answer", "detail": []}


# --- Étiquettes de documents (D1, D2…) dans le texte ---------------------------------------
from RAG.src.generation.checks import check_document_labels  # noqa: E402


@pytest.mark.parametrize("answer", [
    "Le variant est pathogène (D1).", "Selon le document D2, il est pathogène.", "d1 : pathogène.",
    "Voir D1, D2 et D3.", "Source : [D1]",
    "Le variant est pathogène (D1, D2).", "Pathogène (D1 ; D3).", "Pathogène (voir D2).", "Pathogène [D2].",
    "Selon la fiche D 1, il est pathogène.", "D'après les documents D1 et D2.", "Cf. D3.", "Pathogène (d1).",
    "Les sources D1, D2 le disent.", "Pathogène ( D 2 ).",
])
def test_document_label_in_text_is_rejected(answer):
    assert _reason(check_document_labels, answer, [doc(), doc("clinvar:2"), doc("clinvar:3")]) == "document_label_in_text"


@pytest.mark.parametrize("answer", [
    "Le variant est pathogène.", "Taille 1D3 non concernée.", "Le gène RAD51D est cité.",
    "Vitamine D3 hors sujet.",  # D3 n'est pas une étiquette quand un seul document est transmis
])
def test_text_without_a_transmitted_label_passes(answer):
    check_document_labels(answer, [doc()])


@pytest.mark.parametrize("answer", [
    "La cycline D1 est surexprimée.", "Un déficit en vitamine D3.", "Le récepteur D2 de la dopamine.",
    "Le groupe D de complémentation.", "Variant p.Asp1 et p.Asp12 hors sujet.", "La protéine D1 régule le cycle.",
    "Fanconi anemia complementation group D1 et D2.",
])
def test_medical_terms_that_look_like_labels_are_not_rejected(answer):
    check_document_labels(answer, [doc(), doc("clinvar:2"), doc("clinvar:3")])


def test_a_label_lookalike_copied_from_the_documents_is_not_a_label():
    d = doc(text=TEXT + " Associated conditions: Fanconi anemia complementation group D1.")
    check_document_labels("Fanconi anemia complementation group D1.", [d])
    assert _reason(check_document_labels, "Voir D1.", [doc()]) == "document_label_in_text"


def test_real_variation_id_of_the_card_is_still_accepted_and_the_internal_id_rejected():
    check_identifiers("Variant (ClinVar 17677) pathogène.", [doc()])
    assert _reason(check_identifiers, "Variant (ClinVar 32716).", [doc()]) == "identifier_not_in_sources"


# --- « pas de conflit » (statut de revue) et termes de signification dans un nom de maladie ---

@pytest.mark.parametrize("answer", [
    "Variant pathogène, statut de revue : critères fournis, plusieurs contributeurs, pas de conflit.",
    "Variant pathogène (pas de conflits).",
    "Variant pathogène, pas de conflit d'interprétation.",
    "Variant pathogène, Pas de conflits d’interprétations.",
    "Variant pathogène, sans conflit d'interprétation.",
    "Variant pathogène, aucun conflit d'interprétation.",
])
def test_no_conflict_forms_of_the_review_status_do_not_trigger_the_negation_rule(answer):
    check_significances(answer, [REVIEWED])


@pytest.mark.parametrize("answer", [
    "Pas de conflit, il n'est pas pathogène.",
    "Pas de conflit : il est non pathogène.",
    "Pas de conflit d'interprétation, ce variant n'est pas listé comme pathogène.",
    "Sans conflits, ce variant est bénin.",
    "Pas de conflit, ce variant est pathogène mais pas selon un laboratoire.",
    "Ce variant n'est pas pathogène, pas de conflit.",
    "Pas de conflit.",  # sans terme de signification : rien à contrôler, mais aucune régression
])
def test_no_conflict_mask_covers_only_the_phrase_itself(answer):
    if answer == "Pas de conflit.":
        check_significances(answer, [REVIEWED])
        return
    assert _reason(check_significances, answer, [REVIEWED]) == "significance_not_in_sources"


BENIGN_NAME = _doc_text(
    "Clinical significance: Pathogenic.\nAssociated conditions: Benign familial hematuria (OMIM 141200, "
    "inheritance: Autosomal dominant); Cowden syndrome.\nRelated phenotypes (HPO): Hematuria; Benign "
    "hereditary chorea.")


@pytest.mark.parametrize("answer", [
    "Variant pathogène associé à Benign familial hematuria et au syndrome de Cowden.",
    "Variant pathogène, condition : benign familial hematuria.",
    "Variant pathogène, phénotypes : Hematuria, Benign hereditary chorea.",
    "Variant pathogène associé à BENIGN  FAMILIAL   HEMATURIA.",
])
def test_a_significance_term_inside_a_verbatim_disease_name_is_not_counted(answer):
    check_significances(answer, [BENIGN_NAME])


@pytest.mark.parametrize("answer", [
    "Ce variant est bénin et associé à Benign familial hematuria.",
    "Variant pathogène associé à Benign familial hematuria ; il est bénin.",
    "Variant pathogène, condition : Benign familial.",  # nom incomplet : non neutralisé
    "Variant pathogène, condition : syndrome familial bénin d'hématurie.",  # traduction : non neutralisée
    "Variant pathogène, condition : Benign.",  # un mot isolé ne neutralise rien
    "Variant pathogène associé à Benign familial hematuria, qui n'est pas bénin.",
    "Variant pathogène associé à non-Benign familial hematuria.",
])
def test_only_the_exact_disease_name_portion_is_neutralised(answer):
    assert _reason(check_significances, answer, [BENIGN_NAME]) == "significance_not_in_sources"


def test_a_disease_name_of_an_uncited_document_neutralises_nothing():
    other = _doc_text("Clinical significance: Pathogenic.", doc_id="clinvar:2")
    assert _reason(check_significances, "Variant pathogène associé à Benign familial hematuria.",
                   [other]) == "significance_not_in_sources"


def test_the_translated_name_of_case_c20_stays_rejected():
    # P1-C20 : « excroissances bénignes » est une traduction du modèle, absente des fiches
    # (Macrocephaly-autism syndrome) : correctement rejetée, la règle ne porte que sur le mot à mot.
    d = _doc_text("Clinical significance: Uncertain significance. Associated conditions: Macrocephaly-autism "
                  "syndrome; Cowden syndrome.", sig="Uncertain significance", gene="PTEN")
    answer = ("Variantes de signification incertaine, associées au syndrome d'excroissances bénignes avec "
              "macrocéphalie (Macrocephaly-autism syndrome).")
    assert _reason(check_significances, answer, [d]) == "significance_not_in_sources"


# --- C1 (revue finale n° 2) : identifiant ↔ document cité ↔ signification -------------------
# Deux fiches de variants distincts : c.5266dup pathogène (doc()), c.4837A>G bénin, et une
# troisième probablement pathogène. Réponses réalistes, sur le modèle des réponses acceptées de
# la recette (listes à puces « X – signification clinique : … », « tandis que », « respectivement »).
BENIGN_TEXT = ("Variant NM_007294.4(BRCA1):c.4837A>G (p.Ser1613Gly), gene BRCA1. dbSNP rs1799966. "
               "ClinVar Variation ID 41818. Clinical significance: Benign.")
LIKELY_TEXT = ("Variant NM_007294.4(BRCA1):c.5123C>A (p.Ala1708Glu), gene BRCA1. dbSNP rs28897696. "
               "ClinVar Variation ID 55449. Clinical significance: Likely pathogenic.")


def variant_doc(doc_id, text, sig, hgvs_c, hgvs_p, rs, vid):
    return RetrievedDocument(doc_id=doc_id, doc_type="variant", text=text, gene_symbol="BRCA1",
                             clinical_significance=sig, review_status=None, rs_dbsnp=rs,
                             hgvs_c=hgvs_c, hgvs_p=hgvs_p, clinvar_variation_id=vid,
                             clinvar_url=None, source_version="2026-09", similarity=0.9, stage="exact")


PATHO = doc()
BENIGN = variant_doc("clinvar:999", BENIGN_TEXT, "Benign", "c.4837A>G", "p.Ser1613Gly", 1799966, "41818")
LIKELY = variant_doc("clinvar:888", LIKELY_TEXT, "Likely pathogenic", "c.5123C>A", "p.Ala1708Glu", 28897696, "55449")
ALL3 = [PATHO, BENIGN, LIKELY]
ALL3_IDS = [d.doc_id for d in ALL3]


def _verdict(answer, documents=ALL3, citations=ALL3_IDS, status="answered"):
    from RAG.src.generation.checks import explain_rejection
    explanation = explain_rejection(answer, documents, citations, status)
    return explanation and explanation["reason"]


def test_reviewer_probe_benign_variant_called_pathogenic_with_the_other_card_cited_is_rejected():
    """Sonde probe5 : le variant nommé vient d'un document transmis mais NON cité."""
    answer = "Le variant c.4837A>G (rs1799966) est pathogène."
    assert _verdict(answer, [PATHO, BENIGN], [PATHO.doc_id]) == "identifier_not_cited"


@pytest.mark.parametrize("answer", [
    "Le variant c.4837A>G (rs1799966) est pathogène.",
    "Le variant rs1799966 est pathogène.",
    "Le variant p.Ser1613Gly est pathogène.",
    "Le variant ClinVar Variation ID 41818 est pathogène.",
])
def test_every_variant_identifier_must_belong_to_a_cited_document(answer):
    assert _verdict(answer, [PATHO, BENIGN], [PATHO.doc_id]) == "identifier_not_cited"


def test_the_same_answer_citing_its_own_card_with_its_own_significance_passes():
    assert _verdict("Le variant c.4837A>G (rs1799966) est bénin.", [PATHO, BENIGN], [BENIGN.doc_id]) is None


def test_a_named_variant_with_the_significance_of_another_cited_card_is_rejected():
    """Les deux fiches sont citées : « pathogène » est bien dans les documents cités, mais pas
    dans celui du variant nommé."""
    answer = "Le variant c.4837A>G (rs1799966) est pathogène."
    assert _verdict(answer, [PATHO, BENIGN], [PATHO.doc_id, BENIGN.doc_id]) == "significance_not_in_sources"


def test_genes_may_still_come_from_transmitted_documents_only():
    gene_doc = RetrievedDocument(doc_id="gene:BRCA1", doc_type="gene", text="Gene BRCA1 interacts with RAD51.",
                                 gene_symbol="BRCA1", clinical_significance=None, review_status=None,
                                 rs_dbsnp=None, hgvs_c=None, hgvs_p=None, clinvar_variation_id=None,
                                 clinvar_url=None, source_version="2026-09", similarity=0.9, stage="exact")
    assert _verdict("Le variant c.5266dup de BRCA1 est pathogène ; BRCA1 interagit avec RAD51.",
                    [PATHO, gene_doc], [PATHO.doc_id]) is None


@pytest.mark.parametrize("answer", [
    # Liste à puces, un variant et sa signification par ligne (forme des réponses de la recette).
    "Variants répertoriés :\n- NM_007294.4(BRCA1):c.5266dup (p.Gln1756fs) – signification clinique : pathogène – "
    "statut de révision : reviewed by expert panel.\n- NM_007294.4(BRCA1):c.4837A>G (p.Ser1613Gly) – "
    "signification clinique : bénin.\n- NM_007294.4(BRCA1):c.5123C>A (p.Ala1708Glu) – probablement pathogène.",
    # Même liste sans point final : une seule « phrase », les puces ne sont pas découpées.
    "Variants :\n- c.5266dup : pathogène\n- c.4837A>G : bénin\n- c.5123C>A : probablement pathogène",
    "Le variant c.5266dup (pathogène) et le variant c.4837A>G (bénin) sont cités.",
    "Le variant c.5266dup est pathogène, tandis que le variant c.4837A>G (rs1799966) est bénin.",
    "Une variante (c.4837A>G, rs1799966) est classée bénin, tandis que les variantes c.5266dup (p.Gln1756fs) "
    "et c.5123C>A sont respectivement classées pathogène et probablement pathogène.",
    "Les variants c.5266dup et c.4837A>G sont respectivement pathogène et bénin.",
    "Les variants c.5266dup et c.5123C>A sont pathogène ou probablement pathogène.",
    "Les variantes classées comme pathogène ou probablement pathogène sont :\n- c.5123C>A – signification "
    "clinique : probablement pathogène ;\n- c.5266dup – signification clinique : pathogène.",
    "Les variants pathogènes sont c.5266dup (rs80357906).",
    "Le variant c.5266dup est un variant pathogène, c.4837A>G un variant bénin.",
    # Forme de la recette P1-B02 : en-tête, un variant annoté entre parenthèses, puis « d'autres ».
    "Les variantes répertoriées comme pathogènes sont : NM_007294.4(BRCA1):c.5266dup (p.Gln1756fs), "
    "c.4837A>G (p.Ser1613Gly, bénin) et d'autres variantes probablement pathogènes.",
    "Les variantes répertoriées comme pathogènes sont : c.5266dup, c.4837A>G (bénin), rs80357906.",
])
def test_correct_multi_variant_answers_pass(answer):
    assert _verdict(answer) is None


@pytest.mark.parametrize("answer", [
    "Variants :\n- c.5266dup : bénin\n- c.4837A>G : pathogène",
    "Variants répertoriés :\n- NM_007294.4(BRCA1):c.5266dup – signification clinique : pathogène.\n"
    "- NM_007294.4(BRCA1):c.4837A>G – signification clinique : pathogène.",
    "Le variant c.5266dup (bénin) et le variant c.4837A>G (pathogène) sont cités.",
    "Le variant c.5266dup est bénin, tandis que le variant c.4837A>G (rs1799966) est pathogène.",
    "Les variants c.5266dup et c.4837A>G sont respectivement bénin et pathogène.",
    "Les variants c.5266dup et c.4837A>G sont pathogènes.",
    "Les variants pathogènes sont c.5266dup et c.4837A>G.",
    "Le variant c.5266dup est pathogène, de même que c.4837A>G.",
    # Permutation entre deux fiches citées dès que les identifiants sont écrits.
    "Le variant c.5123C>A est pathogène et le variant c.5266dup est probablement pathogène.",
    "Les variantes répertoriées comme pathogènes sont : c.4837A>G, c.5266dup (pathogène).",
    "Le variant c.4837A>G et d'autres variantes pathogènes sont décrits.",
    "Le variant c.5266dup est pathogène (bénin selon certains).",
    "Les variantes répertoriées comme pathogènes sont : c.5266dup (p.Gln1756fs) et d'autres variantes "
    "de signification incertaine, dont c.4837A>G.",
])
def test_inverted_or_misattributed_multi_variant_answers_are_rejected(answer):
    assert _verdict(answer) == "significance_not_in_sources"


def test_a_sentence_without_variant_keeps_the_cited_documents_rule():
    assert _verdict("Ces variants sont pathogènes ou bénins.") is None
    assert _verdict("Ces variants sont de signification incertaine.") == "significance_not_in_sources"


# --- I1 (revue finale n° 2) : inversions, atténuations, abréviations ------------------------
@pytest.mark.parametrize("answer", [
    "Ce variant est loin d'être pathogène.",
    "Ce variant est tout sauf pathogène.",
    "Il est peu probable que ce variant soit pathogène.",
    "Il est improbable que ce variant soit pathogène.",
    "L'hypothèse d'un variant pathogène a été écartée.",
    "Ce variant a été exclu des variants pathogènes.",
    "Ce variant était considéré comme pathogène à tort.",
    "Il est faussement présenté comme pathogène.",
    "Le caractère pathogène est faux.",
    "Contrairement aux attentes, il est pathogène.",
    "Le caractère pathogène a été réfuté.",
    "Le caractère pathogène a été infirmé.",
    "Ce variant est pathogène ? Faux.",
    "Ce variant est pathogène ? Non.",
    "Ce variant est pathogène. Inexact.",
    "Ce variant est potentiellement pathogène.",
    "Ce variant est possiblement pathogène.",
    "Ce variant est éventuellement pathogène.",
    "Ce variant est hautement pathogène.",
    "Ce variant est peut-être pathogène.",
    "Ce variant pourrait être pathogène.",
    "Ce variant est P/LP.",
    "Ce variant est classé LP.",
    "Ce variant est classé B.",
    "Ce variant est LB.",
    "Ce variant est classé P.",
    "Ce variant (B) est décrit.",
    "Classe 5 (pathogène).",
    "Ce variant est classé en classe 3.",
    "Classe ACMG 4.",
])
def test_inversions_softenings_and_abbreviations_are_rejected(answer):
    assert _reason(check_significances, answer, [doc()]) == "significance_not_in_sources"


@pytest.mark.parametrize("answer", [
    "Le variant c.5266dup (p.Gln1756fs) est pathogène.",
    "Il est associé exclusivement au cancer du sein et il est pathogène.",
    "Ce variant pathogène est décrit par une infirmière.",
    "Les lymphocytes B et la vitamine B12 ne sont pas concernés.",
    "Le gène code une protéine de classe I.",
    "Il est pathogène. Non sans raison, ClinVar le documente.",
])
def test_ordinary_wording_near_these_words_is_still_accepted(answer):
    check_significances(answer, [doc()])


# --- m1 / m2 (revue finale n° 2) -------------------------------------------------------------
@pytest.mark.parametrize("answer", [
    "dbSNP 80357999 est pathogène.",
    "Le variant dbSNP rs80357999 est pathogène.",
    "Le variant rs-12345 est pathogène.",
    "Le variant rs – 12345 est pathogène.",
    "Le variant p.(Arg1699Trp) est pathogène.",
    "Le variant m.3243A>G est pathogène.",
    "Le variant c. 68A>G est pathogène.",
    "Le variant c.5266 del est pathogène.",
])
def test_identifier_forms_outside_the_usual_spelling_are_still_checked(answer):
    assert _reason(check_identifiers, answer, [doc()]) == "identifier_not_in_sources"


@pytest.mark.parametrize("answer", [
    "dbSNP 80357906 : pathogène.",
    "Le variant rs-80357906 est pathogène.",
    "Le variant p.(Gln1756Profs*74) est pathogène.",
    "Le variant c. 5266dup est pathogène.",
    "Le variant c.5266 dup est pathogène.",
])
def test_the_same_forms_naming_the_document_variant_pass(answer):
    check_identifiers(answer, [doc()])


def test_a_dbsnp_number_of_an_uncited_card_is_not_cited():
    assert _verdict("Le variant dbSNP 1799966 est pathogène.", [PATHO, BENIGN], [PATHO.doc_id]) == "identifier_not_cited"


@pytest.mark.parametrize("answer", [
    "D'autres variantes non listées ici sont pathogènes.",
    "Il est pathogène et d'autres variantes non listées ici sont bénignes.",
])
def test_the_truncated_list_formula_does_not_cover_a_significance_after_it(answer):
    assert _reason(check_significances, answer, [doc()]) == "significance_not_in_sources"


def test_the_truncated_list_formula_is_still_masked_at_the_end_of_a_list():
    check_significances("Le variant c.5266dup est pathogène (et d'autres variantes non listées ici).", [doc()])


# --- N1 (re-relecture de la vague n° 2) : délimiteurs Markdown ou ASCII collés à un identifiant ---
# Sans normalisation, « **c.9999A>G** » n'était pas extrait : identifiant inventé et appariement
# variant ↔ signification contournés par une simple mise en forme.
@pytest.mark.parametrize("answer", [
    "Le variant **c.9999A>G** est pathogène.",
    "Le variant **p.Arg9999Ter** est pathogène.",
    "Le variant `c.9999A>G` est pathogène.",
    'Le variant "c.9999A>G" est pathogène.',
    "Le variant [c.9999A>G] est pathogène.",
    "Le variant _c.9999A>G_ est pathogène.",
    "Le variant *c.9999A>G* est pathogène.",
    "Le variant c.9999A>G* est pathogène.",
    "Le variant 'c.9999A>G' est pathogène.",
    "Le variant ~~c.9999A>G~~ est pathogène.",
    "Le variant <b>c.9999A>G</b> est pathogène.",
    "| c.9999A>G| pathogène |",
    "Le variant **rs99999999** est pathogène.",
    "Le variant **p.Arg9999***, pathogène.",
])
def test_an_invented_identifier_in_markup_is_still_rejected(answer):
    assert _verdict(answer) == "identifier_not_in_sources"


@pytest.mark.parametrize("answer", [
    "**c.4837A>G** — *pathogène*",
    "**NM_007294.4(BRCA1):c.4837A>G** : pathogène",
    "Le variant `c.4837A>G` est pathogène.",
    'Le variant "c.4837A>G" est pathogène.',
    "Le variant c.4837A>G est _pathogène_.",
    "- **c.4837A>G** (rs1799966) : **pathogène**",
])
def test_a_swapped_significance_in_markup_is_still_rejected(answer):
    assert _verdict(answer) == "significance_not_in_sources"


@pytest.mark.parametrize("answer", [
    "- **c.5266dup** (rs80357906) : **pathogène**\n- **c.4837A>G** (`rs1799966`) : *bénin*",
    "Le variant _c.5266dup_ est **pathogène** et le variant \"c.4837A>G\" est bénin.",
    "| Variant | Signification |\n|---|---|\n|c.5266dup|pathogène|\n|c.4837A>G|bénin|",
])
def test_correct_answers_in_markup_pass(answer):
    assert _verdict(answer) is None


@pytest.mark.parametrize(("text", "expected"), [
    ("p.Arg337*", "p.Arg337Ter"),
    ("**p.Arg337***", "p.Arg337Ter"),
    ("c.*123A>G", "c.*123A>G"),
    ("p.Gln1756Profs*74", "p.Gln1756fs"),
    ("c.68_69del", "c.68_69del"),
    ("c.-61-9703_-61-9700del", "c.-61-9703_-61-9700del"),
    ("NM_007294.4(BRCA1):c.5266dup", "c.5266dup"),
])
def test_markup_removal_keeps_the_stars_and_underscores_of_hgvs(text, expected):
    from RAG.src.generation.checks import _answer_text, _text_ids
    assert expected in _text_ids(_answer_text(text))

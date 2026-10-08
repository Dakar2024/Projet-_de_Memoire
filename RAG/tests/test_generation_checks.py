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

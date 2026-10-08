import pytest

from RAG.src.generation import messages
from RAG.src.generation.answer import generate_answer, validate_generation
from RAG.src.llm.common import LlmCall
from RAG.src.retrieval.analysis import QueryAnalysis
from RAG.src.retrieval.identifiers import extract_identifiers
from RAG.src.retrieval.retriever import RetrievedDocument, SearchResult, SearchTrace
from RAG.src.utils.config import LlmProfile
from RAG.src.utils.errors import LlmUnavailableError

PROFILE = LlmProfile("essai", "openai/gpt-oss-120b", "groq", "Groq", None, "groq")
TEXT = "Variant c.5266dup, gene BRCA1. dbSNP rs80357906. Clinical significance: Pathogenic."
HISTORY_TEXT = TEXT + "\nClassification history: previously Uncertain significance until 2015-01."


def doc(doc_id="clinvar:32716", text=TEXT, sig="Pathogenic"):
    return RetrievedDocument(doc_id=doc_id, doc_type="variant", text=text, gene_symbol="BRCA1",
                             clinical_significance=sig, review_status="reviewed by expert panel",
                             rs_dbsnp=80357906, hgvs_c="c.5266dup", hgvs_p="p.Gln1756fs",
                             clinvar_variation_id="17677", clinvar_url="https://example/17677",
                             source_version="2026-09", similarity=0.9, stage="exact")


def result(docs=None, question="Que sait-on de rs80357906 ?", flags=None, not_found=None):
    ids = extract_identifiers(question)
    trace = SearchTrace(mode="full", identifiers=ids,
                        analysis=QueryAnalysis("q", "none", None, True, "essai"),
                        flags=list(flags or []), not_found_identifiers=list(not_found or []))
    return SearchResult(question=question, documents=tuple(docs if docs is not None else [doc()]), trace=trace)


class StubClient:
    def __init__(self, content=None, error=None):
        self.content, self.error, self.calls = content, error, 0

    def complete_json(self, profile, **kwargs):
        self.calls += 1
        if self.error:
            raise self.error
        return LlmCall(self.content, "gen-1", "Groq", 0.0, 900, 200)


def ok(status="answered", answer="Le variant rs80357906 est pathogène.", citations=("clinvar:32716",), reason=None):
    return {"status": status, "scope_reason": reason, "answer": answer, "citations": list(citations)}


def _generate(client, res=None):
    return generate_answer("Que sait-on de rs80357906 ?", res or result(), client=client, profile=PROFILE, max_tokens=3000)


def test_a_verified_answer_is_returned_with_sources_from_the_database():
    answer = _generate(StubClient(ok()))

    assert answer.status == "answered" and answer.rejected is None
    assert answer.sources[0].clinvar_variation_id == "17677" and answer.sources[0].significance_fr == "pathogène"
    assert "2026-09" in answer.disclaimer


def test_an_invented_citation_becomes_unverifiable():
    answer = _generate(StubClient(ok(citations=("clinvar:999",))))

    assert (answer.status, answer.answer, answer.rejected) == ("unverifiable", messages.UNVERIFIABLE, "citation_not_transmitted")
    assert [s.doc_id for s in answer.sources] == ["clinvar:32716"]


def test_out_of_scope_text_is_replaced_by_the_fixed_message():
    answer = _generate(StubClient(ok(status="out_of_scope", reason="counting", answer="Il y a 10 variants.", citations=())))

    assert answer.answer == messages.OUT_OF_SCOPE["counting"] and answer.sources == ()


def test_not_in_sources_text_with_an_identifier_is_replaced():
    answer = _generate(StubClient(ok(status="not_in_sources", answer="rs12345 n'est pas documenté.", citations=())))
    assert answer.answer == messages.NO_DOCUMENT and answer.status == "not_in_sources"


def test_no_document_means_no_llm_call():
    client = StubClient(ok())
    answer = _generate(client, result(docs=[]))
    assert client.calls == 0 and answer.answer == messages.NO_DOCUMENT


def test_only_an_out_of_panel_gene_means_no_llm_call():
    client = StubClient(ok())
    res = result(question="Quels variants de MLH1 ?", flags=["gene_out_of_panel"])
    answer = generate_answer("Quels variants de MLH1 ?", res, client=client, profile=PROFILE, max_tokens=3000)
    assert client.calls == 0 and answer.answer == messages.OUT_OF_SCOPE["gene_out_of_panel"]


def test_all_cited_identifiers_missing_means_no_llm_call():
    client = StubClient(ok())
    q = "Que sait-on de rs9999999999 ?"
    res = result(docs=[doc("clinvar:5")], question=q, flags=["identifier_not_found"], not_found=["rs9999999999"])
    answer = generate_answer(q, res, client=client, profile=PROFILE, max_tokens=3000)
    assert client.calls == 0 and "rs9999999999" in answer.answer and answer.status == "not_in_sources"


def test_schema_violations_make_generation_unavailable():
    with pytest.raises(LlmUnavailableError):
        _generate(StubClient({"status": "answered"}))


@pytest.mark.parametrize("content", [
    {"status": "maybe", "scope_reason": None, "answer": "x", "citations": []},
    {"status": "answered", "scope_reason": "counting", "answer": "x", "citations": ["a"]},
    {"status": "out_of_scope", "scope_reason": None, "answer": "x", "citations": []},
    {"status": "answered", "scope_reason": None, "answer": "x" * 4001, "citations": ["a"]},
    {"status": "answered", "scope_reason": None, "answer": "x", "citations": "a"},
    {"status": "answered", "scope_reason": None, "answer": "x", "citations": ["a"], "extra": 1},
])
def test_validate_generation_rejects_malformed_content(content):
    with pytest.raises(ValueError):
        validate_generation(content)


def test_llm_errors_propagate():
    with pytest.raises(LlmUnavailableError):
        _generate(StubClient(error=LlmUnavailableError("503")))


def test_history_of_a_cited_document_is_restored_by_the_code():
    answer = _generate(StubClient(ok()), result(docs=[doc(text=HISTORY_TEXT)]))

    assert answer.status == "answered"
    source = answer.sources[0]
    assert (source.previous_significance, source.previous_significance_fr, source.previous_until) == (
        "Uncertain significance", "signification incertaine", "2015-01")
    assert answer.history == (messages.history_sentence("clinvar:32716", "signification incertaine", "2015-01"),)


def test_no_history_when_the_cited_document_has_none():
    answer = _generate(StubClient(ok()))

    assert answer.history == ()
    assert answer.sources[0].previous_significance is None and answer.sources[0].previous_until is None


def test_an_uncited_document_brings_no_history():
    docs = [doc(), doc("clinvar:7", text=HISTORY_TEXT)]
    answer = _generate(StubClient(ok()), result(docs=docs))

    assert [s.doc_id for s in answer.sources] == ["clinvar:32716"] and answer.history == ()


def test_a_rejected_answer_carries_no_history():
    answer = _generate(StubClient(ok(citations=("clinvar:999",))), result(docs=[doc(text=HISTORY_TEXT)]))
    assert answer.status == "unverifiable" and answer.history == ()


def test_a_narrated_history_becomes_unverifiable():
    content = ok(answer="Le variant rs80357906 a été reclassé en 2019.")
    answer = _generate(StubClient(content), result(docs=[doc(text=HISTORY_TEXT)]))

    assert (answer.status, answer.answer, answer.rejected) == ("unverifiable", messages.UNVERIFIABLE, "history_narrated")


def test_identifier_check_receives_the_real_status(monkeypatch):
    seen = {}

    def spy(answer, documents, status="answered"):
        seen["status"] = status

    monkeypatch.setattr("RAG.src.generation.answer.check_identifiers", spy)
    _generate(StubClient(ok(status="partial")))
    assert seen == {"status": "partial"}


def test_as_dict_serialises_sources_and_history():
    data = _generate(StubClient(ok()), result(docs=[doc(text=HISTORY_TEXT)])).as_dict()
    assert data["sources"][0]["previous_until"] == "2015-01" and len(data["history"]) == 1

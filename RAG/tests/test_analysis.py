import json

import pytest

from RAG.src.llm.openrouter import LlmCall
from RAG.src.retrieval.analysis import AnalysisCache, analyze, validate_analysis
from RAG.src.utils.config import LlmProfile
from RAG.src.utils.errors import RagConfigurationError, LlmPermanentError, LlmProviderMismatchError, LlmUnavailableError

PROFILE = LlmProfile("mistral-medium", "mistralai/mistral-medium-3-5", "mistral/zdr", "Mistral", None)
GOOD = {"english_query": "Is BRCA1 rs80357906 pathogenic?", "significance": "none", "disease": None}


class StubClient:
    def __init__(self, result):
        self.result = result
        self.calls = 0

    def complete_json(self, profile, **kwargs):
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return LlmCall(self.result, "gen-1", "Mistral", 0.0012, 100, 30)


def _analyze(client, cache=None, question="Le variant rs80357906 est-il pathogène ?"):
    return analyze(question, client=client, profile=PROFILE, max_tokens=2000, cache=cache)


def test_a_valid_answer_is_used():
    result = _analyze(StubClient(GOOD))

    assert result.available and result.english_query == GOOD["english_query"]
    assert (result.significance, result.disease) == ("none", None)
    assert (result.provider_name, result.cost_usd, result.profile) == ("Mistral", 0.0012, "mistral-medium")


def test_validate_analysis_rejects_unknown_significance():
    with pytest.raises(ValueError):
        validate_analysis({**GOOD, "significance": "DROP TABLE rag_documents"})


@pytest.mark.parametrize("content", [
    {**GOOD, "english_query": "   "},
    {"english_query": "x", "significance": "none"},
    {**GOOD, "extra": 1},
    {**GOOD, "disease": 12},
])
def test_malformed_answers_are_rejected(content):
    with pytest.raises(ValueError):
        validate_analysis(content)


def test_blank_disease_becomes_none():
    assert validate_analysis({**GOOD, "disease": "  "})[2] is None


@pytest.mark.parametrize("failure", [LlmUnavailableError("503"), LlmProviderMismatchError("Bedrock")])
def test_transient_failures_degrade_to_the_raw_question(failure):
    result = _analyze(StubClient(failure))

    assert result.available is False
    assert result.english_query == "Le variant rs80357906 est-il pathogène ?"
    assert result.significance == "none" and result.error


def test_an_invalid_answer_degrades_too_but_keeps_its_cost():
    result = _analyze(StubClient({**GOOD, "significance": "grave"}))

    assert result.available is False and result.significance == "none"
    assert (result.cost_usd, result.provider_name) == (0.0012, "Mistral")


def test_permanent_errors_propagate():
    with pytest.raises(LlmPermanentError):
        _analyze(StubClient(LlmPermanentError("402")))


def test_cache_avoids_a_second_paid_call(tmp_path):
    cache = AnalysisCache(tmp_path / "cache.json")
    client = StubClient(GOOD)

    first = _analyze(client, cache)
    second = _analyze(client, AnalysisCache(tmp_path / "cache.json"))

    assert client.calls == 1
    assert second.from_cache and second.english_query == first.english_query
    assert second.cost_usd == first.cost_usd


def test_failures_are_never_cached(tmp_path):
    cache = AnalysisCache(tmp_path / "cache.json")
    _analyze(StubClient(LlmUnavailableError("503")), cache)

    assert not (tmp_path / "cache.json").exists()


def test_cache_key_depends_on_model_and_prompt_version(tmp_path):
    cache = AnalysisCache(tmp_path / "cache.json")
    _analyze(StubClient(GOOD), cache)
    other = LlmProfile("x", "openai/gpt-oss-120b", "deepinfra/bf16", "DeepInfra", "bf16")

    assert cache.get("Le variant rs80357906 est-il pathogène ?", other) is None


@pytest.mark.parametrize("text", ['{"tronque": ', "[1, 2]"])
def test_an_unreadable_cache_file_stops_instead_of_resetting(tmp_path, text):
    path = tmp_path / "cache.json"
    path.write_text(text, encoding="utf-8")

    with pytest.raises(RagConfigurationError, match="cache.json"):
        AnalysisCache(path)


def test_a_hand_edited_cache_entry_is_a_miss(tmp_path):
    path = tmp_path / "cache.json"
    _analyze(StubClient(GOOD), AnalysisCache(path))
    data = json.loads(path.read_text(encoding="utf-8"))
    for entry in data.values():
        entry["significance"] = "grave"
    path.write_text(json.dumps(data), encoding="utf-8")
    client = StubClient(GOOD)

    result = _analyze(client, AnalysisCache(path))

    assert client.calls == 1 and result.available and not result.from_cache
    assert result.significance == "none"


def test_prompt_sha_covers_the_system_prompt_the_schema_and_the_user_template():
    import hashlib

    from RAG.src.prompts import analysis as prompts

    raw = prompts.SYSTEM_PROMPT + json.dumps(prompts.ANALYSIS_SCHEMA, sort_keys=True) + prompts.user_message("{q}")
    assert prompts.PROMPT_SHA == hashlib.sha256(raw.encode("utf-8")).hexdigest()
    assert prompts.prompt_sha256() == prompts.PROMPT_SHA


@pytest.mark.parametrize("attribute,value", [
    ("SYSTEM_PROMPT", "autre consigne"),
    ("ANALYSIS_SCHEMA", {"type": "object"}),
    ("user_message", lambda question: f"<q>{question}</q>"),
])
def test_cache_key_changes_when_the_prompt_changes_even_without_a_new_version(monkeypatch, attribute, value):
    """Oublier d'incrémenter PROMPT_VERSION ne doit pas rejouer des analyses obtenues
    avec un autre prompt."""
    from RAG.src.prompts import analysis as prompts

    before = AnalysisCache.key("question", PROFILE)
    monkeypatch.setattr(prompts, attribute, value)

    assert AnalysisCache.key("question", PROFILE) != before


@pytest.mark.parametrize("field,value", [
    ("provider_name", "Amazon Bedrock"),
    ("provider_name", None),
    ("cost_usd", -0.5),
    ("cost_usd", True),
    ("cost_usd", float("nan")),
    ("cost_usd", "0.001"),
    ("latency_ms", -1.0),
    ("latency_ms", False),
])
def test_an_invalid_cache_hit_is_a_miss_and_is_overwritten(tmp_path, field, value):
    """Un hit servi par un autre fournisseur que celui du profil, ou au coût ou à la latence
    invalides, ne doit ni atteindre la recherche ni fausser le coût de la mesure."""
    path = tmp_path / "cache.json"
    _analyze(StubClient(GOOD), AnalysisCache(path))
    data = json.loads(path.read_text(encoding="utf-8"))
    (key,) = data
    data[key][field] = value
    path.write_text(json.dumps(data), encoding="utf-8")
    client = StubClient(GOOD)

    result = _analyze(client, AnalysisCache(path))

    assert client.calls == 1 and not result.from_cache
    rewritten = json.loads(path.read_text(encoding="utf-8"))[key]
    assert rewritten["provider_name"] == "Mistral" and rewritten["cost_usd"] == 0.0012
    assert isinstance(rewritten["latency_ms"], float) and rewritten["latency_ms"] >= 0


def test_a_truncated_answer_stops_the_search():
    from RAG.src.utils.errors import LlmTruncatedError

    with pytest.raises(LlmTruncatedError):
        _analyze(StubClient(LlmTruncatedError("coupée", cost_usd=0.01)))

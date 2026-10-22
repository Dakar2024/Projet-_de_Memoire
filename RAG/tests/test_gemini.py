import json

import pytest
import requests
import responses

from RAG.src.llm.gemini import GEMINI_BASE_URL, MAX_WAIT_S, GeminiClient, build_payload, retry_delay
from RAG.src.utils.config import LlmProfile, load_gemini_key
from RAG.src.utils.errors import (
    LlmPermanentError,
    LlmQuotaExhaustedError,
    LlmTruncatedError,
    LlmUnavailableError,
    RagConfigurationError,
)

JUDGE = LlmProfile("juge", "gemini-3.8-flash", "gemini-api", "Google", None, backend="gemini")
SCHEMA = {"type": "object", "properties": {}, "additionalProperties": False, "required": []}
CHAT = f"{GEMINI_BASE_URL}/chat/completions"
HIGH_DEMAND = [{"error": {"code": 503, "message": "This model is currently experiencing high demand.",
                          "status": "UNAVAILABLE"}}]


class FakeSleep:
    def __init__(self):
        self.waits: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.waits.append(seconds)


def _client(**kwargs) -> GeminiClient:
    kwargs.setdefault("sleep", FakeSleep())
    return GeminiClient("AIza_secret", session=requests.Session(), **kwargs)


def _call(client, profile=JUDGE):
    return client.complete_json(profile, system="sys", user="usr", schema_name="s", schema=SCHEMA, max_tokens=4000)


def _chat_ok(content='{"a": 1}', finish_reason="stop"):
    """Réponse telle qu'observée le 22/10/2026 (gemini-3.7-flash) : ni `provider` ni coût."""
    responses.add(responses.POST, CHAT, json={
        "id": "C_7ZatGLDcL7sgLXnN6RDQ", "object": "chat.completion", "created": 1, "model": "gemini-3.8-flash",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content},
                     "finish_reason": finish_reason}],
        "usage": {"completion_tokens": 14, "prompt_tokens": 20, "total_tokens": 34},
    })


def test_payload_uses_reasoning_effort_and_a_strict_schema():
    payload = build_payload(JUDGE, system="sys", user="usr", schema_name="s", schema=SCHEMA, max_tokens=4000)

    assert payload == {
        "model": "gemini-3.8-flash",
        "messages": [{"role": "system", "content": "sys"}, {"role": "user", "content": "usr"}],
        "response_format": {"type": "json_schema", "json_schema": {"name": "s", "strict": True, "schema": SCHEMA}},
        "reasoning_effort": "low",
        "max_tokens": 4000,
    }


@pytest.mark.parametrize("profile", [
    LlmProfile("x", "google/gemini-3.8-flash", "google-vertex/global", "Google", None, backend="openrouter"),
    LlmProfile("x", "gemini-3.8-flash", "gemini-api", "Vertex", None, backend="gemini"),
    LlmProfile("x", "gemini-3.8-flash", "gemini-api", "Google", "bf16", backend="gemini"),
])
def test_a_profile_gemini_cannot_honour_is_refused(profile):
    with pytest.raises(RagConfigurationError):
        build_payload(profile, system="s", user="u", schema_name="n", schema=SCHEMA, max_tokens=10)


@responses.activate
def test_success_returns_the_content_at_zero_cost_and_sends_the_key_as_bearer():
    _chat_ok()
    call = _call(_client())

    assert (call.content, call.provider_name, call.cost_usd) == ({"a": 1}, "Google", 0.0)
    assert (call.generation_id, call.prompt_tokens, call.completion_tokens) == ("C_7ZatGLDcL7sgLXnN6RDQ", 20, 14)
    request = responses.calls[0].request
    assert request.headers["Authorization"] == "Bearer AIza_secret"
    assert json.loads(request.body)["model"] == "gemini-3.8-flash"


@responses.activate
def test_high_demand_is_waited_out_then_succeeds():
    sleep = FakeSleep()
    responses.add(responses.POST, CHAT, status=503, json=HIGH_DEMAND)
    _chat_ok()

    assert _call(_client(sleep=sleep)).content == {"a": 1}
    assert sleep.waits == [10.0]


@responses.activate
def test_persistent_high_demand_is_transient_after_bounded_waits():
    sleep = FakeSleep()
    for _ in range(3):
        responses.add(responses.POST, CHAT, status=503, json=HIGH_DEMAND)

    with pytest.raises(LlmUnavailableError, match="503") as info:
        _call(_client(sleep=sleep, max_waits=2))
    assert not isinstance(info.value, LlmQuotaExhaustedError)
    assert len(responses.calls) == 3 and len(sleep.waits) == 2


@responses.activate
def test_persistent_429_is_a_quota_error_with_the_announced_delay():
    body = {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "details": [
        {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "37s"}]}}
    sleep = FakeSleep()
    for _ in range(2):
        responses.add(responses.POST, CHAT, status=429, json=body)

    with pytest.raises(LlmQuotaExhaustedError) as info:
        _call(_client(sleep=sleep, max_waits=1))
    assert sleep.waits == [37.0] and info.value.retry_after_s == 37.0


@responses.activate
def test_a_long_announced_wait_is_capped():
    sleep = FakeSleep()
    responses.add(responses.POST, CHAT, status=429, headers={"Retry-After": "3600"}, json={})
    _chat_ok()

    _call(_client(sleep=sleep))
    assert sleep.waits == [MAX_WAIT_S]


@pytest.mark.parametrize("status", [400, 401, 403, 404])
@responses.activate
def test_refusals_are_permanent_and_never_quote_the_message(status):
    responses.add(responses.POST, CHAT, status=status,
                  json=[{"error": {"code": status, "message": "question secrète", "status": "X"}}])

    with pytest.raises(LlmPermanentError) as info:
        _call(_client())
    assert "secrète" not in str(info.value)


@responses.activate
def test_network_error_is_transient():
    responses.add(responses.POST, CHAT, body=requests.ConnectionError("boom"))

    with pytest.raises(LlmUnavailableError, match="injoignable"):
        _call(_client())


@responses.activate
def test_truncated_answer_is_refused():
    _chat_ok(content='{"a"', finish_reason="length")

    with pytest.raises(LlmTruncatedError, match="judge.max_tokens"):
        _call(_client())


def test_retry_delay_reads_header_then_body_and_ignores_garbage():
    def response(headers=None, body=None):
        r = requests.Response()
        r.headers.update(headers or {})
        r._content = json.dumps(body).encode() if body is not None else b"not json"
        return r

    assert retry_delay(response({"Retry-After": "12"})) == 12.0
    info = {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "1m5s"}
    assert retry_delay(response(body=[{"error": {"details": [info]}}])) == 65.0
    assert retry_delay(response(body={"error": {"details": ["x"]}})) is None
    assert retry_delay(response()) is None


def test_empty_key_is_refused():
    with pytest.raises(LlmPermanentError, match="GEMINI_API_KEY"):
        GeminiClient("  ")


def test_gemini_key_is_required_and_never_echoed():
    with pytest.raises(RagConfigurationError, match="GEMINI_API_KEY"):
        load_gemini_key({})
    assert load_gemini_key({"GEMINI_API_KEY": " AIza_x "}) == "AIza_x"

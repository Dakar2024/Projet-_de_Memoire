import json

import pytest
import requests
import responses

from RAG.src.llm.groq import GROQ_BASE_URL, GroqClient, build_payload, parse_duration, rate_limit_wait
from RAG.src.utils.config import LlmProfile
from RAG.src.utils.errors import (
    LlmPermanentError, LlmQuotaExhaustedError, LlmTruncatedError, LlmUnavailableError, RagConfigurationError,
)

TRIAL = LlmProfile("essai-groq-gpt-oss-120b", "openai/gpt-oss-120b", "groq", "Groq", None, backend="groq")
SCHEMA = {"type": "object", "properties": {}, "additionalProperties": False, "required": []}
CHAT = f"{GROQ_BASE_URL}/chat/completions"


class FakeSleep:
    def __init__(self):
        self.waits: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.waits.append(seconds)


def _client(**kwargs) -> GroqClient:
    kwargs.setdefault("sleep", FakeSleep())
    return GroqClient("gsk_secret", session=requests.Session(), **kwargs)


def _call(client, profile=TRIAL):
    return client.complete_json(profile, system="sys", user="usr", schema_name="s", schema=SCHEMA, max_tokens=2000)


def _chat_ok(content='{"a": 1}', finish_reason="stop"):
    """Réponse de chat telle qu'observée le 05/10/2026 : ni `provider` ni `usage.cost`."""
    responses.add(responses.POST, CHAT, json={
        "id": "chatcmpl-123", "object": "chat.completion", "created": 1, "model": "openai/gpt-oss-120b",
        "service_tier": "on_demand", "system_fingerprint": "fp", "x_groq": {"id": "req_1"},
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content},
                     "finish_reason": finish_reason}],
        "usage": {"prompt_tokens": 120, "completion_tokens": 40, "total_tokens": 160, "queue_time": 0.01,
                  "completion_tokens_details": {"reasoning_tokens": 12}},
    })


def test_payload_uses_reasoning_effort_and_never_the_openrouter_only_parameters():
    payload = build_payload(TRIAL, system="sys", user="usr", schema_name="s", schema=SCHEMA, max_tokens=2000)

    assert payload == {
        "model": "openai/gpt-oss-120b",
        "messages": [{"role": "system", "content": "sys"}, {"role": "user", "content": "usr"}],
        "response_format": {"type": "json_schema", "json_schema": {"name": "s", "strict": True, "schema": SCHEMA}},
        "reasoning_effort": "low",
        "max_tokens": 2000,
    }


@pytest.mark.parametrize("profile", [
    LlmProfile("x", "openai/gpt-oss-120b", "deepinfra/bf16", "DeepInfra", "bf16", backend="openrouter"),
    LlmProfile("x", "openai/gpt-oss-120b", "groq", "DeepInfra", None, backend="groq"),
    LlmProfile("x", "openai/gpt-oss-120b", "groq", "Groq", None, backend="openrouter"),
    LlmProfile("x", "openai/gpt-oss-120b", "groq", "Groq", "bf16", backend="groq"),
])
def test_a_profile_that_groq_cannot_honour_is_refused_before_any_call(profile):
    with pytest.raises(RagConfigurationError):
        build_payload(profile, system="", user="", schema_name="s", schema=SCHEMA, max_tokens=2000)


@responses.activate
def test_successful_call_is_served_by_groq_at_no_cost():
    _chat_ok()

    call = _call(_client())

    assert call.content == {"a": 1}
    assert (call.generation_id, call.provider_name, call.cost_usd) == ("chatcmpl-123", "Groq", 0.0)
    assert (call.prompt_tokens, call.completion_tokens) == (120, 40)
    request = responses.calls[0].request
    assert request.headers["Authorization"] == "Bearer gsk_secret"
    assert request.url == CHAT and len(responses.calls) == 1
    assert json.loads(request.body)["reasoning_effort"] == "low"


@responses.activate
def test_a_rate_limit_waits_for_retry_after_then_retries():
    responses.add(responses.POST, CHAT, status=429, headers={"retry-after": "7",
                                                             "x-ratelimit-reset-tokens": "1m26.4s"})
    _chat_ok()
    sleep = FakeSleep()

    call = _call(_client(sleep=sleep))

    assert call.content == {"a": 1}
    assert sleep.waits == [7.0] and len(responses.calls) == 2


@responses.activate
def test_a_rate_limit_without_retry_after_uses_the_token_reset():
    responses.add(responses.POST, CHAT, status=429, headers={"x-ratelimit-reset-tokens": "4.575s"})
    _chat_ok()
    sleep = FakeSleep()

    _call(_client(sleep=sleep))

    assert sleep.waits == [4.575]


@responses.activate
def test_repeated_rate_limits_end_as_an_exhausted_quota():
    for _ in range(4):
        responses.add(responses.POST, CHAT, status=429, headers={"retry-after": "2"})
    sleep = FakeSleep()

    with pytest.raises(LlmQuotaExhaustedError, match="429") as excinfo:
        _call(_client(sleep=sleep, max_rate_limit_waits=3))
    assert isinstance(excinfo.value, LlmUnavailableError)
    assert sleep.waits == [2.0, 2.0, 2.0] and len(responses.calls) == 4


@responses.activate
@pytest.mark.parametrize("headers, announced", [
    ({"retry-after": "999"}, "999"),
    ({"x-ratelimit-reset-tokens": "2m"}, "120"),
    ({"retry-after": "illisible", "x-ratelimit-reset-tokens": "61s"}, "61"),
])
def test_a_wait_announced_beyond_the_cap_stops_at_once(headers, announced):
    responses.add(responses.POST, CHAT, status=429, headers=headers, json={"error": {
        "message": "gsk_secret usr", "code": "rate_limit_exceeded"}})
    sleep = FakeSleep()

    with pytest.raises(LlmQuotaExhaustedError) as excinfo:
        _call(_client(sleep=sleep))
    message = str(excinfo.value)
    assert sleep.waits == [] and len(responses.calls) == 1
    assert announced in message and TRIAL.name in message
    assert "gsk_secret" not in message and "usr" not in message


@responses.activate
def test_no_request_left_today_stops_at_once_with_the_announced_reset():
    responses.add(responses.POST, CHAT, status=429, headers={
        "retry-after": "3", "x-ratelimit-remaining-requests": "0", "x-ratelimit-reset-requests": "2h0m0s"})
    sleep = FakeSleep()

    with pytest.raises(LlmQuotaExhaustedError, match="7200") as excinfo:
        _call(_client(sleep=sleep))
    assert sleep.waits == [] and len(responses.calls) == 1
    assert "gsk_secret" not in str(excinfo.value)


@responses.activate
def test_a_short_announced_wait_with_requests_left_is_waited():
    """`x-ratelimit-reset-requests` (« 1m26.4s » observé sur une réponse normale) ne
    compte que si plus aucune requête ne reste : sinon il ferait croire à un quota épuisé."""
    responses.add(responses.POST, CHAT, status=429, headers={
        "retry-after": "4", "x-ratelimit-remaining-requests": "998", "x-ratelimit-reset-requests": "1m26.4s"})
    _chat_ok()
    sleep = FakeSleep()

    assert _call(_client(sleep=sleep)).content == {"a": 1}
    assert sleep.waits == [4.0]


@responses.activate
def test_a_request_beyond_the_tokens_per_minute_limit_is_permanent():
    responses.add(responses.POST, CHAT, status=413, json={"error": {"message": "gsk_secret usr",
                                                                    "code": "rate_limit_exceeded"}})

    with pytest.raises(LlmPermanentError, match="413") as excinfo:
        _call(_client())
    assert "gsk_secret" not in str(excinfo.value) and "usr" not in str(excinfo.value)
    assert len(responses.calls) == 1


@pytest.mark.parametrize("text, seconds", [
    ("4.575s", 4.575), ("1m26.4s", 86.4), ("2m", 120.0), ("250ms", 0.25), ("1h", 3600.0), ("7", 7.0),
    ("0.5", 0.5), (" 3s ", 3.0),
])
def test_parse_duration(text, seconds):
    assert parse_duration(text) == pytest.approx(seconds)


@pytest.mark.parametrize("text", [None, "", "abc", "-3s", "1x", "s", "Wed, 21 Oct 2015 07:28:00 GMT", "nan", "inf"])
def test_parse_duration_rejects_unreadable_values(text):
    assert parse_duration(text) is None


@pytest.mark.parametrize("headers, seconds", [
    ({"retry-after": "3", "x-ratelimit-reset-tokens": "9s"}, 3.0),
    ({"retry-after": "illisible", "x-ratelimit-reset-tokens": "9s"}, 9.0),
    ({"x-ratelimit-reset-tokens": "1m26.4s"}, 60.0),
    ({"retry-after": "illisible"}, 10.0),
    ({}, 10.0),
])
def test_rate_limit_wait_is_bounded_and_has_a_default(headers, seconds):
    assert rate_limit_wait(headers) == pytest.approx(seconds)


@responses.activate
@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_refusals_are_permanent_and_never_echo_the_key_or_the_body(status):
    responses.add(responses.POST, CHAT, status=status, json={"error": {
        "message": "clé gsk_secret refusée pour : usr", "type": "invalid_request_error",
        "code": "invalid_api_key"}})

    with pytest.raises(LlmPermanentError) as excinfo:
        _call(_client())
    message = str(excinfo.value)
    assert "gsk_secret" not in message and "usr" not in message and "refusée" not in message
    assert str(status) in message and TRIAL.name in message and "invalid_api_key" in message
    assert len(responses.calls) == 1


@responses.activate
@pytest.mark.parametrize("status", [500, 503])
def test_server_errors_are_transient_and_not_retried(status):
    responses.add(responses.POST, CHAT, status=status, body="gsk_secret usr")

    with pytest.raises(LlmUnavailableError) as excinfo:
        _call(_client())
    assert "gsk_secret" not in str(excinfo.value) and "usr" not in str(excinfo.value)
    assert len(responses.calls) == 1


@responses.activate
def test_unreachable_service_is_transient_and_never_echoes_the_key():
    responses.add(responses.POST, CHAT, body=requests.ConnectionError("gsk_secret"))

    with pytest.raises(LlmUnavailableError) as excinfo:
        _call(_client())
    assert "gsk_secret" not in str(excinfo.value)


@responses.activate
@pytest.mark.parametrize("content, finish_reason", [('{"a": ', "length"), (None, "stop"), ("  ", "stop")])
def test_a_truncated_or_empty_answer_is_permanent_and_free(content, finish_reason):
    _chat_ok(content=content, finish_reason=finish_reason)

    with pytest.raises(LlmTruncatedError, match="llm.max_tokens") as excinfo:
        _call(_client())
    assert excinfo.value.cost_usd == 0.0


@responses.activate
@pytest.mark.parametrize("content", ["pas du json", "[1, 2]"])
def test_non_json_or_non_object_content_is_unavailable(content):
    _chat_ok(content=content)

    with pytest.raises(LlmUnavailableError, match="JSON"):
        _call(_client())


def test_an_empty_key_is_refused_upfront():
    with pytest.raises(LlmPermanentError, match="GROQ_API_KEY"):
        GroqClient("  ")

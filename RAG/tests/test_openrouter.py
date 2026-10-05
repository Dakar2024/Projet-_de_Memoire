import json

import pytest
import requests
import responses

from RAG.src.llm.openrouter import OPENROUTER_BASE_URL, OpenRouterClient, build_payload
from RAG.src.utils.config import LlmProfile
from RAG.src.utils.errors import LlmPermanentError, LlmProviderMismatchError, LlmUnavailableError

CLAUDE = LlmProfile("claude-opus-5.5", "anthropic/claude-opus-5.5", "google-vertex/europe", "Google", None)
OSS = LlmProfile("gpt-oss-120b", "openai/gpt-oss-120b", "deepinfra/bf16", "DeepInfra", "bf16")
SCHEMA = {"type": "object", "properties": {}, "additionalProperties": False, "required": []}
CHAT = f"{OPENROUTER_BASE_URL}/chat/completions"
GEN = f"{OPENROUTER_BASE_URL}/generation"


def _client(**kwargs) -> OpenRouterClient:
    return OpenRouterClient("sk-or-secret", session=requests.Session(), sleep=lambda s: None, **kwargs)


def _call(client, profile=CLAUDE):
    return client.complete_json(profile, system="sys", user="usr", schema_name="s", schema=SCHEMA, max_tokens=2000)


def _chat_ok(content='{"a": 1}'):
    responses.add(responses.POST, CHAT, json={"id": "gen-123", "choices": [{"message": {"content": content}}],
                                             "usage": {"prompt_tokens": 120, "completion_tokens": 40}})


def _gen_ok(provider="Google", cost=0.0021):
    responses.add(responses.GET, GEN, json={"data": {"provider_name": provider, "total_cost": cost}})


def test_payload_pins_the_endpoint_and_never_sends_rejected_parameters():
    payload = build_payload(OSS, system="sys", user="usr", schema_name="s", schema=SCHEMA, max_tokens=2000)

    assert payload["provider"] == {
        "order": ["deepinfra/bf16"], "only": ["deepinfra/bf16"], "allow_fallbacks": False,
        "require_parameters": True, "zdr": True, "data_collection": "deny", "quantizations": ["bf16"],
    }
    assert payload["response_format"] == {"type": "json_schema",
                                          "json_schema": {"name": "s", "strict": True, "schema": SCHEMA}}
    assert payload["reasoning"] == {"effort": "low"}
    assert payload["max_tokens"] == 2000
    assert "max_completion_tokens" not in payload and "temperature" not in payload
    assert payload["messages"] == [{"role": "system", "content": "sys"}, {"role": "user", "content": "usr"}]


def test_no_quantization_filter_when_none_is_pinned():
    assert "quantizations" not in build_payload(CLAUDE, system="", user="", schema_name="s", schema=SCHEMA,
                                                max_tokens=2000)["provider"]


@responses.activate
def test_successful_call_reports_provider_cost_and_tokens():
    _chat_ok()
    _gen_ok()

    call = _call(_client())

    assert call.content == {"a": 1}
    assert (call.generation_id, call.provider_name, call.cost_usd) == ("gen-123", "Google", 0.0021)
    assert (call.prompt_tokens, call.completion_tokens) == (120, 40)
    assert responses.calls[0].request.headers["Authorization"] == "Bearer sk-or-secret"
    assert responses.calls[1].request.url.endswith("/generation?id=gen-123")


@responses.activate
def test_provider_mismatch_is_rejected():
    _chat_ok()
    _gen_ok(provider="Amazon Bedrock")

    with pytest.raises(LlmProviderMismatchError, match="Amazon Bedrock"):
        _call(_client())


@responses.activate
def test_generation_stats_are_retried_until_available():
    _chat_ok()
    responses.add(responses.GET, GEN, status=404)
    _gen_ok()

    assert _call(_client()).provider_name == "Google"


@responses.activate
def test_missing_generation_stats_reject_the_answer():
    _chat_ok()
    for _ in range(5):
        responses.add(responses.GET, GEN, status=404)

    with pytest.raises(LlmUnavailableError, match="fournisseur"):
        _call(_client())


@responses.activate
@pytest.mark.parametrize("status", [401, 402, 403, 404])
def test_refusals_are_permanent_and_never_echo_the_key(status):
    responses.add(responses.POST, CHAT, status=status, json={"error": {"message": "refus"}})

    with pytest.raises(LlmPermanentError) as excinfo:
        _call(_client())
    assert "sk-or-secret" not in str(excinfo.value)


@responses.activate
@pytest.mark.parametrize("status", [429, 500, 503])
def test_throttling_and_server_errors_are_transient(status):
    responses.add(responses.POST, CHAT, status=status)

    with pytest.raises(LlmUnavailableError):
        _call(_client())


@responses.activate
def test_unreachable_service_is_transient_and_never_echoes_the_key():
    responses.add(responses.POST, CHAT, body=requests.ConnectionError("refusé"))

    with pytest.raises(LlmUnavailableError) as excinfo:
        _call(_client())
    assert "sk-or-secret" not in str(excinfo.value)


@responses.activate
def test_non_json_content_is_unavailable():
    _chat_ok(content="pas du json")

    with pytest.raises(LlmUnavailableError, match="JSON"):
        _call(_client())


def test_an_empty_key_is_refused_upfront():
    with pytest.raises(LlmPermanentError):
        OpenRouterClient("  ")

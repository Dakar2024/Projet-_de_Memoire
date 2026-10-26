
import pytest
import requests
import responses

from RAG.src.llm.openrouter import OPENROUTER_BASE_URL, OpenRouterClient, build_payload
from RAG.src.utils.config import LlmProfile
from RAG.src.utils.errors import (
    LlmPermanentError,
    LlmProviderMismatchError,
    LlmTruncatedError,
    LlmUnavailableError,
)

CLAUDE = LlmProfile("claude-opus-5.5", "anthropic/claude-opus-5.5", "google-vertex/europe", "Google", None)
OSS = LlmProfile("gpt-oss-120b", "openai/gpt-oss-120b", "deepinfra/bf16", "DeepInfra", "bf16")
SCHEMA = {"type": "object", "properties": {}, "additionalProperties": False, "required": []}
CHAT = f"{OPENROUTER_BASE_URL}/chat/completions"
_ABSENT = object()


def _client(**kwargs) -> OpenRouterClient:
    kwargs.setdefault("sleep", lambda seconds: None)
    return OpenRouterClient("sk-or-secret", session=requests.Session(), **kwargs)


def _call(client, profile=CLAUDE):
    return client.complete_json(profile, system="sys", user="usr", schema_name="s", schema=SCHEMA, max_tokens=2000)


def _chat_ok(content='{"a": 1}', finish_reason="stop", usage=None, provider="Google", cost=0.0021):
    """Réponse de chat telle qu'observée le 05/10/2026 : `provider` au premier niveau
    (hors schéma documenté) et `usage.cost` en dollars. `_ABSENT` retire le champ."""
    if usage is None:
        usage = {"prompt_tokens": 120, "completion_tokens": 40, "total_tokens": 160, "is_byok": False,
                 "cost_details": {"upstream_inference_cost": None}}
        if cost is not _ABSENT:
            usage["cost"] = cost
    body = {"id": "gen-123", "object": "chat.completion", "model": "m",
            "choices": [{"message": {"content": content}, "finish_reason": finish_reason}], "usage": usage}
    if provider is not _ABSENT:
        body["provider"] = provider
    responses.add(responses.POST, CHAT, json=body)


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
def test_successful_call_reads_provider_and_cost_from_the_chat_response():
    _chat_ok()

    call = _call(_client())

    assert call.content == {"a": 1}
    assert (call.generation_id, call.provider_name, call.cost_usd) == ("gen-123", "Google", 0.0021)
    assert (call.prompt_tokens, call.completion_tokens) == (120, 40)
    assert responses.calls[0].request.headers["Authorization"] == "Bearer sk-or-secret"
    assert len(responses.calls) == 1 and responses.calls[0].request.method == "POST"
    assert responses.calls[0].request.url == CHAT


@responses.activate
def test_provider_mismatch_is_rejected():
    _chat_ok(provider="Amazon Bedrock")

    with pytest.raises(LlmProviderMismatchError, match="Amazon Bedrock"):
        _call(_client())


@responses.activate
@pytest.mark.parametrize("status", [401, 402, 403, 404])
def test_refusals_are_permanent_and_never_echo_the_key(status):
    """Le corps d'erreur peut citer la clé ou la question (donnée de santé) : seuls le
    statut, le profil et un code court passent dans le message."""
    responses.add(responses.POST, CHAT, status=status, json={"error": {
        "message": "clé sk-or-secret refusée pour : usr", "code": status, "metadata": {"raw": "sk-or-secret"}}})

    with pytest.raises(LlmPermanentError) as excinfo:
        _call(_client())
    message = str(excinfo.value)
    assert "sk-or-secret" not in message and "usr" not in message and "refusée" not in message
    assert str(status) in message and CLAUDE.name in message


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


@responses.activate
def test_a_refusal_keeps_a_short_error_code_but_never_a_long_one():
    responses.add(responses.POST, CHAT, status=400, json={"error": {"code": "invalid_schema", "message": "usr"}})
    with pytest.raises(LlmPermanentError, match="invalid_schema") as excinfo:
        _call(_client())
    assert "usr" not in str(excinfo.value)

    responses.add(responses.POST, CHAT, status=400, json={"error": {"code": "usr " * 30}})
    with pytest.raises(LlmPermanentError) as excinfo:
        _call(_client())
    assert "usr" not in str(excinfo.value)


@responses.activate
def test_a_non_json_refusal_body_is_never_echoed():
    responses.add(responses.POST, CHAT, status=401, body="<html>sk-or-secret usr</html>")

    with pytest.raises(LlmPermanentError) as excinfo:
        _call(_client())
    assert "sk-or-secret" not in str(excinfo.value) and "usr" not in str(excinfo.value)


@responses.activate
def test_a_zero_cost_is_accepted():
    _chat_ok(cost=0)

    assert _call(_client()).cost_usd == 0.0


@responses.activate
def test_a_truncated_answer_is_permanent_and_keeps_its_cost():
    _chat_ok(content='{"a": ', finish_reason="length", cost=0.03)

    with pytest.raises(LlmTruncatedError, match="llm.max_tokens") as excinfo:
        _call(_client())
    assert isinstance(excinfo.value, LlmPermanentError)
    assert excinfo.value.cost_usd == 0.03
    assert len(responses.calls) == 1


@responses.activate
@pytest.mark.parametrize("content", [None, "", "   "])
def test_an_empty_answer_is_treated_as_truncated(content):
    _chat_ok(content=content)

    with pytest.raises(LlmTruncatedError) as excinfo:
        _call(_client())
    assert excinfo.value.cost_usd == 0.0021


@responses.activate
@pytest.mark.parametrize("usage", [[1, 2], "beaucoup", {"prompt_tokens": "abc"}])
def test_malformed_usage_is_unavailable(usage):
    _chat_ok(usage=usage)

    with pytest.raises(LlmUnavailableError, match="incomplète"):
        _call(_client())


@responses.activate
@pytest.mark.parametrize("provider", [_ABSENT, None, "", "   ", 42, ["Google"], {"name": "Google"}])
def test_an_unprovable_provider_rejects_the_answer(provider):
    """Le champ `provider` n'est pas dans le schéma documenté : s'il manque ou n'est pas
    une chaîne non vide, on ne peut pas prouver le point d'accès, la réponse est rejetée."""
    _chat_ok(provider=provider)

    with pytest.raises(LlmUnavailableError, match="fournisseur") as excinfo:
        _call(_client())
    assert not isinstance(excinfo.value, LlmProviderMismatchError)
    assert len(responses.calls) == 1


@responses.activate
@pytest.mark.parametrize("cost", [_ABSENT, None, -0.01, float("nan"), float("inf"), True, "0.002"])
def test_an_absent_or_invalid_cost_rejects_the_answer(cost):
    _chat_ok(cost=cost)

    with pytest.raises(LlmUnavailableError, match="coût réel absent ou invalide"):
        _call(_client())
    assert len(responses.calls) == 1


@responses.activate
@pytest.mark.parametrize("cost", [_ABSENT, None, -1, "0.03"])
def test_a_truncated_answer_with_an_invalid_cost_has_an_unknown_cost(cost):
    _chat_ok(content=None, finish_reason="length", cost=cost)

    with pytest.raises(LlmTruncatedError) as excinfo:
        _call(_client())
    assert excinfo.value.cost_usd is None


@responses.activate
@pytest.mark.parametrize("provider", [_ABSENT, "Amazon Bedrock"])
def test_a_truncated_answer_stays_truncated_whatever_the_provider(provider):
    """Une coupure est permanente : elle prime sur un fournisseur absent ou différent."""
    _chat_ok(content='{"a": ', finish_reason="length", provider=provider, cost=0.03)

    with pytest.raises(LlmTruncatedError) as excinfo:
        _call(_client())
    assert excinfo.value.cost_usd == 0.03


@responses.activate
@pytest.mark.parametrize("provider, cost", [
    (_ABSENT, 0.0021), ({"raw": "sk-or-secret usr"}, 0.0021), ("Google", "sk-or-secret usr"),
])
def test_rejections_never_echo_the_key_or_the_question(provider, cost):
    """Un champ invalide n'est jamais recopié dans le message : il vient du corps de la réponse."""
    _chat_ok(provider=provider, cost=cost)

    with pytest.raises(LlmUnavailableError) as excinfo:
        _call(_client())
    assert "sk-or-secret" not in str(excinfo.value) and "usr" not in str(excinfo.value)


def test_the_client_no_longer_accepts_a_generation_retry_schedule():
    with pytest.raises(TypeError):
        OpenRouterClient("sk-or-secret", generation_attempts=8)


@responses.activate
def test_received_503_is_retried_once_then_succeeds():
    waits = []
    responses.add(responses.POST, CHAT, status=503)
    _chat_ok()

    result = _call(_client(sleep=waits.append))

    assert result.content == {"a": 1}
    assert waits == [1.0] and len(responses.calls) == 2


@responses.activate
def test_connection_error_is_not_retried():
    waits = []
    responses.add(responses.POST, CHAT, body=requests.ConnectionError("coupé"))

    with pytest.raises(LlmUnavailableError):
        _call(_client(sleep=waits.append))

    assert len(responses.calls) == 1 and waits == []


def test_close_closes_the_session():
    closed = []

    class Session:
        def close(self):
            closed.append(1)

    OpenRouterClient("sk-or-secret", session=Session()).close()

    assert closed == [1]

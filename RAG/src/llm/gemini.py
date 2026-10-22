"""Client Gemini direct (interface compatible OpenAI), offre gratuite : juge de E3a seulement, jamais l'application."""
from __future__ import annotations

import time
from collections.abc import Callable

import requests

from RAG.src.llm.common import (
    PERMANENT_STATUSES,
    LlmCall,
    chat_messages,
    error_code,
    json_object,
    json_schema_format,
    read_chat_reply,
)
from RAG.src.llm.groq import parse_duration
from RAG.src.utils.config import LlmProfile
from RAG.src.utils.errors import (
    LlmPermanentError,
    LlmQuotaExhaustedError,
    LlmTruncatedError,
    LlmUnavailableError,
    RagConfigurationError,
)

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
GEMINI_PROVIDER_NAME = "Google"
_SERVICE = "Gemini"
# 429 (quota par minute) et 503 (« high demand », fréquent sur l'offre gratuite) : attente bornée puis abandon.
RETRY_STATUSES = (429, 502, 503)
MAX_WAIT_S = 60.0
DEFAULT_WAIT_S = 10.0
_RETRY_INFO = "type.googleapis.com/google.rpc.RetryInfo"


def build_payload(profile: LlmProfile, *, system: str, user: str, schema_name: str,
                  schema: dict, max_tokens: int) -> dict:
    """Construit la requête (`reasoning_effort` → `thinking_level`) ; refuse un profil que Gemini ne peut honorer."""
    if profile.backend != "gemini":
        raise RagConfigurationError(f"profil {profile.name} : backend {profile.backend!r}, pas gemini")
    if profile.provider_name != GEMINI_PROVIDER_NAME:
        raise RagConfigurationError(
            f"profil {profile.name} : provider_name doit valoir « {GEMINI_PROVIDER_NAME} » (appel direct à Gemini)")
    if profile.quantization is not None:
        raise RagConfigurationError(f"profil {profile.name} : Gemini ne permet pas de figer une quantification")
    return {
        "model": profile.model,
        "messages": chat_messages(system, user),
        "response_format": json_schema_format(schema_name, schema),
        "reasoning_effort": "low",
        "max_tokens": max_tokens,
    }


def retry_delay(response: requests.Response) -> float | None:
    """Lit l'attente annoncée (`Retry-After`, sinon `RetryInfo.retryDelay` du corps), ou None."""
    seconds = parse_duration(response.headers.get("Retry-After"))
    if seconds is not None:
        return seconds
    try:
        body = response.json()
        # L'interface compatible OpenAI renvoie parfois l'erreur dans une liste.
        error = (body[0] if isinstance(body, list) else body)["error"]
        for detail in error.get("details") or ():
            if isinstance(detail, dict) and detail.get("@type") == _RETRY_INFO:
                return parse_duration(detail.get("retryDelay"))
    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
        return None
    return None


class GeminiClient:
    """Client Gemini à sortie JSON imposée, avec attente bornée sur 429 et 503."""

    def __init__(self, api_key: str, *, timeout_s: float = 60.0, session: requests.Session | None = None,
                 base_url: str = GEMINI_BASE_URL, sleep: Callable[[float], None] = time.sleep,
                 max_waits: int = 4) -> None:
        if not api_key or not api_key.strip():
            raise LlmPermanentError("clé Gemini vide (GEMINI_API_KEY)")
        self._headers = {"Authorization": f"Bearer {api_key.strip()}"}
        self._timeout = timeout_s
        self._session = session or requests.Session()
        self._base = base_url.rstrip("/")
        self._sleep = sleep
        self._max_waits = max_waits

    def close(self) -> None:
        """Ferme la session HTTP."""
        self._session.close()

    def _send(self, payload: dict) -> requests.Response:
        """Envoie la requête ; une erreur réseau ou un délai dépassé devient transitoire."""
        try:
            return self._session.post(f"{self._base}/chat/completions", headers=self._headers, json=payload,
                                      timeout=self._timeout)
        except requests.RequestException as exc:
            raise LlmUnavailableError(f"Gemini injoignable : {type(exc).__name__}") from exc

    def complete_json(self, profile: LlmProfile, *, system: str, user: str, schema_name: str,
                      schema: dict, max_tokens: int) -> LlmCall:
        """Appelle le modèle (coût 0, offre gratuite) ; 429 persistant → `LlmQuotaExhaustedError`."""
        payload = build_payload(profile, system=system, user=user, schema_name=schema_name,
                                schema=schema, max_tokens=max_tokens)
        response = self._send(payload)
        for _ in range(self._max_waits):
            if response.status_code not in RETRY_STATUSES:
                break
            announced = retry_delay(response)
            self._sleep(min(DEFAULT_WAIT_S if announced is None else announced, MAX_WAIT_S))
            response = self._send(payload)
        if response.status_code == 429:
            raise LlmQuotaExhaustedError(f"quota Gemini épuisé (429) pour {profile.name}",
                                         retry_after_s=retry_delay(response))
        if response.status_code in PERMANENT_STATUSES:
            raise LlmPermanentError(
                f"Gemini refuse la requête ({response.status_code}) pour {profile.name}{error_code(response)}")
        if response.status_code >= 400:
            raise LlmUnavailableError(f"Gemini indisponible ({response.status_code}) pour {profile.name}")
        reply = read_chat_reply(response, _SERVICE)
        if reply.truncated:
            raise LlmTruncatedError(
                f"réponse coupée ou vide pour {profile.name} (finish_reason={reply.finish_reason!r}) : "
                "augmenter judge.max_tokens dans RAG/experiments/evaluation_e3a.yaml",
                cost_usd=0.0,
            )
        content = json_object(reply.raw_content, _SERVICE)
        return LlmCall(content=content, generation_id=reply.generation_id, provider_name=GEMINI_PROVIDER_NAME,
                       cost_usd=0.0, prompt_tokens=reply.prompt_tokens, completion_tokens=reply.completion_tokens)

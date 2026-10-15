"""Client OpenRouter : point d'accès figé, zéro rétention, fournisseur servi et coût réel vérifiés dans la réponse."""
from __future__ import annotations

import time
from collections.abc import Callable

import requests

from RAG.src.llm.common import (
    PERMANENT_STATUSES,
    LlmCall,
    chat_messages,
    error_code,
    is_cost,
    json_object,
    json_schema_format,
    post_with_bounded_retry,
    read_chat_reply,
)
from RAG.src.utils.config import LlmProfile
from RAG.src.utils.errors import (
    LlmPermanentError,
    LlmProviderMismatchError,
    LlmTruncatedError,
    LlmUnavailableError,
)

__all__ = ["OPENROUTER_BASE_URL", "LlmCall", "OpenRouterClient", "build_payload"]

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
_SERVICE = "OpenRouter"


def build_payload(profile: LlmProfile, *, system: str, user: str, schema_name: str,
                  schema: dict, max_tokens: int) -> dict:
    """Construit la requête ; ni `temperature` ni `max_completion_tokens`, qui excluraient le point d'accès figé."""
    provider = {
        "order": [profile.provider_tag], "only": [profile.provider_tag],
        "allow_fallbacks": False, "require_parameters": True,
        "zdr": True, "data_collection": "deny",
    }
    if profile.quantization:
        provider["quantizations"] = [profile.quantization]
    return {
        "model": profile.model,
        "messages": chat_messages(system, user),
        "response_format": json_schema_format(schema_name, schema),
        "provider": provider,
        "reasoning": {"effort": "low"},
        "max_tokens": max_tokens,
    }


class OpenRouterClient:
    """Client OpenRouter à sortie JSON imposée."""

    def __init__(self, api_key: str, *, timeout_s: float = 60.0, session: requests.Session | None = None,
                 base_url: str = OPENROUTER_BASE_URL,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        if not api_key or not api_key.strip():
            raise LlmPermanentError("clé OpenRouter vide (OPENROUTER_API_KEY)")
        self._headers = {"Authorization": f"Bearer {api_key.strip()}"}
        self._timeout = timeout_s
        # Sans relance automatique : relancer un POST payant pourrait le facturer deux fois.
        self._session = session or requests.Session()
        self._base = base_url.rstrip("/")
        self._sleep = sleep

    def close(self) -> None:
        """Ferme la session HTTP."""
        self._session.close()

    def _send(self, method: str, path: str, **kwargs) -> requests.Response:
        try:
            return self._session.request(method, f"{self._base}{path}", headers=self._headers,
                                         timeout=self._timeout, **kwargs)
        except requests.RequestException as exc:
            raise LlmUnavailableError(f"OpenRouter injoignable ({path}) : {type(exc).__name__}") from exc

    def complete_json(self, profile: LlmProfile, *, system: str, user: str, schema_name: str,
                      schema: dict, max_tokens: int) -> LlmCall:
        """Appelle le modèle et rejette une réponse coupée, d'un autre fournisseur ou sans coût."""
        payload = build_payload(profile, system=system, user=user, schema_name=schema_name,
                                schema=schema, max_tokens=max_tokens)
        response = post_with_bounded_retry(
            lambda: self._send("POST", "/chat/completions", json=payload), sleep=self._sleep)
        if response.status_code in PERMANENT_STATUSES:
            raise LlmPermanentError(
                f"OpenRouter refuse la requête ({response.status_code}) pour {profile.name}"
                f"{error_code(response)}"
            )
        if response.status_code >= 400:
            raise LlmUnavailableError(f"OpenRouter indisponible ({response.status_code}) pour {profile.name}")
        reply = read_chat_reply(response, _SERVICE)
        # Lus avant le contrôle de coupure : une réponse coupée reste facturée.
        served = reply.data.get("provider")
        cost = reply.usage.get("cost")
        # Une coupure est permanente : elle prime sur un fournisseur ou un coût invérifiable.
        if reply.truncated:
            raise LlmTruncatedError(
                f"réponse coupée ou vide pour {profile.name} (finish_reason={reply.finish_reason!r}) : "
                "augmenter llm.max_tokens dans RAG/config.yaml",
                cost_usd=float(cost) if is_cost(cost) else None,
            )
        content = json_object(reply.raw_content, _SERVICE)
        # Sans `provider`, le point d'accès est improuvable ; la valeur reçue n'est pas recopiée.
        if not (isinstance(served, str) and served.strip()):
            raise LlmUnavailableError(
                f"fournisseur servi improuvable pour {profile.name} : champ provider absent ou invalide dans la réponse"
            )
        if served != profile.provider_name:
            raise LlmProviderMismatchError(
                f"servi par « {served} » au lieu de « {profile.provider_name} » ({profile.name})"
            )
        if not is_cost(cost):
            raise LlmUnavailableError(f"coût réel absent ou invalide dans la réponse pour {profile.name}")
        return LlmCall(content=content, generation_id=reply.generation_id, provider_name=served,
                       cost_usd=float(cost), prompt_tokens=reply.prompt_tokens,
                       completion_tokens=reply.completion_tokens)

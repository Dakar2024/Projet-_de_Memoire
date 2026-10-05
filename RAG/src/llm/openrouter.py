"""Client OpenRouter (E2a). Seul fichier du projet qui connaît OpenRouter.

Chaque requête est figée sur un point d'accès précis (fournisseur, quantification),
sans basculement, en zéro rétention, avec sortie JSON imposée. Après la réponse, le
fournisseur réellement servi et le coût réel sont lus sur `GET /generation` : la
réponse de chat ne les donne pas dans ses champs documentés (vérifié le 05/10/2026).
Une réponse servie par un autre fournisseur est rejetée.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass

import requests

from RAG.src.utils.config import LlmProfile
from RAG.src.utils.errors import LlmPermanentError, LlmProviderMismatchError, LlmUnavailableError

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
_PERMANENT = (400, 401, 402, 403, 404)
_TRANSIENT = (408, 429, 500, 502, 503, 504)


@dataclass(frozen=True)
class LlmCall:
    content: dict
    generation_id: str
    provider_name: str
    cost_usd: float
    prompt_tokens: int
    completion_tokens: int


def build_payload(profile: LlmProfile, *, system: str, user: str, schema_name: str,
                  schema: dict, max_tokens: int) -> dict:
    """Corps de requête. `max_tokens` plutôt que `max_completion_tokens`, et pas de
    `temperature` : avec `require_parameters`, un paramètre refusé par le point
    d'accès figé l'exclurait (vérifié sur l'API publique le 05/10/2026)."""
    provider = {
        "order": [profile.provider_tag], "only": [profile.provider_tag],
        "allow_fallbacks": False, "require_parameters": True,
        "zdr": True, "data_collection": "deny",
    }
    if profile.quantization:
        provider["quantizations"] = [profile.quantization]
    return {
        "model": profile.model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "response_format": {"type": "json_schema",
                            "json_schema": {"name": schema_name, "strict": True, "schema": schema}},
        "provider": provider,
        "reasoning": {"effort": "low"},
        "max_tokens": max_tokens,
    }


class OpenRouterClient:
    def __init__(self, api_key: str, *, timeout_s: float = 60.0, session: requests.Session | None = None,
                 base_url: str = OPENROUTER_BASE_URL, generation_attempts: int = 5,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        if not api_key or not api_key.strip():
            raise LlmPermanentError("clé OpenRouter vide (OPENROUTER_API_KEY)")
        self._headers = {"Authorization": f"Bearer {api_key.strip()}"}
        self._timeout = timeout_s
        # Session sans relance automatique : relancer un POST payant pourrait facturer
        # deux fois la même analyse. La lecture de /generation a sa propre boucle.
        self._session = session or requests.Session()
        self._base = base_url.rstrip("/")
        self._attempts = generation_attempts
        self._sleep = sleep

    def _send(self, method: str, path: str, **kwargs) -> requests.Response:
        try:
            return self._session.request(method, f"{self._base}{path}", headers=self._headers,
                                         timeout=self._timeout, **kwargs)
        except requests.RequestException as exc:
            # Ni les en-têtes ni la clé dans le message.
            raise LlmUnavailableError(f"OpenRouter injoignable ({path}) : {type(exc).__name__}") from exc

    def complete_json(self, profile: LlmProfile, *, system: str, user: str, schema_name: str,
                      schema: dict, max_tokens: int) -> LlmCall:
        payload = build_payload(profile, system=system, user=user, schema_name=schema_name,
                                schema=schema, max_tokens=max_tokens)
        response = self._send("POST", "/chat/completions", json=payload)
        if response.status_code in _PERMANENT:
            raise LlmPermanentError(
                f"OpenRouter refuse la requête ({response.status_code}) pour {profile.name} : "
                f"{response.text[:300]}"
            )
        if response.status_code in _TRANSIENT or response.status_code >= 400:
            raise LlmUnavailableError(f"OpenRouter indisponible ({response.status_code}) pour {profile.name}")
        try:
            data = response.json()
            generation_id = str(data["id"])
            content = json.loads(data["choices"][0]["message"]["content"])
            usage = data.get("usage") or {}
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LlmUnavailableError(f"réponse OpenRouter non JSON ou incomplète : {exc!r}") from exc
        if not isinstance(content, dict):
            raise LlmUnavailableError("réponse OpenRouter : le JSON attendu est un objet")
        provider_name, cost = self._generation_stats(generation_id)
        if provider_name != profile.provider_name:
            raise LlmProviderMismatchError(
                f"servi par « {provider_name} » au lieu de « {profile.provider_name} » ({profile.name})"
            )
        return LlmCall(content=content, generation_id=generation_id, provider_name=provider_name,
                       cost_usd=cost, prompt_tokens=int(usage.get("prompt_tokens") or 0),
                       completion_tokens=int(usage.get("completion_tokens") or 0))

    def _generation_stats(self, generation_id: str) -> tuple[str, float]:
        """Fournisseur réellement servi et coût réel. Sans eux, la réponse est
        rejetée : on ne peut pas prouver qu'elle respecte le point d'accès figé."""
        for attempt in range(self._attempts):
            response = self._send("GET", "/generation", params={"id": generation_id})
            if response.status_code == 200:
                try:
                    stats = response.json()["data"]
                    return str(stats["provider_name"]), float(stats.get("total_cost") or 0.0)
                except (ValueError, KeyError, TypeError) as exc:
                    raise LlmUnavailableError(f"statistiques de génération illisibles : {exc!r}") from exc
            if attempt + 1 < self._attempts:
                self._sleep(1.0)
        raise LlmUnavailableError(
            f"fournisseur de la génération {generation_id} invérifiable : statistiques indisponibles"
        )

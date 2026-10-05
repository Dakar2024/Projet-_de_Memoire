"""Client OpenRouter (E2a). Seul fichier du projet qui connaît OpenRouter.

Chaque requête est figée sur un point d'accès précis (fournisseur, quantification),
sans basculement, en zéro rétention, avec sortie JSON imposée. Après la réponse, le
fournisseur réellement servi et le coût réel sont lus sur `GET /generation` : la
réponse de chat ne les donne pas dans ses champs documentés (vérifié le 05/10/2026).
Une réponse servie par un autre fournisseur est rejetée.

Limite connue : `provider_name` prouve le fournisseur, pas la région ni le point
d'accès exact (« Google » ne distingue pas Vertex Europe d'une autre région). La
région est imposée par `only` dans la requête ; elle n'est pas revérifiée après coup.

Les messages d'erreur ne citent jamais le corps d'une réponse : il peut reprendre la
question (donnée de santé) ou des en-têtes. Seuls le statut, le profil et un code
d'erreur court y figurent.
"""

from __future__ import annotations

import json
import math
import time
from collections.abc import Callable
from dataclasses import dataclass

import requests

from RAG.src.utils.config import LlmProfile
from RAG.src.utils.errors import (
    LlmPermanentError,
    LlmProviderMismatchError,
    LlmTruncatedError,
    LlmUnavailableError,
)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
_PERMANENT = (400, 401, 402, 403, 404)
_TRANSIENT = (408, 429, 500, 502, 503, 504)
_MAX_CODE_CHARS = 40


def _error_code(response: requests.Response) -> str:
    """Code d'erreur d'OpenRouter, s'il est un entier ou une chaîne courte. Jamais
    `error.message` ni le reste du corps : ils peuvent citer la question."""
    try:
        code = response.json()["error"]["code"]
    except (ValueError, KeyError, TypeError):
        return ""
    if isinstance(code, int) and not isinstance(code, bool):
        return f", code {code}"
    if isinstance(code, str) and 0 < len(code) <= _MAX_CODE_CHARS and code.replace("_", "").replace("-", "").isalnum():
        return f", code {code}"
    return ""


def _is_cost(value: object) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and value >= 0)


def _generation_delay(attempt: int) -> float:
    """Attente avant la tentative suivante : 0,5, 1, 2, puis 4 s."""
    return min(0.5 * 2 ** attempt, 4.0)


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
                 base_url: str = OPENROUTER_BASE_URL, generation_attempts: int = 8,
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
                f"OpenRouter refuse la requête ({response.status_code}) pour {profile.name}"
                f"{_error_code(response)}"
            )
        if response.status_code in _TRANSIENT or response.status_code >= 400:
            raise LlmUnavailableError(f"OpenRouter indisponible ({response.status_code}) pour {profile.name}")
        try:
            data = response.json()
            generation_id = str(data["id"])
            choice = data["choices"][0]
            raw_content = choice["message"]["content"]
            finish_reason = choice.get("finish_reason")
            usage = data.get("usage") or {}
            if not isinstance(usage, dict):
                raise TypeError("usage n'est pas un objet")
            prompt_tokens = int(usage.get("prompt_tokens") or 0)
            completion_tokens = int(usage.get("completion_tokens") or 0)
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LlmUnavailableError(f"réponse OpenRouter non JSON ou incomplète : {type(exc).__name__}") from exc
        if finish_reason == "length" or raw_content is None or (isinstance(raw_content, str)
                                                                  and not raw_content.strip()):
            raise LlmTruncatedError(
                f"réponse coupée ou vide pour {profile.name} (finish_reason={finish_reason!r}) : "
                "augmenter llm.max_tokens dans RAG/config.yaml",
                cost_usd=self._cost_if_available(generation_id),
            )
        try:
            content = json.loads(raw_content)
        except (ValueError, TypeError) as exc:
            raise LlmUnavailableError(f"réponse OpenRouter non JSON ou incomplète : {type(exc).__name__}") from exc
        if not isinstance(content, dict):
            raise LlmUnavailableError("réponse OpenRouter : le JSON attendu est un objet")
        provider_name, cost = self._generation_stats(generation_id)
        if provider_name != profile.provider_name:
            raise LlmProviderMismatchError(
                f"servi par « {provider_name} » au lieu de « {profile.provider_name} » ({profile.name})"
            )
        return LlmCall(content=content, generation_id=generation_id, provider_name=provider_name,
                       cost_usd=cost, prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)

    def _cost_if_available(self, generation_id: str) -> float | None:
        """Coût d'une réponse inexploitable mais facturée ; `None` s'il reste inconnu."""
        try:
            return self._generation_stats(generation_id)[1]
        except LlmUnavailableError:
            return None

    def _generation_stats(self, generation_id: str) -> tuple[str, float]:
        """Fournisseur réellement servi et coût réel. Sans eux, la réponse est
        rejetée : on ne peut pas prouver qu'elle respecte le point d'accès figé.

        Les statistiques arrivent avec un léger retard : une réponse en erreur, une
        coupure réseau, un fournisseur absent ou vide, un coût absent, négatif ou non
        fini signifient « pas encore prêtes », et on réessaie avec une attente croissante."""
        for attempt in range(self._attempts):
            try:
                response = self._send("GET", "/generation", params={"id": generation_id})
            except LlmUnavailableError:
                response = None
            if response is not None and response.status_code == 200:
                try:
                    stats = response.json()["data"]
                    provider_name, cost = stats["provider_name"], stats["total_cost"]
                except (ValueError, KeyError, TypeError, IndexError):
                    provider_name, cost = None, None
                if isinstance(provider_name, str) and provider_name.strip() and _is_cost(cost):
                    return provider_name, float(cost)
            if attempt + 1 < self._attempts:
                self._sleep(_generation_delay(attempt))
        raise LlmUnavailableError(
            f"fournisseur de la génération {generation_id} invérifiable : statistiques indisponibles"
        )

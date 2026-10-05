"""Client OpenRouter (E2a). Seul fichier du projet qui connaît OpenRouter.

Chaque requête est figée sur un point d'accès précis (fournisseur, quantification),
sans basculement, en zéro rétention, avec sortie JSON imposée. Le fournisseur
réellement servi et le coût réel sont lus dans la réponse de chat elle-même : le champ
`provider` de premier niveau et `usage.cost` (en dollars). `usage.cost` est documenté ;
`provider` ne l'est pas, il a été observé le 05/10/2026 avec et sans zéro rétention
(« DeepInfra » pour `deepinfra/bf16`). `GET /generation`, prévu à l'origine pour cette
preuve, répondait 404 pour toutes les générations de ce compte, même plusieurs minutes
après : il n'est plus appelé. Une réponse sans `provider` exploitable est rejetée (on
ne peut pas prouver le point d'accès) ; un autre fournisseur est rejeté aussi.

Limite connue : `provider` prouve le fournisseur, pas la région ni le point d'accès
exact (« Google » ne distingue pas Vertex Europe d'une autre région). La région est
imposée par `only` dans la requête ; elle n'est pas revérifiée après coup.

Les messages d'erreur ne citent jamais le corps d'une réponse : il peut reprendre la
question (donnée de santé) ou des en-têtes. Seuls le statut, le profil et un code
d'erreur court y figurent.
"""

from __future__ import annotations

import json
import math
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
                 base_url: str = OPENROUTER_BASE_URL) -> None:
        if not api_key or not api_key.strip():
            raise LlmPermanentError("clé OpenRouter vide (OPENROUTER_API_KEY)")
        self._headers = {"Authorization": f"Bearer {api_key.strip()}"}
        self._timeout = timeout_s
        # Session sans relance automatique : relancer un POST payant pourrait facturer
        # deux fois la même analyse.
        self._session = session or requests.Session()
        self._base = base_url.rstrip("/")

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
            # Lus avant le contrôle de coupure : une réponse coupée reste facturée.
            served = data.get("provider")
            cost = usage.get("cost")
        except (ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
            raise LlmUnavailableError(f"réponse OpenRouter non JSON ou incomplète : {type(exc).__name__}") from exc
        # Une coupure est permanente : elle prime sur un fournisseur ou un coût invérifiable.
        if finish_reason == "length" or raw_content is None or (isinstance(raw_content, str)
                                                                  and not raw_content.strip()):
            raise LlmTruncatedError(
                f"réponse coupée ou vide pour {profile.name} (finish_reason={finish_reason!r}) : "
                "augmenter llm.max_tokens dans RAG/config.yaml",
                cost_usd=float(cost) if _is_cost(cost) else None,
            )
        try:
            content = json.loads(raw_content)
        except (ValueError, TypeError) as exc:
            raise LlmUnavailableError(f"réponse OpenRouter non JSON ou incomplète : {type(exc).__name__}") from exc
        if not isinstance(content, dict):
            raise LlmUnavailableError("réponse OpenRouter : le JSON attendu est un objet")
        # Jamais d'acceptation silencieuse : sans `provider`, le point d'accès est improuvable.
        # La valeur invalide n'est pas recopiée dans le message (elle vient du corps).
        if not (isinstance(served, str) and served.strip()):
            raise LlmUnavailableError(
                f"fournisseur servi improuvable pour {profile.name} : champ provider absent ou invalide dans la réponse"
            )
        if served != profile.provider_name:
            raise LlmProviderMismatchError(
                f"servi par « {served} » au lieu de « {profile.provider_name} » ({profile.name})"
            )
        if not _is_cost(cost):
            raise LlmUnavailableError(f"coût réel absent ou invalide dans la réponse pour {profile.name}")
        return LlmCall(content=content, generation_id=generation_id, provider_name=served,
                       cost_usd=float(cost), prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)

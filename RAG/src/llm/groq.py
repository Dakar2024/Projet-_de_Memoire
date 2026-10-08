"""Client Groq (E2a), réservé à l'essai gratuit de validation de la chaîne.

Jamais utilisé par la mesure officielle (OpenRouter, règle de choix fixée d'avance) :
seuls les profils de `llm.trial_profiles` portent `backend: groq`.

Sources consultées le 05/10/2026, avec une requête minuscule sans donnée de santé :
- https://console.groq.com/docs/api-reference (chat/completions, compatible OpenAI) ;
  `reasoning: {effort}` y est refusé (400 « property 'reasoning' is unsupported »),
  `reasoning_effort` est accepté ;
- https://console.groq.com/docs/structured-outputs : gpt-oss-120b accepte
  `strict: true` (décodage contraint) ;
- https://console.groq.com/docs/rate-limits : offre gratuite de gpt-oss-120b à 30
  requêtes par minute, 1 000 par jour, 8 000 jetons par minute, 200 000 par jour ;
  en-têtes `retry-after` et `x-ratelimit-reset-tokens` (« 4.575s », « 1m26.4s ») ;
- https://console.groq.com/docs/your-data : pas de rétention par défaut, zéro
  rétention activable (activée par l'utilisateur dans Data Controls).

La réponse n'a ni champ `provider` ni `usage.cost` : l'appel va directement chez Groq,
c'est l'adresse appelée qui prouve le fournisseur, et l'offre gratuite ne coûte rien.
Groq ne permet de figer ni point d'accès ni quantification.
"""

from __future__ import annotations

import math
import re
import time
from collections.abc import Callable, Mapping

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
from RAG.src.utils.config import LlmProfile
from RAG.src.utils.errors import (
    LlmPermanentError,
    LlmQuotaExhaustedError,
    LlmTruncatedError,
    LlmUnavailableError,
    RagConfigurationError,
)

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_PROVIDER_NAME = "Groq"
_SERVICE = "Groq"
# Attente après un 429 : bornée, avec une valeur par défaut si les en-têtes sont illisibles.
MAX_RATE_LIMIT_WAIT_S = 60.0
DEFAULT_RATE_LIMIT_WAIT_S = 10.0
_DURATION = re.compile(r"(?:\d+(?:\.\d+)?(?:h|ms|m|s))+")
_DURATION_PART = re.compile(r"(\d+(?:\.\d+)?)(h|ms|m|s)")
_UNIT_SECONDS = {"h": 3600.0, "m": 60.0, "s": 1.0, "ms": 0.001}


def parse_duration(text: str | None) -> float | None:
    """Durée en secondes : nombre nu (`retry-after`) ou format Groq (« 4.575s »,
    « 1m26.4s », « 2m », « 250ms »). `None` si la valeur est illisible."""
    value = (text or "").strip()
    if re.fullmatch(r"\d+(?:\.\d+)?", value):
        return float(value)
    if not _DURATION.fullmatch(value):
        return None
    seconds = sum(float(number) * _UNIT_SECONDS[unit] for number, unit in _DURATION_PART.findall(value))
    return seconds if math.isfinite(seconds) else None


def rate_limit_wait(headers: Mapping[str, str]) -> float:
    """Attente avant de réessayer après un 429 : `retry-after`, sinon
    `x-ratelimit-reset-tokens`, sinon une valeur par défaut ; toujours bornée."""
    seconds = announced_wait(headers)
    return DEFAULT_RATE_LIMIT_WAIT_S if seconds is None else min(seconds, MAX_RATE_LIMIT_WAIT_S)


def announced_wait(headers: Mapping[str, str]) -> float | None:
    """Attente annoncée par un 429, non bornée : `retry-after`, sinon
    `x-ratelimit-reset-tokens` ; `None` si aucune n'est lisible."""
    for name in ("retry-after", "x-ratelimit-reset-tokens"):
        seconds = parse_duration(headers.get(name))
        if seconds is not None:
            return seconds
    return None


def quota_exhausted_reason(headers: Mapping[str, str]) -> str | None:
    """Motif d'arrêt si un 429 annonce un quota épuisé : plus aucune requête du jour, ou
    une attente au-delà du plafond. `x-ratelimit-reset-requests` ne compte que dans le
    premier cas : sur une réponse normale il annonce déjà plus d'une minute (« 1m26.4s »)."""
    if (headers.get("x-ratelimit-remaining-requests") or "").strip() == "0":
        reset = parse_duration(headers.get("x-ratelimit-reset-requests"))
        delay = f", réinitialisation annoncée dans {reset:.0f} s" if reset is not None else ""
        return f"plus aucune requête autorisée{delay}"
    wait = announced_wait(headers)
    if wait is not None and wait > MAX_RATE_LIMIT_WAIT_S:
        return f"réinitialisation annoncée dans {wait:.0f} s (plafond d'attente {MAX_RATE_LIMIT_WAIT_S:.0f} s)"
    return None


def build_payload(profile: LlmProfile, *, system: str, user: str, schema_name: str,
                  schema: dict, max_tokens: int) -> dict:
    """Corps de requête. `reasoning_effort` et non `reasoning` (refusé par Groq) ; ni bloc
    `provider`, ni `temperature`, ni `max_completion_tokens`. Un profil que Groq ne peut pas
    honorer (autre client, autre fournisseur, quantification figée) est refusé avant l'appel."""
    if profile.backend != "groq":
        raise RagConfigurationError(f"profil {profile.name} : backend {profile.backend!r}, pas groq")
    if profile.provider_name != GROQ_PROVIDER_NAME:
        raise RagConfigurationError(
            f"profil {profile.name} : provider_name doit valoir « {GROQ_PROVIDER_NAME} » (appel direct à Groq)")
    if profile.quantization is not None:
        raise RagConfigurationError(f"profil {profile.name} : Groq ne permet pas de figer une quantification")
    return {
        "model": profile.model,
        "messages": chat_messages(system, user),
        "response_format": json_schema_format(schema_name, schema),
        "reasoning_effort": "low",
        "max_tokens": max_tokens,
    }


class GroqClient:
    def __init__(self, api_key: str, *, timeout_s: float = 60.0, session: requests.Session | None = None,
                 base_url: str = GROQ_BASE_URL, sleep: Callable[[float], None] = time.sleep,
                 max_rate_limit_waits: int = 6) -> None:
        if not api_key or not api_key.strip():
            raise LlmPermanentError("clé Groq vide (GROQ_API_KEY)")
        self._headers = {"Authorization": f"Bearer {api_key.strip()}"}
        self._timeout = timeout_s
        # Session sans relance automatique : seuls les 429 sont réessayés, explicitement.
        self._session = session or requests.Session()
        self._base = base_url.rstrip("/")
        self._sleep = sleep
        self._max_waits = max_rate_limit_waits

    def _post(self, path: str, payload: dict) -> requests.Response:
        try:
            return self._session.post(f"{self._base}{path}", headers=self._headers, json=payload,
                                      timeout=self._timeout)
        except requests.RequestException as exc:
            # Ni les en-têtes ni la clé dans le message.
            raise LlmUnavailableError(f"Groq injoignable ({path}) : {type(exc).__name__}") from exc

    def complete_json(self, profile: LlmProfile, *, system: str, user: str, schema_name: str,
                      schema: dict, max_tokens: int) -> LlmCall:
        """Analyse au format `LlmCall`. `cost_usd` vaut toujours 0,0 : offre gratuite, et
        Groq ne renvoie aucun coût. Un 429 n'est pas facturé : on attend puis on réessaie,
        au plus `max_rate_limit_waits` fois ; un quota épuisé (aucune requête restante,
        attente annoncée au-delà du plafond, attentes épuisées) lève `LlmQuotaExhaustedError`."""
        payload = build_payload(profile, system=system, user=user, schema_name=schema_name,
                                schema=schema, max_tokens=max_tokens)
        waits = 0
        while True:
            response = self._post("/chat/completions", payload)
            if response.status_code != 429:
                break
            # Quota épuisé : attendre ne servirait à rien, ni pour cette question ni pour les suivantes.
            reason = quota_exhausted_reason(response.headers)
            if reason is not None:
                raise LlmQuotaExhaustedError(f"quota Groq épuisé (429) pour {profile.name} : {reason}",
                                             retry_after_s=announced_wait(response.headers))
            if waits >= self._max_waits:
                raise LlmQuotaExhaustedError(
                    f"quota Groq épuisé (429) pour {profile.name} : toujours dépassé après {waits} attentes",
                    retry_after_s=announced_wait(response.headers))
            waits += 1
            self._sleep(rate_limit_wait(response.headers))
        if response.status_code == 413:
            # Une seule requête dépasse la limite de jetons par minute : relancer ne changera rien.
            raise LlmPermanentError(
                f"Groq refuse la requête (413) pour {profile.name} : elle dépasse la limite de jetons "
                "par minute de l'offre gratuite, réduire llm.max_tokens ou le prompt")
        if response.status_code in PERMANENT_STATUSES:
            raise LlmPermanentError(
                f"Groq refuse la requête ({response.status_code}) pour {profile.name}{error_code(response)}")
        if response.status_code >= 400:
            raise LlmUnavailableError(f"Groq indisponible ({response.status_code}) pour {profile.name}")
        reply = read_chat_reply(response, _SERVICE)
        if reply.truncated:
            raise LlmTruncatedError(
                f"réponse coupée ou vide pour {profile.name} (finish_reason={reply.finish_reason!r}) : "
                "augmenter llm.max_tokens dans RAG/config.yaml",
                cost_usd=0.0,
            )
        content = json_object(reply.raw_content, _SERVICE)
        return LlmCall(content=content, generation_id=reply.generation_id, provider_name=GROQ_PROVIDER_NAME,
                       cost_usd=0.0, prompt_tokens=reply.prompt_tokens, completion_tokens=reply.completion_tokens)

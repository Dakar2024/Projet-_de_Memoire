"""Briques communes aux clients LLM ; les erreurs ne citent jamais le corps d'une réponse (donnée de santé)."""
from __future__ import annotations

import json
import math
from collections.abc import Callable
from dataclasses import dataclass

import requests

from RAG.src.utils.errors import LlmUnavailableError

# Refus que relancer ne corrigerait pas (requête, clé, crédit, modèle).
PERMANENT_STATUSES = (400, 401, 402, 403, 404)
# Statuts reçus après lesquels aucune génération n'a eu lieu : relançables sans risque de double facturation.
RETRY_STATUSES = (429, 502, 503)
_MAX_CODE_CHARS = 40


@dataclass(frozen=True)
class LlmCall:
    """Résultat d'un appel LLM : contenu JSON, fournisseur servi, coût et jetons."""

    content: dict
    generation_id: str
    provider_name: str
    cost_usd: float
    prompt_tokens: int
    completion_tokens: int


@dataclass(frozen=True)
class ChatReply:
    """Champs utiles d'une réponse de chat ; chaque client lit ses propres champs dans `data` et `usage`."""

    data: dict
    generation_id: str
    raw_content: object
    finish_reason: object
    usage: dict
    prompt_tokens: int
    completion_tokens: int

    @property
    def truncated(self) -> bool:
        """Indique une réponse vide ou coupée par le plafond de jetons."""
        content = self.raw_content
        return (self.finish_reason == "length" or content is None
                or (isinstance(content, str) and not content.strip()))


def error_code(response: requests.Response) -> str:
    """Renvoie le code d'erreur court du service, jamais `error.message` (il peut citer la question)."""
    try:
        code = response.json()["error"]["code"]
    except (ValueError, KeyError, TypeError):
        return ""
    if isinstance(code, int) and not isinstance(code, bool):
        return f", code {code}"
    if isinstance(code, str) and 0 < len(code) <= _MAX_CODE_CHARS and code.replace("_", "").replace("-", "").isalnum():
        return f", code {code}"
    return ""


def is_cost(value: object) -> bool:
    """Indique un coût valide : nombre fini et positif."""
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and value >= 0)


def chat_messages(system: str, user: str) -> list[dict]:
    """Construit les messages système et utilisateur."""
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def json_schema_format(schema_name: str, schema: dict) -> dict:
    """Impose une sortie JSON par schéma strict (décodage contraint)."""
    return {"type": "json_schema", "json_schema": {"name": schema_name, "strict": True, "schema": schema}}


def read_chat_reply(response: requests.Response, service: str) -> ChatReply:
    """Lit une réponse 200 au format OpenAI ; une réponse illisible est transitoire."""
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
    except (ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
        raise LlmUnavailableError(f"réponse {service} non JSON ou incomplète : {type(exc).__name__}") from exc
    return ChatReply(data=data, generation_id=generation_id, raw_content=raw_content,
                     finish_reason=finish_reason, usage=usage, prompt_tokens=prompt_tokens,
                     completion_tokens=completion_tokens)


def json_object(raw_content: object, service: str) -> dict:
    """Décode le contenu de la réponse en objet JSON, sinon erreur transitoire."""
    try:
        content = json.loads(raw_content)
    except (ValueError, TypeError) as exc:
        raise LlmUnavailableError(f"réponse {service} non JSON ou incomplète : {type(exc).__name__}") from exc
    if not isinstance(content, dict):
        raise LlmUnavailableError(f"réponse {service} : le JSON attendu est un objet")
    return content


def _retry_after(response: requests.Response) -> float | None:
    """Lit l'en-tête Retry-After en secondes, ou None."""
    value = response.headers.get("Retry-After")
    try:
        seconds = float(value) if value is not None else None
    except ValueError:
        return None
    return seconds if seconds is not None and math.isfinite(seconds) and seconds >= 0 else None


def post_with_bounded_retry(send: Callable[[], requests.Response], *, sleep: Callable[[float], None],
                            max_retries: int = 2, base_delay_s: float = 1.0, max_delay_s: float = 30.0,
                            statuses: tuple[int, ...] = RETRY_STATUSES) -> requests.Response:
    """Relance seulement sur 429/502/503 reçus (rien de facturé), jamais sur erreur réseau ; attente bornée."""
    response = send()
    for attempt in range(max_retries):
        if response.status_code not in statuses:
            return response
        announced = _retry_after(response)
        delay = announced if announced is not None else base_delay_s * (2 ** attempt)
        sleep(min(delay, max_delay_s))
        response = send()
    return response

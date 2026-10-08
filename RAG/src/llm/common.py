"""Briques communes aux clients LLM (OpenRouter pour la mesure officielle, Groq pour
l'essai) : résultat d'un appel, lecture d'une réponse de chat au format OpenAI, code
d'erreur court.

Les messages d'erreur ne citent jamais le corps d'une réponse : il peut reprendre la
question (donnée de santé) ou des en-têtes. Seuls le statut, le profil et un code
d'erreur court y figurent.
"""

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
    content: dict
    generation_id: str
    provider_name: str
    cost_usd: float
    prompt_tokens: int
    completion_tokens: int


@dataclass(frozen=True)
class ChatReply:
    """Champs utiles d'une réponse de chat. `data` et `usage` sont des objets JSON :
    chaque client y lit ses propres champs (fournisseur, coût)."""

    data: dict
    generation_id: str
    raw_content: object
    finish_reason: object
    usage: dict
    prompt_tokens: int
    completion_tokens: int

    @property
    def truncated(self) -> bool:
        """Réponse coupée par le plafond de jetons, ou vide."""
        content = self.raw_content
        return (self.finish_reason == "length" or content is None
                or (isinstance(content, str) and not content.strip()))


def error_code(response: requests.Response) -> str:
    """Code d'erreur du service, s'il est un entier ou une chaîne courte. Jamais
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


def is_cost(value: object) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and value >= 0)


def chat_messages(system: str, user: str) -> list[dict]:
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def json_schema_format(schema_name: str, schema: dict) -> dict:
    """Sortie JSON imposée par schéma strict (décodage contraint)."""
    return {"type": "json_schema", "json_schema": {"name": schema_name, "strict": True, "schema": schema}}


def read_chat_reply(response: requests.Response, service: str) -> ChatReply:
    """Lit une réponse 200 au format OpenAI. Toute réponse illisible est transitoire."""
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
    """Contenu de la réponse, décodé : un objet JSON, sinon transitoire."""
    try:
        content = json.loads(raw_content)
    except (ValueError, TypeError) as exc:
        raise LlmUnavailableError(f"réponse {service} non JSON ou incomplète : {type(exc).__name__}") from exc
    if not isinstance(content, dict):
        raise LlmUnavailableError(f"réponse {service} : le JSON attendu est un objet")
    return content


def _retry_after(response: requests.Response) -> float | None:
    value = response.headers.get("Retry-After")
    try:
        seconds = float(value) if value is not None else None
    except ValueError:
        return None
    return seconds if seconds is not None and math.isfinite(seconds) and seconds >= 0 else None


def post_with_bounded_retry(send: Callable[[], requests.Response], *, sleep: Callable[[float], None],
                            max_retries: int = 2, base_delay_s: float = 1.0, max_delay_s: float = 30.0,
                            statuses: tuple[int, ...] = RETRY_STATUSES) -> requests.Response:
    """Relance un appel seulement quand le service a RÉPONDU 429, 502 ou 503 : aucune
    génération n'a eu lieu, rien n'est facturé. Jamais sur une erreur réseau ni un délai
    dépassé, où la requête a pu être traitée (et facturée) sans que la réponse arrive.
    L'attente respecte `Retry-After`, plafonnée à `max_delay_s` ; après `max_retries`
    relances, la dernière réponse est rendue telle quelle."""
    response = send()
    for attempt in range(max_retries):
        if response.status_code not in statuses:
            return response
        announced = _retry_after(response)
        delay = announced if announced is not None else base_delay_s * (2 ** attempt)
        sleep(min(delay, max_delay_s))
        response = send()
    return response

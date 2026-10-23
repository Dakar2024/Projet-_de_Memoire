"""RAG failures → errors shown to the user (MODELISATION_BACKEND.md § 4.2, step 6).

Pure on purpose: the client hands over the status, the JSON body when there is one and the headers.
Every failure releases the quota reservation; the caller does that, not this module.
"""

import logging
from collections.abc import Mapping

from core.exceptions import AppError

logger = logging.getLogger(__name__)


class AssistantError(AppError):
    def __init__(self, code: str, status: int, message: str, retry_after: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.status = status
        self.headers = {"Retry-After": retry_after} if retry_after else None


_BUSY = "L'assistant traite beaucoup de questions. Réessayez dans quelques secondes."
_UNAVAILABLE = "L'assistant ne répond pas pour le moment. Votre question n'a pas été décomptée."


def assistant_unavailable(retry_after: str | None = None) -> AssistantError:
    return AssistantError("assistant_unavailable", 503, _UNAVAILABLE, retry_after)


def translate(status: int, body: Mapping | None, headers: Mapping[str, str]) -> AssistantError:
    """Map a non-200 answer of the RAG gateway to the backend's own error."""
    code = body.get("error") if isinstance(body, Mapping) else None
    retry_after = headers.get("retry-after")

    if status == 429:
        # Either the RAG's own "busy" (JSON) or the gateway's limit_req (an nginx HTML page):
        # the body cannot be relied on, the status is enough.
        return AssistantError("assistant_busy", 503, _BUSY, retry_after or "2")
    if status == 503 and code == "index_empty":
        return AssistantError("index_building", 503, "La base de fiches est en cours de construction.", retry_after)
    if status in (422, 413):
        return AssistantError("validation_error", 422, "Question invalide : de 1 à 1 000 caractères.")
    if status in (401, 403):
        # Configuration error, not the user's: the key in .env is missing or wrong.
        logger.error("RAG gateway refused the API key (HTTP %s): check RAG_API_KEY", status)
        return AssistantError("internal", 500, "Erreur interne du serveur")
    if status >= 500:
        # 503 timeout/unavailable from the RAG, or 502/504 from nginx when rag-api is down.
        return assistant_unavailable(retry_after)
    logger.error("Unexpected RAG gateway answer: HTTP %s (%s)", status, code)
    return AssistantError("internal", 500, "Erreur interne du serveur")

"""Client of the RAG gateway (POST /v1/questions). The API key never leaves the server."""

import logging
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from core.settings import settings
from features.assistant.rag_errors import AssistantError, assistant_unavailable, translate

logger = logging.getLogger(__name__)

AnswerStatus = Literal["answered", "partial", "not_in_sources", "out_of_scope", "unverifiable"]


class RagSource(BaseModel):
    """`Source.as_dict()` of RAG/src/generation/answer.py."""

    model_config = ConfigDict(extra="ignore")

    doc_id:                   str
    gene:                     str | None = None
    variant:                  str | None = None
    protein:                  str | None = None
    significance:             str | None = None
    significance_fr:          str | None = None
    review_status:            str | None = None
    clinvar_variation_id:     str | None = None
    clinvar_url:              str | None = None
    archive:                  str | None = None
    previous_significance:    str | None = None
    previous_significance_fr: str | None = None
    previous_until:           str | None = None


class RagAnswer(BaseModel):
    """`PipelineResult.as_dict(include_trace=True)` + `request_id` (RAG/src/api/app.py)."""

    model_config = ConfigDict(extra="ignore")

    status:       AnswerStatus
    answer:       str
    history:      list[str] = []
    sources:      list[RagSource] = []
    disclaimer:   str
    scope_reason: str | None = None
    timings_ms:   dict[str, float] = {}
    trace:        dict[str, Any] | None = None
    request_id:   str | None = None

    def _generation(self) -> dict[str, Any]:
        # Cost, model and provider are only in the trace: that is why the backend always asks for it.
        return (self.trace or {}).get("generation") or {}

    @property
    def cost_usd(self) -> float | None:
        return self._generation().get("cost_usd")

    @property
    def model(self) -> str | None:
        return self._generation().get("model")

    @property
    def provider_name(self) -> str | None:
        return self._generation().get("provider_name")


def build_http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=settings.RAG_BASE_URL,
        headers={"X-API-Key": settings.RAG_API_KEY},
        # Slightly longer than the RAG's own limit (120 s), so its 503 "timeout" arrives first.
        timeout=httpx.Timeout(settings.RAG_TIMEOUT_S, connect=5.0),
    )


class RagClient:
    def __init__(self, http: httpx.AsyncClient) -> None:
        self._http = http

    async def ask(self, question: str) -> RagAnswer:
        """One question, alone: the RAG has no memory and must judge each question by itself."""
        try:
            response = await self._http.post("/v1/questions", json={"question": question, "trace": True})
        except httpx.TimeoutException:
            raise assistant_unavailable() from None
        except httpx.TransportError as exc:
            logger.warning("RAG gateway unreachable: %s", type(exc).__name__)
            raise assistant_unavailable() from None

        if response.status_code != 200:
            try:
                body = response.json()
            except ValueError:
                body = None  # nginx pages are HTML
            raise translate(response.status_code, body, response.headers)
        try:
            return RagAnswer.model_validate_json(response.content)
        except ValidationError as exc:
            # The RAG contract changed: our bug, logged without the answer text.
            logger.error("Unexpected RAG answer shape: %s", [e["loc"] for e in exc.errors()])
            raise AssistantError("internal", 500, "Erreur interne du serveur") from None

    async def aclose(self) -> None:
        await self._http.aclose()

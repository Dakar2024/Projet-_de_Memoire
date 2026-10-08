"""API du RAG (E2b), Litestar. Écoute en local seulement (port publié sur 127.0.0.1) ;
clé d'API ; au plus N questions simultanées (emplacements du pipeline) ; délai total
borné ; erreurs sans détail interne ; journal sans texte.

Lancement : uvicorn RAG.src.api.app:create_app --factory"""

from __future__ import annotations

import asyncio
import math
import uuid
from contextlib import asynccontextmanager
from typing import Callable

import psycopg
from litestar import Litestar, Request, Response, get, post
from litestar.datastructures import State
from litestar.exceptions import HTTPException, NotAuthorizedException, ValidationException

from RAG.src.api.logs import configure_logging, log_event
from RAG.src.api.schemas import QuestionIn
from RAG.src.api.security import require_api_key
from RAG.src.utils.config import ApiConfig, load_api_config, load_api_key
from RAG.src.utils.errors import (
    EmbeddingServiceError, LlmProviderMismatchError, LlmQuotaExhaustedError, LlmUnavailableError,
    QuestionRejectedError, RagPermanentError,
)

_MESSAGES = {
    "unauthorized": "Clé d'API absente ou invalide.",
    "invalid_question": "Question invalide : texte de 1 à 1 000 caractères attendu.",
    "too_large": "Requête trop volumineuse.",
    "busy": "Trop de questions en cours ; réessayez dans quelques secondes.",
    "timeout": "La réponse a dépassé le délai autorisé ; réessayez.",
    "unavailable": "Service de génération ou de recherche momentanément indisponible ; réessayez.",
    "internal": "Erreur interne ; elle a été journalisée.",
    "not_found": "Ressource inconnue.",
    "method_not_allowed": "Méthode non autorisée pour cette ressource.",
    "invalid_request": "Requête invalide.",
}


class ApiError(Exception):
    def __init__(self, code: str, http_status: int, retry_after: float | None = None) -> None:
        super().__init__(code)
        self.code, self.http_status, self.retry_after = code, http_status, retry_after


def _classify(exc: BaseException) -> ApiError:
    if isinstance(exc, ApiError):
        return exc
    if isinstance(exc, NotAuthorizedException):
        return ApiError("unauthorized", 401)
    if isinstance(exc, (ValidationException, QuestionRejectedError)):
        return ApiError("invalid_question", 422)
    if isinstance(exc, HTTPException) and exc.status_code == 413:
        return ApiError("too_large", 413)
    if isinstance(exc, HTTPException) and exc.status_code == 404:
        return ApiError("not_found", 404)
    if isinstance(exc, HTTPException) and exc.status_code == 405:
        return ApiError("method_not_allowed", 405)
    if isinstance(exc, HTTPException) and 400 <= exc.status_code < 500:
        return ApiError("invalid_request", exc.status_code)
    if isinstance(exc, LlmQuotaExhaustedError):
        return ApiError("unavailable", 503, getattr(exc, "retry_after_s", None))
    if isinstance(exc, (LlmUnavailableError, LlmProviderMismatchError, EmbeddingServiceError, psycopg.OperationalError)):
        return ApiError("unavailable", 503)
    if isinstance(exc, RagPermanentError):
        return ApiError("internal", 500)
    return ApiError("internal", 500)


def _error_response(request: Request, exc: Exception) -> Response:
    """Seul chemin d'erreur : corps fixe, journal sans message d'exception (il pourrait
    contenir un extrait de la requête), seulement le nom de sa classe pour les 5xx."""
    err = _classify(exc)
    request_id = getattr(request.state, "request_id", None) or uuid.uuid4().hex
    log_event(event="error", request_id=request_id, http_status=err.http_status, error=err.code,
              **({"status": type(exc).__name__} if err.http_status >= 500 else {}))
    headers = {}
    if err.retry_after is not None and math.isfinite(err.retry_after):
        headers["Retry-After"] = str(max(1, math.ceil(err.retry_after)))
    return Response({"error": err.code, "message": _MESSAGES[err.code], "request_id": request_id},
                    status_code=err.http_status, headers=headers)


@get("/health", sync_to_thread=False)
def health() -> dict:
    return {"status": "ok"}


@get("/ready", guards=[require_api_key], sync_to_thread=True)
def ready(state: State) -> dict:
    return state.pipeline.ready()


@post("/v1/questions", guards=[require_api_key], status_code=200)
async def ask_question(data: QuestionIn, state: State, request: Request) -> dict:
    request_id = uuid.uuid4().hex
    request.state.request_id = request_id
    pipeline = state.pipeline
    slot = pipeline.acquire()
    if slot is None:
        raise ApiError("busy", 429)

    def run():
        # L'emplacement est rendu ici, une seule fois, quand le fil se termine : après un
        # délai dépassé, il reste occupé tant que la génération tourne encore.
        try:
            return pipeline.ask(slot, data.question)
        finally:
            try:
                pipeline.release(slot)
            except RuntimeError:
                # Pipeline déjà fermé (arrêt pendant que ce fil tournait) : rien à rendre.
                log_event(event="release_after_shutdown", request_id=request_id)

    future = asyncio.get_running_loop().run_in_executor(None, run)
    try:
        result = await asyncio.wait_for(asyncio.shield(future), timeout=state.api_config.request_timeout_s)
    except asyncio.TimeoutError:
        # Le résultat tardif (ou son erreur) est consommé pour ne pas être signalé plus tard.
        future.add_done_callback(lambda f: f.exception() if not f.cancelled() else None)
        raise ApiError("timeout", 503) from None
    body = result.as_dict(include_trace=data.trace)
    a = result.answer
    log_event(event="question", request_id=request_id, status=a.status, http_status=200,
              timings_ms=result.timings_ms, cost_usd=a.cost_usd, model=a.model, provider_name=a.provider_name,
              flags=result.search.trace.flags, rejected=a.rejected, scope_reason=a.scope_reason,
              sources=len(a.sources))
    return {**body, "request_id": request_id}


def create_app(pipeline_factory: Callable[[], object] | None = None, *, api_config: ApiConfig | None = None,
               api_key: str | None = None) -> Litestar:
    config = api_config or load_api_config()
    key = api_key or load_api_key()

    if pipeline_factory is None:
        from RAG.src.generation.pipeline import QuestionPipeline

        def pipeline_factory():
            return QuestionPipeline(config.max_concurrency)

    @asynccontextmanager
    async def lifespan(app: Litestar):
        # Le pipeline réel vérifie modèle, canari et index à l'entrée : en cas d'échec,
        # l'application ne démarre pas.
        pipeline = await asyncio.get_running_loop().run_in_executor(None, lambda: pipeline_factory().__enter__())
        app.state.pipeline = pipeline
        try:
            yield
        finally:
            pipeline.__exit__(None, None, None)

    configure_logging()
    return Litestar(
        route_handlers=[health, ready, ask_question],
        lifespan=[lifespan],
        state=State({"api_key": key, "api_config": config, "pipeline": None}),
        openapi_config=None,
        logging_config=None,
        request_max_body_size=config.max_body_bytes,
        exception_handlers={Exception: _error_response},
    )

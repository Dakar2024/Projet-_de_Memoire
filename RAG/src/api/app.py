"""API Litestar du RAG : clé d'API, concurrence et délai bornés, erreurs sans détail interne, journal sans texte."""
from __future__ import annotations

import asyncio
import math
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from typing import Callable

import psycopg
from litestar import Litestar, Request, Response, get, post
from litestar.datastructures import State
from litestar.exceptions import ClientException, HTTPException, NotAuthorizedException, ValidationException

from RAG.src.api.logs import configure_logging, log_event
from RAG.src.api.schemas import QuestionIn
from RAG.src.api.security import require_api_key, require_json
from RAG.src.utils.config import ApiConfig, load_api_config, load_api_key
from RAG.src.utils.errors import (
    EmbeddingServiceError, IndexEmptyError, LlmProviderMismatchError, LlmQuotaExhaustedError, LlmUnavailableError,
    QuestionRejectedError, RagPermanentError,
)

_MESSAGES = {
    "unauthorized": "Clé d'API absente ou invalide.",
    "invalid_question": "Question invalide : texte de 1 à 1 000 caractères attendu.",
    "too_large": "Requête trop volumineuse.",
    "busy": "Trop de questions en cours ; réessayez dans quelques secondes.",
    "timeout": "La réponse a dépassé le délai autorisé ; réessayez.",
    "unavailable": "Service de génération ou de recherche momentanément indisponible ; réessayez.",
    "index_empty": "Index pas encore construit : lancer l'indexation (DAG de panel), puis réessayer.",
    "internal": "Erreur interne ; elle a été journalisée.",
    "not_found": "Ressource inconnue.",
    "method_not_allowed": "Méthode non autorisée pour cette ressource.",
    "invalid_request": "Requête invalide.",
    "unsupported_media_type": "Corps attendu au format JSON (Content-Type: application/json).",
}


class ApiError(Exception):
    """Erreur renvoyée au client : code public, statut HTTP et éventuel Retry-After."""

    def __init__(self, code: str, http_status: int, retry_after: float | None = None) -> None:
        super().__init__(code)
        self.code, self.http_status, self.retry_after = code, http_status, retry_after


def _classify(exc: BaseException) -> ApiError:
    """Traduit une exception en erreur publique de l'API."""
    if isinstance(exc, ApiError):
        return exc
    if isinstance(exc, NotAuthorizedException):
        return ApiError("unauthorized", 401)
    if isinstance(exc, (ValidationException, QuestionRejectedError)):
        return ApiError("invalid_question", 422)
    if isinstance(exc, ClientException) and exc.status_code == 400:
        # Corps JSON illisible.
        return ApiError("invalid_question", 422)
    if isinstance(exc, HTTPException) and exc.status_code == 415:
        return ApiError("unsupported_media_type", 415)
    if isinstance(exc, HTTPException) and exc.status_code == 413:
        return ApiError("too_large", 413)
    if isinstance(exc, HTTPException) and exc.status_code == 404:
        return ApiError("not_found", 404)
    if isinstance(exc, HTTPException) and exc.status_code == 405:
        return ApiError("method_not_allowed", 405)
    if isinstance(exc, HTTPException) and 400 <= exc.status_code < 500:
        return ApiError("invalid_request", exc.status_code)
    if isinstance(exc, IndexEmptyError):
        return ApiError("index_empty", 503)
    if isinstance(exc, LlmQuotaExhaustedError):
        return ApiError("unavailable", 503, getattr(exc, "retry_after_s", None))
    if isinstance(exc, (LlmUnavailableError, LlmProviderMismatchError, EmbeddingServiceError, psycopg.OperationalError)):
        return ApiError("unavailable", 503)
    return ApiError("internal", 500)


def _error_response(request: Request, exc: Exception) -> Response:
    """Rend toute erreur avec un corps fixe ; le journal ne garde que la classe de l'exception (5xx)."""
    err = _classify(exc)
    request_id = getattr(request.state, "request_id", None) or uuid.uuid4().hex
    log_event(event="error", request_id=request_id, http_status=err.http_status, error=err.code,
              **({"exception": type(exc).__name__} if err.http_status >= 500 else {}))
    headers = {}
    if err.retry_after is not None and math.isfinite(err.retry_after):
        headers["Retry-After"] = str(max(1, math.ceil(err.retry_after)))
    return Response({"error": err.code, "message": _MESSAGES[err.code], "request_id": request_id},
                    status_code=err.http_status, headers=headers)


@get("/health", sync_to_thread=False)
def health() -> dict:
    """Indique que le processus répond."""
    return {"status": "ok"}


@get("/ready", guards=[require_api_key], sync_to_thread=True)
def ready(state: State) -> dict:
    """Indique si la base, l'index et le service d'embedding répondent."""
    return state.pipeline.ready()


@post("/v1/questions", guards=[require_api_key, require_json], status_code=200)
async def ask_question(data: QuestionIn, state: State, request: Request) -> dict:
    """Répond à une question dans un emplacement libre du pipeline, avec délai borné."""
    request_id = uuid.uuid4().hex
    request.state.request_id = request_id
    pipeline = state.pipeline
    slot = pipeline.acquire()
    if slot is None:
        raise ApiError("busy", 429)

    def run():
        # Emplacement rendu à la fin du fil : occupé tant que la génération tourne, même après le délai.
        """Répond dans le fil de l'emplacement et le rend à la fin."""
        try:
            return pipeline.ask(slot, data.question)
        finally:
            try:
                pipeline.release(slot)
            except RuntimeError:
                # Toléré seulement pendant l'arrêt ; sinon double rendu, donc connexion partagée.
                if not state.closing.is_set():
                    raise
                log_event(event="release_after_shutdown", request_id=request_id)

    future = asyncio.get_running_loop().run_in_executor(state.executor, run)
    timed_out = False

    def consume(f: asyncio.Future) -> None:
        # Issue toujours consommée (sinon trace asyncio) ; après le délai, seule la classe est journalisée.
        """Consomme l'issue du fil ; après le délai, journalise l'erreur ou le coût tardif."""
        if f.cancelled() or not timed_out:
            return
        exc = f.exception()
        if exc is not None:
            log_event(event="late_error", request_id=request_id, exception=type(exc).__name__)
        else:
            # Réponse tardive non livrée, mais son coût LLM est consigné.
            a = f.result().answer
            log_event(event="late_result", request_id=request_id, status=a.status, cost_usd=a.cost_usd,
                      model=a.model, provider_name=a.provider_name)

    future.add_done_callback(consume)
    try:
        result = await asyncio.wait_for(asyncio.shield(future), timeout=state.api_config.request_timeout_s)
    except asyncio.TimeoutError:
        timed_out = True
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
    """Crée l'application ; le pipeline est ouvert au démarrage et fermé après les fils actifs."""
    config = api_config or load_api_config()
    key = api_key or load_api_key()

    if pipeline_factory is None:
        from RAG.src.generation.pipeline import QuestionPipeline

        def pipeline_factory():
            """Crée le pipeline réel."""
            return QuestionPipeline(config.max_concurrency)

    @asynccontextmanager
    async def lifespan(app: Litestar):
        # Modèle, canari et index vérifiés à l'ouverture : un échec empêche le démarrage (index vide admis).
        pipeline = await asyncio.get_running_loop().run_in_executor(None, lambda: pipeline_factory().__enter__())
        app.state.pipeline = pipeline
        app.state.closing = threading.Event()
        # Un fil par emplacement : une question n'attend jamais un fil libre.
        app.state.executor = ThreadPoolExecutor(max_workers=config.max_concurrency, thread_name_prefix="rag-api")
        try:
            yield
        finally:
            # Drapeau posé avant la fermeture, pour que les fils tardifs reconnaissent l'arrêt.
            app.state.closing.set()
            # Fils attendus avant de fermer les connexions (psycopg ferme sans verrou), au plus un délai de question.
            waiter = threading.Thread(target=app.state.executor.shutdown,
                                      kwargs={"wait": True, "cancel_futures": True}, daemon=True)
            waiter.start()
            await asyncio.get_running_loop().run_in_executor(None, waiter.join, config.request_timeout_s)
            if waiter.is_alive():
                log_event(event="shutdown_threads_active")
            pipeline.__exit__(None, None, None)

    configure_logging()
    return Litestar(
        route_handlers=[health, ready, ask_question],
        lifespan=[lifespan],
        state=State({"api_key": key, "api_config": config, "pipeline": None, "closing": None, "executor": None}),
        # OpenAPI désactivé sauf configuration contraire.
        **({} if config.openapi else {"openapi_config": None}),
        logging_config=None,
        request_max_body_size=config.max_body_bytes,
        exception_handlers={Exception: _error_response},
    )

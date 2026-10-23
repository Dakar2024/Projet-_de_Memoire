import logging
from datetime import UTC, datetime
from http import HTTPStatus

from asyncpg.exceptions import UniqueViolationError
from litestar import Litestar, Response, Router, get
from litestar.config.cors import CORSConfig
from litestar.logging import LoggingConfig
from litestar.middleware.logging import LoggingMiddlewareConfig
from litestar.middleware.rate_limit import RateLimitConfig
from litestar.openapi import OpenAPIConfig
from litestar.openapi.plugins import ScalarRenderPlugin
from litestar.plugins.pydantic import PydanticPlugin
from litestar.stores.redis import RedisStore

from core.database import DB
from core.exceptions import EXCEPTION_HANDLERS
from core.redis import redis_client
from core.security import check_origin, client_ip
from core.settings import settings
from features.admin.controller import AccessRequestController
from features.assistant.controller import AssistantController
from features.assistant.rag_client import RagClient, build_http_client
from features.auth.controller import AuthController, MeController
from features.auth.status import AccountStatus
from features.usage.controller import UsageController

logger = logging.getLogger(__name__)


@get("/health", tags=["Health"])
async def health_check() -> Response:
    return Response(
        content={"status": "ok", "service": settings.APP_NAME},
        status_code=HTTPStatus.OK,
    )


async def seed_admin() -> None:
    from features.auth.helpers import hash_password
    from features.auth.tables import User

    existing = await User.objects().where(User.email == settings.ADMIN_EMAIL).first()
    if existing:
        return

    admin = User(
        email=settings.ADMIN_EMAIL,
        hashed_password=hash_password(settings.ADMIN_PASSWORD),
        full_name=settings.ADMIN_NAME,
        role="admin",
        status=AccountStatus.ACTIVE.value,
        email_verified_at=datetime.now(UTC),
    )
    try:
        await admin.save().run()
        logger.info("Compte admin créé : %s", settings.ADMIN_EMAIL)
    except UniqueViolationError:
        pass  # another worker inserted it first


async def open_database_pool() -> None:
    await DB.start_connection_pool()


async def close_database_pool() -> None:
    await DB.close_connection_pool()


async def close_redis() -> None:
    await redis_client.aclose()


async def open_rag_client(app: Litestar) -> None:
    if not settings.RAG_API_KEY:
        logger.warning("RAG_API_KEY vide : l'assistant répondra 500 tant que la clé n'est pas dans .env")
    app.state.rag = RagClient(build_http_client())


async def close_rag_client(app: Litestar) -> None:
    await app.state.rag.aclose()


logging_config = LoggingConfig(
    root={"level": "INFO", "handlers": ["queue_listener"]},
    formatters={"standard": {"format": "%(asctime)s %(levelname)s %(name)s — %(message)s"}},
    log_exceptions="debug",
)

# Path and query only, never the body: questions and answers must not reach the logs.
logging_middleware = LoggingMiddlewareConfig(
    request_log_fields=["method", "path", "query"],
    response_log_fields=["status_code"],
)

# Counters in Redis, shared by every uvicorn worker (the default store is per-process memory).
rate_limit = RateLimitConfig(
    rate_limit=("minute", 60),  # 60 requêtes / minute par IP
    exclude=["/health"],
    identifier_for_request=client_ip,
)

# Every business route lives under /api, the prefix the frontend proxies to this backend.
api = Router(
    path="/api",
    route_handlers=[
        AuthController,
        MeController,
        AccessRequestController,
        AssistantController,
        UsageController,
        # Ajouter ici les controllers des nouvelles features
    ],
)

app = Litestar(
    middleware=[logging_middleware.middleware, rate_limit.middleware],
    route_handlers=[health_check, api],
    stores={"rate_limit": RedisStore(redis_client, namespace="rate_limit")},
    plugins=[PydanticPlugin(prefer_alias=True)],
    on_startup=[open_database_pool, seed_admin, open_rag_client],
    on_shutdown=[close_rag_client, close_database_pool, close_redis],
    before_request=check_origin,
    exception_handlers=EXCEPTION_HANDLERS,
    logging_config=logging_config,
    cors_config=CORSConfig(
        allow_origins=settings.ALLOWED_ORIGINS,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Accept"],
        allow_credentials=True,
    ),
    openapi_config=OpenAPIConfig(
        title=f"{settings.APP_NAME} API",
        version="1.0.0",
        path="/docs",
        render_plugins=[ScalarRenderPlugin()],
    ),
)

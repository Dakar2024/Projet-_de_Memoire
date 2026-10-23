import logging
import traceback
from http import HTTPStatus

from litestar import Request, Response
from litestar.exceptions import HTTPException, ValidationException

logger = logging.getLogger(__name__)

# Every error body is {"error": <code>, "message": <text>}: the frontend branches on `error`
# (ApiErrorCode in apps/frontend/src/shared/api/contracts.ts), `message` is for humans.


class AppError(Exception):
    """Root exception for all domain errors."""

    code = "internal"
    status = HTTPStatus.INTERNAL_SERVER_ERROR


class NotFoundError(AppError):
    code = "not_found"
    status = HTTPStatus.NOT_FOUND


class AlreadyExistsError(AppError):
    code = "conflict"
    status = HTTPStatus.CONFLICT


class UnauthorizedError(AppError):
    code = "unauthorized"
    status = HTTPStatus.UNAUTHORIZED


class ForbiddenError(AppError):
    code = "forbidden"
    status = HTTPStatus.FORBIDDEN


class ValidationError(AppError):
    code = "validation_error"
    status = HTTPStatus.UNPROCESSABLE_ENTITY


_HTTP_CODES: dict[int, str] = {
    HTTPStatus.UNAUTHORIZED:          "unauthorized",
    HTTPStatus.FORBIDDEN:             "forbidden",
    HTTPStatus.NOT_FOUND:             "not_found",
    HTTPStatus.TOO_MANY_REQUESTS:     "rate_limited",
    HTTPStatus.SERVICE_UNAVAILABLE:   "unavailable",
}


def _error(code: str, message: str, status: int, headers: dict[str, str] | None = None) -> Response:
    return Response(content={"error": code, "message": message}, status_code=status, headers=headers)


def app_error_handler(_: Request, exc: AppError) -> Response:
    return _error(exc.code, str(exc), exc.status)


def http_exception_handler(_: Request, exc: HTTPException) -> Response:
    code = _HTTP_CODES.get(exc.status_code)
    if code is None:
        code = "internal" if exc.status_code >= 500 else "validation_error"
    # Keeps Retry-After and the RateLimit-* headers set by the rate limit middleware.
    return _error(code, exc.detail, exc.status_code, headers=exc.headers)


def litestar_validation_handler(_: Request, exc: ValidationException) -> Response:
    detail = exc.extra
    if isinstance(detail, list) and detail:
        first = detail[0]
        message = first.get("message", str(first)) if isinstance(first, dict) else str(first)
    else:
        message = exc.detail or "Données invalides"
    return _error("validation_error", message, HTTPStatus.UNPROCESSABLE_ENTITY)


def internal_error_handler(req: Request, exc: Exception) -> Response:
    logger.error("Unhandled exception on %s %s\n%s", req.method, req.url.path, traceback.format_exc())
    return _error("internal", "Erreur interne du serveur", HTTPStatus.INTERNAL_SERVER_ERROR)


EXCEPTION_HANDLERS: dict = {
    AppError:            app_error_handler,
    ValidationException: litestar_validation_handler,
    HTTPException:       http_exception_handler,
    500:                 internal_error_handler,
}

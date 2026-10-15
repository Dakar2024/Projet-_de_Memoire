"""Gardes de l'API : clé comparée en temps constant et corps JSON obligatoire."""
from __future__ import annotations

import hmac

from litestar.connection import ASGIConnection
from litestar.exceptions import HTTPException, NotAuthorizedException
from litestar.handlers.base import BaseRouteHandler


def require_api_key(connection: ASGIConnection, _: BaseRouteHandler) -> None:
    """Refuse la requête si la clé `X-API-Key` est absente ou fausse."""
    expected: str = connection.app.state.api_key
    given = connection.headers.get("x-api-key") or ""
    if not hmac.compare_digest(given.encode("utf-8"), expected.encode("utf-8")):
        raise NotAuthorizedException()


def require_json(connection: ASGIConnection, _: BaseRouteHandler) -> None:
    """Refuse par 415, avant lecture du corps, tout type autre que `application/json`."""
    media_type = (connection.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
    if media_type != "application/json":
        raise HTTPException(status_code=415)

"""Clé d'API : comparée en temps constant, jamais journalisée."""

from __future__ import annotations

import hmac

from litestar.connection import ASGIConnection
from litestar.exceptions import HTTPException, NotAuthorizedException
from litestar.handlers.base import BaseRouteHandler


def require_api_key(connection: ASGIConnection, _: BaseRouteHandler) -> None:
    expected: str = connection.app.state.api_key
    given = connection.headers.get("x-api-key") or ""
    if not hmac.compare_digest(given.encode("utf-8"), expected.encode("utf-8")):
        raise NotAuthorizedException()


def require_json(connection: ASGIConnection, _: BaseRouteHandler) -> None:
    """Corps déclaré JSON (`application/json`, paramètres comme `charset` admis), vérifié
    avant toute lecture du corps : un autre type est refusé par 415."""
    media_type = (connection.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
    if media_type != "application/json":
        raise HTTPException(status_code=415)

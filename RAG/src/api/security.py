"""Clé d'API : comparée en temps constant, jamais journalisée."""

from __future__ import annotations

import hmac

from litestar.connection import ASGIConnection
from litestar.exceptions import NotAuthorizedException
from litestar.handlers.base import BaseRouteHandler


def require_api_key(connection: ASGIConnection, _: BaseRouteHandler) -> None:
    expected: str = connection.app.state.api_key
    given = connection.headers.get("x-api-key") or ""
    if not hmac.compare_digest(given.encode("utf-8"), expected.encode("utf-8")):
        raise NotAuthorizedException()

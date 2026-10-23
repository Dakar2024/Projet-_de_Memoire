"""Session guards. The user is reloaded from the database on every request (MODELISATION § 4.1):
a suspension, a role change or a password change applies at once, not when the token expires.
"""

from collections.abc import Awaitable, Callable

from litestar import Request
from litestar.connection import ASGIConnection
from litestar.exceptions import NotAuthorizedException, PermissionDeniedException
from litestar.handlers import BaseRouteHandler

from core.exceptions import UnauthorizedError
from features.auth.helpers import decode_token
from features.auth.status import LOGIN_STATUSES, AccountStatus
from features.auth.tables import User

COOKIE_NAME = "access_token"

Guard = Callable[[ASGIConnection, BaseRouteHandler], Awaitable[None]]


async def _session_user(connection: ASGIConnection) -> User:
    cached = connection.state.get("user")
    if cached is not None:
        return cached
    token = connection.cookies.get(COOKIE_NAME)
    if not token:
        raise NotAuthorizedException("Non authentifié")
    try:
        claims = decode_token(token)
    except UnauthorizedError:
        raise NotAuthorizedException("Session invalide ou expirée") from None
    user = await User.objects().where(User.id == claims.user_id).first()
    # A bumped token_version (password changed, account suspended) revokes older tokens.
    if user is None or user.token_version != claims.token_version or AccountStatus(user.status) not in LOGIN_STATUSES:
        raise NotAuthorizedException("Session invalide ou expirée")
    connection.state.user = user
    return user


def _require(*statuses: AccountStatus, admin: bool = False) -> Guard:
    async def guard(connection: ASGIConnection, _: BaseRouteHandler) -> None:
        user = await _session_user(connection)
        if AccountStatus(user.status) not in statuses:
            raise PermissionDeniedException("Accès refusé pour l'état actuel du compte")
        if admin and user.role != "admin":
            raise PermissionDeniedException("Réservé aux administrateurs")

    return guard


# Any account that may hold a session: /auth/me, so the frontend can route an onboarding account.
session_guard = _require(AccountStatus.ACTIVE, AccountStatus.ONBOARDING)
onboarding_guard = _require(AccountStatus.ONBOARDING)
active_user_guard = _require(AccountStatus.ACTIVE)
# Role read from the database, never from the token.
admin_guard = _require(AccountStatus.ACTIVE, admin=True)


async def provide_current_user(request: Request) -> User:
    """Dependency for handlers behind one of the guards above."""
    return await _session_user(request)

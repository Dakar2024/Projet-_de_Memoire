from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import cache
from uuid import UUID

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from core.exceptions import UnauthorizedError
from core.settings import settings
from features.auth.schemas import UserResponse
from features.auth.status import AccountStatus
from features.auth.tables import User

_ph = PasswordHasher()

_ALGORITHM = "HS256"


def hash_password(plain: str) -> str:
    return _ph.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _ph.verify(hashed, plain)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_needs_rehash(hashed: str) -> bool:
    return _ph.check_needs_rehash(hashed)


@cache
def _dummy_hash() -> str:
    return _ph.hash("placeholder-password-for-timing")


def burn_password_check(plain: str) -> None:
    """Spend the time of a real check, so an unknown e-mail answers as slowly as a wrong password."""
    verify_password(plain, _dummy_hash())


# ── Session token ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SessionClaims:
    user_id:       UUID
    token_version: int
    remember:      bool


def session_lifetime(remember: bool) -> timedelta:
    if remember:
        return timedelta(days=settings.SESSION_REMEMBER_DAYS)
    return timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)


def create_access_token(user_id: UUID, token_version: int, *, remember: bool = False) -> str:
    # Neither role nor status in the token: both are read from the database on every request,
    # so a suspension or a role change applies at once.
    payload = {
        "sub": str(user_id),
        "tv": token_version,
        "rm": remember,  # to reissue a token of the same lifetime after a password change
        "exp": datetime.now(UTC) + session_lifetime(remember),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=_ALGORITHM)


def decode_token(token: str) -> SessionClaims:
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[_ALGORITHM], options={"require": ["sub", "tv", "exp"]}
        )
        return SessionClaims(
            user_id=UUID(payload["sub"]),
            token_version=int(payload["tv"]),
            remember=bool(payload.get("rm", False)),
        )
    except (jwt.InvalidTokenError, ValueError, TypeError):
        raise UnauthorizedError("Session invalide ou expirée") from None


def user_to_response(user: User) -> UserResponse:
    return UserResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        status=AccountStatus(user.status),
        profession=user.profession,
        organization=user.organization,
    )

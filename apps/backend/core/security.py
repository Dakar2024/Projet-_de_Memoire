"""Cross-cutting request protections: origin check (CSRF), client IP, per-subject rate limits."""

import hashlib
from dataclasses import dataclass
from typing import Protocol

from litestar import Request
from litestar.connection import ASGIConnection
from litestar.exceptions import PermissionDeniedException, TooManyRequestsException
from litestar.middleware.rate_limit import get_remote_address
from redis.asyncio import Redis

from core.settings import settings

_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def check_origin(request: Request) -> None:
    """CSRF protection for the cookie session (OWASP: verify the origin with standard headers).

    Browsers always send `Origin` on cross-site POST/PUT/PATCH/DELETE; a value outside
    ALLOWED_ORIGINS is refused. The frontend server calls the API without `Origin`, which is
    accepted: that call is not made by a browser, so it carries no ambient credentials of its own.
    """
    if request.method not in _UNSAFE_METHODS:
        return
    origin = request.headers.get("origin")
    if origin is not None and origin not in settings.ALLOWED_ORIGINS:
        raise PermissionDeniedException("Origine non autorisée")
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise PermissionDeniedException("Origine non autorisée")


def client_ip(connection: ASGIConnection) -> str:
    """Address of the end user, see TRUST_FORWARDED_FOR in core/settings.py."""
    if settings.TRUST_FORWARDED_FOR:
        forwarded = connection.headers.get("x-forwarded-for", "")
        # Last entry: the one written by our own proxy; earlier ones come from the client.
        last = forwarded.rsplit(",", 1)[-1].strip()
        if last:
            return last
    return get_remote_address(connection)


# ── Rate limits on sensitive routes (login, register, forgot-password) ───────


@dataclass(frozen=True)
class Limit:
    name:     str
    max_hits: int
    window_s: int


class Counter(Protocol):
    async def hit(self, key: str, window_s: int) -> tuple[int, int]:
        """Count one hit in a fixed window; return (hits so far, seconds left in the window)."""
        ...


class RedisCounter:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def hit(self, key: str, window_s: int) -> tuple[int, int]:
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.incr(key)
            pipe.expire(key, window_s, nx=True)
            pipe.ttl(key)
            hits, _, ttl = await pipe.execute()
        return int(hits), max(int(ttl), 1)


class RateLimiter:
    def __init__(self, counter: Counter) -> None:
        self._counter = counter

    async def enforce(self, limit: Limit, subject: str) -> None:
        # Subjects (e-mail, IP) are hashed: no personal data in Redis key names.
        digest = hashlib.sha256(subject.strip().lower().encode()).hexdigest()[:32]
        hits, retry_after = await self._counter.hit(f"auth-limit:{limit.name}:{digest}", limit.window_s)
        if hits > limit.max_hits:
            raise TooManyRequestsException(
                "Trop de tentatives. Réessayez plus tard.", headers={"Retry-After": str(retry_after)}
            )

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest

from core.exceptions import UnauthorizedError
from core.settings import settings
from features.auth.helpers import create_access_token, decode_token, session_lifetime


def test_token_round_trip():
    user_id = uuid4()
    claims = decode_token(create_access_token(user_id, 3, remember=True))
    assert claims.user_id == user_id
    assert claims.token_version == 3
    assert claims.remember is True


def test_token_carries_neither_role_nor_status():
    payload = jwt.decode(create_access_token(uuid4(), 0), settings.SECRET_KEY, algorithms=["HS256"])
    assert set(payload) == {"sub", "tv", "rm", "exp"}


def test_remember_me_lasts_longer():
    assert session_lifetime(True) == timedelta(days=settings.SESSION_REMEMBER_DAYS)
    assert session_lifetime(False) == timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)


def _sign(payload: dict, key: str = settings.SECRET_KEY) -> str:
    return jwt.encode(payload, key, algorithm="HS256")


@pytest.mark.parametrize(
    "token",
    [
        _sign({"sub": str(uuid4()), "tv": 0, "exp": datetime.now(UTC) - timedelta(seconds=1)}),
        _sign({"sub": str(uuid4()), "tv": 0, "exp": datetime.now(UTC) + timedelta(hours=1)}, "x" * 40),
        _sign({"sub": str(uuid4()), "exp": datetime.now(UTC) + timedelta(hours=1)}),  # no tv
        _sign({"sub": "not-a-uuid", "tv": 0, "exp": datetime.now(UTC) + timedelta(hours=1)}),
        jwt.encode({"sub": str(uuid4()), "tv": 0}, None, algorithm="none"),
        "garbage",
    ],
    ids=["expired", "wrong-key", "no-version", "bad-subject", "unsigned", "garbage"],
)
def test_invalid_tokens_are_rejected(token: str):
    with pytest.raises(UnauthorizedError):
        decode_token(token)

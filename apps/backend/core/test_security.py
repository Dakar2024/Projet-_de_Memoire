import asyncio

import pytest
from litestar import Litestar, Request, get, post
from litestar.exceptions import TooManyRequestsException
from litestar.testing import TestClient

from core.exceptions import EXCEPTION_HANDLERS
from core.security import Limit, RateLimiter, check_origin, client_ip
from core.settings import settings

ALLOWED = settings.ALLOWED_ORIGINS[0]


@get("/read")
async def read() -> str:
    return "ok"


@post("/write")
async def write() -> str:
    return "ok"


@get("/ip")
async def ip_echo(request: Request) -> str:
    return client_ip(request)


@pytest.fixture
def client():
    app = Litestar([read, write, ip_echo], before_request=check_origin, exception_handlers=EXCEPTION_HANDLERS)
    with TestClient(app=app) as c:
        yield c


@pytest.mark.parametrize(
    ("headers", "status"),
    [
        ({}, 201),  # server-to-server call from the frontend
        ({"origin": ALLOWED}, 201),
        ({"origin": "https://evil.example"}, 403),
        ({"origin": "null"}, 403),
        ({"sec-fetch-site": "cross-site"}, 403),
        ({"origin": ALLOWED, "sec-fetch-site": "same-origin"}, 201),
    ],
)
def test_unsafe_methods_check_the_origin(client: TestClient, headers: dict, status: int):
    response = client.post("/write", headers=headers)
    assert response.status_code == status
    if status == 403:
        assert response.json()["error"] == "forbidden"


def test_safe_methods_are_not_checked(client: TestClient):
    assert client.get("/read", headers={"origin": "https://evil.example"}).status_code == 200


def test_forwarded_for_is_ignored_by_default(client: TestClient):
    assert client.get("/ip", headers={"x-forwarded-for": "203.0.113.9"}).text != "203.0.113.9"


def test_forwarded_for_last_entry_when_trusted(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "TRUST_FORWARDED_FOR", True)
    response = client.get("/ip", headers={"x-forwarded-for": "198.51.100.1, 203.0.113.9"})
    assert response.text == "203.0.113.9"


class MemoryCounter:
    def __init__(self) -> None:
        self.hits: dict[str, int] = {}

    async def hit(self, key: str, window_s: int) -> tuple[int, int]:
        self.hits[key] = self.hits.get(key, 0) + 1
        return self.hits[key], window_s


def test_limiter_blocks_after_max_hits():
    counter = MemoryCounter()
    limiter = RateLimiter(counter)
    limit = Limit("login-email", max_hits=3, window_s=900)

    async def scenario() -> None:
        for _ in range(3):
            await limiter.enforce(limit, "Jane@APHP.fr")
        with pytest.raises(TooManyRequestsException) as info:
            await limiter.enforce(limit, "jane@aphp.fr")  # same subject, other spelling
        assert info.value.headers == {"Retry-After": "900"}
        await limiter.enforce(limit, "other@aphp.fr")  # other subject, own counter

    asyncio.run(scenario())


def test_limiter_keys_hold_no_personal_data():
    counter = MemoryCounter()
    asyncio.run(RateLimiter(counter).enforce(Limit("mail-email", 3, 60), "jane@aphp.fr"))
    (key,) = counter.hits
    assert "jane" not in key and "aphp" not in key

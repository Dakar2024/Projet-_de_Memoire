from litestar import Litestar, get, post
from litestar.params import JSONBody
from litestar.plugins.pydantic import PydanticPlugin
from litestar.stores.redis import RedisStore
from litestar.testing import TestClient

from core.schemas import CamelModel


class Profile(CamelModel):
    full_name: str


def test_business_routes_live_under_api():
    from app import app

    paths = {route.path for route in app.routes}
    assert "/health" in paths
    assert "/api/auth/login" in paths
    assert not any(p.startswith("/auth") or p.startswith("/users") for p in paths)


def test_rate_limit_counters_are_in_redis():
    from app import app

    assert isinstance(app.stores.get("rate_limit"), RedisStore)


def test_camel_model_round_trip():
    @get("/profile")
    async def read() -> Profile:
        return Profile(full_name="Ada Lovelace")

    @post("/profile")
    async def write(data: JSONBody[Profile]) -> dict:
        return {"name": data.full_name}

    app = Litestar([read, write], plugins=[PydanticPlugin(prefer_alias=True)])
    with TestClient(app=app) as client:
        assert client.get("/profile").json() == {"fullName": "Ada Lovelace"}
        assert client.post("/profile", json={"fullName": "Grace"}).json() == {"name": "Grace"}

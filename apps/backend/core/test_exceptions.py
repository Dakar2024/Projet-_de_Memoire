import pytest
from litestar import Litestar, get, post
from litestar.exceptions import NotAuthorizedException, TooManyRequestsException
from litestar.params import FromPath, JSONBody
from litestar.testing import TestClient
from pydantic import BaseModel

from core.exceptions import EXCEPTION_HANDLERS, ForbiddenError, NotFoundError
from features.auth.exceptions import AccountBlockedError, InvalidCredentialsError
from features.auth.status import AccountStatus


class Payload(BaseModel):
    name: str


@get("/domain/{kind:str}")
async def raise_domain(kind: FromPath[str]) -> None:
    errors = {
        "not_found": NotFoundError("absent"),
        "forbidden": ForbiddenError("interdit"),
        "credentials": InvalidCredentialsError(),
        "suspended": AccountBlockedError(AccountStatus.SUSPENDED),
    }
    raise errors[kind]


@get("/unauthorized")
async def raise_unauthorized() -> None:
    raise NotAuthorizedException("Non authentifié")


@get("/throttled")
async def raise_throttled() -> None:
    raise TooManyRequestsException("Trop de requêtes", headers={"Retry-After": "30"})


@get("/crash")
async def crash() -> None:
    raise RuntimeError("boom")


@post("/validate")
async def validate(data: JSONBody[Payload]) -> None:
    return None


@pytest.fixture
def client():
    app = Litestar(
        [raise_domain, raise_unauthorized, raise_throttled, crash, validate],
        exception_handlers=EXCEPTION_HANDLERS,
    )
    with TestClient(app=app) as c:
        yield c


@pytest.mark.parametrize(
    ("kind", "status", "code"),
    [
        ("not_found", 404, "not_found"),
        ("forbidden", 403, "forbidden"),
        ("credentials", 401, "invalid_credentials"),
        ("suspended", 403, "account_suspended"),
    ],
)
def test_domain_errors_carry_their_code(client: TestClient, kind: str, status: int, code: str):
    response = client.get(f"/domain/{kind}")
    assert response.status_code == status
    assert response.json()["error"] == code
    assert response.json()["message"]


def test_litestar_http_errors_are_mapped(client: TestClient):
    response = client.get("/unauthorized")
    assert response.status_code == 401
    assert response.json() == {"error": "unauthorized", "message": "Non authentifié"}


def test_rate_limit_keeps_retry_after(client: TestClient):
    response = client.get("/throttled")
    assert response.status_code == 429
    assert response.json()["error"] == "rate_limited"
    assert response.headers["retry-after"] == "30"


def test_unknown_route_is_not_found(client: TestClient):
    assert client.get("/nowhere").json()["error"] == "not_found"


def test_validation_error(client: TestClient):
    response = client.post("/validate", json={})
    assert response.status_code == 422
    assert response.json()["error"] == "validation_error"


def test_unhandled_exception_hides_details(client: TestClient):
    response = client.get("/crash")
    assert response.status_code == 500
    assert response.json() == {"error": "internal", "message": "Erreur interne du serveur"}

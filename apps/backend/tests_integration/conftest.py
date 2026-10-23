"""Fixtures for the integration tests: the real app against the PostgreSQL and Redis of
compose.test.yml. Each test starts from empty tables; e-mails are recorded, not sent.
"""

import asyncio
import os
import re
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import asyncpg
import httpx
import pytest
from litestar.testing import TestClient
from redis import Redis

from core.settings import settings
from features.assistant.rag_client import RagClient
from features.auth import controller as auth_controller
from features.auth.emails import Email

pytestmark = pytest.mark.integration

ADMIN_EMAIL = settings.ADMIN_EMAIL
ADMIN_PASSWORD = settings.ADMIN_PASSWORD
PASSWORD = "correct-horse-battery"

_TABLES = (
    "usage_events, daily_usage, feedback, message_sources, messages, conversations, "
    "audit_log, app_settings, email_verification_tokens, password_reset_tokens, users"
)


def sql(query: str, *args: Any) -> list[asyncpg.Record]:
    """Run one statement on a connection of its own (the app's pool lives in the client's loop)."""

    async def run() -> list[asyncpg.Record]:
        conn = await asyncpg.connect(
            host=settings.POSTGRES_HOST,
            port=settings.POSTGRES_PORT,
            user=settings.POSTGRES_USER,
            password=settings.POSTGRES_PASSWORD,
            database=settings.POSTGRES_DB,
        )
        try:
            return await conn.fetch(query, *args)
        finally:
            await conn.close()

    return asyncio.run(run())


@dataclass
class RecordingMailer:
    sent: list[tuple[str, Email]] = field(default_factory=list)

    async def send(self, to: str, email: Email) -> None:
        self.sent.append((to, email))

    def last_to(self, to: str) -> Email:
        return [email for recipient, email in self.sent if recipient == to][-1]

    def token_for(self, to: str) -> str:
        match = re.search(r"token=([\w-]+)", self.last_to(to).text)
        assert match, "no token in the last e-mail"
        return match.group(1)


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> None:
    try:
        sql("SELECT 1")
    except OSError:
        pytest.skip("PostgreSQL de compose.test.yml injoignable (make test-integration)")
    env = {**os.environ, "PICCOLO_CONF": "core.database"}
    subprocess.run(["piccolo", "migrations", "forwards", "all"], check=True, env=env, capture_output=True)


@pytest.fixture
def mailer(monkeypatch: pytest.MonkeyPatch) -> RecordingMailer:
    recording = RecordingMailer()
    monkeypatch.setattr(auth_controller, "mailer_factory", lambda: recording)
    return recording


class FakeRag:
    """Stands in for the RAG gateway: records the requests, answers what the test queued."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.replies: list[httpx.Response | Exception] = []

    def reply(self, response: httpx.Response | Exception) -> None:
        self.replies.append(response)

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        reply = self.replies.pop(0) if self.replies else httpx.Response(200, json=rag_answer())
        if isinstance(reply, Exception):
            raise reply
        return reply


def rag_answer(status: str = "answered", sources: int = 2, cost: float = 0.0012) -> dict:
    """A body shaped like PipelineResult.as_dict(include_trace=True) of the RAG."""
    return {
        "status": status,
        "answer": "Le variant est classé pathogène [1][2].",
        "history": ["Classé VUS jusqu'en 2019."],
        "sources": [
            {
                "doc_id": f"clinvar:{1000 + i}",
                "gene": "BRCA1",
                "variant": f"NM_007294.4(BRCA1):c.{68 + i}_{69 + i}del",
                "protein": "p.Glu23fs",
                "significance": "Pathogenic",
                "significance_fr": "Pathogène",
                "review_status": "reviewed by expert panel",
                "clinvar_variation_id": str(1000 + i),
                "clinvar_url": f"https://www.ncbi.nlm.nih.gov/clinvar/variation/{1000 + i}/",
                "archive": "2026-10",
                "previous_significance": None,
                "previous_significance_fr": None,
                "previous_until": None,
            }
            for i in range(sources)
        ],
        "disclaimer": "Information de recherche, pas un avis médical.",
        "scope_reason": None,
        "timings_ms": {"analysis": 1.0, "search": 20.0, "generation": 900.0, "total": 925.0},
        "trace": {"generation": {"provider_name": "groq", "model": "llama", "cost_usd": cost}},
        "request_id": "rag-req-1",
    }


@pytest.fixture
def rag() -> FakeRag:
    return FakeRag()


@pytest.fixture
def client(mailer: RecordingMailer, rag: FakeRag) -> Iterator[TestClient]:
    sql(f"TRUNCATE {_TABLES} CASCADE")
    Redis.from_url(settings.REDIS_URL).flushdb()
    from app import app

    with TestClient(app=app) as c:  # startup seeds the admin and opens the real RAG client
        real = app.state.rag
        app.state.rag = RagClient(
            httpx.AsyncClient(transport=httpx.MockTransport(rag.handler), base_url="http://rag-gateway")
        )
        yield c
        app.state.rag = real


def set_registration(mode: str, domains: list[str] | None = None) -> None:
    sql(
        "INSERT INTO app_settings (id, registration_mode, allowed_email_domains) VALUES (1, $1, $2) "
        "ON CONFLICT (id) DO UPDATE SET registration_mode = $1, allowed_email_domains = $2",
        mode,
        domains or [],
    )


def login(client: TestClient, email: str, password: str = PASSWORD, remember: bool = False):
    client.cookies.clear()
    return client.post("/api/auth/login", json={"email": email, "password": password, "remember": remember})


def register(client: TestClient, email: str, password: str = PASSWORD):
    return client.post(
        "/api/auth/register",
        json={"email": email, "password": password, "termsAccepted": True, "noPatientDataPledge": True},
    )


def onboard(client: TestClient):
    return client.put(
        "/api/me/onboarding",
        json={"fullName": "Awa Diop", "profession": "medical_biologist", "organization": "CHU Fann"},
    )


def verified_onboarding_user(client: TestClient, mailer: RecordingMailer, email: str) -> None:
    """Register and verify: the account is left in `onboarding`, signed in."""
    assert register(client, email).status_code == 202
    assert client.post("/api/auth/verify-email", json={"token": mailer.token_for(email)}).status_code == 200
    assert login(client, email).status_code == 200


def active_user(client: TestClient, mailer: RecordingMailer, email: str) -> None:
    """Full path to `active` through an admin approval; the user is left signed in."""
    verified_onboarding_user(client, mailer, email)
    assert onboard(client).status_code == 200
    user_id = sql("SELECT id FROM users WHERE email = $1", email)[0]["id"]
    assert login(client, ADMIN_EMAIL, ADMIN_PASSWORD).status_code == 200
    assert client.post(f"/api/admin/requests/{user_id}/approve").status_code == 200
    assert login(client, email).status_code == 200

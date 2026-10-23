"""MODELISATION_BACKEND.md § 4.2 and § 4.6 against PostgreSQL, the RAG replaced by FakeRag."""

import asyncio
import json
from uuid import uuid4

import httpx
import pytest
from litestar.testing import TestClient

from features.usage.service import QuotaExceededError, reserve, today
from tests_integration.conftest import (
    ADMIN_EMAIL,
    ADMIN_PASSWORD,
    FakeRag,
    RecordingMailer,
    active_user,
    login,
    rag_answer,
    sql,
)

pytestmark = pytest.mark.integration

EMAIL = "awa.diop@chu-fann.sn"
OTHER = "moussa.ba@chu-fann.sn"
QUESTION = "Quelle est la signification de BRCA1 c.68_69del ?"


def ask(client: TestClient, question: str = QUESTION, **extra):
    return client.post("/api/assistant/questions", json={"question": question, **extra})


def test_answer_is_relayed_and_stored(client: TestClient, mailer: RecordingMailer, rag: FakeRag):
    active_user(client, mailer, EMAIL)
    response = ask(client)
    assert response.status_code == 200
    body = response.json()
    message = body["message"]
    assert body["quotaRemaining"] == 19
    assert "trace" not in body or body["trace"] is None  # never the cost to a user
    assert message["role"] == "assistant"
    assert message["status"] == "answered"
    assert message["history"] == ["Classé VUS jusqu'en 2019."]
    assert [s["rank"] for s in message["sources"]] == [1, 2]
    assert message["sources"][0]["stars"] == 3
    assert message["sources"][0]["significanceFr"] == "Pathogène"

    # One question, alone, with the trace for the costs.
    (request,) = rag.requests
    assert json.loads(request.content) == {"question": QUESTION, "trace": True}

    event = sql("SELECT status, http_status, cost_usd, model, message FROM usage_events")[0]
    assert (event["status"], event["http_status"], float(event["cost_usd"]), event["model"]) == (
        "answered", 200, 0.0012, "llama",
    )
    assert event["message"] is not None
    assert sql("SELECT count(*) FROM message_sources")[0]["count"] == 2


def test_history_survives_sign_out(client: TestClient, mailer: RecordingMailer, rag: FakeRag):
    """The user's request: sign out, sign back in, the sidebar lists the conversations."""
    active_user(client, mailer, EMAIL)
    first = ask(client, "Première question sur BRCA2").json()["conversationId"]
    ask(client, "Suite de la même conversation", conversationId=first)
    second = ask(client, "Une autre conversation sur HBB").json()["conversationId"]

    client.delete("/api/auth/logout")
    assert client.get("/api/assistant/conversations").status_code == 401
    login(client, EMAIL)

    items = client.get("/api/assistant/conversations").json()["items"]
    assert [(i["id"], i["title"]) for i in items] == [
        (second, "Une autre conversation sur HBB"),
        (first, "Première question sur BRCA2"),
    ]
    thread = client.get(f"/api/assistant/conversations/{first}").json()
    answer = rag_answer()["answer"]
    assert [(m["role"], m["content"]) for m in thread["messages"]] == [
        ("user", "Première question sur BRCA2"),
        ("assistant", answer),
        ("user", "Suite de la même conversation"),
        ("assistant", answer),
    ]
    assert len(thread["messages"][1]["sources"]) == 2


def test_conversations_are_private(client: TestClient, mailer: RecordingMailer, rag: FakeRag):
    active_user(client, mailer, EMAIL)
    conversation_id = ask(client).json()["conversationId"]
    message_id = sql("SELECT id FROM messages WHERE role = 'assistant'")[0]["id"]
    active_user(client, mailer, OTHER)

    assert client.get("/api/assistant/conversations").json()["items"] == []
    url = f"/api/assistant/conversations/{conversation_id}"
    assert client.get(url).status_code == 404
    assert client.patch(url, json={"title": "volé"}).status_code == 404
    assert client.delete(url).status_code == 404
    assert client.put(f"/api/assistant/messages/{message_id}/feedback", json={"rating": 1}).status_code == 404
    assert ask(client, conversationId=conversation_id).status_code == 404
    assert len(rag.requests) == 1  # refused before any call


@pytest.mark.parametrize(
    ("reply", "code", "retry_after"),
    [
        (httpx.Response(429, text="<html>429 Too Many Requests</html>"), "assistant_busy", "2"),
        (httpx.Response(503, json={"error": "index_empty"}), "index_building", None),
        (
            httpx.Response(503, json={"error": "unavailable"}, headers={"Retry-After": "9"}),
            "assistant_unavailable",
            "9",
        ),
        (httpx.Response(502, text="<html>Bad Gateway</html>"), "assistant_unavailable", None),
        (httpx.ConnectError("refused"), "assistant_unavailable", None),
        (httpx.ReadTimeout("slow"), "assistant_unavailable", None),
    ],
    ids=["gateway-limit", "index-empty", "unavailable", "bad-gateway", "unreachable", "timeout"],
)
def test_failures_cost_nothing(client, mailer, rag: FakeRag, reply, code, retry_after):
    active_user(client, mailer, EMAIL)
    rag.reply(reply)
    response = ask(client)
    assert response.status_code == 503
    assert response.json()["error"] == code
    assert response.headers.get("retry-after") == retry_after
    # Nothing in the thread, quota given back, the call still in the cost register.
    assert sql("SELECT count(*) FROM conversations")[0]["count"] == 0
    assert client.get("/api/me/usage").json()["used"] == 0
    assert sql("SELECT error_code FROM usage_events")[0]["error_code"] == code


def test_daily_quota(client: TestClient, mailer: RecordingMailer, rag: FakeRag):
    active_user(client, mailer, EMAIL)
    sql("UPDATE users SET daily_quota_override = 2 WHERE email = $1", EMAIL)
    assert ask(client).json()["quotaRemaining"] == 1
    assert ask(client).json()["quotaRemaining"] == 0
    response = ask(client)
    assert response.status_code == 429
    assert response.json()["error"] == "quota_exceeded"
    assert int(response.headers["retry-after"]) > 0
    assert len(rag.requests) == 2
    usage = client.get("/api/me/usage").json()
    assert (usage["used"], usage["limit"], usage["remaining"]) == (2, 2, 0)


def test_concurrent_reservations_respect_the_quota(client: TestClient, mailer: RecordingMailer):
    """MODELISATION § 7.2: 20 concurrent reservations on a quota of 5, exactly 5 succeed."""
    active_user(client, mailer, EMAIL)
    user_id = sql("SELECT id FROM users WHERE email = $1", EMAIL)[0]["id"]

    async def attempt() -> bool:
        try:
            await reserve(user_id, today(), 5)
            return True
        except QuotaExceededError:
            return False

    async def burst() -> list[bool]:
        return await asyncio.gather(*(attempt() for _ in range(20)))

    results = client.blocking_portal.call(burst)  # in the app's loop, where Piccolo's pool lives
    assert results.count(True) == 5
    assert sql("SELECT used FROM daily_usage")[0]["used"] == 5


def test_monthly_budget(client: TestClient, mailer: RecordingMailer, rag: FakeRag):
    active_user(client, mailer, EMAIL)
    sql("INSERT INTO usage_events (id, http_status, cost_usd) VALUES ($1, 200, 50)", uuid4())
    response = ask(client)
    assert response.status_code == 503
    assert response.json()["error"] == "budget_exhausted"
    assert rag.requests == []


def test_panel_filter_is_refused(client: TestClient, mailer: RecordingMailer, rag: FakeRag):
    active_user(client, mailer, EMAIL)
    response = ask(client, panel="sickle")
    assert response.status_code == 422
    assert response.json()["error"] == "panel_filter_unavailable"
    assert rag.requests == []


@pytest.mark.parametrize("question", ["", "   ", "x" * 1001])
def test_question_bounds(client: TestClient, mailer: RecordingMailer, rag: FakeRag, question: str):
    active_user(client, mailer, EMAIL)
    assert ask(client, question).status_code == 422
    assert rag.requests == []


def test_unverifiable_answers_are_stored(client: TestClient, mailer: RecordingMailer, rag: FakeRag):
    active_user(client, mailer, EMAIL)
    rag.reply(httpx.Response(200, json=rag_answer(status="unverifiable")))
    response = ask(client)
    assert response.json()["message"]["status"] == "unverifiable"


def test_trace_for_admins_when_enabled(client: TestClient, mailer: RecordingMailer, rag: FakeRag):
    login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    assert ask(client).json().get("trace") is None
    sql(
        "INSERT INTO app_settings (id, admin_trace_visible) VALUES (1, true) "
        "ON CONFLICT (id) DO UPDATE SET admin_trace_visible = true"
    )
    assert ask(client).json()["trace"]["generation"]["cost_usd"] == 0.0012


def test_rename_pin_and_feedback(client: TestClient, mailer: RecordingMailer, rag: FakeRag):
    active_user(client, mailer, EMAIL)
    body = ask(client).json()
    url = f"/api/assistant/conversations/{body['conversationId']}"
    assert client.patch(url, json={"title": "BRCA1 délétion", "pinned": True}).json()["pinned"] is True
    assert client.get(url).json()["title"] == "BRCA1 délétion"

    feedback = f"/api/assistant/messages/{body['message']['id']}/feedback"
    assert client.put(feedback, json={"rating": -1, "comment": "Source manquante"}).status_code == 200
    assert client.put(feedback, json={"rating": 1}).json() == {"rating": 1, "comment": None}
    assert [(r["rating"], r["comment"]) for r in sql("SELECT rating, comment FROM feedback")] == [(1, None)]
    question_id = sql("SELECT id FROM messages WHERE role = 'user'")[0]["id"]
    assert client.put(f"/api/assistant/messages/{question_id}/feedback", json={"rating": 1}).status_code == 404


def test_pagination_and_search(client: TestClient, mailer: RecordingMailer, rag: FakeRag):
    active_user(client, mailer, EMAIL)
    sql("UPDATE users SET daily_quota_override = 100 WHERE email = $1", EMAIL)
    for i in range(33):
        ask(client, f"Question {i:02d} sur {'HBB' if i % 3 == 0 else 'BRCA2'}")

    first = client.get("/api/assistant/conversations").json()
    assert len(first["items"]) == 30
    assert first["items"][0]["title"] == "Question 32 sur BRCA2"
    second = client.get("/api/assistant/conversations", params={"cursor": first["nextCursor"]}).json()
    assert [i["title"] for i in second["items"]] == [
        "Question 02 sur BRCA2",
        "Question 01 sur BRCA2",
        "Question 00 sur HBB",
    ]
    assert second["nextCursor"] is None

    found = client.get("/api/assistant/conversations", params={"q": "hbb"}).json()["items"]
    assert len(found) == 11
    assert client.get("/api/assistant/conversations", params={"q": "%"}).json()["items"] == []
    assert client.get("/api/assistant/conversations", params={"cursor": "garbage"}).status_code == 422


def test_deletion_and_purge(client: TestClient, mailer: RecordingMailer, rag: FakeRag):
    from features.assistant.tasks import purge_conversations

    active_user(client, mailer, EMAIL)
    kept = ask(client, "À garder").json()["conversationId"]
    dropped = ask(client, "À supprimer").json()["conversationId"]
    assert client.delete(f"/api/assistant/conversations/{dropped}").status_code == 204
    assert [i["id"] for i in client.get("/api/assistant/conversations").json()["items"]] == [kept]
    assert client.get(f"/api/assistant/conversations/{dropped}").status_code == 404

    # Default retention: none. Only the deleted conversation goes; its cost stays, unlinked.
    assert client.blocking_portal.call(purge_conversations) == 1
    assert sql("SELECT count(*) FROM conversations")[0]["count"] == 1
    assert sql("SELECT count(*) FROM usage_events WHERE message IS NULL")[0]["count"] == 1
    assert sql("SELECT count(*) FROM usage_events")[0]["count"] == 2


def test_retention_set_by_an_admin(client: TestClient, mailer: RecordingMailer, rag: FakeRag):
    from features.assistant.tasks import purge_conversations

    active_user(client, mailer, EMAIL)
    ask(client, "Ancienne")
    ask(client, "Récente")
    sql("UPDATE conversations SET updated_at = now() - interval '40 days' WHERE title = 'Ancienne'")
    assert client.blocking_portal.call(purge_conversations) == 0  # no limit by default
    sql("INSERT INTO app_settings (id, conversation_retention_days) VALUES (1, 30) "
        "ON CONFLICT (id) DO UPDATE SET conversation_retention_days = 30")
    assert client.blocking_portal.call(purge_conversations) == 1
    assert [r["title"] for r in sql("SELECT title FROM conversations")] == ["Récente"]


def test_erasing_the_account_erases_the_history(client: TestClient, mailer: RecordingMailer, rag: FakeRag):
    active_user(client, mailer, EMAIL)
    ask(client)
    assert client.request("DELETE", "/api/me", json={"password": "correct-horse-battery"}).status_code == 200
    assert sql("SELECT count(*) FROM conversations")[0]["count"] == 0
    # The month's spending is kept, without anyone attached to it.
    assert sql("SELECT count(*) FROM usage_events WHERE \"user\" IS NULL")[0]["count"] == 1

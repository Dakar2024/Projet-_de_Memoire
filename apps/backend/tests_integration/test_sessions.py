"""Revocation, password reset, rate limits and account erasure."""

import pytest
from litestar.testing import TestClient

from tests_integration.conftest import (
    ADMIN_EMAIL,
    ADMIN_PASSWORD,
    PASSWORD,
    RecordingMailer,
    active_user,
    login,
    sql,
)

pytestmark = pytest.mark.integration

EMAIL = "awa.diop@chu-fann.sn"
NEW_PASSWORD = "another-long-password"


def test_password_change_signs_out_other_sessions(client: TestClient, mailer: RecordingMailer):
    active_user(client, mailer, EMAIL)
    other_session = client.cookies["access_token"]
    login(client, EMAIL)
    response = client.patch(
        "/api/auth/me/password", json={"currentPassword": PASSWORD, "newPassword": NEW_PASSWORD}
    )
    assert response.status_code == 200
    assert client.get("/api/auth/me").status_code == 200  # this session got a fresh cookie

    client.cookies.set("access_token", other_session)
    assert client.get("/api/auth/me").status_code == 401


def test_wrong_current_password(client: TestClient, mailer: RecordingMailer):
    active_user(client, mailer, EMAIL)
    response = client.patch(
        "/api/auth/me/password", json={"currentPassword": "not-the-password", "newPassword": NEW_PASSWORD}
    )
    assert response.status_code == 422
    assert response.json()["error"] == "invalid_password"


def test_suspension_applies_to_open_sessions(client: TestClient, mailer: RecordingMailer):
    active_user(client, mailer, EMAIL)
    sql("UPDATE users SET status = 'suspended' WHERE email = $1", EMAIL)
    assert client.get("/api/auth/me").status_code == 401


def test_remember_me_sets_a_persistent_cookie(client: TestClient, mailer: RecordingMailer):
    active_user(client, mailer, EMAIL)
    session = login(client, EMAIL, remember=False).headers["set-cookie"]
    persistent = login(client, EMAIL, remember=True).headers["set-cookie"]
    assert "Max-Age" not in session
    assert "Max-Age=2592000" in persistent
    assert "HttpOnly" in persistent and "SameSite=lax" in persistent


def test_password_reset(client: TestClient, mailer: RecordingMailer):
    active_user(client, mailer, EMAIL)
    old_session = client.cookies["access_token"]
    client.cookies.clear()

    unknown = client.post("/api/auth/forgot-password", json={"email": "nobody@chu-fann.sn"})
    known = client.post("/api/auth/forgot-password", json={"email": EMAIL})
    assert (unknown.status_code, unknown.json()) == (known.status_code, known.json())

    token = mailer.token_for(EMAIL)
    assert client.post("/api/auth/reset-password", json={"token": token, "password": NEW_PASSWORD}).status_code == 200
    assert client.post("/api/auth/reset-password", json={"token": token, "password": PASSWORD}).status_code == 422

    assert login(client, EMAIL, PASSWORD).status_code == 401
    assert login(client, EMAIL, NEW_PASSWORD).status_code == 200
    client.cookies.set("access_token", old_session)
    assert client.get("/api/auth/me").status_code == 401


def test_login_is_rate_limited_per_address(client: TestClient, mailer: RecordingMailer):
    for _ in range(10):
        assert login(client, EMAIL, "wrong-password-123").status_code == 401
    response = login(client, EMAIL, "wrong-password-123")
    assert response.status_code == 429
    assert response.json()["error"] == "rate_limited"
    assert int(response.headers["retry-after"]) > 0


def test_account_erasure(client: TestClient, mailer: RecordingMailer):
    active_user(client, mailer, EMAIL)
    assert client.request("DELETE", "/api/me", json={"password": "wrong-password-123"}).status_code == 422
    response = client.request("DELETE", "/api/me", json={"password": PASSWORD})
    assert response.status_code == 200
    assert sql("SELECT count(*) FROM users WHERE email = $1", EMAIL)[0]["count"] == 0
    # The journal keeps the actions, without anyone attached to them.
    assert sql("SELECT count(*) FROM audit_log WHERE action = 'user.erase' AND actor IS NULL")[0]["count"] == 1
    assert login(client, EMAIL).status_code == 401


def test_last_admin_cannot_erase_itself(client: TestClient, mailer: RecordingMailer):
    login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    response = client.request("DELETE", "/api/me", json={"password": ADMIN_PASSWORD})
    assert response.status_code == 409
    assert response.json()["error"] == "last_admin"


def test_cross_site_writes_are_refused(client: TestClient, mailer: RecordingMailer):
    response = client.post(
        "/api/auth/login",
        json={"email": EMAIL, "password": PASSWORD, "remember": False},
        headers={"origin": "https://evil.example"},
    )
    assert response.status_code == 403

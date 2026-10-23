"""MODELISATION_BACKEND.md § 4.1 end to end: request, verification, onboarding, review."""

import pytest
from litestar.testing import TestClient

from tests_integration.conftest import (
    ADMIN_EMAIL,
    ADMIN_PASSWORD,
    RecordingMailer,
    active_user,
    login,
    onboard,
    register,
    set_registration,
    sql,
    verified_onboarding_user,
)

pytestmark = pytest.mark.integration

EMAIL = "awa.diop@chu-fann.sn"


def test_from_request_to_active_account(client: TestClient, mailer: RecordingMailer):
    assert register(client, EMAIL).status_code == 202
    row = sql("SELECT status, terms_accepted_at, no_patient_data_pledge_at FROM users WHERE email = $1", EMAIL)[0]
    assert row["status"] == "pending_email"
    assert row["terms_accepted_at"] and row["no_patient_data_pledge_at"]

    assert login(client, EMAIL).json()["error"] == "account_pending_email"

    assert client.post("/api/auth/verify-email", json={"token": mailer.token_for(EMAIL)}).status_code == 200
    response = login(client, EMAIL)
    assert response.status_code == 200
    assert response.json()["status"] == "onboarding"
    assert response.json()["profession"] is None
    assert client.get("/api/auth/me").json()["status"] == "onboarding"
    # Onboarding sessions only reach /me and the onboarding form.
    assert client.patch("/api/auth/me", json={"fullName": "X"}).status_code == 403

    response = onboard(client)
    assert response.status_code == 200
    assert response.json()["status"] == "pending_review"
    assert "access_token" not in client.cookies  # session ended, the frontend shows "pending"
    assert "Nouvelle demande" in mailer.last_to(ADMIN_EMAIL).subject
    assert login(client, EMAIL).json()["error"] == "account_pending_review"

    assert login(client, ADMIN_EMAIL, ADMIN_PASSWORD).status_code == 200
    requests = client.get("/api/admin/requests").json()
    assert [(r["email"], r["organization"]) for r in requests] == [(EMAIL, "CHU Fann")]
    assert client.post(f"/api/admin/requests/{requests[0]['id']}/approve").json()["status"] == "active"
    assert "Accès accordé" in mailer.last_to(EMAIL).subject

    response = login(client, EMAIL)
    assert response.status_code == 200
    assert response.json() | {"id": None} == {
        "id": None,
        "email": EMAIL,
        "fullName": "Awa Diop",
        "role": "user",
        "status": "active",
        "profession": "medical_biologist",
        "organization": "CHU Fann",
    }

    # MODELISATION § 7.1: every transition is journaled, with its actor.
    audit = sql(
        "SELECT a.action, u.email AS actor FROM audit_log a LEFT JOIN users u ON u.id = a.actor "
        "WHERE a.target_type = 'user' ORDER BY a.created_at"
    )
    assert [(r["action"], r["actor"]) for r in audit] == [
        ("user.register", None),
        ("user.verify_email", EMAIL),
        ("user.submit_profile", EMAIL),
        ("user.approve", ADMIN_EMAIL),
    ]


def test_rejection_with_reason(client: TestClient, mailer: RecordingMailer):
    verified_onboarding_user(client, mailer, EMAIL)
    onboard(client)
    user_id = sql("SELECT id FROM users WHERE email = $1", EMAIL)[0]["id"]
    login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    response = client.post(f"/api/admin/requests/{user_id}/reject", json={"reason": "Usage hors périmètre"})
    assert response.json()["status"] == "rejected"
    assert "Usage hors périmètre" in mailer.last_to(EMAIL).text
    assert login(client, EMAIL).json()["error"] == "account_rejected"
    # The journal records that a reason was given, not the reason itself.
    details = sql("SELECT details FROM audit_log WHERE action = 'user.reject'")[0]["details"]
    assert details == '{"with_reason": true}'


def test_a_decision_applies_once(client: TestClient, mailer: RecordingMailer):
    verified_onboarding_user(client, mailer, EMAIL)
    onboard(client)
    user_id = sql("SELECT id FROM users WHERE email = $1", EMAIL)[0]["id"]
    login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    assert client.post(f"/api/admin/requests/{user_id}/approve").status_code == 200
    response = client.post(f"/api/admin/requests/{user_id}/reject", json={})
    assert response.status_code == 409
    assert response.json()["error"] == "invalid_transition"


def test_open_domains_activates_listed_domains(client: TestClient, mailer: RecordingMailer):
    set_registration("open_domains", ["chu-fann.sn"])
    verified_onboarding_user(client, mailer, EMAIL)
    response = onboard(client)
    assert response.json()["status"] == "active"
    assert "access_token" in client.cookies  # straight in, no review
    assert client.patch("/api/auth/me", json={"organization": "CHU de Fann"}).json()["organization"] == "CHU de Fann"


def test_open_domains_sends_other_domains_to_review(client: TestClient, mailer: RecordingMailer):
    set_registration("open_domains", ["aphp.fr"])
    verified_onboarding_user(client, mailer, EMAIL)
    assert onboard(client).json()["status"] == "pending_review"


def test_invite_only_closes_registration(client: TestClient, mailer: RecordingMailer):
    set_registration("invite_only")
    response = register(client, EMAIL)
    assert response.status_code == 403
    assert response.json()["error"] == "registration_closed"
    assert mailer.sent == []


def test_admin_routes_need_an_admin(client: TestClient, mailer: RecordingMailer):
    client.cookies.clear()
    assert client.get("/api/admin/requests").status_code == 401
    active_user(client, mailer, EMAIL)
    assert client.get("/api/admin/requests").status_code == 403

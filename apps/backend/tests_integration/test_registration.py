"""Neutral answers, professional addresses and single-use links."""

import re

import pytest
from litestar.testing import TestClient

from tests_integration.conftest import PASSWORD, RecordingMailer, login, register, sql, verified_onboarding_user

pytestmark = pytest.mark.integration

EMAIL = "awa.diop@chu-fann.sn"


def test_known_address_gets_the_same_answer(client: TestClient, mailer: RecordingMailer):
    first = register(client, EMAIL)
    second = register(client, EMAIL.upper())  # same address, other case
    assert (first.status_code, first.json()) == (second.status_code, second.json())
    assert sql("SELECT count(*) FROM users")[0]["count"] == 2  # admin + one

    # Still unverified: the second request sends a fresh link, and the first one stops working.
    first_link, second_link = (
        re.search(r"token=([\w-]+)", email.text).group(1) for to, email in mailer.sent if to == EMAIL
    )
    assert client.post("/api/auth/verify-email", json={"token": first_link}).status_code == 422
    assert client.post("/api/auth/verify-email", json={"token": second_link}).status_code == 200


def test_known_verified_address_is_told_by_email_only(client: TestClient, mailer: RecordingMailer):
    verified_onboarding_user(client, mailer, EMAIL)
    response = register(client, EMAIL)
    assert response.status_code == 202
    assert "existe déjà" in mailer.last_to(EMAIL).text


def test_consumer_mailboxes_are_refused(client: TestClient, mailer: RecordingMailer):
    response = register(client, "awa@gmail.com")
    assert response.status_code == 422
    assert response.json()["error"] == "email_not_professional"
    assert mailer.sent == []


@pytest.mark.parametrize(
    "payload",
    [
        {"email": EMAIL, "password": "short", "termsAccepted": True, "noPatientDataPledge": True},
        {"email": EMAIL, "password": PASSWORD, "termsAccepted": False, "noPatientDataPledge": True},
        {"email": EMAIL, "password": PASSWORD, "termsAccepted": True},
        {"email": "not-an-email", "password": PASSWORD, "termsAccepted": True, "noPatientDataPledge": True},
    ],
    ids=["short-password", "terms-refused", "pledge-missing", "bad-email"],
)
def test_invalid_requests(client: TestClient, payload: dict):
    response = client.post("/api/auth/register", json=payload)
    assert response.status_code == 422
    assert response.json()["error"] == "validation_error"


def test_verification_link_works_once(client: TestClient, mailer: RecordingMailer):
    register(client, EMAIL)
    token = mailer.token_for(EMAIL)
    assert client.post("/api/auth/verify-email", json={"token": token}).status_code == 200
    response = client.post("/api/auth/verify-email", json={"token": token})
    assert response.status_code == 422
    assert response.json()["error"] == "invalid_token"


def test_expired_verification_link(client: TestClient, mailer: RecordingMailer):
    register(client, EMAIL)
    sql("UPDATE email_verification_tokens SET expires_at = now() - interval '1 second'")
    response = client.post("/api/auth/verify-email", json={"token": mailer.token_for(EMAIL)})
    assert response.json()["error"] == "invalid_token"


def test_tokens_are_stored_hashed(client: TestClient, mailer: RecordingMailer):
    register(client, EMAIL)
    token = mailer.token_for(EMAIL)
    stored = sql("SELECT token_hash FROM email_verification_tokens")[0]["token_hash"]
    assert token not in stored and len(stored) == 64


def test_resend_verification_is_neutral(client: TestClient, mailer: RecordingMailer):
    register(client, EMAIL)
    unknown = client.post("/api/auth/resend-verification", json={"email": "nobody@chu-fann.sn"})
    known = client.post("/api/auth/resend-verification", json={"email": EMAIL})
    assert (unknown.status_code, unknown.json()) == (known.status_code, known.json())
    assert len([to for to, _ in mailer.sent if to == EMAIL]) == 2


def test_unknown_email_and_wrong_password_look_the_same(client: TestClient, mailer: RecordingMailer):
    verified_onboarding_user(client, mailer, EMAIL)
    wrong = login(client, EMAIL, "wrong-password-123")
    unknown = login(client, "nobody@chu-fann.sn")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()

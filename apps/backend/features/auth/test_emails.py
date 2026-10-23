from urllib.parse import parse_qs, urlparse

import pytest

from core.settings import settings
from features.auth import emails


def _links(email: emails.Email) -> list[str]:
    return [word for word in email.text.split() if word.startswith("http")]


def test_verification_link_points_to_the_frontend():
    (link,) = _links(emails.verification_email("tok-123"))
    url = urlparse(link)
    assert link.startswith(settings.FRONTEND_URL)
    assert url.path == "/fr/verify-email"
    assert parse_qs(url.query) == {"token": ["tok-123"]}


def test_reset_link_points_to_the_frontend():
    (link,) = _links(emails.reset_password_email("tok-456"))
    assert urlparse(link).path == "/fr/reset-password"


@pytest.mark.parametrize(
    "email",
    [
        emails.verification_email("t"),
        emails.already_registered_email(),
        emails.access_request_email("a@aphp.fr", "AP-HP"),
        emails.approved_email(),
        emails.rejected_email("Usage hors périmètre"),
        emails.rejected_email(None),
        emails.reset_password_email("t"),
    ],
)
def test_every_email_has_text_html_and_app_name(email: emails.Email):
    assert settings.APP_NAME in email.subject
    assert email.text.strip()
    assert email.html.startswith("<!DOCTYPE html>")


def test_html_is_escaped():
    email = emails.rejected_email("<script>alert(1)</script>")
    assert "<script>" not in email.html
    assert "&lt;script&gt;" in email.html


def test_logo_is_embedded_inline():
    from email import message_from_bytes

    from core.mail import LOGO_CID, build_message

    email = emails.approved_email()
    assert f'src="cid:{LOGO_CID}"' in email.html
    raw = build_message(to="a@aphp.fr", subject=email.subject, text=email.text, html=email.html).as_bytes()
    parts = {part.get_content_type(): part for part in message_from_bytes(raw).walk()}
    assert {"multipart/alternative", "multipart/related", "text/plain", "text/html", "image/png"} <= set(parts)
    assert parts["image/png"]["Content-ID"] == f"<{LOGO_CID}>"
    assert parts["image/png"].get_content_disposition() == "inline"  # part of the body, not an attachment
    assert parts["image/png"].get_payload(decode=True).startswith(b"\x89PNG")

from dags.common.emails import LOGO_CID, Email
from dags.common.mailer import build_message

EMAIL = Email(
    subject="[genomique] Test",
    text="Texte brut",
    html=f'<p>Corps</p><img src="cid:{LOGO_CID}" />',
)


def _message(email=EMAIL):
    return build_message(sender="Genomica <alertes@example.test>", to=["a@example.test", "b@example.test"],
                         email=email)


def test_message_carries_the_headers():
    message = _message()

    assert message["Subject"] == "[genomique] Test"
    assert message["From"] == "Genomica <alertes@example.test>"
    assert message["To"] == "a@example.test, b@example.test"


def test_message_has_a_text_part_and_an_html_part():
    """Un client sans HTML lit la version texte, comme pour les e-mails de l'application."""
    message = _message()

    assert message.get_body(("plain",)).get_content().strip() == "Texte brut"
    assert "<p>Corps</p>" in message.get_body(("html",)).get_content()


def test_logo_is_embedded_inline_not_attached():
    """Une pièce jointe ordinaire (ce que fait SmtpHook) s'afficherait sous le mail, pas en tête."""
    images = [part for part in _message().walk() if part.get_content_maintype() == "image"]

    assert len(images) == 1
    assert images[0]["Content-ID"] == f"<{LOGO_CID}>"
    assert images[0].get_content_disposition() == "inline"


def test_no_logo_is_sent_when_the_html_does_not_show_it():
    message = _message(Email(subject="s", text="t", html="<p>Sans logo</p>"))

    assert not [part for part in message.walk() if part.get_content_maintype() == "image"]

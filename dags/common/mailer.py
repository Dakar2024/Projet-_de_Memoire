"""Envoi des e-mails du pipeline par la connection SMTP `smtp_default` (relais Resend)."""
from __future__ import annotations

from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path

from dags.common.emails import APP_NAME, LOGO_CID, Email

# Même logo que les e-mails de l'application (apps/backend/core/assets/logo.png), copié : le pipeline
# et l'application se déploient séparément.
_LOGO = Path(__file__).parent / "assets" / "logo.png"


def build_message(*, sender: str, to: list[str], email: Email) -> EmailMessage:
    """Construit le message : texte, HTML, et logo intégré au HTML s'il l'affiche."""
    message = EmailMessage()
    message["Subject"] = email.subject
    message["From"] = sender
    message["To"] = ", ".join(to)
    message.set_content(email.text)
    message.add_alternative(email.html, subtype="html")
    if f"cid:{LOGO_CID}" in email.html:
        # multipart/alternative → la partie HTML devient multipart/related avec l'image.
        # disposition="inline" : avec un simple nom de fichier, la bibliothèque standard la marque
        # « attachment » et les clients l'affichent sous le mail au lieu de l'en-tête.
        message.get_payload()[1].add_related(
            _LOGO.read_bytes(), maintype="image", subtype="png",
            cid=f"<{LOGO_CID}>", disposition="inline", filename="logo.png",
        )
    return message


def send_email(to: list[str], email: Email) -> None:
    """Envoie un e-mail aux destinataires, expéditeur et identifiants lus dans `smtp_default`."""
    from airflow.providers.smtp.hooks.smtp import SmtpHook

    with SmtpHook() as smtp:
        message = build_message(sender=formataddr((APP_NAME, smtp.from_email)), to=to, email=email)
        # `send_email_smtp` n'envoie que son propre MIME (logo en pièce jointe ordinaire) : on passe
        # par le client déjà authentifié du hook. tests_airflow/test_alerting.py vérifie qu'il existe.
        smtp._smtp_client.send_message(message)

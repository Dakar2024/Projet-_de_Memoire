"""Content of the account e-mails. Pure: composing is tested, sending goes through a `Mailer`."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol
from urllib.parse import urlencode

from jinja2 import Environment, FileSystemLoader

from core.mail import LOGO_CID
from core.settings import settings

_jinja = Environment(loader=FileSystemLoader(Path(__file__).parent / "templates"), autoescape=True)

# The frontend routes are prefixed by the language (/fr/…, /en/…); e-mails are French for now.
_LANG = "fr"


@dataclass(frozen=True)
class Email:
    subject: str
    text:    str
    html:    str


class Mailer(Protocol):
    async def send(self, to: str, email: Email) -> None: ...


def frontend_url(path: str, **query: str) -> str:
    """Link into the frontend, always built from FRONTEND_URL (never from a client-supplied URL)."""
    url = f"{settings.FRONTEND_URL.rstrip('/')}/{_LANG}/{path.lstrip('/')}"
    return f"{url}?{urlencode(query)}" if query else url


def _compose(
    subject: str,
    title: str,
    paragraphs: list[str],
    *,
    button_url: str | None = None,
    button_label: str | None = None,
    footnote: str | None = None,
) -> Email:
    lines = [title, "", *paragraphs]
    if button_url:
        lines += ["", f"{button_label} : {button_url}"]
    if footnote:
        lines += ["", footnote]
    html = _jinja.get_template("message.html").render(
        app_name=settings.APP_NAME,
        logo_cid=LOGO_CID,
        year=datetime.now().year,
        title=title,
        paragraphs=paragraphs,
        button_url=button_url,
        button_label=button_label,
        footnote=footnote,
    )
    return Email(subject=f"{subject} — {settings.APP_NAME}", text="\n".join(lines), html=html)


def verification_email(token: str) -> Email:
    return _compose(
        "Confirmez votre adresse",
        "Confirmez votre adresse e-mail",
        [
            "Vous avez demandé un accès à l'application. Confirmez votre adresse pour continuer :",
            "vous compléterez ensuite votre profil professionnel.",
        ],
        button_url=frontend_url("verify-email", token=token),
        button_label="Confirmer mon adresse",
        footnote=f"Ce lien est valable {settings.VERIFICATION_TOKEN_HOURS} h. "
        "Si vous n'êtes pas à l'origine de cette demande, ignorez ce message.",
    )


def already_registered_email() -> Email:
    return _compose(
        "Demande d'inscription",
        "Un compte existe déjà pour cette adresse",
        [
            "Quelqu'un, probablement vous, a demandé à créer un compte avec cette adresse.",
            "Vous pouvez vous connecter, ou réinitialiser votre mot de passe si vous l'avez oublié.",
        ],
        button_url=frontend_url("sign-in"),
        button_label="Se connecter",
        footnote="Si vous n'êtes pas à l'origine de cette demande, ignorez ce message.",
    )


def access_request_email(applicant_email: str, organization: str | None) -> Email:
    return _compose(
        "Nouvelle demande d'accès",
        "Nouvelle demande d'accès à examiner",
        [f"{applicant_email} ({organization or 'établissement non renseigné'}) a complété son profil."],
        button_url=frontend_url("admin/requests"),
        button_label="Examiner la demande",
    )


def approved_email() -> Email:
    return _compose(
        "Accès accordé",
        "Votre accès est accordé",
        ["Votre demande a été acceptée. Vous pouvez maintenant vous connecter."],
        button_url=frontend_url("sign-in"),
        button_label="Se connecter",
    )


def rejected_email(reason: str | None) -> Email:
    paragraphs = ["Votre demande d'accès n'a pas été acceptée."]
    if reason:
        paragraphs.append(f"Motif : {reason}")
    return _compose("Demande d'accès", "Votre demande d'accès", paragraphs)


def reset_password_email(token: str) -> Email:
    return _compose(
        "Réinitialisation du mot de passe",
        "Réinitialisez votre mot de passe",
        ["Vous avez demandé à réinitialiser votre mot de passe."],
        button_url=frontend_url("reset-password", token=token),
        button_label="Choisir un nouveau mot de passe",
        footnote=f"Ce lien est valable {settings.RESET_TOKEN_MINUTES} min. "
        "Si vous n'êtes pas à l'origine de cette demande, ignorez ce message.",
    )

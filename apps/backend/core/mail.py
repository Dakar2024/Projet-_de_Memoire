import logging
from email.message import EmailMessage
from pathlib import Path

import aiosmtplib

from core.settings import settings

logger = logging.getLogger(__name__)

# Brand logo: apps/frontend/public/Genomica_logo.png with its white margins cropped, 900 px wide
# (shown at 300 px, sharp on high-density screens), 256-colour PNG.
# Sent as an inline attachment (cid:), not as a URL: no public server is needed, and Gmail
# blocks data: images. Templates show it with <img src="cid:genomica-logo">.
LOGO_CID = "genomica-logo"
_LOGO = Path(__file__).parent / "assets" / "logo.png"


def build_message(*, to: str, subject: str, text: str, html: str) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"]    = f"{settings.APP_NAME} <{settings.MAIL_FROM}>"
    msg["To"]      = to
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    if f"cid:{LOGO_CID}" in html:
        # multipart/alternative → the HTML part becomes multipart/related with the image.
        html_part = msg.get_payload()[1]
        # disposition="inline": with only a filename, the stdlib marks it "attachment" and mail
        # clients list it as an attachment instead of showing it in the body.
        html_part.add_related(
            _LOGO.read_bytes(),
            maintype="image",
            subtype="png",
            cid=f"<{LOGO_CID}>",
            disposition="inline",
            filename="logo.png",
        )
    return msg


async def send_email(
    *,
    to: str,
    subject: str,
    text: str,
    html: str,
) -> None:
    await aiosmtplib.send(
        build_message(to=to, subject=subject, text=text, html=html),
        hostname=settings.MAIL_SERVER,
        port=settings.MAIL_PORT,
        username=settings.MAIL_USERNAME,
        password=settings.MAIL_PASSWORD,
        use_tls=settings.MAIL_USE_TLS,
        start_tls=settings.MAIL_STARTTLS,
    )
    logger.info("Email envoyé — %s", subject)

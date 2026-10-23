import asyncio
from datetime import UTC, datetime

from huey import crontab

from core.mail import send_email
from core.worker import huey
from features.auth.emails import Email


@huey.task(retries=3, retry_delay=60)
def send_email_task(to: str, subject: str, text: str, html: str) -> None:
    """Send one e-mail from the worker; retried if the SMTP server is unreachable."""
    asyncio.run(send_email(to=to, subject=subject, text=text, html=html))


class HueyMailer:
    """`Mailer` used by the app: the request only enqueues, the worker talks to SMTP."""

    async def send(self, to: str, email: Email) -> None:
        # Enqueueing is a blocking Redis call: keep it off the event loop.
        await asyncio.to_thread(send_email_task, to, email.subject, email.text, email.html)


@huey.periodic_task(crontab(minute="0", hour="3"))  # tous les jours à 3h
def cleanup_expired_tokens() -> None:
    """Supprime les jetons de vérification et de réinitialisation expirés."""
    from features.auth.tables import EmailVerificationToken, PasswordResetToken

    async def _run() -> None:
        now = datetime.now(UTC)
        await EmailVerificationToken.delete().where(EmailVerificationToken.expires_at < now).run()
        await PasswordResetToken.delete().where(PasswordResetToken.expires_at < now).run()

    asyncio.run(_run())

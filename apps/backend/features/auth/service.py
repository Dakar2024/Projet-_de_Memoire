import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from asyncpg.exceptions import UniqueViolationError
from piccolo.columns import Column

from core.exceptions import ValidationError
from core.settings import settings
from features.app_settings.service import RegistrationMode, get_settings
from features.audit.service import record
from features.auth import emails
from features.auth.email_domains import is_allowed_domain, is_professional_email, normalize_email
from features.auth.emails import Mailer
from features.auth.exceptions import (
    AccountBlockedError,
    EmailNotProfessionalError,
    InvalidCredentialsError,
    InvalidTokenError,
    LastAdminError,
    RegistrationClosedError,
)
from features.auth.helpers import (
    burn_password_check,
    create_access_token,
    hash_password,
    password_needs_rehash,
    verify_password,
)
from features.auth.schemas import (
    ChangePasswordRequest,
    LoginRequest,
    OnboardingRequest,
    RegisterRequest,
    UpdateProfileRequest,
)
from features.auth.status import LOGIN_STATUSES, AccountStatus, InvalidTransitionError, plan_transition
from features.auth.tables import EmailVerificationToken, PasswordResetToken, User
from features.auth.tokens import hash_token, new_token

TokenTable = type[EmailVerificationToken] | type[PasswordResetToken]


class InvalidPasswordError(ValidationError):
    code = "invalid_password"

    def __init__(self) -> None:
        super().__init__("Mot de passe actuel incorrect")


def _now() -> datetime:
    return datetime.now(UTC)


async def _hash(plain: str) -> str:
    # Argon2 takes tens of milliseconds of CPU: run it off the event loop.
    return await asyncio.to_thread(hash_password, plain)


async def _verify(plain: str, hashed: str) -> bool:
    return await asyncio.to_thread(verify_password, plain, hashed)


async def _reload(user_id: UUID) -> User:
    return await User.objects().where(User.id == user_id).first()


class AuthService:
    def __init__(self, mailer: Mailer) -> None:
        self._mailer = mailer

    # ── Status changes ───────────────────────────────────────────────────────

    async def transition(
        self,
        user: User,
        target: AccountStatus,
        *,
        actor_id: UUID | None,
        by_admin: bool,
        changes: dict[Column, Any] | None = None,
        details: dict[str, Any] | None = None,
    ) -> User:
        """The only way to change `User.status`: checks the diagram, writes the audit entry with it."""
        plan = plan_transition(AccountStatus(user.status), target, by_admin=by_admin)
        async with User._meta.db.transaction():
            # Conditional on the status read: two concurrent decisions cannot both apply.
            updated = (
                await User.update({User.status: target.value, **(changes or {})})
                .where((User.id == user.id) & (User.status == plan.from_status.value))
                .returning(User.id)
                .run()
            )
            if not updated:
                raise InvalidTransitionError(plan.from_status, target)
            await record(actor_id=actor_id, action=plan.action, target_type="user", target_id=user.id, details=details)
        return await _reload(user.id)

    # ── Registration ─────────────────────────────────────────────────────────

    async def register(self, data: RegisterRequest) -> None:
        """Same outcome whether the address is new or known: nobody learns who has an account."""
        email = normalize_email(data.email)
        if not is_professional_email(email):
            raise EmailNotProfessionalError()
        if (await get_settings()).registration_mode is RegistrationMode.INVITE_ONLY:
            raise RegistrationClosedError()

        # Hashed before the lookup, for a known address too: both answers take the same time.
        hashed = await _hash(data.password)
        existing = await User.objects().where(User.email == email).first()
        if existing is not None:
            await self._answer_known_address(existing)
            return

        now = _now()
        user = User(email=email, hashed_password=hashed, terms_accepted_at=now, no_patient_data_pledge_at=now)
        try:
            await user.save().run()
        except UniqueViolationError:  # registered concurrently
            await self._answer_known_address(await User.objects().where(User.email == email).first())
            return
        await record(actor_id=None, action="user.register", target_type="user", target_id=user.id)
        await self._send_verification(user)

    async def resend_verification(self, email: str) -> None:
        user = await User.objects().where(User.email == normalize_email(email)).first()
        if user is not None and user.status == AccountStatus.PENDING_EMAIL:
            await self._send_verification(user)

    async def verify_email(self, token: str) -> None:
        user_id = await self._consume_token(EmailVerificationToken, token)
        user = await _reload(user_id)
        await self.transition(
            user,
            AccountStatus.ONBOARDING,
            actor_id=user.id,
            by_admin=False,
            changes={User.email_verified_at: _now()},
        )

    async def complete_onboarding(self, user: User, data: OnboardingRequest) -> User:
        config = await get_settings()
        auto = config.registration_mode is RegistrationMode.OPEN_DOMAINS and is_allowed_domain(
            user.email, config.allowed_email_domains
        )
        changes: dict[Column, Any] = {
            User.full_name: data.full_name,
            User.profession: data.profession,
            User.organization: data.organization,
            User.intended_use: data.intended_use or None,
        }
        if auto:
            changes[User.approved_at] = _now()
        target = AccountStatus.ACTIVE if auto else AccountStatus.PENDING_REVIEW
        user = await self.transition(user, target, actor_id=user.id, by_admin=False, changes=changes)
        if not auto:
            message = emails.access_request_email(user.email, user.organization)
            for admin_email in await self._active_admin_emails():
                await self._mailer.send(admin_email, message)
        return user

    # ── Session ──────────────────────────────────────────────────────────────

    async def login(self, data: LoginRequest) -> tuple[User, str]:
        user = await User.objects().where(User.email == normalize_email(data.email)).first()
        if user is None:
            await asyncio.to_thread(burn_password_check, data.password)
            raise InvalidCredentialsError()
        if not await _verify(data.password, user.hashed_password):
            raise InvalidCredentialsError()
        # The status is revealed only to someone who knows the password.
        status = AccountStatus(user.status)
        if status not in LOGIN_STATUSES:
            raise AccountBlockedError(status)

        changes: dict[Column, Any] = {User.last_login_at: _now()}
        if password_needs_rehash(user.hashed_password):
            changes[User.hashed_password] = await _hash(data.password)
        await User.update(changes).where(User.id == user.id).run()
        return user, create_access_token(user.id, user.token_version, remember=data.remember)

    # ── Profile ──────────────────────────────────────────────────────────────

    async def update_profile(self, user: User, data: UpdateProfileRequest) -> User:
        changes: dict[Column, Any] = {}
        if data.full_name is not None:
            changes[User.full_name] = data.full_name
        if data.profession is not None:
            changes[User.profession] = data.profession
        if data.organization is not None:
            changes[User.organization] = data.organization
        if changes:
            await User.update(changes).where(User.id == user.id).run()
        return await _reload(user.id)

    async def change_password(self, user: User, data: ChangePasswordRequest, *, remember: bool) -> str:
        """Sign out every other session; return a fresh token for the current one."""
        if not await _verify(data.current_password, user.hashed_password):
            raise InvalidPasswordError()
        version = await self._set_password(user.id, data.new_password)
        return create_access_token(user.id, version, remember=remember)

    async def delete_account(self, user: User, password: str) -> None:
        if not await _verify(password, user.hashed_password):
            raise InvalidPasswordError()
        async with User._meta.db.transaction():
            if user.role == "admin" and await self._active_admin_count() <= 1:
                raise LastAdminError()
            await record(actor_id=None, action="user.erase", target_type="user", target_id=user.id)
            # Tokens cascade; audit entries keep the action with a null actor.
            await User.delete().where(User.id == user.id).run()

    # ── Password reset ───────────────────────────────────────────────────────

    async def forgot_password(self, email: str) -> None:
        user = await User.objects().where(User.email == normalize_email(email)).first()
        if user is None or AccountStatus(user.status) not in LOGIN_STATUSES:
            return
        token = await self._issue_token(PasswordResetToken, user.id, timedelta(minutes=settings.RESET_TOKEN_MINUTES))
        await self._mailer.send(user.email, emails.reset_password_email(token))

    async def reset_password(self, token: str, password: str) -> None:
        user_id = await self._consume_token(PasswordResetToken, token)
        await self._set_password(user_id, password)
        await record(actor_id=user_id, action="user.reset_password", target_type="user", target_id=user_id)

    # ── Internals ────────────────────────────────────────────────────────────

    async def _answer_known_address(self, user: User) -> None:
        if user.status == AccountStatus.PENDING_EMAIL:
            await self._send_verification(user)
        else:
            await self._mailer.send(user.email, emails.already_registered_email())

    async def _send_verification(self, user: User) -> None:
        lifetime = timedelta(hours=settings.VERIFICATION_TOKEN_HOURS)
        token = await self._issue_token(EmailVerificationToken, user.id, lifetime)
        await self._mailer.send(user.email, emails.verification_email(token))

    async def _issue_token(self, table: TokenTable, user_id: UUID, lifetime: timedelta) -> str:
        """New single-use token; the previous unused ones of the same kind stop working."""
        token, digest = new_token()
        now = _now()
        async with table._meta.db.transaction():
            await table.update({table.used_at: now}).where((table.user == user_id) & table.used_at.is_null()).run()
            await table(user=user_id, token_hash=digest, expires_at=now + lifetime).save().run()
        return token

    async def _consume_token(self, table: TokenTable, token: str) -> UUID:
        """Mark the token used and return its user, in one statement: a link works only once."""
        now = _now()
        rows = (
            await table.update({table.used_at: now})
            .where((table.token_hash == hash_token(token)) & table.used_at.is_null() & (table.expires_at > now))
            .returning(table.user)
            .run()
        )
        if not rows:
            raise InvalidTokenError()
        return rows[0]["user"]

    async def _set_password(self, user_id: UUID, password: str) -> int:
        """Store the new hash and bump `token_version`; return the new version."""
        hashed = await _hash(password)
        async with User._meta.db.transaction():
            rows = (
                await User.update({User.hashed_password: hashed, User.token_version: User.token_version + 1})
                .where(User.id == user_id)
                .returning(User.token_version)
                .run()
            )
            # A reset link must not stay usable once the password has changed.
            await PasswordResetToken.update({PasswordResetToken.used_at: _now()}).where(
                (PasswordResetToken.user == user_id) & PasswordResetToken.used_at.is_null()
            ).run()
        return rows[0]["token_version"]

    async def _active_admin_emails(self) -> list[str]:
        rows = await User.select(User.email).where(
            (User.role == "admin") & (User.status == AccountStatus.ACTIVE.value)
        ).run()
        return [row["email"] for row in rows]

    async def _active_admin_count(self) -> int:
        return await User.count().where((User.role == "admin") & (User.status == AccountStatus.ACTIVE.value)).run()


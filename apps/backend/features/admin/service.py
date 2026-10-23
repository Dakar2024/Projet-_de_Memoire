from datetime import UTC, datetime
from uuid import UUID

from features.auth import emails
from features.auth.emails import Mailer
from features.auth.exceptions import UserNotFoundError
from features.auth.service import AuthService
from features.auth.status import AccountStatus
from features.auth.tables import User


class AccessRequestService:
    """Admin decisions on completed profiles (MODELISATION § 4.5), through AuthService.transition."""

    def __init__(self, auth: AuthService, mailer: Mailer) -> None:
        self._auth = auth
        self._mailer = mailer

    async def pending(self) -> list[User]:
        return (
            await User.objects()
            .where(User.status == AccountStatus.PENDING_REVIEW.value)
            .order_by(User.created_at)
            .run()
        )

    async def approve(self, admin: User, user_id: UUID) -> User:
        user = await self._get(user_id)
        user = await self._auth.transition(
            user,
            AccountStatus.ACTIVE,
            actor_id=admin.id,
            by_admin=True,
            changes={User.approved_at: datetime.now(UTC), User.approved_by: admin.id},
        )
        await self._mailer.send(user.email, emails.approved_email())
        return user

    async def reject(self, admin: User, user_id: UUID, reason: str) -> User:
        user = await self._get(user_id)
        user = await self._auth.transition(
            user,
            AccountStatus.REJECTED,
            actor_id=admin.id,
            by_admin=True,
            changes={User.rejection_reason: reason or None},
            # The reason goes to the applicant by e-mail; the journal only records that one was given.
            details={"with_reason": bool(reason)},
        )
        await self._mailer.send(user.email, emails.rejected_email(reason or None))
        return user

    async def _get(self, user_id: UUID) -> User:
        user = await User.objects().where(User.id == user_id).first()
        if user is None:
            raise UserNotFoundError(str(user_id))
        return user

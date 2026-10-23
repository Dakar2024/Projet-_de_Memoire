"""Daily quota and monthly budget (MODELISATION_BACKEND.md § 4.3)."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from uuid import UUID

from core.exceptions import AppError
from features.app_settings.service import SettingsSnapshot
from features.auth.tables import User
from features.usage.tables import DailyUsage, UsageEvent


class QuotaExceededError(AppError):
    code = "quota_exceeded"
    status = 429

    def __init__(self, resets_at: datetime) -> None:
        super().__init__("Quota de questions atteint pour aujourd'hui.")
        self.headers = {"Retry-After": str(max(1, int((resets_at - datetime.now(UTC)).total_seconds())))}


class BudgetExhaustedError(AppError):
    code = "budget_exhausted"
    status = 503

    def __init__(self) -> None:
        super().__init__("Le budget mensuel de l'assistant est atteint. Réessayez le mois prochain.")


@dataclass(frozen=True)
class Quota:
    used:      int
    limit:     int
    resets_at: datetime

    @property
    def remaining(self) -> int:
        return max(self.limit - self.used, 0)


def today() -> date:
    # The quota day is UTC (also Dakar's time): one boundary for every user and every worker.
    return datetime.now(UTC).date()


def next_reset(day: date) -> datetime:
    return datetime.combine(day + timedelta(days=1), time.min, tzinfo=UTC)


def month_start(now: datetime) -> datetime:
    return datetime(now.year, now.month, 1, tzinfo=UTC)


def daily_limit(user: User, config: SettingsSnapshot) -> int:
    return user.daily_quota_override if user.daily_quota_override is not None else config.default_daily_quota


async def reserve(user_id: UUID, day: date, limit: int) -> int:
    """Take one unit if any is left, in a single statement: two tabs cannot both pass the limit.

    Returns the count after the reservation; raises QuotaExceededError when nothing is left.
    """
    rows = await DailyUsage.raw(
        "INSERT INTO daily_usage (id, \"user\", day, used) VALUES (gen_random_uuid(), {}, {}, 1) "
        "ON CONFLICT (\"user\", day) DO UPDATE SET used = daily_usage.used + 1 "
        "WHERE daily_usage.used < {} "
        "RETURNING used",
        user_id,
        day,
        limit,
    )
    # A first insertion bypasses the WHERE: refuse it too when the limit is zero.
    if not rows or rows[0]["used"] > limit:
        if rows:
            await release(user_id, day)
        raise QuotaExceededError(next_reset(day))
    return rows[0]["used"]


async def release(user_id: UUID, day: date) -> None:
    """Give the unit back: the user does not pay for a failure of the assistant."""
    await DailyUsage.raw(
        "UPDATE daily_usage SET used = used - 1 WHERE \"user\" = {} AND day = {} AND used > 0", user_id, day
    )


async def quota_of(user: User, config: SettingsSnapshot) -> Quota:
    day = today()
    row = await DailyUsage.select(DailyUsage.used).where((DailyUsage.user == user.id) & (DailyUsage.day == day)).first()
    return Quota(used=row["used"] if row else 0, limit=daily_limit(user, config), resets_at=next_reset(day))


async def month_cost(now: datetime | None = None) -> Decimal:
    start = month_start(now or datetime.now(UTC))
    rows = await UsageEvent.raw(
        "SELECT COALESCE(SUM(cost_usd), 0) AS total FROM usage_events WHERE created_at >= {}", start
    )
    return Decimal(rows[0]["total"])


async def ensure_budget(config: SettingsSnapshot) -> None:
    """Refuse new questions once the month's LLM spending reached the budget set by the admin."""
    if await month_cost() >= config.monthly_budget_usd:
        raise BudgetExhaustedError()

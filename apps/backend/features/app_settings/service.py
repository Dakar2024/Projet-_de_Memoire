from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from features.app_settings.tables import SINGLETON_ID, AppSettings


class RegistrationMode(StrEnum):
    ADMIN_REVIEW = "admin_review"  # every completed profile goes to an admin
    OPEN_DOMAINS = "open_domains"  # allowed domains are activated at once, the others reviewed
    INVITE_ONLY  = "invite_only"   # registration closed (invitations are not built yet)


class SettingsSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    registration_mode:           RegistrationMode
    allowed_email_domains:       list[str]
    default_daily_quota:         int
    monthly_budget_usd:          Decimal
    conversation_retention_days: int | None
    admin_trace_visible:         bool
    banner_message:              str | None


async def get_settings() -> SettingsSnapshot:
    """Read the settings row, creating it with the defaults on first use."""
    row = await AppSettings.objects().where(AppSettings.id == SINGLETON_ID).first()
    if row is None:
        # ON CONFLICT: two workers may hit an empty table at the same time.
        await AppSettings.insert(AppSettings(id=SINGLETON_ID)).on_conflict(action="DO NOTHING").run()
        row = await AppSettings.objects().where(AppSettings.id == SINGLETON_ID).first()
    return SettingsSnapshot.model_validate(row.to_dict())

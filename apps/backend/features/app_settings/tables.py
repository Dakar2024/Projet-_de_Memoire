from decimal import Decimal

from piccolo.columns import Array, Boolean, ForeignKey, Integer, Numeric, Text, Timestamptz, Varchar
from piccolo.columns.base import OnDelete
from piccolo.table import Table

from features.auth.tables import User

SINGLETON_ID = 1


class AppSettings(Table, tablename="app_settings"):
    """Global settings, one row (id = 1), edited from the admin screen."""

    id                          = Integer(primary_key=True, default=SINGLETON_ID)
    registration_mode           = Varchar(length=32, default="admin_review")  # admin_review|open_domains|invite_only
    allowed_email_domains       = Array(base_column=Varchar(length=255), default=list)
    default_daily_quota         = Integer(default=20)
    monthly_budget_usd          = Numeric(digits=(10, 2), default=Decimal("50.00"))
    conversation_retention_days = Integer(default=90)  # 0 = keep nothing
    admin_trace_visible         = Boolean(default=False)
    banner_message              = Text(null=True, default=None)
    updated_by                  = ForeignKey(references=User, null=True, default=None, on_delete=OnDelete.set_null)
    updated_at                  = Timestamptz(auto_now=True)

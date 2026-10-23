from piccolo.columns import UUID, Date, ForeignKey, Integer, Numeric, Timestamptz, Varchar
from piccolo.columns.base import OnDelete
from piccolo.constraints import Unique
from piccolo.table import Table

from features.assistant.tables import Message
from features.auth.tables import User


class DailyUsage(Table, tablename="daily_usage"):
    """Quota counter, reserved atomically before each RAG call (MODELISATION § 4.3)."""

    id   = UUID(primary_key=True)
    user = ForeignKey(references=User, on_delete=OnDelete.cascade)
    day  = Date()  # UTC
    used = Integer(default=0)

    # Target of the INSERT … ON CONFLICT of the reservation.
    one_counter_per_day = Unique([user, day])


class UsageEvent(Table, tablename="usage_events"):
    """Append-only, one row per RAG call, never the question or the answer text."""

    id             = UUID(primary_key=True)
    # Set to null when the account is erased: the month's spending must not shrink.
    user           = ForeignKey(references=User, null=True, default=None, on_delete=OnDelete.set_null)
    message        = ForeignKey(references=Message, null=True, default=None, on_delete=OnDelete.set_null)
    status         = Varchar(length=32, null=True, default=None)  # answer status when HTTP 200
    http_status    = Integer()                                    # what the user received
    error_code     = Varchar(length=32, null=True, default=None)
    cost_usd       = Numeric(digits=(10, 6), default=None, null=True)
    model          = Varchar(length=128, null=True, default=None)
    provider_name  = Varchar(length=64, null=True, default=None)
    latency_ms     = Integer(null=True, default=None)
    rag_request_id = Varchar(length=64, null=True, default=None)
    created_at     = Timestamptz(auto_now_add=True, index=True)

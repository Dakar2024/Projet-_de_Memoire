from piccolo.columns import JSONB, UUID, ForeignKey, Timestamptz, Varchar
from piccolo.columns.base import OnDelete
from piccolo.table import Table

from features.auth.tables import User


class AuditLog(Table, tablename="audit_log"):
    """Append-only journal of sensitive actions. `details` never holds personal data."""

    id          = UUID(primary_key=True)
    # Null for system actions, and after the actor's account is erased.
    actor       = ForeignKey(references=User, null=True, default=None, on_delete=OnDelete.set_null)
    action      = Varchar(length=64)   # user.approve, user.suspend, settings.update…
    target_type = Varchar(length=32)   # user, settings…
    target_id   = Varchar(length=64)   # a UUID, kept as text so erasing the target keeps the entry
    details     = JSONB(default={})
    created_at  = Timestamptz(auto_now_add=True, index=True)

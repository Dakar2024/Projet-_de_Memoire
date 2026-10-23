from typing import Any
from uuid import UUID

from features.audit.tables import AuditLog


async def record(
    *,
    actor_id: UUID | None,
    action: str,
    target_type: str,
    target_id: UUID | str,
    details: dict[str, Any] | None = None,
) -> None:
    """Write one audit entry. Call it inside the transaction of the change it describes."""
    await AuditLog(
        actor=actor_id,
        action=action,
        target_type=target_type,
        target_id=str(target_id),
        details=details or {},
    ).save().run()

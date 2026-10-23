import asyncio
from datetime import UTC, datetime, timedelta

from huey import crontab

from core.worker import huey


async def purge_conversations(now: datetime | None = None) -> int:
    """Remove for good the conversations the users deleted, and those past the retention period.

    Messages, sources and feedback go with them (ON DELETE CASCADE); usage_events keep their
    costs with a null message. Returns the number of conversations removed.
    """
    from features.app_settings.service import get_settings
    from features.assistant.tables import Conversation

    now = now or datetime.now(UTC)
    expired = Conversation.deleted_at.is_not_null()
    retention = (await get_settings()).conversation_retention_days
    if retention is not None:
        # Set by an admin; by default (null) the history is kept until the user deletes it.
        expired |= Conversation.updated_at < now - timedelta(days=retention)
    removed = await Conversation.delete().where(expired).returning(Conversation.id).run()
    return len(removed)


@huey.periodic_task(crontab(minute="30", hour="3"))  # tous les jours à 3 h 30
def purge_conversations_task() -> None:
    asyncio.run(purge_conversations())

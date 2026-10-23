"""Data migration: no retention limit by default (decision of 2026-10-23).

Separate from the column change before it: Piccolo runs `add_raw` before the column operations of
the same migration, so the NOT NULL constraint was still there.
"""

from piccolo.apps.migrations.auto.migration_manager import MigrationManager
from piccolo.table import Table

ID = "2026-10-23T01:51:31:000000"
VERSION = "1.38.0"
DESCRIPTION = "Keep conversations until the user deletes them"


class AppSettings(Table, tablename="app_settings"):
    """Bare table class, only to run raw SQL on it."""


async def forwards():
    manager = MigrationManager(migration_id=ID, app_name="app_settings", description=DESCRIPTION)

    async def keep_until_deleted() -> None:
        # The row created with the old default (90) follows the new one; a value set by an admin stays.
        await AppSettings.raw(
            "UPDATE app_settings SET conversation_retention_days = NULL WHERE conversation_retention_days = 90"
        )

    manager.add_raw(keep_until_deleted)
    return manager

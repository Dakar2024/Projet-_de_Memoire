from piccolo.apps.migrations.auto.migration_manager import MigrationManager
from piccolo.columns.column_types import Integer

ID = "2026-10-23T01:51:30:718807"
VERSION = "1.38.0"
DESCRIPTION = ""


async def forwards():
    manager = MigrationManager(
        migration_id=ID, app_name="app_settings", description=DESCRIPTION
    )

    manager.alter_column(
        table_class_name="AppSettings",
        tablename="app_settings",
        column_name="conversation_retention_days",
        db_column_name="conversation_retention_days",
        params={"default": None, "null": True},
        old_params={"default": 90, "null": False},
        column_class=Integer,
        old_column_class=Integer,
        schema=None,
    )

    return manager

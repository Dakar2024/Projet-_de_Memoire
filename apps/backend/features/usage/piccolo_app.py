from piccolo.conf.apps import AppConfig

from features.usage.tables import DailyUsage, UsageEvent

APP_CONFIG = AppConfig(
    app_name="usage",
    migrations_folder_path="features/usage/migrations",
    table_classes=[DailyUsage, UsageEvent],
    migration_dependencies=["features.auth.piccolo_app", "features.assistant.piccolo_app"],
)

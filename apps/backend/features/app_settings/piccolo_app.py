from piccolo.conf.apps import AppConfig

from features.app_settings.tables import AppSettings

APP_CONFIG = AppConfig(
    app_name="app_settings",
    migrations_folder_path="features/app_settings/migrations",
    table_classes=[AppSettings],
    migration_dependencies=["features.auth.piccolo_app"],
)

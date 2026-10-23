from piccolo.conf.apps import AppConfig

from features.audit.tables import AuditLog

APP_CONFIG = AppConfig(
    app_name="audit",
    migrations_folder_path="features/audit/migrations",
    table_classes=[AuditLog],
    migration_dependencies=["features.auth.piccolo_app"],
)

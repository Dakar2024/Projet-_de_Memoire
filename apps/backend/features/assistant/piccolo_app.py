from piccolo.conf.apps import AppConfig

from features.assistant.tables import Conversation, Feedback, Message, MessageSource

APP_CONFIG = AppConfig(
    app_name="assistant",
    migrations_folder_path="features/assistant/migrations",
    table_classes=[Conversation, Message, MessageSource, Feedback],
    migration_dependencies=["features.auth.piccolo_app"],
)

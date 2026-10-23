from piccolo.conf.apps import AppRegistry
from piccolo.engine.postgres import PostgresEngine

from core.settings import settings

# Piccolo lit ce fichier via PICCOLO_CONF=core.database (dans .env ou Makefile)

DB = PostgresEngine(config={
    "database": settings.POSTGRES_DB,
    "user":     settings.POSTGRES_USER,
    "password": settings.POSTGRES_PASSWORD,
    "host":     settings.POSTGRES_HOST,
    "port":     settings.POSTGRES_PORT,
})

APP_REGISTRY = AppRegistry(apps=[
    "features.auth.piccolo_app",
    "features.audit.piccolo_app",
    "features.app_settings.piccolo_app",
    "features.assistant.piccolo_app",
    "features.usage.piccolo_app",
    # "features.my_feature.piccolo_app",
])

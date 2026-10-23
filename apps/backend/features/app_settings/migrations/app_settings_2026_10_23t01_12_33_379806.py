import decimal

from piccolo.apps.migrations.auto.migration_manager import MigrationManager
from piccolo.columns.base import OnDelete, OnUpdate
from piccolo.columns.column_types import UUID, Array, Boolean, ForeignKey, Integer, Numeric, Text, Timestamptz, Varchar
from piccolo.columns.defaults.timestamptz import TimestamptzNow
from piccolo.columns.defaults.uuid import UUID4
from piccolo.columns.indexes import IndexMethod
from piccolo.table import Table


class User(Table, tablename="users", schema=None):
    id = UUID(
        default=UUID4(),
        null=False,
        primary_key=True,
        unique=False,
        index=False,
        index_method=IndexMethod.btree,
        choices=None,
        db_column_name=None,
        secret=False,
    )


ID = "2026-10-23T01:12:33:379806"
VERSION = "1.38.0"
DESCRIPTION = ""


async def forwards():
    manager = MigrationManager(
        migration_id=ID, app_name="app_settings", description=DESCRIPTION
    )

    manager.add_table(
        class_name="AppSettings",
        tablename="app_settings",
        schema=None,
        columns=None,
    )

    manager.add_column(
        table_class_name="AppSettings",
        tablename="app_settings",
        column_name="id",
        db_column_name="id",
        column_class_name="Integer",
        column_class=Integer,
        params={
            "default": 1,
            "null": False,
            "primary_key": True,
            "unique": False,
            "index": False,
            "index_method": IndexMethod.btree,
            "choices": None,
            "db_column_name": None,
            "secret": False,
        },
        schema=None,
    )

    manager.add_column(
        table_class_name="AppSettings",
        tablename="app_settings",
        column_name="registration_mode",
        db_column_name="registration_mode",
        column_class_name="Varchar",
        column_class=Varchar,
        params={
            "length": 32,
            "default": "admin_review",
            "null": False,
            "primary_key": False,
            "unique": False,
            "index": False,
            "index_method": IndexMethod.btree,
            "choices": None,
            "db_column_name": None,
            "secret": False,
        },
        schema=None,
    )

    manager.add_column(
        table_class_name="AppSettings",
        tablename="app_settings",
        column_name="allowed_email_domains",
        db_column_name="allowed_email_domains",
        column_class_name="Array",
        column_class=Array,
        params={
            "default": list,
            "base_column": Varchar(
                length=255,
                default="",
                null=False,
                primary_key=False,
                unique=False,
                index=False,
                index_method=IndexMethod.btree,
                choices=None,
                db_column_name=None,
                secret=False,
            ),
            "null": False,
            "primary_key": False,
            "unique": False,
            "index": False,
            "index_method": IndexMethod.btree,
            "choices": None,
            "db_column_name": None,
            "secret": False,
        },
        schema=None,
    )

    manager.add_column(
        table_class_name="AppSettings",
        tablename="app_settings",
        column_name="default_daily_quota",
        db_column_name="default_daily_quota",
        column_class_name="Integer",
        column_class=Integer,
        params={
            "default": 20,
            "null": False,
            "primary_key": False,
            "unique": False,
            "index": False,
            "index_method": IndexMethod.btree,
            "choices": None,
            "db_column_name": None,
            "secret": False,
        },
        schema=None,
    )

    manager.add_column(
        table_class_name="AppSettings",
        tablename="app_settings",
        column_name="monthly_budget_usd",
        db_column_name="monthly_budget_usd",
        column_class_name="Numeric",
        column_class=Numeric,
        params={
            "default": decimal.Decimal("50.00"),
            "digits": (10, 2),
            "null": False,
            "primary_key": False,
            "unique": False,
            "index": False,
            "index_method": IndexMethod.btree,
            "choices": None,
            "db_column_name": None,
            "secret": False,
        },
        schema=None,
    )

    manager.add_column(
        table_class_name="AppSettings",
        tablename="app_settings",
        column_name="conversation_retention_days",
        db_column_name="conversation_retention_days",
        column_class_name="Integer",
        column_class=Integer,
        params={
            "default": 90,
            "null": False,
            "primary_key": False,
            "unique": False,
            "index": False,
            "index_method": IndexMethod.btree,
            "choices": None,
            "db_column_name": None,
            "secret": False,
        },
        schema=None,
    )

    manager.add_column(
        table_class_name="AppSettings",
        tablename="app_settings",
        column_name="admin_trace_visible",
        db_column_name="admin_trace_visible",
        column_class_name="Boolean",
        column_class=Boolean,
        params={
            "default": False,
            "null": False,
            "primary_key": False,
            "unique": False,
            "index": False,
            "index_method": IndexMethod.btree,
            "choices": None,
            "db_column_name": None,
            "secret": False,
        },
        schema=None,
    )

    manager.add_column(
        table_class_name="AppSettings",
        tablename="app_settings",
        column_name="banner_message",
        db_column_name="banner_message",
        column_class_name="Text",
        column_class=Text,
        params={
            "default": None,
            "null": True,
            "primary_key": False,
            "unique": False,
            "index": False,
            "index_method": IndexMethod.btree,
            "choices": None,
            "db_column_name": None,
            "secret": False,
        },
        schema=None,
    )

    manager.add_column(
        table_class_name="AppSettings",
        tablename="app_settings",
        column_name="updated_by",
        db_column_name="updated_by",
        column_class_name="ForeignKey",
        column_class=ForeignKey,
        params={
            "references": User,
            "on_delete": OnDelete.set_null,
            "on_update": OnUpdate.cascade,
            "target_column": None,
            "null": True,
            "primary_key": False,
            "unique": False,
            "index": False,
            "index_method": IndexMethod.btree,
            "choices": None,
            "db_column_name": None,
            "secret": False,
        },
        schema=None,
    )

    manager.add_column(
        table_class_name="AppSettings",
        tablename="app_settings",
        column_name="updated_at",
        db_column_name="updated_at",
        column_class_name="Timestamptz",
        column_class=Timestamptz,
        params={
            "default": TimestamptzNow(),
            "auto_now": True,
            "null": False,
            "primary_key": False,
            "unique": False,
            "index": False,
            "index_method": IndexMethod.btree,
            "choices": None,
            "db_column_name": None,
            "secret": False,
        },
        schema=None,
    )

    return manager

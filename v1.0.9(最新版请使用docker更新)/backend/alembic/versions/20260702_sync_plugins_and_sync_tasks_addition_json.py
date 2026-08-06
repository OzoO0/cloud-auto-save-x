"""sync plugins and sync tasks addition json

Revision ID: 20260702_sync_plugins_and_sync_tasks_addition_json
Revises: 20260701_sync_executions_cancel_fields
Create Date: 2026-07-02 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260702_sync_plugins_and_sync_tasks_addition_json"
down_revision = "20260701_sync_executions_cancel_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "sync_tasks" in existing_tables:
        cols = {c["name"] for c in inspector.get_columns("sync_tasks")}
        if "addition_json" not in cols:
            op.add_column("sync_tasks", sa.Column("addition_json", sa.Text(), nullable=True))

    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "sync_plugin_definitions" not in existing_tables:
        op.create_table(
            "sync_plugin_definitions",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column("plugin_key", sa.String(length=128), nullable=False),
            sa.Column("module_name", sa.String(length=128), nullable=False),
            sa.Column("source_type", sa.String(length=16), nullable=False),
            sa.Column("version", sa.String(length=32), nullable=True),
            sa.Column("installed", sa.Boolean(), nullable=False, server_default="1"),
            sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("plugin_key"),
            sa.UniqueConstraint("module_name"),
        )
        op.create_index("ix_sync_plugin_definitions_plugin_key", "sync_plugin_definitions", ["plugin_key"])

    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "sync_plugin_configs" not in existing_tables and "sync_plugin_definitions" in existing_tables:
        op.create_table(
            "sync_plugin_configs",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column("sync_plugin_definition_id", sa.Integer(), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default="1"),
            sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
            sa.Column("config_json", sa.Text(), nullable=True),
            sa.Column("default_task_config_json", sa.Text(), nullable=True),
            sa.Column("runtime_status", sa.String(length=32), nullable=True),
            sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.ForeignKeyConstraint(["sync_plugin_definition_id"], ["sync_plugin_definitions.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("sync_plugin_definition_id"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "sync_plugin_configs" in existing_tables:
        op.drop_table("sync_plugin_configs")

    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "sync_plugin_definitions" in existing_tables:
        op.drop_index("ix_sync_plugin_definitions_plugin_key", table_name="sync_plugin_definitions")
        op.drop_table("sync_plugin_definitions")

    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "sync_tasks" in existing_tables:
        cols = {c["name"] for c in inspector.get_columns("sync_tasks")}
        if "addition_json" in cols:
            op.drop_column("sync_tasks", "addition_json")


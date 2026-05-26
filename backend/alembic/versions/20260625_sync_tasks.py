"""sync tasks

Revision ID: 20260625_sync_tasks
Revises: 20260623_task_savepath_snapshots_task_uid
Create Date: 2026-06-25 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260625_sync_tasks"
down_revision = "20260623_task_savepath_snapshots_task_uid"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "sync_tasks" not in existing_tables:
        op.create_table(
            "sync_tasks",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default="1"),
            sa.Column("source_type", sa.String(length=16), nullable=False),
            sa.Column("source_path", sa.Text(), nullable=False),
            sa.Column("target_type", sa.String(length=16), nullable=False),
            sa.Column("target_path", sa.Text(), nullable=False),
            sa.Column("mode", sa.String(length=16), nullable=False, server_default="one_way"),
            sa.Column("strategy_json", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )

    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "sync_executions" not in existing_tables:
        op.create_table(
            "sync_executions",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column("sync_task_id", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("stage", sa.String(length=64), nullable=True),
            sa.Column("run_log", sa.Text(), nullable=True),
            sa.Column("stats_json", sa.Text(), nullable=True),
            sa.Column("message", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["sync_task_id"], ["sync_tasks.id"], ondelete="CASCADE"),
        )
        op.create_index("ix_sync_executions_sync_task_id", "sync_executions", ["sync_task_id"])

    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "sync_file_snapshots" not in existing_tables:
        op.create_table(
            "sync_file_snapshots",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column("sync_task_id", sa.Integer(), nullable=False),
            sa.Column("side", sa.String(length=16), nullable=False),
            sa.Column("rel_path", sa.Text(), nullable=False),
            sa.Column("is_dir", sa.Boolean(), nullable=False, server_default="0"),
            sa.Column("size", sa.BigInteger(), nullable=False, server_default="0"),
            sa.Column("modified_at", sa.Float(), nullable=False, server_default="0"),
            sa.Column("hash", sa.String(length=128), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["sync_task_id"], ["sync_tasks.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("sync_task_id", "side", "rel_path", name="uq_sync_snapshot_task_side_path"),
        )
        op.create_index("ix_sync_file_snapshots_sync_task_id", "sync_file_snapshots", ["sync_task_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "sync_file_snapshots" in existing_tables:
        op.drop_index("ix_sync_file_snapshots_sync_task_id", table_name="sync_file_snapshots")
        op.drop_table("sync_file_snapshots")

    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "sync_executions" in existing_tables:
        op.drop_index("ix_sync_executions_sync_task_id", table_name="sync_executions")
        op.drop_table("sync_executions")

    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "sync_tasks" in existing_tables:
        op.drop_table("sync_tasks")


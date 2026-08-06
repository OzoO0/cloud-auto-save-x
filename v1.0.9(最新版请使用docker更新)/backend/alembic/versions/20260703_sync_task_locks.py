"""sync task locks

Revision ID: 20260703_sync_task_locks
Revises: 20260702_sync_plugins_and_sync_tasks_addition_json
Create Date: 2026-07-03 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260703_sync_task_locks"
down_revision = "20260702_sync_plugins_and_sync_tasks_addition_json"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "sync_task_locks" not in existing_tables:
        op.create_table(
            "sync_task_locks",
            sa.Column("sync_task_id", sa.Integer(), nullable=False),
            sa.Column("locked_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("owner", sa.String(length=64), nullable=True),
            sa.ForeignKeyConstraint(["sync_task_id"], ["sync_tasks.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("sync_task_id"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "sync_task_locks" in existing_tables:
        op.drop_table("sync_task_locks")


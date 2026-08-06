"""task savepath snapshots

Revision ID: 20260622_task_savepath_snapshots
Revises: 20260621_share_preview_batch_cache
Create Date: 2026-06-22 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260622_task_savepath_snapshots"
down_revision = "20260621_share_preview_batch_cache"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "task_savepath_snapshots" in inspector.get_table_names():
        return

    op.create_table(
        "task_savepath_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("task_execution_id", sa.Integer(), nullable=True),
        sa.Column("drive_account_id", sa.Integer(), nullable=True),
        sa.Column("savepath", sa.String(length=255), nullable=False),
        sa.Column("files_json", sa.Text(), nullable=False),
        sa.Column("file_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_size", sa.BigInteger(), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_execution_id"], ["task_executions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["drive_account_id"], ["drive_accounts.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("task_id", name="uq_task_savepath_snapshots_task_id"),
    )
    op.create_index("ix_task_savepath_snapshots_task_execution_id", "task_savepath_snapshots", ["task_execution_id"])
    op.create_index("ix_task_savepath_snapshots_drive_account_id", "task_savepath_snapshots", ["drive_account_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "task_savepath_snapshots" not in inspector.get_table_names():
        return

    op.drop_index("ix_task_savepath_snapshots_drive_account_id", table_name="task_savepath_snapshots")
    op.drop_index("ix_task_savepath_snapshots_task_execution_id", table_name="task_savepath_snapshots")
    op.drop_table("task_savepath_snapshots")


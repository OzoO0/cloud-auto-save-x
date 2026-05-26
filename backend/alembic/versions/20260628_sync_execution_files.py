"""sync execution files

Revision ID: 20260628_sync_execution_files
Revises: 20260627_sync_executions_heartbeat_at
Create Date: 2026-06-28 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260628_sync_execution_files"
down_revision = "20260627_sync_executions_heartbeat_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())
    if "sync_executions" not in existing_tables:
        return
    if "sync_execution_files" in existing_tables:
        return

    op.create_table(
        "sync_execution_files",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("sync_execution_id", sa.Integer(), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["sync_execution_id"], ["sync_executions.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("sync_execution_id", "path", name="uq_sync_execution_files_execution_path"),
    )
    op.create_index("ix_sync_execution_files_execution_id", "sync_execution_files", ["sync_execution_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())
    if "sync_execution_files" not in existing_tables:
        return
    op.drop_index("ix_sync_execution_files_execution_id", table_name="sync_execution_files")
    op.drop_table("sync_execution_files")


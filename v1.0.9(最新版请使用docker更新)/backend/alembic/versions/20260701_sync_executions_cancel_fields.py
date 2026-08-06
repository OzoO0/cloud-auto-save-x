"""sync executions cancel fields

Revision ID: 20260701_sync_executions_cancel_fields
Revises: 20260630_sync_task_drama_links
Create Date: 2026-07-01 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260701_sync_executions_cancel_fields"
down_revision = "20260630_sync_task_drama_links"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())
    if "sync_executions" not in existing_tables:
        return

    cols = {c["name"] for c in inspector.get_columns("sync_executions")}
    if "cancel_requested_at" not in cols:
        op.add_column("sync_executions", sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True))
    if "cancel_requested_by" not in cols:
        op.add_column("sync_executions", sa.Column("cancel_requested_by", sa.Integer(), nullable=True))
    if "cancel_message" not in cols:
        op.add_column("sync_executions", sa.Column("cancel_message", sa.Text(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())
    if "sync_executions" not in existing_tables:
        return

    cols = {c["name"] for c in inspector.get_columns("sync_executions")}
    if "cancel_message" in cols:
        op.drop_column("sync_executions", "cancel_message")
    if "cancel_requested_by" in cols:
        op.drop_column("sync_executions", "cancel_requested_by")
    if "cancel_requested_at" in cols:
        op.drop_column("sync_executions", "cancel_requested_at")


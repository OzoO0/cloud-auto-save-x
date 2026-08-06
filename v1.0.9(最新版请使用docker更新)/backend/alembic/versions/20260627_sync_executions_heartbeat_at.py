"""sync executions heartbeat_at

Revision ID: 20260627_sync_executions_heartbeat_at
Revises: 20260626_openlist_settings
Create Date: 2026-06-27 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260627_sync_executions_heartbeat_at"
down_revision = "20260626_openlist_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())
    if "sync_executions" not in existing_tables:
        return

    cols = {c["name"] for c in inspector.get_columns("sync_executions")}
    if "heartbeat_at" not in cols:
        op.add_column("sync_executions", sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())
    if "sync_executions" not in existing_tables:
        return

    cols = {c["name"] for c in inspector.get_columns("sync_executions")}
    if "heartbeat_at" in cols:
        op.drop_column("sync_executions", "heartbeat_at")


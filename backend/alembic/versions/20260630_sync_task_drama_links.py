"""sync task drama links

Revision ID: 20260630_sync_task_drama_links
Revises: 20260629_sync_tasks_uid
Create Date: 2026-06-30 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260630_sync_task_drama_links"
down_revision = "20260629_sync_tasks_uid"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "sync_task_drama_links" in existing_tables:
        return

    op.create_table(
        "sync_task_drama_links",
        sa.Column("sync_task_uid", sa.String(length=32), nullable=False),
        sa.Column("task_uid", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["sync_task_uid"], ["sync_tasks.uid"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_uid"], ["tasks.task_uid"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("sync_task_uid", "task_uid", name="pk_sync_task_drama_links"),
    )
    op.create_index("ix_sync_task_drama_links_sync_task_uid", "sync_task_drama_links", ["sync_task_uid"])
    op.create_index("ix_sync_task_drama_links_task_uid", "sync_task_drama_links", ["task_uid"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "sync_task_drama_links" not in existing_tables:
        return

    op.drop_index("ix_sync_task_drama_links_task_uid", table_name="sync_task_drama_links")
    op.drop_index("ix_sync_task_drama_links_sync_task_uid", table_name="sync_task_drama_links")
    op.drop_table("sync_task_drama_links")


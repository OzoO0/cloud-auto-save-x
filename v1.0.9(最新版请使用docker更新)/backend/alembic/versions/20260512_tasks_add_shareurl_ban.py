"""tasks add shareurl ban

Revision ID: 20260512_tasks_add_shareurl_ban
Revises: 20260614_task_scheduler_default_enable_and_cron, 20260614_resource_search_sources
Create Date: 2026-05-12 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260512_tasks_add_shareurl_ban"
down_revision = ("20260614_task_scheduler_default_enable_and_cron", "20260614_resource_search_sources")
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "tasks" not in inspector.get_table_names():
        return
    columns = {col.get("name") for col in inspector.get_columns("tasks")}
    if "shareurl_ban" not in columns:
        op.add_column("tasks", sa.Column("shareurl_ban", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("tasks", "shareurl_ban")

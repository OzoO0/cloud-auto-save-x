"""tasks add task_type

Revision ID: 20260510_tasks_add_task_type
Revises: 20260510_notification_settings
Create Date: 2026-05-10 00:00:01.000000

"""

from alembic import op
import sqlalchemy as sa


revision = "20260510_tasks_add_task_type"
down_revision = "20260510_notification_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("task_type", sa.String(length=32), server_default="generic", nullable=False))


def downgrade() -> None:
    op.drop_column("tasks", "task_type")


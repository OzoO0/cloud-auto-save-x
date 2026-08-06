"""task scheduler settings

Revision ID: 20260510_task_scheduler_settings
Revises: 20260510_tasks_add_task_type
Create Date: 2026-05-10 00:00:02.000000

"""

from alembic import op
import sqlalchemy as sa


revision = "20260510_task_scheduler_settings"
down_revision = "20260510_tasks_add_task_type"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "task_scheduler_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="0", nullable=False),
        sa.Column("crontab", sa.String(length=64), server_default="0 */6 * * *", nullable=False),
        sa.Column("timezone", sa.String(length=64), server_default="Asia/Shanghai", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute("INSERT INTO task_scheduler_settings (id, enabled, crontab, timezone) VALUES (1, 0, '0 */6 * * *', 'Asia/Shanghai')")


def downgrade() -> None:
    op.drop_table("task_scheduler_settings")


"""notification settings remove enabled

Revision ID: 20260611_notification_settings_remove_enabled
Revises: 20260511_task_executions_add_run_log_and_stage
Create Date: 2026-06-11 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = "20260611_notification_settings_remove_enabled"
down_revision = "20260511_task_executions_add_run_log_and_stage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("notification_settings", schema=None) as batch_op:
        batch_op.drop_column("enabled")


def downgrade() -> None:
    with op.batch_alter_table("notification_settings", schema=None) as batch_op:
        batch_op.add_column(sa.Column("enabled", sa.Boolean(), server_default="0", nullable=False))


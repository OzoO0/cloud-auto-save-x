"""task scheduler default enable and cron

Revision ID: 20260614_task_scheduler_default_enable_and_cron
Revises: 20260613_drive_accounts_probe_fail_count
Create Date: 2026-06-14 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = "20260614_task_scheduler_default_enable_and_cron"
down_revision = "20260613_drive_accounts_probe_fail_count"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("task_scheduler_settings") as batch_op:
        batch_op.alter_column("enabled", existing_type=sa.Boolean(), server_default="1")
        batch_op.alter_column("crontab", existing_type=sa.String(length=64), server_default="0 */2 * * *")

    op.execute(
        """
        UPDATE task_scheduler_settings
        SET enabled = 1,
            crontab = '0 */2 * * *'
        WHERE id = 1
          AND enabled = 0
          AND crontab = '0 */6 * * *'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE task_scheduler_settings
        SET enabled = 0,
            crontab = '0 */6 * * *'
        WHERE id = 1
          AND enabled = 1
          AND crontab = '0 */2 * * *'
        """
    )

    with op.batch_alter_table("task_scheduler_settings") as batch_op:
        batch_op.alter_column("crontab", existing_type=sa.String(length=64), server_default="0 */6 * * *")
        batch_op.alter_column("enabled", existing_type=sa.Boolean(), server_default="0")

"""task executions add run_log stage

Revision ID: 20260511_task_executions_add_run_log_and_stage
Revises: 20260510_task_scheduler_settings
Create Date: 2026-05-11 00:00:01.000000

"""

from alembic import op
import sqlalchemy as sa


revision = "20260511_task_executions_add_run_log_and_stage"
down_revision = "20260510_task_scheduler_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("task_executions", sa.Column("stage", sa.String(length=64), nullable=True))
    op.add_column("task_executions", sa.Column("run_log", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("task_executions", "run_log")
    op.drop_column("task_executions", "stage")


"""drive accounts probe fail count

Revision ID: 20260613_drive_accounts_probe_fail_count
Revises: 20260612_magic_regex_rules
Create Date: 2026-06-13 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = "20260613_drive_accounts_probe_fail_count"
down_revision = "20260612_magic_regex_rules"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("drive_accounts", sa.Column("probe_fail_count", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("drive_accounts", "probe_fail_count")


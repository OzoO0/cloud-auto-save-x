"""magic regex rules

Revision ID: 20260612_magic_regex_rules
Revises: 20260611_notification_settings_remove_enabled
Create Date: 2026-06-12 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = "20260612_magic_regex_rules"
down_revision = "20260611_notification_settings_remove_enabled"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "magic_regex_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=128), nullable=True),
        sa.Column("pattern", sa.Text(), nullable=False, server_default=""),
        sa.Column("replace", sa.Text(), nullable=False, server_default=""),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_magic_regex_rules_key", "magic_regex_rules", ["key"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_magic_regex_rules_key", table_name="magic_regex_rules")
    op.drop_table("magic_regex_rules")

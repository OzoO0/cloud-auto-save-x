"""notification settings

Revision ID: 20260510_notification_settings
Revises: 3f2d8d9d1e11
Create Date: 2026-05-10 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = "20260510_notification_settings"
down_revision = "3f2d8d9d1e11"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notification_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="0", nullable=False),
        sa.Column("config_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute("INSERT INTO notification_settings (id, enabled, config_json) VALUES (1, 0, '{}')")


def downgrade() -> None:
    op.drop_table("notification_settings")


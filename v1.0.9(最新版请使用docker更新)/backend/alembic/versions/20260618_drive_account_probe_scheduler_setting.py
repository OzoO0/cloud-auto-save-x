"""drive account probe scheduler setting

Revision ID: 20260618_drive_account_probe_scheduler_setting
Revises: 20260617_tmdb_media_cache
Create Date: 2026-06-18 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260618_drive_account_probe_scheduler_setting"
down_revision = "20260617_tmdb_media_cache"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    if "drive_account_probe_scheduler_settings" not in tables:
        op.create_table(
            "drive_account_probe_scheduler_settings",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("enabled", sa.Boolean(), server_default="1", nullable=False),
            sa.Column("crontab", sa.String(length=64), server_default="0 4 * * *", nullable=False),
            sa.Column("timezone", sa.String(length=64), server_default="Asia/Shanghai", nullable=False),
            sa.Column("enabled_only", sa.Boolean(), server_default="1", nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.execute("INSERT INTO drive_account_probe_scheduler_settings (id) VALUES (1)")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    if "drive_account_probe_scheduler_settings" in tables:
        op.drop_table("drive_account_probe_scheduler_settings")


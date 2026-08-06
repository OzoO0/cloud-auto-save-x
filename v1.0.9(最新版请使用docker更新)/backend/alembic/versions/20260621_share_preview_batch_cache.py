"""share preview batch cache

Revision ID: 20260621_share_preview_batch_cache
Revises: 20260620_invalid_share_links
Create Date: 2026-06-21 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260621_share_preview_batch_cache"
down_revision = "20260620_invalid_share_links"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "share_preview_batch_cache" in inspector.get_table_names():
        return

    op.create_table(
        "share_preview_batch_cache",
        sa.Column("shareurl", sa.String(length=2048), primary_key=True, nullable=False),
        sa.Column("drive_type", sa.String(length=32), nullable=True),
        sa.Column("ok", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("hit_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_share_preview_batch_cache_drive_type", "share_preview_batch_cache", ["drive_type"])
    op.create_index("ix_share_preview_batch_cache_expires_at", "share_preview_batch_cache", ["expires_at"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "share_preview_batch_cache" not in inspector.get_table_names():
        return
    op.drop_index("ix_share_preview_batch_cache_expires_at", table_name="share_preview_batch_cache")
    op.drop_index("ix_share_preview_batch_cache_drive_type", table_name="share_preview_batch_cache")
    op.drop_table("share_preview_batch_cache")


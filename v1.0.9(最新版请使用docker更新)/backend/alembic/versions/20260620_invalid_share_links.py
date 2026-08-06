"""invalid share links

Revision ID: 20260620_invalid_share_links
Revises: 20260619_audit_read_permission
Create Date: 2026-06-20 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260620_invalid_share_links"
down_revision = "20260619_audit_read_permission"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "invalid_share_links" in inspector.get_table_names():
        return

    op.create_table(
        "invalid_share_links",
        sa.Column("shareurl", sa.String(length=2048), primary_key=True, nullable=False),
        sa.Column("drive_type", sa.String(length=32), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("hit_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_invalid_share_links_drive_type", "invalid_share_links", ["drive_type"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "invalid_share_links" not in inspector.get_table_names():
        return
    op.drop_index("ix_invalid_share_links_drive_type", table_name="invalid_share_links")
    op.drop_table("invalid_share_links")

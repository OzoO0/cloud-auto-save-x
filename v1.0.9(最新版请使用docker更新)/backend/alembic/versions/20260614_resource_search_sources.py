"""resource search sources

Revision ID: 20260614_resource_search_sources
Revises: 20260613_drive_accounts_probe_fail_count
Create Date: 2026-06-14 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260614_resource_search_sources"
down_revision = "20260613_drive_accounts_probe_fail_count"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "resource_search_sources" not in inspector.get_table_names():
        op.create_table(
            "resource_search_sources",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("key", sa.String(length=32), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default="1"),
            sa.Column("config_json", sa.Text(), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
    index_name = op.f("ix_resource_search_sources_key")
    existing_indexes = {idx.get("name") for idx in inspector.get_indexes("resource_search_sources")}
    if index_name not in existing_indexes:
        op.create_index(index_name, "resource_search_sources", ["key"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_resource_search_sources_key"), table_name="resource_search_sources")
    op.drop_table("resource_search_sources")

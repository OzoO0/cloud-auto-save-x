"""tmdb settings

Revision ID: 20260615_tmdb_settings
Revises: 20260512_tasks_add_shareurl_ban
Create Date: 2026-06-15 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260615_tmdb_settings"
down_revision = "20260512_tasks_add_shareurl_ban"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "tmdb_settings" not in inspector.get_table_names():
        op.create_table(
            "tmdb_settings",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("config_json", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.execute("INSERT INTO tmdb_settings (id, config_json) VALUES (1, '{}')")


def downgrade() -> None:
    op.drop_table("tmdb_settings")

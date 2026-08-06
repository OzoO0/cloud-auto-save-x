"""tasks add tmdb link

Revision ID: 20260616_tasks_add_tmdb_link
Revises: 20260615_tmdb_settings
Create Date: 2026-06-16 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260616_tasks_add_tmdb_link"
down_revision = "20260615_tmdb_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "tasks" not in inspector.get_table_names():
        return
    columns = {col.get("name") for col in inspector.get_columns("tasks")}
    if "tmdb_id" not in columns:
        op.add_column("tasks", sa.Column("tmdb_id", sa.Integer(), nullable=True))
    if "tmdb_media_type" not in columns:
        op.add_column("tasks", sa.Column("tmdb_media_type", sa.String(length=8), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "tasks" not in inspector.get_table_names():
        return
    columns = {col.get("name") for col in inspector.get_columns("tasks")}
    if "tmdb_media_type" in columns:
        op.drop_column("tasks", "tmdb_media_type")
    if "tmdb_id" in columns:
        op.drop_column("tasks", "tmdb_id")


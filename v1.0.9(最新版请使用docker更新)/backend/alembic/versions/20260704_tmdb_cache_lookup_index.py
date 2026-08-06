"""tmdb media cache lookup index

Revision ID: 20260704_tmdb_cache_lookup_index
Revises: 20260703_sync_task_locks
Create Date: 2026-07-04 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260704_tmdb_cache_lookup_index"
down_revision = "20260703_sync_task_locks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_indexes = set(tuple(idx) for idx in inspector.get_indexes("tmdb_media_cache"))
    index_name = "ix_tmdb_media_cache_lookup"

    columns = ["media_type", "tmdb_id", "language", "poster_language", "updated_at"]
    if (index_name, "tmdb_media_cache") not in existing_indexes:
        op.create_index(index_name, "tmdb_media_cache", columns, unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_indexes = set(idx["name"] for idx in inspector.get_indexes("tmdb_media_cache"))
    if "ix_tmdb_media_cache_lookup" in existing_indexes:
        op.drop_index("ix_tmdb_media_cache_lookup", table_name="tmdb_media_cache")

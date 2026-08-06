"""tmdb media cache

Revision ID: 20260617_tmdb_media_cache
Revises: 20260616_tasks_add_tmdb_link
Create Date: 2026-06-17 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260617_tmdb_media_cache"
down_revision = "20260616_tasks_add_tmdb_link"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    if "tmdb_media_cache" not in tables:
        op.create_table(
            "tmdb_media_cache",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("media_type", sa.String(length=8), nullable=False),
            sa.Column("tmdb_id", sa.Integer(), nullable=False),
            sa.Column("language", sa.String(length=16), server_default="zh-CN", nullable=False),
            sa.Column("poster_language", sa.String(length=16), server_default="zh-CN", nullable=False),
            sa.Column("payload_json", sa.Text(), nullable=True),
            sa.Column("update_weekdays_json", sa.Text(), nullable=True),
            sa.Column("display_title", sa.String(length=255), nullable=True),
            sa.Column("original_title", sa.String(length=255), nullable=True),
            sa.Column("year", sa.String(length=8), nullable=True),
            sa.Column("status", sa.String(length=64), nullable=True),
            sa.Column("first_air_date", sa.String(length=32), nullable=True),
            sa.Column("last_air_date", sa.String(length=32), nullable=True),
            sa.Column("release_date", sa.String(length=32), nullable=True),
            sa.Column("next_episode_air_date", sa.String(length=32), nullable=True),
            sa.Column("poster_path", sa.String(length=255), nullable=True),
            sa.Column("vote_average", sa.Float(), nullable=True),
            sa.Column("vote_count", sa.Integer(), nullable=True),
            sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_accessed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("refresh_in_progress", sa.Boolean(), server_default="0", nullable=False),
            sa.Column("refresh_started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("fail_count", sa.Integer(), server_default="0", nullable=False),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("media_type", "tmdb_id", "language", "poster_language", name="uq_tmdb_media_cache_key"),
        )
        op.create_index("ix_tmdb_media_cache_expires_at", "tmdb_media_cache", ["expires_at"], unique=False)
        op.create_index("ix_tmdb_media_cache_last_accessed_at", "tmdb_media_cache", ["last_accessed_at"], unique=False)
        op.create_index("ix_tmdb_media_cache_tmdb", "tmdb_media_cache", ["media_type", "tmdb_id"], unique=False)

    if "tmdb_cache_scheduler_settings" not in tables:
        op.create_table(
            "tmdb_cache_scheduler_settings",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("enabled", sa.Boolean(), server_default="1", nullable=False),
            sa.Column("crontab", sa.String(length=64), server_default="0 */6 * * *", nullable=False),
            sa.Column("timezone", sa.String(length=64), server_default="Asia/Shanghai", nullable=False),
            sa.Column("max_items_per_run", sa.Integer(), server_default="200", nullable=False),
            sa.Column("only_refresh_linked_tasks", sa.Boolean(), server_default="1", nullable=False),
            sa.Column("retention_days", sa.Integer(), server_default="60", nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.execute("INSERT INTO tmdb_cache_scheduler_settings (id) VALUES (1)")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())
    if "tmdb_cache_scheduler_settings" in tables:
        op.drop_table("tmdb_cache_scheduler_settings")
    if "tmdb_media_cache" in tables:
        op.drop_index("ix_tmdb_media_cache_tmdb", table_name="tmdb_media_cache")
        op.drop_index("ix_tmdb_media_cache_last_accessed_at", table_name="tmdb_media_cache")
        op.drop_index("ix_tmdb_media_cache_expires_at", table_name="tmdb_media_cache")
        op.drop_table("tmdb_media_cache")


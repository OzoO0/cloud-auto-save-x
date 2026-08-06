from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TMDBMediaCache(Base):
    __tablename__ = "tmdb_media_cache"
    __table_args__ = (
        UniqueConstraint("media_type", "tmdb_id", "language", "poster_language", name="uq_tmdb_media_cache_key"),
        Index("ix_tmdb_media_cache_expires_at", "expires_at"),
        Index("ix_tmdb_media_cache_last_accessed_at", "last_accessed_at"),
        Index("ix_tmdb_media_cache_tmdb", "media_type", "tmdb_id"),
        Index("ix_tmdb_media_cache_lookup", "media_type", "tmdb_id", "language", "poster_language", "updated_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    media_type: Mapped[str] = mapped_column(String(8), nullable=False)
    tmdb_id: Mapped[int] = mapped_column(Integer, nullable=False)
    language: Mapped[str] = mapped_column(String(16), nullable=False, server_default="zh-CN")
    poster_language: Mapped[str] = mapped_column(String(16), nullable=False, server_default="zh-CN")

    payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    update_weekdays_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    display_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    original_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    year: Mapped[str | None] = mapped_column(String(8), nullable=True)
    status: Mapped[str | None] = mapped_column(String(64), nullable=True)

    first_air_date: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_air_date: Mapped[str | None] = mapped_column(String(32), nullable=True)
    release_date: Mapped[str | None] = mapped_column(String(32), nullable=True)
    next_episode_air_date: Mapped[str | None] = mapped_column(String(32), nullable=True)

    poster_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    vote_average: Mapped[float | None] = mapped_column(Float, nullable=True)
    vote_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_accessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    refresh_in_progress: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="0")
    refresh_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    fail_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


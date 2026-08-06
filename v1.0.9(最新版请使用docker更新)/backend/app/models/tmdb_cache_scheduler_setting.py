from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TMDBCacheSchedulerSetting(Base):
    __tablename__ = "tmdb_cache_scheduler_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="1")
    crontab: Mapped[str] = mapped_column(String(64), nullable=False, server_default="0 */6 * * *")
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, server_default="Asia/Shanghai")

    max_items_per_run: Mapped[int] = mapped_column(Integer, nullable=False, server_default="200")
    only_refresh_linked_tasks: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="1")
    retention_days: Mapped[int] = mapped_column(Integer, nullable=False, server_default="60")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


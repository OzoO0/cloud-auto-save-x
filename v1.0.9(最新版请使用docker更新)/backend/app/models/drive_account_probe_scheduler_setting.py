from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DriveAccountProbeSchedulerSetting(Base):
    __tablename__ = "drive_account_probe_scheduler_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="1")
    crontab: Mapped[str] = mapped_column(String(64), nullable=False, server_default="0 4 * * *")
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, server_default="Asia/Shanghai")

    enabled_only: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="1")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


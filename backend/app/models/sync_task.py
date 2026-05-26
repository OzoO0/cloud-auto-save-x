from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class SyncTask(Base):
    __tablename__ = "sync_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    uid: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="1")

    source_type: Mapped[str] = mapped_column(String(16), nullable=False)
    source_path: Mapped[str] = mapped_column(Text, nullable=False)
    target_type: Mapped[str] = mapped_column(String(16), nullable=False)
    target_path: Mapped[str] = mapped_column(Text, nullable=False)

    mode: Mapped[str] = mapped_column(String(16), nullable=False, server_default="one_way")
    strategy_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    executions = relationship("SyncExecution", back_populates="sync_task", lazy="selectin", cascade="all, delete-orphan")
    snapshots = relationship("SyncFileSnapshot", back_populates="sync_task", lazy="selectin", cascade="all, delete-orphan")

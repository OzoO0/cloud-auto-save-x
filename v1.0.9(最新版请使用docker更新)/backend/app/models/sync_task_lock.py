from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SyncTaskLock(Base):
    __tablename__ = "sync_task_locks"

    sync_task_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("sync_tasks.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    locked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    owner: Mapped[str | None] = mapped_column(String(64), nullable=True)


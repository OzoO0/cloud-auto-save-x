from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SyncTaskDramaLink(Base):
    __tablename__ = "sync_task_drama_links"

    sync_task_uid: Mapped[str] = mapped_column(String(32), ForeignKey("sync_tasks.uid", ondelete="CASCADE"), primary_key=True)
    task_uid: Mapped[str] = mapped_column(String(64), ForeignKey("tasks.task_uid", ondelete="CASCADE"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


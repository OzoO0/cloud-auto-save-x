from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class SyncExecution(Base):
    __tablename__ = "sync_executions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sync_task_id: Mapped[int] = mapped_column(Integer, ForeignKey("sync_tasks.id", ondelete="CASCADE"), index=True, nullable=False)

    status: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    run_log: Mapped[str | None] = mapped_column(Text, nullable=True)
    stats_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    sync_task = relationship("SyncTask", back_populates="executions", lazy="selectin")

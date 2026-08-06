from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TaskSavepathSnapshot(Base):
    __tablename__ = "task_savepath_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_uid: Mapped[str] = mapped_column(String(64), ForeignKey("tasks.task_uid", ondelete="CASCADE"), nullable=False, unique=True)
    task_execution_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("task_executions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    drive_account_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("drive_accounts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    savepath: Mapped[str] = mapped_column(String(255), nullable=False)
    files_json: Mapped[str] = mapped_column(Text, nullable=False)
    file_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    total_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    saved_latest_season: Mapped[int | None] = mapped_column(Integer, nullable=True)
    saved_latest_episode: Mapped[int | None] = mapped_column(Integer, nullable=True)
    saved_latest_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

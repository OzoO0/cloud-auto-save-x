from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class SyncFileSnapshot(Base):
    __tablename__ = "sync_file_snapshots"
    __table_args__ = (UniqueConstraint("sync_task_id", "side", "rel_path", name="uq_sync_snapshot_task_side_path"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sync_task_id: Mapped[int] = mapped_column(Integer, ForeignKey("sync_tasks.id", ondelete="CASCADE"), index=True, nullable=False)
    side: Mapped[str] = mapped_column(String(16), nullable=False)
    rel_path: Mapped[str] = mapped_column(Text, nullable=False)

    is_dir: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="0")
    size: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    modified_at: Mapped[float] = mapped_column(Float, nullable=False, server_default="0")
    hash: Mapped[str | None] = mapped_column(String(128), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    sync_task = relationship("SyncTask", back_populates="snapshots", lazy="selectin")

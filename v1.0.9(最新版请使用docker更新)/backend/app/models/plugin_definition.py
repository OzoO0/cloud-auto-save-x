from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class PluginDefinition(Base):
    __tablename__ = "plugin_definitions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plugin_key: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    module_name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    source_type: Mapped[str] = mapped_column(String(16), nullable=False)
    version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    installed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="1")
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    config = relationship("PluginConfig", back_populates="definition", uselist=False, lazy="selectin")

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TelegramBotSession(Base):
    __tablename__ = "telegram_bot_sessions"
    __table_args__ = (UniqueConstraint("chat_id", "user_id", name="uq_telegram_bot_sessions_chat_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    scene: Mapped[str] = mapped_column(String(64), nullable=False, server_default="home")
    step: Mapped[str] = mapped_column(String(64), nullable=False, server_default="idle")
    context_json: Mapped[str] = mapped_column(Text, nullable=False, server_default="{}")
    last_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.telegram_bot_session import TelegramBotSession
from app.models.telegram_bot_state import TelegramBotState


DEFAULT_TELEGRAM_BOT_STATE_ID = 1


@dataclass
class TelegramSessionData:
    chat_id: int
    user_id: int
    scene: str
    step: str
    context: dict[str, Any]
    last_message_id: int | None


def _loads(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        payload = json.loads(value)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _dumps(value: dict[str, Any] | None) -> str:
    return json.dumps(value or {}, ensure_ascii=False)


def get_or_create_bot_state(db: Session) -> TelegramBotState:
    item = db.get(TelegramBotState, DEFAULT_TELEGRAM_BOT_STATE_ID)
    if item is not None:
        return item
    item = TelegramBotState(id=DEFAULT_TELEGRAM_BOT_STATE_ID, last_update_id=0)
    db.add(item)
    db.flush()
    return item


def get_last_update_id(db: Session) -> int:
    item = get_or_create_bot_state(db)
    return int(getattr(item, "last_update_id", 0) or 0)


def save_last_update_id(db: Session, update_id: int) -> TelegramBotState:
    item = get_or_create_bot_state(db)
    item.last_update_id = int(update_id)
    item.last_processed_at = datetime.now()
    db.flush()
    return item


def mark_polled(db: Session) -> TelegramBotState:
    item = get_or_create_bot_state(db)
    item.last_polled_at = datetime.now()
    item.last_error = None
    db.flush()
    return item


def mark_poll_error(db: Session, message: str) -> TelegramBotState:
    item = get_or_create_bot_state(db)
    item.last_error = str(message or "")[:1024] or None
    item.last_polled_at = datetime.now()
    db.flush()
    return item


def get_or_create_session(db: Session, *, chat_id: int, user_id: int) -> TelegramBotSession:
    row = (
        db.query(TelegramBotSession)
        .filter(TelegramBotSession.chat_id == int(chat_id), TelegramBotSession.user_id == int(user_id))
        .first()
    )
    if row is not None:
        return row
    row = TelegramBotSession(chat_id=int(chat_id), user_id=int(user_id), scene="home", step="idle", context_json="{}")
    db.add(row)
    db.flush()
    return row


def load_session_data(db: Session, *, chat_id: int, user_id: int) -> TelegramSessionData:
    row = get_or_create_session(db, chat_id=chat_id, user_id=user_id)
    return TelegramSessionData(
        chat_id=int(row.chat_id),
        user_id=int(row.user_id),
        scene=str(row.scene or "home"),
        step=str(row.step or "idle"),
        context=_loads(row.context_json),
        last_message_id=int(row.last_message_id) if row.last_message_id is not None else None,
    )


def save_session_data(
    db: Session,
    *,
    chat_id: int,
    user_id: int,
    scene: str | None = None,
    step: str | None = None,
    context: dict[str, Any] | None = None,
    last_message_id: int | None | object = None,
) -> TelegramBotSession:
    row = get_or_create_session(db, chat_id=chat_id, user_id=user_id)
    if scene is not None:
        row.scene = str(scene or "home")
    if step is not None:
        row.step = str(step or "idle")
    if context is not None:
        row.context_json = _dumps(context)
    if last_message_id is not None:
        row.last_message_id = int(last_message_id) if last_message_id else None
    db.flush()
    return row


def reset_session(
    db: Session,
    *,
    chat_id: int,
    user_id: int,
    scene: str = "home",
    step: str = "idle",
    preserve_message_id: bool = True,
) -> TelegramBotSession:
    row = get_or_create_session(db, chat_id=chat_id, user_id=user_id)
    last_message_id = row.last_message_id if preserve_message_id else None
    row.scene = scene
    row.step = step
    row.context_json = "{}"
    row.last_message_id = last_message_id
    db.flush()
    return row

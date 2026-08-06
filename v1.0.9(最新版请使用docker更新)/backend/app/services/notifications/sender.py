from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.services.notifications import legacy_notify
from app.services.notifications.settings import get_or_create_notification_setting, load_notification_config


def _get_channel_enabled_map(config: dict[str, Any]) -> dict[str, bool]:
    raw = (config or {}).get("__channel_enabled")
    if not isinstance(raw, dict):
        return {}
    result: dict[str, bool] = {}
    for key, value in raw.items():
        if isinstance(key, str):
            result[key] = bool(value)
    return result


def send_test(
    title: str,
    content: str,
    *,
    config: dict[str, Any],
    channels: list[str] | None = None,
) -> list[dict[str, Any]]:
    merged = dict(legacy_notify.DEFAULT_PUSH_CONFIG)
    merged.update(config or {})
    return legacy_notify.send(title, content, ignore_default_config=True, channels=channels, **merged)


def send_runtime(
    db: Session,
    title: str,
    content: str,
    *,
    channels: list[str] | None = None,
) -> list[dict[str, Any]]:
    if not content:
        return []
    item = get_or_create_notification_setting(db)
    config = load_notification_config(item)
    merged = dict(legacy_notify.DEFAULT_PUSH_CONFIG)
    merged.update(config or {})
    try:
        return legacy_notify.send(title, content, ignore_default_config=True, channels=channels, **merged)
    except Exception:
        return []

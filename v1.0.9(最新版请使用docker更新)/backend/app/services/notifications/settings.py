from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.models.notification_setting import NotificationSetting


DEFAULT_NOTIFICATION_SETTING_ID = 1


def get_or_create_notification_setting(db: Session) -> NotificationSetting:
    item = db.get(NotificationSetting, DEFAULT_NOTIFICATION_SETTING_ID)
    if item is not None:
        return item
    item = NotificationSetting(id=DEFAULT_NOTIFICATION_SETTING_ID, config_json=json.dumps({}, ensure_ascii=False))
    db.add(item)
    db.flush()
    return item


def load_notification_config(item: NotificationSetting) -> dict[str, Any]:
    if not item.config_json:
        return {}
    try:
        payload = json.loads(item.config_json)
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    payload.pop("CONSOLE", None)
    return payload


def get_runtime_notification_config(db: Session) -> dict[str, Any]:
    item = get_or_create_notification_setting(db)
    return load_notification_config(item)


def update_notification_setting(
    db: Session,
    *,
    config: dict[str, Any] | None = None,
) -> NotificationSetting:
    item = get_or_create_notification_setting(db)
    if config is not None:
        config.pop("CONSOLE", None)
        item.config_json = json.dumps(config, ensure_ascii=False)
    db.flush()
    return item

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class NotificationConfigUpdateIn(BaseModel):
    config: dict[str, Any] | None = None


class NotificationConfigOut(BaseModel):
    config: dict[str, Any]
    default_config: dict[str, Any]
    updated_at: datetime | None = None


class NotificationTestIn(BaseModel):
    title: str
    content: str
    channels: list[str] | None = None


class NotificationChannelResult(BaseModel):
    channel: str
    ok: bool
    error: str | None = None


class NotificationTestOut(BaseModel):
    results: list[NotificationChannelResult]

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class PluginUpdateIn(BaseModel):
    enabled: bool | None = None
    priority: int | None = Field(default=None, ge=0, le=9999)
    config: dict[str, Any] | None = None


class PluginOut(BaseModel):
    id: int
    plugin_key: str
    module_name: str
    source_type: str
    version: str | None = None
    installed: bool
    discovered_at: datetime
    enabled: bool
    priority: int
    runtime_status: str | None = None
    last_checked_at: datetime | None = None
    last_error: str | None = None
    config: dict[str, Any] = {}
    config_fields: list[dict[str, Any]] = []
    default_task_config: dict[str, Any] = {}
    task_config_fields: list[dict[str, Any]] = []

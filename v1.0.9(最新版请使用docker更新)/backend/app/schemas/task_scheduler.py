from __future__ import annotations

from pydantic import BaseModel, Field


class TaskSchedulerSettingOut(BaseModel):
    enabled: bool
    crontab: str
    timezone: str


class TaskSchedulerSettingUpdateIn(BaseModel):
    enabled: bool | None = None
    crontab: str | None = Field(default=None, max_length=64)
    timezone: str | None = Field(default=None, max_length=64)


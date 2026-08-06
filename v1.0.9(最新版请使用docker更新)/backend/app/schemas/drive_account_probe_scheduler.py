from __future__ import annotations

from pydantic import BaseModel, Field


class DriveAccountProbeSchedulerSettingOut(BaseModel):
    enabled: bool = True
    crontab: str = Field(default="0 4 * * *", max_length=64)
    timezone: str = Field(default="Asia/Shanghai", max_length=64)
    enabled_only: bool = True


class DriveAccountProbeSchedulerSettingUpdateIn(BaseModel):
    enabled: bool | None = None
    crontab: str | None = Field(default=None, max_length=64)
    timezone: str | None = Field(default=None, max_length=64)
    enabled_only: bool | None = None


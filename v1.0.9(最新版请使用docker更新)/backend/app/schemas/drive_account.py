from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class DriveAccountBase(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    drive_type: str = Field(min_length=1, max_length=64)
    cookie: str | None = None
    config: dict[str, Any] | None = None
    enabled: bool = True
    is_default: bool = False
    capacity_warning_threshold: int = Field(default=85, ge=1, le=100)


class DriveAccountCreateIn(DriveAccountBase):
    pass


class DriveAccountUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    cookie: str | None = None
    config: dict[str, Any] | None = None
    enabled: bool | None = None
    is_default: bool | None = None
    capacity_warning_threshold: int | None = Field(default=None, ge=1, le=100)


class DriveAccountStatusIn(BaseModel):
    enabled: bool


class DriveAccountOut(BaseModel):
    id: int
    name: str
    drive_type: str
    config: dict[str, Any] = {}
    profile: dict[str, Any] = {}
    enabled: bool
    is_default: bool
    capacity_warning_threshold: int
    used_space: int | None = None
    total_space: int | None = None
    usage_ratio: float | None = None
    runtime_status: str | None = None
    probe_fail_count: int = 0
    last_checked_at: datetime | None = None
    profile_updated_at: datetime | None = None
    last_error: str | None = None
    created_at: datetime
    updated_at: datetime


class DriveTypeOut(BaseModel):
    code: str
    drive_name: str
    class_name: str
    config_format: str = "raw"
    default_config: dict[str, Any] = {}
    config_fields: list[dict[str, Any]] = []

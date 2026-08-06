from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.schemas.task_scheduler import TaskSchedulerSettingOut


class CapacitySummaryOut(BaseModel):
    account_count: int
    enabled_account_count: int
    capacity_account_count: int
    warning_account_count: int
    total_used_space: int | None = None
    total_space: int | None = None
    usage_ratio: float | None = None


class CapacityAccountOut(BaseModel):
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
    last_checked_at: datetime | None = None
    profile_updated_at: datetime | None = None
    last_error: str | None = None
    created_at: datetime
    updated_at: datetime


class CapacityOverviewOut(BaseModel):
    summary: CapacitySummaryOut
    accounts: list[CapacityAccountOut]
    warning_accounts: list[CapacityAccountOut]
    unsupported_accounts: list[CapacityAccountOut]
    updated_at: datetime | None = None


class DramaSummaryOut(BaseModel):
    task_count: int
    enabled_task_count: int
    tmdb_bound_count: int
    banned_count: int
    unknown_schedule_count: int
    monthly_success_count: int
    window_days: int
    execution_total: int
    execution_success: int
    execution_failed: int
    execution_skipped: int
    success_rate: float | None = None
    avg_duration_s: float | None = None


class DramaTrendPointOut(BaseModel):
    date: str
    total: int
    success: int
    failed: int
    skipped: int
    avg_duration_s: float | None = None


class DramaFailureItemOut(BaseModel):
    task_id: int
    taskname: str
    status: str
    started_at: datetime
    stage: str | None = None
    message: str | None = None


class DramaOverviewOut(BaseModel):
    scheduler: TaskSchedulerSettingOut
    summary: DramaSummaryOut
    trend: list[DramaTrendPointOut]
    recent_failures: list[DramaFailureItemOut]
    updated_at: datetime | None = None

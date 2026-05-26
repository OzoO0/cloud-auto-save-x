from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


SyncEndpointType = Literal["local", "openlist"]
SyncMode = Literal["one_way", "two_way"]


class SyncEndpoint(BaseModel):
    type: SyncEndpointType
    path: str = Field(min_length=1)


class SyncStrategy(BaseModel):
    overwrite: bool = False
    one_way_delete_extras: bool = False
    force_refresh: bool = False
    concurrency: int = Field(default=4, ge=1, le=32)
    request_interval_seconds: float = Field(default=0.0, ge=0.0, le=5.0)
    openlist_copy_batch_size: int = Field(default=200, ge=1, le=5000)


class SyncTaskBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    enabled: bool = True
    source: SyncEndpoint
    target: SyncEndpoint
    mode: SyncMode = "one_way"
    strategy: SyncStrategy = Field(default_factory=SyncStrategy)
    drama_task_uids: list[str] = Field(default_factory=list)


class SyncTaskCreateIn(SyncTaskBase):
    pass


class SyncTaskUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    enabled: bool | None = None
    source: SyncEndpoint | None = None
    target: SyncEndpoint | None = None
    mode: SyncMode | None = None
    strategy: SyncStrategy | None = None
    drama_task_uids: list[str] | None = None


class SyncExecutionOut(BaseModel):
    id: int
    sync_task_id: int
    status: str
    started_at: datetime
    finished_at: datetime | None = None
    stage: str | None = None
    run_log: str | None = None
    stats: dict[str, Any] = {}
    message: str | None = None


class SyncTaskOut(BaseModel):
    id: int
    uid: str
    name: str
    enabled: bool
    source: SyncEndpoint
    target: SyncEndpoint
    mode: SyncMode
    strategy: SyncStrategy
    drama_task_uids: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class SyncRunIn(BaseModel):
    strategy: SyncStrategy | None = None

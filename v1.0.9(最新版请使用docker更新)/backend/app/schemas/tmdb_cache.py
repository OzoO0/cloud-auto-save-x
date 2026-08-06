from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class TMDBCacheStatusOut(BaseModel):
    configured: bool = False
    media_type: str = Field(default="", max_length=8)
    tmdb_id: int = 0
    exists: bool = False

    language: str | None = Field(default=None, max_length=16)
    poster_language: str | None = Field(default=None, max_length=16)

    display_title: str | None = Field(default=None, max_length=255)
    original_title: str | None = Field(default=None, max_length=255)
    year: str | None = Field(default=None, max_length=8)
    status: str | None = Field(default=None, max_length=64)

    fetched_at: datetime | None = None
    expires_at: datetime | None = None
    last_accessed_at: datetime | None = None

    refresh_in_progress: bool = False
    refresh_started_at: datetime | None = None

    fail_count: int = 0
    last_error: str | None = None


class TMDBCacheListItem(BaseModel):
    media_type: str = Field(default="", max_length=8)
    tmdb_id: int = 0
    language: str | None = Field(default=None, max_length=16)
    poster_language: str | None = Field(default=None, max_length=16)

    display_title: str | None = Field(default=None, max_length=255)
    original_title: str | None = Field(default=None, max_length=255)
    year: str | None = Field(default=None, max_length=8)
    status: str | None = Field(default=None, max_length=64)

    fetched_at: datetime | None = None
    expires_at: datetime | None = None
    last_accessed_at: datetime | None = None

    refresh_in_progress: bool = False
    fail_count: int = 0
    last_error: str | None = None


class TMDBCacheListOut(BaseModel):
    configured: bool = False
    page: int = 1
    page_size: int = 20
    total: int = 0
    items: list[TMDBCacheListItem] = []


class TMDBCacheItemOut(TMDBCacheStatusOut):
    payload_json: str | None = None
    update_weekdays: list[int] = []


class TMDBCacheRefreshIn(BaseModel):
    media_type: str = Field(..., max_length=8)
    tmdb_id: int = Field(..., ge=1)
    force: bool = True
    async_refresh: bool = False


class TMDBCacheRefreshOut(BaseModel):
    queued: bool = False
    status: TMDBCacheStatusOut


class TMDBCacheRefreshLinkedTasksIn(BaseModel):
    enabled_only: bool = True
    max_items: int = Field(default=200, ge=1, le=2000)
    force: bool = True


class TMDBCacheRefreshLinkedTasksOut(BaseModel):
    configured: bool = False
    targets: int = 0
    refreshed: int = 0


class TMDBCachePurgeIn(BaseModel):
    retention_days: int = Field(default=60, ge=1, le=3650)


class TMDBCachePurgeOut(BaseModel):
    deleted: int = 0


class TMDBCacheSetTTLIn(BaseModel):
    media_type: str = Field(..., max_length=8)
    tmdb_id: int = Field(..., ge=1)
    ttl_seconds: int = Field(..., ge=60, le=3650 * 24 * 60 * 60)


class TMDBCacheSetTTLOut(BaseModel):
    updated: bool = False
    status: TMDBCacheStatusOut


class TMDBCacheDeleteOut(BaseModel):
    deleted: int = 0


class TMDBCacheSchedulerSettingOut(BaseModel):
    enabled: bool = True
    crontab: str = Field(default="0 */6 * * *", max_length=64)
    timezone: str = Field(default="Asia/Shanghai", max_length=64)
    max_items_per_run: int = Field(default=200, ge=1, le=2000)
    only_refresh_linked_tasks: bool = True
    retention_days: int = Field(default=60, ge=1, le=3650)


class TMDBCacheSchedulerSettingUpdateIn(BaseModel):
    enabled: bool | None = None
    crontab: str | None = Field(default=None, max_length=64)
    timezone: str | None = Field(default=None, max_length=64)
    max_items_per_run: int | None = Field(default=None, ge=1, le=2000)
    only_refresh_linked_tasks: bool | None = None
    retention_days: int | None = Field(default=None, ge=1, le=3650)

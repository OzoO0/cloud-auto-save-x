from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class CacheDeleteOut(BaseModel):
    deleted: int = 0


class CachePurgeOut(BaseModel):
    deleted: int = 0


class CacheClearOut(BaseModel):
    cleared: bool = False


class SharePreviewBatchCachePurgeIn(BaseModel):
    expired_only: bool = True
    retention_seconds: int = Field(default=0, ge=0, le=3650 * 24 * 60 * 60)


class SharePreviewBatchCacheListItem(BaseModel):
    shareurl: str = Field(default="", max_length=2048)
    drive_type: str | None = Field(default=None, max_length=32)
    ok: bool = False
    message: str | None = None
    checked_at: datetime | None = None
    expires_at: datetime | None = None
    hit_count: int = 0
    updated_at: datetime | None = None


class SharePreviewBatchCacheListOut(BaseModel):
    page: int = 1
    page_size: int = 20
    total: int = 0
    items: list[SharePreviewBatchCacheListItem] = []


class InvalidShareLinkListItem(BaseModel):
    shareurl: str = Field(default="", max_length=2048)
    drive_type: str | None = Field(default=None, max_length=32)
    message: str | None = None
    hit_count: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None


class InvalidShareLinkListOut(BaseModel):
    page: int = 1
    page_size: int = 20
    total: int = 0
    items: list[InvalidShareLinkListItem] = []


class InvalidShareLinkClearIn(BaseModel):
    drive_type: str | None = Field(default=None, max_length=32)


class ProxyImageCacheStatsOut(BaseModel):
    enabled: bool = True
    cache_dir: str = Field(default="", max_length=2048)
    ttl_seconds: int = 0
    max_file_bytes: int = 0
    max_total_bytes: int = 0

    total_files: int = 0
    total_bytes: int = 0
    stale_files: int = 0


class ProxyImageCacheOperateOut(BaseModel):
    deleted_files: int = 0
    deleted_bytes: int = 0

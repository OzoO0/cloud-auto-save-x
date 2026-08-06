from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import require_permissions
from app.core.permissions import TASK_READ, TASK_WRITE
from app.core.settings import settings
from app.db.session import get_db
from app.schemas.cache_management import (
    CacheClearOut,
    CacheDeleteOut,
    CachePurgeOut,
    InvalidShareLinkClearIn,
    InvalidShareLinkListItem,
    InvalidShareLinkListOut,
    ProxyImageCacheOperateOut,
    ProxyImageCacheStatsOut,
    SharePreviewBatchCacheListItem,
    SharePreviewBatchCacheListOut,
    SharePreviewBatchCachePurgeIn,
)
from app.services.invalid_share_links import clear_invalid_share_links, delete_invalid_share_link, list_invalid_share_links
from app.services.proxy_image_cache import (
    ProxyImageCacheConfig,
    clear_proxy_image_cache,
    purge_expired_proxy_image_cache,
    resolve_proxy_image_cache_dir,
    scan_proxy_image_cache_stats,
)
from app.services.share_preview_batch import cache_clear as share_preview_batch_cache_clear
from app.services.share_preview_batch_cache import (
    delete_preview_batch_cache_item,
    list_preview_batch_cache,
    purge_expired_preview_batch_cache,
    purge_old_preview_batch_cache,
)


router = APIRouter()

_DISPLAY_TZ = ZoneInfo("Asia/Shanghai")


def _as_display_tz(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_DISPLAY_TZ)


def _proxy_image_cfg() -> ProxyImageCacheConfig:
    ttl = max(int(settings.media_proxy_image_cache_ttl_seconds or 0), 1)
    return ProxyImageCacheConfig(
        enabled=bool(settings.media_proxy_image_cache_enabled),
        cache_dir=resolve_proxy_image_cache_dir(database_url=settings.database_url, explicit_dir=settings.media_proxy_image_cache_dir),
        ttl_seconds=ttl,
        max_file_bytes=int(settings.media_proxy_image_cache_max_file_bytes or 0),
        max_total_bytes=int(settings.media_proxy_image_cache_max_total_bytes or 0),
    )


@router.get(
    "/share-preview-batch/list",
    response_model=SharePreviewBatchCacheListOut,
    dependencies=[Depends(require_permissions(TASK_READ))],
)
def get_share_preview_batch_cache_list(
    page: int = Query(1, ge=1, le=100000),
    page_size: int = Query(20, ge=1, le=200),
    q: str | None = Query(default=None, max_length=256),
    drive_type: str | None = Query(default=None, max_length=32),
    ok: bool | None = Query(default=None),
    expired_only: bool = Query(False),
    db: Session = Depends(get_db),
):
    rows, total = list_preview_batch_cache(
        db,
        page=page,
        page_size=page_size,
        q=q,
        drive_type=drive_type,
        ok=ok,
        expired_only=bool(expired_only),
    )
    items = [
        SharePreviewBatchCacheListItem(
            shareurl=r.shareurl,
            drive_type=r.drive_type,
            ok=bool(r.ok),
            message=r.message,
            checked_at=_as_display_tz(r.checked_at),
            expires_at=_as_display_tz(r.expires_at),
            hit_count=int(getattr(r, "hit_count", 0) or 0),
            updated_at=_as_display_tz(r.updated_at),
        )
        for r in rows
    ]
    return SharePreviewBatchCacheListOut(page=int(page), page_size=int(page_size), total=int(total), items=items)


@router.delete(
    "/share-preview-batch/item",
    response_model=CacheDeleteOut,
    dependencies=[Depends(require_permissions(TASK_WRITE))],
)
def delete_share_preview_batch_cache_item(
    shareurl: str = Query(..., min_length=8, max_length=2048),
    db: Session = Depends(get_db),
):
    deleted = delete_preview_batch_cache_item(db, shareurl=shareurl)
    db.commit()
    return CacheDeleteOut(deleted=int(deleted))


@router.post(
    "/share-preview-batch/purge",
    response_model=CachePurgeOut,
    dependencies=[Depends(require_permissions(TASK_WRITE))],
)
def post_share_preview_batch_cache_purge(
    payload: SharePreviewBatchCachePurgeIn = Body(...),
    db: Session = Depends(get_db),
):
    if bool(payload.expired_only):
        deleted = purge_expired_preview_batch_cache(db)
    else:
        retention = int(payload.retention_seconds or 0) or int(settings.tasks_share_preview_batch_db_cache_retention_seconds or 0) or 0
        deleted = purge_old_preview_batch_cache(db, retention_seconds=retention)
    db.commit()
    return CachePurgeOut(deleted=int(deleted))


@router.post(
    "/share-preview-batch/clear-memory",
    response_model=CacheClearOut,
    dependencies=[Depends(require_permissions(TASK_WRITE))],
)
def post_share_preview_batch_cache_clear_memory():
    share_preview_batch_cache_clear()
    return CacheClearOut(cleared=True)


@router.get(
    "/invalid-share-links/list",
    response_model=InvalidShareLinkListOut,
    dependencies=[Depends(require_permissions(TASK_READ))],
)
def get_invalid_share_links_list(
    page: int = Query(1, ge=1, le=100000),
    page_size: int = Query(20, ge=1, le=200),
    q: str | None = Query(default=None, max_length=256),
    drive_type: str | None = Query(default=None, max_length=32),
    db: Session = Depends(get_db),
):
    rows, total = list_invalid_share_links(db, page=page, page_size=page_size, q=q, drive_type=drive_type)
    items = [
        InvalidShareLinkListItem(
            shareurl=r.shareurl,
            drive_type=r.drive_type,
            message=r.message,
            hit_count=int(getattr(r, "hit_count", 0) or 0),
            created_at=_as_display_tz(r.created_at),
            updated_at=_as_display_tz(r.updated_at),
        )
        for r in rows
    ]
    return InvalidShareLinkListOut(page=int(page), page_size=int(page_size), total=int(total), items=items)


@router.delete(
    "/invalid-share-links/item",
    response_model=CacheDeleteOut,
    dependencies=[Depends(require_permissions(TASK_WRITE))],
)
def delete_invalid_share_links_item(
    shareurl: str = Query(..., min_length=8, max_length=2048),
    db: Session = Depends(get_db),
):
    deleted = delete_invalid_share_link(db, shareurl=shareurl)
    db.commit()
    return CacheDeleteOut(deleted=int(deleted))


@router.post(
    "/invalid-share-links/clear",
    response_model=CachePurgeOut,
    dependencies=[Depends(require_permissions(TASK_WRITE))],
)
def post_invalid_share_links_clear(
    payload: InvalidShareLinkClearIn = Body(...),
    db: Session = Depends(get_db),
):
    deleted = clear_invalid_share_links(db, drive_type=payload.drive_type)
    db.commit()
    return CachePurgeOut(deleted=int(deleted))


@router.get(
    "/proxy-image/stats",
    response_model=ProxyImageCacheStatsOut,
    dependencies=[Depends(require_permissions(TASK_READ))],
)
def get_proxy_image_cache_stats():
    cfg = _proxy_image_cfg()
    total_files, total_bytes, stale_files = scan_proxy_image_cache_stats(cfg=cfg)
    return ProxyImageCacheStatsOut(
        enabled=bool(cfg.enabled),
        cache_dir=str(cfg.cache_dir),
        ttl_seconds=int(cfg.ttl_seconds),
        max_file_bytes=int(cfg.max_file_bytes),
        max_total_bytes=int(cfg.max_total_bytes),
        total_files=int(total_files),
        total_bytes=int(total_bytes),
        stale_files=int(stale_files),
    )


@router.post(
    "/proxy-image/purge",
    response_model=ProxyImageCacheOperateOut,
    dependencies=[Depends(require_permissions(TASK_WRITE))],
)
def post_proxy_image_cache_purge():
    cfg = _proxy_image_cfg()
    deleted_files, deleted_bytes = purge_expired_proxy_image_cache(cfg=cfg)
    return ProxyImageCacheOperateOut(deleted_files=int(deleted_files), deleted_bytes=int(deleted_bytes))


@router.post(
    "/proxy-image/clear",
    response_model=ProxyImageCacheOperateOut,
    dependencies=[Depends(require_permissions(TASK_WRITE))],
)
def post_proxy_image_cache_clear():
    cfg = _proxy_image_cfg()
    deleted_files, deleted_bytes = clear_proxy_image_cache(cfg=cfg)
    return ProxyImageCacheOperateOut(deleted_files=int(deleted_files), deleted_bytes=int(deleted_bytes))

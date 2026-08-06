from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session
from zoneinfo import ZoneInfo

from app.core.deps import CurrentUser, get_current_user, require_permissions
from app.core.permissions import TASK_READ, TASK_WRITE
from app.db.session import get_db
from app.models.tmdb_media_cache import TMDBMediaCache
from app.schemas.tmdb_cache import (
    TMDBCacheDeleteOut,
    TMDBCacheItemOut,
    TMDBCacheListItem,
    TMDBCacheListOut,
    TMDBCachePurgeIn,
    TMDBCachePurgeOut,
    TMDBCacheRefreshIn,
    TMDBCacheRefreshLinkedTasksIn,
    TMDBCacheRefreshLinkedTasksOut,
    TMDBCacheRefreshOut,
    TMDBCacheSetTTLIn,
    TMDBCacheSetTTLOut,
    TMDBCacheSchedulerSettingOut,
    TMDBCacheSchedulerSettingUpdateIn,
    TMDBCacheStatusOut,
)
from app.services import audit
from app.services.tmdb_cache import (
    delete_cache_item,
    get_tmdb_detail_cached,
    list_cache,
    purge_cold_cache,
    refresh_linked_tasks,
    set_ttl_seconds,
    trigger_refresh_async,
)
from app.services.tmdb_cache_scheduler import get_or_create_tmdb_cache_scheduler_setting, update_tmdb_cache_scheduler_setting
from app.services.tmdb_settings import get_or_create_tmdb_setting, get_tmdb_runtime_config
from app.extensions.runtime.task_scheduler import task_scheduler_manager


router = APIRouter()


_DISPLAY_TZ = ZoneInfo("Asia/Shanghai")


def _as_display_tz(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_DISPLAY_TZ)


def _status_out(*, configured: bool, mt: str, tid: int, row: TMDBMediaCache | None) -> TMDBCacheStatusOut:
    if row is None:
        return TMDBCacheStatusOut(configured=configured, media_type=mt, tmdb_id=tid, exists=False)
    return TMDBCacheStatusOut(
        configured=configured,
        media_type=mt,
        tmdb_id=tid,
        exists=True,
        language=row.language,
        poster_language=row.poster_language,
        display_title=row.display_title,
        original_title=row.original_title,
        year=row.year,
        status=row.status,
        fetched_at=_as_display_tz(row.fetched_at),
        expires_at=_as_display_tz(row.expires_at),
        last_accessed_at=_as_display_tz(row.last_accessed_at),
        refresh_in_progress=bool(row.refresh_in_progress),
        refresh_started_at=_as_display_tz(row.refresh_started_at),
        fail_count=int(row.fail_count or 0),
        last_error=row.last_error,
    )


def _load_weekdays(value: str | None) -> list[int]:
    if not value:
        return []
    try:
        import json

        data = json.loads(value)
        if not isinstance(data, list):
            return []
        out: list[int] = []
        for x in data:
            try:
                n = int(x)
            except Exception:
                continue
            if 1 <= n <= 7:
                out.append(n)
        return out[:7]
    except Exception:
        return []


def _scheduler_out(setting) -> TMDBCacheSchedulerSettingOut:
    return TMDBCacheSchedulerSettingOut(
        enabled=bool(setting.enabled),
        crontab=str(setting.crontab),
        timezone=str(setting.timezone),
        max_items_per_run=int(setting.max_items_per_run or 200),
        only_refresh_linked_tasks=bool(setting.only_refresh_linked_tasks),
        retention_days=int(setting.retention_days or 60),
    )


@router.get("/cache/status", response_model=TMDBCacheStatusOut, dependencies=[Depends(require_permissions(TASK_READ))])
def get_tmdb_cache_status(
    media_type: str = Query(..., min_length=2, max_length=8),
    tmdb_id: int = Query(..., ge=1),
    db: Session = Depends(get_db),
):
    mt = str(media_type or "").strip().lower()
    if mt not in ("movie", "tv"):
        return TMDBCacheStatusOut(configured=False, media_type=mt or media_type, tmdb_id=tmdb_id, exists=False)

    setting = get_or_create_tmdb_setting(db)
    cfg = get_tmdb_runtime_config(setting)
    configured = bool(str(cfg.get("api_key") or "").strip())
    if not configured:
        return TMDBCacheStatusOut(configured=False, media_type=mt, tmdb_id=tmdb_id, exists=False)

    language = str(cfg.get("language") or "zh-CN").strip() or "zh-CN"
    poster_language = str(cfg.get("poster_language") or "zh-CN").strip() or "zh-CN"
    row = (
        db.execute(
            select(TMDBMediaCache).where(
                TMDBMediaCache.media_type == mt,
                TMDBMediaCache.tmdb_id == tmdb_id,
                TMDBMediaCache.language == language,
                TMDBMediaCache.poster_language == poster_language,
            )
        )
        .scalars()
        .first()
    )
    return _status_out(configured=configured, mt=mt, tid=tmdb_id, row=row)


@router.get("/cache/item", response_model=TMDBCacheItemOut, dependencies=[Depends(require_permissions(TASK_READ))])
def get_tmdb_cache_item(
    media_type: str = Query(..., min_length=2, max_length=8),
    tmdb_id: int = Query(..., ge=1),
    db: Session = Depends(get_db),
):
    mt = str(media_type or "").strip().lower()
    if mt not in ("movie", "tv"):
        return TMDBCacheItemOut(configured=False, media_type=mt or media_type, tmdb_id=tmdb_id, exists=False, payload_json=None, update_weekdays=[])

    setting = get_or_create_tmdb_setting(db)
    cfg = get_tmdb_runtime_config(setting)
    configured = bool(str(cfg.get("api_key") or "").strip())
    if not configured:
        return TMDBCacheItemOut(configured=False, media_type=mt, tmdb_id=tmdb_id, exists=False, payload_json=None, update_weekdays=[])

    language = str(cfg.get("language") or "zh-CN").strip() or "zh-CN"
    poster_language = str(cfg.get("poster_language") or "zh-CN").strip() or "zh-CN"
    row = (
        db.execute(
            select(TMDBMediaCache).where(
                TMDBMediaCache.media_type == mt,
                TMDBMediaCache.tmdb_id == tmdb_id,
                TMDBMediaCache.language == language,
                TMDBMediaCache.poster_language == poster_language,
            )
        )
        .scalars()
        .first()
    )

    if row is None:
        return TMDBCacheItemOut(configured=True, media_type=mt, tmdb_id=tmdb_id, exists=False, payload_json=None, update_weekdays=[])

    base = _status_out(configured=True, mt=mt, tid=tmdb_id, row=row)
    return TMDBCacheItemOut(**base.model_dump(), payload_json=row.payload_json, update_weekdays=_load_weekdays(row.update_weekdays_json))


@router.get("/cache/list", response_model=TMDBCacheListOut, dependencies=[Depends(require_permissions(TASK_READ))])
def get_tmdb_cache_list(
    page: int = Query(1, ge=1, le=100000),
    page_size: int = Query(20, ge=1, le=200),
    media_type: str | None = Query(default=None, max_length=8),
    q: str | None = Query(default=None, max_length=128),
    status: str | None = Query(default=None, max_length=64),
    expired_only: bool = Query(False),
    db: Session = Depends(get_db),
):
    configured, total, _language, _poster_language, rows = list_cache(
        db,
        page=page,
        page_size=page_size,
        media_type=media_type,
        q=q,
        status=status,
        expired_only=bool(expired_only),
    )
    items = [
        TMDBCacheListItem(
            media_type=r.media_type,
            tmdb_id=int(r.tmdb_id),
            language=r.language,
            poster_language=r.poster_language,
            display_title=r.display_title,
            original_title=r.original_title,
            year=r.year,
            status=r.status,
            fetched_at=_as_display_tz(r.fetched_at),
            expires_at=_as_display_tz(r.expires_at),
            last_accessed_at=_as_display_tz(r.last_accessed_at),
            refresh_in_progress=bool(r.refresh_in_progress),
            fail_count=int(r.fail_count or 0),
            last_error=r.last_error,
        )
        for r in rows
    ]
    return TMDBCacheListOut(configured=bool(configured), page=int(page), page_size=int(page_size), total=int(total), items=items)


@router.post("/cache/refresh", response_model=TMDBCacheRefreshOut, dependencies=[Depends(require_permissions(TASK_WRITE))])
def post_tmdb_cache_refresh(
    request: Request,
    payload: TMDBCacheRefreshIn,
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    mt = str(payload.media_type or "").strip().lower()
    if mt not in ("movie", "tv"):
        return TMDBCacheRefreshOut(queued=False, status=TMDBCacheStatusOut(configured=False, media_type=mt, tmdb_id=payload.tmdb_id, exists=False))

    setting = get_or_create_tmdb_setting(db)
    cfg = get_tmdb_runtime_config(setting)
    configured = bool(str(cfg.get("api_key") or "").strip())
    if not configured:
        return TMDBCacheRefreshOut(queued=False, status=TMDBCacheStatusOut(configured=False, media_type=mt, tmdb_id=payload.tmdb_id, exists=False))

    language = str(cfg.get("language") or "zh-CN").strip() or "zh-CN"
    poster_language = str(cfg.get("poster_language") or "zh-CN").strip() or "zh-CN"

    row = (
        db.execute(
            select(TMDBMediaCache).where(
                TMDBMediaCache.media_type == mt,
                TMDBMediaCache.tmdb_id == payload.tmdb_id,
                TMDBMediaCache.language == language,
                TMDBMediaCache.poster_language == poster_language,
            )
        )
        .scalars()
        .first()
    )

    queued = False
    if payload.async_refresh and row is not None:
        trigger_refresh_async(db, media_type=mt, tmdb_id=payload.tmdb_id, language=language, poster_language=poster_language)  # type: ignore[arg-type]
        queued = True
        db.commit()
        db.refresh(row)
    else:
        _, _data, _weekdays, _episode_weekdays, row = get_tmdb_detail_cached(
            db, media_type=mt, tmdb_id=payload.tmdb_id, force_refresh=bool(payload.force)  # type: ignore[arg-type]
        )
        db.commit()
        if row is not None:
            db.refresh(row)

    audit.write_audit_log(
        db,
        actor_user_id=current.user.id,
        action="tmdb.cache.refresh",
        target_type="tmdb_media_cache",
        target_id=f"{mt}:{payload.tmdb_id}",
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        success=True,
        detail=f"force={bool(payload.force)} async={bool(payload.async_refresh)}",
    )
    db.commit()

    return TMDBCacheRefreshOut(queued=queued, status=_status_out(configured=configured, mt=mt, tid=payload.tmdb_id, row=row))


@router.post("/cache/set-ttl", response_model=TMDBCacheSetTTLOut, dependencies=[Depends(require_permissions(TASK_WRITE))])
def post_tmdb_cache_set_ttl(
    request: Request,
    payload: TMDBCacheSetTTLIn,
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    mt = str(payload.media_type or "").strip().lower()
    if mt not in ("movie", "tv"):
        return TMDBCacheSetTTLOut(updated=False, status=TMDBCacheStatusOut(configured=False, media_type=mt, tmdb_id=payload.tmdb_id, exists=False))

    configured, row = set_ttl_seconds(db, media_type=mt, tmdb_id=int(payload.tmdb_id), ttl_seconds=int(payload.ttl_seconds))  # type: ignore[arg-type]
    audit.write_audit_log(
        db,
        actor_user_id=current.user.id,
        action="tmdb.cache.set_ttl",
        target_type="tmdb_media_cache",
        target_id=f"{mt}:{int(payload.tmdb_id)}",
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        success=True,
        detail=f"ttl_seconds={int(payload.ttl_seconds)}",
    )
    db.commit()
    if row is not None:
        db.refresh(row)
    return TMDBCacheSetTTLOut(updated=row is not None, status=_status_out(configured=bool(configured), mt=mt, tid=int(payload.tmdb_id), row=row))


@router.delete("/cache/item", response_model=TMDBCacheDeleteOut, dependencies=[Depends(require_permissions(TASK_WRITE))])
def delete_tmdb_cache_item(
    request: Request,
    media_type: str = Query(..., min_length=2, max_length=8),
    tmdb_id: int = Query(..., ge=1),
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    mt = str(media_type or "").strip().lower()
    if mt not in ("movie", "tv"):
        return TMDBCacheDeleteOut(deleted=0)

    configured, deleted = delete_cache_item(db, media_type=mt, tmdb_id=int(tmdb_id))  # type: ignore[arg-type]
    audit.write_audit_log(
        db,
        actor_user_id=current.user.id,
        action="tmdb.cache.delete",
        target_type="tmdb_media_cache",
        target_id=f"{mt}:{int(tmdb_id)}",
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        success=True,
        detail=f"deleted={int(deleted)} configured={bool(configured)}",
    )
    db.commit()
    return TMDBCacheDeleteOut(deleted=int(deleted))

@router.post(
    "/cache/refresh-linked-tasks",
    response_model=TMDBCacheRefreshLinkedTasksOut,
    dependencies=[Depends(require_permissions(TASK_WRITE))],
)
def post_tmdb_cache_refresh_linked_tasks(
    request: Request,
    payload: TMDBCacheRefreshLinkedTasksIn,
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    result = refresh_linked_tasks(db, enabled_only=bool(payload.enabled_only), max_items=int(payload.max_items), force=bool(payload.force))
    audit.write_audit_log(
        db,
        actor_user_id=current.user.id,
        action="tmdb.cache.refresh_linked_tasks",
        target_type="tmdb_media_cache",
        target_id=None,
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        success=True,
        detail=_safe_json(result),
    )
    db.commit()
    return TMDBCacheRefreshLinkedTasksOut(configured=bool(result.get("configured")), targets=int(result.get("targets") or 0), refreshed=int(result.get("refreshed") or 0))


@router.post("/cache/purge", response_model=TMDBCachePurgeOut, dependencies=[Depends(require_permissions(TASK_WRITE))])
def post_tmdb_cache_purge(
    request: Request,
    payload: TMDBCachePurgeIn,
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    deleted = purge_cold_cache(db, retention_days=int(payload.retention_days))
    audit.write_audit_log(
        db,
        actor_user_id=current.user.id,
        action="tmdb.cache.purge",
        target_type="tmdb_media_cache",
        target_id=None,
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        success=True,
        detail=f"retention_days={int(payload.retention_days)} deleted={int(deleted)}",
    )
    db.commit()
    return TMDBCachePurgeOut(deleted=int(deleted))


@router.get(
    "/cache/scheduler",
    response_model=TMDBCacheSchedulerSettingOut,
    dependencies=[Depends(require_permissions(TASK_READ))],
)
def get_tmdb_cache_scheduler_setting(db: Session = Depends(get_db)):
    setting = get_or_create_tmdb_cache_scheduler_setting(db)
    db.commit()
    db.refresh(setting)
    return _scheduler_out(setting)


@router.patch(
    "/cache/scheduler",
    response_model=TMDBCacheSchedulerSettingOut,
    dependencies=[Depends(require_permissions(TASK_WRITE))],
)
def patch_tmdb_cache_scheduler_setting(
    request: Request,
    payload: TMDBCacheSchedulerSettingUpdateIn,
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    setting = update_tmdb_cache_scheduler_setting(db, **payload.model_dump(exclude_unset=True))
    audit.write_audit_log(
        db,
        actor_user_id=current.user.id,
        action="tmdb.cache.scheduler.update",
        target_type="tmdb_cache_scheduler_setting",
        target_id=str(setting.id),
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        success=True,
    )
    db.commit()
    db.refresh(setting)
    task_scheduler_manager.reload()
    return _scheduler_out(setting)


def _safe_json(data: object) -> str:
    try:
        import json

        return json.dumps(data, ensure_ascii=False)
    except Exception:
        return str(data)

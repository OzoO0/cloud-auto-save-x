import json
import os
import queue
import threading
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
import re
from sqlalchemy import and_, func, or_, select, update as sa_update
from sqlalchemy.orm import Session

from app.core.deps import CurrentUser, get_current_user, require_permissions
from app.core.errors import bad_request, not_found
from app.core.permissions import TASK_READ, TASK_RUN, TASK_WRITE
from app.core.settings import settings
from app.db.session import get_db
from app.db.session import SessionLocal
from app.extensions.runtime.adapter_registry import AdapterRegistry
from app.extensions.runtime.account_manager import DatabaseAccountManager
from app.extensions.runtime.execution_log import ExecutionLog
from app.extensions.runtime.magic_rename import MagicRename
from app.models.drive_account import DriveAccount
from app.models.task import Task
from app.models.task_savepath_snapshot import TaskSavepathSnapshot
from app.models.tmdb_media_cache import TMDBMediaCache
from app.extensions.runtime.task_scheduler import task_scheduler_manager
from app.extensions.runtime.task_executor import TaskExecutor
from app.schemas.task_browse import (
    DriveBrowseIn,
    DriveBrowseItemOut,
    DriveBrowseOut,
    DriveBrowsePathOut,
    DriveMkdirIn,
    DriveMkdirOut,
    SharePreviewBatchIn,
    SharePreviewBatchItemOut,
    SharePreviewBatchOut,
    SharePreviewIn,
    SharePreviewItemOut,
    SharePreviewOut,
)
from app.schemas.task_magic_regex import MagicRegexOut, MagicRegexRuleOut
from app.schemas.task_scheduler import TaskSchedulerSettingOut, TaskSchedulerSettingUpdateIn
from app.schemas.task import (
    SavepathSnapshotSyncItemOut,
    SavepathSnapshotSyncOut,
    StopCompletedDramaTasksOut,
    TaskCreateIn,
    TaskExecutionOut,
    TaskOut,
    TaskStatusIn,
    TaskUpdateIn,
)
from app.schemas.resource_search import TaskSuggestionListOut
from app.schemas.task_repair import RepairBannedTasksOut
from app.services import audit
from app.services.notifications.sender import send_runtime
from app.services.notifications.task_notify import DRAMA_NOTIFY_TITLE, build_task_section
from app.services.sync_task_triggers import should_trigger_linked_sync_for_drama_execution, trigger_linked_sync_tasks_async
from app.services.share_preview_batch import cache_clear as _preview_batch_cache_clear
from app.services.share_preview_batch import preview_share_batch
from app.services.drama_update_progress import build_drama_update_progress
from app.services.drama_share_repair import repair_banned_drama_tasks
from app.services.task_scheduler import get_or_create_task_scheduler_setting, update_task_scheduler_setting
from app.services.resource_search import fetch_task_suggestions
from app.services.tasks import create_task, delete_task, get_task, list_tasks_recent_executions, set_task_enabled, update_task
from app.services.tmdb_settings import get_or_create_tmdb_setting, get_tmdb_runtime_config

router = APIRouter()
def _share_preview_batch_cache_clear() -> None:
    _preview_batch_cache_clear()


def _execution_out(item) -> TaskExecutionOut:
    return TaskExecutionOut(
        id=item.id,
        task_id=item.task_id,
        status=item.status,
        started_at=item.started_at,
        finished_at=item.finished_at,
        tree_summary=item.tree_summary,
        message=item.message,
        stage=getattr(item, "stage", None),
        run_log=getattr(item, "run_log", None),
        adapter_snapshot=json.loads(item.adapter_snapshot) if item.adapter_snapshot else {},
        plugins_snapshot=json.loads(item.plugins_snapshot) if item.plugins_snapshot else [],
    )


def _tmdb_lang_pair(db: Session) -> tuple[str, str]:
    cfg = get_tmdb_runtime_config(get_or_create_tmdb_setting(db))
    language = str(cfg.get("language") or "zh-CN").strip() or "zh-CN"
    poster_language = str(cfg.get("poster_language") or "zh-CN").strip() or "zh-CN"
    return language, poster_language


def _tmdb_cache_key(item) -> tuple[str, int] | None:
    tmdb_id = getattr(item, "tmdb_id", None)
    if tmdb_id is None:
        return None
    try:
        tid = int(tmdb_id)
    except Exception:
        return None
    if tid <= 0:
        return None
    mt = str(getattr(item, "tmdb_media_type", None) or "").strip().lower()
    if mt not in ("movie", "tv"):
        return None
    return mt, tid


def _load_tmdb_status_map(db: Session, items: list[object]) -> dict[tuple[str, int], str | None]:
    keys: list[tuple[str, int]] = []
    seen: set[tuple[str, int]] = set()
    for item in items:
        key = _tmdb_cache_key(item)
        if key is None or key in seen:
            continue
        seen.add(key)
        keys.append(key)
    if not keys:
        return {}

    language, poster_language = _tmdb_lang_pair(db)
    tv_ids = [tid for mt, tid in keys if mt == "tv"]
    movie_ids = [tid for mt, tid in keys if mt == "movie"]
    conds = []
    if tv_ids:
        conds.append(and_(TMDBMediaCache.media_type == "tv", TMDBMediaCache.tmdb_id.in_(tv_ids)))
    if movie_ids:
        conds.append(and_(TMDBMediaCache.media_type == "movie", TMDBMediaCache.tmdb_id.in_(movie_ids)))
    if not conds:
        return {}

    rows = (
        db.execute(
            select(TMDBMediaCache.media_type, TMDBMediaCache.tmdb_id, TMDBMediaCache.status)
            .where(TMDBMediaCache.language == language, TMDBMediaCache.poster_language == poster_language, or_(*conds))
            .order_by(TMDBMediaCache.updated_at.desc())
        )
        .all()
    )
    out: dict[tuple[str, int], str | None] = {}
    for mt, tid, status in rows:
        key = (str(mt or "").strip().lower(), int(tid))
        if key not in out:
            out[key] = str(status or "").strip() or None
    return out


def _load_tmdb_payload_map(db: Session, items: list[object]) -> dict[tuple[str, int], dict[str, object] | None]:
    keys: list[tuple[str, int]] = []
    seen: set[tuple[str, int]] = set()
    for item in items:
        if str(getattr(item, "task_type", "") or "") != "drama":
            continue
        key = _tmdb_cache_key(item)
        if key is None or key in seen:
            continue
        if key[0] != "tv":
            continue
        seen.add(key)
        keys.append(key)
    if not keys:
        return {}

    language, poster_language = _tmdb_lang_pair(db)
    tv_ids = [tid for mt, tid in keys if mt == "tv"]
    if not tv_ids:
        return {}

    rows = (
        db.execute(
            select(TMDBMediaCache.media_type, TMDBMediaCache.tmdb_id, TMDBMediaCache.payload_json)
            .where(
                TMDBMediaCache.media_type == "tv",
                TMDBMediaCache.tmdb_id.in_(tv_ids),
                TMDBMediaCache.language == language,
                TMDBMediaCache.poster_language == poster_language,
            )
            .order_by(TMDBMediaCache.updated_at.desc())
        )
        .all()
    )
    out: dict[tuple[str, int], dict[str, object] | None] = {}
    for mt, tid, payload in rows:
        key = (str(mt or "").strip().lower(), int(tid))
        if key in out:
            continue
        if not payload:
            out[key] = None
            continue
        try:
            parsed = json.loads(payload)
        except Exception:
            parsed = None
        out[key] = parsed if isinstance(parsed, dict) else None
    return out


def _load_savepath_snapshot_map(db: Session, items: list[object]) -> dict[str, TaskSavepathSnapshot]:
    task_uids: list[str] = []
    seen: set[str] = set()
    for item in items:
        if str(getattr(item, "task_type", "") or "") != "drama":
            continue
        uid = str(getattr(item, "task_uid", "") or "").strip()
        if not uid or uid in seen:
            continue
        seen.add(uid)
        task_uids.append(uid)
    if not task_uids:
        return {}
    try:
        rows = (
            db.execute(select(TaskSavepathSnapshot).where(TaskSavepathSnapshot.task_uid.in_(task_uids)))
            .scalars()
            .all()
        )
    except Exception:
        return {}
    return {str(r.task_uid): r for r in rows if getattr(r, "task_uid", None)}


def _get_tmdb_status(db: Session, mt: str, tid: int) -> str | None:
    language, poster_language = _tmdb_lang_pair(db)
    row = (
        db.execute(
            select(TMDBMediaCache.status)
            .where(
                TMDBMediaCache.media_type == mt,
                TMDBMediaCache.tmdb_id == tid,
                TMDBMediaCache.language == language,
                TMDBMediaCache.poster_language == poster_language,
            )
            .order_by(TMDBMediaCache.updated_at.desc())
            .limit(1)
        )
        .first()
    )
    if row is None:
        return None
    status = str(row[0] or "").strip()
    return status or None


def _task_out(
    db: Session,
    item,
    *,
    tmdb_status_map: dict[tuple[str, int], str | None] | None = None,
    tmdb_payload_map: dict[tuple[str, int], dict[str, object] | None] | None = None,
    snapshot_map: dict[str, TaskSavepathSnapshot] | None = None,
) -> TaskOut:
    raw_executions = list(getattr(item, "executions", None) or [])
    raw_executions.sort(key=lambda x: x.started_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)

    tmdb_status: str | None = None
    tmdb_is_ended: bool | None = None
    drama_update_progress = None
    key = _tmdb_cache_key(item)
    if key is not None:
        tmdb_status = tmdb_status_map.get(key) if isinstance(tmdb_status_map, dict) else _get_tmdb_status(db, key[0], key[1])
        if key[0] == "tv" and tmdb_status is not None:
            tmdb_is_ended = tmdb_status in ("Ended", "Canceled")
        if (
            key[0] == "tv"
            and str(getattr(item, "task_type", "") or "") == "drama"
            and isinstance(tmdb_payload_map, dict)
            and isinstance(snapshot_map, dict)
        ):
            drama_update_progress = build_drama_update_progress(
                tmdb_details=tmdb_payload_map.get(key),
                snapshot=snapshot_map.get(str(getattr(item, "task_uid", "") or "").strip()),
            )

    return TaskOut(
        id=item.id,
        task_uid=item.task_uid,
        task_type=item.task_type,
        taskname=item.taskname,
        shareurl=item.shareurl,
        savepath=item.savepath,
        pattern=item.pattern,
        replace=item.replace,
        enddate=item.enddate,
        ignore_extension=item.ignore_extension,
        sort_index=item.sort_index,
        startfid=item.startfid,
        account_name=item.account_name,
        update_subdir=item.update_subdir,
        shareurl_ban=getattr(item, "shareurl_ban", None),
        tmdb_id=getattr(item, "tmdb_id", None),
        tmdb_media_type=getattr(item, "tmdb_media_type", None),
        tmdb_status=tmdb_status,
        tmdb_is_ended=tmdb_is_ended,
        drama_update_progress=drama_update_progress,
        enabled=item.enabled,
        addition=json.loads(item.addition_json) if item.addition_json else {},
        extra=json.loads(item.extra_json) if item.extra_json else {},
        executions=[_execution_out(x) for x in raw_executions[:3]],
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _scheduler_out(item) -> TaskSchedulerSettingOut:
    return TaskSchedulerSettingOut(enabled=item.enabled, crontab=item.crontab, timezone=item.timezone)


def _pick_default_account_name(db: Session, drive_type: str) -> str | None:
    active = (
        db.execute(
            select(DriveAccount)
            .where(DriveAccount.enabled.is_(True), DriveAccount.drive_type == drive_type, DriveAccount.runtime_status == "active")
            .order_by(DriveAccount.is_default.desc(), DriveAccount.id.asc())
        )
        .scalars()
        .first()
    )
    if active is not None:
        return active.name
    fallback = (
        db.execute(
            select(DriveAccount)
            .where(DriveAccount.enabled.is_(True), DriveAccount.drive_type == drive_type)
            .order_by(DriveAccount.is_default.desc(), DriveAccount.id.asc())
        )
        .scalars()
        .first()
    )
    return None if fallback is None else fallback.name


def _pick_any_default_account(db: Session) -> DriveAccount | None:
    active = (
        db.execute(
            select(DriveAccount)
            .where(DriveAccount.enabled.is_(True), DriveAccount.runtime_status == "active")
            .order_by(DriveAccount.is_default.desc(), DriveAccount.id.asc())
        )
        .scalars()
        .first()
    )
    if active is not None:
        return active
    return (
        db.execute(select(DriveAccount).where(DriveAccount.enabled.is_(True)).order_by(DriveAccount.is_default.desc(), DriveAccount.id.asc()))
        .scalars()
        .first()
    )


def _get_active_account(db: Session, account_name: str) -> DriveAccount | None:
    name = str(account_name or "").strip()
    if not name:
        return None
    active = (
        db.execute(
            select(DriveAccount).where(
                DriveAccount.enabled.is_(True),
                DriveAccount.name == name,
                DriveAccount.runtime_status == "active",
            )
        )
        .scalars()
        .first()
    )
    if active is not None:
        return active
    return (
        db.execute(select(DriveAccount).where(DriveAccount.enabled.is_(True), DriveAccount.name == name))
        .scalars()
        .first()
    )


@router.get('/magic-regex', response_model=MagicRegexOut, dependencies=[Depends(require_permissions(TASK_READ))])
def list_magic_regex(db: Session = Depends(get_db)) -> MagicRegexOut:
    from app.services.magic_regex import list_enabled_effective_rules_for_picker

    rules = [
        MagicRegexRuleOut(key=item["key"], label=item.get("label"), pattern=item.get("pattern") or "", replace=item.get("replace") or "")
        for item in list_enabled_effective_rules_for_picker(db)
    ]
    return MagicRegexOut(rules=rules)


@router.get("/suggestions", response_model=TaskSuggestionListOut, dependencies=[Depends(require_permissions(TASK_READ))])
def get_task_suggestions(q: str = "", d: int = 0, drive_type: str = "", db: Session = Depends(get_db)) -> TaskSuggestionListOut:
    try:
        dt = str(drive_type or "").strip() or None
        items, changed, msg = fetch_task_suggestions(db, keyword=q, deep=d, drive_type=dt)
        if changed:
            db.commit()
        return TaskSuggestionListOut(success=True, data=items, message=msg)
    except Exception as e:
        return TaskSuggestionListOut(success=True, message=f"error: {str(e)}", data=[])


def _bool_is_dir(payload: dict) -> bool:
    if payload.get("is_dir") is not None:
        return bool(payload.get("is_dir"))
    if payload.get("isdir") is not None:
        return str(payload.get("isdir")) in ("1", "true", "True")
    if payload.get("dir") is not None:
        return bool(payload.get("dir"))
    if payload.get("kind") in ("folder", "dir", "directory"):
        return True
    if payload.get("kind") in ("file",):
        return False
    if payload.get("type") in ("folder", "dir"):
        return True
    if payload.get("type") in ("file",):
        return False
    if payload.get("file_type") is not None:
        value = str(payload.get("file_type"))
        if value in ("0", "dir", "folder"):
            return True
        if value in ("1", "file"):
            return False
    return False


def _pick_name(payload: dict) -> str:
    return str(
        payload.get("file_name")
        or payload.get("server_filename")
        or payload.get("fileName")
        or payload.get("name")
        or payload.get("title")
        or payload.get("fid")
        or payload.get("fs_id")
        or ""
    )


def _pick_fid(payload: dict) -> str:
    return str(payload.get("fid") or payload.get("fs_id") or payload.get("file_id") or payload.get("id") or payload.get("fileId") or "")


def _pick_fid_token(payload: dict) -> str | None:
    value = payload.get("fid_token") or payload.get("share_fid_token") or payload.get("token")
    if value is None:
        return None
    return str(value)


def _pick_updated_at(payload: dict):
    return payload.get("updated_at") or payload.get("update_time") or payload.get("mtime") or payload.get("modified_at")


def _pick_size(payload: dict) -> int | None:
    if payload.get("size") is None:
        return None
    try:
        return int(payload.get("size"))
    except (TypeError, ValueError):
        return None


def _pick_children_count(payload: dict) -> int | None:
    if payload.get("include_items") is not None:
        try:
            return int(payload.get("include_items"))
        except (TypeError, ValueError):
            pass
    for key in ("children_count", "child_count", "child_cnt", "count", "cnt", "total"):
        if payload.get(key) is not None:
            try:
                return int(payload.get(key))
            except (TypeError, ValueError):
                pass
    file_count = None
    dir_count = None
    for key in ("file_count", "file_cnt", "files", "fileCount", "fileCnt", "sub_file_cnt", "subFileCount"):
        if payload.get(key) is not None:
            try:
                file_count = int(payload.get(key))
                break
            except (TypeError, ValueError):
                pass
    for key in ("dir_count", "dir_cnt", "dirs", "dirCount", "dirCnt", "sub_dir_cnt", "subDirCount"):
        if payload.get(key) is not None:
            try:
                dir_count = int(payload.get(key))
                break
            except (TypeError, ValueError):
                pass
    if file_count is None and dir_count is None:
        return None
    return int((file_count or 0) + (dir_count or 0))


@router.get('', response_model=list[TaskOut], dependencies=[Depends(require_permissions(TASK_READ))])
def get_tasks(db: Session = Depends(get_db)):
    items = list_tasks_recent_executions(db, limit=3)
    tmdb_status_map = _load_tmdb_status_map(db, items)
    tmdb_payload_map = _load_tmdb_payload_map(db, items)
    snapshot_map = _load_savepath_snapshot_map(db, items)
    return [
        _task_out(
            db,
            item,
            tmdb_status_map=tmdb_status_map,
            tmdb_payload_map=tmdb_payload_map,
            snapshot_map=snapshot_map,
        )
        for item in items
    ]


@router.post("/drama/stop-completed", response_model=StopCompletedDramaTasksOut, dependencies=[Depends(require_permissions(TASK_WRITE))])
def post_stop_completed_drama_tasks(request: Request, current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    language, poster_language = _tmdb_lang_pair(db)

    checked = (
        db.execute(
            select(func.count(Task.id)).where(
                Task.task_type == "drama",
                Task.enabled.is_(True),
                Task.tmdb_id.is_not(None),
                Task.tmdb_media_type == "tv",
            )
        )
        .scalar_one()
    )
    ended_statuses = ["Ended", "Canceled"]
    matched_ids = (
        db.execute(
            select(Task.id)
            .join(
                TMDBMediaCache,
                and_(
                    TMDBMediaCache.media_type == Task.tmdb_media_type,
                    TMDBMediaCache.tmdb_id == Task.tmdb_id,
                    TMDBMediaCache.language == language,
                    TMDBMediaCache.poster_language == poster_language,
                ),
            )
            .where(
                Task.task_type == "drama",
                Task.enabled.is_(True),
                Task.tmdb_id.is_not(None),
                Task.tmdb_media_type == "tv",
                TMDBMediaCache.status.in_(ended_statuses),
            )
            .order_by(Task.id.desc())
        )
        .scalars()
        .all()
    )

    stopped = 0
    if matched_ids:
        db.execute(sa_update(Task).where(Task.id.in_(matched_ids)).values(enabled=False))
        stopped = len(matched_ids)

    audit.write_audit_log(
        db,
        actor_user_id=current.user.id,
        action="task.drama.stop_completed",
        target_type="task",
        target_id="drama",
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        success=True,
        detail=f"checked={checked}, matched={len(matched_ids)}, stopped={stopped}",
    )
    db.commit()

    return StopCompletedDramaTasksOut(checked=int(checked or 0), matched=len(matched_ids), stopped=stopped, task_ids=matched_ids[:50])


@router.post("/drama/savepath-snapshots/sync", response_model=SavepathSnapshotSyncOut, dependencies=[Depends(require_permissions(TASK_WRITE))])
def post_sync_drama_savepath_snapshots(
    request: Request, current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)
):
    items = (
        db.execute(select(Task).where(Task.task_type == "drama").order_by(Task.id.desc()))
        .scalars()
        .all()
    )
    checked = len(items)
    if not items:
        return SavepathSnapshotSyncOut(checked=0, synced=0, skipped=0, failed=0, items=[])

    manager = DatabaseAccountManager(db)
    task_payloads = [{"shareurl": str(t.shareurl or ""), "account_name": getattr(t, "account_name", None)} for t in items]
    manager.init_for_tasks(task_payloads)

    synced = 0
    skipped = 0
    failed = 0
    out_items: list[SavepathSnapshotSyncItemOut] = []
    for task in items:
        ok = False
        msg = None
        try:
            payload = {"shareurl": str(task.shareurl or ""), "account_name": getattr(task, "account_name", None)}
            adapter = manager.get_adapter_for_task(payload)
            if adapter is None:
                msg = "没有可用的驱动账号"
                failed += 1
            else:
                if not getattr(adapter, "is_active", False):
                    adapter.init()
                from app.services.task_savepath_snapshot import capture_and_upsert_snapshot

                account_name = str(getattr(adapter, "account_name", "") or getattr(task, "account_name", "") or "").strip()
                row = capture_and_upsert_snapshot(
                    db,
                    task_uid=str(getattr(task, "task_uid", "") or "").strip(),
                    savepath=str(getattr(task, "savepath", "") or "").strip(),
                    adapter=adapter,
                    account_name=account_name,
                    emit_line=None,
                )
                if row is None:
                    msg = "快照生成失败"
                    skipped += 1
                else:
                    ok = True
                    synced += 1
        except Exception as e:
            msg = str(e) or type(e).__name__
            failed += 1

        if len(out_items) < 50:
            out_items.append(
                SavepathSnapshotSyncItemOut(
                    task_id=int(getattr(task, "id", 0) or 0),
                    task_uid=str(getattr(task, "task_uid", "") or ""),
                    taskname=str(getattr(task, "taskname", "") or ""),
                    ok=ok,
                    message=msg,
                )
            )

    audit.write_audit_log(
        db,
        actor_user_id=current.user.id,
        action="task.drama.sync_savepath_snapshots",
        target_type="task",
        target_id="drama",
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        success=True,
        detail=f"checked={checked}, synced={synced}, skipped={skipped}, failed={failed}",
    )
    db.commit()
    return SavepathSnapshotSyncOut(checked=checked, synced=synced, skipped=skipped, failed=failed, items=out_items)


@router.post('', response_model=TaskOut, dependencies=[Depends(require_permissions(TASK_WRITE))])
def post_task(request: Request, payload: TaskCreateIn, current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    task = create_task(db, **payload.model_dump())
    audit.write_audit_log(db, actor_user_id=current.user.id, action='task.create', target_type='task', target_id=str(task.id), ip=request.client.host if request.client else None, user_agent=request.headers.get('user-agent'), success=True)
    db.commit()
    db.refresh(task)
    return _task_out(db, task)


@router.patch('/{task_id:int}', response_model=TaskOut, dependencies=[Depends(require_permissions(TASK_WRITE))])
def patch_task(request: Request, task_id: int, payload: TaskUpdateIn, current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    task = update_task(db, task_id, **payload.model_dump(exclude_unset=True))
    audit.write_audit_log(db, actor_user_id=current.user.id, action='task.update', target_type='task', target_id=str(task_id), ip=request.client.host if request.client else None, user_agent=request.headers.get('user-agent'), success=True)
    db.commit()
    db.refresh(task)
    return _task_out(db, task)


@router.patch('/{task_id:int}/status', response_model=TaskOut, dependencies=[Depends(require_permissions(TASK_WRITE))])
def patch_task_status(request: Request, task_id: int, payload: TaskStatusIn, current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    task = set_task_enabled(db, task_id, payload.enabled)
    audit.write_audit_log(db, actor_user_id=current.user.id, action='task.status', target_type='task', target_id=str(task_id), ip=request.client.host if request.client else None, user_agent=request.headers.get('user-agent'), success=True, detail=f'enabled={payload.enabled}')
    db.commit()
    db.refresh(task)
    return _task_out(db, task)


@router.delete('/{task_id:int}', dependencies=[Depends(require_permissions(TASK_WRITE))])
def delete_task_by_id(request: Request, task_id: int, current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    delete_task(db, task_id)
    audit.write_audit_log(db, actor_user_id=current.user.id, action='task.delete', target_type='task', target_id=str(task_id), ip=request.client.host if request.client else None, user_agent=request.headers.get('user-agent'), success=True)
    db.commit()
    return {'ok': True}


@router.post('/{task_id:int}/run', response_model=TaskExecutionOut, dependencies=[Depends(require_permissions(TASK_RUN))])
def post_run_task(request: Request, task_id: int, current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    task = get_task(db, task_id)
    execution = TaskExecutor(db).run_task(task)
    audit.write_audit_log(db, actor_user_id=current.user.id, action='task.run', target_type='task', target_id=str(task_id), ip=request.client.host if request.client else None, user_agent=request.headers.get('user-agent'), success=execution.status == 'success', detail=execution.message)
    db.commit()
    db.refresh(execution)
    if str(getattr(task, "task_type", "") or "") == "drama":
        try:
            section, should_notify = build_task_section(task, execution)
            if should_notify:
                send_runtime(db, DRAMA_NOTIFY_TITLE, section)
        except Exception:
            pass
        if should_trigger_linked_sync_for_drama_execution(execution):
            trigger_linked_sync_tasks_async([str(getattr(task, "task_uid", "") or "")], source="api.tasks.run")
    return _execution_out(execution)


@router.post('/{task_id:int}/run/stream', dependencies=[Depends(require_permissions(TASK_RUN))])
def post_run_task_stream(request: Request, task_id: int, current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    task = get_task(db, task_id)
    init_payload = {
        "task_id": int(task.id),
        "taskname": str(task.taskname),
        "started_at": datetime.now().isoformat(),
    }
    audit.write_audit_log(
        db,
        actor_user_id=current.user.id,
        action='task.run.stream',
        target_type='task',
        target_id=str(init_payload["task_id"]),
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get('user-agent'),
        success=True,
    )
    db.commit()

    q: queue.Queue[tuple[str, object]] = queue.Queue()
    done_sentinel = object()

    def emit_line(line: str) -> None:
        q.put(("log", line))

    def emit_stage(stage: str) -> None:
        q.put(("stage", stage))

    def worker() -> None:
        with SessionLocal() as wdb:
            log = ExecutionLog(emit_line=emit_line, emit_stage=emit_stage)
            try:
                wtask = get_task(wdb, task_id)
                execution = TaskExecutor(wdb).run_task(wtask, log=log)
                wdb.commit()
                wdb.refresh(execution)
                if str(getattr(wtask, "task_type", "") or "") == "drama":
                    try:
                        section, should_notify = build_task_section(wtask, execution)
                        if should_notify:
                            send_runtime(wdb, DRAMA_NOTIFY_TITLE, section)
                    except Exception:
                        pass
                    if should_trigger_linked_sync_for_drama_execution(execution):
                        trigger_linked_sync_tasks_async([str(getattr(wtask, "task_uid", "") or "")], source="api.tasks.run.stream")
                q.put(
                    (
                        "done",
                        {
                            "status": execution.status,
                            "message": execution.message,
                            "execution": _execution_out(execution).model_dump(mode="json"),
                        },
                    )
                )
            except Exception as exc:
                wdb.rollback()
                message = getattr(exc, "message", None) or str(exc).strip() or type(exc).__name__
                log.section("异常")
                log.line(message)
                q.put(
                    (
                        "done",
                        {
                            "status": "failed",
                            "message": message,
                            "execution": {
                                "id": 0,
                                "task_id": task_id,
                                "status": "failed",
                                "started_at": log.started_at.isoformat(),
                                "finished_at": datetime.now().isoformat(),
                                "tree_summary": None,
                                "message": message,
                                "stage": log.stage,
                                "run_log": log.render(),
                                "adapter_snapshot": {},
                                "plugins_snapshot": [],
                            },
                        },
                    )
                )
            finally:
                q.put(("done_sentinel", done_sentinel))

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()

    def sse(event: str, data: object) -> bytes:
        payload = json.dumps(data, ensure_ascii=False)
        return f"event: {event}\ndata: {payload}\n\n".encode("utf-8")

    def gen():
        yield sse("init", init_payload)
        while True:
            try:
                kind, value = q.get(timeout=15)
            except queue.Empty:
                yield b": ping\n\n"
                continue
            if kind == "log":
                yield sse("log", {"line": str(value)})
                continue
            if kind == "stage":
                yield sse("stage", {"stage": str(value)})
                continue
            if kind == "done":
                yield sse("done", value)
                continue
            if kind == "done_sentinel":
                break

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post('/run/stream', dependencies=[Depends(require_permissions(TASK_RUN))])
def post_run_task_stream_by_payload(request: Request, payload: TaskCreateIn, current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    import uuid

    init_payload = {
        "task_id": 0,
        "taskname": str(payload.taskname),
        "started_at": datetime.now().isoformat(),
        "preview": True,
    }
    audit.write_audit_log(
        db,
        actor_user_id=current.user.id,
        action='task.run.preview_stream',
        target_type='task',
        target_id='0',
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get('user-agent'),
        success=True,
        detail=str(payload.taskname or ""),
    )
    db.commit()

    q: queue.Queue[tuple[str, object]] = queue.Queue()
    done_sentinel = object()

    def emit_line(line: str) -> None:
        q.put(("log", line))

    def emit_stage(stage: str) -> None:
        q.put(("stage", stage))

    def worker() -> None:
        with SessionLocal() as wdb:
            log = ExecutionLog(emit_line=emit_line, emit_stage=emit_stage)
            try:
                from app.models.task import Task
                from app.extensions.runtime.task_executor import TaskExecutor

                task_uid = (str(payload.task_uid or "").strip() or f"preview-{uuid.uuid4().hex}")
                wtask = Task(
                    task_uid=task_uid,
                    task_type=str(payload.task_type or "generic"),
                    taskname=str(payload.taskname or ""),
                    shareurl=str(payload.shareurl or ""),
                    savepath=str(payload.savepath or ""),
                    pattern=(str(payload.pattern) if payload.pattern is not None else None),
                    replace=(str(payload.replace) if payload.replace is not None else None),
                    enddate=(str(payload.enddate) if payload.enddate is not None else None),
                    ignore_extension=bool(payload.ignore_extension),
                    sort_index=(int(payload.sort_index) if payload.sort_index is not None else None),
                    startfid=(str(payload.startfid) if payload.startfid is not None else None),
                    account_name=(str(payload.account_name) if payload.account_name is not None else None),
                    update_subdir=(str(payload.update_subdir) if payload.update_subdir is not None else None),
                    tmdb_id=(int(payload.tmdb_id) if payload.tmdb_id is not None else None),
                    tmdb_media_type=(str(payload.tmdb_media_type) if payload.tmdb_media_type is not None else None),
                    enabled=True,
                    addition_json=json.dumps(payload.addition or {}, ensure_ascii=False),
                    extra_json=json.dumps(payload.extra or {}, ensure_ascii=False),
                )
                wtask.id = 0
                execution = TaskExecutor(wdb).run_task(wtask, log=log, persist_execution=False)
                q.put(
                    (
                        "done",
                        {
                            "status": execution.status,
                            "message": execution.message,
                            "execution": _execution_out(execution).model_dump(mode="json"),
                        },
                    )
                )
            except Exception as exc:
                wdb.rollback()
                message = getattr(exc, "message", None) or str(exc).strip() or type(exc).__name__
                log.section("异常")
                log.line(message)
                q.put(
                    (
                        "done",
                        {
                            "status": "failed",
                            "message": message,
                            "execution": {
                                "id": 0,
                                "task_id": 0,
                                "status": "failed",
                                "started_at": log.started_at.isoformat(),
                                "finished_at": datetime.now().isoformat(),
                                "tree_summary": None,
                                "message": message,
                                "stage": log.stage,
                                "run_log": log.render(),
                                "adapter_snapshot": {},
                                "plugins_snapshot": [],
                            },
                        },
                    )
                )
            finally:
                q.put(("done_sentinel", done_sentinel))

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()

    def sse(event: str, data: object) -> bytes:
        payload_s = json.dumps(data, ensure_ascii=False)
        return f"event: {event}\ndata: {payload_s}\n\n".encode("utf-8")

    def gen():
        yield sse("init", init_payload)
        while True:
            try:
                kind, value = q.get(timeout=15)
            except queue.Empty:
                yield b": ping\n\n"
                continue
            if kind == "log":
                yield sse("log", {"line": str(value)})
                continue
            if kind == "stage":
                yield sse("stage", {"stage": str(value)})
                continue
            if kind == "done":
                yield sse("done", value)
                continue
            if kind == "done_sentinel":
                break

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get('/scheduler', response_model=TaskSchedulerSettingOut, dependencies=[Depends(require_permissions(TASK_READ))])
def get_task_scheduler_setting(db: Session = Depends(get_db)):
    setting = get_or_create_task_scheduler_setting(db)
    db.commit()
    db.refresh(setting)
    return _scheduler_out(setting)


@router.patch('/scheduler', response_model=TaskSchedulerSettingOut, dependencies=[Depends(require_permissions(TASK_WRITE))])
def patch_task_scheduler_setting(request: Request, payload: TaskSchedulerSettingUpdateIn, current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    setting = update_task_scheduler_setting(db, **payload.model_dump(exclude_unset=True))
    audit.write_audit_log(db, actor_user_id=current.user.id, action='task.scheduler.update', target_type='task_scheduler_setting', target_id=str(setting.id), ip=request.client.host if request.client else None, user_agent=request.headers.get('user-agent'), success=True)
    db.commit()
    db.refresh(setting)
    task_scheduler_manager.reload()
    return _scheduler_out(setting)


@router.post("/repair-banned", response_model=RepairBannedTasksOut, dependencies=[Depends(require_permissions(TASK_WRITE))])
def post_repair_banned_tasks(db: Session = Depends(get_db)) -> RepairBannedTasksOut:
    result = repair_banned_drama_tasks(db)
    return RepairBannedTasksOut(**(result or {}))


@router.post('/share/preview', response_model=SharePreviewOut, dependencies=[Depends(require_permissions(TASK_READ))])
def post_share_preview(payload: SharePreviewIn, db: Session = Depends(get_db)):
    drive_type = AdapterRegistry.detect_drive_type(payload.shareurl)
    if drive_type is None:
        raise bad_request('TASK_SHAREURL_INVALID', '无法识别的网盘分享链接')
    account_name = payload.account_name or _pick_default_account_name(db, drive_type)
    if payload.account_name and _get_active_account(db, payload.account_name) is None:
        raise not_found('DRIVE_ACCOUNT_NOT_FOUND', '指定账号不存在或不可用')
    manager = DatabaseAccountManager(db)
    task_payload = {"shareurl": payload.shareurl, "account_name": account_name}
    manager.init_for_tasks([task_payload])
    adapter = manager.get_adapter_for_task(task_payload)
    if adapter is None:
        raise not_found('DRIVE_ACCOUNT_NOT_FOUND', '没有可用的驱动账号')
    pwd_id, passcode, extracted_pdir_fid, _ = adapter.extract_url(payload.shareurl)
    if not pwd_id:
        raise bad_request('TASK_SHAREURL_INVALID', '无法解析分享链接')
    token_response = adapter.get_stoken(pwd_id, passcode or '')
    stoken = ((token_response or {}).get("data") or {}).get("stoken")
    if not stoken:
        message = (token_response or {}).get("message") or "获取分享 token 失败"
        raise bad_request('TASK_SHARE_TOKEN_FAILED', str(message))
    pdir_fid = payload.pdir_fid if payload.pdir_fid is not None else (extracted_pdir_fid or "")
    detail = adapter.get_detail(pwd_id, stoken, pdir_fid or "")
    raw_items = (((detail or {}).get("data") or {}).get("list")) or []
    taskname = str(payload.taskname or "")
    pattern = str(payload.pattern or "")
    replace = str(payload.replace or "")
    savepath = str(payload.savepath or "").strip().rstrip("/")
    update_subdir = str(payload.update_subdir or "").strip()
    startfid = str(payload.startfid or "").strip()
    ignore_ext = bool(payload.ignore_extension)

    from app.services.tmdb_settings import get_or_create_tmdb_setting, get_tmdb_runtime_config

    tmdb_cfg = get_tmdb_runtime_config(get_or_create_tmdb_setting(db))
    disable_guessit_fallback = bool(tmdb_cfg.get("disable_guessit_tmdb_fallback_rename") or False)
    tv_tpl = str(tmdb_cfg.get("guessit_tmdb_tv_rename_template") or "").strip()
    movie_tpl = str(tmdb_cfg.get("guessit_tmdb_movie_rename_template") or "").strip()
    tmdb_series_title = None
    tmdb_tv_seasons = None
    tmdb_year = None
    tmdb_id = int(payload.tmdb_id) if payload.tmdb_id is not None else 0
    tmdb_media_type = str(payload.tmdb_media_type or "").strip().lower()
    if not disable_guessit_fallback and tmdb_id > 0 and tmdb_media_type in ("movie", "tv"):
        try:
            from app.services.tmdb_cache import get_tmdb_detail_cached

            configured, detail, _, _episode_weekdays, _row = get_tmdb_detail_cached(db, media_type=tmdb_media_type, tmdb_id=tmdb_id)
            if configured and isinstance(detail, dict):
                tmdb_series_title = detail.get("name") if tmdb_media_type == "tv" else detail.get("title")
                if tmdb_media_type == "tv":
                    raw_seasons = detail.get("seasons")
                    tmdb_tv_seasons = raw_seasons if isinstance(raw_seasons, list) else None
                if tmdb_media_type == "movie":
                    rd = str(detail.get("release_date") or "").strip()
                    if len(rd) >= 4 and rd[:4].isdigit():
                        tmdb_year = int(rd[:4])
        except Exception:
            tmdb_series_title = None

    dir_file_list: list[dict] = []
    dir_filename_list: list[str] = []
    if savepath:
        normalized = re.sub(r"/+", "/", savepath)
        dest_fid = None
        try:
            fid_list = adapter.get_fids([normalized]) or []
            match = None
            for item in fid_list:
                item_path = item.get("file_path") or item.get("path") or item.get("filePath")
                if item_path == normalized:
                    match = item
                    break
            if match is None and fid_list:
                match = fid_list[0]
            if match and match.get("fid"):
                dest_fid = str(match.get("fid"))
        except Exception:
            dest_fid = None
        if dest_fid:
            listing = adapter.ls_dir(dest_fid, max_items=2000) or {}
            dir_file_list = (((listing or {}).get("data") or {}).get("list")) or []
            for raw in dir_file_list:
                if _bool_is_dir(raw):
                    continue
                name = _pick_name(raw)
                if name:
                    dir_filename_list.append(name)

    from app.services.magic_regex import get_enabled_magic_regex_map

    mr = MagicRename(magic_regex=get_enabled_magic_regex_map(db))
    mr.set_taskname(taskname)
    pattern, replace = mr.magic_regex_conv(pattern, replace)
    compiled_search = re.compile(pattern) if pattern else None
    compiled_subdir = re.compile(update_subdir) if update_subdir else None
    video_exts = {
        ".mp4",
        ".mkv",
        ".avi",
        ".mov",
        ".wmv",
        ".flv",
        ".webm",
        ".m4v",
        ".ts",
        ".m2ts",
        ".mpg",
        ".mpeg",
        ".3gp",
    }

    def _is_video_name(name: str) -> bool:
        try:
            _base, _ext = os.path.splitext(str(name or ""))
        except Exception:
            return False
        return bool(_ext) and _ext.lower() in video_exts

    def _to_ts(v):
        try:
            return float(v)
        except Exception:
            return None

    start_ts = None
    fid_keep = None
    if startfid:
        start_item = next((f for f in raw_items if str(_pick_fid(f)).strip() == startfid), None)
        if start_item:
            start_ts = _to_ts(_pick_updated_at(start_item))
            if start_ts is None:
                sorted_list = sorted(raw_items, key=lambda x: _to_ts(_pick_updated_at(x)) or 0, reverse=True)
                kept: list[str] = []
                for f in sorted_list:
                    fid = str(_pick_fid(f)).strip()
                    if fid == startfid:
                        break
                    if fid:
                        kept.append(fid)
                fid_keep = set(kept)

    preview_list: list[dict] = []
    for raw in raw_items[: payload.max_items]:
        fid = _pick_fid(raw)
        file_name = _pick_name(raw)
        if not fid or not file_name:
            continue
        is_dir = _bool_is_dir(raw)
        updated_at = _pick_updated_at(raw)
        size = _pick_size(raw)
        include_items = _pick_children_count(raw) if is_dir else None

        item: dict = {
            "fid": fid,
            "fid_token": _pick_fid_token(raw),
            "file_name": file_name,
            "dir": is_dir,
            "updated_at": updated_at,
            "size": size,
            "include_items": include_items,
            "file_name_re": None,
            "file_name_saved": None,
        }

        if is_dir or not _is_video_name(file_name):
            preview_list.append(item)
            continue

        if startfid:
            if start_ts is not None:
                if (_to_ts(updated_at) or 0) <= start_ts:
                    item["file_name_saved"] = "起始及之前"
                    preview_list.append(item)
                    continue
            elif fid_keep is not None:
                if fid not in fid_keep:
                    item["file_name_saved"] = "起始及之前"
                    preview_list.append(item)
                    continue

        search_re = compiled_subdir if (is_dir and compiled_subdir) else compiled_search
        matched = (not search_re) or bool(search_re.search(file_name))
        if matched:
            file_name_re = file_name
            if not is_dir:
                if not disable_guessit_fallback and (not pattern.strip()) and (not replace.strip()) and bool(tmdb_series_title):
                    try:
                        from app.extensions.runtime.guessit_fallback import guessit_media_target

                        file_name_re = (
                            guessit_media_target(
                                file_name,
                                media_type=tmdb_media_type,
                                tmdb_title=(str(tmdb_series_title) if tmdb_series_title else None),
                                tmdb_year=tmdb_year,
                                tv_seasons=tmdb_tv_seasons,
                                tv_rename_template=tv_tpl or None,
                                movie_rename_template=movie_tpl or None,
                                trace_tag="preview",
                            )
                            or file_name
                        )
                    except Exception:
                        file_name_re = file_name
                else:
                    file_name_re = mr.sub(pattern, replace, file_name)
            saved = mr.is_exists(file_name_re, dir_filename_list, ignore_ext and not is_dir) if dir_filename_list else None
            if saved:
                item["file_name_saved"] = saved
            else:
                item["file_name_re"] = file_name_re
        preview_list.append(item)

    best: dict[str, tuple[tuple[float, float], int]] = {}
    for idx, f in enumerate(preview_list):
        if f.get("file_name_saved"):
            continue
        if f.get("dir"):
            continue
        target = f.get("file_name_re")
        if not target:
            continue
        key = os.path.splitext(target)[0] if ignore_ext else target
        sz = _pick_size(f)
        ts = _to_ts(f.get("updated_at"))
        score = (float(sz) if sz is not None else float("-inf"), ts if ts is not None else float("-inf"))
        prev = best.get(key)
        if prev is None or score > prev[0] or (score == prev[0] and idx > prev[1]):
            best[key] = (score, idx)
    if best:
        keep_idx = set(v[1] for v in best.values())
        for idx, f in enumerate(preview_list):
            if idx in keep_idx:
                continue
            if f.get("file_name_saved") or f.get("dir"):
                continue
            if f.get("file_name_re"):
                f["file_name_saved"] = "重命名冲突（保留最大）"
                f["file_name_re"] = None

    if re.search(r"\{I+\}", replace or ""):
        try:
            start_index = int(payload.sort_index or 1)
        except (TypeError, ValueError):
            start_index = 1
        dest_file_list_for_index = []
        for raw in dir_file_list:
            dest_file_list_for_index.append({"file_name": _pick_name(raw), "dir": _bool_is_dir(raw)})
        mr.set_dir_file_list(dest_file_list_for_index, replace, start_index=start_index)
        mr.sort_file_list(preview_list, start_index=start_index)

    items: list[SharePreviewItemOut] = []
    for it in preview_list:
        items.append(
            SharePreviewItemOut(
                fid=str(it["fid"]),
                fid_token=it.get("fid_token"),
                name=str(it["file_name"]),
                name_re=it.get("file_name_re"),
                is_dir=bool(it.get("dir")),
                updated_at=it.get("updated_at"),
                size=it.get("size"),
                children_count=it.get("include_items") if it.get("dir") else None,
                file_name=str(it["file_name"]),
                file_name_re=it.get("file_name_re"),
                file_name_saved=it.get("file_name_saved"),
                dir=bool(it.get("dir")),
                include_items=it.get("include_items") if it.get("dir") else None,
            )
        )
    return SharePreviewOut(
        drive_type=str(drive_type),
        suggested_account_name=account_name,
        pwd_id=str(pwd_id),
        pdir_fid=str(pdir_fid or ""),
        items=items,
    )


@router.post("/share/preview-batch", response_model=SharePreviewBatchOut, dependencies=[Depends(require_permissions(TASK_READ))])
def post_share_preview_batch(payload: SharePreviewBatchIn, db: Session = Depends(get_db)):
    out, changed = preview_share_batch(db, payload)
    if changed:
        db.commit()
    return out


@router.post('/drive/browse', response_model=DriveBrowseOut, dependencies=[Depends(require_permissions(TASK_READ))])
def post_drive_browse(payload: DriveBrowseIn, db: Session = Depends(get_db)):
    drive_type: str | None = None
    if payload.account_name:
        account = _get_active_account(db, payload.account_name)
        if account is None:
            raise not_found("DRIVE_ACCOUNT_NOT_FOUND", "指定账号不存在或不可用")
        drive_type = str(account.drive_type)
    if not payload.account_name:
        if payload.shareurl:
            drive_type = AdapterRegistry.detect_drive_type(payload.shareurl)
            if drive_type is None:
                raise bad_request('TASK_SHAREURL_INVALID', '无法识别的网盘分享链接')
            payload.account_name = _pick_default_account_name(db, drive_type)
        else:
            any_default = _pick_any_default_account(db)
            if any_default:
                payload.account_name = any_default.name
                drive_type = str(any_default.drive_type)
    if not payload.account_name:
        raise not_found('DRIVE_ACCOUNT_NOT_FOUND', '没有可用的驱动账号')
    manager = DatabaseAccountManager(db)
    task_payload = {"shareurl": payload.shareurl or "", "account_name": payload.account_name}
    manager.init_for_tasks([task_payload])
    adapter = manager.get_adapter_for_task(task_payload)
    if adapter is None:
        raise not_found('DRIVE_ACCOUNT_NOT_FOUND', '没有可用的驱动账号')
    dir_path = str(payload.dir_path or "").strip() or "/"

    is_fid_mode = ("/" not in dir_path) and (dir_path not in ("/", "0"))
    normalized_path = re.sub(r"/+", "/", dir_path)
    if not normalized_path.startswith("/") and not is_fid_mode:
        normalized_path = "/" + normalized_path
    normalized_path = normalized_path.rstrip('/')
    paths: list[DriveBrowsePathOut] = []
    if dir_path in ("/", "0"):
        pdir_fid = "0"
    elif is_fid_mode:
        pdir_fid = dir_path
    else:
        fid_list = adapter.get_fids([normalized_path])
        match = None
        for item in fid_list or []:
            item_path = item.get("file_path") or item.get("path") or item.get("filePath")
            if item_path == normalized_path:
                match = item
                break
        if match is None and fid_list:
            match = fid_list[0]
        pdir_fid = str(match.get("fid")) if match and match.get("fid") else None

        segments = [s for s in normalized_path.split("/") if s]
        if segments:
            accum_paths = ["/" + "/".join(segments[: i + 1]) for i in range(len(segments))]
            fid_arr = adapter.get_fids(accum_paths) or []
            fid_map: dict[str, str] = {}
            for it in fid_arr:
                p = it.get("file_path") or it.get("path") or it.get("filePath")
                f = it.get("fid")
                if p and f:
                    fid_map[str(p)] = str(f)
            for i, name in enumerate(segments):
                p = accum_paths[i]
                fid_val = fid_map.get(p)
                if fid_val:
                    paths.append(DriveBrowsePathOut(fid=fid_val, name=name))

    if not pdir_fid:
        return DriveBrowseOut(
            account_name=str(payload.account_name),
            drive_type=str(drive_type) if drive_type else None,
            dir_path=dir_path,
            exists=False,
            pdir_fid=None,
            items=[],
            paths=paths,
        )

    listing = adapter.ls_dir(str(pdir_fid), max_items=payload.max_items)
    raw_items = (((listing or {}).get("data") or {}).get("list")) or []
    items: list[DriveBrowseItemOut] = []
    for raw in raw_items[: payload.max_items]:
        fid = _pick_fid(raw)
        name = _pick_name(raw)
        if not fid or not name:
            continue
        is_dir = _bool_is_dir(raw)
        items.append(
            DriveBrowseItemOut(
                fid=fid,
                name=name,
                is_dir=is_dir,
                updated_at=_pick_updated_at(raw),
                size=_pick_size(raw),
                include_items=_pick_children_count(raw) if is_dir else None,
                file_name=name,
                dir=is_dir,
            )
        )
    return DriveBrowseOut(
        account_name=str(payload.account_name),
        drive_type=str(drive_type) if drive_type else None,
        dir_path=dir_path,
        exists=True,
        pdir_fid=str(pdir_fid),
        items=items,
        paths=paths,
    )


@router.post('/drive/mkdir', response_model=DriveMkdirOut, dependencies=[Depends(require_permissions(TASK_WRITE))])
def post_drive_mkdir(payload: DriveMkdirIn, db: Session = Depends(get_db)):
    if payload.account_name and _get_active_account(db, payload.account_name) is None:
        raise not_found("DRIVE_ACCOUNT_NOT_FOUND", "指定账号不存在或不可用")
    if not payload.account_name:
        if not payload.shareurl:
            raise bad_request('TASK_ACCOUNT_REQUIRED', '缺少 account_name 或 shareurl')
        drive_type = AdapterRegistry.detect_drive_type(payload.shareurl)
        if drive_type is None:
            raise bad_request('TASK_SHAREURL_INVALID', '无法识别的网盘分享链接')
        payload.account_name = _pick_default_account_name(db, drive_type)
    if not payload.account_name:
        raise not_found('DRIVE_ACCOUNT_NOT_FOUND', '没有可用的驱动账号')
    manager = DatabaseAccountManager(db)
    task_payload = {"shareurl": payload.shareurl or "", "account_name": payload.account_name}
    manager.init_for_tasks([task_payload])
    adapter = manager.get_adapter_for_task(task_payload)
    if adapter is None:
        raise not_found('DRIVE_ACCOUNT_NOT_FOUND', '没有可用的驱动账号')
    response = adapter.mkdir(payload.dir_path)
    return DriveMkdirOut(account_name=str(payload.account_name), dir_path=payload.dir_path, response=response or {})

from __future__ import annotations

import json
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.errors import bad_request, not_found
from app.extensions.runtime.adapter_registry import AdapterRegistry
from app.extensions.runtime.task_executor import TaskExecutor
from app.models.sync_task_drama_link import SyncTaskDramaLink
from app.models.task import Task
from app.models.task_execution import TaskExecution


def list_tasks(db: Session) -> list[Task]:
    return db.execute(select(Task).options(selectinload(Task.executions)).order_by(Task.id.desc())).scalars().all()


def list_tasks_recent_executions(db: Session, *, limit: int = 3) -> list[Task]:
    tasks = db.execute(select(Task).order_by(Task.id.desc())).scalars().all()
    if not tasks:
        return []

    task_ids = [int(getattr(t, "id", 0) or 0) for t in tasks]
    task_ids = [tid for tid in task_ids if tid > 0]
    if not task_ids or limit <= 0:
        for t in tasks:
            t.executions = []
        return tasks

    rn = (
        select(
            TaskExecution.id.label("id"),
            TaskExecution.task_id.label("task_id"),
            func.row_number()
            .over(partition_by=TaskExecution.task_id, order_by=TaskExecution.started_at.desc())
            .label("rn"),
        )
        .where(TaskExecution.task_id.in_(task_ids))
        .subquery()
    )
    recent_ids = (
        db.execute(select(rn.c.id).where(rn.c.rn <= limit))
        .scalars()
        .all()
    )

    exec_map: dict[int, list[TaskExecution]] = {tid: [] for tid in task_ids}
    if recent_ids:
        executions = (
            db.execute(
                select(TaskExecution)
                .where(TaskExecution.id.in_(recent_ids))
                .order_by(TaskExecution.task_id.asc(), TaskExecution.started_at.desc())
            )
            .scalars()
            .all()
        )
        for ex in executions:
            tid = int(getattr(ex, "task_id", 0) or 0)
            if tid in exec_map:
                exec_map[tid].append(ex)

    for t in tasks:
        tid = int(getattr(t, "id", 0) or 0)
        t.executions = exec_map.get(tid, [])

    return tasks



def get_task(db: Session, task_id: int) -> Task:
    task = db.execute(select(Task).options(selectinload(Task.executions)).where(Task.id == task_id)).scalars().first()
    if task is None:
        raise not_found('TASK_NOT_FOUND', '任务不存在')
    return task


def create_task(db: Session, **payload) -> Task:
    drive_type = AdapterRegistry.detect_drive_type(payload['shareurl'])
    if drive_type is None:
        raise bad_request('TASK_SHAREURL_INVALID', '无法识别的网盘分享链接')
    tmdb_media_type = payload.get("tmdb_media_type")
    if tmdb_media_type is not None:
        tmdb_media_type = str(tmdb_media_type).strip().lower() or None
        if tmdb_media_type is not None and tmdb_media_type not in ("movie", "tv"):
            raise bad_request("TASK_TMDB_MEDIA_TYPE_INVALID", "无效的 TMDB 类型")
    tmdb_id = payload.get("tmdb_id")
    if tmdb_id is not None:
        try:
            tmdb_id = int(tmdb_id)
        except Exception:
            raise bad_request("TASK_TMDB_ID_INVALID", "无效的 TMDB ID")
        if tmdb_id <= 0:
            raise bad_request("TASK_TMDB_ID_INVALID", "无效的 TMDB ID")
    task = Task(
        task_uid=payload.get('task_uid') or uuid.uuid4().hex,
        task_type=payload.get('task_type') or 'generic',
        taskname=payload['taskname'],
        shareurl=payload['shareurl'],
        savepath=payload['savepath'],
        pattern=payload.get('pattern'),
        replace=payload.get('replace'),
        enddate=payload.get('enddate'),
        ignore_extension=payload.get('ignore_extension', False),
        sort_index=payload.get('sort_index'),
        startfid=payload.get('startfid'),
        account_name=payload.get('account_name'),
        update_subdir=payload.get('update_subdir'),
        tmdb_id=tmdb_id,
        tmdb_media_type=tmdb_media_type,
        enabled=payload.get('enabled', True),
        addition_json=json.dumps(payload.get('addition') or {}, ensure_ascii=False),
        extra_json=json.dumps(payload.get('extra') or {}, ensure_ascii=False),
    )
    db.add(task)
    db.flush()
    return task


def update_task(db: Session, task_id: int, **payload) -> Task:
    task = get_task(db, task_id)
    task.shareurl_ban = None
    old_shareurl = str(getattr(task, "shareurl", "") or "").strip()
    clearable_fields = {'pattern', 'replace', 'enddate', 'sort_index', 'startfid', 'account_name', 'update_subdir', 'tmdb_id', 'tmdb_media_type'}
    for key in [
        'task_type',
        'taskname',
        'shareurl',
        'savepath',
        'pattern',
        'replace',
        'enddate',
        'ignore_extension',
        'sort_index',
        'startfid',
        'account_name',
        'update_subdir',
        'tmdb_id',
        'tmdb_media_type',
        'enabled',
    ]:
        if key not in payload:
            continue
        if key in clearable_fields:
            value = payload[key]
            if key == "tmdb_media_type":
                if isinstance(value, str) and not value.strip():
                    value = None
                if value is not None:
                    value = str(value).strip().lower() or None
                if value is not None and value not in ("movie", "tv"):
                    raise bad_request("TASK_TMDB_MEDIA_TYPE_INVALID", "无效的 TMDB 类型")
            if key == "tmdb_id":
                if value in ("", 0):
                    value = None
                if value is not None:
                    try:
                        value = int(value)
                    except Exception:
                        raise bad_request("TASK_TMDB_ID_INVALID", "无效的 TMDB ID")
                    if value <= 0:
                        raise bad_request("TASK_TMDB_ID_INVALID", "无效的 TMDB ID")
            if isinstance(value, str) and not value.strip():
                value = None
            setattr(task, key, value)
            continue
        if payload[key] is not None:
            setattr(task, key, payload[key])
    if payload.get('addition') is not None:
        task.addition_json = json.dumps(payload['addition'], ensure_ascii=False)
    if payload.get('extra') is not None:
        task.extra_json = json.dumps(payload['extra'], ensure_ascii=False)
    if "shareurl" in payload:
        new_shareurl = str(getattr(task, "shareurl", "") or "").strip()
        if new_shareurl and new_shareurl != old_shareurl:
            task.shareurl_ban = None
    db.flush()
    return task


def set_task_enabled(db: Session, task_id: int, enabled: bool) -> Task:
    task = get_task(db, task_id)
    task.enabled = enabled
    return task


def delete_task(db: Session, task_id: int) -> None:
    task = get_task(db, task_id)
    db.query(SyncTaskDramaLink).filter(SyncTaskDramaLink.task_uid == str(task.task_uid)).delete(synchronize_session=False)
    db.delete(task)
    db.flush()


def run_task(db: Session, task_id: int):
    task = get_task(db, task_id)
    executor = TaskExecutor(db)
    execution = executor.run_task(task)
    db.flush()
    return execution

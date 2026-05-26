import json
import queue
import threading
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import CurrentUser, get_current_user, require_permissions
from app.core.errors import ApiError
from app.core.permissions import SYNC_READ, SYNC_RUN, SYNC_WRITE
from app.db.session import SessionLocal, get_db
from app.extensions.runtime.execution_log import ExecutionLog
from app.extensions.runtime.sync_executor import SyncExecutor
from app.models.sync_execution import SyncExecution
from app.models.sync_task import SyncTask
from app.models.sync_task_drama_link import SyncTaskDramaLink
from app.schemas.sync_execution_files import SyncExecutionFileOut
from app.schemas.sync_task import SyncExecutionOut, SyncRunIn, SyncTaskCreateIn, SyncTaskOut, SyncTaskUpdateIn
from app.schemas.path_browse import PathBrowseIn, PathBrowseItemOut, PathBrowseOut, PathBrowsePathOut
from app.services import audit
from app.services.sync_tasks import (
    browse_local_dir,
    create_sync_task,
    delete_sync_task,
    get_sync_task,
    list_sync_execution_files,
    list_sync_executions,
    list_sync_tasks,
    update_sync_task,
)


router = APIRouter()


def _task_out(item: SyncTask, *, drama_task_uids: list[str] | None = None) -> SyncTaskOut:
    strategy = {}
    if item.strategy_json:
        try:
            strategy = json.loads(item.strategy_json)
        except Exception:
            strategy = {}
    return SyncTaskOut(
        id=item.id,
        uid=item.uid,
        name=item.name,
        enabled=item.enabled,
        source={"type": item.source_type, "path": item.source_path},
        target={"type": item.target_type, "path": item.target_path},
        mode=item.mode,
        strategy=strategy,
        drama_task_uids=list(drama_task_uids or []),
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _execution_out(item: SyncExecution) -> SyncExecutionOut:
    stats: dict[str, Any] = {}
    if item.stats_json:
        try:
            parsed = json.loads(item.stats_json)
        except Exception:
            parsed = None
        if isinstance(parsed, dict):
            stats = parsed
    return SyncExecutionOut(
        id=item.id,
        sync_task_id=item.sync_task_id,
        status=item.status,
        started_at=item.started_at,
        finished_at=item.finished_at,
        stage=item.stage,
        run_log=item.run_log,
        stats=stats,
        message=item.message,
    )


@router.get("", response_model=list[SyncTaskOut], dependencies=[Depends(require_permissions(SYNC_READ))])
def get_sync_tasks(current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = list_sync_tasks(db)
    uids = [str(t.uid) for t in rows if getattr(t, "uid", None)]
    mapping: dict[str, list[str]] = {}
    if uids:
        links = db.execute(select(SyncTaskDramaLink).where(SyncTaskDramaLink.sync_task_uid.in_(uids))).scalars().all()
        for it in links:
            mapping.setdefault(str(it.sync_task_uid), []).append(str(it.task_uid))
    return [_task_out(t, drama_task_uids=mapping.get(str(t.uid), [])) for t in rows]


@router.post("", response_model=SyncTaskOut, dependencies=[Depends(require_permissions(SYNC_WRITE))])
def post_sync_task(request: Request, payload: SyncTaskCreateIn, current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    task = create_sync_task(
        db,
        name=payload.name,
        enabled=payload.enabled,
        source=payload.source.model_dump(mode="json"),
        target=payload.target.model_dump(mode="json"),
        mode=payload.mode,
        strategy=payload.strategy.model_dump(mode="json"),
        drama_task_uids=list(payload.drama_task_uids or []),
    )
    audit.write_audit_log(
        db,
        actor_user_id=current.user.id,
        action="sync_task.create",
        target_type="sync_task",
        target_id=str(task.id),
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        success=True,
    )
    db.commit()
    db.refresh(task)
    linked = db.execute(select(SyncTaskDramaLink.task_uid).where(SyncTaskDramaLink.sync_task_uid == str(task.uid))).scalars().all()
    return _task_out(task, drama_task_uids=[str(x) for x in linked if x])


@router.patch("/{sync_task_id:int}", response_model=SyncTaskOut, dependencies=[Depends(require_permissions(SYNC_WRITE))])
def patch_sync_task(request: Request, sync_task_id: int, payload: SyncTaskUpdateIn, current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    task = update_sync_task(db, sync_task_id, **payload.model_dump(exclude_unset=True))
    audit.write_audit_log(
        db,
        actor_user_id=current.user.id,
        action="sync_task.update",
        target_type="sync_task",
        target_id=str(sync_task_id),
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        success=True,
    )
    db.commit()
    db.refresh(task)
    linked = db.execute(select(SyncTaskDramaLink.task_uid).where(SyncTaskDramaLink.sync_task_uid == str(task.uid))).scalars().all()
    return _task_out(task, drama_task_uids=[str(x) for x in linked if x])


@router.delete("/{sync_task_id:int}", dependencies=[Depends(require_permissions(SYNC_WRITE))])
def delete_sync_task_by_id(request: Request, sync_task_id: int, current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    delete_sync_task(db, sync_task_id)
    audit.write_audit_log(
        db,
        actor_user_id=current.user.id,
        action="sync_task.delete",
        target_type="sync_task",
        target_id=str(sync_task_id),
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        success=True,
    )
    db.commit()
    return {"ok": True}


@router.get("/{sync_task_id:int}/executions", response_model=list[SyncExecutionOut], dependencies=[Depends(require_permissions(SYNC_READ))])
def get_sync_task_executions(sync_task_id: int, current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    return [_execution_out(e) for e in list_sync_executions(db, sync_task_id)]


@router.get("/{sync_task_id:int}/executions/latest", response_model=SyncExecutionOut | None, dependencies=[Depends(require_permissions(SYNC_READ))])
def get_sync_task_execution_latest(sync_task_id: int, current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = list_sync_executions(db, sync_task_id, limit=1)
    if not rows:
        return None
    return _execution_out(rows[0])


@router.get(
    "/{sync_task_id:int}/executions/{sync_execution_id:int}/files",
    response_model=list[SyncExecutionFileOut],
    dependencies=[Depends(require_permissions(SYNC_READ))],
)
def get_sync_execution_files(
    sync_task_id: int,
    sync_execution_id: int,
    offset: int = 0,
    limit: int = 500,
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = list_sync_execution_files(db, sync_task_id, sync_execution_id, offset=offset, limit=limit)
    return [
        SyncExecutionFileOut(
            id=r.id,
            sync_execution_id=r.sync_execution_id,
            path=r.path,
            action=r.action,
            status=r.status,
            size=r.size,
            message=r.message,
            updated_at=r.updated_at,
            created_at=r.created_at,
        )
        for r in rows
    ]


@router.post("/local/browse", response_model=PathBrowseOut, dependencies=[Depends(require_permissions(SYNC_READ))])
def post_local_browse(payload: PathBrowseIn, current: CurrentUser = Depends(get_current_user)) -> PathBrowseOut:
    rel, exists, items, paths = browse_local_dir(payload.path)
    out_items = [
        PathBrowseItemOut(
            name=str(it["name"]),
            path=str(it["path"]),
            is_dir=bool(it.get("is_dir")),
            updated_at=it.get("updated_at"),
            size=it.get("size"),
        )
        for it in items[: int(payload.max_items)]
    ]
    out_paths = [PathBrowsePathOut(name=str(p["name"]), path=str(p["path"])) for p in paths]
    return PathBrowseOut(dir_path=str(rel), exists=bool(exists), paths=out_paths, items=out_items)


@router.post("/{sync_task_id:int}/run", response_model=SyncExecutionOut, dependencies=[Depends(require_permissions(SYNC_RUN))])
def post_run_sync_task(
    request: Request,
    sync_task_id: int,
    payload: SyncRunIn | None = None,
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    running = (
        db.execute(
            select(SyncExecution)
            .where(SyncExecution.sync_task_id == sync_task_id, SyncExecution.status == "running", SyncExecution.finished_at.is_(None))
            .order_by(SyncExecution.started_at.desc())
        )
        .scalars()
        .first()
    )
    if running is not None:
        raise ApiError(code="SYNC_TASK_RUNNING", message="同步任务正在执行", http_status=409, detail=str(running.id))
    task = get_sync_task(db, sync_task_id)
    override = payload.strategy.model_dump(mode="json") if payload and payload.strategy else None
    execution = SyncExecutor(db).run_sync_task(task, strategy_override=override)
    audit.write_audit_log(
        db,
        actor_user_id=current.user.id,
        action="sync_task.run",
        target_type="sync_task",
        target_id=str(sync_task_id),
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        success=execution.status == "success",
        detail=execution.message,
    )
    db.commit()
    db.refresh(execution)
    return _execution_out(execution)


@router.post("/{sync_task_id:int}/run/stream", dependencies=[Depends(require_permissions(SYNC_RUN))])
def post_run_sync_task_stream(
    request: Request,
    sync_task_id: int,
    payload: SyncRunIn | None = None,
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    running = (
        db.execute(
            select(SyncExecution)
            .where(SyncExecution.sync_task_id == sync_task_id, SyncExecution.status == "running", SyncExecution.finished_at.is_(None))
            .order_by(SyncExecution.started_at.desc())
        )
        .scalars()
        .first()
    )
    if running is not None:
        raise ApiError(code="SYNC_TASK_RUNNING", message="同步任务正在执行", http_status=409, detail=str(running.id))
    init_payload = {"sync_task_id": int(sync_task_id), "started_at": datetime.now().isoformat()}
    audit.write_audit_log(
        db,
        actor_user_id=current.user.id,
        action="sync_task.run.stream",
        target_type="sync_task",
        target_id=str(sync_task_id),
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        success=True,
    )
    db.commit()

    q: queue.Queue[tuple[str, object]] = queue.Queue()
    done_sentinel = object()

    def emit_line(line: str) -> None:
        q.put(("log", line))

    def emit_stage(stage: str) -> None:
        q.put(("stage", stage))

    def emit_progress(payload: dict) -> None:
        q.put(("progress", dict(payload or {})))

    override = payload.strategy.model_dump(mode="json") if payload and payload.strategy else None

    def worker() -> None:
        with SessionLocal() as wdb:
            log = ExecutionLog(emit_line=emit_line, emit_stage=emit_stage, emit_progress=emit_progress)
            try:
                wtask = get_sync_task(wdb, sync_task_id)
                execution = SyncExecutor(wdb).run_sync_task(wtask, log=log, strategy_override=override)
                wdb.commit()
                wdb.refresh(execution)
                q.put(("done", {"status": execution.status, "message": execution.message, "execution": _execution_out(execution).model_dump(mode="json")}))
            except Exception as exc:
                wdb.rollback()
                message = getattr(exc, "message", None) or str(exc).strip() or type(exc).__name__
                q.put(
                    (
                        "done",
                        {
                            "status": "failed",
                            "message": message,
                            "execution": {
                                "id": 0,
                                "sync_task_id": sync_task_id,
                                "status": "failed",
                                "started_at": log.started_at.isoformat(),
                                "finished_at": datetime.now().isoformat(),
                                "stage": log.stage,
                                "run_log": log.render(),
                                "stats": {},
                                "message": message,
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
            if kind == "progress":
                yield sse("progress", value)
                continue
            if kind == "done":
                yield sse("done", value)
                continue
            if kind == "done_sentinel":
                break

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

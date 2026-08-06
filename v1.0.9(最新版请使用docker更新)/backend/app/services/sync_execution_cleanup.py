from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.sync_execution import SyncExecution
from app.models.sync_execution_file import SyncExecutionFile


def purge_old_sync_executions(db: Session, *, keep_per_task: int = 3) -> dict[str, int]:
    keep = max(0, int(keep_per_task))
    if keep <= 0:
        return {"sync_tasks": 0, "deleted_executions": 0, "deleted_files": 0}

    sync_task_ids = db.execute(select(SyncExecution.sync_task_id).distinct()).scalars().all()
    deleted_executions = 0
    deleted_files = 0
    touched_tasks = 0

    for sync_task_id in sync_task_ids:
        rows = (
            db.execute(
                select(SyncExecution.id, SyncExecution.status, SyncExecution.finished_at)
                .where(SyncExecution.sync_task_id == int(sync_task_id))
                .order_by(SyncExecution.started_at.desc(), SyncExecution.id.desc())
            )
            .all()
        )
        if len(rows) <= keep:
            continue

        keep_ids: set[int] = set(int(x[0]) for x in rows[:keep] if x[0] is not None)
        for exe_id, status, finished_at in rows:
            if exe_id is None:
                continue
            if str(status or "") == "running" and finished_at is None:
                keep_ids.add(int(exe_id))

        to_delete = [int(exe_id) for exe_id, _status, _finished_at in rows if exe_id is not None and int(exe_id) not in keep_ids]
        if not to_delete:
            continue

        touched_tasks += 1
        deleted_files += int(
            db.execute(delete(SyncExecutionFile).where(SyncExecutionFile.sync_execution_id.in_(to_delete))).rowcount or 0
        )
        deleted_executions += int(db.execute(delete(SyncExecution).where(SyncExecution.id.in_(to_delete))).rowcount or 0)

    return {"sync_tasks": int(touched_tasks), "deleted_executions": int(deleted_executions), "deleted_files": int(deleted_files)}


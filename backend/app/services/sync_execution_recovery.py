from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.sync_execution import SyncExecution


def abort_running_sync_executions_on_startup(db: Session) -> int:
    rows = (
        db.execute(select(SyncExecution).where(SyncExecution.status == "running", SyncExecution.finished_at.is_(None)))
        .scalars()
        .all()
    )
    if not rows:
        return 0
    now = datetime.now()
    for r in rows:
        r.status = "aborted"
        r.stage = "aborted"
        r.finished_at = now
        r.heartbeat_at = now
        r.message = "aborted: server restarted"
    return len(rows)


def abort_stale_running_sync_executions(db: Session, *, threshold_seconds: int) -> int:
    threshold = datetime.now() - timedelta(seconds=int(threshold_seconds))
    rows = (
        db.execute(select(SyncExecution).where(SyncExecution.status == "running", SyncExecution.finished_at.is_(None)))
        .scalars()
        .all()
    )
    now = datetime.now()
    n = 0
    for r in rows:
        ts = r.heartbeat_at or r.started_at
        if ts and ts > threshold:
            continue
        r.status = "aborted"
        r.stage = "aborted"
        r.finished_at = now
        r.heartbeat_at = now
        r.message = "aborted: stale (no heartbeat > 2h)"
        n += 1
    return n


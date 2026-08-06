from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.task import Task
from app.models.task_execution import TaskExecution
from app.services.task_scheduler import get_or_create_task_scheduler_setting


def _safe_json_object(value: str | None) -> dict:
    if not value:
        return {}
    try:
        data = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _normalize_weekdays(value: object) -> list[int]:
    arr = value if isinstance(value, list) else []
    days: list[int] = []
    for item in arr:
        try:
            n = int(item)
        except (TypeError, ValueError):
            continue
        if 1 <= n <= 7:
            days.append(n)
    return sorted(set(days))


def _daterange(start: date, end: date) -> list[date]:
    if start > end:
        return []
    days: list[date] = []
    cursor = start
    while cursor <= end:
        days.append(cursor)
        cursor = cursor + timedelta(days=1)
    return days


def build_drama_overview(db: Session, *, days: int = 30) -> dict:
    try:
        window_days = int(days)
    except (TypeError, ValueError):
        window_days = 30
    window_days = max(1, min(365, window_days))
    
    now_utc = datetime.now()
    since = now_utc - timedelta(days=window_days)
    month_start = datetime(now_utc.year, now_utc.month, 1)

    scheduler = get_or_create_task_scheduler_setting(db)
    tasks = (
        db.execute(select(Task).where(Task.task_type == "drama").order_by(Task.id.asc()))
        .scalars()
        .all()
    )

    enabled_task_count = 0
    tmdb_bound_count = 0
    banned_count = 0
    unknown_schedule_count = 0

    for task in tasks:
        if task.enabled:
            enabled_task_count += 1
        if task.tmdb_id is not None:
            tmdb_bound_count += 1
        if str(getattr(task, "shareurl_ban", "") or "").strip():
            banned_count += 1

        if task.enabled and task.tmdb_id is None:
            extra = _safe_json_object(getattr(task, "extra_json", None))
            runweek = _normalize_weekdays(extra.get("runweek"))
            if not runweek:
                unknown_schedule_count += 1

    execution_total = 0
    execution_success = 0
    execution_failed = 0
    execution_skipped = 0
    duration_sum = 0.0
    duration_count = 0
    monthly_success_count = 0

    start_day = since.date()
    end_day = now_utc.date()
        
    trend_map: dict[str, dict[str, object]] = {
        d.isoformat(): {"total": 0, "success": 0, "failed": 0, "skipped": 0, "dur_sum": 0.0, "dur_cnt": 0}
        for d in _daterange(start_day, end_day)
    }

    recent_failures: list[dict] = []

    executions = (
        db.execute(
            select(TaskExecution, Task.taskname)
            .join(Task, Task.id == TaskExecution.task_id)
            .where(Task.task_type == "drama", TaskExecution.started_at >= since)
            .order_by(TaskExecution.started_at.desc())
        )
        .all()
    )

    for execution, taskname in executions:
        status = str(execution.status or "").strip().lower()
        execution_total += 1
        if status == "success":
            execution_success += 1
        elif status == "skipped":
            execution_skipped += 1
        else:
            execution_failed += 1

        started_at = execution.started_at
        day_key = started_at.date().isoformat()
        bucket = trend_map.get(day_key)
        if bucket is not None:
            bucket["total"] = int(bucket["total"]) + 1
            if status == "success":
                bucket["success"] = int(bucket["success"]) + 1
            elif status == "skipped":
                bucket["skipped"] = int(bucket["skipped"]) + 1
            else:
                bucket["failed"] = int(bucket["failed"]) + 1

        finished_at = execution.finished_at if execution.finished_at else None
        if finished_at is not None:
            delta = (finished_at - started_at).total_seconds()
            if delta >= 0 and delta < 3600 * 24 * 2:
                duration_sum += float(delta)
                duration_count += 1
                if bucket is not None:
                    bucket["dur_sum"] = float(bucket["dur_sum"]) + float(delta)
                    bucket["dur_cnt"] = int(bucket["dur_cnt"]) + 1

        if status == "success" and started_at >= month_start:
            monthly_success_count += 1

        if len(recent_failures) < 12 and status == "failed":
            recent_failures.append(
                {
                    "task_id": int(execution.task_id),
                    "taskname": str(taskname or "").strip() or f"任务 #{execution.task_id}",
                    "status": status,
                    "started_at": started_at,
                    "stage": str(execution.stage or "").strip() or None,
                    "message": str(execution.message or "").strip() or None,
                }
            )

    trend: list[dict] = []
    for d in _daterange(start_day, end_day):
        key = d.isoformat()
        bucket = trend_map.get(key) or {}
        dur_cnt = int(bucket.get("dur_cnt") or 0)
        dur_sum = float(bucket.get("dur_sum") or 0.0)
        trend.append(
            {
                "date": key,
                "total": int(bucket.get("total") or 0),
                "success": int(bucket.get("success") or 0),
                "failed": int(bucket.get("failed") or 0),
                "skipped": int(bucket.get("skipped") or 0),
                "avg_duration_s": round(dur_sum / dur_cnt, 2) if dur_cnt > 0 else None,
            }
        )

    effective_total = execution_success + execution_failed
    success_rate = round(execution_success / effective_total, 4) if effective_total > 0 else None
    avg_duration_s = round(duration_sum / duration_count, 2) if duration_count > 0 else None

    return {
        "scheduler": {
            "enabled": bool(scheduler.enabled),
            "crontab": str(scheduler.crontab),
            "timezone": str(scheduler.timezone),
        },
        "summary": {
            "task_count": len(tasks),
            "enabled_task_count": enabled_task_count,
            "tmdb_bound_count": tmdb_bound_count,
            "banned_count": banned_count,
            "unknown_schedule_count": unknown_schedule_count,
            "monthly_success_count": monthly_success_count,
            "window_days": window_days,
            "execution_total": execution_total,
            "execution_success": execution_success,
            "execution_failed": execution_failed,
            "execution_skipped": execution_skipped,
            "success_rate": success_rate,
            "avg_duration_s": avg_duration_s,
        },
        "trend": trend,
        "recent_failures": recent_failures,
        "updated_at": now_utc,
    }

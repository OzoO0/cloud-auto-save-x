from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import select

from app.db.session import SessionLocal
from app.extensions.runtime.sync_executor import SyncExecutor
from app.models.sync_execution import SyncExecution
from app.models.sync_task import SyncTask
from app.models.sync_task_drama_link import SyncTaskDramaLink


logger = logging.getLogger(__name__)
_executor = ThreadPoolExecutor(max_workers=1)


def trigger_linked_sync_tasks_async(task_uids: list[str], *, source: str) -> None:
    uids = _normalize_task_uids(task_uids)
    if not uids:
        return
    _executor.submit(_run_linked_sync_tasks, uids, str(source or ""))


def should_trigger_linked_sync_for_drama_execution(execution: object | None) -> bool:
    if execution is None:
        return False
    if str(getattr(execution, "status", "") or "") != "success":
        return False
    tree_summary = str(getattr(execution, "tree_summary", "") or "")
    if "无可转存文件" in tree_summary:
        return False
    run_log = str(getattr(execution, "run_log", "") or "")
    for m in re.finditer(r"saved_fids:\s*(\d+)", run_log):
        try:
            if int(m.group(1)) > 0:
                return True
        except Exception:
            continue
    if " -> " in tree_summary:
        return True
    return False


def _normalize_task_uids(values: list[str] | None) -> list[str]:
    if not values:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for raw in values:
        uid = str(raw or "").strip()
        if not uid or uid in seen:
            continue
        seen.add(uid)
        out.append(uid)
    return out


def _run_linked_sync_tasks(task_uids: list[str], source: str) -> None:
    with SessionLocal() as db:
        try:
            links = db.execute(select(SyncTaskDramaLink.sync_task_uid).where(SyncTaskDramaLink.task_uid.in_(task_uids))).scalars().all()
            sync_uids = _normalize_task_uids([str(x) for x in links if x])
            if not sync_uids:
                return

            tasks = (
                db.execute(select(SyncTask).where(SyncTask.uid.in_(sync_uids), SyncTask.enabled.is_(True)).order_by(SyncTask.id.asc()))
                .scalars()
                .all()
            )
            if not tasks:
                return

            logger.info("触发关联同步任务 source=%s drama_tasks=%s sync_tasks=%s", source, len(task_uids), len(tasks))
            skipped = 0
            failed = 0
            success = 0

            executor = SyncExecutor(db)
            for task in tasks:
                running = (
                    db.execute(
                        select(SyncExecution.id).where(
                            SyncExecution.sync_task_id == int(task.id),
                            SyncExecution.status == "running",
                            SyncExecution.finished_at.is_(None),
                        )
                    )
                    .scalars()
                    .first()
                )
                if running is not None:
                    skipped += 1
                    logger.info("跳过同步任务：正在运行 sync_task_id=%s uid=%s name=%s running_execution_id=%s", task.id, task.uid, task.name, running)
                    continue
                try:
                    executor.run_sync_task(task)
                    success += 1
                except Exception as e:
                    failed += 1
                    db.rollback()
                    logger.warning("同步任务执行失败 sync_task_id=%s uid=%s name=%s err=%s", task.id, task.uid, task.name, str(e).strip() or type(e).__name__)

            logger.info(
                "关联同步任务触发完成 source=%s drama_tasks=%s sync_tasks=%s success=%s skipped=%s failed=%s",
                source,
                len(task_uids),
                len(tasks),
                success,
                skipped,
                failed,
            )
        except Exception as e:
            db.rollback()
            logger.exception("关联同步任务触发异常 source=%s err=%s", source, str(e).strip() or type(e).__name__)

from __future__ import annotations

from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.sync_execution import SyncExecution
from app.models.sync_execution_file import SyncExecutionFile
from app.models.sync_task import SyncTask
from app.services.notifications.sender import send_runtime
from app.services.notifications.task_notify import DRAMA_NOTIFY_TITLE


SYNC_NOTIFY_TITLE = DRAMA_NOTIFY_TITLE


def _strip_root_prefix(task: SyncTask, abs_path: str) -> str:
    raw = str(abs_path or "").replace("\\", "/").strip()
    if not raw:
        return ""
    if str(getattr(task, "target_type", "") or "") == "openlist":
        root = str(getattr(task, "target_path", "") or "").replace("\\", "/").strip() or "/"
        if not root.startswith("/"):
            root = "/" + root
        root = "/".join([p for p in root.split("/") if p])
        root = "/" + root if root else "/"
        if root != "/" and raw.startswith(root + "/"):
            return raw[len(root) + 1 :].lstrip("/")
        if root == raw:
            return ""
        return raw.lstrip("/")
    base = str(getattr(task, "target_path", "") or "").replace("\\", "/").strip().lstrip("/")
    prefix = "data/sync/"
    if base:
        prefix = prefix + base.rstrip("/") + "/"
    if raw.startswith(prefix):
        return raw[len(prefix) :].lstrip("/")
    if raw.startswith("data/sync/"):
        return raw[len("data/sync/") :].lstrip("/")
    return raw.lstrip("/")


def _build_ascii_tree(paths: Iterable[str]) -> str:
    uniq = sorted({p for p in [str(x or "").strip() for x in paths] if p})
    if not uniq:
        return ""
    root: dict[str, dict] = {}
    for p in uniq:
        parts = [x for x in str(p).split("/") if x]
        node = root
        for part in parts:
            child = node.get(part)
            if not isinstance(child, dict):
                child = {}
                node[part] = child
            node = child

    lines: list[str] = []

    def walk(node: dict[str, dict], prefix: str) -> None:
        items = list(node.items())
        for idx, (name, child) in enumerate(items):
            last = idx == len(items) - 1
            branch = "└── " if last else "├── "
            lines.append(prefix + branch + str(name))
            if child:
                ext = "    " if last else "│   "
                walk(child, prefix + ext)

    walk(root, "")
    return "\n".join(lines)


def build_sync_execution_section(task: SyncTask, execution: SyncExecution, files: list[SyncExecutionFile]) -> tuple[str, bool]:
    if str(getattr(execution, "status", "") or "") != "success":
        return "", False
    copied = [_strip_root_prefix(task, r.path) for r in files if str(r.status or "") == "success" and str(r.action or "") == "copy"]
    deleted = [_strip_root_prefix(task, r.path) for r in files if str(r.status or "") == "success" and str(r.action or "") == "delete"]
    copied = [p for p in copied if p]
    deleted = [p for p in deleted if p]
    if not copied and not deleted:
        return "", False

    name = str(getattr(task, "name", "") or "")
    mode = str(getattr(task, "mode", "") or "one_way")
    source = f"{getattr(task, 'source_type', '')}:{getattr(task, 'source_path', '')}"
    target = f"{getattr(task, 'target_type', '')}:{getattr(task, 'target_path', '')}"

    def cap(items: list[str], limit: int) -> tuple[list[str], int]:
        uniq = sorted(set([str(x or "").strip() for x in items if str(x or "").strip()]))
        if len(uniq) <= limit:
            return uniq, 0
        return uniq[:limit], len(uniq) - limit

    copied_view, copied_extra = cap(copied, 50)
    deleted_view, deleted_extra = cap(deleted, 50)

    parts: list[str] = []
    parts.append(f"✅同步《{name}》完成")
    parts.append(f"模式: {mode}")
    parts.append(f"源: {source}")
    parts.append(f"目标: {target}")
    if copied:
        tree = _build_ascii_tree(copied_view)
        parts.append(f"新增/更新({len(set(copied))}):")
        parts.append(tree or "└── (empty)")
        if copied_extra:
            parts.append(f"…（其余 {copied_extra} 项略）")
    if deleted:
        tree = _build_ascii_tree(deleted_view)
        parts.append(f"删除({len(set(deleted))}):")
        parts.append(tree or "└── (empty)")
        if deleted_extra:
            parts.append(f"…（其余 {deleted_extra} 项略）")
    return "\n".join([p for p in parts if p is not None]), True


def send_sync_execution_notification(db: Session, task: SyncTask, execution: SyncExecution) -> None:
    try:
        status = str(getattr(execution, "status", "") or "")
        if status not in {"success", "failed"}:
            return
        execution_id = int(getattr(execution, "id", 0) or 0)
        if execution_id <= 0:
            return
        name = str(getattr(task, "name", "") or "")
        mode = str(getattr(task, "mode", "") or "one_way")
        source = f"{getattr(task, 'source_type', '')}:{getattr(task, 'source_path', '')}"
        target = f"{getattr(task, 'target_type', '')}:{getattr(task, 'target_path', '')}"

        if status == "failed":
            stage = str(getattr(execution, "stage", "") or "")
            message = str(getattr(execution, "message", "") or "").strip()
            parts = []
            parts.append(f"❌同步《{name}》失败")
            parts.append(f"模式: {mode}")
            parts.append(f"源: {source}")
            parts.append(f"目标: {target}")
            if stage:
                parts.append(f"阶段: {stage}")
            if message:
                parts.append(f"原因: {message}")
            send_runtime(db, SYNC_NOTIFY_TITLE, "\n".join([p for p in parts if p]))
            return

        rows = (
            db.execute(select(SyncExecutionFile).where(SyncExecutionFile.sync_execution_id == execution_id).order_by(SyncExecutionFile.id.asc()))
            .scalars()
            .all()
        )
        content, should = build_sync_execution_section(task, execution, rows)
        if should and content:
            send_runtime(db, SYNC_NOTIFY_TITLE, content)
    except Exception:
        return

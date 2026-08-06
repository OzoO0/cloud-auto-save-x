from __future__ import annotations

import re

from app.models.task import Task
from app.models.task_execution import TaskExecution


DRAMA_NOTIFY_TITLE = "【智能追剧平台】"


def _normalize_savepath(value: str) -> str:
    s = str(value or "").strip()
    if not s:
        return "/"
    if not s.startswith("/"):
        s = "/" + s
    return re.sub(r"/{2,}", "/", s)


def extract_root_new_files(tree_summary: str | None) -> list[str]:
    if not tree_summary:
        return []
    result: list[str] = []
    for raw in str(tree_summary).splitlines():
        if "->" not in raw:
            continue
        right = str(raw).split("->", 1)[1].strip()
        if right:
            result.append(right)
    return result


def format_root_file_tree(names: list[str]) -> str:
    if not names:
        return ""
    if len(names) == 1:
        return f"└── 🎞️{names[0]}"
    lines: list[str] = []
    for idx, name in enumerate(names):
        prefix = "└── " if idx == len(names) - 1 else "├── "
        lines.append(f"{prefix}🎞️{name}")
    return "\n".join(lines)


def build_task_section(task: Task, execution: TaskExecution) -> tuple[str, bool]:
    status = str(getattr(execution, "status", "") or "")
    taskname = str(getattr(task, "taskname", "") or "")
    message = str(getattr(execution, "message", "") or "").strip()

    if status == "success":
        names = extract_root_new_files(getattr(execution, "tree_summary", None))
        if not names:
            return "", False
        savepath = _normalize_savepath(str(getattr(task, "savepath", "") or ""))
        tree = format_root_file_tree(names)
        section = f"✅《{taskname}》添加追更：\n{savepath}\n{tree}"
        return section, True

    if status == "skipped":
        return "", False

    if status == "failed":
        text = message or "未知错误"
        section = f"❌《{taskname}》执行失败：\n{text}"
        return section, True

    return "", False

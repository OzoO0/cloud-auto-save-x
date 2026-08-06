from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable
from zoneinfo import ZoneInfo


@dataclass
class ExecutionLog:
    lines: list[str] = field(default_factory=list)
    stage: str | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now())
    emit_line: Callable[[str], None] | None = field(default=None, repr=False)
    emit_stage: Callable[[str], None] | None = field(default=None, repr=False)
    emit_progress: Callable[[dict[str, Any]], None] | None = field(default=None, repr=False)

    def set_stage(self, stage: str | None) -> None:
        self.stage = stage
        if self.emit_stage and stage:
            self.emit_stage(str(stage))

    def section(self, title: str) -> None:
        title = str(title or "").strip() or "阶段"
        line = f"==============={title}==============="
        self.lines.append(line)
        if self.emit_line:
            self.emit_line(line)

    def line(self, text: str = "") -> None:
        line = str(text)
        self.lines.append(line)
        if self.emit_line:
            self.emit_line(line)

    def progress(self, payload: dict[str, Any]) -> None:
        if self.emit_progress:
            self.emit_progress(dict(payload or {}))

    def render(self) -> str:
        return "\n".join(self.lines).rstrip() + "\n"

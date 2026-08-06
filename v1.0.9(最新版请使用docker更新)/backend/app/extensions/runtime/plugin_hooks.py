from __future__ import annotations

import sys
import threading
from contextlib import contextmanager
from typing import Any


_capture_lock = threading.RLock()


class _LineWriter:
    def __init__(self, emit_line, prefix: str):
        self.emit_line = emit_line
        self.prefix = prefix
        self._buf = ""

    def write(self, s: str) -> int:
        if not s:
            return 0
        text = str(s).replace("\r\n", "\n").replace("\r", "\n")
        self._buf += text
        while "\n" in self._buf:
            line, rest = self._buf.split("\n", 1)
            self._buf = rest
            out = line.strip()
            if out:
                self.emit_line(f"{self.prefix}{out}")
        return len(s)

    def flush(self) -> None:
        out = self._buf.strip()
        self._buf = ""
        if out:
            self.emit_line(f"{self.prefix}{out}")


@contextmanager
def _capture_print(emit_line, *, prefix: str):
    if emit_line is None:
        yield
        return
    with _capture_lock:
        old_out = sys.stdout
        old_err = sys.stderr
        writer = _LineWriter(emit_line, prefix)
        sys.stdout = writer
        sys.stderr = writer
        try:
            yield
        finally:
            try:
                writer.flush()
            finally:
                sys.stdout = old_out
                sys.stderr = old_err


class PluginHookRunner:
    @staticmethod
    def task_before(
        plugins: list[dict[str, Any]],
        tasks: list[dict[str, Any]],
        account: Any,
        *,
        emit_line=None,
    ) -> list[dict[str, Any]]:
        current = tasks
        for item in plugins:
            plugin = item['instance']
            definition = item.get("definition")
            key = getattr(definition, "plugin_key", None) or ""
            prefix = f"[{key}] " if key else ""
            if not getattr(plugin, 'is_active', False):
                if emit_line is not None and key:
                    emit_line(f"{prefix}skipped: inactive")
                continue
            if not hasattr(plugin, 'task_before'):
                continue
            if emit_line is not None and key:
                emit_line(f"{prefix}task_before")
            with _capture_print(emit_line, prefix=prefix):
                current = plugin.task_before(tasklist=current, account=account) or current
        return current

    @staticmethod
    def run(
        plugins: list[dict[str, Any]],
        task: dict[str, Any],
        account: Any,
        tree: Any,
        *,
        emit_line=None,
    ) -> dict[str, Any]:
        current = task
        for item in plugins:
            plugin = item['instance']
            definition = item.get("definition")
            key = getattr(definition, "plugin_key", None) or ""
            prefix = f"[{key}] " if key else ""
            if not getattr(plugin, 'is_active', False):
                if emit_line is not None and key:
                    emit_line(f"{prefix}skipped: inactive")
                continue
            if not hasattr(plugin, 'run'):
                continue
            if emit_line is not None and key:
                emit_line(f"{prefix}run")
            with _capture_print(emit_line, prefix=prefix):
                current = plugin.run(current, account=account, tree=tree) or current
        return current

    @staticmethod
    def task_after(
        plugins: list[dict[str, Any]],
        tasks: list[dict[str, Any]],
        account: Any,
        *,
        emit_line=None,
    ) -> list[dict[str, Any]]:
        current = tasks
        for item in plugins:
            plugin = item['instance']
            definition = item.get("definition")
            key = getattr(definition, "plugin_key", None) or ""
            prefix = f"[{key}] " if key else ""
            if not getattr(plugin, 'is_active', False):
                if emit_line is not None and key:
                    emit_line(f"{prefix}skipped: inactive")
                continue
            if not hasattr(plugin, 'task_after'):
                continue
            if emit_line is not None and key:
                emit_line(f"{prefix}task_after")
            with _capture_print(emit_line, prefix=prefix):
                result = plugin.task_after(tasklist=current, account=account) or {}
            current = result.get('tasklist', current)
        return current

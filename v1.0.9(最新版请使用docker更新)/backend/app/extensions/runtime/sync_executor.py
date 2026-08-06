from __future__ import annotations

import json
import logging
import os
import posixpath
import secrets
import shutil
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from treelib import Tree

from app.core.errors import ApiError, bad_request
from app.db.session import SessionLocal
from app.extensions.runtime.execution_log import ExecutionLog
from app.extensions.runtime.plugin_hooks import PluginHookRunner
from app.extensions.runtime.sync_plugin_loader import sync_sync_plugin_definitions
from app.extensions.runtime.sync_plugin_registry import SyncPluginRegistry
from app.models.sync_execution import SyncExecution
from app.models.sync_execution_file import SyncExecutionFile
from app.models.sync_file_snapshot import SyncFileSnapshot
from app.models.sync_task import SyncTask
from app.models.sync_task_lock import SyncTaskLock
from app.services.notifications.sync_notify import send_sync_execution_notification
from app.services.openlist_client_factory import get_openlist_client

logger = logging.getLogger(__name__)


EndpointType = Literal["local", "openlist"]


@dataclass(frozen=True, slots=True)
class FileMeta:
    is_dir: bool
    size: int
    modified_at: float


@dataclass(frozen=True, slots=True)
class Endpoint:
    type: EndpointType
    path: str


@dataclass(frozen=True, slots=True)
class Strategy:
    overwrite: bool
    one_way_delete_extras: bool
    force_refresh: bool
    concurrency: int
    request_interval_seconds: float
    openlist_copy_batch_size: int


class SyncCancelled(Exception):
    def __init__(self, message: str = "cancelled"):
        super().__init__(message)
        self.message = message


class _CancelChecker:
    def __init__(self, sync_execution_id: int):
        self.sync_execution_id = int(sync_execution_id)
        self._cancelled = False
        self._message: str | None = None
        self._last_check_ts = 0.0

    @property
    def message(self) -> str | None:
        return self._message

    def is_cancelled(self) -> bool:
        if self._cancelled:
            return True
        now_ts = _now_ts()
        if now_ts - self._last_check_ts < 0.8:
            return False
        self._last_check_ts = now_ts
        with SessionLocal() as rdb:
            row = (
                rdb.execute(
                    select(SyncExecution.cancel_requested_at, SyncExecution.cancel_message).where(SyncExecution.id == self.sync_execution_id)
                )
                .first()
            )
        if not row:
            return False
        cancel_requested_at, cancel_message = row
        if cancel_requested_at is None:
            return False
        self._cancelled = True
        self._message = str(cancel_message).strip() if cancel_message else None
        return True

    def raise_if_cancelled(self) -> None:
        if self.is_cancelled():
            raise SyncCancelled(self._message or "cancelled")


def _now_ts() -> float:
    return time.time()


def _parse_iso_ts(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s:
        return 0.0
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception:
        return 0.0


def _norm_rel(p: str) -> str:
    p = str(p or "").replace("\\", "/").strip()
    p = p.lstrip("/")
    if not p:
        return ""
    p = posixpath.normpath(p)
    if p == ".":
        return ""
    return p


def _join_openlist(root: str, rel: str) -> str:
    root = str(root or "").strip() or "/"
    if not root.startswith("/"):
        root = "/" + root
    root = posixpath.normpath(root)
    rel = _norm_rel(rel)
    if not rel:
        return root
    return posixpath.normpath(posixpath.join(root, rel))


def _local_sync_root() -> Path:
    backend_dir = Path(__file__).resolve().parents[3]
    return backend_dir / "data" / "sync"


def _resolve_local_path(base: Path, rel: str) -> Path:
    rel = _norm_rel(rel)
    full = (base / rel).resolve()
    base_resolved = base.resolve()
    try:
        full.relative_to(base_resolved)
    except Exception:
        raise bad_request("SYNC_LOCAL_PATH_FORBIDDEN", "本地路径不允许")
    return full


def _same_meta(a: FileMeta | None, b: FileMeta | None) -> bool:
    if a is None or b is None:
        return False
    if a.is_dir != b.is_dir:
        return False
    if a.is_dir:
        return True
    return int(a.size) == int(b.size) and int(a.modified_at) == int(b.modified_at)


def _tmp_name(name: str) -> str:
    token = secrets.token_hex(4)
    return f".{str(name)}.sync_tmp_{token}"


def _conflict_path(rel: str, ts: str) -> str:
    rel = _norm_rel(rel)
    base, ext = posixpath.splitext(rel)
    return f"{base}(conflict-{ts}){ext}"


class SyncExecutor:
    def __init__(self, db: Session):
        self.db = db
        self._openlist_client = None

    def _get_openlist_client(self):
        if self._openlist_client is None:
            self._openlist_client = get_openlist_client(self.db)
        return self._openlist_client

    def run_sync_task(
        self,
        task: SyncTask,
        *,
        log: ExecutionLog | None = None,
        strategy_override: dict[str, Any] | None = None,
    ) -> SyncExecution:
        if not bool(getattr(task, "enabled", True)):
            raise bad_request("SYNC_TASK_DISABLED", "同步任务已禁用")

        log = log or ExecutionLog()
        log.set_stage("start")
        log.section("同步开始")
        log.line(f"执行时间: {log.started_at.strftime('%Y-%m-%d %H:%M:%S')}")
        log.line(f"任务名称: {str(getattr(task, 'name', '') or '')}")
        log.line("")

        source = Endpoint(type=str(task.source_type or "").strip(), path=str(task.source_path or "").strip())
        target = Endpoint(type=str(task.target_type or "").strip(), path=str(task.target_path or "").strip())
        mode = str(getattr(task, "mode", "") or "one_way").strip() or "one_way"
        if source.type == "openlist" or target.type == "openlist":
            self._get_openlist_client()

        strategy = self._load_strategy(task, override=strategy_override)
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "sync start sync_task_id=%s mode=%s source=%s:%s target=%s:%s strategy=%s override=%s",
                int(getattr(task, "id", 0) or 0),
                mode,
                source.type,
                source.path,
                target.type,
                target.path,
                json.dumps(
                    {
                        "overwrite": bool(strategy.overwrite),
                        "one_way_delete_extras": bool(strategy.one_way_delete_extras),
                        "force_refresh": bool(strategy.force_refresh),
                        "concurrency": int(strategy.concurrency),
                        "request_interval_seconds": float(strategy.request_interval_seconds),
                        "openlist_copy_batch_size": int(strategy.openlist_copy_batch_size),
                    },
                    ensure_ascii=False,
                ),
                json.dumps(strategy_override or {}, ensure_ascii=False) if strategy_override else None,
            )

        task_id = int(getattr(task, "id", 0) or 0)
        lock_owner = f"{os.getpid()}:{threading.get_ident()}"
        try:
            lock_now = datetime.now()
            self.db.add(SyncTaskLock(sync_task_id=task_id, locked_at=lock_now, owner=lock_owner))
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            raise ApiError(code="SYNC_TASK_RUNNING", message="同步任务正在执行", http_status=409, detail=str(task_id))

        def _release_lock() -> None:
            try:
                with SessionLocal() as ldb:
                    ldb.execute(delete(SyncTaskLock).where(SyncTaskLock.sync_task_id == task_id))
                    ldb.commit()
            except Exception:
                pass

        now = datetime.now()
        execution = SyncExecution(
            sync_task_id=task_id,
            status="running",
            stage=log.stage,
            started_at=now,
            created_at=now,
            heartbeat_at=now,
        )
        execution.stats_json = json.dumps(
            {
                "total_files": 0,
                "done_files": 0,
                "copied_files": 0,
                "deleted_files": 0,
                "skipped_files": 0,
                "failed_files": 0,
                "recent_events": [],
            },
            ensure_ascii=False,
        )
        try:
            self.db.add(execution)
            self.db.flush()
            self.db.commit()
        except Exception:
            self.db.rollback()
            _release_lock()
            raise
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("sync execution created sync_task_id=%s sync_execution_id=%s", int(task.id), int(execution.id))

        cancel_checker = _CancelChecker(int(execution.id))

        try:
            cancel_checker.raise_if_cancelled()
            log.set_stage("scan")
            log.section("扫描文件")

            if target.type == "openlist":
                try:
                    client = self._get_openlist_client()
                    log.line(f"确保目标目录存在: {_join_openlist(target.path, '')}")
                    self._ensure_openlist_abs_dir(client, target.path, log=log)
                except Exception as e:
                    log.line(f"目标目录创建失败: type=openlist path={target.path} err={str(e).strip() or type(e).__name__}")
            if mode == "two_way" and source.type == "openlist":
                try:
                    client = self._get_openlist_client()
                    log.line(f"确保源目录存在: {_join_openlist(source.path, '')}")
                    self._ensure_openlist_abs_dir(client, source.path, log=log)
                except Exception as e:
                    log.line(f"源目录创建失败: type=openlist path={source.path} err={str(e).strip() or type(e).__name__}")

            try:
                log.line(f"扫描源端: type={source.type} path={source.path}")
                source_map = self._scan_endpoint(source, strategy=strategy, cancel_checker=cancel_checker)
            except Exception as e:
                log.line(f"扫描源端失败: type={source.type} path={source.path} err={str(e).strip() or type(e).__name__}")
                raise
            try:
                log.line(f"扫描目标端: type={target.type} path={target.path}")
                target_map = self._scan_endpoint(target, strategy=strategy, cancel_checker=cancel_checker)
            except Exception as e:
                log.line(f"扫描目标端失败: type={target.type} path={target.path} err={str(e).strip() or type(e).__name__}")
                raise

            log.line(f"源: {len(source_map)} 项")
            log.line(f"目标: {len(target_map)} 项")

            log.set_stage("diff")
            log.section("生成差异")

            actions = self._build_actions(
                source=source,
                target=target,
                mode=mode,
                strategy=strategy,
                source_map=source_map,
                target_map=target_map,
                sync_task_id=int(task.id),
            )

            log.line(f"动作数: {len(actions)}")
            for a in actions:
                try:
                    if str(a.get("kind") or "") != "copy":
                        continue
                    src_ep = a.get("src")
                    if not isinstance(src_ep, Endpoint):
                        continue
                    src_rel = _norm_rel(str(a.get("src_rel") or ""))
                    meta = None
                    if src_ep == source:
                        meta = source_map.get(src_rel)
                    elif src_ep == target:
                        meta = target_map.get(src_rel)
                    if meta is None or meta.is_dir:
                        continue
                    a["_size"] = int(meta.size)
                except Exception:
                    continue
            if logger.isEnabledFor(logging.DEBUG):
                head = []
                for a in actions[:10]:
                    try:
                        src: Endpoint | None = a.get("src") if isinstance(a.get("src"), Endpoint) else None
                        dst: Endpoint | None = a.get("dst") if isinstance(a.get("dst"), Endpoint) else None
                        head.append(
                            {
                                "kind": str(a.get("kind") or ""),
                                "src": f"{src.type}:{src.path}" if src else None,
                                "dst": f"{dst.type}:{dst.path}" if dst else None,
                                "src_rel": str(a.get("src_rel") or ""),
                                "dst_rel": str(a.get("dst_rel") or ""),
                                "dst_exists": bool(a.get("dst_exists")) if a.get("dst_exists") is not None else None,
                                "conflict": bool(a.get("conflict")) if a.get("conflict") is not None else None,
                            }
                        )
                    except Exception:
                        continue
                logger.debug(
                    "sync actions built sync_execution_id=%s total=%s head=%s",
                    int(execution.id),
                    len(actions),
                    json.dumps(head, ensure_ascii=False),
                )

            log.set_stage("apply")
            log.section("执行同步")

            max_events = 500
            def display_path(ep: Endpoint, rel: str) -> str:
                rel = _norm_rel(rel)
                if ep.type == "openlist":
                    return _join_openlist(ep.path, rel)
                base = _norm_rel(ep.path)
                if base:
                    return posixpath.normpath(posixpath.join("data/sync", base, rel))
                return posixpath.normpath(posixpath.join("data/sync", rel))

            file_rows: dict[str, dict[str, Any]] = {}
            if mode == "one_way":
                for rel, meta in source_map.items():
                    if meta.is_dir:
                        continue
                    p = display_path(target, rel)
                    if not p:
                        continue
                    tmeta = target_map.get(rel)
                    status = "pending"
                    message = None
                    if tmeta is not None and not tmeta.is_dir:
                        if not strategy.overwrite:
                            status = "skipped"
                            message = "exists"
                        elif _same_meta(meta, tmeta):
                            status = "skipped"
                            message = "up_to_date"
                    file_rows[p] = {"action": "copy", "size": int(meta.size), "status": status, "message": message}

                if strategy.one_way_delete_extras:
                    for rel, meta in target_map.items():
                        if meta.is_dir:
                            continue
                        if rel in source_map:
                            continue
                        p = display_path(target, rel)
                        if not p:
                            continue
                        file_rows[p] = {"action": "delete", "size": int(meta.size), "status": "pending", "message": None}
            else:
                for a in actions:
                    kind = str(a.get("kind") or "")
                    if kind not in {"copy", "delete"}:
                        continue
                    dst: Endpoint = a["dst"]
                    dst_rel = str(a.get("dst_rel") or "")
                    p = display_path(dst, dst_rel)
                    if not p:
                        continue
                    action = "copy" if kind == "copy" else "delete"
                    size = None
                    if kind == "copy":
                        src: Endpoint = a["src"]
                        src_rel = _norm_rel(str(a.get("src_rel") or ""))
                        meta = None
                        if src == source:
                            meta = source_map.get(src_rel)
                        elif src == target:
                            meta = target_map.get(src_rel)
                        if meta and not meta.is_dir:
                            size = int(meta.size)
                    if p not in file_rows:
                        file_rows[p] = {"action": action, "size": size, "status": "pending", "message": None}

            init_done = int(sum(1 for v in file_rows.values() if str(v.get("status")) in {"success", "skipped", "failed"}))
            init_skipped = int(sum(1 for v in file_rows.values() if str(v.get("status")) == "skipped"))
            stats: dict[str, Any] = {
                "total_files": int(len(file_rows)),
                "done_files": init_done,
                "copied_files": 0,
                "deleted_files": 0,
                "skipped_files": init_skipped,
                "failed_files": 0,
                "recent_events": [],
            }

            if file_rows and execution.id:
                now = datetime.now()
                self.db.execute(delete(SyncExecutionFile).where(SyncExecutionFile.sync_execution_id == int(execution.id)))
                self.db.add_all(
                    [
                        SyncExecutionFile(
                            sync_execution_id=int(execution.id),
                            path=str(p),
                            action=str(v.get("action") or "copy"),
                            status=str(v.get("status") or "pending"),
                            size=v.get("size"),
                            message=v.get("message"),
                            created_at=now,
                            updated_at=now,
                        )
                        for p, v in file_rows.items()
                    ]
                )
                self.db.commit()

            last_persist = 0.0
            pending_file_updates: dict[str, dict[str, Any]] = {}

            def persist(force: bool = False) -> None:
                nonlocal last_persist
                now_ts = _now_ts()
                if not force and now_ts - last_persist < 0.8:
                    return
                last_persist = now_ts
                updates = list(pending_file_updates.items())
                pending_file_updates.clear()
                if len(updates) > 200:
                    keep = updates[200:]
                    for k, v in keep:
                        pending_file_updates[k] = v
                    updates = updates[:200]
                with SessionLocal() as w:
                    w.execute(
                        update(SyncExecution)
                        .where(SyncExecution.id == int(execution.id))
                        .values(
                            stage=log.stage,
                            heartbeat_at=datetime.now(),
                            stats_json=json.dumps(stats, ensure_ascii=False),
                            run_log=log.render(),
                        )
                    )
                    for p, payload in updates:
                        w.execute(
                            update(SyncExecutionFile)
                            .where(SyncExecutionFile.sync_execution_id == int(execution.id), SyncExecutionFile.path == str(p))
                            .values(**payload)
                        )
                    w.commit()

            def update_file_row(path: str, *, action: str, status: str, size: int | None = None, message: str | None = None) -> None:
                if not path:
                    return
                payload: dict[str, Any] = {"action": str(action), "status": str(status), "updated_at": datetime.now()}
                if size is not None:
                    payload["size"] = int(size)
                if message is not None:
                    payload["message"] = str(message)
                pending_file_updates[str(path)] = payload

            def emit_progress(event: dict[str, Any] | None = None) -> None:
                payload: dict[str, Any] = {
                    "total_files": int(stats.get("total_files") or 0),
                    "done_files": int(stats.get("done_files") or 0),
                    "copied_files": int(stats.get("copied_files") or 0),
                    "deleted_files": int(stats.get("deleted_files") or 0),
                    "skipped_files": int(stats.get("skipped_files") or 0),
                    "failed_files": int(stats.get("failed_files") or 0),
                }
                if event is not None:
                    payload["event"] = event
                log.progress(payload)

            persist(True)
            emit_progress(None)

            self._apply_actions(
                actions,
                strategy=strategy,
                log=log,
                sync_execution_id=int(execution.id),
                on_event=emit_progress,
                on_persist=persist,
                max_events=max_events,
                stats=stats,
                display_path=display_path,
                on_file_update=update_file_row,
                cancel_checker=cancel_checker,
            )

            if mode == "two_way":
                log.set_stage("rescan")
                log.section("刷新快照")
                cancel_checker.raise_if_cancelled()
                source_map = self._scan_endpoint(source, strategy=strategy, cancel_checker=cancel_checker)
                target_map = self._scan_endpoint(target, strategy=strategy, cancel_checker=cancel_checker)

            self._persist_snapshots(int(task.id), source_map, target_map)

            copied_files = int(stats.get("copied_files") or 0)
            if copied_files <= 0:
                log.set_stage("sync_plugin_run")
                log.section("插件执行")
                log.line("跳过: 本次无新增同步文件")
            else:
                try:
                    sync_sync_plugin_definitions(self.db)
                    plugins = SyncPluginRegistry(self.db).load_active_plugins()
                    if plugins:
                        addition = {}
                        raw_addition = getattr(task, "addition_json", None)
                        if raw_addition:
                            try:
                                parsed = json.loads(raw_addition)
                            except Exception:
                                parsed = None
                            if isinstance(parsed, dict):
                                addition = parsed

                        sync_task_data: dict[str, Any] = {
                            "uid": str(getattr(task, "uid", "") or ""),
                            "name": str(getattr(task, "name", "") or ""),
                            "enabled": bool(getattr(task, "enabled", True)),
                            "source": {"type": source.type, "path": source.path},
                            "target": {"type": target.type, "path": target.path},
                            "mode": str(mode),
                            "strategy": {
                                "overwrite": bool(strategy.overwrite),
                                "one_way_delete_extras": bool(strategy.one_way_delete_extras),
                                "force_refresh": bool(strategy.force_refresh),
                                "concurrency": int(strategy.concurrency),
                                "request_interval_seconds": float(strategy.request_interval_seconds),
                                "openlist_copy_batch_size": int(strategy.openlist_copy_batch_size),
                            },
                            "addition": addition,
                            "execution_id": int(getattr(execution, "id", 0) or 0),
                            "stats": stats,
                        }

                        sync_tree = Tree()
                        sync_tree.create_node(
                            str(sync_task_data.get("name") or "sync"),
                            "root",
                            data={"type": "sync_task", "uid": sync_task_data.get("uid")},
                        )
                        file_rows_for_tree = (
                            self.db.execute(
                                select(SyncExecutionFile)
                                .where(SyncExecutionFile.sync_execution_id == int(execution.id))
                                .order_by(SyncExecutionFile.path.asc())
                            )
                            .scalars()
                            .all()
                        )
                        for row in file_rows_for_tree[:5000]:
                            p = str(getattr(row, "path", "") or "").strip()
                            if not p:
                                continue
                            segments = [s for s in p.strip("/").split("/") if s]
                            parent = "root"
                            cur = ""
                            for seg in segments[:-1]:
                                cur = f"{cur}/{seg}" if cur else seg
                                if not sync_tree.contains(cur):
                                    sync_tree.create_node(seg, cur, parent=parent, data={"is_dir": True, "path": cur})
                                parent = cur
                            leaf_id = f"{cur}/{segments[-1]}" if segments else p
                            if not sync_tree.contains(leaf_id):
                                sync_tree.create_node(
                                    segments[-1] if segments else p,
                                    leaf_id,
                                    parent=parent,
                                    data={
                                        "path": p,
                                        "action": getattr(row, "action", None),
                                        "status": getattr(row, "status", None),
                                        "size": getattr(row, "size", None),
                                        "message": getattr(row, "message", None),
                                        "is_dir": False,
                                    },
                                )

                        log.set_stage("sync_plugin_task_before")
                        log.section("插件前置")
                        updated_list = PluginHookRunner.task_before(plugins, [sync_task_data], None, emit_line=log.line)
                        sync_task_data = updated_list[0] if updated_list else sync_task_data

                        log.set_stage("sync_plugin_run")
                        log.section("插件执行")
                        sync_task_data = PluginHookRunner.run(plugins, sync_task_data, None, sync_tree, emit_line=log.line)

                        log.set_stage("sync_plugin_task_after")
                        log.section("插件收尾")
                        PluginHookRunner.task_after(plugins, [sync_task_data], None, emit_line=log.line)
                except Exception as e:
                    log.set_stage("sync_plugin_error")
                    log.section("插件异常")
                    log.line(str(e).strip() or type(e).__name__)

            execution.status = "success"
            execution.finished_at = datetime.now()
            execution.stage = log.stage
            execution.stats_json = json.dumps(stats, ensure_ascii=False)
            execution.run_log = log.render()
            execution.message = "success"
            execution.heartbeat_at = datetime.now()
            self.db.commit()
            _release_lock()
            send_sync_execution_notification(self.db, task, execution)
            log.section("同步完成")
            return execution
        except SyncCancelled as exc:
            message = str(getattr(exc, "message", None) or str(exc) or "cancelled").strip() or "cancelled"
            log.set_stage("aborted")
            log.section("已停止")
            log.line(message)

            with SessionLocal() as w:
                w.execute(
                    update(SyncExecutionFile)
                    .where(
                        SyncExecutionFile.sync_execution_id == int(execution.id),
                        SyncExecutionFile.status.in_(["pending", "syncing"]),
                    )
                    .values(status="aborted", message="aborted", updated_at=datetime.now())
                )
                w.commit()

            execution.status = "aborted"
            execution.finished_at = datetime.now()
            execution.stage = log.stage
            execution.run_log = log.render()
            execution.message = f"aborted: {message}"
            execution.heartbeat_at = datetime.now()
            self.db.commit()
            _release_lock()
            return execution
        except Exception as exc:
            message = getattr(exc, "message", None) or str(exc).strip() or type(exc).__name__
            log.set_stage("error")
            log.section("异常")
            log.line(message)

            execution.status = "failed"
            execution.finished_at = datetime.now()
            execution.stage = log.stage
            execution.stats_json = json.dumps({}, ensure_ascii=False)
            execution.run_log = log.render()
            execution.message = message
            execution.heartbeat_at = datetime.now()
            self.db.commit()
            _release_lock()
            send_sync_execution_notification(self.db, task, execution)
            raise

    def _load_strategy(self, task: SyncTask, *, override: dict[str, Any] | None) -> Strategy:
        base: dict[str, Any] = {}
        raw = getattr(task, "strategy_json", None)
        if raw:
            try:
                base = json.loads(raw)
            except Exception:
                base = {}
        if override:
            base = {**base, **override}

        def _b(name: str, default: bool) -> bool:
            return bool(base.get(name, default))

        def _i(name: str, default: int, lo: int, hi: int) -> int:
            v = base.get(name, default)
            try:
                v = int(v)
            except Exception:
                v = default
            return max(lo, min(hi, v))

        def _f(name: str, default: float, lo: float, hi: float) -> float:
            v = base.get(name, default)
            try:
                v = float(v)
            except Exception:
                v = default
            return max(lo, min(hi, v))

        return Strategy(
            overwrite=_b("overwrite", False),
            one_way_delete_extras=_b("one_way_delete_extras", False),
            force_refresh=_b("force_refresh", False),
            concurrency=_i("concurrency", 4, 1, 32),
            request_interval_seconds=_f("request_interval_seconds", 0.0, 0.0, 5.0),
            openlist_copy_batch_size=_i("openlist_copy_batch_size", 200, 1, 5000),
        )

    def _scan_endpoint(self, endpoint: Endpoint, *, strategy: Strategy, cancel_checker: _CancelChecker | None = None) -> dict[str, FileMeta]:
        if cancel_checker is not None:
            cancel_checker.raise_if_cancelled()
        if endpoint.type == "openlist":
            client = self._get_openlist_client()
            return self._scan_openlist(
                client,
                endpoint.path,
                refresh=strategy.force_refresh,
                interval=strategy.request_interval_seconds,
                cancel_checker=cancel_checker,
            )
        if endpoint.type == "local":
            root = _local_sync_root()
            root.mkdir(parents=True, exist_ok=True)
            base = _resolve_local_path(root, endpoint.path)
            return self._scan_local(base, cancel_checker=cancel_checker)
        raise bad_request("SYNC_ENDPOINT_INVALID", "无效的同步端点类型")

    def _scan_openlist(
        self,
        client,
        root_path: str,
        *,
        refresh: bool,
        interval: float,
        cancel_checker: _CancelChecker | None,
    ) -> dict[str, FileMeta]:
        root_path = str(root_path or "").strip() or "/"
        root_path = "/" + root_path.lstrip("/")
        root_path = posixpath.normpath(root_path)

        out: dict[str, FileMeta] = {"": FileMeta(is_dir=True, size=0, modified_at=0.0)}
        stack: list[tuple[str, str]] = [(root_path, "")]
        while stack:
            if cancel_checker is not None:
                cancel_checker.raise_if_cancelled()
            abs_dir, rel_dir = stack.pop()
            page = 1
            per_page = 100
            total = None
            while True:
                if cancel_checker is not None:
                    cancel_checker.raise_if_cancelled()
                if interval > 0:
                    time.sleep(interval)
                try:
                    resp = client.fs_list(abs_dir, refresh=refresh, page=page, per_page=per_page)
                except Exception as exc:
                    api_code = getattr(exc, "api_code", None)
                    api_message = str(getattr(exc, "api_message", "") or "").strip()
                    text = (api_message or str(exc) or "").lower()
                    if str(api_code) in {"404", "500"} and ("object not found" in text or "failed get dir" in text):
                        raise bad_request("SYNC_OPENLIST_DIR_NOT_FOUND", f"OpenList 目录不存在: {abs_dir}") from exc
                    raise
                data = resp.get("data") if isinstance(resp, dict) else None
                content = []
                if isinstance(data, dict):
                    content = data.get("content") or data.get("items") or []
                    total = data.get("total") if total is None else total
                if not isinstance(content, list):
                    content = []
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "sync scan(openlist) dir=%s rel=%s page=%s per_page=%s refresh=%s items=%s total=%s",
                        abs_dir,
                        rel_dir,
                        page,
                        per_page,
                        bool(refresh),
                        len(content),
                        total,
                    )
                for item in content:
                    if not isinstance(item, dict):
                        continue
                    name = str(item.get("name") or "").strip()
                    if not name:
                        continue
                    is_dir = bool(item.get("is_dir") or item.get("isDir") or False)
                    size = int(item.get("size") or 0)
                    modified_at = _parse_iso_ts(
                        item.get("modified")
                        or item.get("updated")
                        or item.get("updated_at")
                        or item.get("updatedAt")
                        or item.get("created")
                        or item.get("created_at")
                        or item.get("createdAt")
                    )
                    rel = _norm_rel(posixpath.join(rel_dir, name))
                    out[rel] = FileMeta(is_dir=is_dir, size=size, modified_at=modified_at)
                    if is_dir:
                        stack.append((_join_openlist(abs_dir, name), rel))
                if total is None:
                    break
                try:
                    if page * per_page >= int(total):
                        break
                except Exception:
                    break
                page += 1
        return out

    def _scan_local(self, base: Path, *, cancel_checker: _CancelChecker | None) -> dict[str, FileMeta]:
        if not base.exists():
            return {"": FileMeta(is_dir=True, size=0, modified_at=0.0)}
        if not base.is_dir():
            raise bad_request("SYNC_LOCAL_PATH_INVALID", "本地路径必须是目录")
        out: dict[str, FileMeta] = {"": FileMeta(is_dir=True, size=0, modified_at=base.stat().st_mtime)}
        for root, dirs, files in os.walk(base):
            if cancel_checker is not None:
                cancel_checker.raise_if_cancelled()
            root_p = Path(root)
            rel_root = _norm_rel(root_p.relative_to(base).as_posix())
            for d in dirs:
                p = root_p / d
                rel = _norm_rel(posixpath.join(rel_root, d))
                try:
                    st = p.stat()
                    out[rel] = FileMeta(is_dir=True, size=0, modified_at=st.st_mtime)
                except Exception:
                    out[rel] = FileMeta(is_dir=True, size=0, modified_at=0.0)
            for f in files:
                p = root_p / f
                rel = _norm_rel(posixpath.join(rel_root, f))
                try:
                    st = p.stat()
                    out[rel] = FileMeta(is_dir=False, size=int(st.st_size), modified_at=float(st.st_mtime))
                except Exception:
                    out[rel] = FileMeta(is_dir=False, size=0, modified_at=0.0)
        return out

    def _load_baseline(self, sync_task_id: int) -> tuple[dict[str, FileMeta], dict[str, FileMeta]]:
        rows = (
            self.db.execute(select(SyncFileSnapshot).where(SyncFileSnapshot.sync_task_id == sync_task_id))
            .scalars()
            .all()
        )
        src: dict[str, FileMeta] = {}
        dst: dict[str, FileMeta] = {}
        for row in rows:
            side = str(getattr(row, "side", "") or "").strip()
            rel = _norm_rel(getattr(row, "rel_path", "") or "")
            meta = FileMeta(
                is_dir=bool(getattr(row, "is_dir", False)),
                size=int(getattr(row, "size", 0) or 0),
                modified_at=float(getattr(row, "modified_at", 0.0) or 0.0),
            )
            if side == "source":
                src[rel] = meta
            elif side == "target":
                dst[rel] = meta
        return src, dst

    def _build_actions(
        self,
        *,
        source: Endpoint,
        target: Endpoint,
        mode: str,
        strategy: Strategy,
        source_map: dict[str, FileMeta],
        target_map: dict[str, FileMeta],
        sync_task_id: int,
    ) -> list[dict[str, Any]]:
        mode = str(mode or "one_way").strip() or "one_way"
        if mode not in ("one_way", "two_way"):
            raise bad_request("SYNC_MODE_INVALID", "无效的同步模式")

        if mode == "one_way":
            return self._build_one_way_actions(source, target, strategy, source_map, target_map)
        return self._build_two_way_actions(sync_task_id, source, target, source_map, target_map)

    def _build_one_way_actions(
        self,
        source: Endpoint,
        target: Endpoint,
        strategy: Strategy,
        source_map: dict[str, FileMeta],
        target_map: dict[str, FileMeta],
    ) -> list[dict[str, Any]]:
        actions: list[dict[str, Any]] = []
        for rel, meta in source_map.items():
            if meta.is_dir:
                continue
            tmeta = target_map.get(rel)
            if tmeta is None or tmeta.is_dir:
                actions.append(
                    {
                        "kind": "copy",
                        "src": source,
                        "dst": target,
                        "src_rel": rel,
                        "dst_rel": rel,
                        "dst_exists": False,
                    }
                )
                continue
            if not strategy.overwrite:
                continue
            if not _same_meta(meta, tmeta):
                actions.append(
                    {
                        "kind": "copy",
                        "src": source,
                        "dst": target,
                        "src_rel": rel,
                        "dst_rel": rel,
                        "dst_exists": True,
                    }
                )
        if strategy.one_way_delete_extras:
            for rel, meta in target_map.items():
                if meta.is_dir:
                    continue
                if rel not in source_map:
                    actions.append({"kind": "delete", "dst": target, "dst_rel": rel})
        return actions

    def _build_two_way_actions(
        self,
        sync_task_id: int,
        source: Endpoint,
        target: Endpoint,
        source_map: dict[str, FileMeta],
        target_map: dict[str, FileMeta],
    ) -> list[dict[str, Any]]:
        base_src, base_dst = self._load_baseline(int(sync_task_id))
        actions: list[dict[str, Any]] = []
        ts = datetime.now().strftime("%Y%m%d%H%M%S")
        if not base_src and not base_dst:
            rels = {rel for rel, meta in source_map.items() if not meta.is_dir} | {
                rel for rel, meta in target_map.items() if not meta.is_dir
            }
            for rel in sorted(rels):
                s_meta = source_map.get(rel)
                t_meta = target_map.get(rel)
                if s_meta is None and t_meta is None:
                    continue
                if s_meta is not None and (t_meta is None or t_meta.is_dir):
                    actions.append(
                        {
                            "kind": "copy",
                            "src": source,
                            "dst": target,
                            "src_rel": rel,
                            "dst_rel": rel,
                            "dst_exists": False,
                        }
                    )
                    continue
                if t_meta is not None and (s_meta is None or s_meta.is_dir):
                    actions.append(
                        {
                            "kind": "copy",
                            "src": target,
                            "dst": source,
                            "src_rel": rel,
                            "dst_rel": rel,
                            "dst_exists": False,
                        }
                    )
                    continue
                if _same_meta(s_meta, t_meta):
                    continue
                actions.append(
                    {
                        "kind": "copy",
                        "src": source,
                        "dst": target,
                        "src_rel": rel,
                        "dst_rel": _conflict_path(rel, ts),
                        "conflict": True,
                        "dst_exists": bool(target_map.get(_conflict_path(rel, ts)) and not target_map.get(_conflict_path(rel, ts)).is_dir),
                    }
                )
                actions.append(
                    {
                        "kind": "copy",
                        "src": target,
                        "dst": source,
                        "src_rel": rel,
                        "dst_rel": _conflict_path(rel, ts),
                        "conflict": True,
                        "dst_exists": bool(source_map.get(_conflict_path(rel, ts)) and not source_map.get(_conflict_path(rel, ts)).is_dir),
                    }
                )
            return actions

        changed_src = {
            rel for rel, meta in source_map.items() if not meta.is_dir and not _same_meta(meta, base_src.get(rel))
        }
        changed_dst = {
            rel for rel, meta in target_map.items() if not meta.is_dir and not _same_meta(meta, base_dst.get(rel))
        }

        for rel in sorted(changed_src | changed_dst):
            in_src = rel in changed_src
            in_dst = rel in changed_dst
            if in_src and in_dst:
                conflict_rel = _conflict_path(rel, ts)
                actions.append(
                    {
                        "kind": "copy",
                        "src": source,
                        "dst": target,
                        "src_rel": rel,
                        "dst_rel": conflict_rel,
                        "conflict": True,
                        "dst_exists": bool(target_map.get(conflict_rel) and not target_map.get(conflict_rel).is_dir),
                    }
                )
                actions.append(
                    {
                        "kind": "copy",
                        "src": target,
                        "dst": source,
                        "src_rel": rel,
                        "dst_rel": conflict_rel,
                        "conflict": True,
                        "dst_exists": bool(source_map.get(conflict_rel) and not source_map.get(conflict_rel).is_dir),
                    }
                )
                continue
            if in_src:
                actions.append(
                    {
                        "kind": "copy",
                        "src": source,
                        "dst": target,
                        "src_rel": rel,
                        "dst_rel": rel,
                        "dst_exists": bool(target_map.get(rel) and not target_map.get(rel).is_dir),
                    }
                )
            if in_dst:
                actions.append(
                    {
                        "kind": "copy",
                        "src": target,
                        "dst": source,
                        "src_rel": rel,
                        "dst_rel": rel,
                        "dst_exists": bool(source_map.get(rel) and not source_map.get(rel).is_dir),
                    }
                )
        return actions

    def _apply_actions(
        self,
        actions: list[dict[str, Any]],
        *,
        strategy: Strategy,
        log: ExecutionLog,
        sync_execution_id: int,
        stats: dict[str, Any],
        max_events: int,
        on_event: Callable[[dict[str, Any] | None], None],
        on_persist: Callable[[bool], None],
        display_path: Callable[[Endpoint, str], str],
        on_file_update: Callable[..., None],
        cancel_checker: _CancelChecker | None,
    ) -> None:
        if not actions:
            return

        local_actions: list[dict[str, Any]] = []
        server_actions: list[dict[str, Any]] = []
        for a in actions:
            src = a.get("src")
            dst = a.get("dst")
            if a.get("kind") == "delete":
                if isinstance(dst, Endpoint) and dst.type == "openlist":
                    server_actions.append(a)
                else:
                    local_actions.append(a)
                continue
            if a.get("kind") == "copy":
                src_rel = str(a.get("src_rel") or "")
                dst_rel = str(a.get("dst_rel") or "")
                if (
                    isinstance(src, Endpoint)
                    and isinstance(dst, Endpoint)
                    and src.type == "openlist"
                    and dst.type == "openlist"
                    and _norm_rel(src_rel) == _norm_rel(dst_rel)
                ):
                    server_actions.append(a)
                else:
                    local_actions.append(a)
                continue

        finished: set[str] = set()

        def _append_event(action: str, status: str, path: str, *, size: int | None = None, message: str | None = None) -> dict[str, Any]:
            evt: dict[str, Any] = {
                "ts": datetime.now().isoformat(),
                "action": str(action),
                "status": str(status),
                "path": str(path),
            }
            if size is not None:
                evt["size"] = int(size)
            if message:
                evt["message"] = str(message)

            if sync_execution_id and path:
                on_file_update(path, action=str(action), status=str(status), size=size, message=(str(message) if message else None))

            terminal = status in {"success", "skipped", "failed"}
            if terminal and path and path not in finished:
                finished.add(path)
                stats["done_files"] = int(stats.get("done_files") or 0) + 1
                if status == "success":
                    if action == "copy":
                        stats["copied_files"] = int(stats.get("copied_files") or 0) + 1
                    elif action == "delete":
                        stats["deleted_files"] = int(stats.get("deleted_files") or 0) + 1
                elif status == "skipped":
                    stats["skipped_files"] = int(stats.get("skipped_files") or 0) + 1
                else:
                    stats["failed_files"] = int(stats.get("failed_files") or 0) + 1

            recent = stats.get("recent_events")
            if not isinstance(recent, list):
                recent = []
                stats["recent_events"] = recent
            recent.append(evt)
            if len(recent) > int(max_events):
                del recent[: len(recent) - int(max_events)]

            if terminal:
                if status == "success":
                    log.line(f"[ok] {action} {path}")
                elif status == "skipped":
                    log.line(f"[skip] {action} {path}")
                else:
                    log.line(f"[fail] {action} {path}{(': ' + message) if message else ''}")

            on_event(evt)
            on_persist(False)
            return evt

        def flush_now() -> None:
            on_persist(True)

        if server_actions:
            self._apply_server_actions(
                server_actions,
                strategy=strategy,
                log=log,
                push_event=_append_event,
                flush_now=flush_now,
                cancel_checker=cancel_checker,
            )

        if local_actions:
            self._apply_local_actions(
                local_actions,
                strategy=strategy,
                log=log,
                push_event=_append_event,
                display_path=display_path,
                flush_now=flush_now,
                cancel_checker=cancel_checker,
            )

        on_persist(True)

    def _apply_server_actions(
        self,
        actions: list[dict[str, Any]],
        *,
        strategy: Strategy,
        log: ExecutionLog,
        push_event: Callable[[str, str, str], dict[str, Any]],
        flush_now: Callable[[], None],
        cancel_checker: _CancelChecker | None,
    ) -> None:
        client = self._get_openlist_client()

        copy_groups: dict[str, dict[str, Any]] = {}
        delete_groups: dict[str, list[str]] = {}

        for a in actions:
            kind = a.get("kind")
            if kind == "copy":
                src: Endpoint = a["src"]
                dst: Endpoint = a["dst"]
                src_rel = str(a.get("src_rel") or "")
                dst_rel = str(a.get("dst_rel") or "")
                src_abs = _join_openlist(src.path, src_rel)
                dst_abs = _join_openlist(dst.path, dst_rel)
                src_dir = posixpath.dirname(src_abs) or "/"
                name = posixpath.basename(src_abs)
                dst_dir = posixpath.dirname(dst_abs) or "/"
                key = f"{src_dir} -> {dst_dir}"
                group = copy_groups.get(key)
                if group is None:
                    group = {"src_dir": src_dir, "dst_dir": dst_dir, "names": []}
                    copy_groups[key] = group
                group["names"].append(name)
            elif kind == "delete":
                dst: Endpoint = a["dst"]
                dst_rel = str(a.get("dst_rel") or "")
                dst_abs = _join_openlist(dst.path, dst_rel)
                dst_dir = posixpath.dirname(dst_abs) or "/"
                name = posixpath.basename(dst_abs)
                delete_groups.setdefault(dst_dir, []).append(name)

        for group in copy_groups.values():
            names: list[str] = list(group["names"])
            for i in range(0, len(names), strategy.openlist_copy_batch_size):
                if cancel_checker is not None:
                    cancel_checker.raise_if_cancelled()
                batch = names[i : i + strategy.openlist_copy_batch_size]
                batch_paths = [posixpath.normpath(posixpath.join(group["dst_dir"], str(name))) for name in batch]
                if strategy.request_interval_seconds > 0:
                    time.sleep(strategy.request_interval_seconds)
                self._ensure_openlist_abs_dir(client, str(group["dst_dir"]), log=log)
                for p in batch_paths:
                    push_event("copy", "syncing", p)
                flush_now()
                try:
                    log.line(f"openlist fs_copy: src_dir={group['src_dir']} dst_dir={group['dst_dir']} count={len(batch)}")
                    resp = client.fs_copy(
                        group["src_dir"],
                        group["dst_dir"],
                        batch,
                        overwrite=strategy.overwrite,
                        skip_existing=not strategy.overwrite,
                        merge=False,
                    )
                    tasks = []
                    data = resp.get("data") if isinstance(resp, dict) else None
                    if isinstance(data, dict):
                        tasks = data.get("tasks") or []
                    if isinstance(tasks, list) and tasks:
                        tid_to_path: dict[str, str] = {}
                        done_paths: set[str] = set()
                        name_to_paths: dict[str, list[str]] = {}
                        for bp in batch_paths:
                            name_to_paths.setdefault(posixpath.basename(bp), []).append(bp)
                        for idx, t in enumerate(tasks):
                            if not isinstance(t, dict):
                                continue
                            tid = str(t.get("id") or "").strip()
                            if not tid:
                                continue
                            mapped = None
                            if len(tasks) == len(batch_paths) and idx < len(batch_paths):
                                mapped = batch_paths[idx]
                            else:
                                tname = str(t.get("name") or "").strip()
                                cand = posixpath.basename(tname) if tname else ""
                                options = name_to_paths.get(cand) if cand else None
                                if options and len(options) == 1:
                                    mapped = options[0]
                            if mapped:
                                tid_to_path[tid] = mapped

                        def _emit_terminal(tid: str, data: dict[str, Any]) -> None:
                            path = tid_to_path.get(str(tid))
                            if not path or path in done_paths:
                                return
                            done_paths.add(path)
                            state_raw: Any = data.get("state") if "state" in data else data.get("State")
                            state = str(state_raw or "").strip().lower()
                            status_raw: Any = data.get("status") if "status" in data else data.get("Status")
                            status_text = str(status_raw or "").strip().lower()
                            err_raw: Any = data.get("error") if "error" in data else data.get("Error")
                            err = str(err_raw or "").strip()
                            failed = False
                            if err:
                                failed = True
                            if not failed and ("fail" in status_text or "error" in status_text):
                                failed = True
                            if not failed:
                                try:
                                    sv = int(state) if state.isdigit() else None
                                except Exception:
                                    sv = None
                                if sv is not None and sv in {4, 5}:
                                    failed = True
                            push_event("copy", "failed" if failed else "success", path, message=(err if failed else None))
                            flush_now()

                        self._wait_openlist_tasks(
                            client,
                            "copy",
                            tasks,
                            log=log,
                            flush_now=flush_now,
                            on_item_progress=lambda tid, p: (push_event("copy", "syncing", tid_to_path.get(str(tid)) or "", message=f"{float(p):.1f}%") if tid_to_path.get(str(tid)) and (tid_to_path.get(str(tid)) not in done_paths) else None),
                            on_terminal=_emit_terminal,
                            cancel_checker=cancel_checker,
                        )
                    for p in batch_paths:
                        if p in done_paths:
                            continue
                        push_event("copy", "success", p)
                except Exception as e:
                    log.line(
                        "openlist fs_copy failed: "
                        f"src_dir={group.get('src_dir')} dst_dir={group.get('dst_dir')} "
                        f"batch={batch[:10]}{'...' if len(batch) > 10 else ''} "
                        f"err={str(e).strip() or type(e).__name__} "
                        f"http_status={getattr(e, 'http_status', None)} api_code={getattr(e, 'api_code', None)} api_message={getattr(e, 'api_message', None)}"
                    )
                    for p in batch_paths:
                        push_event("copy", "failed", p, message=str(e))

        for dst_dir, names in delete_groups.items():
            for i in range(0, len(names), 200):
                if cancel_checker is not None:
                    cancel_checker.raise_if_cancelled()
                batch = names[i : i + 200]
                try:
                    if strategy.request_interval_seconds > 0:
                        time.sleep(strategy.request_interval_seconds)
                    for name in batch:
                        push_event("delete", "syncing", posixpath.normpath(posixpath.join(dst_dir, str(name))))
                    flush_now()
                    client.fs_remove(dst_dir, batch)
                    for name in batch:
                        push_event("delete", "success", posixpath.normpath(posixpath.join(dst_dir, str(name))))
                except Exception as e:
                    for name in batch:
                        push_event("delete", "failed", posixpath.normpath(posixpath.join(dst_dir, str(name))), message=str(e))
        return

    def _wait_openlist_tasks(
        self,
        client,
        task_type: str,
        tasks: list[Any],
        *,
        log: ExecutionLog,
        flush_now: Callable[[], None] | None = None,
        on_progress: Callable[[float | None], None] | None = None,
        on_item_progress: Callable[[str, float], None] | None = None,
        on_terminal: Callable[[str, dict[str, Any]], None] | None = None,
        cancel_checker: _CancelChecker | None,
    ) -> None:
        tids: list[str] = []
        for t in tasks:
            if isinstance(t, dict):
                tid = str(t.get("id") or "").strip()
                if tid:
                    tids.append(tid)
        if not tids:
            return
        pending = set(tids)
        last_print = 0.0
        start_ts = _now_ts()
        fail_counts: dict[str, int] = {tid: 0 for tid in tids}
        progresses: dict[str, float | None] = {tid: None for tid in tids}
        states: dict[str, str] = {tid: "" for tid in tids}
        terminal_sent: set[str] = set()
        progress_last_emit: dict[str, float] = {tid: 0.0 for tid in tids}
        progress_last_val: dict[str, float | None] = {tid: None for tid in tids}
        while pending:
            if cancel_checker is not None and cancel_checker.is_cancelled():
                try:
                    client.task_cancel_some(task_type, list(pending))
                except Exception:
                    pass
                if flush_now is not None:
                    flush_now()
                raise SyncCancelled(cancel_checker.message or "cancelled")
            done: set[str] = set()
            for tid in list(pending):
                try:
                    info = client.task_info(task_type, tid)
                    data = info.get("data") if isinstance(info, dict) else None
                    state_raw: Any = ""
                    state = ""
                    progress = None
                    if isinstance(data, dict):
                        state_raw = data.get("state") if "state" in data else data.get("State")
                        state = str(state_raw or "").strip().lower()
                        progress = data.get("progress")
                    prev_state = states.get(tid) or ""
                    prev_progress = progresses.get(tid)
                    try:
                        progresses[tid] = float(progress) if progress is not None and str(progress).strip() != "" else None
                    except Exception:
                        progresses[tid] = None
                    if on_item_progress is not None:
                        pv = progresses.get(tid)
                        if pv is not None:
                            now_ts = _now_ts()
                            last_ts = float(progress_last_emit.get(tid) or 0.0)
                            last_val = progress_last_val.get(tid)
                            if now_ts - last_ts >= 2.0:
                                if last_val is None or abs(float(pv) - float(last_val)) >= 0.5 or now_ts - last_ts >= 6.0:
                                    try:
                                        on_item_progress(tid, float(pv))
                                    except Exception:
                                        pass
                                    progress_last_emit[tid] = now_ts
                                    progress_last_val[tid] = float(pv)
                    if logger.isEnabledFor(logging.DEBUG):
                        states[tid] = state
                        cur_progress = progresses.get(tid)
                        changed = (state != prev_state) or (
                            (cur_progress is not None and prev_progress is not None and abs(float(cur_progress) - float(prev_progress)) >= 5.0)
                            or (cur_progress is not None and prev_progress is None)
                            or (cur_progress is None and prev_progress is not None)
                        )
                        if changed:
                            logger.debug(
                                "sync openlist task progress type=%s tid=%s state=%s raw_state=%s progress=%s pending=%s",
                                task_type,
                                tid,
                                state,
                                state_raw,
                                progress,
                                len(pending),
                            )

                    terminal = False
                    if state in {"succeeded", "success", "finished", "done", "completed", "failed", "error", "canceled", "cancelled"}:
                        terminal = True
                    if not terminal:
                        try:
                            sv = int(state) if state.isdigit() else None
                        except Exception:
                            sv = None
                        if sv is not None:
                            if sv in {2, 3, 4, 5}:
                                terminal = True
                        if not terminal and progress is not None:
                            try:
                                if float(progress) >= 100.0:
                                    terminal = True
                            except Exception:
                                pass

                    if terminal:
                        if on_terminal is not None and tid not in terminal_sent and isinstance(data, dict):
                            try:
                                on_terminal(tid, dict(data))
                            except Exception:
                                pass
                            terminal_sent.add(tid)
                        done.add(tid)
                    if _now_ts() - last_print > 2:
                        log.line(f"openlist task {tid}: state={state} raw_state={state_raw} progress={progress}")
                        if flush_now is not None:
                            flush_now()
                except Exception as e:
                    fail_counts[tid] = int(fail_counts.get(tid) or 0) + 1
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "sync openlist task_info failed type=%s tid=%s fail_count=%s err=%s http_status=%s api_code=%s api_message=%s",
                            task_type,
                            tid,
                            fail_counts[tid],
                            str(e).strip() or type(e).__name__,
                            getattr(e, "http_status", None),
                            getattr(e, "api_code", None),
                            getattr(e, "api_message", None),
                        )
                    if fail_counts[tid] >= 3:
                        try:
                            d = client.task_done(task_type)
                            dd = d.get("data") if isinstance(d, dict) else None
                            items = []
                            if isinstance(dd, dict):
                                items = dd.get("tasks") or dd.get("items") or dd.get("content") or []
                            if isinstance(items, list):
                                for it in items:
                                    if isinstance(it, dict) and str(it.get("id") or "").strip() == tid:
                                        log.line(f"openlist task {tid}: found in done list, treat as done")
                                        done.add(tid)
                                        raise StopIteration()
                        except StopIteration:
                            pass
                        except Exception:
                            pass
                    if _now_ts() - last_print > 2:
                        log.line(
                            f"openlist task {tid}: info failed err={str(e).strip() or type(e).__name__} "
                            f"http_status={getattr(e, 'http_status', None)} api_code={getattr(e, 'api_code', None)} api_message={getattr(e, 'api_message', None)}"
                        )
                        if flush_now is not None:
                            flush_now()
                    continue
            if done:
                pending -= done
            if on_progress is not None:
                vals = [v for v in progresses.values() if isinstance(v, (int, float))]
                on_progress((sum(vals) / len(vals)) if vals else None)
            if not pending:
                break
            if _now_ts() - start_ts > 6 * 3600:
                raise RuntimeError(f"openlist tasks timeout: {sorted(pending)[:5]}{'...' if len(pending) > 5 else ''}")
            if _now_ts() - last_print > 2:
                last_print = _now_ts()
            time.sleep(1.0)

    def _apply_local_actions(
        self,
        actions: list[dict[str, Any]],
        *,
        strategy: Strategy,
        log: ExecutionLog,
        push_event: Callable[..., dict[str, Any]],
        display_path: Callable[[Endpoint, str], str],
        flush_now: Callable[[], None],
        cancel_checker: _CancelChecker | None,
    ) -> None:
        if cancel_checker is not None:
            cancel_checker.raise_if_cancelled()

        def run_one(a: dict[str, Any]) -> dict[str, Any]:
            kind = str(a.get("kind") or "")
            if kind == "copy":
                src: Endpoint = a["src"]
                dst: Endpoint = a["dst"]
                src_rel = str(a.get("src_rel") or "")
                dst_rel = str(a.get("dst_rel") or "")
                path = display_path(dst, dst_rel)
                size = a.get("_size")
                try:
                    on_chunk = None
                    try:
                        total = int(size) if size is not None else 0
                    except Exception:
                        total = 0
                    if total > 0:
                        bytes_done = 0
                        last_emit_ts = 0.0
                        last_pct: float | None = None

                        def _on_chunk(n: int) -> None:
                            nonlocal bytes_done, last_emit_ts, last_pct
                            try:
                                bytes_done += int(n or 0)
                            except Exception:
                                return
                            if bytes_done < 0:
                                bytes_done = 0
                            now = _now_ts()
                            pct = (float(bytes_done) * 100.0) / float(total) if total > 0 else 0.0
                            if pct < 0:
                                pct = 0.0
                            if pct > 100.0:
                                pct = 100.0
                            if last_pct is not None:
                                if (now - last_emit_ts) < 0.8 and abs(float(pct) - float(last_pct)) < 1.0:
                                    return
                            last_emit_ts = now
                            last_pct = float(pct)
                            push_event("copy", "syncing", path, size=total, message=f"{pct:.1f}%")

                        on_chunk = _on_chunk
                    st = self._copy_between(
                        src,
                        dst,
                        src_rel,
                        dst_rel,
                        strategy=strategy,
                        dst_exists=bool(a.get("dst_exists")) if a.get("dst_exists") is not None else None,
                        on_chunk=on_chunk,
                    )
                    return {"action": "copy", "status": st, "path": path, "size": size, "message": None}
                except Exception as e:
                    msg = str(e).strip() or type(e).__name__
                    return {"action": "copy", "status": "failed", "path": path, "size": size, "message": msg}

            if kind == "delete":
                dst: Endpoint = a["dst"]
                dst_rel = str(a.get("dst_rel") or "")
                path = display_path(dst, dst_rel)
                try:
                    st = self._delete_at(dst, dst_rel)
                    return {"action": "delete", "status": st, "path": path, "size": None, "message": None}
                except Exception as e:
                    msg = str(e).strip() or type(e).__name__
                    return {"action": "delete", "status": "failed", "path": path, "size": None, "message": msg}

            return {"action": "unknown", "status": "skipped", "path": "", "size": None, "message": None}

        workers = int(getattr(strategy, "concurrency", 1) or 1)
        uses_openlist = False
        for a in actions:
            src = a.get("src")
            dst = a.get("dst")
            if isinstance(src, Endpoint) and src.type == "openlist":
                uses_openlist = True
                break
            if isinstance(dst, Endpoint) and dst.type == "openlist":
                uses_openlist = True
                break
        if uses_openlist:
            workers = 1

        normalized: list[dict[str, Any]] = []
        for a in actions:
            kind = str(a.get("kind") or "")
            if kind == "copy":
                src: Endpoint = a["src"]
                dst: Endpoint = a["dst"]
                src_rel = str(a.get("src_rel") or "")
                dst_rel = str(a.get("dst_rel") or "")
                size = a.get("_size")
                if size is None and src.type == "local":
                    try:
                        root = _local_sync_root()
                        base = _resolve_local_path(root, src.path)
                        p = _resolve_local_path(base, src_rel)
                        if p.exists() and p.is_file():
                            size = int(p.stat().st_size)
                    except Exception:
                        size = None
                a2 = dict(a)
                a2["_size"] = size
                push_event("copy", "syncing", display_path(dst, dst_rel), size=size)
                flush_now()
                normalized.append(a2)
            elif kind == "delete":
                dst: Endpoint = a["dst"]
                dst_rel = str(a.get("dst_rel") or "")
                push_event("delete", "syncing", display_path(dst, dst_rel))
                flush_now()
                normalized.append(a)
            else:
                normalized.append(a)

        cancelled = False
        with ThreadPoolExecutor(max_workers=workers) as ex:
            it = iter(normalized)
            inflight: set[Any] = set()

            def submit_next() -> bool:
                nonlocal cancelled
                if cancelled:
                    return False
                if cancel_checker is not None and cancel_checker.is_cancelled():
                    cancelled = True
                    return False
                try:
                    a = next(it)
                except StopIteration:
                    return False
                inflight.add(ex.submit(run_one, a))
                return True

            for _ in range(max(0, int(workers))):
                if not submit_next():
                    break

            while inflight:
                done, pending = wait(inflight, return_when=FIRST_COMPLETED)
                inflight = pending
                for fut in done:
                    r = fut.result()
                    push_event(
                        r.get("action") or "",
                        r.get("status") or "",
                        r.get("path") or "",
                        size=r.get("size"),
                        message=r.get("message"),
                    )
                while len(inflight) < int(workers):
                    if not submit_next():
                        break

            if cancel_checker is not None and cancel_checker.is_cancelled():
                cancelled = True

        if cancelled:
            flush_now()
            raise SyncCancelled(cancel_checker.message if cancel_checker is not None else "cancelled")
        return

    def _copy_between(
        self,
        src: Endpoint,
        dst: Endpoint,
        src_rel: str,
        dst_rel: str,
        *,
        strategy: Strategy,
        dst_exists: bool | None = None,
        on_chunk: Callable[[int], None] | None = None,
    ) -> str:
        src_rel = _norm_rel(src_rel)
        dst_rel = _norm_rel(dst_rel)
        if src.type == "local" and dst.type == "openlist":
            return self._copy_local_to_openlist(
                src.path,
                dst.path,
                src_rel,
                dst_rel,
                strategy=strategy,
                dst_exists=dst_exists,
                on_chunk=on_chunk,
            )
        if src.type == "openlist" and dst.type == "local":
            return self._copy_openlist_to_local(src.path, dst.path, src_rel, dst_rel, strategy=strategy, on_chunk=on_chunk)
        if src.type == "local" and dst.type == "local":
            return self._copy_local_to_local(src.path, dst.path, src_rel, dst_rel, strategy=strategy, on_chunk=on_chunk)
        if src.type == "openlist" and dst.type == "openlist":
            return self._copy_openlist_to_openlist(
                src.path,
                dst.path,
                src_rel,
                dst_rel,
                strategy=strategy,
                dst_exists=dst_exists,
                on_chunk=on_chunk,
            )
        raise bad_request("SYNC_COPY_UNSUPPORTED", "不支持的复制方向")

    def _copy_local_to_openlist(
        self,
        local_base: str,
        openlist_base: str,
        src_rel: str,
        dst_rel: str,
        *,
        strategy: Strategy,
        dst_exists: bool | None = None,
        on_chunk: Callable[[int], None] | None = None,
    ) -> str:
        root = _local_sync_root()
        base = _resolve_local_path(root, local_base)
        src_path = _resolve_local_path(base, src_rel)
        if not src_path.exists() or not src_path.is_file():
            return "skipped"
        client = self._get_openlist_client()
        self._ensure_openlist_dirs(client, openlist_base, dst_rel)
        dst_abs = _join_openlist(openlist_base, dst_rel)
        dst_dir = posixpath.dirname(dst_abs) or "/"
        dst_name = posixpath.basename(dst_abs)
        use_tmp = bool(strategy.overwrite and dst_exists)
        tmp_abs = ""
        if use_tmp:
            tmp_abs = posixpath.normpath(posixpath.join(dst_dir, _tmp_name(dst_name)))
        upload_abs = tmp_abs if use_tmp else dst_abs
        with src_path.open("rb") as f:
            if on_chunk:
                class _CountingReader:
                    def __init__(self, fp):
                        self._fp = fp

                    def read(self, n: int = -1):
                        data = self._fp.read(n)
                        if data:
                            on_chunk(len(data))
                        return data

                    def __getattr__(self, name: str):
                        return getattr(self._fp, name)

                client.fs_put(upload_abs, _CountingReader(f), content_length=int(src_path.stat().st_size))
            else:
                client.fs_put(upload_abs, f, content_length=int(src_path.stat().st_size))
        if use_tmp and tmp_abs:
            try:
                client.fs_remove(dst_dir, [dst_name])
            except Exception:
                pass
            try:
                client.fs_rename(tmp_abs, dst_name, overwrite=False)
            except Exception:
                try:
                    client.fs_remove(dst_dir, [posixpath.basename(tmp_abs)])
                except Exception:
                    pass
                raise
        if strategy.request_interval_seconds > 0:
            time.sleep(strategy.request_interval_seconds)
        return "success"

    def _copy_openlist_to_local(
        self,
        openlist_base: str,
        local_base: str,
        src_rel: str,
        dst_rel: str,
        *,
        strategy: Strategy,
        on_chunk: Callable[[int], None] | None = None,
    ) -> str:
        root = _local_sync_root()
        base = _resolve_local_path(root, local_base)
        dst_path = _resolve_local_path(base, dst_rel)
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        use_tmp = bool(strategy.overwrite and dst_path.exists())
        tmp_path = dst_path
        if use_tmp:
            tmp_path = dst_path.with_name(_tmp_name(dst_path.name))
        client = self._get_openlist_client()
        src_abs = _join_openlist(openlist_base, src_rel)
        try:
            client.download_by_path(src_abs, dst_path=tmp_path, on_chunk=on_chunk)
            if use_tmp:
                try:
                    if dst_path.exists():
                        dst_path.unlink()
                except Exception:
                    pass
                os.replace(tmp_path, dst_path)
        except Exception:
            if use_tmp:
                try:
                    if tmp_path.exists():
                        tmp_path.unlink()
                except Exception:
                    pass
            raise
        if strategy.request_interval_seconds > 0:
            time.sleep(strategy.request_interval_seconds)
        return "success"

    def _copy_local_to_local(
        self,
        src_base: str,
        dst_base: str,
        src_rel: str,
        dst_rel: str,
        *,
        strategy: Strategy,
        on_chunk: Callable[[int], None] | None = None,
    ) -> str:
        root = _local_sync_root()
        src_root = _resolve_local_path(root, src_base)
        dst_root = _resolve_local_path(root, dst_base)
        src_path = _resolve_local_path(src_root, src_rel)
        dst_path = _resolve_local_path(dst_root, dst_rel)
        if not src_path.exists() or not src_path.is_file():
            return "skipped"
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        if dst_path.exists() and not strategy.overwrite:
            return "skipped"
        use_tmp = bool(strategy.overwrite and dst_path.exists())
        tmp_path = dst_path
        if use_tmp:
            tmp_path = dst_path.with_name(_tmp_name(dst_path.name))
        try:
            with src_path.open("rb") as rf, tmp_path.open("wb") as wf:
                while True:
                    chunk = rf.read(1024 * 1024)
                    if not chunk:
                        break
                    wf.write(chunk)
                    if on_chunk:
                        on_chunk(len(chunk))
            if use_tmp:
                try:
                    if dst_path.exists():
                        dst_path.unlink()
                except Exception:
                    pass
                os.replace(tmp_path, dst_path)
            shutil.copystat(src_path, dst_path)
        except Exception:
            if use_tmp:
                try:
                    if tmp_path.exists():
                        tmp_path.unlink()
                except Exception:
                    pass
            raise
        return "success"

    def _copy_openlist_to_openlist(
        self,
        src_base: str,
        dst_base: str,
        src_rel: str,
        dst_rel: str,
        *,
        strategy: Strategy,
        dst_exists: bool | None = None,
        on_chunk: Callable[[int], None] | None = None,
    ) -> str:
        client = self._get_openlist_client()
        if src_rel == dst_rel:
            src_abs = _join_openlist(src_base, src_rel)
            dst_dir = posixpath.dirname(_join_openlist(dst_base, dst_rel)) or "/"
            src_dir = posixpath.dirname(src_abs) or "/"
            name = posixpath.basename(src_abs)
            self._ensure_openlist_abs_dir(client, dst_dir)
            client.fs_copy(src_dir, dst_dir, [name], overwrite=strategy.overwrite, skip_existing=not strategy.overwrite, merge=False)
            return "success"

        root = _local_sync_root()
        tmp_dir = root / ".tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = (tmp_dir / f"{int(time.time() * 1000)}-{threading.get_ident()}").with_suffix(".bin")
        try:
            src_abs = _join_openlist(src_base, src_rel)
            client.download_by_path(src_abs, dst_path=tmp_path, on_chunk=on_chunk)
            self._ensure_openlist_dirs(client, dst_base, dst_rel)
            dst_abs = _join_openlist(dst_base, dst_rel)
            dst_dir = posixpath.dirname(dst_abs) or "/"
            dst_name = posixpath.basename(dst_abs)
            use_tmp = bool(strategy.overwrite and dst_exists)
            tmp_abs = ""
            if use_tmp:
                tmp_abs = posixpath.normpath(posixpath.join(dst_dir, _tmp_name(dst_name)))
            upload_abs = tmp_abs if use_tmp else dst_abs
            with tmp_path.open("rb") as f:
                client.fs_put(upload_abs, f, content_length=int(tmp_path.stat().st_size))
            if use_tmp and tmp_abs:
                try:
                    client.fs_remove(dst_dir, [dst_name])
                except Exception:
                    pass
                try:
                    client.fs_rename(tmp_abs, dst_name, overwrite=False)
                except Exception:
                    try:
                        client.fs_remove(dst_dir, [posixpath.basename(tmp_abs)])
                    except Exception:
                        pass
                    raise
        finally:
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except Exception:
                pass
        return "success"

    def _delete_at(self, dst: Endpoint, dst_rel: str) -> str:
        dst_rel = _norm_rel(dst_rel)
        if dst.type == "openlist":
            client = self._get_openlist_client()
            abs_path = _join_openlist(dst.path, dst_rel)
            dir_path = posixpath.dirname(abs_path) or "/"
            name = posixpath.basename(abs_path)
            client.fs_remove(dir_path, [name])
            return "success"
        if dst.type == "local":
            root = _local_sync_root()
            base = _resolve_local_path(root, dst.path)
            p = _resolve_local_path(base, dst_rel)
            if p.exists() and p.is_file():
                p.unlink()
                return "success"
            return "skipped"
        raise bad_request("SYNC_DELETE_UNSUPPORTED", "不支持的删除方向")

    def _ensure_openlist_dirs(self, client, openlist_base: str, rel: str) -> None:
        rel = _norm_rel(rel)
        parent = posixpath.dirname(rel)
        if not parent or parent == ".":
            return
        parts = [p for p in parent.split("/") if p]
        cur = str(openlist_base or "").strip() or "/"
        cur = "/" + cur.lstrip("/")
        cur = posixpath.normpath(cur)
        for p in parts:
            cur = posixpath.normpath(posixpath.join(cur, p))
            try:
                client.request_json("POST", "/api/fs/mkdir", json={"path": cur}, ensure_success=False)
            except Exception:
                pass

    def _ensure_openlist_abs_dir(self, client, abs_dir: str, *, log: ExecutionLog | None = None) -> None:
        abs_dir = str(abs_dir or "").strip() or "/"
        abs_dir = "/" + abs_dir.lstrip("/")
        abs_dir = posixpath.normpath(abs_dir)
        if abs_dir in {"/", "."}:
            return
        parts = [p for p in abs_dir.split("/") if p]
        cur = "/"
        for p in parts:
            cur = posixpath.normpath(posixpath.join(cur, p))
            try:
                resp = client.request_json("POST", "/api/fs/mkdir", json={"path": cur}, ensure_success=False)
                code = resp.get("code") if isinstance(resp, dict) else None
                if code is not None and str(code) != "200" and log is not None:
                    log.line(f"openlist mkdir non-200: path={cur} code={code} message={str(resp.get('message') or '')}")
            except Exception as e:
                if log is not None:
                    log.line(
                        f"openlist mkdir exception: path={cur} err={str(e).strip() or type(e).__name__} "
                        f"http_status={getattr(e, 'http_status', None)} api_code={getattr(e, 'api_code', None)} api_message={getattr(e, 'api_message', None)}"
                    )

    def _persist_snapshots(self, sync_task_id: int, source_map: dict[str, FileMeta], target_map: dict[str, FileMeta]) -> None:
        self.db.execute(delete(SyncFileSnapshot).where(SyncFileSnapshot.sync_task_id == sync_task_id))
        now = datetime.now()
        rows: list[SyncFileSnapshot] = []
        for side, mp in (("source", source_map), ("target", target_map)):
            for rel, meta in mp.items():
                rows.append(
                    SyncFileSnapshot(
                        sync_task_id=sync_task_id,
                        side=side,
                        rel_path=_norm_rel(rel),
                        is_dir=bool(meta.is_dir),
                        size=int(meta.size),
                        modified_at=float(meta.modified_at),
                        hash=None,
                        created_at=now,
                    )
                )
        self.db.add_all(rows)
        self.db.flush()

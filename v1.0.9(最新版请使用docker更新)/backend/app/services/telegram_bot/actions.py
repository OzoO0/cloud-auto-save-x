from __future__ import annotations

import json
import posixpath
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.routes.tasks import post_share_preview
from app.core.errors import ApiError, bad_request, not_found
from app.extensions.adapters.adapter_factory import AdapterFactory
from app.extensions.adapters.aliyun_adapter import AliyunAdapter
from app.extensions.adapters.drive_auth import DriveAuthRequired
from app.extensions.runtime.account_manager import DatabaseAccountManager
from app.extensions.runtime.adapter_registry import AdapterRegistry
from app.models.drive_account import DriveAccount
from app.models.notification_setting import NotificationSetting
from app.models.sync_execution import SyncExecution
from app.models.sync_task import SyncTask
from app.models.sync_task_drama_link import SyncTaskDramaLink
from app.models.task import Task
from app.models.task_execution import TaskExecution
from app.services.drive_account_auth_sessions import create_auth_session, delete_auth_session, get_auth_session
from app.services.dashboard_drama import build_drama_overview
from app.services.drive_account_probe_scheduler import (
    get_or_create_drive_account_probe_scheduler_setting,
    update_drive_account_probe_scheduler_setting,
)
from app.services.drive_accounts import (
    build_capacity_overview,
    create_drive_account,
    get_drive_account,
    list_drive_accounts,
    probe_drive_account,
    refresh_drive_account_profiles,
    serialize_drive_account,
    set_default_drive_account,
    set_drive_account_enabled,
    sign_in_drive_account,
    supported_drive_types,
    update_drive_account,
)
from app.services.magic_regex import list_enabled_effective_rules_for_picker
from app.services.media_discovery import tmdb_detail, tmdb_search
from app.services.notifications.sender import send_test
from app.services.notifications import legacy_notify
from app.services.notifications.settings import (
    get_or_create_notification_setting,
    get_runtime_notification_config,
    update_notification_setting,
)
from app.services.openlist_client_factory import get_openlist_client
from app.services.share_preview_batch import preview_share_batch
from app.services.openlist_settings import get_or_create_openlist_setting, load_openlist_config, update_openlist_setting
from app.services.resource_search import fetch_task_suggestions, list_sources, update_source
from app.schemas.task_browse import SharePreviewBatchIn, SharePreviewIn
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
from app.extensions.runtime.sync_executor import SyncExecutor
from app.services.task_scheduler import get_or_create_task_scheduler_setting, update_task_scheduler_setting
from app.services.tasks import (
    create_task,
    delete_task,
    get_task,
    list_tasks_recent_executions,
    set_task_enabled,
    update_task,
)
from app.extensions.runtime.task_executor import TaskExecutor
from app.services.tmdb_settings import get_or_create_tmdb_setting, get_tmdb_runtime_config, load_tmdb_config, update_tmdb_setting


def _loads(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        payload = json.loads(value)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _dump_dt(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _loads_json_detail(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        payload = json.loads(value)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _pick_default_account_name(db: Session, drive_type: str) -> str | None:
    active = (
        db.execute(
            select(DriveAccount)
            .where(DriveAccount.enabled.is_(True), DriveAccount.drive_type == drive_type, DriveAccount.runtime_status == "active")
            .order_by(DriveAccount.is_default.desc(), DriveAccount.id.asc())
        )
        .scalars()
        .first()
    )
    if active is not None:
        return str(active.name)
    fallback = (
        db.execute(
            select(DriveAccount)
            .where(DriveAccount.enabled.is_(True), DriveAccount.drive_type == drive_type)
            .order_by(DriveAccount.is_default.desc(), DriveAccount.id.asc())
        )
        .scalars()
        .first()
    )
    return None if fallback is None else str(fallback.name)


def _pick_any_default_account(db: Session) -> DriveAccount | None:
    active = (
        db.execute(
            select(DriveAccount)
            .where(DriveAccount.enabled.is_(True), DriveAccount.runtime_status == "active")
            .order_by(DriveAccount.is_default.desc(), DriveAccount.id.asc())
        )
        .scalars()
        .first()
    )
    if active is not None:
        return active
    return (
        db.execute(select(DriveAccount).where(DriveAccount.enabled.is_(True)).order_by(DriveAccount.is_default.desc(), DriveAccount.id.asc()))
        .scalars()
        .first()
    )


def _get_active_account(db: Session, account_name: str) -> DriveAccount | None:
    name = str(account_name or "").strip()
    if not name:
        return None
    active = (
        db.execute(
            select(DriveAccount).where(
                DriveAccount.enabled.is_(True),
                DriveAccount.name == name,
                DriveAccount.runtime_status == "active",
            )
        )
        .scalars()
        .first()
    )
    if active is not None:
        return active
    return (
        db.execute(select(DriveAccount).where(DriveAccount.enabled.is_(True), DriveAccount.name == name))
        .scalars()
        .first()
    )


def _bool_is_dir(payload: dict[str, Any]) -> bool:
    if payload.get("is_dir") is not None:
        return bool(payload.get("is_dir"))
    if payload.get("isdir") is not None:
        return str(payload.get("isdir")) in ("1", "true", "True")
    if payload.get("dir") is not None:
        return bool(payload.get("dir"))
    if payload.get("kind") in ("folder", "dir", "directory"):
        return True
    if payload.get("type") in ("folder", "dir"):
        return True
    if payload.get("type") in ("file",):
        return False
    if payload.get("file_type") is not None:
        value = str(payload.get("file_type"))
        if value in ("0", "dir", "folder"):
            return True
        if value in ("1", "file"):
            return False
    return False


def _pick_name(payload: dict[str, Any]) -> str:
    return str(
        payload.get("file_name")
        or payload.get("server_filename")
        or payload.get("fileName")
        or payload.get("name")
        or payload.get("title")
        or payload.get("fid")
        or payload.get("fs_id")
        or ""
    )


def _pick_fid(payload: dict[str, Any]) -> str:
    return str(payload.get("fid") or payload.get("fs_id") or payload.get("file_id") or payload.get("id") or payload.get("fileId") or "")


def _pick_updated_at(payload: dict[str, Any]) -> Any | None:
    return payload.get("updated_at") or payload.get("modified_at") or payload.get("mtime") or payload.get("update_time")


def _pick_size(payload: dict[str, Any]) -> int | None:
    value = payload.get("size")
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return None


def _tmdb_display_title(item: dict[str, Any]) -> str:
    media_type = str(item.get("media_type") or "").strip().lower()
    if media_type == "movie":
        return str(item.get("title") or item.get("original_title") or "").strip()
    return str(item.get("name") or item.get("original_name") or "").strip()


def _tmdb_display_date(item: dict[str, Any]) -> str:
    media_type = str(item.get("media_type") or "").strip().lower()
    if media_type == "movie":
        return str(item.get("release_date") or "").strip()
    return str(item.get("first_air_date") or "").strip()


def _tmdb_year(item: dict[str, Any]) -> str:
    raw = _tmdb_display_date(item)
    return raw[:4] if len(raw) >= 4 else ""


def _tmdb_standard_keyword(item: dict[str, Any]) -> str:
    title = _tmdb_display_title(item)
    year = _tmdb_year(item)
    media_type = str(item.get("media_type") or "").strip().lower()
    if media_type == "movie" and title and year:
        return f"{title} {year}"
    return title


def _first_http_url(text: str) -> str | None:
    normalized = str(text or "").strip().replace("？", "?").replace("＆", "&")
    match = re.search(r"https?://[^\s]+", normalized)
    if not match:
        return None
    return str(match.group(0) or "").strip() or None


def _all_http_urls(text: str) -> list[str]:
    normalized = str(text or "").strip().replace("？", "?").replace("＆", "&")
    urls = [str(x or "").strip() for x in re.findall(r"https?://[^\s]+", normalized)]
    return list(dict.fromkeys([x for x in urls if x]))


def _extract_share_fid(shareurl: str) -> str | None:
    url = str(shareurl or "").strip()
    if not url:
        return None
    match_query = re.search(r"(?:\?|&)fid=([^&#]+)", url)
    if match_query:
        fid = str(match_query.group(1) or "").strip()
        if fid and fid not in ("0", "root"):
            return fid
    match_hash = re.search(r"#/list/share/([a-zA-Z0-9]{6,64})", url)
    if match_hash:
        return str(match_hash.group(1) or "").strip() or None
    match_tail = re.search(r"/([a-fA-F0-9]{32})-?[^/]*$", url)
    if match_tail:
        return str(match_tail.group(1) or "").strip() or None
    return None


def _rewrite_shareurl_with_fid(shareurl: str, fid: str | None) -> str:
    raw = str(shareurl or "").strip()
    target_fid = str(fid or "").strip()
    if not raw:
        return raw
    if "yun.139.com" in raw or "caiyun.139.com" in raw:
        parsed = urlsplit(raw)
        if parsed.fragment:
            frag_path, frag_query = (parsed.fragment.split("?", 1) + [""])[:2]
            frag_pairs = [(k, v) for k, v in parse_qsl(frag_query, keep_blank_values=True) if str(k).lower() != "fid"]
            if target_fid and target_fid not in ("0", "root"):
                frag_pairs.append(("fid", target_fid))
            rebuilt_fragment = frag_path if not frag_pairs else f"{frag_path}?{urlencode(frag_pairs)}"
            return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, rebuilt_fragment)).strip()
        query_pairs = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if str(k).lower() != "fid"]
        if target_fid and target_fid not in ("0", "root"):
            query_pairs.append(("fid", target_fid))
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query_pairs), parsed.fragment)).strip()
    if not target_fid or target_fid == "0":
        match = re.search(r".*s/[a-zA-Z0-9\-_]+(\?[^#]*)?", raw)
        return str(match.group(0) if match else raw.split("#")[0]).strip()
    if target_fid in raw:
        match = re.search(rf".*/{re.escape(target_fid)}[^/]*", raw)
        if match:
            return str(match.group(0) or "").strip() or raw
    return f"{raw.split('#')[0]}#/list/share/{target_fid}"


def _is_video_filename(name: str) -> bool:
    return bool(re.search(r"\.(mp4|mkv|mov|m4v|avi|mpeg|ts|flv|wmv|webm|cas)$", str(name or "").strip(), flags=re.IGNORECASE))


def _to_sort_ts(value: Any) -> float:
    try:
        number = float(value)
        return number if number > 1e12 else number * 1000
    except Exception:
        pass
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.timestamp() * 1000
    except Exception:
        return 0.0


def _format_display_datetime(value: Any) -> str:
    if value in (None, ""):
        return "-"
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    raw = str(value).strip()
    if not raw:
        return "-"
    match = re.search(r"(-?\d{10,19})", raw)
    if match:
        try:
            number = float(match.group(1))
            while number > 1e12:
                number /= 1000.0
            if number > 0:
                return datetime.fromtimestamp(number).strftime("%Y-%m-%d %H:%M")
        except Exception:
            pass
    try:
        number = float(raw)
        while number > 1e12:
            number /= 1000.0
        if number > 0:
            return datetime.fromtimestamp(number).strftime("%Y-%m-%d %H:%M")
    except Exception:
        pass
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return raw


def _tv_progress_text(detail: dict[str, Any]) -> str:
    if not isinstance(detail, dict) or not detail:
        return ""
    seasons = int(detail.get("number_of_seasons") or 0) or 0
    total = int(detail.get("number_of_episodes") or 0) or 0
    last = detail.get("last_episode_to_air") if isinstance(detail.get("last_episode_to_air"), dict) else {}
    last_season = int((last or {}).get("season_number") or 0) or 0
    last_episode = int((last or {}).get("episode_number") or 0) or 0
    parts: list[str] = []
    if seasons > 0:
        parts.append(f"季数:{seasons}")
    if total > 0:
        parts.append(f"总集:{total}")
    if last_season > 0 and last_episode > 0:
        parts.append(f"当前:S{last_season:02d}E{last_episode:02d}")
    return " · ".join(parts)


def _task_execution_summary(execution: TaskExecution | None) -> dict[str, Any] | None:
    if execution is None:
        return None
    return {
        "id": int(execution.id),
        "status": str(execution.status or ""),
        "stage": str(getattr(execution, "stage", "") or "") or None,
        "message": str(execution.message or "") or None,
        "started_at": _dump_dt(execution.started_at),
        "finished_at": _dump_dt(execution.finished_at),
    }


def _sync_execution_summary(execution: SyncExecution | None) -> dict[str, Any] | None:
    if execution is None:
        return None
    return {
        "id": int(execution.id),
        "status": str(execution.status or ""),
        "stage": str(execution.stage or "") or None,
        "message": str(execution.message or "") or None,
        "started_at": _dump_dt(execution.started_at),
        "finished_at": _dump_dt(execution.finished_at),
        "cancel_requested_at": _dump_dt(getattr(execution, "cancel_requested_at", None)),
    }


def _task_to_dict(db: Session, task: Task) -> dict[str, Any]:
    sync_task_uids = db.execute(select(SyncTaskDramaLink.sync_task_uid).where(SyncTaskDramaLink.task_uid == str(task.task_uid))).scalars().all()
    sync_uid_list = [str(x) for x in sync_task_uids if x]
    sync_name_map: dict[str, str] = {}
    if sync_uid_list:
        rows = db.execute(select(SyncTask.uid, SyncTask.name).where(SyncTask.uid.in_(sync_uid_list))).all()
        sync_name_map = {str(uid): str(name or uid) for uid, name in rows if uid}
    latest_execution = None
    if getattr(task, "executions", None):
        latest_execution = sorted(task.executions, key=lambda x: x.id, reverse=True)[0]
    return {
        "id": int(task.id),
        "task_uid": str(task.task_uid),
        "task_type": str(task.task_type or ""),
        "taskname": str(task.taskname or ""),
        "shareurl": str(task.shareurl or ""),
        "savepath": str(task.savepath or ""),
        "pattern": task.pattern,
        "replace": task.replace,
        "enddate": task.enddate,
        "ignore_extension": bool(task.ignore_extension),
        "sort_index": task.sort_index,
        "startfid": task.startfid,
        "account_name": task.account_name,
        "update_subdir": task.update_subdir,
        "shareurl_ban": task.shareurl_ban,
        "tmdb_id": task.tmdb_id,
        "tmdb_media_type": task.tmdb_media_type,
        "enabled": bool(task.enabled),
        "addition": _loads(task.addition_json),
        "extra": _loads(task.extra_json),
        "sync_task_uids": sync_uid_list,
        "sync_task_names": [sync_name_map.get(uid, uid) for uid in sync_uid_list],
        "latest_execution": _task_execution_summary(latest_execution),
        "created_at": _dump_dt(task.created_at),
        "updated_at": _dump_dt(task.updated_at),
    }


def _sync_task_to_dict(db: Session, task: SyncTask) -> dict[str, Any]:
    links = db.execute(select(SyncTaskDramaLink.task_uid).where(SyncTaskDramaLink.sync_task_uid == str(task.uid))).scalars().all()
    drama_uid_list = [str(x) for x in links if x]
    drama_name_map: dict[str, str] = {}
    if drama_uid_list:
        rows = db.execute(select(Task.task_uid, Task.taskname).where(Task.task_uid.in_(drama_uid_list))).all()
        drama_name_map = {str(uid): str(name or uid) for uid, name in rows if uid}
    latest_execution = None
    if getattr(task, "executions", None):
        latest_execution = sorted(task.executions, key=lambda x: x.id, reverse=True)[0]
    return {
        "id": int(task.id),
        "uid": str(task.uid),
        "name": str(task.name or ""),
        "enabled": bool(task.enabled),
        "source": {"type": str(task.source_type or ""), "path": str(task.source_path or "")},
        "target": {"type": str(task.target_type or ""), "path": str(task.target_path or "")},
        "mode": str(task.mode or ""),
        "strategy": _loads(task.strategy_json),
        "addition": _loads(task.addition_json),
        "drama_task_uids": drama_uid_list,
        "drama_task_names": [drama_name_map.get(uid, uid) for uid in drama_uid_list],
        "latest_execution": _sync_execution_summary(latest_execution),
        "created_at": _dump_dt(task.created_at),
        "updated_at": _dump_dt(task.updated_at),
    }


@dataclass
class TelegramBotActions:
    db: Session

    def build_status_summary(self) -> dict[str, Any]:
        drama = build_drama_overview(self.db, days=30)
        capacity = build_capacity_overview(self.db)
        sync_total = self.db.execute(select(func.count(SyncTask.id))).scalar_one()
        sync_running = (
            self.db.execute(select(func.count(SyncExecution.id)).where(SyncExecution.status == "running", SyncExecution.finished_at.is_(None)))
            .scalar_one()
        )
        task_total = self.db.execute(select(func.count(Task.id))).scalar_one()
        task_enabled = self.db.execute(select(func.count(Task.id)).where(Task.enabled.is_(True))).scalar_one()
        return {
            "tasks_total": int(task_total or 0),
            "tasks_enabled": int(task_enabled or 0),
            "sync_total": int(sync_total or 0),
            "sync_running": int(sync_running or 0),
            "drama_summary": drama.get("summary") or {},
            "capacity_summary": (capacity.get("summary") or {}),
            "updated_at": _dump_dt(datetime.now()),
        }

    def list_tasks(self, *, page: int = 1, page_size: int = 8, task_type: str | None = None) -> dict[str, Any]:
        page = max(1, int(page or 1))
        items = list_tasks_recent_executions(self.db, limit=3)
        if task_type:
            items = [x for x in items if str(getattr(x, "task_type", "") or "") == task_type]
        total = len(items)
        start = (page - 1) * page_size
        sliced = items[start : start + page_size]
        return {"items": [_task_to_dict(self.db, x) for x in sliced], "total": total, "page": page, "page_size": page_size}

    def get_task_detail(self, task_id: int) -> dict[str, Any]:
        return _task_to_dict(self.db, get_task(self.db, int(task_id)))

    def toggle_task(self, task_id: int) -> dict[str, Any]:
        task = get_task(self.db, int(task_id))
        task = set_task_enabled(self.db, int(task.id), not bool(task.enabled))
        self.db.commit()
        self.db.refresh(task)
        return _task_to_dict(self.db, task)

    def delete_task(self, task_id: int) -> None:
        delete_task(self.db, int(task_id))
        self.db.commit()

    def save_task(self, *, task_id: int | None = None, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload or {})
        if task_id is None:
            task = create_task(self.db, **data)
        else:
            task = update_task(self.db, int(task_id), **data)
        self.db.commit()
        self.db.refresh(task)
        return _task_to_dict(self.db, task)

    def run_task(self, task_id: int) -> dict[str, Any]:
        task = get_task(self.db, int(task_id))
        execution = TaskExecutor(self.db).run_task(task)
        self.db.commit()
        self.db.refresh(execution)
        return _task_execution_summary(execution) or {}

    def list_task_executions(self, task_id: int, *, limit: int = 5) -> list[dict[str, Any]]:
        rows = (
            self.db.execute(select(TaskExecution).where(TaskExecution.task_id == int(task_id)).order_by(TaskExecution.id.desc()).limit(int(limit)))
            .scalars()
            .all()
        )
        return [_task_execution_summary(x) or {} for x in rows]

    def search_resources(self, keyword: str, *, drive_type: str | None = None) -> dict[str, Any]:
        items, changed, message = fetch_task_suggestions(self.db, keyword=keyword, deep=0, drive_type=drive_type)
        verified_items: list[dict[str, Any]] = [dict(x) for x in items]
        shareurls = [str(x.get("shareurl") or "").strip() for x in items if str(x.get("shareurl") or "").strip()]
        if shareurls:
            preview_map: dict[str, Any] = {}
            batch_size = 50
            preview_failed = False
            for offset in range(0, len(shareurls), batch_size):
                chunk = shareurls[offset : offset + batch_size]
                if not chunk:
                    continue
                try:
                    batch_out, preview_changed = preview_share_batch(self.db, SharePreviewBatchIn(shareurls=chunk, account_name=None))
                except Exception:
                    preview_failed = True
                    continue
                if preview_changed:
                    changed = True
                for row in batch_out.items or []:
                    key = str(row.shareurl or "").strip()
                    if key:
                        preview_map[key] = row
            ok_count = 0
            fail_count = 0
            for item in verified_items:
                shareurl = str(item.get("shareurl") or "").strip()
                if not shareurl:
                    continue
                preview_item = preview_map.get(shareurl)
                if preview_item is None:
                    item["verify"] = False
                    fail_count += 1
                    continue
                item["verify"] = bool(preview_item.ok)
                item["pdir_fid"] = str(preview_item.pdir_fid or preview_item.resolved_pdir_fid or "") or None
                item["resolved_pdir_fid"] = str(preview_item.resolved_pdir_fid or preview_item.pdir_fid or "") or None
                item["latest_video"] = preview_item.latest_video.model_dump(mode="json") if preview_item.latest_video is not None else None
                item["suggested_account_name"] = str(preview_item.suggested_account_name or "") or None
                if item["verify"]:
                    ok_count += 1
                else:
                    fail_count += 1
            max_size = max([int((x.get("latest_video") or {}).get("size") or 0) for x in verified_items] or [0])
            for item in verified_items:
                size = int((item.get("latest_video") or {}).get("size") or 0)
                item["max_video"] = bool(max_size > 0 and size == max_size)
            verified_items.sort(
                key=lambda x: (
                    -(int((x.get("latest_video") or {}).get("size") or 0)),
                    str(x.get("taskname") or ""),
                )
            )
            if ok_count or fail_count:
                extra = f"链接校验: 可用 {ok_count} / 不可用 {fail_count}"
                message = f"{message}; {extra}" if message else extra
            if preview_failed:
                extra = "部分链接校验失败，已跳过异常批次"
                message = f"{message}; {extra}" if message else extra
        else:
            verified_items = [dict(x) for x in items]
        if changed:
            self.db.commit()
        return {"items": verified_items, "message": message}

    def inspect_share_text(self, text: str) -> dict[str, Any] | None:
        raw_text = str(text or "").strip()
        if not raw_text:
            return None
        candidates = self.extract_share_candidates(raw_text)
        if not candidates:
            return None
        picked = candidates[0]
        return self.inspect_share_candidate(raw_text, str(picked.get("shareurl") or raw_text))

    def extract_share_candidates(self, text: str) -> list[dict[str, Any]]:
        raw_text = str(text or "").strip()
        if not raw_text:
            return []
        urls = _all_http_urls(raw_text)
        candidates: list[dict[str, Any]] = []
        for url in urls:
            drive_type = AdapterRegistry.detect_drive_type(url)
            if drive_type is None:
                continue
            candidates.append({"shareurl": url, "drive_type": drive_type})
        if candidates:
            return candidates
        drive_type = AdapterRegistry.detect_drive_type(raw_text)
        if drive_type is None:
            return []
        extracted_url = _first_http_url(raw_text) or raw_text
        return [{"shareurl": extracted_url, "drive_type": drive_type}]

    def inspect_share_candidate(self, text: str, shareurl: str) -> dict[str, Any] | None:
        raw_text = str(text or "").strip()
        picked_shareurl = str(shareurl or "").strip()
        if not raw_text or not picked_shareurl:
            return None
        drive_type = AdapterRegistry.detect_drive_type(picked_shareurl) or AdapterRegistry.detect_drive_type(raw_text)
        if drive_type is None:
            return None
        extracted_url = picked_shareurl
        adapter = AdapterFactory.create_adapter(str(drive_type), no_login=True, account_name="tg_share_text")
        pwd_id: str | None = None
        passcode = ""
        extracted_pdir_fid: Any = None
        if adapter is not None:
            try:
                pwd_id, passcode, extracted_pdir_fid, _ = adapter.extract_url(raw_text)
            except Exception:
                pwd_id = None
                passcode = ""
                extracted_pdir_fid = None
        if not pwd_id:
            return {
                "raw_text": raw_text,
                "shareurl": extracted_url,
                "drive_type": drive_type,
                "parsed": False,
                "preview_ok": False,
                "preview_message": "无法解析分享链接",
                "matched_task": None,
                "suggested_account_name": None,
                "resolved_pdir_fid": None,
                "latest_video": None,
            }

        shareurl_value = extracted_url
        preview_changed = False
        preview_item = None
        try:
            preview_out, preview_changed = preview_share_batch(self.db, SharePreviewBatchIn(shareurls=[raw_text], account_name=None))
            preview_item = (preview_out.items or [None])[0]
        except Exception as exc:
            preview_item = {"ok": False, "message": str(exc)}
        if preview_changed:
            self.db.commit()

        candidate_urls = [raw_text, extracted_url, shareurl_value]
        candidate_urls = [str(x).strip() for x in candidate_urls if str(x).strip()]
        candidate_urls = list(dict.fromkeys(candidate_urls))
        task = None
        if candidate_urls:
            task = (
                self.db.execute(select(Task).where(Task.shareurl.in_(candidate_urls)).order_by(Task.id.asc()))
                .scalars()
                .first()
            )

        latest_video: dict[str, Any] | None = None
        if preview_item is not None:
            latest_raw = getattr(preview_item, "latest_video", None)
            if latest_raw is not None:
                latest_video = latest_raw.model_dump(mode="json")
        return {
            "raw_text": raw_text,
            "shareurl": shareurl_value,
            "resolved_shareurl": _rewrite_shareurl_with_fid(shareurl_value, getattr(preview_item, "resolved_pdir_fid", None) or str(extracted_pdir_fid or "") or None),
            "drive_type": drive_type,
            "parsed": True,
            "pwd_id": pwd_id,
            "passcode": passcode,
            "preview_ok": bool(getattr(preview_item, "ok", False)),
            "preview_message": getattr(preview_item, "message", None),
            "suggested_account_name": getattr(preview_item, "suggested_account_name", None),
            "resolved_pdir_fid": getattr(preview_item, "resolved_pdir_fid", None) or str(extracted_pdir_fid or "") or None,
            "latest_video": latest_video,
            "matched_task": _task_to_dict(self.db, task) if task is not None else None,
        }

    def preview_task_share(
        self,
        *,
        shareurl: str,
        account_name: str | None = None,
        pdir_fid: str | None = None,
        max_items: int = 200,
        taskname: str | None = None,
        pattern: str | None = None,
        replace: str | None = None,
        sort_index: int | None = None,
        savepath: str | None = None,
        ignore_extension: bool | None = None,
        update_subdir: str | None = None,
        startfid: str | None = None,
        tmdb_id: int | None = None,
        tmdb_media_type: str | None = None,
    ) -> dict[str, Any]:
        payload = SharePreviewIn(
            shareurl=str(shareurl or "").strip(),
            account_name=str(account_name or "").strip() or None,
            pdir_fid=str(pdir_fid or "").strip() or None,
            max_items=int(max_items or 200),
            taskname=str(taskname or "").strip() or None,
            pattern=str(pattern or "").strip() or None,
            replace=str(replace or "").strip() or None,
            sort_index=sort_index,
            savepath=str(savepath or "").strip() or None,
            ignore_extension=ignore_extension,
            update_subdir=str(update_subdir or "").strip() or None,
            startfid=str(startfid or "").strip() or None,
            tmdb_id=tmdb_id,
            tmdb_media_type=str(tmdb_media_type or "").strip() or None,
        )
        out = post_share_preview(payload, db=self.db)
        data = out.model_dump(mode="json")
        resolved_fid = str(data.get("pdir_fid") or "").strip()
        data["shareurl"] = payload.shareurl
        data["resolved_shareurl"] = _rewrite_shareurl_with_fid(payload.shareurl, resolved_fid or payload.pdir_fid)
        items = list(data.get("items") or [])
        for item in items:
            if not isinstance(item, dict):
                continue
            item["updated_at_display"] = _format_display_datetime(item.get("updated_at"))
        items.sort(key=lambda x: (not bool(x.get("is_dir")), -_to_sort_ts(x.get("updated_at")), str(x.get("name") or "").lower()))
        data["items"] = items
        return data

    def search_tmdb_media(self, keyword: str, *, media_type: str = "multi", year: str | None = None) -> dict[str, Any]:
        configured, items, page_no, total_pages, total_results = tmdb_search(
            self.db, q=keyword, search_type=media_type, page=1, year=year
        )
        rows: list[dict[str, Any]] = []
        for item in items:
            row = dict(item)
            mt = str(row.get("media_type") or "").strip().lower()
            tid = int(row.get("id") or 0) or 0
            detail_data: dict[str, Any] = {}
            update_weekdays: list[int] = []
            episode_weekdays: list[int] = []
            if configured and mt in {"movie", "tv"} and tid > 0:
                try:
                    _ok, detail_data, update_weekdays, episode_weekdays = tmdb_detail(self.db, media_type=mt, tmdb_id=tid)  # type: ignore[arg-type]
                except Exception:
                    detail_data = {}
                    update_weekdays = []
                    episode_weekdays = []
            row["display_title"] = _tmdb_display_title(row)
            row["display_date"] = _tmdb_display_date(row)
            row["standard_keyword"] = _tmdb_standard_keyword(row)
            row["detail"] = detail_data
            row["progress_text"] = _tv_progress_text(detail_data) if mt == "tv" else ""
            row["update_weekdays"] = update_weekdays
            row["episode_weekdays"] = episode_weekdays
            rows.append(row)
        self.db.commit()
        return {
            "configured": configured,
            "items": rows,
            "page": page_no,
            "total_pages": total_pages,
            "total_results": total_results,
        }

    def replace_task_shareurl(
        self,
        task_id: int,
        shareurl: str,
        *,
        account_name: str | None = None,
        tmdb_id: int | None = None,
        tmdb_media_type: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"shareurl": shareurl}
        if account_name is not None:
            payload["account_name"] = account_name
        if tmdb_id:
            payload["tmdb_id"] = int(tmdb_id)
        if tmdb_media_type:
            payload["tmdb_media_type"] = str(tmdb_media_type)
        task = update_task(self.db, int(task_id), **payload)
        self.db.commit()
        self.db.refresh(task)
        return _task_to_dict(self.db, task)

    def list_sync_tasks(self, *, page: int = 1, page_size: int = 8) -> dict[str, Any]:
        page = max(1, int(page or 1))
        items = list_sync_tasks(self.db)
        total = len(items)
        start = (page - 1) * page_size
        sliced = items[start : start + page_size]
        return {"items": [_sync_task_to_dict(self.db, x) for x in sliced], "total": total, "page": page, "page_size": page_size}

    def list_sync_task_options(self) -> list[dict[str, Any]]:
        items = list_sync_tasks(self.db)
        return [
            {
                "id": int(item.id),
                "uid": str(item.uid or ""),
                "name": str(item.name or ""),
                "enabled": bool(item.enabled),
                "mode": str(item.mode or ""),
            }
            for item in items
        ]

    def list_drama_task_options(self) -> list[dict[str, Any]]:
        items = list_tasks_recent_executions(self.db, limit=1)
        return [
            {
                "id": int(item.id),
                "task_uid": str(item.task_uid or ""),
                "taskname": str(item.taskname or ""),
                "enabled": bool(item.enabled),
            }
            for item in items
            if str(getattr(item, "task_type", "") or "") == "drama"
        ]

    def get_sync_task_detail(self, sync_task_id: int) -> dict[str, Any]:
        return _sync_task_to_dict(self.db, get_sync_task(self.db, int(sync_task_id)))

    def toggle_sync_task(self, sync_task_id: int) -> dict[str, Any]:
        task = get_sync_task(self.db, int(sync_task_id))
        task = update_sync_task(self.db, int(task.id), enabled=(not bool(task.enabled)))
        self.db.commit()
        self.db.refresh(task)
        return _sync_task_to_dict(self.db, task)

    def delete_sync_task(self, sync_task_id: int) -> None:
        delete_sync_task(self.db, int(sync_task_id))
        self.db.commit()

    def save_sync_task(self, *, sync_task_id: int | None = None, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload or {})
        if sync_task_id is None:
            task = create_sync_task(self.db, **data)
        else:
            task = update_sync_task(self.db, int(sync_task_id), **data)
        self.db.commit()
        self.db.refresh(task)
        return _sync_task_to_dict(self.db, task)

    def run_sync_task(self, sync_task_id: int) -> dict[str, Any]:
        task = get_sync_task(self.db, int(sync_task_id))
        execution = SyncExecutor(self.db).run_sync_task(task)
        self.db.commit()
        self.db.refresh(execution)
        return _sync_execution_summary(execution) or {}

    def cancel_sync_task(self, sync_task_id: int) -> dict[str, Any] | None:
        execution = (
            self.db.execute(
                select(SyncExecution)
                .where(SyncExecution.sync_task_id == int(sync_task_id), SyncExecution.status == "running", SyncExecution.finished_at.is_(None))
                .order_by(SyncExecution.id.desc())
            )
            .scalars()
            .first()
        )
        if execution is None:
            return None
        now = datetime.now()
        execution.cancel_requested_at = now
        execution.stage = "aborting"
        execution.message = "cancel requested from tg"
        execution.heartbeat_at = now
        self.db.commit()
        self.db.refresh(execution)
        return _sync_execution_summary(execution)

    def list_sync_executions(self, sync_task_id: int, *, limit: int = 5) -> list[dict[str, Any]]:
        rows = list_sync_executions(self.db, int(sync_task_id), limit=int(limit))
        return [_sync_execution_summary(x) or {} for x in rows]

    def list_sync_execution_files_summary(self, sync_task_id: int, sync_execution_id: int, *, limit: int = 10) -> list[dict[str, Any]]:
        rows = list_sync_execution_files(self.db, int(sync_task_id), int(sync_execution_id), offset=0, limit=int(limit))
        return [{"path": str(x.path or ""), "action": str(x.action or ""), "status": str(x.status or ""), "message": str(x.message or "") or None} for x in rows]

    def list_accounts(self, *, page: int = 1, page_size: int = 8) -> dict[str, Any]:
        page = max(1, int(page or 1))
        items = [serialize_drive_account(x) for x in list_drive_accounts(self.db)]
        total = len(items)
        start = (page - 1) * page_size
        sliced = items[start : start + page_size]
        return {"items": sliced, "total": total, "page": page, "page_size": page_size}

    def get_account_detail(self, account_id: int) -> dict[str, Any]:
        return serialize_drive_account(get_drive_account(self.db, int(account_id)))

    def set_account_default(self, account_id: int) -> dict[str, Any]:
        account = set_default_drive_account(self.db, int(account_id))
        self.db.commit()
        self.db.refresh(account)
        return serialize_drive_account(account)

    def toggle_account(self, account_id: int) -> dict[str, Any]:
        account = get_drive_account(self.db, int(account_id))
        if bool(account.enabled):
            account = set_drive_account_enabled(self.db, int(account_id), False)
        else:
            account = probe_drive_account(self.db, int(account_id))
            if getattr(account, "runtime_status", None) == "active":
                account.enabled = True
        self.db.commit()
        self.db.refresh(account)
        return serialize_drive_account(account)

    def probe_account(self, account_id: int) -> dict[str, Any]:
        account = probe_drive_account(self.db, int(account_id))
        self.db.commit()
        self.db.refresh(account)
        return serialize_drive_account(account)

    def sign_in_account(self, account_id: int) -> dict[str, Any]:
        result = sign_in_drive_account(self.db, int(account_id))
        self.db.commit()
        return result

    def refresh_accounts(self) -> list[dict[str, Any]]:
        items = refresh_drive_account_profiles(self.db)
        self.db.commit()
        for item in items:
            self.db.refresh(item)
        return [serialize_drive_account(x) for x in items]

    def save_account(self, *, account_id: int | None = None, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload or {})
        if account_id is None:
            account = create_drive_account(self.db, **data)
        else:
            account = update_drive_account(self.db, int(account_id), **data)
        self.db.commit()
        self.db.refresh(account)
        return serialize_drive_account(account)

    def get_drive_types(self) -> list[dict[str, Any]]:
        return supported_drive_types()

    def list_account_names(self) -> list[str]:
        rows = (
            self.db.execute(select(DriveAccount.name).where(DriveAccount.enabled.is_(True)).order_by(DriveAccount.is_default.desc(), DriveAccount.id.asc()))
            .scalars()
            .all()
        )
        return [str(x) for x in rows if x]

    def list_magic_regex_rules(self) -> list[dict[str, str]]:
        return [dict(item) for item in list_enabled_effective_rules_for_picker(self.db)]

    def browse_task_drive(
        self,
        *,
        dir_path: str,
        account_name: str | None = None,
        shareurl: str | None = None,
        max_items: int = 100,
    ) -> dict[str, Any]:
        drive_type: str | None = None
        chosen_account = str(account_name or "").strip() or None
        if chosen_account:
            account = _get_active_account(self.db, chosen_account)
            if account is None:
                raise not_found("DRIVE_ACCOUNT_NOT_FOUND", "指定账号不存在或不可用")
            drive_type = str(account.drive_type)
        if not chosen_account:
            if shareurl:
                drive_type = AdapterRegistry.detect_drive_type(str(shareurl))
                if drive_type is None:
                    raise bad_request("TASK_SHAREURL_INVALID", "无法识别的网盘分享链接")
                chosen_account = _pick_default_account_name(self.db, drive_type)
            else:
                any_default = _pick_any_default_account(self.db)
                if any_default is not None:
                    chosen_account = str(any_default.name)
                    drive_type = str(any_default.drive_type)
        if not chosen_account:
            raise not_found("DRIVE_ACCOUNT_NOT_FOUND", "没有可用的驱动账号")

        manager = DatabaseAccountManager(self.db)
        task_payload = {"shareurl": shareurl or "", "account_name": chosen_account}
        manager.init_for_tasks([task_payload])
        adapter = manager.get_adapter_for_task(task_payload)
        if adapter is None:
            raise not_found("DRIVE_ACCOUNT_NOT_FOUND", "没有可用的驱动账号")

        raw_dir_path = str(dir_path or "").strip() or "/"
        is_fid_mode = ("/" not in raw_dir_path) and (raw_dir_path not in ("/", "0"))
        normalized_path = re.sub(r"/+", "/", raw_dir_path)
        if not normalized_path.startswith("/") and not is_fid_mode:
            normalized_path = "/" + normalized_path
        normalized_path = normalized_path.rstrip("/") or "/"

        paths: list[dict[str, str]] = []
        if raw_dir_path in ("/", "0"):
            pdir_fid = "0"
        elif is_fid_mode:
            pdir_fid = raw_dir_path
        else:
            fid_list = adapter.get_fids([normalized_path]) or []
            match = None
            for item in fid_list:
                item_path = item.get("file_path") or item.get("path") or item.get("filePath")
                if item_path == normalized_path:
                    match = item
                    break
            if match is None and fid_list:
                match = fid_list[0]
            pdir_fid = str(match.get("fid")) if match and match.get("fid") else None

            segments = [s for s in normalized_path.split("/") if s]
            if segments:
                accum_paths = ["/" + "/".join(segments[: i + 1]) for i in range(len(segments))]
                fid_arr = adapter.get_fids(accum_paths) or []
                fid_map: dict[str, str] = {}
                for item in fid_arr:
                    p = item.get("file_path") or item.get("path") or item.get("filePath")
                    f = item.get("fid")
                    if p and f:
                        fid_map[str(p)] = str(f)
                for i, name in enumerate(segments):
                    fid_val = fid_map.get(accum_paths[i])
                    if fid_val:
                        paths.append({"fid": fid_val, "name": name})

        if not pdir_fid:
            return {
                "account_name": chosen_account,
                "drive_type": drive_type,
                "dir_path": raw_dir_path,
                "exists": False,
                "pdir_fid": None,
                "items": [],
                "paths": paths,
            }

        listing = adapter.ls_dir(str(pdir_fid), max_items=int(max_items))
        raw_items = (((listing or {}).get("data") or {}).get("list")) or []
        items: list[dict[str, Any]] = []
        for raw in raw_items[: int(max_items)]:
            fid = _pick_fid(raw)
            name = _pick_name(raw)
            if not fid or not name:
                continue
            items.append(
                {
                    "fid": fid,
                    "name": name,
                    "is_dir": _bool_is_dir(raw),
                    "updated_at": _pick_updated_at(raw),
                    "size": _pick_size(raw),
                    "include_items": raw.get("children_count") or raw.get("include_items"),
                }
            )
        items.sort(key=lambda x: (not bool(x.get("is_dir")), str(x.get("name") or "").lower()))
        return {
            "account_name": chosen_account,
            "drive_type": drive_type,
            "dir_path": raw_dir_path,
            "exists": True,
            "pdir_fid": str(pdir_fid),
            "items": items,
            "paths": paths,
        }

    def browse_sync_path(self, *, path_type: str, dir_path: str, max_items: int = 100) -> dict[str, Any]:
        path_type = str(path_type or "").strip().lower()
        if path_type == "local":
            rel, exists, items, paths = browse_local_dir(dir_path)
            items.sort(key=lambda x: (not bool(x.get("is_dir")), str(x.get("name") or "").lower()))
            return {"path_type": path_type, "dir_path": rel, "exists": exists, "items": items[: int(max_items)], "paths": paths}
        if path_type == "openlist":
            client = get_openlist_client(self.db)
            normalized = "/" + posixpath.normpath(str(dir_path or "").strip() or "/").lstrip("/")
            if normalized != "/" and normalized.endswith("/"):
                normalized = normalized.rstrip("/")
            segments = [s for s in normalized.split("/") if s]
            paths = [{"name": name, "path": "/" + "/".join(segments[: i + 1])} for i, name in enumerate(segments)]
            try:
                resp = client.fs_list(normalized, refresh=False, page=1, per_page=int(max_items))
            except Exception:
                return {"path_type": path_type, "dir_path": normalized, "exists": False, "items": [], "paths": paths}
            data = resp.get("data") if isinstance(resp, dict) else None
            raw_items = None
            if isinstance(data, dict):
                raw_items = data.get("content") or data.get("items") or data.get("list") or data.get("files")
            if raw_items is None and isinstance(resp, dict):
                raw_items = resp.get("content") or resp.get("items") or resp.get("list") or resp.get("files")
            if not isinstance(raw_items, list):
                raw_items = []
            items: list[dict[str, Any]] = []
            for it in raw_items[: int(max_items)]:
                if not isinstance(it, dict):
                    continue
                name = str(it.get("name") or it.get("file_name") or it.get("fileName") or it.get("title") or "").strip()
                if not name or name in {".", ".."}:
                    continue
                full = posixpath.join(normalized.rstrip("/") or "/", name)
                if not full.startswith("/"):
                    full = "/" + full
                items.append(
                    {
                        "name": name,
                        "path": full,
                        "is_dir": bool(it.get("is_dir")) if it.get("is_dir") is not None else _bool_is_dir(it),
                        "updated_at": it.get("updated_at") or it.get("modified_at") or it.get("mtime"),
                        "size": _pick_size(it),
                    }
                )
            items.sort(key=lambda x: (not bool(x.get("is_dir")), str(x.get("name") or "").lower()))
            return {"path_type": path_type, "dir_path": normalized, "exists": True, "items": items, "paths": paths}
        raise ValueError("不支持的路径类型")

    def start_account_auth(self, account_id: int) -> dict[str, Any]:
        account = get_drive_account(self.db, int(account_id))
        if str(account.drive_type or "") == "aliyun":
            resp = AliyunAdapter.generate_qrcode()
            if not isinstance(resp, dict) or not resp.get("success"):
                raise bad_request("DRIVE_ACCOUNT_AUTH_FAILED", "生成二维码失败", detail=str((resp or {}).get("message") or ""))
            data = resp.get("data") or {}
            session = create_auth_session(
                account_id=account.id,
                drive_type=account.drive_type,
                method="qrcode",
                adapter={"t": data.get("t") or "", "ck": data.get("ck") or ""},
                payload={"qrcode_url": data.get("qrCodeUrl") or "", "status": "NEW"},
            )
            return {
                "account_id": int(account.id),
                "drive_type": str(account.drive_type or ""),
                "method": "qrcode",
                "session_id": session.session_id,
                "payload": dict(session.payload or {}),
            }
        try:
            probe_drive_account(self.db, int(account_id))
            self.db.commit()
        except ApiError as exc:
            if exc.code == "DRIVE_ACCOUNT_AUTH_REQUIRED":
                detail = _loads_json_detail(exc.detail)
                detail["message"] = exc.message
                return detail
            raise
        self.db.refresh(account)
        return {"account_id": int(account.id), "drive_type": str(account.drive_type or ""), "method": "done", "account": serialize_drive_account(account)}

    def get_account_auth_status(self, session_id: str) -> dict[str, Any]:
        session = get_auth_session(session_id)
        if session is None:
            raise not_found("DRIVE_ACCOUNT_AUTH_SESSION_NOT_FOUND", "认证会话已失效")
        return {
            "account_id": int(session.account_id),
            "drive_type": str(session.drive_type or ""),
            "method": str(session.method or ""),
            "session_id": str(session.session_id),
            "payload": dict(session.payload or {}),
        }

    def poll_account_auth_qrcode(self, session_id: str) -> dict[str, Any]:
        session = get_auth_session(session_id)
        if session is None:
            raise not_found("DRIVE_ACCOUNT_AUTH_SESSION_NOT_FOUND", "认证会话已失效")
        if session.method != "qrcode":
            raise bad_request("DRIVE_ACCOUNT_AUTH_METHOD_MISMATCH", "认证方式不匹配")
        meta = session.adapter or {}
        resp = AliyunAdapter.query_qrcode_status(str(meta.get("t") or ""), str(meta.get("ck") or ""))
        if not isinstance(resp, dict) or not resp.get("success"):
            raise bad_request("DRIVE_ACCOUNT_AUTH_FAILED", "查询二维码状态失败", detail=str((resp or {}).get("message") or ""))
        data = resp.get("data") or {}
        if str(data.get("status") or "") == "CONFIRMED" and str(data.get("refresh_token") or ""):
            delete_auth_session(session_id)
            account = self.db.get(DriveAccount, int(session.account_id))
            if account is None:
                raise not_found("DRIVE_ACCOUNT_NOT_FOUND", "驱动账号不存在")
            config = AdapterRegistry.parse_config_json(account.drive_type, account.config_json, account.cookie)
            config["refresh_token"] = str(data.get("refresh_token") or "")
            update_drive_account(self.db, account.id, config=config)
            account = probe_drive_account(self.db, account.id)
            self.db.commit()
            self.db.refresh(account)
            return {"done": True, "account": serialize_drive_account(account)}
        session.payload.update({"status": str(data.get("status") or ""), "message": str(data.get("message") or "")})
        self.db.commit()
        return {
            "done": False,
            "account_id": int(session.account_id),
            "drive_type": str(session.drive_type or ""),
            "method": "qrcode",
            "session_id": str(session.session_id),
            "payload": dict(session.payload or {}),
        }

    def send_account_auth_sms(self, session_id: str) -> dict[str, Any]:
        session = get_auth_session(session_id)
        if session is None:
            raise not_found("DRIVE_ACCOUNT_AUTH_SESSION_NOT_FOUND", "认证会话已失效")
        if session.method != "sms":
            raise bad_request("DRIVE_ACCOUNT_AUTH_METHOD_MISMATCH", "认证方式不匹配")
        result = session.adapter.send_sms()
        self.db.commit()
        return result if isinstance(result, dict) else {"ok": True, "message": str(result)}

    def submit_account_auth_code(self, session_id: str, code: str) -> dict[str, Any]:
        session = get_auth_session(session_id)
        if session is None:
            raise not_found("DRIVE_ACCOUNT_AUTH_SESSION_NOT_FOUND", "认证会话已失效")
        if session.method == "captcha":
            try:
                session.adapter.submit_captcha(code)
            except DriveAuthRequired as exc:
                delete_auth_session(session_id)
                new_session = create_auth_session(
                    account_id=int(session.account_id),
                    drive_type=str(session.drive_type or ""),
                    method=exc.method,
                    adapter=exc.adapter or session.adapter,
                    payload=exc.payload,
                )
                return {
                    "done": False,
                    "account_id": int(session.account_id),
                    "drive_type": str(session.drive_type or ""),
                    "method": exc.method,
                    "session_id": new_session.session_id,
                    "payload": dict(exc.payload or {}),
                }
        elif session.method == "sms":
            session.adapter.submit_sms(code)
        else:
            raise bad_request("DRIVE_ACCOUNT_AUTH_METHOD_MISMATCH", "认证方式不匹配")
        delete_auth_session(session_id)
        update_drive_account(self.db, int(session.account_id), config=session.adapter.export_runtime_config())
        account = probe_drive_account(self.db, int(session.account_id))
        self.db.commit()
        self.db.refresh(account)
        return {"done": True, "account": serialize_drive_account(account)}

    def list_setting_domains(self) -> list[dict[str, str]]:
        return [
            {"key": "notifications", "label": "通知配置"},
            {"key": "task_scheduler", "label": "任务调度"},
            {"key": "probe_scheduler", "label": "账号探测调度"},
            {"key": "resource_sources", "label": "资源搜索源"},
            {"key": "tmdb", "label": "TMDB"},
            {"key": "openlist", "label": "OpenList"},
        ]

    def get_setting_domain(self, key: str) -> dict[str, Any]:
        if key == "notifications":
            item = get_or_create_notification_setting(self.db)
            current = get_runtime_notification_config(self.db)
            return {
                "key": key,
                "label": "通知配置",
                "values": {**dict(legacy_notify.DEFAULT_PUSH_CONFIG), **current},
                "default_values": dict(legacy_notify.DEFAULT_PUSH_CONFIG),
                "updated_at": _dump_dt(getattr(item, "updated_at", None)),
            }
        if key == "task_scheduler":
            item = get_or_create_task_scheduler_setting(self.db)
            return {"key": key, "label": "任务调度", "values": {"enabled": bool(item.enabled), "crontab": str(item.crontab), "timezone": str(item.timezone)}}
        if key == "probe_scheduler":
            item = get_or_create_drive_account_probe_scheduler_setting(self.db)
            return {
                "key": key,
                "label": "账号探测调度",
                "values": {
                    "enabled": bool(item.enabled),
                    "crontab": str(item.crontab),
                    "timezone": str(item.timezone),
                    "enabled_only": bool(item.enabled_only),
                },
            }
        if key == "resource_sources":
            return {"key": key, "label": "资源搜索源", "values": {"sources": list_sources(self.db)}}
        if key == "tmdb":
            item = get_or_create_tmdb_setting(self.db)
            runtime = get_tmdb_runtime_config(item)
            values = load_tmdb_config(item)
            values["api_key"] = runtime.get("api_key") or ""
            return {"key": key, "label": "TMDB", "values": values}
        if key == "openlist":
            item = get_or_create_openlist_setting(self.db)
            values = load_openlist_config(item)
            values["token"] = str(getattr(item, "token", "") or "")
            return {"key": key, "label": "OpenList", "values": values}
        raise ValueError(f"unsupported setting domain: {key}")

    def update_setting_value(self, domain: str, field: str, value: Any) -> dict[str, Any]:
        if domain == "notifications":
            current = get_runtime_notification_config(self.db)
            current[str(field)] = value
            update_notification_setting(self.db, config=current)
        elif domain == "task_scheduler":
            payload = {field: value}
            update_task_scheduler_setting(self.db, **payload)
        elif domain == "probe_scheduler":
            payload = {field: value}
            update_drive_account_probe_scheduler_setting(self.db, **payload)
        elif domain == "resource_sources":
            source_key, _, source_field = field.partition(".")
            payload = {source_field: value}
            update_source(self.db, source_key, payload)
        elif domain == "tmdb":
            update_tmdb_setting(self.db, payload={field: value})
        elif domain == "openlist":
            update_openlist_setting(self.db, payload={field: value})
        else:
            raise ValueError(f"unsupported setting domain: {domain}")
        self.db.commit()
        return self.get_setting_domain(domain)

    def send_notification_test(self, title: str, content: str, channels: list[str] | None = None) -> list[dict[str, Any]]:
        config = get_runtime_notification_config(self.db)
        return send_test(title, content, config=config, channels=channels)

    def raw_notification_keys(self) -> list[str]:
        item = get_or_create_notification_setting(self.db)
        current = get_runtime_notification_config(self.db)
        saved = _loads(getattr(item, "config_json", None))
        return sorted({*legacy_notify.DEFAULT_PUSH_CONFIG.keys(), *saved.keys(), *current.keys()})

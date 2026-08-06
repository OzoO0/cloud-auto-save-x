from __future__ import annotations

from datetime import datetime
import json
import os
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.extensions.runtime.guessit_fallback import guessit_episode_numbers
from app.models.drive_account import DriveAccount
from app.models.task import Task
from app.models.task_savepath_snapshot import TaskSavepathSnapshot
from app.services.tmdb_cache import get_tmdb_detail_cached


_VIDEO_EXTS = {
    ".mp4",
    ".mkv",
    ".avi",
    ".ts",
    ".m2ts",
    ".mov",
    ".wmv",
    ".flv",
    ".webm",
    ".m4v",
    ".cas",
}


def _normalize_savepath(savepath: str | None) -> str | None:
    raw = str(savepath or "").strip()
    if not raw:
        return None
    if raw in {"0", "/"}:
        return "/"
    if not raw.startswith("/"):
        raw = "/" + raw
    raw = raw.rstrip("/")
    return raw or "/"


def _bool_is_dir(payload: dict) -> bool:
    if payload.get("is_dir") is not None:
        return bool(payload.get("is_dir"))
    if payload.get("isdir") is not None:
        return str(payload.get("isdir")) in ("1", "true", "True")
    if payload.get("dir") is not None:
        return bool(payload.get("dir"))
    if payload.get("kind") in ("folder", "dir", "directory"):
        return True
    if payload.get("kind") in ("file",):
        return False
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


def _pick_name(payload: dict) -> str:
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


def _pick_updated_at(payload: dict):
    return payload.get("updated_at") or payload.get("update_time") or payload.get("mtime") or payload.get("modified_at")


def _pick_size(payload: dict) -> int | None:
    if payload.get("size") is None:
        return None
    try:
        return int(payload.get("size"))
    except (TypeError, ValueError):
        return None


def _resolve_drive_account_id(db: Session, account_name: str) -> int | None:
    name = str(account_name or "").strip()
    if not name:
        return None
    return db.execute(select(DriveAccount.id).where(DriveAccount.name == name)).scalars().first()


def _resolve_dir_fid(adapter: Any, savepath: str) -> str | None:
    if savepath == "/":
        return "0"
    fid_list = adapter.get_fids([savepath]) or []
    match = None
    for item in fid_list:
        item_path = item.get("file_path") or item.get("path") or item.get("filePath")
        if str(item_path) == savepath:
            match = item
            break
    if match is None and fid_list:
        match = fid_list[0]
    fid = match.get("fid") if match else None
    return str(fid) if fid else None


def fetch_savepath_files(adapter: Any, savepath: str) -> list[dict[str, Any]]:
    fid = _resolve_dir_fid(adapter, savepath)
    if not fid:
        return []
    listing = adapter.ls_dir(str(fid), max_items=0) or {}
    raw_items = (((listing or {}).get("data") or {}).get("list")) or []
    result: list[dict[str, Any]] = []
    for raw in raw_items:
        if _bool_is_dir(raw):
            continue
        name = _pick_name(raw)
        if not name:
            continue
        size = _pick_size(raw)
        updated_at = _pick_updated_at(raw)
        result.append({"file_name": name, "size": size, "updated_at": updated_at})
    return result


def _is_video_name(name: str) -> bool:
    base, ext = os.path.splitext(str(name or ""))
    if not base:
        return False
    if not ext:
        return True
    return ext.lower() in _VIDEO_EXTS


def _pick_tv_seasons(details: dict[str, Any] | None) -> list[dict[str, Any]] | None:
    if not isinstance(details, dict):
        return None
    raw = details.get("seasons")
    return raw if isinstance(raw, list) else None


def resolve_saved_latest_progress(
    db: Session,
    *,
    task_uid: str,
    files: list[dict[str, Any]],
) -> tuple[int | None, int | None, str | None]:
    uid = str(task_uid or "").strip()
    if not uid or not files:
        return None, None, None

    task = db.execute(select(Task).where(Task.task_uid == uid)).scalars().first()
    if task is None:
        return None, None, None
    if str(getattr(task, "task_type", "") or "") != "drama":
        return None, None, None
    if str(getattr(task, "tmdb_media_type", "") or "").strip().lower() != "tv":
        return None, None, None
    try:
        tmdb_id = int(getattr(task, "tmdb_id", 0) or 0)
    except Exception:
        tmdb_id = 0
    if tmdb_id <= 0:
        return None, None, None

    configured, detail, _update_weekdays, _episode_weekdays, _row = get_tmdb_detail_cached(
        db,
        media_type="tv",
        tmdb_id=tmdb_id,
    )
    if not configured or not isinstance(detail, dict):
        return None, None, None

    tv_seasons = _pick_tv_seasons(detail)
    best_key: tuple[int, int] | None = None
    best_name: str | None = None
    for item in files:
        if not isinstance(item, dict):
            continue
        name = str(item.get("file_name") or "").strip()
        if not name or not _is_video_name(name):
            continue
        season, episode = guessit_episode_numbers(name, tv_seasons=tv_seasons)
        if season is None or episode is None:
            continue
        try:
            key = (int(season), int(episode))
        except Exception:
            continue
        if key[0] <= 0 or key[1] <= 0:
            continue
        if best_key is None or key > best_key:
            best_key = key
            best_name = name
    if best_key is None:
        return None, None, None
    return int(best_key[0]), int(best_key[1]), best_name


def upsert_task_savepath_snapshot(
    db: Session,
    *,
    task_uid: str,
    task_execution_id: int | None,
    drive_account_id: int | None,
    savepath: str,
    files: list[dict[str, Any]],
    saved_latest_season: int | None = None,
    saved_latest_episode: int | None = None,
    saved_latest_name: str | None = None,
) -> TaskSavepathSnapshot:
    files_json = json.dumps(files, ensure_ascii=False)
    file_count = len(files)
    total_size: int | None = 0
    for item in files:
        sz = item.get("size")
        if sz is None:
            total_size = None
            break
        try:
            total_size += int(sz)
        except (TypeError, ValueError):
            total_size = None
            break

    uid = str(task_uid or "").strip()
    if not uid:
        raise ValueError("task_uid required")
    row = db.execute(select(TaskSavepathSnapshot).where(TaskSavepathSnapshot.task_uid == uid)).scalars().first()
    if row is None:
        row = TaskSavepathSnapshot(
            task_uid=uid,
            task_execution_id=task_execution_id,
            drive_account_id=drive_account_id,
            savepath=savepath,
            files_json=files_json,
            file_count=file_count,
            total_size=total_size,
            saved_latest_season=saved_latest_season,
            saved_latest_episode=saved_latest_episode,
            saved_latest_name=saved_latest_name,
            captured_at=datetime.now(),
        )
        db.add(row)
        return row

    row.task_execution_id = task_execution_id
    row.drive_account_id = drive_account_id
    row.savepath = savepath
    row.files_json = files_json
    row.file_count = file_count
    row.total_size = total_size
    row.saved_latest_season = saved_latest_season
    row.saved_latest_episode = saved_latest_episode
    row.saved_latest_name = saved_latest_name
    row.captured_at = datetime.now()
    return row


def capture_and_upsert_snapshot(
    db: Session,
    *,
    task_uid: str,
    savepath: str | None,
    adapter: Any,
    account_name: str,
    emit_line: Any | None = None,
) -> TaskSavepathSnapshot | None:
    normalized = _normalize_savepath(savepath)
    if not normalized:
        return None

    drive_account_id = _resolve_drive_account_id(db, account_name)
    if drive_account_id is None:
        if emit_line:
            emit_line("保存路径快照: 跳过（无法解析 drive_account_id）")
        return None

    try:
        files = fetch_savepath_files(adapter, normalized)
    except Exception as e:
        if emit_line:
            emit_line(f"保存路径快照: 失败（{str(e)}）")
        return None

    saved_latest_season = None
    saved_latest_episode = None
    saved_latest_name = None
    try:
        saved_latest_season, saved_latest_episode, saved_latest_name = resolve_saved_latest_progress(
            db,
            task_uid=str(task_uid or "").strip(),
            files=files,
        )
    except Exception as e:
        if emit_line:
            emit_line(f"快照进度解析: 失败（{str(e)}）")

    if emit_line:
        emit_line(f"保存路径快照: OK（{len(files)} 个文件）")
        if saved_latest_season is not None and saved_latest_episode is not None:
            emit_line(f"快照进度解析: S{int(saved_latest_season):02d}E{int(saved_latest_episode):02d}")
        else:
            emit_line("快照进度解析: 未识别到剧集文件")
    return upsert_task_savepath_snapshot(
        db,
        task_uid=task_uid,
        task_execution_id=None,
        drive_account_id=drive_account_id,
        savepath=normalized,
        files=files,
        saved_latest_season=saved_latest_season,
        saved_latest_episode=saved_latest_episode,
        saved_latest_name=saved_latest_name,
    )

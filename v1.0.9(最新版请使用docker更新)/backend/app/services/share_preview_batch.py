from __future__ import annotations

import os
import random
import threading
import time
from typing import Any

from cachetools import TTLCache
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import not_found
from app.core.settings import settings
from app.db.session import SessionLocal
from app.extensions.runtime.account_manager import DatabaseAccountManager
from app.extensions.runtime.adapter_registry import AdapterRegistry
from app.models.drive_account import DriveAccount
from app.schemas.task_browse import SharePreviewBatchIn, SharePreviewBatchItemOut, SharePreviewBatchOut
from app.services.invalid_share_links import upsert_invalid_share_link
from app.services.share_preview_batch_cache import (
    get_cached_preview_batch_item,
    purge_old_preview_batch_cache,
    upsert_preview_batch_cache,
)


_share_preview_batch_cache = TTLCache(
    maxsize=max(1, int(getattr(settings, "tasks_share_preview_batch_cache_max_entries", 2000) or 2000)),
    ttl=max(1, int(getattr(settings, "tasks_share_preview_batch_cache_ttl_seconds", 300) or 300)),
)
_share_preview_batch_cache_lock = threading.Lock()


def cache_clear() -> None:
    with _share_preview_batch_cache_lock:
        _share_preview_batch_cache.clear()


def _share_preview_batch_cache_get(*, shareurl: str) -> SharePreviewBatchItemOut | None:
    key = shareurl
    with _share_preview_batch_cache_lock:
        hit = _share_preview_batch_cache.get(key)
    if hit is None:
        return None
    return hit.model_copy()


def _share_preview_batch_cache_set(*, shareurl: str, item: SharePreviewBatchItemOut) -> None:
    key = shareurl
    with _share_preview_batch_cache_lock:
        _share_preview_batch_cache[key] = item


def _should_persist_invalid_share_link(message: str | None) -> bool:
    msg = str(message or "").strip()
    if not msg:
        return False
    lowered = msg.lower()
    if any(
        x in lowered
        for x in (
            "timeout",
            "timed out",
            "connectionerror",
            "connecterror",
            "readtimeout",
            "proxyerror",
            "connection reset",
            "name or service not known",
            "temporary failure",
        )
    ):
        return False
    if any(x in msg for x in ("超时", "连接超时", "网络", "连接失败", "连接被重置")):
        return False
    if "没有可用的驱动账号" in msg:
        return False
    if "指定账号不存在" in msg:
        return False
    if "登录失败" in msg:
        return False
    if "响应解析失败" in msg:
        return False
    if "cookie" in lowered and any(x in msg for x in ("失效", "过期", "被限流", "限流")):
        return False
    if any(x in msg for x in ("被限流", "限流")) or any(x in lowered for x in ("rate limit", "ratelimit", "too many requests")):
        return False
    return True


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


def _pick_fid(payload: dict) -> str:
    return str(payload.get("fid") or payload.get("fs_id") or payload.get("file_id") or payload.get("id") or payload.get("fileId") or "")


def _pick_updated_at(payload: dict):
    return payload.get("updated_at") or payload.get("update_time") or payload.get("mtime") or payload.get("modified_at")


def _pick_size(payload: dict) -> int | None:
    if payload.get("size") is None:
        return None
    try:
        return int(payload.get("size"))
    except (TypeError, ValueError):
        return None


video_exts = {
    ".mp4",
    ".mkv",
    ".avi",
    ".mov",
    ".wmv",
    ".flv",
    ".webm",
    ".m4v",
    ".ts",
    ".m2ts",
    ".mpg",
    ".mpeg",
    ".3gp",
    ".cas",
}


def _is_video_name(name: str) -> bool:
    try:
        _base, _ext = os.path.splitext(str(name or ""))
    except Exception:
        return False
    return bool(_ext) and _ext.lower() in video_exts


def _to_ts(v):
    try:
        return float(v)
    except Exception:
        return None


def _auto_resolve_latest_video(adapter, pwd_id: str, stoken: str, start_fid: str) -> tuple[str, dict | None]:
    current_fid = str(start_fid or "").strip()
    latest: dict | None = None
    for _depth in range(10):
        detail = adapter.get_detail(pwd_id, stoken, current_fid)
        raw_items = (((detail or {}).get("data") or {}).get("list")) or []
        files = [x for x in raw_items if not _bool_is_dir(x)]
        videos = [x for x in files if _is_video_name(_pick_name(x))]
        if videos:
            videos.sort(key=lambda x: _to_ts(_pick_updated_at(x)) or 0, reverse=True)
            hit = videos[0]
            latest = {
                "fid": _pick_fid(hit) or None,
                "name": _pick_name(hit) or None,
                "updated_at": _pick_updated_at(hit),
                "size": _pick_size(hit),
            }
            break
        dirs = [x for x in raw_items if _bool_is_dir(x)]
        if not dirs:
            break
        if len(dirs) > 1:
            dirs.sort(key=lambda x: _to_ts(_pick_updated_at(x)) or 0, reverse=True)
        next_dir = dirs[0]
        next_fid = str(_pick_fid(next_dir) or "").strip()
        if not next_fid or next_fid == current_fid:
            break
        current_fid = next_fid
    return current_fid, latest


def preview_share_batch(db: Session, payload: SharePreviewBatchIn) -> tuple[SharePreviewBatchOut, bool]:
    def _short_tx(fn):
        with SessionLocal() as s:
            s.expire_on_commit = False
            try:
                out = fn(s)
                s.commit()
                return out
            except Exception:
                s.rollback()
                raise

    shareurls = [str(x or "").strip() for x in (payload.shareurls or [])]
    shareurls = [x for x in shareurls if x]
    shareurls = list(dict.fromkeys(shareurls))
    if not shareurls:
        return SharePreviewBatchOut(items=[]), False

    cache_changed = False
    try:
        purged = _short_tx(
            lambda s: purge_old_preview_batch_cache(
                s,
                retention_seconds=int(
                    getattr(settings, "tasks_share_preview_batch_db_cache_retention_seconds", 7 * 24 * 60 * 60)
                    or 7 * 24 * 60 * 60
                ),
            )
        )
        if purged > 0:
            cache_changed = True
    except Exception:
        purged = 0

    per_drive: dict[str, list[str]] = {}
    items: list[SharePreviewBatchItemOut] = []
    for url in shareurls:
        cached = _share_preview_batch_cache_get(shareurl=url)
        if cached is not None:
            items.append(cached)
            continue
        try:
            row, hit_changed = _short_tx(lambda s: get_cached_preview_batch_item(s, shareurl=url))
        except Exception:
            row, hit_changed = (None, False)
        if row is not None:
            if not bool(row.ok):
                out = SharePreviewBatchItemOut(shareurl=row.shareurl, drive_type=row.drive_type, ok=bool(row.ok), message=row.message)
                items.append(out)
                _share_preview_batch_cache_set(shareurl=url, item=out)
                if hit_changed:
                    cache_changed = True
                continue
            drive_type = AdapterRegistry.detect_drive_type(url) or row.drive_type
        else:
            drive_type = AdapterRegistry.detect_drive_type(url)
        if drive_type is None:
            items.append(SharePreviewBatchItemOut(shareurl=url, drive_type=None, ok=False, message="无法识别的网盘分享链接"))
            continue
        per_drive.setdefault(str(drive_type), []).append(url)

    if not per_drive:
        return SharePreviewBatchOut(items=items), cache_changed

    manager = DatabaseAccountManager(db, no_login=True)
    invalid_changed = False

    def _safe_error(e: Exception) -> str:
        text = f"{type(e).__name__}: {str(e)}"
        text = text.strip() or type(e).__name__
        if len(text) > 240:
            text = text[:120] + " ... " + text[-80:]
        return text

    def _candidate_accounts_for_drive(drive_type: str) -> list[DriveAccount]:
        rows = (
            db.execute(select(DriveAccount).where(DriveAccount.enabled.is_(True), DriveAccount.drive_type == drive_type).order_by(DriveAccount.id.asc()))
            .scalars()
            .all()
        )
        rows.sort(
            key=lambda x: (
                0 if bool(getattr(x, "is_default", False)) else 1,
                0 if str(getattr(x, "runtime_status", "") or "") == "active" else 1,
                int(getattr(x, "id", 0) or 0),
            )
        )
        if payload.account_name:
            specified = str(payload.account_name or "").strip()
            if specified:
                hit = next((x for x in rows if str(x.name) == specified), None)
                if hit is None:
                    raise not_found("DRIVE_ACCOUNT_NOT_FOUND", "指定账号不存在或不可用")
                rows = [hit] + [x for x in rows if str(x.name) != specified]
        return rows

    adapter_cache: dict[str, object] = {}

    def _get_ready_adapter(account: DriveAccount):
        name = str(getattr(account, "name", "") or "").strip()
        if not name:
            return None
        cached = adapter_cache.get(name)
        if cached is not None:
            return cached
        adapter = manager.manager.get_adapter(name)
        if adapter is None:
            return None
        if (not bool(getattr(adapter, "is_active", False))) and (not bool(getattr(adapter, "no_login", False))):
            try:
                ok = adapter.init()
            except Exception:
                ok = None
            if not ok:
                return None
        adapter_cache[name] = adapter
        return adapter

    for drive_type, urls in per_drive.items():
        try:
            candidates = _candidate_accounts_for_drive(drive_type)
        except Exception as e:
            message = _safe_error(e)
            for url in urls:
                items.append(SharePreviewBatchItemOut(shareurl=url, drive_type=drive_type, ok=False, message=message))
            continue
        if not candidates:
            for url in urls:
                items.append(SharePreviewBatchItemOut(shareurl=url, drive_type=drive_type, ok=False, message="没有可用的驱动账号"))
            continue
        for url in urls:
            try:
                ok = False
                last_error: str | None = None
                used_name: str | None = None
                resolved_pdir_fid: str | None = None
                latest_video: dict | None = None
                for account in candidates:
                    adapter = _get_ready_adapter(account)
                    if adapter is None:
                        last_error = f"账号 {str(getattr(account, 'name', '') or '').strip()}: 不可用"
                        continue
                    try:
                        pwd_id, passcode, extracted_pdir_fid, _ = adapter.extract_url(url)
                    except Exception as e:
                        last_error = _safe_error(e)
                        break
                    if not pwd_id:
                        last_error = "无法解析分享链接"
                        break
                    try:
                        token_response = adapter.get_stoken(pwd_id, passcode or "")
                    except Exception as e:
                        last_error = f"账号 {str(getattr(account, 'name', '') or '').strip()}: {_safe_error(e)}"
                        continue
                    stoken = ((token_response or {}).get("data") or {}).get("stoken")
                    if not stoken:
                        message = (token_response or {}).get("message") or "获取分享 token 失败"
                        last_error = f"账号 {str(getattr(account, 'name', '') or '').strip()}: {str(message)}"
                        continue
                    try:
                        resolved_pdir_fid, latest_video = _auto_resolve_latest_video(adapter, pwd_id, stoken, extracted_pdir_fid or "")
                    except Exception as e:
                        last_error = f"账号 {str(getattr(account, 'name', '') or '').strip()}: {_safe_error(e)}"
                        continue
                    if latest_video and latest_video.get("name"):
                        try:
                            from app.extensions.runtime.guessit_fallback import guessit_episode_numbers

                            s, e2 = guessit_episode_numbers(str(latest_video.get("name") or ""), trace_tag="preview_batch")
                            if s is not None and e2 is not None:
                                latest_video["season"] = int(s)
                                latest_video["episode"] = int(e2)
                        except Exception:
                            pass
                    ok = True
                    used_name = str(getattr(account, "name", "") or "").strip() or None
                    break
                out = SharePreviewBatchItemOut(
                    shareurl=url,
                    drive_type=drive_type,
                    ok=ok,
                    message=None if ok else (last_error or "没有可用账号"),
                    suggested_account_name=used_name,
                    pdir_fid=resolved_pdir_fid if ok else None,
                    resolved_pdir_fid=resolved_pdir_fid if ok else None,
                    latest_video=latest_video if ok else None,
                )
                items.append(out)
                _share_preview_batch_cache_set(shareurl=url, item=out)
                try:
                    if _short_tx(
                        lambda s: upsert_preview_batch_cache(
                            s,
                            shareurl=out.shareurl,
                            drive_type=out.drive_type,
                            ok=out.ok,
                            message=out.message,
                            ttl_seconds=int(
                                getattr(settings, "tasks_share_preview_batch_db_cache_ttl_seconds", 6 * 60 * 60) or 6 * 60 * 60
                            ),
                        )
                    ):
                        cache_changed = True
                except Exception:
                    pass
                if (not out.ok) and _should_persist_invalid_share_link(out.message):
                    try:
                        if _short_tx(
                            lambda s: upsert_invalid_share_link(
                                s, shareurl=out.shareurl, drive_type=out.drive_type, message=out.message
                            )
                        ):
                            invalid_changed = True
                    except Exception:
                        pass
            except Exception as e:
                out = SharePreviewBatchItemOut(shareurl=url, drive_type=drive_type, ok=False, message=_safe_error(e))
                items.append(out)
                _share_preview_batch_cache_set(shareurl=url, item=out)
                try:
                    if _short_tx(
                        lambda s: upsert_preview_batch_cache(
                            s,
                            shareurl=out.shareurl,
                            drive_type=out.drive_type,
                            ok=out.ok,
                            message=out.message,
                            ttl_seconds=int(
                                getattr(settings, "tasks_share_preview_batch_db_cache_ttl_seconds", 6 * 60 * 60) or 6 * 60 * 60
                            ),
                        )
                    ):
                        cache_changed = True
                except Exception:
                    pass
                if _should_persist_invalid_share_link(out.message):
                    try:
                        if _short_tx(
                            lambda s: upsert_invalid_share_link(
                                s, shareurl=out.shareurl, drive_type=out.drive_type, message=out.message
                            )
                        ):
                            invalid_changed = True
                    except Exception:
                        pass
            finally:
                time.sleep(random.uniform(0.06, 0.22))

    return SharePreviewBatchOut(items=items), bool(invalid_changed or cache_changed)

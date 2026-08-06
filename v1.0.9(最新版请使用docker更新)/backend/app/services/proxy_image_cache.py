from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
import threading
import time
import uuid

from fastapi import Response
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
import requests
from starlette.background import BackgroundTask


@dataclass(frozen=True)
class ProxyImageCacheConfig:
    enabled: bool
    cache_dir: str
    ttl_seconds: int
    max_file_bytes: int
    max_total_bytes: int


_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _now_ts() -> int:
    return int(time.time())


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _safe_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _is_image_content_type(content_type: str | None) -> bool:
    if not content_type:
        return False
    return str(content_type).split(";", 1)[0].strip().lower().startswith("image/")


def resolve_proxy_image_cache_dir(*, database_url: str, explicit_dir: str | None) -> str:
    if explicit_dir and str(explicit_dir).strip():
        return str(explicit_dir).strip()
    if database_url.startswith("sqlite") and "///" in database_url:
        path = database_url.split("///", 1)[1]
        directory = os.path.dirname(path) or "./data"
        return os.path.join(directory, "cache", "proxy_image")
    return os.path.join("./data", "cache", "proxy_image")


def ensure_dir(path: str) -> bool:
    try:
        os.makedirs(path, exist_ok=True)
        return True
    except OSError:
        return False


def _get_lock(key: str) -> threading.Lock:
    with _locks_guard:
        lock = _locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _locks[key] = lock
        return lock


def _paths_for_url(cache_dir: str, url: str) -> tuple[str, str, str, str]:
    key = _sha256_hex(url)
    shard = key[:2]
    shard_dir = os.path.join(cache_dir, shard)
    meta_path = os.path.join(shard_dir, f"{key}.json")
    bin_path = os.path.join(shard_dir, f"{key}.bin")
    return key, shard_dir, meta_path, bin_path


def _read_meta(meta_path: str) -> dict | None:
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
        return None
    except (OSError, json.JSONDecodeError):
        return None


def _is_fresh(meta: dict) -> bool:
    expires_at = meta.get("expires_at")
    if not isinstance(expires_at, int):
        return False
    return expires_at > _now_ts()


def _format_etag(etag_hex: str) -> str:
    return f"\"{etag_hex}\""


def _if_none_match_hit(if_none_match: str | None, etag: str) -> bool:
    if not if_none_match:
        return False
    raw = str(if_none_match).strip()
    if not raw:
        return False
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if "*" in parts:
        return True
    if etag in parts:
        return True
    etag_unquoted = etag.strip("\"")
    return any(p.strip("\"") == etag_unquoted for p in parts)


def try_build_cached_response(
    *,
    cfg: ProxyImageCacheConfig,
    url: str,
    if_none_match: str | None,
    cache_control: str,
) -> tuple[Response | None, str]:
    if not cfg.enabled:
        return None, "BYPASS"

    key, shard_dir, meta_path, bin_path = _paths_for_url(cfg.cache_dir, url)
    if not os.path.exists(meta_path) or not os.path.exists(bin_path):
        return None, "MISS"

    meta = _read_meta(meta_path)
    if not meta or not _is_fresh(meta):
        _best_effort_delete(meta_path, bin_path)
        return None, "MISS"

    content_type = str(meta.get("content_type") or "image/jpeg")
    if not _is_image_content_type(content_type):
        _best_effort_delete(meta_path, bin_path)
        return None, "MISS"
    etag_hex = str(meta.get("etag") or key)
    etag = _format_etag(etag_hex)

    headers = {
        "Cache-Control": cache_control,
        "ETag": etag,
    }

    if _if_none_match_hit(if_none_match, etag):
        headers["X-Proxy-Cache"] = "HIT-304"
        return Response(status_code=304, headers=headers), "HIT-304"

    headers["X-Proxy-Cache"] = "HIT"
    return FileResponse(path=bin_path, media_type=content_type, headers=headers), "HIT"


def fetch_store_and_build_response(
    *,
    cfg: ProxyImageCacheConfig,
    session: requests.Session,
    url: str,
    cache_control: str,
    headers: dict[str, str] | None = None,
) -> tuple[Response, str]:
    if not cfg.enabled:
        return _bypass_stream(session=session, url=url, cache_control=cache_control, headers=headers), "BYPASS"

    key, shard_dir, meta_path, bin_path = _paths_for_url(cfg.cache_dir, url)
    if not ensure_dir(shard_dir):
        return _bypass_stream(session=session, url=url, cache_control=cache_control, headers=headers), "BYPASS"

    lock = _get_lock(key)
    with lock:
        cached, state = try_build_cached_response(cfg=cfg, url=url, if_none_match=None, cache_control=cache_control)
        if cached is not None:
            cached.headers["X-Proxy-Cache"] = "HIT"
            return cached, "HIT"

        res = session.get(url, stream=True, timeout=15, headers=headers)
        res.raise_for_status()
        content_type = res.headers.get("content-type") or "image/jpeg"
        if not _is_image_content_type(content_type):
            _best_effort_close(res)
            return (
                RedirectResponse(url=url, status_code=302, headers={"Cache-Control": cache_control, "X-Proxy-Cache": "BYPASS"}),
                "BYPASS",
            )
        content_length = _safe_int(res.headers.get("content-length"))
        if cfg.max_file_bytes > 0 and (content_length is None or content_length > cfg.max_file_bytes):
            return _bypass_stream_res(res=res, content_type=content_type, cache_control=cache_control), "BYPASS"

        tmp_path = os.path.join(shard_dir, f"{key}.{uuid.uuid4().hex}.tmp")
        hasher = hashlib.sha256()
        written = 0
        try:
            try:
                with open(tmp_path, "wb") as f:
                    for chunk in res.iter_content(chunk_size=8192):
                        if not chunk:
                            continue
                        written += len(chunk)
                        if cfg.max_file_bytes > 0 and written > cfg.max_file_bytes:
                            raise ValueError("proxy image too large")
                        hasher.update(chunk)
                        f.write(chunk)
            except (OSError, ValueError):
                return _bypass_stream(session=session, url=url, cache_control=cache_control, headers=headers), "BYPASS"

            etag_hex = hasher.hexdigest()
            os.replace(tmp_path, bin_path)
            meta = {
                "url": url,
                "content_type": content_type,
                "etag": etag_hex,
                "size": written,
                "created_at": _now_ts(),
                "expires_at": _now_ts() + max(int(cfg.ttl_seconds), 1),
            }
            try:
                _atomic_write_json(meta_path, meta)
                _enforce_total_size_limit(cfg=cfg)
            except OSError:
                pass
            headers = {
                "Cache-Control": cache_control,
                "ETag": _format_etag(etag_hex),
                "X-Proxy-Cache": "MISS",
            }
            return FileResponse(path=bin_path, media_type=content_type, headers=headers), "MISS"
        finally:
            _best_effort_close(res)
            _best_effort_delete(tmp_path, tmp_path)


def _atomic_write_json(path: str, data: dict) -> None:
    directory = os.path.dirname(path)
    if directory:
        ensure_dir(directory)
    tmp_path = f"{path}.{uuid.uuid4().hex}.tmp"
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(payload)
    os.replace(tmp_path, path)


def _best_effort_close(res: requests.Response) -> None:
    try:
        res.close()
    except Exception:
        return


def _best_effort_delete(path_a: str, path_b: str) -> None:
    for p in {path_a, path_b}:
        try:
            if p and os.path.exists(p):
                os.remove(p)
        except OSError:
            continue


def _bypass_stream(*, session: requests.Session, url: str, cache_control: str, headers: dict[str, str] | None = None) -> Response:
    res = session.get(url, stream=True, timeout=15, headers=headers)
    res.raise_for_status()
    content_type = res.headers.get("content-type") or "image/jpeg"
    if not _is_image_content_type(content_type):
        _best_effort_close(res)
        return RedirectResponse(url=url, status_code=302, headers={"Cache-Control": cache_control, "X-Proxy-Cache": "BYPASS"})
    return _bypass_stream_res(res=res, content_type=content_type, cache_control=cache_control)


def _bypass_stream_res(*, res: requests.Response, content_type: str, cache_control: str) -> Response:
    def iterator():
        for chunk in res.iter_content(chunk_size=8192):
            if chunk:
                yield chunk

    return StreamingResponse(
        iterator(),
        media_type=content_type,
        headers={"Cache-Control": cache_control, "X-Proxy-Cache": "BYPASS"},
        background=BackgroundTask(res.close),
    )


def _enforce_total_size_limit(*, cfg: ProxyImageCacheConfig) -> None:
    max_total = int(cfg.max_total_bytes or 0)
    if max_total <= 0:
        return
    root = cfg.cache_dir
    if not os.path.isdir(root):
        return

    items: list[tuple[int, str, str, int]] = []
    total = 0
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            if not name.endswith(".json"):
                continue
            meta_path = os.path.join(dirpath, name)
            bin_path = meta_path[:-5] + ".bin"
            try:
                st = os.stat(bin_path)
            except OSError:
                _best_effort_delete(meta_path, bin_path)
                continue
            meta = _read_meta(meta_path) or {}
            created_at = meta.get("created_at")
            created = int(created_at) if isinstance(created_at, int) else int(st.st_mtime)
            size = int(st.st_size)
            total += size
            items.append((created, meta_path, bin_path, size))

    if total <= max_total:
        return

    items.sort(key=lambda x: x[0])
    for _created, meta_path, bin_path, size in items:
        _best_effort_delete(meta_path, bin_path)
        total -= size
        if total <= max_total:
            break


def scan_proxy_image_cache_stats(*, cfg: ProxyImageCacheConfig) -> tuple[int, int, int]:
    root = str(cfg.cache_dir or "").strip()
    if not root or not os.path.isdir(root):
        return (0, 0, 0)

    total_files = 0
    total_bytes = 0
    stale_files = 0
    now = _now_ts()

    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            if not name.endswith(".json"):
                continue
            meta_path = os.path.join(dirpath, name)
            bin_path = meta_path[:-5] + ".bin"
            try:
                st = os.stat(bin_path)
            except OSError:
                _best_effort_delete(meta_path, bin_path)
                continue

            meta = _read_meta(meta_path) or {}
            expires_at = meta.get("expires_at")
            if isinstance(expires_at, int) and expires_at <= now:
                stale_files += 1

            total_files += 1
            total_bytes += int(st.st_size or 0)

    return (int(total_files), int(total_bytes), int(stale_files))


def purge_expired_proxy_image_cache(*, cfg: ProxyImageCacheConfig) -> tuple[int, int]:
    root = str(cfg.cache_dir or "").strip()
    if not root or not os.path.isdir(root):
        return (0, 0)

    deleted_files = 0
    deleted_bytes = 0
    now = _now_ts()

    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            if not name.endswith(".json"):
                continue
            meta_path = os.path.join(dirpath, name)
            bin_path = meta_path[:-5] + ".bin"
            meta = _read_meta(meta_path) or {}
            expires_at = meta.get("expires_at")
            if not isinstance(expires_at, int) or expires_at > now:
                continue
            try:
                st = os.stat(bin_path)
                deleted_bytes += int(st.st_size or 0)
            except OSError:
                pass
            _best_effort_delete(meta_path, bin_path)
            deleted_files += 1

    return (int(deleted_files), int(deleted_bytes))


def clear_proxy_image_cache(*, cfg: ProxyImageCacheConfig) -> tuple[int, int]:
    root = str(cfg.cache_dir or "").strip()
    if not root or not os.path.isdir(root):
        return (0, 0)

    deleted_files = 0
    deleted_bytes = 0

    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            if not name.endswith(".json"):
                continue
            meta_path = os.path.join(dirpath, name)
            bin_path = meta_path[:-5] + ".bin"
            try:
                st = os.stat(bin_path)
                deleted_bytes += int(st.st_size or 0)
            except OSError:
                pass
            _best_effort_delete(meta_path, bin_path)
            deleted_files += 1

    return (int(deleted_files), int(deleted_bytes))

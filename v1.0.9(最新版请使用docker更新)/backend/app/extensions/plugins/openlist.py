import time
import random
import threading
import posixpath
import re
import logging
import requests
from cachetools import TTLCache


logger = logging.getLogger(__name__)


class Openlist:
    plugin_name = "openlist"
    plugin_version = "0.1.0"

    default_config = {
        "url": "",
        "token": "",
        "storage_id": "",
        "root_dir": "",
    }

    default_task_config = {
        "enable": False,
        "driver": "",
        "mount_path": "",
        "root_dir": "",
        "password": "",
        "refresh": True,
    }

    is_active = False

    def __init__(self, **kwargs):
        self.url = ""
        self.token = ""
        self.storage_id = ""
        self.root_dir = ""

        self.timeout_seconds = 10
        self.max_retries = 3
        self.backoff_seconds = 0.5
        self.cache_ttl_seconds = 20
        self.cache_max_entries = 2048
        self.stale_ttl_seconds = 3600

        self.drivers = {}
        self.storage_mount_path = None

        self._cache_lock = threading.RLock()
        self._cache = TTLCache(maxsize=self.cache_max_entries, ttl=self.cache_ttl_seconds)
        self._stale_cache = {}
        self._last_discover_ts = 0.0

        if kwargs:
            for key in self.default_config:
                if key in kwargs:
                    setattr(self, key, kwargs[key])
            for key in (
                "timeout_seconds",
                "max_retries",
                "backoff_seconds",
                "cache_ttl_seconds",
                "cache_max_entries",
                "stale_ttl_seconds",
            ):
                if key in kwargs:
                    setattr(self, key, kwargs[key])

        self._rebuild_caches()

        if self.url and self.storage_id:
            if self._check_connection():
                ok, resolved = self.storage_id_to_path(self.storage_id, root_dir=self.root_dir)
                if ok:
                    mount_path, root_dir = resolved
                    self.storage_mount_path = mount_path
                    self.root_dir = root_dir
                    self.register_driver(
                        str(self.storage_id),
                        mount_path=self.storage_mount_path,
                        root_dir=self.root_dir,
                    )
                    self.is_active = True

    def _rebuild_caches(self):
        with self._cache_lock:
            max_entries = int(self.cache_max_entries) if self.cache_max_entries else 1
            max_entries = max(1, max_entries)
            ttl = float(self.cache_ttl_seconds) if self.cache_ttl_seconds else 0.0
            ttl = ttl if ttl > 0 else 0.001
            self._cache = TTLCache(
                maxsize=max_entries,
                ttl=ttl,
            )
            self._stale_cache = {}

    def _headers(self):
        headers = {}
        if self.token:
            headers["Authorization"] = self.token
        return headers

    def _request_json(self, method, url, *, params=None, json=None):
        last_exc = None
        for attempt in range(int(self.max_retries) + 1):
            try:
                resp = requests.request(
                    method,
                    url,
                    headers=self._headers(),
                    params=params,
                    json=json,
                    timeout=float(self.timeout_seconds),
                )
                if resp.status_code in (429, 500, 502, 503, 504):
                    raise requests.exceptions.HTTPError(f"status={resp.status_code}", response=resp)
                resp.raise_for_status()
                return resp.json()
            except Exception as e:
                last_exc = e
                if attempt >= int(self.max_retries):
                    break
                sleep_s = float(self.backoff_seconds) * (2**attempt)
                sleep_s = sleep_s + random.random() * max(0.0, sleep_s / 5)
                time.sleep(sleep_s)
        raise last_exc

    def _check_connection(self):
        try:
            data = self.list_dir("/", page=1, per_page=1, refresh=False)
            return data.get("code") == 200
        except Exception as e:
            logger.warning("%s: 连接失败 %s", self.plugin_name, e)
            return False

    def register_driver(self, key, *, mount_path, root_dir="/", password=""):
        if not key:
            raise ValueError("driver key required")
        if not mount_path:
            raise ValueError("mount_path required")
        mount_path = self._norm_path(mount_path)
        root_dir = root_dir or "/"
        root_dir = self._norm_path(root_dir)
        self.drivers[str(key)] = {
            "mount_path": mount_path,
            "root_dir": root_dir,
            "password": password or "",
            "source": "manual",
        }
        return self.drivers[str(key)]

    def storage_id_to_path(self, storage_id, *, root_dir=""):
        storage_id = str(storage_id or "").strip()
        root_dir = str(root_dir or "").strip()
        if match := re.match(r"^(\/[^:]*):(\/[^:]*)$", storage_id):
            mount_path = self._norm_path(match.group(1))
            root = self._norm_path(root_dir) if root_dir else self._norm_path(match.group(2))
            data = self.list_dir(mount_path, refresh=False, page=1, per_page=1)
            if data.get("code") != 200:
                return False, (None, None)
            return True, (mount_path, root)

        if re.match(r"^\d+$", storage_id):
            info = self.get_storage_info(storage_id)
            mount_path = info.get("mount_path") or info.get("mountPath") or info.get("mount")
            if mount_path:
                root = self._norm_path(root_dir) if root_dir else "/"
                return True, (self._norm_path(mount_path), root)
            return False, (None, None)

        mount_path = self._norm_path(storage_id)
        root = self._norm_path(root_dir) if root_dir else "/"
        data = self.list_dir(mount_path, refresh=False, page=1, per_page=1)
        if data.get("code") != 200:
            return False, (None, None)
        return True, (mount_path, root)

    def get_storage_info(self, storage_id):
        try:
            url = self._join("/api/admin/storage/get")
            data = self._request_json("GET", url, params={"id": str(storage_id)})
            if isinstance(data, dict) and data.get("code") == 200 and isinstance(data.get("data"), dict):
                return data["data"]
        except Exception:
            return {}
        return {}

    def discover_drivers(self, *, force=False):
        now = time.time()
        discover_refresh_seconds = getattr(self, "discover_refresh_seconds", 300)
        if not force and (now - float(self._last_discover_ts)) < float(discover_refresh_seconds):
            return self.drivers

        candidates = [
            "/api/admin/storage/list",
            "/api/admin/storage/get",
        ]
        discovered = {}
        for ep in candidates:
            try:
                url = self._join(ep)
                if ep.endswith("/list"):
                    data = self._request_json("GET", url)
                    if data.get("code") != 200:
                        continue
                    items = data.get("data") or []
                    for item in items:
                        key = item.get("id")
                        mount_path = item.get("mount_path") or item.get("mountPath") or item.get("mount")
                        if key is None or not mount_path:
                            continue
                        discovered[str(key)] = {
                            "mount_path": self._norm_path(mount_path),
                            "root_dir": "/",
                            "password": "",
                            "source": "discover",
                            "raw": item,
                        }
                    break
                if ep.endswith("/get"):
                    break
            except Exception:
                continue

        if discovered:
            self.drivers.update(discovered)
            self._last_discover_ts = now
        return self.drivers

    def resolve_path(self, *, driver=None, path="/"):
        path = self._norm_path(path)
        if not driver:
            return path, ""
        info = self.drivers.get(str(driver)) or {}
        mount_path = info.get("mount_path") or ""
        password = info.get("password") or ""
        if mount_path:
            return self._norm_path(posixpath.join(mount_path, path.lstrip("/"))), password
        return path, password

    def list_dir(
        self,
        path,
        *,
        driver=None,
        password="",
        refresh=False,
        page=1,
        per_page=30,
    ):
        page = int(page) if page else 1
        per_page = int(per_page) if per_page else 30
        per_page = max(1, min(100, per_page))
        resolved_path, driver_password = self.resolve_path(driver=driver, path=path)
        password = password or driver_password or ""

        cache_key = (driver or "", resolved_path, password, page, per_page)
        if not refresh:
            with self._cache_lock:
                cached = self._cache.get(cache_key)
            if cached is not None:
                out = dict(cached)
                out["cached"] = True
                out["degraded"] = False
                return out

        endpoints = ["/api/fs/listGet", "/api/fs/list"]
        payload = {
            "path": resolved_path,
            "password": password,
            "refresh": bool(refresh),
            "page": page,
            "per_page": per_page,
        }

        last_error = None
        for ep in endpoints:
            try:
                data = self._request_json("POST", self._join(ep), json=payload)
                if isinstance(data, dict) and data.get("code") == 200:
                    out = {
                        "code": 200,
                        "message": data.get("message") or "success",
                        "data": self._normalize_list_data(data.get("data") or {}),
                        "driver": str(driver) if driver else "",
                        "path": resolved_path,
                        "page": page,
                        "per_page": per_page,
                        "cached": False,
                        "degraded": False,
                    }
                    with self._cache_lock:
                        self._cache[cache_key] = out
                        self._stale_cache[cache_key] = (time.time(), out)
                    return out
                last_error = data
            except Exception as e:
                last_error = e

        degraded = self._get_stale(cache_key)
        if degraded is not None:
            out = dict(degraded)
            out["cached"] = False
            out["degraded"] = True
            return out

        if isinstance(last_error, dict):
            return {
                "code": int(last_error.get("code") or 500),
                "message": str(last_error.get("message") or "request failed"),
                "data": {},
                "driver": str(driver) if driver else "",
                "path": resolved_path,
                "page": page,
                "per_page": per_page,
                "cached": False,
                "degraded": False,
            }
        return {
            "code": 500,
            "message": str(last_error or "request failed"),
            "data": {},
            "driver": str(driver) if driver else "",
            "path": resolved_path,
            "page": page,
            "per_page": per_page,
            "cached": False,
            "degraded": False,
        }

    def refresh_dir(self, path, *, driver=None, password=""):
        path = self._norm_path(path)
        data = self.list_dir(path, driver=driver, password=password, refresh=True, page=1, per_page=1)
        if data.get("code") == 200:
            return True
        msg = str(data.get("message") or "")
        if "object not found" in msg or "not found" in msg:
            if path in ("/", ""):
                return False
            parent = self._norm_path(posixpath.dirname(path) or "/")
            if parent == path:
                return False
            return self.refresh_dir(parent, driver=driver, password=password)
        return False

    def run(self, task, **kwargs):
        try:
            addition = task.get("addition", {}).get(self.plugin_name, self.default_task_config) or {}
            savepath = task.get("savepath") or ""
            if not addition.get("enable", True):
                return task

            driver = addition.get("driver") or str(self.storage_id or "")
            mount_path = addition.get("mount_path") or self.storage_mount_path or ""
            root_dir = addition.get("root_dir") or self.root_dir or ""
            password = addition.get("password") or ""
            do_refresh = bool(addition.get("refresh", True))

            if do_refresh and savepath and mount_path and root_dir and savepath.startswith(root_dir):
                rel = savepath.replace(root_dir, "", 1).lstrip("/")
                target = self._norm_path(posixpath.join(mount_path, rel))
                ok = self.refresh_dir(target, driver=driver or None, password=password)
                if ok:
                    logger.info("%s: 刷新目录成功 %s", self.plugin_name, target)
                else:
                    logger.warning("%s: 刷新目录失败 %s", self.plugin_name, target)
            return task
        except Exception as e:
            logger.exception("%s: 运行出错 %s", self.plugin_name, e)
            return task

    def _get_stale(self, cache_key):
        with self._cache_lock:
            ts_out = self._stale_cache.get(cache_key)
        if not ts_out:
            return None
        ts, out = ts_out
        if (time.time() - float(ts)) > float(self.stale_ttl_seconds):
            return None
        return out

    def _normalize_list_data(self, data):
        content = data.get("content") or data.get("items") or []
        total = data.get("total")
        if total is None:
            total = len(content) if isinstance(content, list) else 0
        return {
            "content": content if isinstance(content, list) else [],
            "total": int(total) if isinstance(total, int) or str(total).isdigit() else total,
            "readme": data.get("readme") or "",
            "header": data.get("header") or "",
            "write": bool(data.get("write")) if "write" in data else None,
            "provider": data.get("provider") or "",
        }

    def _join(self, endpoint):
        base = (self.url or "").rstrip("/")
        endpoint = "/" + str(endpoint or "").lstrip("/")
        return base + endpoint

    def _norm_path(self, p):
        p = str(p or "").strip()
        if not p:
            return "/"
        p = p.replace("\\", "/")
        if not p.startswith("/"):
            p = "/" + p
        p = posixpath.normpath(p)
        if p == ".":
            return "/"
        return p

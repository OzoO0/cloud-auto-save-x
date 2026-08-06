import hashlib
import json
import logging
import posixpath
import random
import time
from typing import Any
from urllib.parse import urlencode

import requests


logger = logging.getLogger(__name__)


class Fnv_refresh_v2:
    plugin_name = "fnv_refresh_v2"
    plugin_version = "py-compat"

    default_config = {
        "tips": "填写 endpoint、mount_quark、secret、fnv_token 后即可启用；token/long_token 可选。",
        "endpoint": "",
        "username": "",
        "password": "",
        "mount_quark": "",
        "remove_useless_wait": 180,
        "token": "",
        "long_token": "",
        "secret": "",
        "fnv_token": "",
    }

    default_task_config: dict[str, Any] = {}

    def __init__(self, **kwargs):
        self.plugin_name = self.__class__.plugin_name
        self.session = requests.Session()
        self.is_active = False
        self.api_key = ""
        self.app_name = "trimemedia-web"

        for key, value in self.default_config.items():
            setattr(self, key, kwargs.get(key, value))

        self.endpoint = self._normalize_endpoint(self.endpoint)
        self.mount_quark = self._normalize_path(self.mount_quark)
        self.remove_useless_wait = self._as_int(self.remove_useless_wait, default=180)

        if not self.endpoint or not self.mount_quark:
            return

        if self.secret and self.fnv_token:
            self.is_active = True
            return

        if self.username and self.password:
            logger.info(
                f"{self.plugin_name}: 当前使用 Python 兼容版，已恢复配置项与扫描入口；"
                "自动换取 token 的闭源逻辑暂不可用，请先按文档抓取 secret 和 fnv_token。"
            )

    def run(self, task, **kwargs):
        if not self.is_active:
            return task

        savepath = str(task.get("savepath") or "").strip()
        if not savepath:
            return task

        target_path = self._build_target_path(savepath)
        if not target_path:
            return task

        library_id = self._get_library_id(target_path)
        if not library_id:
            logger.warning("%s: 未找到与路径匹配的媒体库 %s", self.plugin_name, target_path)
            return task

        if self._scan_library(library_id, target_path):
            logger.info("%s: 已触发飞牛影视刷新 %s", self.plugin_name, target_path)
            if self.remove_useless_wait >= 0:
                self._remove_useless()
        return task

    def _get_library_id(self, target_path: str) -> str | None:
        payload = self._request("GET", "/v/api/v1/mdb/list")
        libraries = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(libraries, list) or not libraries:
            return None

        if len(libraries) == 1:
            return self._extract_guid(libraries[0])

        best_guid = None
        best_score = -1
        for item in libraries:
            guid = self._extract_guid(item)
            if not guid:
                continue
            for path_value in self._extract_path_candidates(item):
                if target_path.startswith(path_value) and len(path_value) > best_score:
                    best_guid = guid
                    best_score = len(path_value)
        return best_guid

    def _scan_library(self, library_id: str, target_path: str) -> bool:
        payload = self._request(
            "POST",
            f"/v/api/v1/mdb/scan/{library_id}",
            data={"dir_list": [target_path]},
        )
        return bool(payload and payload.get("code") == 0)

    def _remove_useless(self) -> None:
        wait_time = self.remove_useless_wait
        for body in ({"wait_time": wait_time}, {"wait": wait_time}, {"seconds": wait_time}):
            payload = self._request("POST", "/v/api/v1/task/removeUseless", data=body, quiet=True)
            if payload and payload.get("code") == 0:
                logger.info("%s: 已清理缺失媒体等待任务", self.plugin_name)
                return

    def _request(
        self,
        method: str,
        rel_url: str,
        *,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        quiet: bool = False,
    ) -> dict[str, Any] | None:
        api_key, app_name = self._load_media_auth_meta()
        url = f"{self.endpoint.rstrip('/')}{rel_url}"
        headers = self._build_headers(method=method, rel_url=rel_url, params=params, data=data, api_key=api_key)
        try:
            response = self.session.request(
                method.upper(),
                url,
                headers=headers,
                params=params,
                data=self._serialize_data(data if data is not None else {}),
                timeout=5,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            if not quiet:
                logger.warning("%s: 请求失败 %s %s", self.plugin_name, rel_url, exc)
            return None

        if not isinstance(payload, dict):
            return None

        if payload.get("code") not in (0, None) and not quiet:
            logger.warning(
                "%s: 接口返回异常 %s %s",
                self.plugin_name,
                rel_url,
                payload.get("msg") or payload.get("message") or payload.get("code"),
            )
        self.api_key = api_key or self.api_key
        self.app_name = app_name or self.app_name
        return payload

    def _load_media_auth_meta(self) -> tuple[str, str]:
        api_key = self.api_key
        app_name = self.app_name

        if api_key:
            return api_key, app_name

        for rel_url in ("/v/api/v1/sys/config", "/v/api/v1/server/info"):
            payload = self._request_without_authx(rel_url)
            if not payload:
                continue
            api_key = api_key or self._find_first(payload, {"api_key", "apikey", "apiKey"})
            app_name = app_name or self._find_first(payload, {"app_name", "appname", "appName"})
            if api_key:
                break

        return str(api_key or ""), str(app_name or "trimemedia-web")

    def _request_without_authx(self, rel_url: str) -> dict[str, Any] | None:
        url = f"{self.endpoint.rstrip('/')}{rel_url}"
        headers = {
            "Content-Type": "application/json",
            **self._cookie_headers(),
        }
        if self.fnv_token:
            headers["Authorization"] = self.fnv_token
        try:
            response = self.session.get(url, headers=headers, timeout=5)
            response.raise_for_status()
            payload = response.json()
            return payload if isinstance(payload, dict) else None
        except Exception:
            return None

    def _build_headers(
        self,
        *,
        method: str,
        rel_url: str,
        params: dict[str, Any] | None,
        data: dict[str, Any] | None,
        api_key: str,
    ) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            **self._cookie_headers(),
        }
        if self.fnv_token:
            headers["Authorization"] = self.fnv_token
        if self.secret and api_key:
            headers["authx"] = self._cse_sign(method, rel_url, params=params, data=data, api_key=api_key)
        return headers

    def _cookie_headers(self) -> dict[str, str]:
        cookies: list[str] = []
        if self.token:
            cookies.append(f"fnos-token={self.token}")
        if self.long_token:
            cookies.append(f"fnos-long-token={self.long_token}")
        if self.fnv_token:
            cookies.append(f"Trim-MC-token={self.fnv_token}")
        return {"Cookie": "; ".join(cookies)} if cookies else {}

    def _build_target_path(self, savepath: str) -> str:
        savepath = self._normalize_path(savepath)
        mount_quark = self._normalize_path(self.mount_quark)
        if not savepath or not mount_quark:
            return ""
        if savepath.startswith(mount_quark):
            return savepath
        rel = savepath.lstrip("/")
        return self._normalize_path(posixpath.join(mount_quark, rel))

    def _extract_guid(self, item: Any) -> str | None:
        candidates = self._find_all(item, {"guid", "id", "mdb_guid"})
        for value in candidates:
            if value:
                return str(value)
        return None

    def _extract_path_candidates(self, item: Any) -> list[str]:
        raw = self._find_all(
            item,
            {
                "dir",
                "path",
                "root_dir",
                "root_path",
                "mount_path",
                "library_path",
                "media_path",
                "folder",
            },
        )
        values: list[str] = []
        for value in raw:
            if isinstance(value, str) and value.startswith("/"):
                values.append(self._normalize_path(value))
            elif isinstance(value, list):
                for sub in value:
                    if isinstance(sub, str) and sub.startswith("/"):
                        values.append(self._normalize_path(sub))
        return list(dict.fromkeys(values))

    def _cse_sign(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        api_key: str,
    ) -> str:
        nonce = str(random.randint(100000, 999999))
        timestamp = str(int(time.time() * 1000))
        serialized = urlencode(sorted(params.items())) if method.lower() == "get" and params else self._serialize_data(data)
        body_hash = self._md5(serialized)
        sign = self._md5("_".join([self.secret, path, nonce, timestamp, body_hash, api_key]))
        return f"nonce={nonce}&timestamp={timestamp}&sign={sign}"

    def _find_first(self, value: Any, keys: set[str]) -> str | None:
        matches = self._find_all(value, keys)
        for item in matches:
            if item:
                return str(item)
        return None

    def _find_all(self, value: Any, keys: set[str]) -> list[Any]:
        hits: list[Any] = []
        if isinstance(value, dict):
            for key, sub in value.items():
                if key in keys:
                    hits.append(sub)
                hits.extend(self._find_all(sub, keys))
        elif isinstance(value, list):
            for item in value:
                hits.extend(self._find_all(item, keys))
        return hits

    @staticmethod
    def _normalize_endpoint(endpoint: str) -> str:
        endpoint = str(endpoint or "").strip().rstrip("/")
        if not endpoint:
            return ""
        if "://" not in endpoint:
            endpoint = f"http://{endpoint}"
        return endpoint

    @staticmethod
    def _normalize_path(path: str) -> str:
        path = str(path or "").strip()
        if not path:
            return ""
        path = path.replace("\\", "/")
        if not path.startswith("/"):
            path = "/" + path
        normalized = posixpath.normpath(path)
        return "/" if normalized == "." else normalized

    @staticmethod
    def _as_int(value: Any, *, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _md5(value: str) -> str:
        return hashlib.md5(value.encode("utf-8")).hexdigest()

    @staticmethod
    def _serialize_data(data: Any) -> str:
        if isinstance(data, dict):
            return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        if isinstance(data, str):
            return data
        if not data:
            return ""
        return ""

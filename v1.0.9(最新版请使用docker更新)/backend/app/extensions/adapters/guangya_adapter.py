# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import logging
import re
import time
from hashlib import md5
from secrets import token_hex
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, unquote, urlparse

import requests

from app.extensions.adapters.base_adapter import BaseCloudDriveAdapter
from app.extensions.adapters.drive_auth import DriveAuthRequired

logger = logging.getLogger(__name__)


def generate_did() -> str:
    return md5(token_hex(16).encode("utf-8")).hexdigest()


def generate_traceparent() -> str:
    return f"00-{token_hex(16)}-{token_hex(8)}-01"


def _deep_get(payload: Any, *keys: str) -> Any:
    if not isinstance(payload, dict):
        return None
    for key in keys:
        if key in payload and payload.get(key) is not None:
            return payload.get(key)
    return None


def _extract_message(payload: Any, default: str = "") -> str:
    if isinstance(payload, dict):
        for key in ("message", "msg", "errorMessage", "error_message", "detail"):
            value = payload.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
    return default


def _extract_data(payload: Any) -> Any:
    if isinstance(payload, dict) and "data" in payload:
        return payload.get("data")
    return payload


def _extract_items(payload: Any) -> list[dict[str, Any]]:
    data = _extract_data(payload)
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if not isinstance(data, dict):
        return []
    for key in ("list", "items", "records", "rows", "fileList", "files"):
        value = data.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    for key in ("list", "items", "records", "rows"):
        value = payload.get(key) if isinstance(payload, dict) else None
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "folder", "dir", "directory"}


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _is_success(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return bool(payload)
    if payload.get("success") is True:
        return True
    if payload.get("ok") is True:
        return True
    for key in ("msg", "message"):
        value = payload.get(key)
        if str(value or "").strip().lower() == "success":
            return True
    for key in ("code", "status", "result"):
        if key not in payload:
            continue
        value = payload.get(key)
        if isinstance(value, (int, float)) and int(value) in (0, 200):
            return True
        if str(value).strip().lower() in {"0", "200", "ok", "success"}:
            return True
    if "data" in payload and payload.get("data") is not None and not _extract_message(payload):
        return True
    return False


def _has_explicit_failure(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    for key in ("code", "status", "result"):
        if key not in payload:
            continue
        value = payload.get(key)
        if isinstance(value, (int, float)):
            if int(value) not in (0, 200):
                return True
            continue
        text = str(value or "").strip().lower()
        if text and text not in {"0", "200", "ok", "success", "true"}:
            return True
    return False


def _payload_summary(payload: Any) -> str:
    if not isinstance(payload, dict):
        return str(type(payload).__name__)
    data = _extract_data(payload)
    data_keys = list(data.keys())[:8] if isinstance(data, dict) else []
    return (
        f"keys={list(payload.keys())[:8]} "
        f"data_type={type(data).__name__} "
        f"data_keys={data_keys} "
        f"message={_extract_message(payload)[:80]}"
    )


class GuangyaClientLite:
    API_USERRES = "https://api.guangyapan.com/nd.bizuserres.s/v1"
    API_USERRES_V2 = "https://api.guangyapan.com/userres/v1"
    API_CLOUD = "https://api.guangyapan.com/nd.bizcloudcollection.s/v1"
    API_ASSETS = "https://api.guangyapan.com/assets/v1"
    API_ACCOUNT = "https://account.guangyapan.com/v1"
    WEB_ORIGIN = "https://www.guangyapan.com"
    USER_AGENT = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/147.0.0.0 Safari/537.36"
    )
    CLIENT_ID = "aMe-8VSlkrbQXpUR"

    def __init__(
        self,
        *,
        access_token: str = "",
        refresh_token: str = "",
        device_id: str = "",
    ):
        self.token = _clean_text(access_token)
        self.refresh_token_value = _clean_text(refresh_token)
        self.token_expires_at: float | None = None
        self.device_id = _clean_text(device_id) or generate_did()
        self._session = requests.Session()
        self._session.headers.update(
            {
                "accept": "application/json, text/plain, */*",
                "content-type": "application/json",
                "did": self.device_id,
                "dt": "4",
                "origin": self.WEB_ORIGIN,
                "referer": f"{self.WEB_ORIGIN}/",
                "user-agent": self.USER_AGENT,
            }
        )
        self._update_auth_header()

    def _update_auth_header(self) -> None:
        if self.token:
            self._session.headers["authorization"] = f"Bearer {self.token}"
        else:
            self._session.headers.pop("authorization", None)

    def _account_headers(self, *, with_auth: bool = False) -> dict[str, str]:
        headers = {
            "accept": "*/*",
            "content-type": "application/json",
            "origin": self.WEB_ORIGIN,
            "referer": f"{self.WEB_ORIGIN}/",
            "user-agent": self.USER_AGENT,
            "x-client-id": self.CLIENT_ID,
            "x-client-version": "0.0.1",
            "x-device-id": self.device_id,
            "x-device-model": "chrome%2F147.0.0.0",
            "x-device-name": "PC-Chrome",
            "x-device-sign": f"wdi10.{self.device_id}{token_hex(16)}",
            "x-net-work-type": "NONE",
            "x-os-version": "MacIntel",
            "x-platform-version": "1",
            "x-protocol-version": "301",
            "x-provider-name": "NONE",
            "x-sdk-version": "9.0.2",
        }
        if with_auth and self.token:
            headers["authorization"] = f"Bearer {self.token}"
        return headers

    def _request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        retry_on_401: bool = True,
        timeout: int | float = 20,
        **kwargs,
    ) -> requests.Response:
        if self.refresh_token_value and self.token_expires_at and time.time() >= self.token_expires_at:
            self.refresh_token()
        merged_headers = {"traceparent": generate_traceparent()}
        if headers:
            merged_headers.update(headers)
        response = self._session.request(method=method, url=url, headers=merged_headers, timeout=timeout, **kwargs)
        if response.status_code == 401 and retry_on_401 and self.refresh_token_value:
            self.refresh_token()
            merged_headers["traceparent"] = generate_traceparent()
            response = self._session.request(method=method, url=url, headers=merged_headers, timeout=timeout, **kwargs)
        response.raise_for_status()
        return response

    def _request_json(self, method: str, url: str, **kwargs) -> dict[str, Any]:
        response = self._request(method, url, **kwargs)
        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError((response.text or "").strip()[:240] or "响应解析失败") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("响应格式异常")
        return payload

    def login_sms_init(self, phone_number: str, captcha_token: str | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {
            "client_id": self.CLIENT_ID,
            "action": "POST:/v1/auth/verification",
            "device_id": self.device_id,
            "meta": {"phone_number": phone_number},
        }
        if captcha_token:
            body["captcha_token"] = captcha_token
        response = requests.post(
            f"{self.API_ACCOUNT}/shield/captcha/init",
            headers=self._account_headers(),
            json=body,
            timeout=20,
        )
        response.raise_for_status()
        return response.json()

    def login_sms_send(self, phone_number: str, captcha_token: str, target: str = "ANY") -> dict[str, Any]:
        headers = self._account_headers()
        headers["x-captcha-token"] = captcha_token
        response = requests.post(
            f"{self.API_ACCOUNT}/auth/verification",
            headers=headers,
            json={"phone_number": phone_number, "target": target, "client_id": self.CLIENT_ID},
            timeout=20,
        )
        response.raise_for_status()
        return response.json()

    def login_sms_verify(self, verification_id: str, verification_code: str) -> dict[str, Any]:
        response = requests.post(
            f"{self.API_ACCOUNT}/auth/verification/verify",
            headers=self._account_headers(),
            json={
                "verification_id": verification_id,
                "verification_code": verification_code,
                "client_id": self.CLIENT_ID,
            },
            timeout=20,
        )
        response.raise_for_status()
        return response.json()

    def login_sms_signin(
        self,
        verification_code: str,
        verification_token: str,
        username: str,
        captcha_token: str,
    ) -> dict[str, Any]:
        headers = self._account_headers()
        headers["x-captcha-token"] = captcha_token
        response = requests.post(
            f"{self.API_ACCOUNT}/auth/signin",
            headers=headers,
            json={
                "verification_code": verification_code,
                "verification_token": verification_token,
                "username": username,
                "client_id": self.CLIENT_ID,
            },
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        access_token = _clean_text(payload.get("access_token"))
        if access_token:
            self.token = access_token
            self._update_auth_header()
            expires_in = payload.get("expires_in")
            self.token_expires_at = time.time() + float(expires_in) if expires_in else None
            self.refresh_token_value = _clean_text(payload.get("refresh_token") or self.refresh_token_value)
        return payload

    def refresh_token(self, refresh_token: str | None = None) -> dict[str, Any]:
        token = _clean_text(refresh_token or self.refresh_token_value)
        if not token:
            raise RuntimeError("无可用的 refresh_token")
        headers = self._account_headers()
        headers["x-action"] = "401"
        response = requests.post(
            f"{self.API_ACCOUNT}/auth/token",
            headers=headers,
            json={
                "client_id": self.CLIENT_ID,
                "grant_type": "refresh_token",
                "refresh_token": token,
            },
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        access_token = _clean_text(payload.get("access_token"))
        if access_token:
            self.token = access_token
            self._update_auth_header()
            expires_in = payload.get("expires_in")
            self.token_expires_at = time.time() + float(expires_in) if expires_in else None
            self.refresh_token_value = _clean_text(payload.get("refresh_token") or token)
        return payload

    def user_info(self) -> dict[str, Any]:
        response = requests.post(
            f"{self.API_ACCOUNT}/user/me",
            headers=self._account_headers(with_auth=True),
            timeout=20,
        )
        response.raise_for_status()
        return response.json()

    def fs_files(
        self,
        parent_id: str | int | None = None,
        *,
        page: int = 0,
        page_size: int = 50,
        order_by: int = 0,
        sort_type: int = 0,
    ) -> dict[str, Any]:
        data: dict[str, Any] = {
            "parentId": "" if parent_id in (None, "", "0", "/", "root") else parent_id,
            "page": page,
            "pageSize": page_size,
            "orderBy": order_by,
            "sortType": sort_type,
        }
        return self._request_json("POST", f"{self.API_USERRES_V2}/file/get_file_list", json=data)

    def fs_create_dir(self, dir_name: str, parent_id: str | int | None = None) -> dict[str, Any]:
        data = {"dirName": dir_name, "parentId": "" if parent_id in (None, "", "0", "/", "root") else parent_id}
        return self._request_json("POST", f"{self.API_USERRES}/file/create_dir", json=data)

    def fs_rename(self, file_id: str, new_name: str) -> dict[str, Any]:
        return self._request_json(
            "POST",
            f"{self.API_USERRES}/file/rename",
            json={"fileId": file_id, "newName": new_name},
        )

    def fs_delete(self, file_ids: list[str]) -> dict[str, Any]:
        return self._request_json("POST", f"{self.API_USERRES}/file/delete_file", json={"fileIds": file_ids})

    def fs_detail(self, file_id: str) -> dict[str, Any]:
        return self._request_json("POST", f"{self.API_USERRES}/file/get_file_detail", json={"fileId": file_id})

    def get_task_status(self, task_id: str) -> dict[str, Any]:
        return self._request_json("POST", f"{self.API_USERRES}/get_task_status", json={"taskId": task_id})

    def get_assets(self) -> dict[str, Any]:
        return self._request_json("POST", f"{self.API_ASSETS}/get_assets", json={})

    def share_restore(self, access_token: str, file_ids: list[str], parent_id: str | None = "") -> dict[str, Any]:
        return self._request_json(
            "POST",
            f"{self.API_USERRES}/restore_share",
            json={"accessToken": access_token, "fileIds": file_ids, "parentId": parent_id or ""},
        )

    @staticmethod
    def _public_headers() -> dict[str, str]:
        return {
            "accept": "application/json, text/plain, */*",
            "content-type": "application/json",
            "did": generate_did(),
            "dt": "4",
            "origin": GuangyaClientLite.WEB_ORIGIN,
            "referer": f"{GuangyaClientLite.WEB_ORIGIN}/",
            "traceparent": generate_traceparent(),
            "user-agent": GuangyaClientLite.USER_AGENT,
        }

    @staticmethod
    def _public_post(url: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = requests.post(url, headers=GuangyaClientLite._public_headers(), json=payload, timeout=20)
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict):
            raise RuntimeError("响应格式异常")
        return body

    @classmethod
    def share_summary(cls, share_id: str) -> dict[str, Any]:
        return cls._public_post(f"{cls.API_USERRES}/get_share_summary", {"shareId": share_id})

    @classmethod
    def share_access_token(cls, share_id: str, code: str) -> dict[str, Any]:
        return cls._public_post(f"{cls.API_USERRES}/get_share_access_token", {"shareId": share_id, "code": code})

    @classmethod
    def share_files_list(
        cls,
        access_token: str,
        *,
        parent_id: str = "",
        page: int = 1,
        page_size: int = 50,
        order_by: int = 0,
        sort_type: int = 0,
    ) -> dict[str, Any]:
        return cls._public_post(
            f"{cls.API_USERRES}/get_share_page_files_list",
            {
                "accessToken": access_token,
                "parentId": parent_id,
                "page": page,
                "pageSize": page_size,
                "orderBy": order_by,
                "sortType": sort_type,
            },
        )


class GuangyaAdapter(BaseCloudDriveAdapter):
    DRIVE_TYPE = "guangya"
    DRIVE_NAME = "光鸭云盘"
    CONFIG_FORMAT = "kv"
    default_config = {
        "phone_number": "",
        "access_token": "",
        "refresh_token": "",
        "device_id": "",
    }
    config_fields = [
        {
            "key": "phone_number",
            "label": "手机号",
            "description": "用于短信登录，格式如 +86 13800138000。",
            "input_type": "text",
            "required": False,
            "secret": False,
            "placeholder": "+86 13800138000",
        },
        {
            "key": "access_token",
            "label": "Access Token",
            "description": "已有登录态时可直接填写；若过期会尝试结合 refresh_token 自动刷新。",
            "input_type": "textarea",
            "required": False,
            "secret": True,
            "placeholder": "access_token",
        },
        {
            "key": "refresh_token",
            "label": "Refresh Token",
            "description": "建议与 access_token 一起填写；短信登录成功后也会自动更新。",
            "input_type": "textarea",
            "required": False,
            "secret": True,
            "placeholder": "refresh_token",
        },
        {
            "key": "device_id",
            "label": "Device ID",
            "description": "可选；不填则自动生成并持久化。",
            "input_type": "text",
            "required": False,
            "secret": False,
            "placeholder": "自动生成",
        },
    ]

    def __init__(
        self,
        cookie: str = "",
        index: int = 0,
        config: dict | None = None,
        account_name: str = "",
        no_login: bool = False,
    ):
        super().__init__(cookie, index, config=config, no_login=no_login)
        self._account_name = _clean_text(account_name) or f"光鸭用户{self.index}"
        self._auth_state: dict[str, Any] | None = None
        self._client = GuangyaClientLite(
            access_token=_clean_text(self.config.get("access_token")),
            refresh_token=_clean_text(self.config.get("refresh_token")),
            device_id=_clean_text(self.config.get("device_id")),
        )
        self.config["device_id"] = self._client.device_id
        self.cookie = self.serialize_config(self.config)

    def _sync_runtime_config(self) -> None:
        self.config["access_token"] = self._client.token
        self.config["refresh_token"] = self._client.refresh_token_value
        self.config["device_id"] = self._client.device_id
        self.cookie = self.serialize_config(self.config)

    def export_runtime_config(self) -> dict[str, Any]:
        self._sync_runtime_config()
        return dict(self.config)

    def _mask_mobile(self, mobile: str) -> str:
        digits = re.sub(r"\D+", "", mobile or "")
        if len(digits) < 7:
            return mobile
        return f"{digits[:3]}****{digits[-4:]}"

    def _normalize_root_parent_id(self, fid: str | None) -> str | None:
        if _clean_text(fid) in {"", "0", "/", "root"}:
            return None
        return _clean_text(fid)

    def _normalize_output_fid(self, fid: Any) -> str:
        value = _clean_text(fid)
        return value or "0"

    def _pick_item_id(self, item: dict[str, Any]) -> str:
        return self._normalize_output_fid(
            _deep_get(item, "fid", "fileId", "id", "resId")
            or _deep_get(_extract_data(item), "fid", "fileId", "id", "resId")
        )

    def _pick_parent_id(self, item: dict[str, Any]) -> str:
        return self._normalize_output_fid(
            _deep_get(item, "parentId", "pdir_fid", "parent_id")
            or _deep_get(_extract_data(item), "parentId", "pdir_fid", "parent_id")
        )

    def _pick_name(self, item: dict[str, Any]) -> str:
        value = _deep_get(item, "file_name", "fileName", "name", "title")
        if value is None:
            value = _deep_get(_extract_data(item), "file_name", "fileName", "name", "title")
        return _clean_text(value)

    def _pick_size(self, item: dict[str, Any]) -> int:
        value = _deep_get(item, "size", "fileSize", "file_size")
        if value is None:
            value = _deep_get(_extract_data(item), "size", "fileSize", "file_size")
        return _to_int(value, 0)

    def _pick_updated_at(self, item: dict[str, Any]) -> int:
        value = _deep_get(item, "updated_at", "updateTime", "updatedAt", "lastOpTime", "utime", "mtime", "createTime", "createdAt", "ctime")
        if value is None:
            value = _deep_get(_extract_data(item), "updated_at", "updateTime", "updatedAt", "lastOpTime", "utime", "mtime", "createTime", "createdAt", "ctime")
        if value is None:
            return 0
        if isinstance(value, (int, float)):
            return int(value)
        text = _clean_text(value)
        if text.isdigit():
            return int(text)
        return 0

    def _pick_is_dir(self, item: dict[str, Any]) -> bool:
        candidates = [
            _deep_get(item, "dir", "isDir", "isFolder", "folder"),
            _deep_get(_extract_data(item), "dir", "isDir", "isFolder", "folder"),
        ]
        for value in candidates:
            if value is not None:
                return _to_bool(value)
        file_type = _deep_get(item, "fileType", "type")
        if file_type is None:
            file_type = _deep_get(_extract_data(item), "fileType", "type")
        if str(file_type).strip().lower() in {"0", "dir", "folder", "directory"}:
            return True
        res_type = _deep_get(item, "resType")
        if res_type is None:
            res_type = _deep_get(_extract_data(item), "resType")
        return str(res_type).strip().lower() in {"2", "dir", "folder", "directory"}

    def _extract_access_token(self, payload: Any) -> str:
        data = _extract_data(payload)
        if isinstance(data, str):
            return _clean_text(data)
        if isinstance(data, dict):
            token = _deep_get(data, "access_token", "accessToken", "token")
            if token:
                return _clean_text(token)
        if isinstance(payload, str):
            return _clean_text(payload)
        if isinstance(payload, dict):
            token = _deep_get(payload, "access_token", "accessToken", "token")
            if token:
                return _clean_text(token)
        return ""

    def _extract_task_id(self, payload: Any) -> str:
        data = _extract_data(payload)
        if isinstance(data, dict):
            value = _deep_get(data, "taskId", "task_id", "id")
            if value:
                return _clean_text(value)
        if isinstance(payload, dict):
            value = _deep_get(payload, "taskId", "task_id", "id")
            if value:
                return _clean_text(value)
        return ""

    def _raise_if_failed(self, payload: dict[str, Any], default_message: str) -> None:
        if _is_success(payload):
            return
        raise RuntimeError(_extract_message(payload, default_message))

    def _list_fs_items(self, parent_id: str | None, *, max_items: int = 0) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        page = 0
        page_size = 50
        while True:
            payload = self._client.fs_files(parent_id=parent_id, page=page, page_size=page_size)
            if not _is_success(payload):
                raise RuntimeError(_extract_message(payload, "获取目录列表失败"))
            batch = _extract_items(payload)
            if not batch:
                break
            items.extend(batch)
            if max_items > 0 and len(items) >= max_items:
                return items[:max_items]
            if len(batch) < page_size:
                break
            page += 1
            if page > 200:
                break
        return items

    def _list_share_items(self, access_token: str, parent_id: str = "") -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        page = 1
        page_size = 50
        while True:
            payload = self._client.share_files_list(access_token, parent_id=parent_id, page=page, page_size=page_size)
            if not _is_success(payload):
                raise RuntimeError(_extract_message(payload, "获取分享文件列表失败"))
            batch = _extract_items(payload)
            if not batch:
                break
            items.extend(batch)
            if len(batch) < page_size:
                break
            page += 1
            if page > 200:
                break
        return items

    def _ensure_login(self) -> None:
        if self.is_active and self._client.token:
            return
        info = self.init()
        if not info:
            raise RuntimeError("未登录或 Token 无效")

    def _try_user_info(self) -> dict[str, Any] | None:
        try:
            payload = self._client.user_info()
        except Exception as exc:
            logger.info("[guangya] user_info failed: %s", exc)
            return None
        if not _is_success(payload):
            return None
        data = _extract_data(payload)
        return data if isinstance(data, dict) else payload

    def _refresh_and_get_user_info(self) -> dict[str, Any] | None:
        if not self._client.refresh_token_value:
            return None
        try:
            refresh_payload = self._client.refresh_token()
            if not _is_success(refresh_payload) and not self._client.token:
                return None
        except Exception as exc:
            logger.info("[guangya] refresh_token failed: %s", exc)
            return None
        return self._try_user_info()

    def _validate_token_via_fs(self) -> bool:
        """`user_info` 当前可能不可用，回退到个人盘列表接口做轻量探活。"""
        if not self._client.token:
            return False
        try:
            payload = self._client.fs_files(parent_id=None, page=0, page_size=1)
        except Exception as exc:
            logger.info("[guangya] fs_files validation failed: %s", exc)
            return False
        if _is_success(payload):
            return True
        if _has_explicit_failure(payload):
            logger.info("[guangya] fs_files validation explicit failure: %s", _payload_summary(payload))
            return False
        data = _extract_data(payload)
        if isinstance(data, dict):
            if _extract_items(payload):
                return True
            if any(key in data for key in ("list", "items", "records", "rows", "fileList", "files", "page", "pageSize", "total", "hasMore")):
                return True
        if isinstance(data, list):
            return True
        logger.info("[guangya] fs_files validation unknown payload: %s", _payload_summary(payload))
        return False

    def init(self) -> Any:
        # 匿名分享模式下不要探测用户态接口，避免公开预览场景被账号态失败干扰。
        if self.no_login:
            return False
        info = self._try_user_info()
        if info is None:
            info = self._refresh_and_get_user_info()
        if info:
            self.is_active = True
            self.nickname = _clean_text(_deep_get(info, "nickname", "nickName", "username", "phoneNumber")) or self._account_name
            self._sync_runtime_config()
            return info
        if self._validate_token_via_fs():
            self.is_active = True
            self.nickname = _clean_text(self.config.get("phone_number")) or self._account_name
            self._sync_runtime_config()
            return {"nickname": self.nickname, "phoneNumber": _clean_text(self.config.get("phone_number"))}
        phone_number = _clean_text(self.config.get("phone_number"))
        if not phone_number:
            return False
        init_result = self._client.login_sms_init(phone_number)
        captcha_token = _clean_text(_deep_get(init_result, "captcha_token", "captchaToken"))
        if not captcha_token:
            challenge_url = _clean_text(_deep_get(init_result, "url", "captcha_url"))
            detail = "需要先完成人机验证" + (f": {challenge_url}" if challenge_url else "")
            raise RuntimeError(detail)
        self._auth_state = {
            "method": "sms",
            "phone_number": phone_number,
            "captcha_token": captcha_token,
            "target": "ANY",
        }
        raise DriveAuthRequired(
            method="sms",
            message="光鸭云盘登录需要短信验证",
            payload={
                "mobile": self._mask_mobile(phone_number),
                "show_name": self._account_name,
            },
            adapter=self,
        )

    def send_sms(self) -> Dict[str, Any]:
        if not self._auth_state or self._auth_state.get("method") != "sms":
            raise RuntimeError("短信会话已失效，请重新检测账号")
        phone_number = _clean_text(self._auth_state.get("phone_number"))
        captcha_token = _clean_text(self._auth_state.get("captcha_token"))
        if not phone_number or not captcha_token:
            raise RuntimeError("短信会话缺少必要参数，请重新检测账号")
        payload = self._client.login_sms_send(phone_number, captcha_token, target=_clean_text(self._auth_state.get("target")) or "ANY")
        verification_id = _clean_text(_deep_get(payload, "verification_id", "verificationId"))
        if not verification_id:
            raise RuntimeError(_extract_message(payload, "发送短信验证码失败"))
        self._auth_state["verification_id"] = verification_id
        return payload

    def submit_sms(self, sms_code: str) -> Any:
        if not self._auth_state or self._auth_state.get("method") != "sms":
            raise RuntimeError("短信会话已失效，请重新检测账号")
        phone_number = _clean_text(self._auth_state.get("phone_number"))
        captcha_token = _clean_text(self._auth_state.get("captcha_token"))
        verification_id = _clean_text(self._auth_state.get("verification_id"))
        if not phone_number or not captcha_token or not verification_id:
            raise RuntimeError("短信会话不完整，请重新发送验证码")
        verify_payload = self._client.login_sms_verify(verification_id, _clean_text(sms_code))
        verification_token = _clean_text(_deep_get(verify_payload, "verification_token", "verificationToken"))
        if not verification_token:
            raise RuntimeError(_extract_message(verify_payload, "短信验证码校验失败"))
        signin_payload = self._client.login_sms_signin(_clean_text(sms_code), verification_token, phone_number, captcha_token)
        access_token = _clean_text(signin_payload.get("access_token"))
        if not access_token:
            raise RuntimeError(_extract_message(signin_payload, "光鸭云盘登录失败"))
        self._sync_runtime_config()
        info = self._try_user_info() or {"nickname": self._account_name, "phoneNumber": phone_number}
        self.is_active = True
        self.nickname = _clean_text(_deep_get(info, "nickname", "nickName", "username", "phoneNumber")) or self._account_name
        self._auth_state = None
        return info

    def get_account_info(self) -> Any:
        self._ensure_login()
        return self._try_user_info() or {"phoneNumber": _clean_text(self.config.get("phone_number"))}

    def get_account_config(self) -> Dict[str, Any]:
        self._ensure_login()
        info = self._try_user_info() or {"phoneNumber": _clean_text(self.config.get("phone_number"))}
        assets_payload: dict[str, Any] = {}
        assets_data: dict[str, Any] = {}
        try:
            assets_payload = self._client.get_assets()
            data = _extract_data(assets_payload)
            if isinstance(data, dict):
                assets_data = data
        except Exception as exc:
            logger.info("[guangya] get_assets failed: %s", exc)

        nickname = _clean_text(_deep_get(info, "nickname", "nickName", "username", "phoneNumber")) or self.nickname or self._account_name
        self.nickname = nickname
        username = _clean_text(_deep_get(info, "username", "phoneNumber", "phone", "mobile")) or _clean_text(self.config.get("phone_number")) or nickname
        used_space = None
        total_space = None
        try:
            if assets_data.get("usedSpaceSize") is not None:
                used_space = int(assets_data.get("usedSpaceSize") or 0)
        except Exception:
            used_space = None
        try:
            if assets_data.get("totalSpaceSize") is not None:
                total_space = int(assets_data.get("totalSpaceSize") or 0)
        except Exception:
            total_space = None

        member_type = ""
        if _to_int(assets_data.get("svipStatus"), 0) > 0:
            member_type = "SVIP"
        elif _to_int(assets_data.get("vipStatus"), 0) > 0:
            member_type = "VIP"

        member_status = {
            "vip_status": _to_int(assets_data.get("vipStatus"), 0),
            "svip_status": _to_int(assets_data.get("svipStatus"), 0),
            "vip_left_time": assets_data.get("vipLeftTime"),
            "vip_expire_time": assets_data.get("vipExpireTime"),
            "system_time": assets_data.get("systemTime"),
        }
        return {
            "drive_type": self.DRIVE_TYPE,
            "drive_name": self.DRIVE_NAME,
            "nickname": nickname,
            "username": username,
            "used_space": used_space,
            "total_space": total_space,
            "member_type": member_type,
            "member_status": member_status,
            "raw": {
                "account_info": info or None,
                "assets_info": assets_data or assets_payload or None,
            },
        }

    def extract_url(self, url: str) -> Tuple[Optional[str], str, Any, List]:
        raw = _clean_text(url)
        if not raw:
            return None, "", "0", []
        normalized = unquote(raw.replace("？", "?").replace("＆", "&"))
        compact = re.sub(r"\s+", "", normalized)

        passcode = ""
        for pat in (
            r"[（(]提取码[：:]\s*([a-zA-Z0-9]{4,8})[)）]",
            r"[（(]访问码[：:]\s*([a-zA-Z0-9]{4,8})[)）]",
            r"提取码[：:]\s*([a-zA-Z0-9]{4,8})",
            r"访问码[：:]\s*([a-zA-Z0-9]{4,8})",
        ):
            match = re.search(pat, compact, re.IGNORECASE)
            if not match:
                continue
            passcode = _clean_text(match.group(1))
            compact = compact.replace(match.group(0), "", 1)
            break

        extracted_url = ""
        match = re.search(r"(https?://[^\s]*guangyapan\.com[^\s]*)", compact, re.IGNORECASE)
        if match:
            extracted_url = match.group(1)
        elif "guangyapan.com" in compact.lower():
            extracted_url = compact if compact.startswith("http") else f"https://{compact.lstrip('/')}"
        else:
            extracted_url = raw

        parsed = urlparse(extracted_url)
        query = parse_qs(parsed.query or "")
        if not passcode:
            for key in ("pwd", "code", "passcode", "accessCode"):
                value = query.get(key) or []
                if value and _clean_text(value[0]):
                    passcode = _clean_text(value[0])
                    break

        share_id = ""
        for key in ("shareId", "share_id", "id", "sid"):
            value = query.get(key) or []
            if value and _clean_text(value[0]):
                share_id = _clean_text(value[0])
                break
        if not share_id:
            path = parsed.path or ""
            patterns = (
                r"/share/([A-Za-z0-9_-]+)",
                r"/s/([A-Za-z0-9_-]+)",
                r"/link/([A-Za-z0-9_-]+)",
                r"/download/([A-Za-z0-9_-]+)",
            )
            for pat in patterns:
                match = re.search(pat, path, re.IGNORECASE)
                if match:
                    share_id = _clean_text(match.group(1))
                    break

        pdir_fid = "0"
        for key in ("parentId", "parent_id", "pdir_fid", "fid", "fileId"):
            value = query.get(key) or []
            if value and _clean_text(value[0]):
                pdir_fid = self._normalize_output_fid(value[0])
                break
        if pdir_fid == "0":
            fragment = _clean_text(parsed.fragment)
            fragment_query = parse_qs(urlparse(fragment).query or "")
            for key in ("parentId", "parent_id", "pdir_fid", "fid", "fileId"):
                value = fragment_query.get(key) or []
                if value and _clean_text(value[0]):
                    pdir_fid = self._normalize_output_fid(value[0])
                    break
        if pdir_fid == "0":
            fragment = _clean_text(parsed.fragment)
            for pat in (r"(?:^|/)list/share/([A-Za-z0-9_-]+)", r"(?:^|/)share/([A-Za-z0-9_-]+)"):
                match = re.search(pat, fragment, re.IGNORECASE)
                if match:
                    pdir_fid = self._normalize_output_fid(match.group(1))
                    break

        return (share_id or None), passcode, pdir_fid, []

    def get_stoken(self, pwd_id: str, passcode: str = "") -> Dict:
        if not pwd_id:
            return {"status": 400, "message": "分享链接无效", "data": {}}
        summary_payload = self._client.share_summary(pwd_id)
        if not _is_success(summary_payload):
            return {"status": 404, "message": _extract_message(summary_payload, "分享不存在或已失效"), "data": {}}
        access_payload = self._client.share_access_token(pwd_id, passcode or "")
        access_token = self._extract_access_token(access_payload)
        if not access_token:
            message = _extract_message(access_payload, "提取码错误或分享不可访问")
            return {"status": 403 if passcode else 400, "message": message, "data": {}}
        stoken = json.dumps({"share_id": pwd_id, "access_token": access_token, "code": passcode or ""}, ensure_ascii=False)
        return {"status": 200, "message": "success", "data": {"stoken": stoken}}

    def _parse_stoken(self, stoken: str, pwd_id: str, passcode: str = "") -> dict[str, Any]:
        try:
            payload = json.loads(stoken) if stoken else {}
        except json.JSONDecodeError:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        access_token = _clean_text(payload.get("access_token"))
        if not access_token:
            token_payload = self.get_stoken(pwd_id, passcode)
            stoken_text = _clean_text(_deep_get((token_payload or {}).get("data") or {}, "stoken"))
            if stoken_text:
                try:
                    nested = json.loads(stoken_text)
                except json.JSONDecodeError:
                    nested = {}
                if isinstance(nested, dict):
                    payload.update({k: v for k, v in nested.items() if v is not None})
                    access_token = _clean_text(payload.get("access_token"))
        return payload

    def get_detail(
        self,
        pwd_id: str,
        stoken: str,
        pdir_fid: str,
        _fetch_share: int = 0,
        fetch_share_full_path: int = 0,
    ) -> Dict:
        if not pwd_id:
            return {"code": 1, "message": "分享链接无效", "data": {"list": []}}
        token_payload = self._parse_stoken(stoken, pwd_id)
        access_token = _clean_text(token_payload.get("access_token"))
        if not access_token:
            return {"code": 1, "message": "分享访问令牌获取失败", "data": {"list": []}}
        parent_id = "" if _clean_text(pdir_fid) in {"", "0", "/", "root"} else _clean_text(pdir_fid)
        try:
            raw_items = self._list_share_items(access_token, parent_id=parent_id)
        except Exception as exc:
            return {"code": 1, "message": str(exc), "data": {"list": []}}
        data_list: list[dict[str, Any]] = []
        for item in raw_items:
            fid = self._pick_item_id(item)
            name = self._pick_name(item)
            is_dir = self._pick_is_dir(item)
            pid = self._pick_parent_id(item)
            data_list.append(
                {
                    "fid": fid,
                    "file_name": name,
                    "dir": is_dir,
                    "size": self._pick_size(item),
                    "updated_at": self._pick_updated_at(item),
                    "share_fid_token": json.dumps(
                        {
                            "pid": pid,
                            "dir": 1 if is_dir else 0,
                            "name": name,
                        },
                        ensure_ascii=False,
                    ),
                }
            )
        data: dict[str, Any] = {"list": data_list, "full_path": []}
        if parent_id:
            data["resolved_pdir_fid"] = self._normalize_output_fid(parent_id)
        return {"code": 0, "message": "success", "data": data}

    def ls_dir(self, pdir_fid: str, max_items: int = 0, **kwargs) -> Dict:
        try:
            self._ensure_login()
            raw_items = self._list_fs_items(self._normalize_root_parent_id(pdir_fid), max_items=max_items)
            items = [
                {
                    "fid": self._pick_item_id(item),
                    "file_name": self._pick_name(item),
                    "dir": self._pick_is_dir(item),
                    "size": self._pick_size(item),
                    "updated_at": self._pick_updated_at(item),
                    "share_fid_token": "",
                }
                for item in raw_items
            ]
            return {"code": 0, "message": "success", "data": {"list": items}}
        except Exception as exc:
            return {"code": 1, "message": str(exc), "data": {"list": []}}

    def _find_child_folder(self, parent_id: str | None, folder_name: str) -> dict[str, Any] | None:
        for item in self._list_fs_items(parent_id):
            if not self._pick_is_dir(item):
                continue
            if self._pick_name(item) == folder_name:
                return item
        return None

    def mkdir(self, dir_path: str) -> Dict:
        if not _clean_text(dir_path):
            return {"code": 1, "message": "目录不能为空", "data": {}}
        try:
            self._ensure_login()
            normalized = re.sub(r"/{2,}", "/", f"/{_clean_text(dir_path)}")
            if normalized == "/":
                return {"code": 0, "message": "success", "data": {"fid": "0"}}
            parts = [part for part in normalized.split("/") if part]
            parent_id: str | None = None
            for part in parts:
                existing = self._find_child_folder(parent_id, part)
                if existing is not None:
                    parent_id = self._pick_item_id(existing)
                    continue
                payload = self._client.fs_create_dir(part, parent_id=parent_id)
                self._raise_if_failed(payload, "创建目录失败")
                new_id = self._extract_task_id(payload)
                if not new_id:
                    existing = self._find_child_folder(parent_id, part)
                    if existing is None:
                        raise RuntimeError("创建目录后未找到目标目录")
                    new_id = self._pick_item_id(existing)
                parent_id = new_id
            return {"code": 0, "message": "success", "data": {"fid": self._normalize_output_fid(parent_id)}}
        except Exception as exc:
            return {"code": 1, "message": str(exc), "data": {}}

    def rename(self, fid: str, file_name: str) -> Dict:
        try:
            self._ensure_login()
            payload = self._client.fs_rename(_clean_text(fid), _clean_text(file_name))
            self._raise_if_failed(payload, "重命名失败")
            return {"code": 0, "message": "success", "data": {}}
        except Exception as exc:
            return {"code": 1, "message": str(exc), "data": {}}

    def delete(self, filelist: List[str]) -> Dict:
        try:
            self._ensure_login()
            if not filelist:
                return {"code": 0, "message": "success", "data": {}}
            payload = self._client.fs_delete([_clean_text(fid) for fid in filelist if _clean_text(fid)])
            self._raise_if_failed(payload, "删除失败")
            return {"code": 0, "message": "success", "data": {}}
        except Exception as exc:
            return {"code": 1, "message": str(exc), "data": {}}

    def get_fids(self, file_paths: List[str]) -> List[Dict]:
        try:
            self._ensure_login()
        except Exception:
            return []
        results: list[dict[str, str]] = []
        for path in file_paths:
            normalized = re.sub(r"/{2,}", "/", f"/{_clean_text(path)}")
            if normalized == "/":
                results.append({"file_path": "/", "fid": "0"})
                continue
            parent_id: str | None = None
            ok = True
            for part in [item for item in normalized.split("/") if item]:
                child = self._find_child_folder(parent_id, part)
                if child is None:
                    ok = False
                    break
                parent_id = self._pick_item_id(child)
            if ok and parent_id:
                results.append({"file_path": normalized, "fid": parent_id})
        return results

    def _diff_dest_dir(self, dest_fid: str, before_fids: set[str], file_names: list[str]) -> list[str]:
        dest_payload = self.ls_dir(dest_fid, max_items=1000)
        if dest_payload.get("code") != 0:
            return []
        items = (dest_payload.get("data") or {}).get("list") or []
        name_to_fids: dict[str, list[str]] = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            fid = _clean_text(item.get("fid"))
            name = _clean_text(item.get("file_name"))
            if not fid or fid in before_fids or not name:
                continue
            name_to_fids.setdefault(name, []).append(fid)
        aligned: list[str] = []
        used: set[str] = set()
        for name in file_names:
            target = ""
            for fid in name_to_fids.get(name, []):
                if fid not in used:
                    target = fid
                    break
            if target:
                used.add(target)
            aligned.append(target)
        return aligned

    def _task_is_done(self, payload: dict[str, Any]) -> bool:
        status = _deep_get(_extract_data(payload), "status", "taskStatus", "state") or _deep_get(payload, "status", "taskStatus", "state")
        status_text = str(status or "").strip().lower()
        if status_text in {"2", "3", "4", "done", "success", "completed", "finish", "finished"}:
            return True
        message = _extract_message(payload).lower()
        return any(token in message for token in ("完成", "成功", "finished", "success"))

    def _task_is_failed(self, payload: dict[str, Any]) -> bool:
        status = _deep_get(_extract_data(payload), "status", "taskStatus", "state") or _deep_get(payload, "status", "taskStatus", "state")
        status_text = str(status or "").strip().lower()
        if status_text in {"5", "-1", "failed", "error"}:
            return True
        message = _extract_message(payload).lower()
        return any(token in message for token in ("失败", "error", "failed"))

    def save_file(
        self,
        fid_list: List[str],
        fid_token_list: List[str],
        to_pdir_fid: str,
        pwd_id: str,
        stoken: str,
        file_names: List[str] | None = None,
    ) -> Dict:
        try:
            self._ensure_login()
            cleaned_fids = [_clean_text(fid) for fid in fid_list if _clean_text(fid)]
            if not cleaned_fids:
                return {
                    "code": 0,
                    "message": "success",
                    "data": {"task_id": f"guangya_sync_{int(time.time())}", "save_as_top_fids": [], "_sync": True},
                }
            token_payload = self._parse_stoken(stoken, pwd_id)
            access_token = _clean_text(token_payload.get("access_token"))
            if not access_token:
                return {"code": 1, "message": "分享访问令牌获取失败", "data": {}}
            dest_fid = self._normalize_output_fid(to_pdir_fid)
            before_fids: set[str] = set()
            if file_names:
                before_payload = self.ls_dir(dest_fid, max_items=1000)
                if before_payload.get("code") == 0:
                    for item in ((before_payload.get("data") or {}).get("list") or []):
                        if isinstance(item, dict) and _clean_text(item.get("fid")):
                            before_fids.add(_clean_text(item.get("fid")))
            payload = self._client.share_restore(access_token, cleaned_fids, parent_id="" if dest_fid == "0" else dest_fid)
            self._raise_if_failed(payload, "转存失败")
            task_id = self._extract_task_id(payload)
            if task_id:
                for _ in range(20):
                    status_payload = self._client.get_task_status(task_id)
                    if self._task_is_failed(status_payload):
                        raise RuntimeError(_extract_message(status_payload, "转存任务失败"))
                    if self._task_is_done(status_payload):
                        break
                    time.sleep(1)
            aligned: list[str] = []
            if file_names:
                for _ in range(15):
                    aligned = self._diff_dest_dir(dest_fid, before_fids, file_names)
                    if aligned and any(aligned):
                        break
                    time.sleep(1)
            return {
                "code": 0,
                "message": "success",
                "data": {
                    "task_id": task_id or f"guangya_sync_{int(time.time())}",
                    "save_as_top_fids": aligned,
                    "_sync": True,
                },
            }
        except Exception as exc:
            return {"code": 1, "message": str(exc), "data": {}}

    def query_task(self, task_id: str) -> Dict:
        try:
            if not _clean_text(task_id) or _clean_text(task_id).startswith("guangya_sync_"):
                return {"code": 0, "message": "ok", "data": {"status": 2, "save_as": {"save_as_top_fids": []}}}
            self._ensure_login()
            payload = self._client.get_task_status(_clean_text(task_id))
            if self._task_is_failed(payload):
                return {"code": 1, "message": _extract_message(payload, "转存任务失败"), "data": {"save_as": {"save_as_top_fids": []}}}
            status = 2 if self._task_is_done(payload) else 1
            return {"code": 0, "message": "ok", "data": {"status": status, "save_as": {"save_as_top_fids": []}}}
        except Exception as exc:
            return {"code": 1, "message": str(exc), "data": {"save_as": {"save_as_top_fids": []}}}

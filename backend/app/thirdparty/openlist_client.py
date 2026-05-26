from __future__ import annotations

import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Callable, Iterable, Literal, Mapping
import requests


@dataclass(slots=True)
class OpenListError(Exception):
    message: str
    http_status: int | None = None
    api_code: int | str | None = None
    api_message: str | None = None
    payload: Any | None = None

    def __str__(self) -> str:
        parts: list[str] = []
        if self.http_status is not None:
            parts.append(f"http_status={self.http_status}")
        if self.api_code is not None:
            parts.append(f"api_code={self.api_code}")
        if self.api_message:
            parts.append(f"api_message={self.api_message}")
        parts.append(self.message)
        return " | ".join(parts)


class OpenListClient:
    def __init__(
        self,
        base_url: str,
        *,
        token: str | None = None,
        timeout_seconds: float = 10.0,
        max_retries: int = 3,
        backoff_seconds: float = 0.5,
        verify: bool = True,
        session: requests.Session | None = None,
    ):
        self.base_url = str(base_url or "").rstrip("/")
        self.token = (token or "").strip()
        self.timeout_seconds = float(timeout_seconds)
        self.max_retries = int(max_retries)
        self.backoff_seconds = float(backoff_seconds)
        self.verify = bool(verify)

        self.session = session or requests.Session()

    def set_token(self, token: str | None) -> None:
        self.token = (token or "").strip()

    def _url(self, endpoint: str) -> str:
        endpoint = "/" + str(endpoint or "").lstrip("/")
        return f"{self.base_url}{endpoint}"

    def _headers(self, extra: Mapping[str, str] | None = None) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self.token:
            headers["Authorization"] = self.token
        if extra:
            headers.update({str(k): str(v) for k, v in extra.items()})
        return headers

    def _sleep(self, attempt: int) -> None:
        sleep_s = self.backoff_seconds * (2**attempt)
        sleep_s = sleep_s + random.random() * max(0.0, sleep_s / 5)
        time.sleep(sleep_s)

    def request(
        self,
        method: str,
        endpoint: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any | None = None,
        data: Any | None = None,
        headers: Mapping[str, str] | None = None,
        timeout_seconds: float | None = None,
        allow_retry: bool = True,
        ensure_success: bool = False,
    ) -> Any:
        url = self._url(endpoint)
        last_exc: Exception | None = None
        retries = self.max_retries if allow_retry else 0
        timeout = float(timeout_seconds) if timeout_seconds is not None else self.timeout_seconds

        for attempt in range(retries + 1):
            try:
                resp = self.session.request(
                    method=str(method or "GET").upper(),
                    url=url,
                    params=dict(params) if params else None,
                    json=json,
                    data=data,
                    headers=self._headers(headers),
                    timeout=timeout,
                    verify=self.verify,
                )
                if resp.status_code in (429, 500, 502, 503, 504):
                    raise requests.exceptions.HTTPError(f"status={resp.status_code}", response=resp)
                resp.raise_for_status()

                content_type = resp.headers.get("Content-Type", "")
                if "application/json" in content_type or resp.text.startswith("{") or resp.text.startswith("["):
                    payload = resp.json()
                    if ensure_success:
                        self._ensure_api_success(payload, http_status=resp.status_code)
                    return payload
                return resp.content
            except Exception as e:
                last_exc = e
                if attempt >= retries:
                    break
                self._sleep(attempt)

        if isinstance(last_exc, requests.exceptions.HTTPError) and getattr(last_exc, "response", None) is not None:
            r = last_exc.response
            raise OpenListError(
                "OpenList request failed",
                http_status=getattr(r, "status_code", None),
                payload=(r.text[:500] if getattr(r, "text", None) else None),
            ) from last_exc
        raise OpenListError("OpenList request failed") from last_exc

    def request_json(
        self,
        method: str,
        endpoint: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any | None = None,
        headers: Mapping[str, str] | None = None,
        timeout_seconds: float | None = None,
        allow_retry: bool = True,
        ensure_success: bool = True,
    ) -> dict[str, Any]:
        payload = self.request(
            method,
            endpoint,
            params=params,
            json=json,
            headers=headers,
            timeout_seconds=timeout_seconds,
            allow_retry=allow_retry,
            ensure_success=False,
        )
        if not isinstance(payload, dict):
            raise OpenListError("OpenList JSON response is not an object", payload=payload)
        if ensure_success:
            self._ensure_api_success(payload)
        return payload

    def _ensure_api_success(self, payload: Any, *, http_status: int | None = None) -> None:
        if not isinstance(payload, dict):
            raise OpenListError("OpenList API payload is not a JSON object", http_status=http_status, payload=payload)
        if "code" not in payload:
            return
        code = payload.get("code")
        if str(code) == "200":
            return
        raise OpenListError(
            "OpenList API returned non-success code",
            http_status=http_status,
            api_code=code,
            api_message=str(payload.get("message") or ""),
            payload=payload,
        )

    def ping(self) -> bool:
        try:
            raw = self.request("GET", "/ping", allow_retry=False, ensure_success=False)
            if isinstance(raw, (bytes, bytearray)):
                return raw.strip() == b"pong"
            return str(raw).strip() == "pong"
        except Exception:
            return False

    def auth_login(self, username: str, password: str) -> dict[str, Any]:
        return self.request_json("POST", "/api/auth/login", json={"username": username, "password": password})

    def auth_login_hash(self, username: str, password: str) -> dict[str, Any]:
        return self.request_json("POST", "/api/auth/login/hash", json={"username": username, "password": password})

    def auth_login_ldap(self, username: str, password: str) -> dict[str, Any]:
        return self.request_json("POST", "/api/auth/login/ldap", json={"username": username, "password": password})

    def me(self) -> dict[str, Any]:
        return self.request_json("GET", "/api/me")

    def me_update(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self.request_json("POST", "/api/me/update", json=dict(payload))

    def me_sshkey_list(self) -> dict[str, Any]:
        return self.request_json("GET", "/api/me/sshkey/list")

    def me_sshkey_add(self, title: str, key: str) -> dict[str, Any]:
        return self.request_json("POST", "/api/me/sshkey/add", json={"title": title, "key": key})

    def me_sshkey_delete(self, key_id: int) -> dict[str, Any]:
        return self.request_json("POST", "/api/me/sshkey/delete", json={"id": key_id})

    def auth_2fa_generate(self) -> dict[str, Any]:
        return self.request_json("POST", "/api/auth/2fa/generate", json={})

    def auth_2fa_verify(self, code: str) -> dict[str, Any]:
        return self.request_json("POST", "/api/auth/2fa/verify", json={"code": code})

    def auth_logout(self) -> dict[str, Any]:
        return self.request_json("GET", "/api/auth/logout")

    def auth_sso(self, method: str) -> bytes:
        return self.request("GET", "/api/auth/sso", params={"method": method}, ensure_success=False, allow_retry=False)

    def auth_sso_callback(self, method: str, *, params: Mapping[str, Any] | None = None) -> bytes:
        p = dict(params or {})
        p["method"] = method
        return self.request("GET", "/api/auth/sso_callback", params=p, ensure_success=False, allow_retry=False)

    def authn_webauthn_begin_login(self) -> dict[str, Any]:
        return self.request_json("GET", "/api/authn/webauthn_begin_login")

    def authn_webauthn_finish_login(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self.request_json("POST", "/api/authn/webauthn_finish_login", json=dict(payload))

    def authn_webauthn_begin_registration(self) -> dict[str, Any]:
        return self.request_json("GET", "/api/authn/webauthn_begin_registration")

    def authn_webauthn_finish_registration(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self.request_json("POST", "/api/authn/webauthn_finish_registration", json=dict(payload))

    def authn_delete_authn(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self.request_json("POST", "/api/authn/delete_authn", json=dict(payload))

    def authn_getcredentials(self) -> dict[str, Any]:
        return self.request_json("GET", "/api/authn/getcredentials")

    def public_settings(self) -> dict[str, Any]:
        return self.request_json("GET", "/api/public/settings", ensure_success=False)

    def public_offline_download_tools(self) -> dict[str, Any]:
        return self.request_json("GET", "/api/public/offline_download_tools", ensure_success=False)

    def public_archive_extensions(self) -> dict[str, Any]:
        return self.request_json("GET", "/api/public/archive_extensions", ensure_success=False)

    def admin_storage_list(self) -> dict[str, Any]:
        return self.request_json("GET", "/api/admin/storage/list")

    def admin_storage_get(self, storage_id: str | int) -> dict[str, Any]:
        return self.request_json("GET", "/api/admin/storage/get", params={"id": str(storage_id)})

    def admin_storage_create(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self.request_json("POST", "/api/admin/storage/create", json=dict(payload))

    def admin_storage_update(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self.request_json("POST", "/api/admin/storage/update", json=dict(payload))

    def admin_storage_delete(self, storage_id: str | int) -> dict[str, Any]:
        return self.request_json("POST", "/api/admin/storage/delete", json={"id": int(storage_id)})

    def admin_storage_enable(self, storage_id: str | int) -> dict[str, Any]:
        return self.request_json("POST", "/api/admin/storage/enable", json={"id": int(storage_id)})

    def admin_storage_disable(self, storage_id: str | int) -> dict[str, Any]:
        return self.request_json("POST", "/api/admin/storage/disable", json={"id": int(storage_id)})

    def admin_storage_load_all(self) -> dict[str, Any]:
        return self.request_json("POST", "/api/admin/storage/load_all", json={})

    def admin_driver_list(self) -> dict[str, Any]:
        return self.request_json("GET", "/api/admin/driver/list")

    def admin_driver_names(self) -> dict[str, Any]:
        return self.request_json("GET", "/api/admin/driver/names")

    def admin_driver_info(self, driver_name: str) -> dict[str, Any]:
        return self.request_json("GET", "/api/admin/driver/info", params={"name": driver_name})

    def admin_setting_get(self) -> dict[str, Any]:
        return self.request_json("GET", "/api/admin/setting/get")

    def admin_setting_list(self) -> dict[str, Any]:
        return self.request_json("GET", "/api/admin/setting/list")

    def admin_setting_save(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self.request_json("POST", "/api/admin/setting/save", json=dict(payload))

    def admin_setting_delete(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self.request_json("POST", "/api/admin/setting/delete", json=dict(payload))

    def admin_setting_default(self) -> dict[str, Any]:
        return self.request_json("POST", "/api/admin/setting/default", json={})

    def admin_setting_reset_token(self) -> dict[str, Any]:
        return self.request_json("POST", "/api/admin/setting/reset_token", json={})

    def admin_setting_set_aria2(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self.request_json("POST", "/api/admin/setting/set_aria2", json=dict(payload))

    def admin_setting_set_qbit(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self.request_json("POST", "/api/admin/setting/set_qbit", json=dict(payload))

    def admin_setting_set_transmission(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self.request_json("POST", "/api/admin/setting/set_transmission", json=dict(payload))

    def admin_setting_set_115(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self.request_json("POST", "/api/admin/setting/set_115", json=dict(payload))

    def admin_setting_set_115_open(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self.request_json("POST", "/api/admin/setting/set_115_open", json=dict(payload))

    def admin_setting_set_123_pan(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self.request_json("POST", "/api/admin/setting/set_123_pan", json=dict(payload))

    def admin_setting_set_123_open(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self.request_json("POST", "/api/admin/setting/set_123_open", json=dict(payload))

    def admin_setting_set_pikpak(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self.request_json("POST", "/api/admin/setting/set_pikpak", json=dict(payload))

    def admin_setting_set_thunder(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self.request_json("POST", "/api/admin/setting/set_thunder", json=dict(payload))

    def admin_setting_set_thunderx(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self.request_json("POST", "/api/admin/setting/set_thunderx", json=dict(payload))

    def admin_setting_set_thunder_browser(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self.request_json("POST", "/api/admin/setting/set_thunder_browser", json=dict(payload))

    def admin_meta_list(self) -> dict[str, Any]:
        return self.request_json("GET", "/api/admin/meta/list")

    def admin_meta_get(self, meta_id: str | int) -> dict[str, Any]:
        return self.request_json("GET", "/api/admin/meta/get", params={"id": str(meta_id)})

    def admin_meta_create(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self.request_json("POST", "/api/admin/meta/create", json=dict(payload))

    def admin_meta_update(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self.request_json("POST", "/api/admin/meta/update", json=dict(payload))

    def admin_meta_delete(self, meta_id: str | int) -> dict[str, Any]:
        return self.request_json("POST", "/api/admin/meta/delete", json={"id": int(meta_id)})

    def admin_user_list(self) -> dict[str, Any]:
        return self.request_json("GET", "/api/admin/user/list")

    def admin_user_get(self, user_id: str | int) -> dict[str, Any]:
        return self.request_json("GET", "/api/admin/user/get", params={"id": str(user_id)})

    def admin_user_create(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self.request_json("POST", "/api/admin/user/create", json=dict(payload))

    def admin_user_update(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self.request_json("POST", "/api/admin/user/update", json=dict(payload))

    def admin_user_cancel_2fa(self, user_id: str | int) -> dict[str, Any]:
        return self.request_json("POST", "/api/admin/user/cancel_2fa", json={"id": int(user_id)})

    def admin_user_delete(self, user_id: str | int) -> dict[str, Any]:
        return self.request_json("POST", "/api/admin/user/delete", json={"id": int(user_id)})

    def admin_user_del_cache(self, user_id: str | int) -> dict[str, Any]:
        return self.request_json("POST", "/api/admin/user/del_cache", json={"id": int(user_id)})

    def admin_user_sshkey_list(self) -> dict[str, Any]:
        return self.request_json("GET", "/api/admin/user/sshkey/list")

    def admin_user_sshkey_delete(self, key_id: str | int) -> dict[str, Any]:
        return self.request_json("POST", "/api/admin/user/sshkey/delete", json={"id": int(key_id)})

    def admin_message_get(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self.request_json("POST", "/api/admin/message/get", json=dict(payload))

    def admin_message_send(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self.request_json("POST", "/api/admin/message/send", json=dict(payload))

    def admin_index_build(self, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
        return self.request_json("POST", "/api/admin/index/build", json=dict(payload or {}))

    def admin_index_update(self, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
        return self.request_json("POST", "/api/admin/index/update", json=dict(payload or {}))

    def admin_index_stop(self) -> dict[str, Any]:
        return self.request_json("POST", "/api/admin/index/stop", json={})

    def admin_index_clear(self) -> dict[str, Any]:
        return self.request_json("POST", "/api/admin/index/clear", json={})

    def admin_index_progress(self) -> dict[str, Any]:
        return self.request_json("GET", "/api/admin/index/progress")

    def admin_scan_start(self, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
        return self.request_json("POST", "/api/admin/scan/start", json=dict(payload or {}))

    def admin_scan_stop(self) -> dict[str, Any]:
        return self.request_json("POST", "/api/admin/scan/stop", json={})

    def admin_scan_progress(self) -> dict[str, Any]:
        return self.request_json("GET", "/api/admin/scan/progress")

    def fs_list(
        self,
        path: str,
        *,
        password: str = "",
        refresh: bool = False,
        page: int = 1,
        per_page: int = 30,
    ) -> dict[str, Any]:
        payload = {
            "path": path,
            "password": password,
            "refresh": bool(refresh),
            "page": int(page),
            "per_page": int(per_page),
        }
        try:
            return self.request_json("POST", "/api/fs/listGet", json=payload)
        except Exception:
            return self.request_json("POST", "/api/fs/list", json=payload)

    def fs_get(self, path: str, *, password: str = "") -> dict[str, Any]:
        return self.request_json("POST", "/api/fs/get", json={"path": path, "password": password})

    def download_url(
        self,
        url: str,
        *,
        dst_path: str | Path | None = None,
        fileobj: BinaryIO | None = None,
        on_chunk: Callable[[int], None] | None = None,
        chunk_size: int = 1024 * 1024,
        timeout_seconds: float | None = None,
    ) -> int:
        if (dst_path is None) == (fileobj is None):
            raise ValueError("Either dst_path or fileobj must be provided")
        timeout = float(timeout_seconds) if timeout_seconds is not None else self.timeout_seconds
        resp = self.session.get(str(url), stream=True, timeout=timeout, verify=self.verify)
        resp.raise_for_status()
        written = 0
        if dst_path is not None:
            p = Path(dst_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("wb") as f:
                for chunk in resp.iter_content(chunk_size=chunk_size):
                    if not chunk:
                        continue
                    f.write(chunk)
                    written += len(chunk)
                    if on_chunk:
                        on_chunk(len(chunk))
        else:
            assert fileobj is not None
            for chunk in resp.iter_content(chunk_size=chunk_size):
                if not chunk:
                    continue
                fileobj.write(chunk)
                written += len(chunk)
                if on_chunk:
                    on_chunk(len(chunk))
        return written

    def download_by_path(
        self,
        path: str,
        *,
        password: str = "",
        dst_path: str | Path | None = None,
        fileobj: BinaryIO | None = None,
        on_chunk: Callable[[int], None] | None = None,
        chunk_size: int = 1024 * 1024,
        timeout_seconds: float | None = None,
    ) -> int:
        resp = self.fs_get(path, password=password)
        data = resp.get("data") if isinstance(resp, dict) else None
        raw_url = ""
        if isinstance(data, dict):
            raw_url = str(data.get("raw_url") or data.get("rawURL") or data.get("rawUrl") or "").strip()
        if not raw_url:
            raise OpenListError("OpenList fs_get missing raw_url", payload=resp)
        return self.download_url(
            raw_url,
            dst_path=dst_path,
            fileobj=fileobj,
            on_chunk=on_chunk,
            chunk_size=chunk_size,
            timeout_seconds=timeout_seconds,
        )

    def fs_dirs(self, path: str, *, password: str = "", force_root: bool = False) -> dict[str, Any]:
        return self.request_json(
            "POST",
            "/api/fs/dirs",
            json={"path": path, "password": password, "force_root": bool(force_root)},
        )

    def fs_search(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self.request_json("POST", "/api/fs/search", json=dict(payload))

    def fs_other(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self.request_json("POST", "/api/fs/other", json=dict(payload))

    def fs_mkdir(self, path: str) -> dict[str, Any]:
        return self.request_json("POST", "/api/fs/mkdir", json={"path": path})

    def fs_rename(self, path: str, name: str, *, overwrite: bool = False) -> dict[str, Any]:
        return self.request_json("POST", "/api/fs/rename", json={"path": path, "name": name, "overwrite": bool(overwrite)})

    def fs_batch_rename(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self.request_json("POST", "/api/fs/batch_rename", json=dict(payload))

    def fs_regex_rename(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self.request_json("POST", "/api/fs/regex_rename", json=dict(payload))

    def fs_move(
        self,
        src_dir: str,
        dst_dir: str,
        names: Iterable[str],
        *,
        overwrite: bool = False,
        skip_existing: bool = False,
    ) -> dict[str, Any]:
        return self.request_json(
            "POST",
            "/api/fs/move",
            json={
                "src_dir": src_dir,
                "dst_dir": dst_dir,
                "names": list(names),
                "overwrite": bool(overwrite),
                "skip_existing": bool(skip_existing),
            },
        )

    def fs_recursive_move(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self.request_json("POST", "/api/fs/recursive_move", json=dict(payload))

    def fs_copy(
        self,
        src_dir: str,
        dst_dir: str,
        names: Iterable[str],
        *,
        overwrite: bool = False,
        skip_existing: bool = False,
        merge: bool = False,
    ) -> dict[str, Any]:
        return self.request_json(
            "POST",
            "/api/fs/copy",
            json={
                "src_dir": src_dir,
                "dst_dir": dst_dir,
                "names": list(names),
                "overwrite": bool(overwrite),
                "skip_existing": bool(skip_existing),
                "merge": bool(merge),
            },
        )

    def fs_remove(self, dir_path: str, names: Iterable[str]) -> dict[str, Any]:
        return self.request_json("POST", "/api/fs/remove", json={"dir": dir_path, "names": list(names)})

    def fs_remove_empty_directory(self, src_dir: str) -> dict[str, Any]:
        return self.request_json("POST", "/api/fs/remove_empty_directory", json={"src_dir": src_dir})

    def fs_archive_decompress(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self.request_json("POST", "/api/fs/archive/decompress", json=dict(payload))

    def fs_archive_meta(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self.request_json("POST", "/api/fs/archive/meta", json=dict(payload))

    def fs_archive_list(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self.request_json("POST", "/api/fs/archive/list", json=dict(payload))

    def fs_get_direct_upload_info(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self.request_json("POST", "/api/fs/get_direct_upload_info", json=dict(payload))

    def fs_link(self, path: str) -> dict[str, Any]:
        return self.request_json("POST", "/api/fs/link", json={"path": path})

    def fs_put(
        self,
        file_path: str,
        content: bytes | BinaryIO,
        *,
        password: str = "",
        md5: str | None = None,
        sha1: str | None = None,
        sha256: str | None = None,
        content_length: int | None = None,
    ) -> dict[str, Any]:
        h: dict[str, str] = {"File-Path": file_path}
        if password:
            h["Password"] = password
        if md5:
            h["X-File-Md5"] = md5
        if sha1:
            h["X-File-Sha1"] = sha1
        if sha256:
            h["X-File-Sha256"] = sha256
        if content_length is not None:
            h["Content-Length"] = str(int(content_length))

        url = self._url("/api/fs/put")
        resp = self.session.request(
            method="PUT",
            url=url,
            data=content,
            headers=self._headers(h),
            timeout=self.timeout_seconds,
            verify=self.verify,
        )
        if resp.status_code >= 400:
            raise OpenListError("OpenList fs_put failed", http_status=resp.status_code, payload=resp.text[:500])
        payload = resp.json()
        self._ensure_api_success(payload, http_status=resp.status_code)
        return payload

    def fs_form(
        self,
        file_path: str,
        files: Mapping[str, Any],
        *,
        password: str = "",
        data: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        h: dict[str, str] = {"File-Path": file_path}
        if password:
            h["Password"] = password
        url = self._url("/api/fs/form")
        resp = self.session.request(
            method="PUT",
            url=url,
            data=dict(data or {}),
            files=dict(files),
            headers=self._headers(h),
            timeout=self.timeout_seconds,
            verify=self.verify,
        )
        if resp.status_code >= 400:
            raise OpenListError("OpenList fs_form failed", http_status=resp.status_code, payload=resp.text[:500])
        payload = resp.json()
        self._ensure_api_success(payload, http_status=resp.status_code)
        return payload

    def fs_add_offline_download(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self.request_json("POST", "/api/fs/add_offline_download", json=dict(payload))

    def task_undone(self, task_type: Literal["upload", "copy", "move", "offline_download", "offline_download_transfer", "decompress", "decompress_upload"]) -> dict[str, Any]:
        return self.request_json("GET", f"/api/task/{task_type}/undone")

    def task_done(self, task_type: Literal["upload", "copy", "move", "offline_download", "offline_download_transfer", "decompress", "decompress_upload"]) -> dict[str, Any]:
        return self.request_json("GET", f"/api/task/{task_type}/done")

    def task_info(self, task_type: str, tid: str) -> dict[str, Any]:
        return self.request_json("POST", f"/api/task/{task_type}/info", params={"tid": tid})

    def task_cancel(self, task_type: str, tid: str) -> dict[str, Any]:
        return self.request_json("POST", f"/api/task/{task_type}/cancel", params={"tid": tid})

    def task_delete(self, task_type: str, tid: str) -> dict[str, Any]:
        return self.request_json("POST", f"/api/task/{task_type}/delete", params={"tid": tid})

    def task_retry(self, task_type: str, tid: str) -> dict[str, Any]:
        return self.request_json("POST", f"/api/task/{task_type}/retry", params={"tid": tid})

    def task_cancel_some(self, task_type: str, tids: list[str]) -> dict[str, Any]:
        return self.request_json("POST", f"/api/task/{task_type}/cancel_some", json=list(tids))

    def task_delete_some(self, task_type: str, tids: list[str]) -> dict[str, Any]:
        return self.request_json("POST", f"/api/task/{task_type}/delete_some", json=list(tids))

    def task_retry_some(self, task_type: str, tids: list[str]) -> dict[str, Any]:
        return self.request_json("POST", f"/api/task/{task_type}/retry_some", json=list(tids))

    def task_clear_done(self, task_type: str) -> dict[str, Any]:
        return self.request_json("POST", f"/api/task/{task_type}/clear_done")

    def task_clear_succeeded(self, task_type: str) -> dict[str, Any]:
        return self.request_json("POST", f"/api/task/{task_type}/clear_succeeded")

    def task_retry_failed(self, task_type: str) -> dict[str, Any]:
        return self.request_json("POST", f"/api/task/{task_type}/retry_failed")

    def admin_task_undone(self, task_type: str) -> dict[str, Any]:
        return self.request_json("GET", f"/api/admin/task/{task_type}/undone")

    def admin_task_done(self, task_type: str) -> dict[str, Any]:
        return self.request_json("GET", f"/api/admin/task/{task_type}/done")

    def admin_task_info(self, task_type: str, tid: str) -> dict[str, Any]:
        return self.request_json("POST", f"/api/admin/task/{task_type}/info", params={"tid": tid})

    def admin_task_cancel(self, task_type: str, tid: str) -> dict[str, Any]:
        return self.request_json("POST", f"/api/admin/task/{task_type}/cancel", params={"tid": tid})

    def admin_task_delete(self, task_type: str, tid: str) -> dict[str, Any]:
        return self.request_json("POST", f"/api/admin/task/{task_type}/delete", params={"tid": tid})

    def admin_task_retry(self, task_type: str, tid: str) -> dict[str, Any]:
        return self.request_json("POST", f"/api/admin/task/{task_type}/retry", params={"tid": tid})

    def admin_task_cancel_some(self, task_type: str, tids: list[str]) -> dict[str, Any]:
        return self.request_json("POST", f"/api/admin/task/{task_type}/cancel_some", json=list(tids))

    def admin_task_delete_some(self, task_type: str, tids: list[str]) -> dict[str, Any]:
        return self.request_json("POST", f"/api/admin/task/{task_type}/delete_some", json=list(tids))

    def admin_task_retry_some(self, task_type: str, tids: list[str]) -> dict[str, Any]:
        return self.request_json("POST", f"/api/admin/task/{task_type}/retry_some", json=list(tids))

    def admin_task_clear_done(self, task_type: str) -> dict[str, Any]:
        return self.request_json("POST", f"/api/admin/task/{task_type}/clear_done")

    def admin_task_clear_succeeded(self, task_type: str) -> dict[str, Any]:
        return self.request_json("POST", f"/api/admin/task/{task_type}/clear_succeeded")

    def admin_task_retry_failed(self, task_type: str) -> dict[str, Any]:
        return self.request_json("POST", f"/api/admin/task/{task_type}/retry_failed")

    def share_list(self) -> dict[str, Any]:
        return self.request_json("POST", "/api/share/list", json={})

    def share_get(self, share_id: str | int) -> dict[str, Any]:
        return self.request_json("GET", "/api/share/get", params={"id": str(share_id)})

    def share_create(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self.request_json("POST", "/api/share/create", json=dict(payload))

    def share_update(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self.request_json("POST", "/api/share/update", json=dict(payload))

    def share_delete(self, share_id: str | int) -> dict[str, Any]:
        return self.request_json("POST", "/api/share/delete", json={"id": int(share_id)})

    def share_enable(self, share_id: str | int) -> dict[str, Any]:
        return self.request_json("POST", "/api/share/enable", json={"id": int(share_id)})

    def share_disable(self, share_id: str | int) -> dict[str, Any]:
        return self.request_json("POST", "/api/share/disable", json={"id": int(share_id)})

# -*- coding: utf-8 -*-
"""
123网盘适配器
基于 123pan 的账号密码登录（Bearer token）与分享页接口实现
"""
import json
import logging
import random
import re
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
import os
from urllib.parse import parse_qs, urlparse
from collections import deque

import requests

from app.extensions.adapters.base_adapter import BaseCloudDriveAdapter

_global_config_saver = None
logger = logging.getLogger(__name__)


def set_config_saver(config_path: Any):
    global _global_config_saver
    if callable(config_path):
        _global_config_saver = config_path


class Pan123Adapter(BaseCloudDriveAdapter):
    DRIVE_TYPE = "123pan"
    DRIVE_NAME = "123 网盘"
    CONFIG_FORMAT = "kv"
    default_config = {
        "username": "",
        "password": "",
        "authorization": "",
        "protocol": "web",
        "deviceType": "M2007J20CI",
        "osVersion": "Android_10",
        "loginUuid": "",
        "name": "",
        "debug": False,
    }
    config_fields = [
        {
            "key": "username",
            "label": "用户名",
            "description": "123 网盘登录用户名。",
            "input_type": "text",
            "required": False,
            "secret": False,
            "placeholder": "",
        },
        {
            "key": "password",
            "label": "密码",
            "description": "123 网盘登录密码；如已填写 authorization 可留空。",
            "input_type": "password",
            "required": False,
            "secret": True,
            "placeholder": "",
        },
        {
            "key": "authorization",
            "label": "Authorization",
            "description": "已获取到的 Bearer Token；优先于用户名密码使用。",
            "input_type": "textarea",
            "required": False,
            "secret": True,
            "placeholder": "Bearer ...",
        },
        {
            "key": "protocol",
            "label": "协议",
            "description": "请求协议，常用 web。",
            "input_type": "text",
            "required": False,
            "secret": False,
            "placeholder": "web",
        },
        {
            "key": "deviceType",
            "label": "设备型号",
            "description": "可选，覆盖默认设备型号。",
            "input_type": "text",
            "required": False,
            "secret": False,
            "placeholder": "M2007J20CI",
        },
        {
            "key": "osVersion",
            "label": "系统版本",
            "description": "可选，覆盖默认系统版本。",
            "input_type": "text",
            "required": False,
            "secret": False,
            "placeholder": "Android_10",
        },
        {
            "key": "loginUuid",
            "label": "Login UUID",
            "description": "可选，不填时自动生成。",
            "input_type": "text",
            "required": False,
            "secret": False,
            "placeholder": "",
        },
        {
            "key": "name",
            "label": "账户别名",
            "description": "可选，用于区分多个 123 网盘账户。",
            "input_type": "text",
            "required": False,
            "secret": False,
            "placeholder": "",
        },
        {
            "key": "debug",
            "label": "调试模式",
            "description": "开启后输出更多调试日志。",
            "input_type": "switch",
            "required": False,
            "secret": False,
            "placeholder": "",
        },
    ]
    DEFAULT_BASE_URL = "https://www.123pan.com"

    WEB_APP_VERSION = "3"
    WEB_USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    )

    ANDROID_APP_VERSION = "61"
    ANDROID_X_APP_VERSION = "2.4.0"
    ANDROID_DEVICE_BRAND = "Xiaomi"

    def __init__(
        self,
        cookie: str = "",
        index: int = 0,
        config: dict | None = None,
        account_name: str = "",
        no_login: bool = False,
    ):
        super().__init__(cookie, index, config=config, no_login=no_login)
        self._api_base = self.DEFAULT_BASE_URL
        self._share_base = self.DEFAULT_BASE_URL
        self._last_share_key = ""

        self._cookie_kv = {str(k): v for k, v in self.config.items()}
        self._user_name = self._cookie_kv.get("username") or self._cookie_kv.get("userName")
        self._password = self._cookie_kv.get("password") or self._cookie_kv.get("passWord")
        self._authorization = self._cookie_kv.get("authorization") or self._cookie_kv.get("Authorization") or ""
        self._protocol = (self._cookie_kv.get("protocol") or "web").lower()

        self._device_type = self._cookie_kv.get("deviceType") or self._cookie_kv.get("devicetype") or "M2007J20CI"
        self._os_version = self._cookie_kv.get("osVersion") or self._cookie_kv.get("osversion") or "Android_10"
        self._login_uuid = self._cookie_kv.get("loginUuid") or self._cookie_kv.get("loginuuid") or str(uuid.uuid4())
        self._account_name = (
            self._cookie_kv.get("name")
            or self._cookie_kv.get("account_name")
            or account_name
            or self._user_name
            or f"123pan用户{self.index}"
        )
        self._debug = (
            str(self._cookie_kv.get("debug", "")).strip().lower() in ("1", "true", "yes", "on")
            or os.environ.get("CLOUD_AUTO_SAVE_123PAN_DEBUG", "").strip() == "1"
        )

        self._session = requests.Session()
        self._session.headers.update(self._build_headers())
        if self._debug:
            logger.setLevel(logging.DEBUG)
        logger.info(f"[123pan] adapter init: account={self._account_name}, protocol={self._protocol}")
        self._share_path_cache: Dict[str, List[Dict[str, str]]] = {}

    def _parse_cookie_kv(self, cookie: str) -> Dict[str, str]:
        result: Dict[str, str] = {}
        if not cookie:
            return result
        for kv in cookie.split(";"):
            kv = kv.strip()
            if not kv or "=" not in kv:
                continue
            k, v = kv.split("=", 1)
            k = k.strip()
            v = v.strip()
            if k:
                result[k] = v
        return result

    def _safe_kv(self, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        redacted = {}
        for k, v in data.items():
            lk = str(k).lower()
            if lk in ("password", "passwd", "pass", "authorization", "cookie", "token", "refresh_token", "pwd", "sharepwd"):
                redacted[k] = "***"
            else:
                redacted[k] = v
        return redacted

    def _summarize_response(self, resp: Any) -> Dict[str, Any]:
        if not isinstance(resp, dict):
            return {"type": type(resp).__name__}
        if "code" in resp:
            code = resp.get("code")
            msg = resp.get("message")
            data = resp.get("data") or {}
        else:
            code = resp.get("info", {}).get("code")
            msg = resp.get("info", {}).get("message")
            data = resp.get("info", {}).get("data") or {}
        summary: Dict[str, Any] = {"code": code, "message": msg}
        if isinstance(data, dict):
            if "InfoList" in data and isinstance(data.get("InfoList"), list):
                summary["InfoList_len"] = len(data.get("InfoList") or [])
                summary["Next"] = data.get("Next")
            if "Info" in data and isinstance(data.get("Info"), dict):
                info = data.get("Info") or {}
                summary["Info_FileId"] = info.get("FileId")
                summary["Info_FileName"] = info.get("FileName")
                summary["Info_Type"] = info.get("Type")
        return summary

    def _parse_time_to_ts(self, v: Any) -> int:
        if not v:
            return 0
        if isinstance(v, (int, float)):
            if v > 10_000_000_000:
                return int(v / 1000)
            return int(v)
        if not isinstance(v, str):
            return 0
        s = v.strip()
        if not s:
            return 0
        try:
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                return int(dt.timestamp())
            return int(dt.timestamp())
        except Exception:
            pass
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return int(datetime.strptime(s, fmt).timestamp())
            except Exception:
                continue
        return 0

    def _build_headers(self) -> Dict[str, str]:
        if self._protocol == "android":
            return {
                "content-type": "application/json",
                "authorization": self._authorization,
                "Authorization": self._authorization,
                "LoginUuid": self._login_uuid,
                "user-agent": f"123pan/v{self.ANDROID_X_APP_VERSION}({self._os_version};{self.ANDROID_DEVICE_BRAND})",
                "accept-encoding": "gzip",
                "osversion": self._os_version,
                "platform": "android",
                "devicetype": self._device_type,
                "devicename": self.ANDROID_DEVICE_BRAND,
                "host": urlparse(self._api_base).netloc,
                "app-version": self.ANDROID_APP_VERSION,
                "x-app-version": self.ANDROID_X_APP_VERSION,
            }
        return {
            "content-type": "application/json",
            "authorization": self._authorization,
            "Authorization": self._authorization,
            "LoginUuid": self._login_uuid,
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "App-Version": self.WEB_APP_VERSION,
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Pragma": "no-cache",
            "Referer": f"{self._api_base}/",
            "User-Agent": self.WEB_USER_AGENT,
            "platform": "web",
        }

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json_data: Any = None,
        base_url: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: int = 30,
    ) -> Dict:
        self._throttle_request()
        url = path
        if not url.startswith("http://") and not url.startswith("https://"):
            base = base_url or self._api_base
            url = f"{base}{path}"
        start = time.time()
        try:
            resp = self._session.request(
                method,
                url,
                params=params,
                json=json_data,
                headers=headers,
                timeout=timeout,
            )
            data = resp.json()
            cost_ms = int((time.time() - start) * 1000)
            if self._debug:
                logger.debug(
                    f"[123pan] api {method} {url} cost={cost_ms}ms "
                    f"auth={'Y' if bool(self._authorization) else 'N'} "
                    f"params={self._safe_kv(params) if params else None} "
                    f"json={self._safe_kv(json_data) if isinstance(json_data, dict) else ('<json>' if json_data else None)} "
                    f"resp={self._summarize_response(data)}"
                )
            if isinstance(data, dict) and "code" in data and data.get("code") not in (0, 200):
                logger.warning(f"[123pan] api nonzero: {method} {path} -> {self._summarize_response(data)}")
            return data
        except Exception as e:
            cost_ms = int((time.time() - start) * 1000)
            logger.warning(f"[123pan] api error: {method} {url} cost={cost_ms}ms err={e}")
            return {"code": 500, "message": f"请求失败: {e}", "data": None}

    def _share_request(self, method: str, path: str, *, params: Optional[Dict[str, Any]] = None) -> Dict:
        url = f"{self._share_base}{path}"
        headers = {
            "User-Agent": self.WEB_USER_AGENT,
            "Referer": f"{self._share_base}/s/{self._last_share_key or ''}",
        }
        start = time.time()
        try:
            resp = requests.request(method, url, params=params, headers=headers, timeout=30)
            data = resp.json()
            cost_ms = int((time.time() - start) * 1000)
            if self._debug:
                logger.debug(
                    f"[123pan] share {method} {url} cost={cost_ms}ms params={self._safe_kv(params) if params else None} "
                    f"resp={self._summarize_response(data)}"
                )
            if isinstance(data, dict) and data.get("info", {}).get("code") not in (0, 200):
                logger.warning(f"[123pan] share nonzero: {method} {path} -> {self._summarize_response(data)}")
            return data
        except Exception as e:
            cost_ms = int((time.time() - start) * 1000)
            logger.warning(f"[123pan] share error: {method} {url} cost={cost_ms}ms err={e}")
            return {"info": {"code": 500, "message": f"请求失败: {e}", "data": None}}

    def _save_cookie_string(self):
        global _global_config_saver
        if not _global_config_saver:
            if self._debug:
                logger.debug(f"[123pan] config_saver not set, skip persist account={self._account_name}")
            return
        cookie_str = self._format_cookie_string()
        try:
            updated = _global_config_saver(cookie_str, self._account_name)
            if self._debug:
                logger.debug(f"[123pan] persist cookie to db: updated={updated} account={self._account_name}")
        except Exception as e:
            logger.warning(f"[123pan] persist cookie to db failed: account={self._account_name} err={e}")

    def _format_cookie_string(self) -> str:
        parts: List[str] = []
        if self._account_name:
            parts.append(f"name={self._account_name}")
        if self._user_name:
            parts.append(f"username={self._user_name}")
        if self._password:
            parts.append(f"password={self._password}")
        if self._authorization:
            parts.append(f"authorization={self._authorization}")
        if self._protocol:
            parts.append(f"protocol={self._protocol}")
        if self._device_type:
            parts.append(f"deviceType={self._device_type}")
        if self._os_version:
            parts.append(f"osVersion={self._os_version}")
        if self._login_uuid:
            parts.append(f"loginUuid={self._login_uuid}")
        return ";".join(parts)

    def _set_authorization(self, authorization: str):
        self._authorization = authorization or ""
        self._session.headers["authorization"] = self._authorization
        self._session.headers["Authorization"] = self._authorization

    def _login(self) -> Dict:
        if not self._user_name or not self._password:
            logger.warning(f"[123pan] login skipped: missing username/password account={self._account_name}")
            return {"code": 401, "message": "用户名或密码为空", "data": None}
        payload = {"type": 1, "passport": self._user_name, "password": self._password}
        res = self._request("POST", "/b/api/user/sign_in", json_data=payload, timeout=30)
        if res.get("code") in (0, 200) and res.get("data", {}).get("token"):
            token = res["data"]["token"]
            self._set_authorization(f"Bearer {token}")
            self._save_cookie_string()
            logger.info(f"[123pan] login ok: account={self._account_name}")
        else:
            logger.warning(f"[123pan] login failed: account={self._account_name} resp={self._summarize_response(res)}")
        return res

    def get_account_info(self) -> Any:
        res = self._request("GET", "/b/api/user/info", timeout=30)
        if res.get("code") in (401, 403):
            res = self._request("GET", "/api/user/info", timeout=30)
        if res.get("code") == 0 and isinstance(res.get("data"), dict):
            return res["data"]
        return False

    def get_account_config(self) -> Dict[str, Any]:
        """获取 123 网盘账户配置/容量信息"""
        account_info: Dict[str, Any] = {}
        try:
            if self._ensure_login():
                account_info = self.get_account_info() or {}
        except Exception:
            account_info = {}

        nickname = (
            account_info.get("Nickname")
            or account_info.get("NickName")
            or self.nickname
            or self._account_name
            or f"123pan用户{self.index}"
        )
        if nickname:
            self.nickname = nickname

        username = (
            account_info.get("Passport")
            or account_info.get("Mail")
            or self._user_name
            or nickname
        )

        used_space = None
        total_space = None
        try:
            if account_info.get("SpaceUsed") is not None:
                used_space = int(account_info.get("SpaceUsed") or 0)
        except Exception:
            used_space = None
        try:
            permanent = int(account_info.get("SpacePermanent") or 0)
            temp = int(account_info.get("SpaceTemp") or 0)
            if permanent or temp:
                total_space = permanent + temp
        except Exception:
            total_space = None

        member_type = ""
        member_status: Dict[str, Any] = {}
        try:
            is_vip = bool(account_info.get("Vip"))
            vip_level = account_info.get("VipLevel")
            vip_expire = account_info.get("VipExpire")
            if is_vip:
                member_type = "VIP"
                member_status = {
                    "is_vip": True,
                    "vip_level": vip_level,
                    "vip_expire": vip_expire,
                }
            else:
                member_status = {"is_vip": False}
        except Exception:
            member_type = ""
            member_status = {}

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
                "account_info": account_info or None,
                "member_info": account_info or None,
            },
        }

    def init(self) -> Any:
        info = None
        if self._authorization:
            if self._debug:
                logger.debug(f"[123pan] init: try existing authorization account={self._account_name}")
            info = self.get_account_info()
        if not info:
            logger.info(f"[123pan] init: relogin account={self._account_name}")
            login_res = self._login()
            if login_res.get("code") not in (0, 200):
                return False
            info = self.get_account_info()
        if info:
            self.is_active = True
            self.nickname = info.get("Nickname") or info.get("NickName") or self._account_name
            logger.info(f"[123pan] init ok: account={self._account_name} nickname={self.nickname}")
            return info
        logger.warning(f"[123pan] init failed: account={self._account_name}")
        return False

    def _ensure_login(self) -> bool:
        if self.is_active and self._authorization:
            return True
        if not self._authorization and (self._user_name and self._password):
            logger.info(f"[123pan] ensure_login: no authorization, try init account={self._account_name}")
        ok = bool(self.init())
        if not ok:
            logger.warning(f"[123pan] ensure_login failed: account={self._account_name}")
        return ok

    def extract_url(self, url: str) -> Tuple[Optional[str], str, Any, List]:
        share_key = None
        passcode = ""
        pdir_fid: Any = 0
        paths: List[Dict[str, str]] = []

        parsed = urlparse(url)
        if parsed.scheme and parsed.netloc:
            self._share_base = f"{parsed.scheme}://{parsed.netloc}"
        qs = parse_qs(parsed.query or "")
        passcode = (qs.get("pwd") or qs.get("passcode") or [""])[0] or ""

        m = re.search(r"/s/([^/?#]+)", parsed.path or "")
        if m:
            share_key = m.group(1)
            share_key = share_key.split(".")[0]

        frag = parsed.fragment or ""
        mfrag = re.search(r"(?:^|/)list/share/(\d+)", frag)
        if mfrag:
            try:
                pdir_fid = int(mfrag.group(1))
            except Exception:
                pdir_fid = 0
        self._last_share_key = share_key or ""
        if self._debug:
            logger.debug(f"[123pan] extract_url: base={self._share_base} share_key={share_key} pwd_present={'Y' if bool(passcode) else 'N'}")
        return share_key, passcode, pdir_fid, paths

    def get_stoken(self, pwd_id: str, passcode: str = "") -> Dict:
        info = self._share_request("GET", f"/gsb/s/{pwd_id}")
        if info.get("info", {}).get("code") != 0:
            return {"status": 404, "message": info.get("info", {}).get("message", "分享不存在"), "data": {}}
        has_pwd = bool(info.get("info", {}).get("data", {}).get("HasPwd"))
        if not has_pwd:
            return {"status": 200, "data": {"stoken": ""}}
        if not passcode:
            return {"status": 400, "message": "提取码不能为空", "data": {}}
        chk = self._share_request("GET", "/gsb/s/pwd-check", params={"shareKey": pwd_id, "pwd": passcode})
        if chk.get("info", {}).get("code") == 0:
            return {"status": 200, "data": {"stoken": passcode}}
        return {"status": 403, "message": chk.get("info", {}).get("message", "提取码错误"), "data": {}}

    def _share_list(self, share_key: str, share_pwd: str, parent_file_id: int) -> List[Dict]:
        list_merge: List[Dict] = []
        next_val: Any = 0
        page = 1
        while True:
            params = {
                "limit": 100,
                "next": next_val or 0,
                "orderBy": "file_name",
                "orderDirection": "asc",
                "shareKey": share_key,
                "ParentFileId": parent_file_id,
                "Page": page,
                "event": "homeListFile",
                "operateType": 1,
            }
            if share_pwd:
                params["SharePwd"] = share_pwd
            resp = self._request("GET", "/b/api/share/get", params=params, base_url=self._share_base, timeout=30)
            if resp.get("code") != 0:
                raise RuntimeError(resp.get("message", "获取分享列表失败"))
            data = resp.get("data") or {}
            info_list = data.get("InfoList") or []
            list_merge.extend(info_list)
            next_val = data.get("Next")
            if next_val in ("-1", -1, None):
                break
            page += 1
        if self._debug:
            logger.debug(f"[123pan] share_list done: share_key={share_key} parent={parent_file_id} count={len(list_merge)}")
        return list_merge

    def _get_share_full_path(self, share_key: str, share_pwd: str, target_dir_fid: int) -> List[Dict[str, str]]:
        cache_key = f"{self._share_base}|{share_key}|{share_pwd}|{target_dir_fid}"
        cached = self._share_path_cache.get(cache_key)
        if cached is not None:
            return cached

        if target_dir_fid in (0, "0", None):
            self._share_path_cache[cache_key] = []
            return []

        try:
            target_dir_fid_int = int(target_dir_fid)
        except Exception:
            self._share_path_cache[cache_key] = []
            return []

        visited_dirs = set()
        parent_map: Dict[int, int] = {}
        name_map: Dict[int, str] = {}

        q = deque([0])
        visited_dirs.add(0)
        list_calls = 0
        max_list_calls = 300

        while q and list_calls < max_list_calls:
            cur = q.popleft()
            try:
                items = self._share_list(share_key, share_pwd, cur)
                list_calls += 1
            except Exception:
                continue

            for it in items:
                try:
                    fid = int(it.get("FileId", 0))
                except Exception:
                    continue
                if fid <= 0:
                    continue
                if fid not in name_map:
                    name_map[fid] = it.get("FileName", "") or ""
                if fid not in parent_map:
                    parent_map[fid] = cur

                if fid == target_dir_fid_int:
                    path_nodes: List[Dict[str, str]] = []
                    node = fid
                    guard = 0
                    while node in parent_map and guard < 200:
                        path_nodes.append({"fid": str(node), "file_name": name_map.get(node, "")})
                        node = parent_map.get(node, 0)
                        guard += 1
                        if node == 0:
                            break
                    path_nodes.reverse()
                    self._share_path_cache[cache_key] = path_nodes
                    return path_nodes

                is_dir = int(it.get("Type", 0)) == 1
                if is_dir and fid not in visited_dirs:
                    visited_dirs.add(fid)
                    q.append(fid)

        if self._debug:
            logger.debug(
                f"[123pan] share_full_path not found: share_key={share_key} target={target_dir_fid_int} "
                f"calls={list_calls}"
            )
        self._share_path_cache[cache_key] = []
        return []

    def get_detail(
        self,
        pwd_id: str,
        stoken: str,
        pdir_fid: str,
        _fetch_share: int = 0,
        fetch_share_full_path: int = 0,
    ) -> Dict:
        try:
            parent_id = int(pdir_fid or 0)
        except Exception:
            parent_id = 0
        try:
            info_list = self._share_list(pwd_id, stoken, parent_id)
        except Exception as e:
            return {"code": 500, "message": str(e), "data": {"list": []}}

        converted = [self._convert_share_item(i) for i in info_list]
        full_path = []
        if fetch_share_full_path and parent_id not in (0, "0"):
            try:
                full_path = self._get_share_full_path(pwd_id, stoken, parent_id)
            except Exception:
                full_path = []
        return {
            "code": 0,
            "message": "ok",
            "data": {
                "list": converted,
                "full_path": full_path,
            },
            "metadata": {"_total": len(converted)},
        }

    def _convert_share_item(self, item: Dict) -> Dict:
        is_dir = int(item.get("Type", 0)) == 1
        fid = str(item.get("FileId", "0"))
        file_name = item.get("FileName", "")
        updated_at = self._parse_time_to_ts(item.get("UpdateAt") or item.get("CreateAt") or item.get("TrashedAt"))
        token = {
            "file_id": item.get("FileId"),
            "type": item.get("Type", 0),
            "etag": item.get("Etag", ""),
            "size": item.get("Size", 0),
            "file_name": file_name,
        }
        return {
            "fid": fid,
            "file_name": file_name,
            "file_type": 0 if is_dir else 1,
            "dir": is_dir,
            "size": item.get("Size", 0),
            "updated_at": updated_at,
            "share_fid_token": json.dumps(token, ensure_ascii=False),
            "obj_category": 0,
        }

    def ls_dir(self, pdir_fid: str, max_items: int = 0, **kwargs) -> Dict:
        if not self._ensure_login():
            return {"code": 401, "message": "未登录或登录失败", "data": {"list": []}}
        try:
            parent_id = int(pdir_fid or 0)
        except Exception:
            parent_id = 0
        params = {
            "driveId": "0",
            "limit": "100",
            "next": "0",
            "orderBy": "file_id",
            "orderDirection": "desc",
            "parentFileId": str(parent_id),
            "trashed": "false",
            "SearchData": "",
            "Page": "1",
            "OnlyLookAbnormalFile": "0",
        }
        resp = self._request("GET", "/b/api/file/list/new", params=params, timeout=30)
        if resp.get("code") != 0:
            if self._debug:
                logger.debug(f"[123pan] ls_dir fallback to /api/file/list/new, last={self._summarize_response(resp)}")
            resp = self._request("GET", "/api/file/list/new", params=params, timeout=30)
        if resp.get("code") != 0:
            return {"code": resp.get("code", 500), "message": resp.get("message", ""), "data": {"list": []}}
        info_list = (resp.get("data") or {}).get("InfoList") or []
        converted = [self._convert_dir_item(i) for i in info_list]
        if max_items > 0:
            converted = converted[:max_items]
        if self._debug:
            logger.debug(f"[123pan] ls_dir ok: pdir_fid={pdir_fid} count={len(converted)}")
        return {"code": 0, "message": "ok", "data": {"list": converted}, "metadata": {"_total": len(converted)}}

    def _convert_dir_item(self, item: Dict) -> Dict:
        is_dir = int(item.get("Type", 0)) == 1
        updated_at = self._parse_time_to_ts(item.get("UpdateAt") or item.get("CreateAt") or item.get("TrashedAt"))
        return {
            "fid": str(item.get("FileId", "0")),
            "file_name": item.get("FileName", ""),
            "file_type": 0 if is_dir else 1,
            "dir": is_dir,
            "size": item.get("Size", 0),
            "updated_at": updated_at,
            "obj_category": 0,
        }

    def _mkdir_under(self, parent_fid: int, name: str) -> Dict:
        if not self._ensure_login():
            return {"code": 401, "message": "未登录或登录失败", "data": None}
        payload = {
            "driveId": 0,
            "etag": "",
            "fileName": name,
            "parentFileId": parent_fid,
            "size": 0,
            "type": 1,
            "duplicate": 1,
            "NotReuse": True,
            "event": "newCreateFolder",
            "operateType": 1,
        }
        return self._request("POST", "/a/api/file/upload_request", json_data=payload, timeout=30)

    def mkdir(self, dir_path: str) -> Dict:
        dir_path = re.sub(r"/{2,}", "/", f"/{dir_path}".strip())
        if dir_path in ("/", ""):
            return {"code": 0, "data": {"fid": "0"}}
        parts = [p for p in dir_path.split("/") if p]
        current_fid = 0
        current_path = ""
        for name in parts:
            current_path = f"{current_path}/{name}" if current_path else f"/{name}"
            cached = self.savepath_fid.get(current_path)
            if cached:
                try:
                    current_fid = int(cached)
                    continue
                except Exception:
                    pass
            children = self.ls_dir(str(current_fid), max_items=2000)
            found = None
            if children.get("code") == 0:
                for it in children.get("data", {}).get("list", []):
                    if it.get("dir") and it.get("file_name") == name:
                        found = it
                        break
            if found:
                current_fid = int(found["fid"])
                self.savepath_fid[current_path] = str(current_fid)
                continue
            created = self._mkdir_under(current_fid, name)
            if created.get("code") != 0:
                return {"code": created.get("code", 500), "message": created.get("message", "创建目录失败")}
            info = (created.get("data") or {}).get("Info") or {}
            current_fid = int(info.get("FileId", 0))
            self.savepath_fid[current_path] = str(current_fid)
        return {"code": 0, "message": "ok", "data": {"fid": str(current_fid)}}

    def rename(self, fid: str, file_name: str) -> Dict:
        if not self._ensure_login():
            return {"code": 401, "message": "未登录或登录失败", "data": None}
        payload = {
            "driveId": 0,
            "fileId": int(fid),
            "fileName": file_name,
            "event": "fileRename",
            "operateType": 1,
        }
        resp = self._request("POST", "/b/api/file/rename", json_data=payload, timeout=30)
        if resp.get("code") == 0:
            return {"code": 0, "message": "ok", "data": resp.get("data")}
        return {"code": resp.get("code", 500), "message": resp.get("message", "重命名失败"), "data": resp.get("data")}

    def delete(self, filelist: List[str]) -> Dict:
        if not self._ensure_login():
            return {"code": 401, "message": "未登录或登录失败", "data": None}
        payload = {
            "driveId": 0,
            "fileTrashInfoList": [{"FileId": int(fid)} for fid in filelist],
            "operation": True,
        }
        resp = self._request("POST", "/a/api/file/trash", json_data=payload, timeout=30)
        if resp.get("code") != 0:
            if self._debug:
                logger.debug(f"[123pan] delete fallback to /b/api/file/trash, last={self._summarize_response(resp)}")
            resp = self._request("POST", "/b/api/file/trash", json_data=payload, timeout=30)
        if resp.get("code") == 0:
            return {"code": 0, "message": "ok", "data": resp.get("data")}
        return {"code": resp.get("code", 500), "message": resp.get("message", "删除失败"), "data": resp.get("data")}

    def _reuse_file(self, parent_fid: int, file_name: str, etag: str, size: int) -> Dict:
        if not self._ensure_login():
            return {"code": 401, "message": "未登录或登录失败", "data": None}
        if not etag:
            return {"code": 400, "message": "缺少 etag，无法执行秒传复用", "data": None}
        payload = {
            "driveId": 0,
            "etag": etag,
            "fileName": file_name,
            "parentFileId": parent_fid,
            "size": int(size),
            "type": 0,
            "duplicate": 0,
        }
        return self._request("POST", "/b/api/file/upload_request", json_data=payload, timeout=60)

    def _save_share_tree(
        self,
        share_key: str,
        share_pwd: str,
        share_file_id: int,
        share_file_name: str,
        share_is_dir: bool,
        share_etag: str,
        share_size: int,
        to_parent_fid: int,
        created_top_fids: List[str],
    ):
        if share_is_dir:
            created = self._mkdir_under(to_parent_fid, share_file_name)
            if created.get("code") != 0:
                raise RuntimeError(created.get("message", "创建目录失败"))
            info = (created.get("data") or {}).get("Info") or {}
            new_dir_id = int(info.get("FileId", 0))
            created_top_fids.append(str(new_dir_id))

            children = self._share_list(share_key, share_pwd, share_file_id)
            for child in children:
                is_dir = int(child.get("Type", 0)) == 1
                self._save_share_tree(
                    share_key=share_key,
                    share_pwd=share_pwd,
                    share_file_id=int(child.get("FileId", 0)),
                    share_file_name=child.get("FileName", ""),
                    share_is_dir=is_dir,
                    share_etag=child.get("Etag", ""),
                    share_size=int(child.get("Size", 0)),
                    to_parent_fid=new_dir_id,
                    created_top_fids=created_top_fids,
                )
            return

        reuse = self._reuse_file(to_parent_fid, share_file_name, share_etag, share_size)
        if reuse.get("code") != 0:
            raise RuntimeError(reuse.get("message", "转存失败"))
        info = (reuse.get("data") or {}).get("Info") or {}
        new_file_id = info.get("FileId")
        if new_file_id is not None:
            created_top_fids.append(str(new_file_id))

    def save_file(
        self,
        fid_list: List[str],
        fid_token_list: List[str],
        to_pdir_fid: str,
        pwd_id: str,
        stoken: str,
    ) -> Dict:
        if not self._ensure_login():
            return {"code": 401, "message": "未登录或登录失败", "data": None}
        try:
            to_parent = int(to_pdir_fid or 0)
        except Exception:
            to_parent = 0

        created_top_fids: List[str] = []
        if self._debug:
            logger.debug(
                f"[123pan] save_file start: share_key={pwd_id} items={len(fid_list)} to_pdir_fid={to_pdir_fid}"
            )
        for fid, token_str in zip(fid_list, fid_token_list):
            try:
                token = json.loads(token_str) if token_str else {}
            except Exception:
                token = {}
            share_file_id = int(token.get("file_id") or fid or 0)
            share_type = int(token.get("type", 0))
            share_is_dir = share_type == 1
            share_file_name = token.get("file_name") or ""
            share_etag = token.get("etag") or ""
            share_size = int(token.get("size") or 0)
            if not share_file_name:
                continue

            try:
                self._save_share_tree(
                    share_key=pwd_id,
                    share_pwd=stoken,
                    share_file_id=share_file_id,
                    share_file_name=share_file_name,
                    share_is_dir=share_is_dir,
                    share_etag=share_etag,
                    share_size=share_size,
                    to_parent_fid=to_parent,
                    created_top_fids=created_top_fids,
                )
            except Exception as e:
                return {"code": 500, "message": str(e), "data": None}

            time.sleep(random.uniform(0.05, 0.15))

        if self._debug:
            logger.debug(f"[123pan] save_file done: created={len(created_top_fids)}")
        return {"code": 0, "message": "ok", "data": {"_sync": True, "save_as_top_fids": created_top_fids}}

    def query_task(self, task_id: str) -> Dict:
        return {"code": 0, "message": "ok", "data": {"save_as": {"save_as_top_fids": []}}}

    def get_fids(self, file_paths: List[str]) -> List[Dict]:
        if not self._ensure_login():
            return []
        results: List[Dict] = []
        for p in file_paths:
            p = re.sub(r"/{2,}", "/", f"/{p}".strip())
            if p in ("/", ""):
                results.append({"file_path": "/", "fid": "0"})
                continue
            if p in self.savepath_fid:
                results.append({"file_path": p, "fid": self.savepath_fid[p]})
                continue
            parts = [x for x in p.split("/") if x]
            current_fid = 0
            current_path = ""
            ok = True
            for name in parts:
                current_path = f"{current_path}/{name}" if current_path else f"/{name}"
                cached = self.savepath_fid.get(current_path)
                if cached:
                    try:
                        current_fid = int(cached)
                        continue
                    except Exception:
                        pass
                children = self.ls_dir(str(current_fid), max_items=2000)
                if children.get("code") != 0:
                    ok = False
                    break
                found = None
                for it in children.get("data", {}).get("list", []):
                    if it.get("dir") and it.get("file_name") == name:
                        found = it
                        break
                if not found:
                    ok = False
                    break
                current_fid = int(found["fid"])
                self.savepath_fid[current_path] = str(current_fid)
            if ok:
                results.append({"file_path": p, "fid": str(current_fid)})
        return results

# -*- coding: utf-8 -*-
from __future__ import annotations

import base64
import hashlib
import json
import logging
import random
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, quote, unquote, urlparse

import requests

from app.extensions.adapters.base_adapter import BaseCloudDriveAdapter


logger = logging.getLogger(__name__)


class Cloud139Adapter(BaseCloudDriveAdapter):
    DRIVE_TYPE = "cloud139"
    DRIVE_NAME = "移动云盘"
    CONFIG_FORMAT = "kv"
    default_config = {
        "authorization": "",
        "cookie": "",
        "phone": "",
        "debug": False,
    }
    config_fields = [
        {
            "key": "authorization",
            "label": "Authorization",
            "description": "抓包获得的 Basic Authorization，支持带或不带 Basic 前缀。",
            "input_type": "textarea",
            "required": False,
            "secret": True,
            "placeholder": "Basic xxxxx",
        },
        {
            "key": "cookie",
            "label": "Cookie",
            "description": "浏览器 Cookie 字符串；未填写 Authorization 时可作为备用登录态。",
            "input_type": "textarea",
            "required": False,
            "secret": True,
            "placeholder": "sid=...",
        },
        {
            "key": "phone",
            "label": "手机号",
            "description": "请求体里的账号信息，若 Authorization 内可解析出手机号可留空。",
            "input_type": "text",
            "required": False,
            "secret": False,
            "placeholder": "13800138000",
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

    BASE_URL = "https://yun.139.com"
    USER_NJS_URL = "https://user-njs.yun.139.com"
    SHARE_KD_NJS_URL = "https://share-kd-njs.yun.139.com"
    PERSONAL_KD_NJS_URL = "https://personal-kd-njs.yun.139.com"
    CATALOG_V1 = f"{BASE_URL}/orchestration/personalCloud/catalog/v1.0"
    SIGN_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
    DEFAULT_HEADERS = {
        "Content-Type": "application/json",
        "x-yun-api-version": "v1",
        "x-yun-app-channel": "10000034",
        "x-yun-channel-source": "10000034",
        "x-yun-client-info": "||9|7.14.4|edge||||linux unknow||zh-CN|||",
        "x-yun-module-type": "100",
        "x-yun-svc-type": "1",
        "mcloud-channel": "1000101",
        "mcloud-version": "7.14.4",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Origin": "https://yun.139.com",
        "Referer": "https://yun.139.com/",
    }

    def __init__(
        self,
        cookie: str = "",
        index: int = 0,
        config: dict[str, Any] | None = None,
        account_name: str = "",
        no_login: bool = False,
    ):
        super().__init__(cookie, index, config=config, no_login=no_login)
        self._cfg = dict(self.config or {})
        self._authorization = str(self._cfg.get("authorization") or "").strip()
        self._cookie_value = str(self._cfg.get("cookie") or "").strip()
        self._phone = str(self._cfg.get("phone") or "").strip()
        self._account_name = account_name or f"cloud139用户{self.index}"
        self._debug = bool(self._cfg.get("debug"))
        self._user_cache: dict[str, Any] | None = None

        self._session = requests.Session()
        self._session.headers.update(dict(self.DEFAULT_HEADERS))
        self._apply_auth_headers()
        if self._debug:
            logger.setLevel(logging.DEBUG)

    @staticmethod
    def _md5(value: str) -> str:
        return hashlib.md5(value.encode("utf-8")).hexdigest()

    @classmethod
    def _random_str(cls, n: int = 16) -> str:
        return "".join(random.choice(cls.SIGN_CHARS) for _ in range(n))

    @staticmethod
    def _format_datetime_cst() -> str:
        cst = datetime.fromtimestamp(time.time() + 8 * 3600)
        return cst.strftime("%Y-%m-%d %H:%M:%S")

    def _get_new_sign_hash(self, body: dict[str, Any] | None, datetime_cst: str, random_str: str) -> str:
        raw = ""
        if body:
            raw = json.dumps(dict(body), ensure_ascii=False, separators=(",", ":"))
            raw = quote(raw, safe="")
            raw = "".join(sorted(raw))
        b64 = base64.b64encode(raw.encode("utf-8")).decode("utf-8")
        r = self._md5(b64)
        c = self._md5(f"{datetime_cst}:{random_str}")
        return self._md5(r + c).upper()

    def _compute_mcloud_sign(self, catalog_id: str) -> str:
        datetime_cst = self._format_datetime_cst()
        random_str = self._random_str(16)
        get_disk_body = {
            "catalogID": catalog_id or "/",
            "sortDirection": 1,
            "startNumber": 1,
            "endNumber": 100,
            "filterType": 0,
            "catalogSortType": 0,
            "contentSortType": 0,
            "commonAccountInfo": self._account_payload(),
        }
        sign_hash = self._get_new_sign_hash(get_disk_body, datetime_cst, random_str)
        return f"{datetime_cst},{random_str},{sign_hash}"

    def _normalize_basic_auth(self, value: str) -> str:
        raw = str(value or "").strip()
        if not raw:
            return ""
        return raw if re.match(r"^Basic\s+", raw, flags=re.I) else f"Basic {raw}"

    def _is_basic_auth_str(self, value: str) -> bool:
        raw = str(value or "").strip()
        if not raw:
            return False
        return bool(re.match(r"^Basic\s+", raw, flags=re.I) or re.fullmatch(r"[A-Za-z0-9+/]+=*", raw))

    def _parse_phone_from_authorization(self, value: str) -> str:
        auth = self._normalize_basic_auth(value)
        if not auth:
            return ""
        try:
            raw = re.sub(r"^Basic\s+", "", auth, flags=re.I)
            padded = raw + ("=" * ((4 - len(raw) % 4) % 4))
            decoded = base64.b64decode(padded).decode("utf-8", errors="ignore")
            parts = decoded.split(":")
            if len(parts) >= 2 and re.fullmatch(r"1\d{10}", parts[1] or ""):
                return parts[1]
        except Exception:
            return ""
        return ""

    def _apply_auth_headers(self) -> None:
        auth = self._normalize_basic_auth(self._authorization)
        if auth:
            self._session.headers["Authorization"] = auth
            if not self._phone:
                self._phone = self._parse_phone_from_authorization(auth)
        elif self._cookie_value:
            self._session.headers["Cookie"] = self._cookie_value
        else:
            # 保持空会话，init 时再提示未配置认证信息。
            pass

    def _account_payload(self) -> dict[str, Any]:
        return {"account": self._phone or "", "accountType": 1}

    def _request_json(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        timeout: int | float = 20,
    ) -> Any:
        self._throttle_request()
        resp = self._session.request(
            method=method,
            url=url,
            headers=headers,
            params=params,
            json=json_body,
            timeout=timeout,
        )
        resp.raise_for_status()
        try:
            return resp.json()
        except Exception as exc:
            raise RuntimeError((resp.text or "").strip()[:300] or "响应解析失败") from exc

    def _debug_log_json(self, tag: str, payload: Any) -> None:
        if not self._debug:
            return
        try:
            text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        except Exception:
            text = str(payload)
        logger.warning("[cloud139][raw][%s] %s", tag, text[:12000])

    def _user_njs_post(self, path: str, body: dict[str, Any]) -> Any:
        headers = {
            "caller": "web",
            "x-m4c-caller": "PC",
            "x-m4c-src": "10002",
            "x-inner-ntwk": "2",
            "mcloud-route": "001",
            "mcloud-version": "7.17.2",
            "mcloud-channel": "1000101",
            "mcloud-client": "10701",
            "INNER-HCY-ROUTER-HTTPS": "1",
        }
        payload = self._request_json("POST", f"{self.USER_NJS_URL}{path}", headers=headers, json_body=body)
        code = str((payload or {}).get("code") or "")
        if code not in ("", "0", "0000"):
            raise RuntimeError((payload or {}).get("desc") or (payload or {}).get("message") or f"user-njs 错误: {code}")
        return (payload or {}).get("data") if isinstance(payload, dict) and "data" in payload else payload

    def _share_kd_post(self, path: str, body: dict[str, Any]) -> Any:
        headers = {
            "caller": "web",
            "x-m4c-caller": "PC",
            "mcloud-client": "10701",
            "mcloud-version": "7.17.2",
            "mcloud-channel": "1000101",
        }
        payload = self._request_json("POST", f"{self.SHARE_KD_NJS_URL}{path}", headers=headers, json_body=body)
        code = str((payload or {}).get("code") or "")
        if code not in ("", "0", "0000"):
            raise RuntimeError((payload or {}).get("desc") or (payload or {}).get("message") or f"share 接口错误: {code}")
        return (payload or {}).get("data") if isinstance(payload, dict) and "data" in payload else payload

    def _personal_kd_post(self, path: str, body: dict[str, Any], sign_catalog_id: str = "/") -> Any:
        headers = {
            "caller": "web",
            "mcloud-version": "7.17.2",
            "mcloud-channel": "1000101",
            "mcloud-client": "10701",
            "mcloud-route": "001",
            "mcloud-sign": self._compute_mcloud_sign(sign_catalog_id or "/"),
            "INNER-HCY-ROUTER-HTTPS": "1",
            "x-m4c-caller": "PC",
            "x-m4c-src": "10002",
            "x-inner-ntwk": "2",
            "x-yun-channel-source": "10000034",
            "x-huawei-channelSrc": "10000034",
            "x-yun-svc-type": "1",
            "x-SvcType": "1",
            "x-yun-module-type": "100",
            "x-yun-app-channel": "10000034",
            "x-yun-api-version": "v1",
            "x-yun-client-info": "||9|7.17.2|chrome|143.0.0.0|python-port||linux||zh-CN|||",
            "X-Deviceinfo": "||9|7.17.2|chrome|143.0.0.0|python-port||linux||zh-CN|||",
            "CMS-DEVICE": "default",
        }
        payload = self._request_json("POST", f"{self.PERSONAL_KD_NJS_URL}{path}", headers=headers, json_body=body)
        code = str((payload or {}).get("code") or "")
        success = bool((payload or {}).get("success"))
        if not success and code not in ("", "0", "0000"):
            raise RuntimeError((payload or {}).get("desc") or (payload or {}).get("message") or f"hcy 接口错误: {code}")
        return (payload or {}).get("data") if isinstance(payload, dict) and "data" in payload else payload

    def _get_user_info(self) -> dict[str, Any]:
        if self._user_cache is not None:
            return dict(self._user_cache)
        data = self._user_njs_post("/user/getUser", {})
        if not isinstance(data, dict):
            raise RuntimeError("获取 139 用户信息失败")
        self._user_cache = dict(data)
        return dict(data)

    def _get_disk_info(self) -> dict[str, Any]:
        user_info = self._get_user_info()
        user_domain_id = str(user_info.get("userDomainId") or "").strip()
        if not user_domain_id:
            return {}
        data = self._user_njs_post("/user/disk/getPersonalDiskInfo", {"userDomainId": user_domain_id})
        return data if isinstance(data, dict) else {}

    def init(self) -> Any:
        if not (self._authorization or self._cookie_value):
            return False
        try:
            info = self._get_user_info()
        except Exception as exc:
            logger.warning("[cloud139] init failed: %s", exc)
            self.is_active = False
            return False
        self.is_active = True
        self.nickname = str(info.get("nickName") or info.get("nickname") or self._phone or self._account_name)
        return info

    def get_account_config(self) -> Dict[str, Any]:
        try:
            info = self._get_user_info()
            disk_info = self._get_disk_info()
        except Exception:
            info = {}
            disk_info = {}
        total_mb = int(disk_info.get("diskSize") or 0) if str(disk_info.get("diskSize") or "").isdigit() else 0
        free_mb = int(disk_info.get("freeDiskSize") or 0) if str(disk_info.get("freeDiskSize") or "").isdigit() else 0
        mb = 1024 * 1024
        used_space = max(total_mb - free_mb, 0) * mb if total_mb else None
        total_space = total_mb * mb if total_mb else None
        nickname = str(info.get("nickName") or info.get("nickname") or self.nickname or self._phone or self._account_name)
        self.nickname = nickname
        return {
            "drive_type": self.DRIVE_TYPE,
            "drive_name": self.DRIVE_NAME,
            "nickname": nickname,
            "username": str(info.get("account") or self._phone or nickname),
            "used_space": used_space,
            "total_space": total_space,
            "raw": {
                "user_info": info or None,
                "disk_info": disk_info or None,
            },
        }

    def _parse_timestamp(self, value: Any) -> int:
        if value is None:
            return 0
        if isinstance(value, (int, float)):
            return int(value)
        text = str(value).strip()
        if not text:
            return 0
        if text.isdigit():
            if len(text) == 14:
                try:
                    return int(datetime.strptime(text, "%Y%m%d%H%M%S").timestamp())
                except Exception:
                    return 0
            if len(text) == 8:
                try:
                    return int(datetime.strptime(text, "%Y%m%d").timestamp())
                except Exception:
                    return 0
            return int(text)
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
            try:
                return int(datetime.strptime(text[:19], fmt).timestamp())
            except Exception:
                continue
        return 0

    def extract_url(self, url: str) -> Tuple[Optional[str], str, Any, List]:
        raw = str(url or "").strip()
        if not raw:
            return None, "", "root", []

        text = raw.replace("？", "?").replace("（", "(").replace("）", ")")
        compact = re.sub(r"\s+", "", text)
        try:
            compact = unquote(compact)
        except Exception:
            pass

        passwd = ""
        pwd_patterns = [
            r"passwd=([a-zA-Z0-9]{4,8})",
            r"pwd=([a-zA-Z0-9]{4,8})",
            r"密码[：:]\s*([a-zA-Z0-9]{4,8})",
            r"提取码[：:]\s*([a-zA-Z0-9]{4,8})",
            r"\(([a-zA-Z0-9]{4,8})\)",
        ]
        for pat in pwd_patterns:
            match = re.search(pat, compact, flags=re.I)
            if match:
                passwd = str(match.group(1) or "").strip()
                break

        if re.fullmatch(r"[a-zA-Z0-9_-]{4,64}", raw) and "/" not in raw:
            return raw, passwd, "root", []

        extracted_url = ""
        direct_match = re.search(r"(https?://(?:yun|caiyun)\.139\.com[^\s]*)", text, flags=re.I)
        if direct_match:
            extracted_url = direct_match.group(1)
        elif re.search(r"(?:yun|caiyun)\.139\.com", text, flags=re.I):
            extracted_url = "https://" + re.search(r"((?:yun|caiyun)\.139\.com[^\s]*)", text, flags=re.I).group(1)
        else:
            extracted_url = text

        try:
            parsed = urlparse(extracted_url)
        except Exception:
            return None, passwd, "root", []

        if not parsed.scheme and parsed.path:
            parsed = urlparse("https://" + extracted_url.lstrip("/"))

        pdir_fid = "root"
        frag = str(parsed.fragment or "").strip()
        frag_path, frag_query = (frag.split("?", 1) + [""])[:2] if frag else ("", "")
        frag_qs = parse_qs(frag_query or "")
        generic_share_fid = ""
        if frag_path:
            m_generic = re.search(r"(?:^|/)list/share/([^/?#]+)", frag_path)
            if m_generic:
                generic_share_fid = str(m_generic.group(1) or "").strip()
                if generic_share_fid:
                    pdir_fid = generic_share_fid

        query = parse_qs(parsed.query or "")
        fid_from_query = str((query.get("fid") or [""])[0] or "").strip()
        if fid_from_query and fid_from_query not in ("0", "root"):
            pdir_fid = fid_from_query
        fid_from_frag = str((frag_qs.get("fid") or [""])[0] or "").strip()
        if fid_from_frag and fid_from_frag not in ("0", "root"):
            pdir_fid = fid_from_frag

        link_id = (query.get("linkID") or query.get("linkId") or [""])[0]
        if not link_id and parsed.query and re.fullmatch(r"[a-zA-Z0-9_-]{4,64}", parsed.query):
            link_id = parsed.query
        if not link_id and parsed.fragment and not generic_share_fid:
            link_id = (frag_qs.get("linkID") or frag_qs.get("linkId") or [""])[0]
            if not link_id:
                frag_parts = re.split(r"[/?]", frag_path)
                candidate = frag_parts[-1] if frag_parts else ""
                if re.fullmatch(r"[a-zA-Z0-9_-]{4,64}", candidate or ""):
                    link_id = candidate
        if not link_id:
            match = re.search(r"linkID=([a-zA-Z0-9_-]{4,64})", compact, flags=re.I)
            if match:
                link_id = match.group(1)

        return (link_id or None), passwd, pdir_fid, []

    def _get_share_info(self, link_id: str, passwd: str = "", pdir_fid: str = "root", start_num: int = 1, end_num: int = 200) -> dict[str, Any] | None:
        payload = {
            "getOutLinkInfoReq": {
                "account": self._phone or "",
                "linkID": link_id,
                "passwd": passwd or "",
                "pCaID": pdir_fid or "root",
                "caSrt": 0,
                "coSrt": 0,
                "srtDr": 1,
                "bNum": start_num,
                "eNum": end_num,
            }
        }
        self._debug_log_json("share.request", payload)
        data = self._share_kd_post("/yun-share/richlifeApp/devapp/IOutLink/getOutLinkInfoV6", payload)
        self._debug_log_json("share.response", data)
        return data if isinstance(data, dict) else None

    def get_stoken(self, pwd_id: str, passcode: str = "") -> Dict:
        if not pwd_id:
            return {"status": 400, "message": "分享链接无效", "data": {}}
        try:
            info = self._get_share_info(pwd_id, passcode or "", "root", 1, 1)
        except Exception as exc:
            return {"status": 500, "message": str(exc), "data": {}}
        if not info:
            return {"status": 404, "message": "分享不存在或认证失败", "data": {}}
        stoken = json.dumps({"linkID": pwd_id, "passwd": passcode or ""}, ensure_ascii=False)
        return {"status": 200, "message": "success", "data": {"stoken": stoken}}

    def _parse_share_token(self, stoken: str) -> dict[str, Any]:
        raw = str(stoken or "").strip()
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {"passwd": raw}

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
        token = self._parse_share_token(stoken)
        passwd = str(token.get("passwd") or "")
        pdir = str(pdir_fid or "root")
        try:
            info = self._get_share_info(pwd_id, passwd, pdir, 1, 200)
        except Exception as exc:
            return {"code": 1, "message": str(exc), "data": {"list": []}}
        if not info:
            return {"code": 1, "message": "获取分享目录失败", "data": {"list": []}}

        data_list: list[dict[str, Any]] = []
        for folder in info.get("caLst") or []:
            fid = str(folder.get("catalogID") or folder.get("caID") or "")
            name = str(folder.get("catalogName") or folder.get("caName") or "")
            if not fid or not name:
                continue
            share_token = json.dumps(
                {
                    "path": str(folder.get("path") or ""),
                    "pid": str(pdir or "root"),
                    "dir": 1,
                    "name": name,
                },
                ensure_ascii=False,
            )
            data_list.append(
                {
                    "fid": fid,
                    "file_name": name,
                    "dir": True,
                    "size": 0,
                    "updated_at": self._parse_timestamp(
                        folder.get("udTime") or folder.get("updateTime") or folder.get("lastUpdateTime")
                    ),
                    "share_fid_token": share_token,
                }
            )
        for file_item in info.get("coLst") or []:
            fid = str(file_item.get("contentID") or file_item.get("coID") or "")
            name = str(file_item.get("contentName") or file_item.get("coName") or "")
            if not fid or not name:
                continue
            share_token = json.dumps(
                {
                    "path": str(file_item.get("path") or ""),
                    "pid": str(pdir or "root"),
                    "dir": 0,
                    "name": name,
                },
                ensure_ascii=False,
            )
            size = file_item.get("coSize") or file_item.get("contentSize") or file_item.get("size") or 0
            try:
                size = int(size)
            except Exception:
                size = 0
            data_list.append(
                {
                    "fid": fid,
                    "file_name": name,
                    "dir": False,
                    "size": size,
                    "updated_at": self._parse_timestamp(
                        file_item.get("udTime") or file_item.get("updateTime") or file_item.get("updatedAt")
                    ),
                    "share_fid_token": share_token,
                }
            )
        return {"code": 0, "message": "success", "data": {"list": data_list, "full_path": []}}

    def _list_disk_dir(self, parent_file_id: str = "/", *, cursor: str | None = None) -> dict[str, Any]:
        body = {
            "pageInfo": {"pageSize": 100, "pageCursor": cursor},
            "orderBy": "updated_at",
            "orderDirection": "DESC",
            "parentFileId": parent_file_id or "/",
            "imageThumbnailStyleList": ["Small", "Large"],
        }
        self._debug_log_json("disk.request", body)
        data = self._personal_kd_post("/hcy/file/list", body, parent_file_id or "/")
        self._debug_log_json("disk.response", data)
        if not isinstance(data, dict):
            raise RuntimeError("获取目录列表失败")
        return data

    def ls_dir(self, pdir_fid: str, max_items: int = 0, **kwargs) -> Dict:
        try:
            parent_file_id = "/" if str(pdir_fid or "") in ("", "0", "/", "root") else str(pdir_fid)
            items: list[dict[str, Any]] = []
            cursor = None
            while True:
                payload = self._list_disk_dir(parent_file_id, cursor=cursor)
                batch = payload.get("items") or payload.get("fileList") or []
                for item in batch:
                    is_dir = str(item.get("fileType") or item.get("category") or "").lower() == "folder"
                    size = item.get("size")
                    try:
                        size = int(size) if size is not None else 0
                    except Exception:
                        size = 0
                    items.append(
                        {
                            "fid": str(item.get("fileId") or item.get("id") or ""),
                            "file_name": str(item.get("name") or item.get("fileName") or ""),
                            "dir": is_dir,
                            "size": size,
                            "updated_at": self._parse_timestamp(item.get("updatedAt") or item.get("updateTime")),
                            "share_fid_token": "",
                        }
                    )
                    if max_items > 0 and len(items) >= max_items:
                        return {"code": 0, "message": "success", "data": {"list": items[:max_items]}}
                cursor = payload.get("nextPageCursor") or ((payload.get("pageInfo") or {}).get("nextPageCursor"))
                if not cursor or not batch:
                    break
            return {"code": 0, "message": "success", "data": {"list": items}}
        except Exception as exc:
            return {"code": 1, "message": str(exc), "data": {"list": []}}

    def _find_child_folder(self, parent_id: str, folder_name: str) -> str:
        listing = self.ls_dir(parent_id, max_items=0)
        for item in (((listing or {}).get("data") or {}).get("list") or []):
            if not item.get("dir"):
                continue
            if str(item.get("file_name") or "") == str(folder_name):
                return str(item.get("fid") or "")
        return ""

    def mkdir(self, dir_path: str) -> Dict:
        try:
            normalized = re.sub(r"/{2,}", "/", f"/{str(dir_path or '').strip()}").rstrip("/")
            if normalized in ("", "/"):
                return {"code": 0, "message": "success", "data": {"fid": "0"}}
            parent_id = "/"
            for name in [seg for seg in normalized.split("/") if seg]:
                exists = self._find_child_folder(parent_id, name)
                if exists:
                    parent_id = exists
                    continue
                body = {"parentFileId": parent_id or "/", "name": name, "type": "folder"}
                data = self._personal_kd_post("/hcy/file/create", body, parent_id or "/")
                new_fid = str((data or {}).get("fileId") or (data or {}).get("id") or "")
                if not new_fid:
                    raise RuntimeError("创建目录失败")
                parent_id = new_fid
            return {"code": 0, "message": "success", "data": {"fid": str(parent_id if parent_id != "/" else "0")}}
        except Exception as exc:
            return {"code": 1, "message": str(exc), "data": {}}

    def rename(self, fid: str, file_name: str) -> Dict:
        try:
            data = self._personal_kd_post("/hcy/file/update", {"fileId": str(fid), "name": str(file_name)}, "/")
            return {"code": 0, "message": "success", "data": data or {}}
        except Exception as exc:
            return {"code": 1, "message": str(exc), "data": {}}

    def delete(self, filelist: List[str]) -> Dict:
        try:
            if not filelist:
                return {"code": 0, "message": "success", "data": {}}
            data = self._personal_kd_post("/hcy/recyclebin/batchTrash", {"fileIds": [str(x) for x in filelist if str(x).strip()]}, "/")
            task_id = str((data or {}).get("taskId") or (data or {}).get("taskID") or "")
            if task_id:
                for _ in range(10):
                    time.sleep(1)
                    task = self._personal_kd_post("/hcy/task/get", {"taskId": task_id}, "/")
                    status = str((task or {}).get("status") or (task or {}).get("taskStatus") or "")
                    if status in ("success", "2"):
                        break
                    if status in ("failed", "3"):
                        raise RuntimeError("删除任务失败")
            return {"code": 0, "message": "success", "data": {}}
        except Exception as exc:
            return {"code": 1, "message": str(exc), "data": {}}

    def get_fids(self, file_paths: List[str]) -> List[Dict]:
        result: list[dict[str, str]] = []
        for path in file_paths or []:
            normalized = re.sub(r"/{2,}", "/", f"/{str(path or '').strip()}").rstrip("/")
            if normalized in ("", "/"):
                result.append({"file_path": "/", "fid": "0"})
                continue
            parent_id = "/"
            ok = True
            for name in [seg for seg in normalized.split("/") if seg]:
                found = self._find_child_folder(parent_id, name)
                if not found:
                    ok = False
                    break
                parent_id = found
            if ok:
                result.append({"file_path": normalized, "fid": str(parent_id if parent_id != "/" else "0")})
        return result

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
            if not fid_list:
                return {"code": 0, "message": "success", "data": {"task_id": "", "save_as_top_fids": [], "_sync": True}}

            token = self._parse_share_token(stoken)
            passwd = str(token.get("passwd") or "")
            co_path_list: list[str] = []
            ca_path_list: list[str] = []
            for idx, fid in enumerate(fid_list):
                fid_token = str(fid_token_list[idx] or "") if idx < len(fid_token_list or []) else ""
                try:
                    payload = json.loads(fid_token) if fid_token else {}
                except Exception:
                    payload = {}
                path = str(payload.get("path") or fid or "").strip()
                if not path:
                    continue
                if int(payload.get("dir") or 0):
                    ca_path_list.append(path)
                else:
                    co_path_list.append(path)
            need_password = bool(passwd)
            target_catalog_id = "/" if str(to_pdir_fid or "") in ("", "0", "/", "root") else str(to_pdir_fid)
            data = self._share_kd_post(
                "/yun-share/richlifeApp/devapp/IBatchOprTask/createOuterLinkBatchOprTask",
                {
                    "createOuterLinkBatchOprTaskReq": {
                        "msisdn": self._phone or "",
                        "ownerAccount": "",
                        "taskType": 1,
                        "linkID": str(pwd_id),
                        "needPassword": need_password,
                        "taskInfo": {
                            "linkID": str(pwd_id),
                            "needPassword": need_password,
                            "contentInfoList": co_path_list,
                            "catalogInfoList": ca_path_list,
                            "newCatalogID": target_catalog_id,
                        },
                    }
                },
            )
            task_id = str((data or {}).get("taskID") or (data or {}).get("taskId") or "")

            before_names: set[str] = set()
            if file_names:
                before = self.ls_dir(target_catalog_id, max_items=1000)
                for item in (((before or {}).get("data") or {}).get("list") or []):
                    name = str(item.get("file_name") or "")
                    if name:
                        before_names.add(name)

            aligned_fids: list[str] = []
            if file_names:
                deadline = time.time() + 60
                while time.time() < deadline:
                    listing = self.ls_dir(target_catalog_id, max_items=1000)
                    if (listing or {}).get("code") != 0:
                        time.sleep(1.5)
                        continue
                    new_map: dict[str, str] = {}
                    for item in (((listing or {}).get("data") or {}).get("list") or []):
                        fid = str(item.get("fid") or "")
                        name = str(item.get("file_name") or "")
                        if not fid or not name or name in before_names:
                            continue
                        if name not in new_map:
                            new_map[name] = fid
                    aligned_fids = [new_map.get(str(name or ""), "") for name in file_names]
                    if any(aligned_fids):
                        break
                    time.sleep(1.5)

            return {
                "code": 0,
                "message": "success",
                "data": {
                    "task_id": task_id,
                    "save_as_top_fids": [x for x in aligned_fids if x],
                    "_sync": True,
                },
            }
        except Exception as exc:
            return {"code": 1, "message": str(exc), "data": {}}

    def query_task(self, task_id: str) -> Dict:
        if not str(task_id or "").strip():
            return {"code": 0, "message": "ok", "data": {"status": 2, "save_as": {"save_as_top_fids": []}}}
        try:
            payload = self._personal_kd_post("/hcy/task/get", {"taskId": str(task_id)}, "/")
        except Exception:
            payload = {}
        status = str((payload or {}).get("status") or (payload or {}).get("taskStatus") or "2")
        if status in ("success", "2"):
            normalized_status: int | str = 2
        elif status in ("failed", "3"):
            normalized_status = 3
        else:
            normalized_status = status or 1
        return {
            "code": 0 if normalized_status != 3 else 1,
            "message": "ok" if normalized_status != 3 else str((payload or {}).get("message") or "任务失败"),
            "data": {
                "status": normalized_status,
                "save_as": {"save_as_top_fids": []},
            },
        }

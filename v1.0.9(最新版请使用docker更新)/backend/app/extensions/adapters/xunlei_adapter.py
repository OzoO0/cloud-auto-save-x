# -*- coding: utf-8 -*-
"""
迅雷网盘适配器
基于 xinyue-search 项目的 API 实现方式
使用 requests 直接调用迅雷网盘 API
"""
import re
import json
import time
import logging
import hashlib
import threading
from typing import Dict, List, Tuple, Optional, Any
from datetime import datetime

import requests

from app.extensions.adapters.base_adapter import BaseCloudDriveAdapter


logger = logging.getLogger(__name__)


# ==================== 常量定义 ====================
API_BASE = "https://api-pan.xunlei.com"
AUTH_BASE = "https://xluser-ssl.xunlei.com"

CLIENT_ID = "Xqp0kJBXWhwaTpB6"

XUNLEI_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36"
)

XUNLEI_HEADERS = {
    "Accept": "*/*",
    "Content-Type": "application/json",
    "Origin": "https://pan.xunlei.com",
    "Referer": "https://pan.xunlei.com/",
    "User-Agent": XUNLEI_UA,
    "x-client-id": CLIENT_ID,
}

# 固定设备 ID 和 captcha 签名（三者配套，不可单独修改）
DEVICE_ID = "925b7631473a13716b791d7f28289cad"
CAPTCHA_SIGN = "1.fe2108ad808a74c9ac0243309242726c"
CAPTCHA_TIMESTAMP = "1645241033384"

# 文件列表过滤条件
FILE_LIST_FILTERS = json.dumps({
    "phase": {"eq": "PHASE_TYPE_COMPLETE"},
    "trashed": {"eq": False},
})

# 错误码映射
ERROR_CODES = {
    "ALREADY_EXISTED": "文件已存在",
    "FORBIDDEN": "无权限操作",
    "NOT_FOUND": "资源不存在",
    "INVALID_ARGUMENT": "参数错误",
    "UNAUTHENTICATED": "认证失败，请重新登录",
    "PERMISSION_DENIED": "权限不足",
    "RESOURCE_EXHAUSTED": "配额已用尽",
    "SENSITIVE_RESOURCE": "该分享内容可能涉及违规信息，无法访问",
    "WRONG_PASS_CODE": "提取码错误",
}

# 全局配置保存函数
_global_config_saver = None


def _config_saver_factory(config_path: str):
    """创建配置保存函数"""
    def save_config(new_refresh_token: str, account_name: str = None):
        """保存新的 refresh_token 到配置文件"""
        try:
            from quark_auto_save import Config
            config = Config.read_json(config_path)
            if not config:
                logger.warning("[Xunlei] 无法读取配置文件")
                return False

            accounts = config.get("accounts", [])
            updated = False
            current_time = time.time()
            for acc in accounts:
                if acc.get("drive_type") == "xunlei":
                    if account_name and acc.get("name") != account_name:
                        continue
                    acc["cookie"] = new_refresh_token
                    acc["_token_updated_at"] = current_time
                    updated = True
                    logger.debug(f"[Xunlei] 已更新账户 {acc.get('name', 'unknown')} 的 refresh_token (时间戳: {current_time})")
                    if account_name:
                        break

            if updated:
                Config.write_json(config_path, config)
                logger.debug("[Xunlei] refresh_token 已保存到配置文件")
                return True
            else:
                logger.warning("[Xunlei] 未找到需要更新的迅雷网盘账户")
                return False
        except Exception as e:
            logger.error(f"[Xunlei] 保存 refresh_token 失败: {e}")
            return False

    return save_config


def set_config_saver(config_path: str):
    """设置配置保存函数"""
    global _global_config_saver
    if callable(config_path):
        _global_config_saver = config_path
    else:
        _global_config_saver = _config_saver_factory(config_path)


class XunleiAdapter(BaseCloudDriveAdapter):
    """迅雷网盘适配器"""

    DRIVE_TYPE = "xunlei"
    DRIVE_NAME = "迅雷网盘"
    CONFIG_FORMAT = "raw"
    default_config = {
        "refresh_token": "",
    }
    config_fields = [
        {
            "key": "refresh_token",
            "label": "Refresh Token",
            "description": "迅雷网盘刷新令牌；系统内部仍兼容存入原有 cookie 字段。",
            "input_type": "textarea",
            "required": True,
            "secret": True,
            "placeholder": "refresh_token",
        }
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
        self._session: requests.Session = requests.Session()
        self._session.headers.update(XUNLEI_HEADERS)

        # refresh_token 存储在 cookie 字段中
        self._refresh_token: str = str(self.config.get("refresh_token") or self.cookie or "").strip()

        # 账户名称（用于多账户配置保存）
        self._account_name: str = account_name

        # 双 Token
        self._access_token: str = ""
        self._access_token_expire: float = 0
        self._captcha_token: str = ""
        self._captcha_token_expire: float = 0

        # token 更新时间戳（用于防回滚）
        self._token_updated_at: float = time.time()

        # 设备 ID（使用固定值，与 captcha_sign 配套）
        self._device_id: str = DEVICE_ID

        # 用户信息
        self._user_id: str = ""
        self._user_name: str = ""

        # 线程锁
        self._token_lock = threading.Lock()

    # ==================== Token 管理 ====================

    def _refresh_access_token(self) -> bool:
        """刷新 access_token"""
        if not self._refresh_token:
            logger.error("[Xunlei] 没有 refresh_token，无法刷新")
            return False

        try:
            url = f"{AUTH_BASE}/v1/auth/token"
            data = {
                "client_id": CLIENT_ID,
                "grant_type": "refresh_token",
                "refresh_token": self._refresh_token,
            }
            # Token 刷新请求不需要 Authorization 和 captcha
            headers = {
                "Content-Type": "application/json",
                "User-Agent": XUNLEI_UA,
            }

            resp = requests.post(url, json=data, headers=headers, timeout=30)
            result = resp.json()

            if "access_token" not in result:
                error = result.get("error_description", result.get("error", "未知错误"))
                logger.error(f"[Xunlei] 刷新 access_token 失败: {error}")
                return False

            self._access_token = result["access_token"]
            self._access_token_expire = time.time() + int(result.get("expires_in", 7200)) - 120

            # 更新 refresh_token
            new_refresh = result.get("refresh_token", "")
            if new_refresh and new_refresh != self._refresh_token:
                old_token = self._refresh_token
                self._refresh_token = new_refresh
                self._save_refresh_token()
                logger.debug("[Xunlei] refresh_token 已更新")

            # 提取用户信息
            self._user_id = str(result.get("user_id", ""))
            self._user_name = result.get("user_name", "")

            # 更新 session headers
            self._session.headers["Authorization"] = f"Bearer {self._access_token}"
            self._session.headers["x-device-id"] = self._device_id

            logger.debug(f"[Xunlei] access_token 刷新成功，用户: {self._user_name or self._user_id}")
            return True

        except Exception as e:
            logger.error(f"[Xunlei] 刷新 access_token 异常: {e}")
            return False

    def _refresh_captcha_token(self) -> bool:
        """刷新 captcha_token"""
        try:
            url = f"{AUTH_BASE}/v1/shield/captcha/init"
            data = {
                "client_id": CLIENT_ID,
                "action": "get:/drive/v1/share",
                "device_id": self._device_id,
                "meta": {
                    "username": "",
                    "phone_number": "",
                    "email": "",
                    "package_name": "pan.xunlei.com",
                    "client_version": "1.45.0",
                    "captcha_sign": CAPTCHA_SIGN,
                    "timestamp": CAPTCHA_TIMESTAMP,
                    "user_id": self._user_id or "0",
                },
            }
            headers = {
                "Content-Type": "application/json",
                "User-Agent": XUNLEI_UA,
            }

            resp = requests.post(url, json=data, headers=headers, timeout=30)
            result = resp.json()

            if "captcha_token" not in result:
                error = result.get("error_description", result.get("error", "未知错误"))
                logger.error(f"[Xunlei] 获取 captcha_token 失败: {error}")
                return False

            self._captcha_token = result["captcha_token"]
            self._captcha_token_expire = time.time() + int(result.get("expires_in", 300)) - 10

            # 更新 session headers
            self._session.headers["x-captcha-token"] = self._captcha_token

            logger.debug("[Xunlei] captcha_token 获取成功")
            return True

        except Exception as e:
            logger.error(f"[Xunlei] 获取 captcha_token 异常: {e}")
            return False

    def _ensure_tokens_valid(self) -> bool:
        """确保双 Token 都有效"""
        access_ok = self._access_token and time.time() < self._access_token_expire
        captcha_ok = self._captcha_token and time.time() < self._captcha_token_expire

        if access_ok and captcha_ok:
            return True

        with self._token_lock:
            # 双重检查
            access_ok = self._access_token and time.time() < self._access_token_expire
            captcha_ok = self._captcha_token and time.time() < self._captcha_token_expire

            if not access_ok:
                if not self._refresh_access_token():
                    return False

            if not captcha_ok:
                if not self._refresh_captcha_token():
                    return False

        return True

    def _save_refresh_token(self):
        """保存新的 refresh_token 到配置文件"""
        global _global_config_saver
        if _global_config_saver:
            _global_config_saver(self._refresh_token, self._account_name)
            self._token_updated_at = time.time()

    # ==================== 请求方法 ====================

    def _request(self, method: str, url: str, body: Dict = None, params: Dict = None) -> Dict:
        """发送 HTTP 请求并返回 JSON"""
        if not self._ensure_tokens_valid():
            return {"error": "TokenInvalid", "error_description": "Token 无效"}
        self._throttle_request()
        
        try:
            if method.upper() == "GET":
                resp = self._session.get(url, params=params, timeout=30)
            elif method.upper() == "PATCH":
                resp = self._session.patch(url, json=body, params=params, timeout=30)
            else:
                resp = self._session.post(url, json=body, params=params, timeout=30)

            return resp.json()

        except Exception as e:
            logger.error(f"[Xunlei] HTTP 请求失败: {e}")
            return {"error": "RequestError", "error_description": str(e)}

    def _get_error_message(self, result: Dict) -> str:
        """从响应中提取错误信息"""
        if "error_description" in result:
            return result["error_description"]
        if "error" in result:
            code = result["error"]
            return ERROR_CODES.get(code, code)
        if "share_status_text" in result:
            return result["share_status_text"]
        return "未知错误"

    def _has_error(self, result: Dict) -> bool:
        """检查响应是否包含错误"""
        return "error" in result or "error_code" in result

    # ==================== 数据格式转换 ====================

    def _convert_xunlei_item(self, item: Dict) -> Dict:
        """将迅雷文件项转换为统一格式"""
        is_folder = item.get("kind") == "drive#folder"
        file_id = item.get("id", "")
        size = int(item.get("size", 0) or 0)

        # 时间解析
        updated_at = 0
        time_str = item.get("modified_time") or item.get("created_time", "")
        if time_str:
            try:
                dt = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
                updated_at = int(dt.timestamp() * 1000)
            except Exception:
                pass

        return {
            "fid": file_id,
            "file_name": item.get("name", ""),
            "file_type": 0 if is_folder else 1,
            "dir": is_folder,
            "size": size,
            "updated_at": updated_at,
            "share_fid_token": file_id,
        }

    # ==================== 公共接口实现 ====================

    def init(self) -> Any:
        """初始化账户，验证 refresh_token 有效性"""
        if not self._refresh_token:
            logger.error("[Xunlei] 未配置 refresh_token")
            return False

        if not self._refresh_access_token():
            return False

        if not self._refresh_captcha_token():
            logger.warning("[Xunlei] captcha_token 获取失败，部分功能可能受限")

        self.is_active = True
        self.nickname = self._user_name or f"迅雷用户{self.index}"

        return {
            "user_id": self._user_id,
            "user_name": self._user_name,
            "nickname": self.nickname,
        }

    def get_account_info(self) -> Any:
        """获取账户信息"""
        return self.init()

    def _get_user_me(self) -> Dict[str, Any]:
        url = f"{AUTH_BASE}/v1/user/me"
        result = self._request("GET", url)
        if not isinstance(result, dict):
            return {}
        if self._has_error(result):
            return {}
        return result

    def _get_drive_about(self) -> Dict[str, Any]:
        url = f"{API_BASE}/drive/v1/about"
        result = self._request("GET", url)
        if not isinstance(result, dict):
            return {}
        if self._has_error(result):
            return {}
        return result

    def get_account_config(self) -> Dict[str, Any]:
        """获取迅雷账户配置/容量信息"""
        user_info: Dict[str, Any] = {}
        about_info: Dict[str, Any] = {}

        try:
            if self._ensure_tokens_valid():
                user_info = self._get_user_me() or {}
                about_info = self._get_drive_about() or {}
        except Exception:
            user_info = {}
            about_info = {}

        nickname = (
            user_info.get("name")
            or self._user_name
            or self.nickname
            or f"迅雷用户{self.index}"
        )
        if nickname:
            self.nickname = nickname

        username = (
            user_info.get("phone_number")
            or user_info.get("sub")
            or user_info.get("id")
            or self._user_id
            or nickname
        )

        quota = about_info.get("quota") if isinstance(about_info, dict) else None
        used_space = None
        total_space = None
        if isinstance(quota, dict):
            try:
                if quota.get("usage") is not None:
                    used_space = int(quota.get("usage") or 0)
            except Exception:
                used_space = None
            try:
                if quota.get("limit") is not None:
                    total_space = int(quota.get("limit") or 0)
            except Exception:
                total_space = None

        member_type = ""
        member_status: Dict[str, Any] = {}
        try:
            vip_info = user_info.get("vip_info") if isinstance(user_info, dict) else None
            vip_flag = False
            expire_time = ""
            level = ""
            if isinstance(vip_info, list) and vip_info:
                for it in vip_info:
                    if not isinstance(it, dict):
                        continue
                    if str(it.get("is_vip") or "") == "1":
                        vip_flag = True
                        expire_time = str(it.get("expire_time") or "")
                        level = str(it.get("level") or "")
                        break
            if vip_flag:
                member_type = "VIP"
                member_status = {"is_vip": True, "level": level or None, "expire_time": expire_time or None}
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
                "account_info": user_info or None,
                "member_info": {
                    "about": about_info or None,
                },
            },
        }

    def get_stoken(self, pwd_id: str, passcode: str = "") -> Dict:
        """获取分享令牌"""
        try:
            params = {
                "share_id": pwd_id,
                "pass_code": passcode,
                "limit": 100,
                "pass_code_token": "",
                "page_token": "",
                "thumbnail_size": "SIZE_SMALL",
            }

            result = self._request("GET", f"{API_BASE}/drive/v1/share", params=params)

            if self._has_error(result):
                msg = self._get_error_message(result)
                return {"status": 400, "code": 1, "message": msg}

            # 检查分享状态
            share_status = result.get("share_status", "")
            if share_status and share_status != "OK":
                status_text = result.get("share_status_text", "")
                if share_status == "SENSITIVE_RESOURCE":
                    status_text = ERROR_CODES.get("SENSITIVE_RESOURCE")
                return {
                    "status": 400,
                    "code": 1,
                    "message": status_text or "分享已失效",
                }

            pass_code_token = result.get("pass_code_token", "")

            return {
                "status": 200,
                "code": 0,
                "data": {
                    "stoken": pass_code_token,
                    "share_id": pwd_id,
                    "share_info": result,
                },
                "message": "success",
            }
        except Exception as e:
            logger.error(f"[Xunlei] 获取分享令牌失败: {e}")
            return {"status": 500, "code": 1, "message": str(e)}

    def get_detail(
        self,
        pwd_id: str,
        stoken: str,
        pdir_fid: str,
        _fetch_share: int = 0,
        fetch_share_full_path: int = 0,
    ) -> Dict:
        """获取分享文件详情列表"""
        try:
            file_list = []
            page_token = ""

            while True:
                params = {
                    "share_id": pwd_id,
                    "pass_code_token": stoken,
                    "limit": 100,
                    "page_token": page_token,
                    "thumbnail_size": "SIZE_SMALL",
                }

                # 如果指定了子目录
                if pdir_fid and pdir_fid != "0":
                    params["parent_id"] = pdir_fid
                    url = f"{API_BASE}/drive/v1/share/detail"
                else:
                    url = f"{API_BASE}/drive/v1/share"

                result = self._request("GET", url, params=params)

                if self._has_error(result):
                    msg = self._get_error_message(result)
                    return {"code": 1, "message": msg, "data": {"list": []}}

                files = result.get("files", [])
                for item in files:
                    file_list.append(self._convert_xunlei_item(item))

                page_token = result.get("next_page_token", "")
                if not page_token:
                    break

            return {
                "code": 0,
                "message": "success",
                "data": {"list": file_list},
                "metadata": {"_total": len(file_list)},
            }

        except Exception as e:
            logger.error(f"[Xunlei] 获取分享详情失败: {e}")
            return {"code": 1, "message": str(e), "data": {"list": []}}

    def ls_dir(self, pdir_fid: str, max_items: int = 0, **kwargs) -> Dict:
        """列出用户网盘目录内容"""
        if not self._ensure_tokens_valid():
            return {"code": 1, "message": "Token 无效", "data": {"list": []}}

        try:
            file_list = []
            page_token = ""
            
            # 判断是否是根目录
            is_root = not pdir_fid or str(pdir_fid) == "0" or str(pdir_fid) == ""

            while True:
                params = {
                    "filters": FILE_LIST_FILTERS,
                    "with_audit": "true",
                    "thumbnail_size": "SIZE_SMALL",
                    "limit": 100,
                }
                
                # 只有访问子目录时才传递 parent_id 参数
                # 根目录时不传递 parent_id 参数
                if not is_root:
                    params["parent_id"] = str(pdir_fid)
                
                if page_token:
                    params["page_token"] = page_token

                result = self._request("GET", f"{API_BASE}/drive/v1/files", params=params)

                if self._has_error(result):
                    msg = self._get_error_message(result)
                    return {"code": 1, "message": msg, "data": {"list": []}}

                files = result.get("files", [])
                for item in files:
                    file_list.append(self._convert_xunlei_item(item))

                # max_items 限量：达到上限后提前终止分页
                if max_items > 0 and len(file_list) >= max_items:
                    file_list = file_list[:max_items]
                    break

                page_token = result.get("next_page_token", "")
                if not page_token:
                    break

            return {
                "code": 0,
                "message": "success",
                "data": {"list": file_list},
                "metadata": {"_total": len(file_list)},
            }

        except Exception as e:
            logger.error(f"[Xunlei] 列出目录失败: {e}")
            return {"code": 1, "message": str(e), "data": {"list": []}}

    def save_file(
        self,
        fid_list: List[str],
        fid_token_list: List[str],
        to_pdir_fid: str,
        pwd_id: str,
        stoken: str,
        file_names: List[str] = None,
    ) -> Dict:
        """转存文件到指定目录"""
        if not self._ensure_tokens_valid():
            return {"code": 1, "message": "Token 无效", "data": {}}

        try:
            parent_id = to_pdir_fid if to_pdir_fid and str(to_pdir_fid) != "0" else ""

            body = {
                "parent_id": parent_id,
                "share_id": pwd_id,
                "pass_code_token": stoken,
                "file_ids": fid_token_list,
                "ancestor_ids": [],
                "specify_parent_id": True,
            }

            result = self._request("POST", f"{API_BASE}/drive/v1/share/restore", body=body)

            if self._has_error(result):
                msg = self._get_error_message(result)
                return {"code": 1, "message": msg, "data": {}}

            # 提取 task_id
            task_id = result.get("restore_task_id", "")
            if not task_id:
                # 没有 task_id 说明是同步完成的
                return {
                    "code": 0,
                    "message": "success",
                    "data": {
                        "task_id": f"xunlei_sync_{pwd_id}",
                        "_sync": True,
                    },
                }

            return {
                "code": 0,
                "message": "success",
                "data": {
                    "task_id": task_id,
                },
            }

        except Exception as e:
            logger.error(f"[Xunlei] 转存失败: {e}")
            return {"code": 1, "message": str(e), "data": {}}

    def query_task(self, task_id: str) -> Dict:
        """查询任务状态"""
        # 同步任务直接返回成功
        if task_id.startswith("xunlei_sync_"):
            return {
                "status": 200,
                "code": 0,
                "data": {"status": 2, "task_title": "转存文件"},
                "message": "success",
            }

        retry_index = 0
        max_retries = 60

        while retry_index < max_retries:
            try:
                result = self._request("GET", f"{API_BASE}/drive/v1/tasks/{task_id}")

                if self._has_error(result):
                    msg = self._get_error_message(result)
                    return {"status": 500, "code": 1, "message": msg, "data": {"status": 0}}

                progress = result.get("progress", 0)
                phase = result.get("phase", "")

                # 任务完成
                if progress == 100 or phase == "PHASE_TYPE_COMPLETE":
                    # 提取转存后的文件ID
                    save_as_top_fids = []
                    params = result.get("params", {})
                    trace_ids_str = params.get("trace_file_ids", "")
                    if trace_ids_str:
                        try:
                            trace_data = json.loads(trace_ids_str)
                            if isinstance(trace_data, dict):
                                save_as_top_fids = list(trace_data.values())
                            elif isinstance(trace_data, list):
                                save_as_top_fids = trace_data
                        except Exception:
                            pass

                    if retry_index > 0:
                        logger.debug("")

                    return {
                        "status": 200,
                        "code": 0,
                        "data": {
                            "status": 2,
                            "task_title": result.get("name", "转存文件"),
                            "save_as": {"save_as_top_fids": save_as_top_fids},
                        },
                        "message": "success",
                    }

                # 任务失败
                if phase == "PHASE_TYPE_ERROR":
                    msg = result.get("message", "任务执行失败")
                    return {"status": 500, "code": 1, "message": msg, "data": {"status": -1}}

                # 任务进行中
                if retry_index == 0:
                    logger.debug(f"[Xunlei] 等待任务执行: {result.get('name', task_id)}")

                retry_index += 1
                time.sleep(0.5)

            except Exception as e:
                logger.error(f"[Xunlei] 查询任务失败: {e}")
                return {"status": 500, "code": 1, "message": str(e), "data": {"status": 0}}

        return {
            "status": 500,
            "code": 1,
            "message": "任务查询超时",
            "data": {"status": 0},
        }

    def mkdir(self, dir_path: str) -> Dict:
        """创建目录"""
        if not self._ensure_tokens_valid():
            return {"code": 1, "message": "Token 无效"}

        try:
            parts = [p for p in dir_path.strip("/").split("/") if p]
            if not parts:
                return {"code": 1, "message": "目录路径无效"}

            parent_id = ""
            created_id = None
            created_name = None

            for name in parts:
                # 检查目录是否存在
                existing = self._find_by_name(parent_id, name, "drive#folder")
                if existing:
                    parent_id = existing.get("id", "")
                    created_id = parent_id
                    created_name = name
                    continue

                # 创建目录
                body = {
                    "kind": "drive#folder",
                    "parent_id": parent_id,
                    "name": name,
                }

                result = self._request("POST", f"{API_BASE}/drive/v1/files", body=body)

                if self._has_error(result):
                    msg = self._get_error_message(result)
                    return {"code": 1, "message": msg}

                parent_id = result.get("file", {}).get("id", "") or result.get("id", "")
                created_id = parent_id
                created_name = name

            return {
                "code": 0,
                "message": "success",
                "data": {"fid": created_id, "file_name": created_name},
            }
        except Exception as e:
            logger.error(f"[Xunlei] 创建目录失败: {e}")
            return {"code": 1, "message": str(e)}

    def _find_by_name(self, parent_id: str, name: str, kind: str = None) -> Optional[Dict]:
        """在指定目录下按名称查找文件/文件夹"""
        try:
            params = {
                "parent_id": parent_id,
                "filters": FILE_LIST_FILTERS,
                "limit": 100,
            }
            result = self._request("GET", f"{API_BASE}/drive/v1/files", params=params)

            for item in result.get("files", []):
                if item.get("name") == name:
                    if kind is None or item.get("kind") == kind:
                        return item
            return None
        except Exception:
            return None

    def rename(self, fid: str, file_name: str) -> Dict:
        """重命名文件"""
        if not self._ensure_tokens_valid():
            return {"code": 1, "message": "Token 无效"}

        try:
            body = {"name": file_name}
            result = self._request("PATCH", f"{API_BASE}/drive/v1/files/{fid}", body=body)

            if self._has_error(result):
                msg = self._get_error_message(result)
                return {"code": 1, "message": msg}

            return {"code": 0, "message": "success"}
        except Exception as e:
            logger.error(f"[Xunlei] 重命名失败: {e}")
            return {"code": 1, "message": str(e)}

    def delete(self, filelist: List[str]) -> Dict:
        """删除文件"""
        if not self._ensure_tokens_valid():
            return {"code": 1, "message": "Token 无效"}

        try:
            body = {"ids": filelist, "space": ""}
            result = self._request("POST", f"{API_BASE}/drive/v1/files:batchDelete", body=body)

            if self._has_error(result):
                msg = self._get_error_message(result)
                return {"code": 1, "message": msg}

            return {"code": 0, "message": "success"}
        except Exception as e:
            logger.error(f"[Xunlei] 删除失败: {e}")
            return {"code": 1, "message": str(e)}

    def get_fids(self, file_paths: List[str]) -> List[Dict]:
        """根据路径获取文件 ID"""
        if not self._ensure_tokens_valid():
            return []

        results = []

        for path in file_paths:
            if not path or path == "/":
                results.append({"file_path": "/", "fid": ""})
                continue

            parts = [p for p in path.strip("/").split("/") if p]
            parent_id = ""
            found = True

            for name in parts:
                item = self._find_by_name(parent_id, name)
                if item:
                    parent_id = item.get("id", "")
                else:
                    found = False
                    break

            if found:
                results.append({"file_path": path, "fid": parent_id})

        return results

    def extract_url(self, url: str) -> Tuple[Optional[str], str, Any, List]:
        """
        解析迅雷网盘分享链接

        支持格式:
        - https://pan.xunlei.com/s/{share_id}
        - https://pan.xunlei.com/s/{share_id}#/list/{folder_id}
        - https://pan.xunlei.com/s/{share_id}?pwd=xxxx
        """
        pwd_id = None
        passcode = ""
        pdir_fid = "0"
        paths = []

        # 提取分享 ID
        match_s = re.search(r"pan\.xunlei\.com/s/([a-zA-Z0-9_-]+)", url)
        if match_s:
            pwd_id = match_s.group(1)
            # 去除 query string
            if "?" in pwd_id:
                pwd_id = pwd_id.split("?")[0]
            if "#" in pwd_id:
                pwd_id = pwd_id.split("#")[0]

        # 提取提取码
        match_pwd = re.search(r"(?:pwd|password)=([a-zA-Z0-9]+)", url)
        if match_pwd:
            passcode = match_pwd.group(1)

        # 提取子目录 ID
        if "#/list/share/" in url:
            raw_fid = url.split("#/list/share/")[-1]
            match_fid = re.match(r"(\w+)", raw_fid)
            if match_fid:
                pdir_fid = match_fid.group(1)

        return pwd_id, passcode, pdir_fid, paths

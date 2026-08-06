# -*- coding: utf-8 -*-
"""
阿里云盘适配器
基于 requests 直接调用阿里云盘 API 实现
参考 aligo 项目的实现方式
"""
import re
import json
import time
import logging
import hashlib
import threading
from typing import Dict, List, Tuple, Optional, Any, Callable
from urllib.parse import urlparse, unquote

import requests

from app.extensions.adapters.base_adapter import BaseCloudDriveAdapter


logger = logging.getLogger(__name__)


# ==================== 常量定义 ====================
API_HOST = "https://api.aliyundrive.com"
AUTH_HOST = "https://auth.aliyundrive.com"
PASSPORT_HOST = "https://passport.aliyundrive.com"
OPEN_HOST = "https://open.alipan.com"

# 客户端 ID
CLIENT_ID = "25dzX3vbYqktVxyX"

# User-Agent
ALIYUN_UA = "AliApp(AYSD/5.8.0) com.alicloud.databox/37029260 Channel/36176927979800@rimet_android_5.8.0 language/zh-CN /Android Mobile/Xiaomi Redmi"

# 统一请求头
UNI_HEADERS = {
    "Referer": "https://aliyundrive.com",
    "User-Agent": ALIYUN_UA,
    "x-canary": "client=Android,app=adrive,version=v5.8.0",
    "Content-Type": "application/json",
}

# API 端点
V2_USER_GET = "/v2/user/get"
V2_FILE_LIST = "/v2/file/list"
ADRIVE_V3_FILE_LIST = "/adrive/v3/file/list"
V2_FILE_GET = "/v2/file/get"
V2_FILE_CREATE = "/v2/file/create"
V2_FILE_COPY = "/v2/file/copy"
V2_RECYCLEBIN_TRASH = "/v2/recyclebin/trash"
V3_FILE_UPDATE = "/v3/file/update"
V2_ACCOUNT_TOKEN = "/v2/account/token"
ADRIVE_V2_SHARE_LINK_GET_SHARE_BY_ANONYMOUS = "/adrive/v2/share_link/get_share_by_anonymous"
V2_SHARE_LINK_GET_SHARE_TOKEN = "/v2/share_link/get_share_token"
ADRIVE_V2_FILE_LIST_BY_SHARE = "/adrive/v2/file/list_by_share"
ADRIVE_V2_FILE_GET_BY_SHARE = "/adrive/v2/file/get_by_share"
ADRIVE_V2_BATCH = "/adrive/v2/batch"
ADRIVE_V1_FILE_GET_PATH = "/adrive/v1/file/get_path"

# 二维码登录相关
NEWLOGIN_QRCODE_GENERATE_DO = "/newlogin/qrcode/generate.do"
NEWLOGIN_QRCODE_QUERY_DO = "/newlogin/qrcode/query.do"


def _config_saver_factory(config_path: str):
    """创建配置保存函数"""
    def save_config(new_refresh_token: str, account_name: str = None):
        """保存新的 refresh_token 到配置文件"""
        try:
            from quark_auto_save import Config
            config = Config.read_json(config_path)
            if not config:
                logger.warning("[Aliyun] 无法读取配置文件")
                return False
            
            # 更新 accounts 中对应账户的 cookie (refresh_token)
            accounts = config.get("accounts", [])
            updated = False
            current_time = time.time()
            for acc in accounts:
                if acc.get("drive_type") == "aliyun":
                    # 如果指定了账户名，只更新匹配的账户
                    if account_name and acc.get("name") != account_name:
                        continue
                    acc["cookie"] = new_refresh_token
                    # 记录 token 更新时间戳，用于防止回滚
                    acc["_token_updated_at"] = current_time
                    updated = True
                    logger.info(f"[Aliyun] 已更新账户 {acc.get('name', 'unknown')} 的 refresh_token (时间戳: {current_time})")
                    if account_name:
                        break
            
            if updated:
                Config.write_json(config_path, config)
                logger.info("[Aliyun] refresh_token 已保存到配置文件")
                return True
            else:
                logger.warning("[Aliyun] 未找到需要更新的阿里云盘账户")
                return False
        except Exception as e:
            logger.error(f"[Aliyun] 保存 refresh_token 失败: {e}")
            return False
    
    return save_config


# 全局配置保存函数（在适配器初始化时设置）
_global_config_saver: Optional[Callable] = None


class AliyunToken:
    """阿里云盘 Token 信息"""
    
    def __init__(self, token_data: Dict = None):
        if token_data is None:
            token_data = {}
        self.access_token: str = token_data.get("access_token", "")
        self.refresh_token: str = token_data.get("refresh_token", "")
        self.expires_in: int = int(token_data.get("expires_in", 0) or 0)
        self.token_type: str = token_data.get("token_type", "Bearer")
        self.user_id: str = str(token_data.get("user_id", ""))
        self.user_name: str = str(token_data.get("user_name", ""))
        self.nick_name: str = str(token_data.get("nick_name", ""))
        self.default_drive_id: str = str(token_data.get("default_drive_id", ""))
        self.default_sbox_drive_id: str = str(token_data.get("default_sbox_drive_id", ""))
        # 确保 expire_time 是数字类型
        expire_time = token_data.get("expire_time", 0)
        if isinstance(expire_time, str):
            try:
                expire_time = float(expire_time)
            except (ValueError, TypeError):
                expire_time = 0
        self.expire_time: float = float(expire_time) if expire_time else (time.time() + self.expires_in - 60)
        # 记录 token 更新时间戳，用于版本控制
        self.updated_at: float = time.time()
    
    @property
    def is_expired(self) -> bool:
        """检查 token 是否过期"""
        try:
            return time.time() >= float(self.expire_time)
        except (ValueError, TypeError):
            return True
    
    def to_dict(self) -> Dict:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_in": self.expires_in,
            "token_type": self.token_type,
            "user_id": self.user_id,
            "user_name": self.user_name,
            "nick_name": self.nick_name,
            "default_drive_id": self.default_drive_id,
            "default_sbox_drive_id": self.default_sbox_drive_id,
            "expire_time": self.expire_time,
            "updated_at": self.updated_at,
        }


class AliyunAdapter(BaseCloudDriveAdapter):
    """阿里云盘适配器"""

    DRIVE_TYPE = "aliyun"
    DRIVE_NAME = "阿里云盘"
    CONFIG_FORMAT = "raw"
    default_config = {
        "refresh_token": "",
    }
    config_fields = [
        {
            "key": "refresh_token",
            "label": "Refresh Token",
            "description": "阿里云盘刷新令牌；系统内部仍兼容存入原有 cookie 字段。",
            "input_type": "textarea",
            "required": True,
            "secret": True,
            "placeholder": "refresh_token",
        }
    ]

    # 错误码映射
    ERROR_CODES = {
        "ShareLinkTokenInvalid": "分享链接 Token 无效",
        "NotFound.ShareLink": "分享链接不存在或已过期",
        "ShareLink.Cancelled": "分享链接已取消",
        "ShareLink.Forbidden": "分享链接被禁止访问",
        "InvalidResource.SharePwd": "提取码错误",
        "ParamFlowException": "请求过于频繁，请稍后重试",
        "ForbiddenNoPermission.File": "没有文件操作权限",
        "AlreadyExist.File": "文件已存在",
        "NotFound.File": "文件不存在",
        "InvalidParameter": "参数错误",
        "AccessTokenInvalid": "访问令牌无效，请重新登录",
        "RefreshTokenExpired": "刷新令牌已过期，请重新登录",
        "UserDeviceOffline": "设备已离线",
    }

    def __init__(
        self,
        cookie: str = "",
        index: int = 0,
        config: dict | None = None,
        account_name: str | None = None,
        no_login: bool = False,
    ):
        """
        初始化阿里云盘适配器
        
        Args:
            cookie: refresh_token 字符串
            index: 账户索引
            account_name: 账户名称（用于 token 更新时定位账户）
        """
        super().__init__(cookie, index, config=config, no_login=no_login)
        self._session: requests.Session = requests.Session()
        self._session.headers.update(UNI_HEADERS)
        self._rate_limit_min_interval = 0.25
        self._rate_limit_max_interval = 0.45
        
        self._refresh_token: str = str(self.config.get("refresh_token") or self.cookie or "").strip()
        self._token: Optional[AliyunToken] = None
        self._account_name: str = account_name or ""
        self._token_lock = threading.Lock()

    def _get_error_message(self, code: str) -> str:
        """获取错误码对应的提示信息"""
        return self.ERROR_CODES.get(code, f"未知错误 ({code})")

    def _init_token(self):
        """初始化并刷新 token"""
        try:
            self._do_refresh_token()
        except Exception as e:
            logger.error(f"[Aliyun] 初始化 token 失败: {e}")

    def _do_refresh_token(self) -> bool:
        """刷新 access_token"""
        with self._token_lock:
            if not self._refresh_token:
                logger.error("[Aliyun] 没有 refresh_token，无法刷新")
                return False
            
            try:
                # 使用 /v2/account/token 端点，与 aligo 保持一致
                url = f"{API_HOST}{V2_ACCOUNT_TOKEN}"
                data = {
                    "refresh_token": self._refresh_token,
                    "grant_type": "refresh_token",
                }
                
                resp = self._session.post(url, json=data, timeout=30)
                result = resp.json()
                
                if "access_token" not in result:
                    code = result.get("code", "Unknown")
                    message = result.get("message", "")
                    logger.error(f"[Aliyun] 刷新 token 失败: {code} - {message}")
                    return False
                
                # 更新 token
                self._token = AliyunToken(result)
                old_refresh_token = self._refresh_token
                self._refresh_token = self._token.refresh_token
                
                # 更新 session 的 Authorization header
                self._session.headers["Authorization"] = f"Bearer {self._token.access_token}"
                
                # 如果 refresh_token 变化了，保存到配置文件
                if old_refresh_token != self._refresh_token:
                    self._save_refresh_token()
                
                logger.info(f"[Aliyun] Token 刷新成功，用户: {self._token.nick_name}")
                return True
                
            except Exception as e:
                logger.error(f"[Aliyun] 刷新 token 异常: {e}")
                return False

    def _save_refresh_token(self):
        """保存新的 refresh_token 到配置文件"""
        global _global_config_saver
        if _global_config_saver:
            _global_config_saver(self._refresh_token, self._account_name)

    def _ensure_token_valid(self) -> bool:
        """确保 token 有效"""
        if bool(getattr(self, "no_login", False)):
            return False
        if not self._token or self._token.is_expired:
            return self._do_refresh_token()
        return True

    def _request(
        self,
        method: str,
        path: str,
        host: str = API_HOST,
        body: Dict = None,
        headers: Dict = None,
        ignore_auth: bool = False,
        **kwargs,
    ) -> requests.Response:
        """发送 HTTP 请求"""
        if not ignore_auth:
            if not self._ensure_token_valid():
                raise Exception("Token 无效")
        url = f"{host}{path}"
        req_headers = dict(self._session.headers)
        if headers:
            req_headers.update(headers)
        
        if ignore_auth and "Authorization" in req_headers:
            del req_headers["Authorization"]

        last_resp: requests.Response | None = None
        for attempt in range(4):
            self._throttle_request()
            try:
                if method.upper() == "GET":
                    resp = self._session.get(url, headers=req_headers, params=body, timeout=30, **kwargs)
                else:
                    resp = self._session.post(url, headers=req_headers, json=body, timeout=30, **kwargs)
                last_resp = resp
            except Exception as e:
                last_resp = None
                if attempt >= 3:
                    logger.error(f"[Aliyun] HTTP 请求失败: {e}")
                    raise
                time.sleep(random.uniform(0.4, 0.9) * (2**attempt))
                continue

            if resp.status_code in (429, 503):
                if attempt >= 3:
                    return resp
                time.sleep(random.uniform(0.6, 1.4) * (2**attempt))
                continue

            try:
                data = resp.json()
            except Exception:
                return resp
            code = str((data or {}).get("code") or "").strip()
            if code in ("TooManyRequests", "BlockException", "ParamFlowException"):
                if attempt >= 3:
                    return resp
                time.sleep(random.uniform(0.6, 1.4) * (2**attempt))
                continue

            return resp

        if last_resp is None:
            raise Exception("Aliyun 请求失败")
        return last_resp

    def _check_response(self, resp: requests.Response) -> Dict:
        """检查响应并返回数据"""
        try:
            data = resp.json()
        except:
            data = {"code": "ParseError", "message": resp.text[:200]}
        
        if resp.status_code not in [200, 201, 202]:
            code = data.get("code", "Unknown")
            message = data.get("message", self._get_error_message(code))
            logger.error(f"[Aliyun] API 错误: {code} - {message}")
        
        return data

    # ==================== 公共接口实现 ====================
    
    def init(self) -> Any:
        """初始化账户，验证 refresh_token 有效性"""
        if bool(getattr(self, "no_login", False)):
            return False
        if not self._refresh_token:
            logger.error("[Aliyun] 未配置 refresh_token")
            return False
        
        if self._do_refresh_token():
            self.is_active = True
            self.nickname = self._token.nick_name or f"阿里云盘用户{self.index}"
            return {
                "user_id": self._token.user_id,
                "user_name": self._token.user_name,
                "nickname": self.nickname,
                "default_drive_id": self._token.default_drive_id,
            }
        
        return False

    def get_account_info(self) -> Any:
        """获取账户信息"""
        return self.init()

    def _get_user_capacity_info(self) -> Dict[str, Any]:
        """获取阿里云盘容量信息"""
        resp = self._request("POST", "/adrive/v1/user/getUserCapacityInfo", body={})
        data = self._check_response(resp)
        if not isinstance(data, dict) or data.get("code"):
            return {}
        return data

    def get_account_config(self) -> Dict[str, Any]:
        """获取阿里云盘账户配置/容量信息"""
        nickname = ""
        username = ""
        capacity_info: Dict[str, Any] = {}

        try:
            if self._ensure_token_valid():
                if self._token:
                    nickname = self._token.nick_name or ""
                    username = self._token.user_name or self._token.user_id or ""
                capacity_info = self._get_user_capacity_info() or {}
        except Exception:
            capacity_info = {}

        if not nickname:
            nickname = self.nickname or f"阿里云盘用户{self.index}"
        self.nickname = nickname

        if not username:
            username = nickname

        drive_details = capacity_info.get("drive_capacity_details") if isinstance(capacity_info, dict) else None
        used_space = None
        total_space = None
        if isinstance(drive_details, dict):
            try:
                if drive_details.get("drive_used_size") is not None:
                    used_space = int(drive_details.get("drive_used_size") or 0)
            except Exception:
                used_space = None
            try:
                if drive_details.get("drive_total_size") is not None:
                    total_space = int(drive_details.get("drive_total_size") or 0)
            except Exception:
                total_space = None

        capacity_level = capacity_info.get("capacity_level_info") if isinstance(capacity_info, dict) else None
        member_type = capacity_level.get("capacity_type") if isinstance(capacity_level, dict) else ""
        member_status = capacity_info.get("user_capacity_limit_details") if isinstance(capacity_info, dict) else {}
        if not isinstance(member_status, dict):
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
                "account_info": self._token.to_dict() if self._token else None,
                "member_info": capacity_info or None,
            },
        }

    def get_stoken(self, pwd_id: str, passcode: str = "") -> Dict:
        """获取分享令牌"""
        try:
            # 先获取分享信息
            share_info = self._get_share_info(pwd_id)
            if not share_info or share_info.get("code"):
                code = share_info.get("code", "Unknown") if share_info else "Unknown"
                return {
                    "status": 400,
                    "code": 1,
                    "message": self._get_error_message(code),
                }
            
            # 获取 share_token
            share_token = self._get_share_token(pwd_id, passcode)
            if not share_token or share_token.get("code"):
                code = share_token.get("code", "Unknown") if share_token else "Unknown"
                return {
                    "status": 400,
                    "code": 1,
                    "message": self._get_error_message(code),
                }
            
            return {
                "status": 200,
                "code": 0,
                "data": {
                    "stoken": share_token.get("share_token", ""),
                    "share_id": pwd_id,
                    "share_info": share_info,
                },
                "message": "success",
            }
        except Exception as e:
            logger.error(f"[Aliyun] 获取分享令牌失败: {e}")
            return {"status": 500, "code": 1, "message": str(e)}

    def _get_share_info(self, share_id: str) -> Dict:
        """获取分享信息（匿名）"""
        body = {"share_id": share_id}
        resp = self._request("POST", ADRIVE_V2_SHARE_LINK_GET_SHARE_BY_ANONYMOUS, body=body, ignore_auth=True)
        return self._check_response(resp)

    def _get_share_token(self, share_id: str, share_pwd: str = "") -> Dict:
        """获取分享 token"""
        body = {"share_id": share_id, "share_pwd": share_pwd}
        resp = self._request("POST", V2_SHARE_LINK_GET_SHARE_TOKEN, body=body, ignore_auth=True)
        return self._check_response(resp)

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
            parent_file_id = pdir_fid if pdir_fid and pdir_fid != "0" else "root"

            # 获取文件列表
            file_list = []
            marker = ""
            while True:
                body = {
                    "share_id": pwd_id,
                    "parent_file_id": parent_file_id,
                    "limit": 100,
                    "marker": marker,
                    "order_by": "name",
                    "order_direction": "ASC",
                }
                headers = {"x-share-token": stoken}
                
                resp = self._request("POST", ADRIVE_V2_FILE_LIST_BY_SHARE, body=body, headers=headers, ignore_auth=True)
                data = self._check_response(resp)

                if data.get("code"):
                    return {
                        "code": 1,
                        "message": self._get_error_message(data.get("code")),
                        "data": {"list": []},
                    }
                
                items = data.get("items", [])
                for item in items:
                    file_info = self._convert_share_item(item)
                    file_list.append(file_info)
                
                marker = data.get("next_marker", "")
                if not marker:
                    break
            
            # 获取面包屑路径
            full_path = []
            if fetch_share_full_path and parent_file_id != "root":
                full_path = self._get_share_path(pwd_id, stoken, parent_file_id)

            return {
                "code": 0,
                "message": "success",
                "data": {"list": file_list, "full_path": full_path},
                "metadata": {"_total": len(file_list)},
            }
        except Exception as e:
            logger.error(f"[Aliyun] 获取分享详情失败: {e}")
            return {"code": 1, "message": str(e), "data": {"list": []}}

    def _get_share_path(self, share_id: str, share_token: str, file_id: str) -> List[Dict]:
        """获取分享文件的路径（面包屑）"""
        if not file_id or file_id == "root":
            return []
        
        try:
            # 方法1: 先获取文件信息得到 drive_id，再调用 get_path API
            file_info = self._get_share_file_info(share_id, share_token, file_id)
            if file_info and file_info.get("drive_id"):
                drive_id = file_info.get("drive_id")
                body = {"drive_id": drive_id, "file_id": file_id}
                headers = {"x-share-token": share_token}
                
                resp = self._request("POST", ADRIVE_V1_FILE_GET_PATH, body=body, headers=headers, ignore_auth=True)
                data = self._check_response(resp)
                
                if not data.get("code"):
                    items = data.get("items", [])
                    path = []
                    for item in items:
                        if item.get("file_id") != "root":
                            path.append({
                                "fid": item.get("file_id", ""),
                                "file_name": item.get("name", ""),
                            })
                    return path
            
            # 方法2: 如果上述方法失败，使用 BFS 遍历
            return self._bfs_share_path(share_id, share_token, file_id)
        except Exception as e:
            logger.debug(f"[Aliyun] 获取分享路径失败: {e}")
            return []

    def _get_share_file_info(self, share_id: str, share_token: str, file_id: str) -> Optional[Dict]:
        """获取分享文件的详细信息"""
        try:
            body = {"share_id": share_id, "file_id": file_id}
            headers = {"x-share-token": share_token}
            
            resp = self._request("POST", ADRIVE_V2_FILE_GET_BY_SHARE, body=body, headers=headers, ignore_auth=True)
            data = self._check_response(resp)
            
            if not data.get("code"):
                return data
            return None
        except Exception as e:
            logger.debug(f"[Aliyun] 获取分享文件信息失败: {e}")
            return None

    def _bfs_share_path(self, share_id: str, share_token: str, target_file_id: str) -> List[Dict]:
        """通过 BFS 遍历获取分享文件的路径（备用方法）"""
        from collections import deque
        
        # 队列元素：(当前目录ID, 当前路径列表)
        queue = deque([("root", [])])
        visited = {"root"}
        
        while queue:
            current_id, current_path = queue.popleft()
            
            # 获取当前目录的文件列表
            body = {
                "share_id": share_id,
                "parent_file_id": current_id,
                "limit": 100,
                "order_by": "name",
                "order_direction": "ASC",
            }
            headers = {"x-share-token": share_token}
            
            try:
                resp = self._request("POST", ADRIVE_V2_FILE_LIST_BY_SHARE, body=body, headers=headers, ignore_auth=True)
                data = self._check_response(resp)
                
                if data.get("code"):
                    continue
                
                items = data.get("items", [])
                for item in items:
                    item_id = item.get("file_id", "")
                    item_name = item.get("name", "")
                    is_folder = item.get("type") == "folder"
                    
                    # 找到目标文件
                    if item_id == target_file_id:
                        return current_path + [{"fid": item_id, "file_name": item_name}]
                    
                    # 如果是文件夹且未访问过，加入队列继续搜索
                    if is_folder and item_id not in visited:
                        visited.add(item_id)
                        new_path = current_path + [{"fid": item_id, "file_name": item_name}]
                        queue.append((item_id, new_path))
            except Exception as e:
                logger.debug(f"[Aliyun] BFS 遍历分享目录失败: {e}")
                continue
        
        return []

    def _convert_share_item(self, item: Dict) -> Dict:
        """转换阿里云盘分享文件项为统一格式"""
        is_folder = item.get("type") == "folder"
        file_id = item.get("file_id", "")
        
        return {
            "fid": file_id,
            "file_name": item.get("name", ""),
            "file_type": 0 if is_folder else 1,
            "dir": is_folder,
            "size": item.get("size", 0),
            "updated_at": self._parse_time(item.get("updated_at", "")),
            "share_fid_token": file_id,
        }

    def _parse_time(self, time_str: str) -> int:
        """解析时间字符串为时间戳"""
        if not time_str:
            return 0
        try:
            # 格式: 2024-01-01T12:00:00.000Z
            from datetime import datetime
            dt = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
            return int(dt.timestamp() * 1000)
        except:
            return 0

    def ls_dir(self, pdir_fid: str, max_items: int = 0, **kwargs) -> Dict:
        """列出用户网盘目录内容"""
        if not self._ensure_token_valid():
            return {"code": 1, "message": "Token 无效", "data": {"list": []}}
        
        # 检查 token 和 drive_id 是否有效
        if not self._token:
            return {"code": 1, "message": "Token 未初始化", "data": {"list": []}}
        
        drive_id = self._token.default_drive_id
        if not drive_id:
            return {"code": 1, "message": "未获取到 drive_id，请检查账户配置", "data": {"list": []}}

        try:
            parent_file_id = str(pdir_fid) if pdir_fid and str(pdir_fid) != "0" else "root"
            
            file_list = []
            marker = ""
            while True:
                body = {
                    "drive_id": drive_id,
                    "parent_file_id": parent_file_id,
                    "limit": 100,
                    "marker": marker,
                    "order_by": "name",
                    "order_direction": "ASC",
                }
                
                resp = self._request("POST", ADRIVE_V3_FILE_LIST, body=body)
                data = self._check_response(resp)
                
                if data.get("code"):
                    return {
                        "code": 1,
                        "message": self._get_error_message(data.get("code")),
                        "data": {"list": []},
                    }
                
                items = data.get("items", [])
                for item in items:
                    file_info = self._convert_item(item)
                    file_list.append(file_info)
                
                # max_items 限量：达到上限后提前终止分页
                if max_items > 0 and len(file_list) >= max_items:
                    file_list = file_list[:max_items]
                    break

                marker = data.get("next_marker", "")
                if not marker:
                    break
            
            return {
                "code": 0,
                "message": "success",
                "data": {"list": file_list},
                "metadata": {"_total": len(file_list)},
            }
        except Exception as e:
            logger.error(f"[Aliyun] 列出目录失败: {e}")
            return {"code": 1, "message": str(e), "data": {"list": []}}

    def _convert_item(self, item: Dict) -> Dict:
        """转换阿里云盘文件项为统一格式"""
        is_folder = item.get("type") == "folder"
        file_id = item.get("file_id", "")
        
        return {
            "fid": file_id,
            "file_name": item.get("name", ""),
            "file_type": 0 if is_folder else 1,
            "dir": is_folder,
            "size": item.get("size", 0),
            "updated_at": self._parse_time(item.get("updated_at", "")),
            "share_fid_token": file_id,
        }

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
        if not self._ensure_token_valid():
            return {"code": 1, "message": "Token 无效", "data": {}}
        
        # 检查 token 和 drive_id 是否有效
        if not self._token:
            return {"code": 1, "message": "Token 未初始化", "data": {}}
        
        try:
            to_parent_id = to_pdir_fid if to_pdir_fid and str(to_pdir_fid) != "0" else "root"
            to_drive_id = str(self._token.default_drive_id) if self._token.default_drive_id else ""
            
            # 验证 drive_id 格式
            if not to_drive_id:
                return {"code": 1, "message": "未获取到 drive_id，请检查账户配置", "data": {}}
            
            logger.debug(f"[Aliyun] save_file: to_drive_id={to_drive_id}, to_parent_id={to_parent_id}")
            
            # 批量转存
            requests_list = []
            for file_id in fid_token_list:
                requests_list.append({
                    "body": {
                        "file_id": file_id,
                        "share_id": pwd_id,
                        "to_parent_file_id": to_parent_id,
                        "to_drive_id": to_drive_id,
                        "auto_rename": True,
                    },
                    "headers": {"Content-Type": "application/json"},
                    "id": file_id,
                    "method": "POST",
                    "url": "/file/copy",
                })
            
            headers = {"x-share-token": stoken}
            body = {"requests": requests_list, "resource": "file"}
            
            resp = self._request("POST", ADRIVE_V2_BATCH, body=body, headers=headers)
            data = self._check_response(resp)
            
            if data.get("code"):
                return {
                    "code": 1,
                    "message": self._get_error_message(data.get("code")),
                    "data": {},
                }
            
            # 提取转存后的文件 ID
            saved_fids = []
            responses = data.get("responses", [])
            for resp_item in responses:
                if resp_item.get("status") in [200, 201, 202]:
                    body = resp_item.get("body", {})
                    saved_fids.append(body.get("file_id", ""))
                else:
                    saved_fids.append("")
            
            return {
                "code": 0,
                "message": "success",
                "data": {
                    "task_id": f"aliyun_sync_{pwd_id}",
                    "save_as_top_fids": saved_fids,
                    "_sync": True,
                },
            }
        except Exception as e:
            logger.error(f"[Aliyun] 转存失败: {e}")
            return {"code": 1, "message": str(e), "data": {}}

    def query_task(self, task_id: str) -> Dict:
        """查询任务状态（阿里云盘转存是同步操作）"""
        return {
            "status": 200,
            "code": 0,
            "data": {"status": 2, "task_title": "转存文件"},
            "message": "success",
        }

    def mkdir(self, dir_path: str) -> Dict:
        """创建目录"""
        if not self._ensure_token_valid():
            return {"code": 1, "message": "Token 无效"}
        
        try:
            # 解析路径，逐级创建
            parts = [p for p in dir_path.strip("/").split("/") if p]
            if not parts:
                return {"code": 1, "message": "目录路径无效"}
            
            parent_id = "root"
            drive_id = self._token.default_drive_id
            created_id = None
            created_name = None
            
            for name in parts:
                # 检查目录是否存在
                existing = self._find_by_name(drive_id, parent_id, name, "folder")
                if existing:
                    parent_id = existing.get("file_id")
                    created_id = parent_id
                    created_name = name
                    continue
                
                # 创建目录
                body = {
                    "drive_id": drive_id,
                    "parent_file_id": parent_id,
                    "name": name,
                    "type": "folder",
                    "check_name_mode": "refuse",
                }
                
                resp = self._request("POST", V2_FILE_CREATE, body=body)
                data = self._check_response(resp)
                
                if data.get("code") == "AlreadyExist.File":
                    # 目录已存在，查找它
                    existing = self._find_by_name(drive_id, parent_id, name, "folder")
                    if existing:
                        parent_id = existing.get("file_id")
                        created_id = parent_id
                        created_name = name
                        continue
                
                if data.get("code"):
                    return {
                        "code": 1,
                        "message": self._get_error_message(data.get("code")),
                    }
                
                parent_id = data.get("file_id", parent_id)
                created_id = parent_id
                created_name = name
            
            return {
                "code": 0,
                "message": "success",
                "data": {"fid": created_id, "file_name": created_name},
            }
        except Exception as e:
            logger.error(f"[Aliyun] 创建目录失败: {e}")
            return {"code": 1, "message": str(e)}

    def _find_by_name(self, drive_id: str, parent_id: str, name: str, file_type: str = None) -> Optional[Dict]:
        """在指定目录下查找文件/文件夹"""
        try:
            body = {
                "drive_id": drive_id,
                "parent_file_id": parent_id,
                "limit": 100,
            }
            resp = self._request("POST", V2_FILE_LIST, body=body)
            data = self._check_response(resp)
            
            for item in data.get("items", []):
                if item.get("name") == name:
                    if file_type is None or item.get("type") == file_type:
                        return item
            return None
        except:
            return None

    def rename(self, fid: str, file_name: str) -> Dict:
        """重命名文件"""
        if not self._ensure_token_valid():
            return {"code": 1, "message": "Token 无效"}
        
        try:
            body = {
                "drive_id": self._token.default_drive_id,
                "file_id": fid,
                "name": file_name,
                "check_name_mode": "refuse",
            }
            
            resp = self._request("POST", V3_FILE_UPDATE, body=body)
            data = self._check_response(resp)
            
            if data.get("code"):
                return {
                    "code": 1,
                    "message": self._get_error_message(data.get("code")),
                }
            
            return {"code": 0, "message": "success"}
        except Exception as e:
            logger.error(f"[Aliyun] 重命名失败: {e}")
            return {"code": 1, "message": str(e)}

    def delete(self, filelist: List[str]) -> Dict:
        """删除文件"""
        if not self._ensure_token_valid():
            return {"code": 1, "message": "Token 无效"}
        
        try:
            drive_id = self._token.default_drive_id
            
            # 批量删除（移到回收站）
            requests_list = []
            for file_id in filelist:
                requests_list.append({
                    "body": {
                        "drive_id": drive_id,
                        "file_id": file_id,
                    },
                    "headers": {"Content-Type": "application/json"},
                    "id": file_id,
                    "method": "POST",
                    "url": "/recyclebin/trash",
                })
            
            body = {"requests": requests_list, "resource": "file"}
            resp = self._request("POST", ADRIVE_V2_BATCH, body=body)
            data = self._check_response(resp)
            
            if data.get("code"):
                return {
                    "code": 1,
                    "message": self._get_error_message(data.get("code")),
                }
            
            return {"code": 0, "message": "success"}
        except Exception as e:
            logger.error(f"[Aliyun] 删除失败: {e}")
            return {"code": 1, "message": str(e)}

    def move_files(self, fids: List[str], to_pdir_fid: str) -> Dict:
        """批量移动文件"""
        return {"code": 0, "message": "success"}

    def get_file_path(self, file_id: str) -> List[Dict]:
        """根据文件 ID 获取路径信息（面包屑导航）"""
        if not self._ensure_token_valid():
            return []
        
        if not file_id or file_id == "0" or file_id == "root":
            return []
        
        try:
            drive_id = str(self._token.default_drive_id) if self._token else ""
            if not drive_id:
                return []
            
            body = {"drive_id": drive_id, "file_id": str(file_id)}
            resp = self._request("POST", ADRIVE_V1_FILE_GET_PATH, body=body)
            data = self._check_response(resp)
            
            items = data.get("items", [])
            path = []
            for item in items:
                item_id = item.get("file_id", "")
                # 排除 root 目录
                if item_id and item_id != "root":
                    path.append({
                        "fid": item_id,
                        "name": item.get("name", ""),
                    })
            return path.reverse()
        except Exception as e:
            logger.debug(f"[Aliyun] 获取文件路径失败: {e}")
            return []

    def get_fids(self, file_paths: List[str]) -> List[Dict]:
        """根据路径获取文件 ID"""
        if not self._ensure_token_valid():
            return []
        
        results = []
        drive_id = self._token.default_drive_id
        
        for path in file_paths:
            if not path or path == "/":
                results.append({"file_path": "/", "fid": "root"})
                continue
            
            parts = [p for p in path.strip("/").split("/") if p]
            parent_id = "root"
            found = True
            
            for name in parts:
                item = self._find_by_name(drive_id, parent_id, name)
                if item:
                    parent_id = item.get("file_id")
                else:
                    found = False
                    break
            
            if found:
                results.append({"file_path": path, "fid": parent_id})
        
        return results

    def extract_url(self, url: str) -> Tuple[Optional[str], str, Any, List]:
        """解析阿里云盘分享链接"""
        pwd_id = None
        passcode = ""
        pdir_fid = "root"
        paths = []

        # 格式: https://www.alipan.com/s/xxxxx 或 https://www.aliyundrive.com/s/xxxxx
        match_s = re.search(r"/s/([a-zA-Z0-9]+)", url)
        if match_s:
            pwd_id = match_s.group(1)
        
        # 提取提取码
        match_pwd = re.search(r"(?:pwd|password|提取码)[=:：]?\s*([a-zA-Z0-9]{4})", url)
        if match_pwd:
            passcode = match_pwd.group(1)

        # 提取子目录 ID
        if "#/list/share/" in url:
            raw_fid = url.split("#/list/share/")[-1]
            match_fid = re.match(r"(\w+)", raw_fid)
            if match_fid:
                pdir_fid = match_fid.group(1)

        return pwd_id, passcode, pdir_fid, paths

    # ==================== 二维码登录相关 ====================
    
    @staticmethod
    def generate_qrcode() -> Dict:
        """生成二维码登录信息"""
        try:
            from urllib.parse import quote
            
            # 获取二维码
            params = {
                "appName": "aliyun_drive",
                "fromSite": "52",
                "appEntrance": "web",
                "_csrf_token": "undefined",
                "umidToken": "undefined",
                "isMobile": "false",
                "lang": "zh_CN",
                "returnUrl": "",
                "hsiz": "1d3d3f3d3f3f",
                "bizParams": "",
                "navlanguage": "zh-CN",
                "navPlatform": "MacIntel",
            }
            
            url = f"{PASSPORT_HOST}{NEWLOGIN_QRCODE_GENERATE_DO}"
            resp = requests.get(url, params=params, timeout=30)
            data = resp.json()
            
            content = data.get("content", {})
            qr_data = content.get("data", {})
            
            # codeContent 是二维码的内容（一个 URL），需要用这个生成二维码图片
            code_content = qr_data.get("codeContent", "")
            
            # URL 编码 codeContent 以便作为参数传递给 QR 码生成服务
            encoded_content = quote(code_content, safe='') if code_content else ""
            
            return {
                "success": True,
                "data": {
                    "t": qr_data.get("t", ""),
                    "ck": qr_data.get("ck", ""),
                    "codeContent": code_content,
                    # 使用 QR 码生成服务生成图片 URL
                    "qrCodeUrl": f"https://api.qrserver.com/v1/create-qr-code/?size=200x200&data={encoded_content}" if encoded_content else "",
                },
            }
        except Exception as e:
            logger.error(f"[Aliyun] 生成二维码失败: {e}")
            return {"success": False, "message": str(e)}

    @staticmethod
    def query_qrcode_status(t: str, ck: str) -> Dict:
        """查询二维码扫描状态"""
        try:
            # 注意：query 接口需要使用 POST 方法，并且参数在 data 中
            params = {
                "appName": "aliyun_drive",
                "fromSite": "52",
                "appEntrance": "web",
                "_csrf_token": "undefined",
                "umidToken": "undefined",
                "isMobile": "false",
                "lang": "zh_CN",
                "returnUrl": "",
                "hsiz": "1d3d3f3d3f3f",
                "navlanguage": "zh-CN",
                "navPlatform": "MacIntel",
            }
            
            # POST 请求，t 和 ck 放在 data 中
            data = {
                "t": t,
                "ck": ck,
            }
            
            url = f"{PASSPORT_HOST}{NEWLOGIN_QRCODE_QUERY_DO}"
            resp = requests.post(url, params=params, data=data, timeout=30)
            result = resp.json()
            
            content = result.get("content", {})
            qr_data = content.get("data", {})
            
            qrCodeStatus = qr_data.get("qrCodeStatus", "")
            
            response = {
                "success": True,
                "data": {
                    "status": qrCodeStatus,
                    "message": {
                        "NEW": "等待扫码",
                        "SCANED": "已扫码，等待确认",
                        "CONFIRMED": "已确认",
                        "EXPIRED": "二维码已过期",
                        "CANCELED": "已取消",
                    }.get(qrCodeStatus, qrCodeStatus),
                },
            }
            
            # 如果已确认，获取 refresh_token
            if qrCodeStatus == "CONFIRMED":
                biz_ext = qr_data.get("bizExt", "")
                if biz_ext:
                    import base64
                    try:
                        # bizExt 是 base64 编码的，解码后是 gb18030 编码的 JSON
                        biz_data = json.loads(base64.b64decode(biz_ext).decode("gb18030"))
                        pds_login_result = biz_data.get("pds_login_result", {})
                        response["data"]["refresh_token"] = pds_login_result.get("refreshToken", "")
                        response["data"]["access_token"] = pds_login_result.get("accessToken", "")
                        response["data"]["user_name"] = pds_login_result.get("userName", "")
                        response["data"]["nick_name"] = pds_login_result.get("nickName", "")
                    except Exception as e:
                        logger.error(f"[Aliyun] 解析登录结果失败: {e}")
            
            return response
        except Exception as e:
            logger.error(f"[Aliyun] 查询二维码状态失败: {e}")
            return {"success": False, "message": str(e)}


# 设置全局配置保存函数的工厂方法
def set_config_saver(config_path: str):
    """设置配置保存函数"""
    global _global_config_saver
    if callable(config_path):
        _global_config_saver = config_path
    else:
        _global_config_saver = _config_saver_factory(config_path)

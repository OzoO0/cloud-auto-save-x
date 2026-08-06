# -*- coding: utf-8 -*-
"""
百度网盘适配器
基于 requests 直接调用百度网盘 API 实现
参考 BaiduPCS-Py 项目的实现方式
"""
import re
import json
import time
import random
import logging
import hashlib
from typing import Dict, List, Tuple, Optional, Any
from urllib.parse import urlparse, unquote
from base64 import standard_b64encode

import requests

from app.extensions.adapters.base_adapter import BaseCloudDriveAdapter


logger = logging.getLogger(__name__)


# ==================== 常量定义 ====================
PCS_BAIDU_COM = "https://pcs.baidu.com"
PAN_BAIDU_COM = "https://pan.baidu.com"

# User-Agent
PCS_UA = "softxm;netdisk"
PAN_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/77.0.3865.75 Safari/537.36"

PCS_HEADERS = {"User-Agent": PCS_UA}
PAN_HEADERS = {"User-Agent": PAN_UA}

# App IDs
PCS_APP_ID = "778750"
PAN_APP_ID = "250528"


# ==================== 工具函数 ====================
def _calu_md5(data: str) -> str:
    """计算 MD5"""
    return hashlib.md5(data.encode("utf-8")).hexdigest()


def _now_timestamp() -> int:
    """当前时间戳（秒）"""
    return int(time.time())


def _dump_json(obj: Any) -> str:
    """JSON 序列化"""
    return json.dumps(obj, separators=(",", ":"))


# ==================== API 节点 ====================
class PcsNode:
    """PCS API 节点"""
    QUOTA = "rest/2.0/pcs/quota"
    FILE = "rest/2.0/pcs/file"

    @classmethod
    def url(cls, node: str) -> str:
        return f"{PCS_BAIDU_COM}/{node}"


class PanNode:
    """PAN API 节点"""
    TRANSFER_SHARED = "share/transfer"
    SHARE = "share/set"
    SHARED_PATH_LIST = "share/list"
    SHARED_RECORD = "share/record"
    SHARED_CANCEL = "share/cancel"
    SHARED_PASSWORD = "share/surlinfoinrecord"
    GETCAPTCHA = "api/getcaptcha"
    CLOUD = "rest/2.0/services/cloud_dl"
    USER_PRODUCTS = "rest/2.0/membership/user"
    FILE = "api/list"

    @classmethod
    def url(cls, node: str) -> str:
        return f"{PAN_BAIDU_COM}/{node}"


class BaiduAdapter(BaseCloudDriveAdapter):
    """百度网盘适配器"""

    DRIVE_TYPE = "baidu"
    DRIVE_NAME = "百度网盘"
    CONFIG_FORMAT = "raw"
    default_config = {
        "cookie": "",
    }
    config_fields = [
        {
            "key": "cookie",
            "label": "Cookie",
            "description": "百度网盘登录 Cookie 原文，通常至少需要 BDUSS 与 STOKEN。",
            "input_type": "textarea",
            "required": True,
            "secret": True,
            "placeholder": "BDUSS=...; STOKEN=...",
        }
    ]

    # 错误码映射
    ERROR_CODES = {
        -6: "认证失败，请检查Cookie是否有效",
        -9: "文件不存在或已被删除",
        -62: "需要输入验证码",
        -65: "访问频率过高，请稍后重试",
        -1: "分享链接不存在",
        -3: "转存文件数超过限制",
        -7: "分享文件夹等待审核中",
        -21: "您的账户被锁定",
        2: "参数错误",
        4: "分享提取码错误",
        12: "转存文件失败",
        105: "分享链接已过期",
        111: "有其他异步任务正在执行",
        145: "分享链接已失效",
        200025: "提取码错误",
        31061: "文件已存在",
        31066: "目录不存在",
        31299: "文件夹创建失败",
    }

    def __init__(
        self,
        cookie: str = "",
        index: int = 0,
        config: dict | None = None,
        account_name: str = "",
        no_login: bool = False,
    ):
        super().__init__(cookie, index, config=config, no_login=no_login)
        self._cookies_dict: Dict[str, str] = {}
        self._session: Optional[requests.Session] = None
        self._bduss: str = ""
        self._stoken: str = ""
        self._bdstoken: str = ""
        self._user_id: Optional[int] = None
        self._share_info: Dict[str, Dict] = {}  # 缓存分享信息

        # 解析 cookie 并创建 session
        if cookie:
            self._parse_cookies(cookie)
            self._init_session()

    def _parse_cookies(self, cookie: str):
        """解析 cookie 字符串"""
        for item in cookie.split(";"):
            item = item.strip()
            if "=" in item:
                k, v = item.split("=", 1)
                self._cookies_dict[k.strip()] = v.strip()

        self._bduss = self._cookies_dict.get("BDUSS", "")
        self._stoken = self._cookies_dict.get("STOKEN", "")

    def _init_session(self):
        """初始化 requests session"""
        self._session = requests.Session()
        self._session.cookies.update(self._cookies_dict)

    def _get_error_message(self, errno: int) -> str:
        """获取错误码对应的提示信息"""
        return self.ERROR_CODES.get(errno, f"未知错误 (errno={errno})")

    def _get_headers(self, url: str) -> Dict[str, str]:
        """根据 URL 选择合适的请求头"""
        if PCS_BAIDU_COM in url:
            return dict(PCS_HEADERS)
        return dict(PAN_HEADERS)

    def _get_app_id(self, url: str) -> str:
        """根据 URL 选择合适的 app_id"""
        if PCS_BAIDU_COM in url:
            return PCS_APP_ID
        return PAN_APP_ID

    def _request(
        self,
        method: str,
        url: str,
        params: Optional[Dict[str, str]] = None,
        headers: Optional[Dict[str, str]] = None,
        data: Any = None,
        **kwargs,
    ) -> requests.Response:
        """发送 HTTP 请求"""
        if not self._session:
            raise Exception("Session 未初始化，请检查 Cookie")
        self._throttle_request()
        if params is None:
            params = {}
        if params:
            params["app_id"] = self._get_app_id(url)

        if headers is None:
            headers = self._get_headers(url)

        try:
            resp = self._session.request(
                method,
                url,
                params=params,
                headers=headers,
                data=data,
                timeout=30,
                **kwargs,
            )
            return resp
        except Exception as e:
            logger.error(f"[Baidu] HTTP 请求失败: {e}")
            raise

    def _check_response(self, info: Dict) -> Dict:
        """检查响应结果，处理错误码"""
        errno = info.get("errno") or info.get("error_code") or 0
        if errno != 0:
            error_msg = info.get("errmsg") or info.get("error_msg") or self._get_error_message(errno)
            logger.error(f"[Baidu] API 错误: errno={errno}, msg={error_msg}")
        return info

    # ==================== 获取 bdstoken ====================
    def _get_bdstoken(self) -> str:
        """获取 bdstoken（用于部分 API 调用）"""
        if self._bdstoken:
            return self._bdstoken

        try:
            url = "https://pan.baidu.com/disk/home"
            resp = self._request("GET", url, params=None)
            html = resp.text
            match = re.search(r'bdstoken[\'\":\s]+([0-9a-f]{32})', html)
            if match:
                self._bdstoken = match.group(1)
                return self._bdstoken
        except Exception as e:
            logger.debug(f"[Baidu] 获取 bdstoken 失败: {e}")

        return ""

    # ==================== 用户信息 ====================
    def _get_user_info_from_tieba(self) -> Dict:
        """通过贴吧 API 获取用户信息"""
        bduss = self._bduss
        timestamp = str(_now_timestamp())

        # 构建请求数据
        data = {
            "bdusstoken": bduss + "|null",
            "channel_id": "",
            "channel_uid": "",
            "stErrorNums": "0",
            "subapp_type": "mini",
            "timestamp": timestamp + "922",
            "_client_type": "2",
            "_client_version": "7.0.0.0",
            "_phone_imei": "352136052843838",
            "from": "mini_ad_wandoujia",
            "model": "MI 9",
        }

        # 计算 cuid
        cuid_str = bduss + "_" + data["_client_version"] + "_" + data["_phone_imei"] + "_" + data["from"]
        data["cuid"] = _calu_md5(cuid_str).upper() + "|" + data["_phone_imei"][::-1]

        # 计算 sign
        sign_str = "".join([k + "=" + data[k] for k in sorted(data.keys())]) + "tiebaclient!!!"
        data["sign"] = _calu_md5(sign_str).upper()

        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Cookie": "ka=open",
            "net": "1",
            "User-Agent": "bdtb for Android 6.9.2.1",
            "client_logid": timestamp + "416",
            "Connection": "Keep-Alive",
        }

        try:
            resp = requests.post(
                "http://tieba.baidu.com/c/s/login",
                headers=headers,
                data=data,
                timeout=15,
            )
            return resp.json()
        except Exception as e:
            logger.error(f"[Baidu] 获取用户信息失败: {e}")
            return {}

    def init(self) -> Any:
        """初始化账户，验证 cookie 有效性"""
        if not self._session:
            logger.error("[Baidu] Session 未初始化，请检查Cookie格式")
            return False

        if not self._bduss:
            logger.error("[Baidu] Cookie 中缺少 BDUSS")
            return False

        try:
            info = self._get_user_info_from_tieba()
            if info.get("user"):
                self.is_active = True
                user_id = info["user"].get("id")
                user_name = info["user"].get("name", "")
                self._user_id = int(user_id) if user_id else None
                self.nickname = user_name or f"百度用户{self.index}"
                return {
                    "user_id": self._user_id,
                    "user_name": user_name,
                    "nickname": self.nickname,
                }
        except Exception as e:
            logger.error(f"[Baidu] 初始化失败: {e}")

        return False

    def get_account_info(self) -> Any:
        """获取账户信息"""
        url = PAN_BAIDU_COM + "/rest/2.0/membership/user/info"
        querystring = {"method": "query", "clienttype": "0", "web": "1"}
        resp = self._request("POST", url, params=querystring)
        return resp.json()

    
    def _get_member_info(self) -> Dict[str, Any]:
        url = PAN_BAIDU_COM + f"/api/quota"
        querystring = {
            "clienttype": "0",
            "app_id": "250528",
            "web": "1",
            "dp-logid": "20218400174358800079",
        }
        resp = self._request("POST", url, params=querystring)
        return resp.json()


    def get_account_config(self) -> Dict[str, Any]:
        """获取百度账户配置/容量信息"""
        account_info = self.get_account_info() or {}
        member_info = self._get_member_info()
        member_data = member_info if isinstance(member_info, dict) else None

        nickname = (
            account_info.get("user_info", {}).get("username")
            or self.nickname
            or f"百度用户{self.index}"
        )
        if nickname:
            self.nickname = nickname

        return {
            "drive_type": self.DRIVE_TYPE,
            "drive_name": self.DRIVE_NAME,
            "nickname": nickname,
            "username": nickname,
            "used_space": member_data.get("used") if isinstance(member_data, dict) else None,
            "total_space": member_data.get("total") if isinstance(member_data, dict) else None,
            "member_type": '',
            "member_status": {},
            "raw": {
                "account_info": account_info or None,
                "member_info": member_data,
            },
        }

    def sign_in(self) -> Dict[str, Any]:
        if not self._session:
            raise RuntimeError("Session 未初始化，请检查 Cookie")

        headers = {
            "Connection": "keep-alive",
            "Accept": "application/json, text/plain, */*",
            "User-Agent": (
                "Mozilla/5.0 (Linux; Android 11; Pixel 5) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.91 "
                "Mobile Safari/537.36"
            ),
            "X-Requested-With": "XMLHttpRequest",
            "Referer": "https://pan.baidu.com/wap/svip/growth/task",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }

        total_points = 0
        parts: list[str] = []
        raw: dict[str, Any] = {}

        def _read_json(resp: requests.Response) -> dict[str, Any]:
            try:
                j = resp.json()
                return j if isinstance(j, dict) else {}
            except Exception:
                text = (resp.text or "").strip()
                if not text:
                    return {}
                try:
                    j = json.loads(text)
                    return j if isinstance(j, dict) else {}
                except Exception:
                    return {"_raw_text": text[:2000]}

        def _extract_points(payload: dict[str, Any]) -> int:
            v = payload.get("points")
            try:
                return int(v) if v is not None else 0
            except Exception:
                return 0

        signin_url = f"{PAN_BAIDU_COM}/rest/2.0/membership/level"
        signin_params = {"app_id": "250528", "web": "5", "method": "signin"}
        resp = self._session.get(signin_url, params=signin_params, headers=headers, timeout=20)
        resp.raise_for_status()
        signin_data = _read_json(resp)
        logger.debug("signin_data=%s", signin_data)
        raw["signin"] = signin_data
        errno = signin_data.get("errno") or signin_data.get("error_code") or 0
        if errno and int(errno) != 0:
            msg = signin_data.get("error_msg") or signin_data.get("errmsg") or self._get_error_message(int(errno))
            msg_text = str(msg or "")
            msg_lower = msg_text.lower()
            if "已签到" in msg_text or "repeat" in msg_lower or ("signin" in msg_lower and "repeat" in msg_lower) or ("sign" in msg_lower and "repeat" in msg_lower):
                parts.append("今日已签到")
            else:
                raise RuntimeError(msg_text)
        else:
            points = _extract_points(signin_data)
            total_points += points
            parts.append(f"签到积分+{points}" if points else "签到成功")

        question_url = f"{PAN_BAIDU_COM}/act/v2/membergrowv2/getdailyquestion"
        resp = self._session.get(question_url, params={"app_id": "250528", "web": "5"}, headers=headers, timeout=20)
        resp.raise_for_status()
        question_data = _read_json(resp)
        raw["question"] = question_data
        answer = question_data.get("answer")
        ask_id = question_data.get("ask_id")
        if answer is not None and ask_id is not None:
            answer_url = f"{PAN_BAIDU_COM}/act/v2/membergrowv2/answerquestion"
            resp = self._session.get(
                answer_url,
                params={
                    "app_id": "250528",
                    "web": "5",
                    "ask_id": str(ask_id),
                    "answer": str(answer),
                },
                headers=headers,
                timeout=20,
            )
            resp.raise_for_status()
            answer_data = _read_json(resp)
            raw["answer"] = answer_data
            score = answer_data.get("score")
            gained = 0
            try:
                gained = int(score) if score is not None else 0
            except Exception:
                gained = 0
            if gained:
                total_points += gained
                parts.append(f"答题积分+{gained}")
            else:
                show_msg = answer_data.get("show_msg") or ""
                if show_msg:
                    parts.append(str(show_msg))

        message = "，".join([p for p in parts if p])
        return {"supported": True, "ok": True, "reward": total_points, "message": message, "raw": raw}

    # ==================== 文件列表操作 ====================
    def _api_list(self, remotepath: str) -> Dict:
        """调用文件列表 API"""

        url = PanNode.url(PanNode.FILE)
        params = {
            "clienttype": "0",
            "app_id": "250528",
            "web": "1",
            "channel": "chunlei",
            "dp-logid": '81153300882182800128',
            "order": "time",
            "desc": "1",
            "num": "200",
            "page": "1",
            "dir": remotepath,
        }
        resp = self._request("POST", url, params=params)
        logger.debug(f"[Baidu] _api_list url={url} params={params},resp={self._check_response(resp.json())}")
        return self._check_response(resp.json())

    def _api_makedir(self, directory: str) -> Dict:
        """调用创建目录 API"""
        url = PcsNode.url(PcsNode.FILE)
        params = {
            "method": "mkdir",
            "path": directory,
        }
        resp = self._request("GET", url, params=params)
        return self._check_response(resp.json())

    def _api_file_operate(self, operate: str, param: List[Dict[str, str]]) -> Dict:
        """调用文件操作 API（移动、重命名、删除等）"""
        url = PcsNode.url(PcsNode.FILE)
        params = {"method": operate}
        data = {"param": _dump_json({"list": param})}
        resp = self._request("POST", url, params=params, data=data)
        return self._check_response(resp.json())

    # ==================== FID 到路径的转换 ====================
    def _resolve_fid_to_path(self, fid: str) -> str:
        """
        将 fid 解析为百度网盘 API 可用的路径。
        
        fid 可能是:
        - 路径字符串（以 / 开头），直接返回
        - "0" 或空，表示根目录，返回 /
        - fs_id（纯数字字符串），通过逐级遍历目录树查找
        """
        if not fid or fid == "0":
            return "/"
        if fid.startswith("/"):
            return fid
        if not fid.isdigit():
            logger.warning(f"[Baidu] fid={fid} 格式无法识别")
            return "/"
        if not self._session:
            return "/"

        # BFS: 从根目录逐级遍历
        dirs_to_search = ["/"]
        max_depth = 10

        for _ in range(max_depth):
            next_dirs = []
            for current_dir in dirs_to_search:
                try:
                    info = self._api_list(current_dir)
                    items = info.get("list", [])
                except Exception as e:
                    logger.debug(f"[Baidu] 列出 {current_dir} 失败: {e}")
                    continue

                for item in items:
                    if str(item.get("fs_id")) == fid:
                        path = item.get("path", "")
                        logger.debug(f"[Baidu] fid={fid} 解析为路径: {path}")
                        return path
                    if item.get("isdir") == 1:
                        next_dirs.append(item.get("path", ""))
                time.sleep(0.5)
            if not next_dirs:
                break
            dirs_to_search = next_dirs

        logger.warning(f"[Baidu] 遍历目录树后仍未找到 fid={fid} 对应的路径")
        return "/"

    # ==================== 分享链接操作 ====================
    def _shared_init_url(self, shared_url: str) -> str:
        """获取分享初始化 URL"""
        u = urlparse(shared_url)
        surl = u.path.split("/s/1")[-1]
        return f"https://pan.baidu.com/share/init?surl={surl}"

    def _api_access_shared(
        self,
        shared_url: str,
        password: str,
        vcode_str: str = "",
        vcode: str = "",
    ) -> Dict:
        """访问分享链接（验证提取码）"""
        url = "https://pan.baidu.com/share/verify"
        init_url = self._shared_init_url(shared_url)

        params = {
            "surl": init_url.split("surl=")[-1],
            "t": str(_now_timestamp() * 1000),
            "channel": "chunlei",
            "web": "1",
            "bdstoken": "null",
            "clienttype": "0",
        }
        data = {
            "pwd": password,
            "vcode": vcode,
            "vcode_str": vcode_str,
        }

        headers = dict(PAN_HEADERS)
        headers["Referer"] = init_url

        resp = self._request("POST", url, params=params, headers=headers, data=data)

        # 更新 cookies
        self._session.cookies.update(resp.cookies.get_dict())

        return self._check_response(resp.json())

    def _api_shared_paths(self, shared_url: str) -> Dict:
        """获取分享文件列表（从 HTML 解析）"""
        resp = self._request("GET", shared_url, params=None)
        html = resp.text

        # 更新 cookies
        self._session.cookies.update(resp.cookies.get_dict())

        # 解析 yunData.setData 或 locals.mset
        match = re.search(r"(?:yunData\.setData|locals\.mset)\((.+?)\);", html)
        if not match:
            logger.error("[Baidu] 无法解析分享页面数据")
            return {}

        try:
            shared_data = json.loads(match.group(1))
            return shared_data
        except json.JSONDecodeError as e:
            logger.error(f"[Baidu] 解析分享数据 JSON 失败: {e}")
            return {}

    def _api_list_shared_paths(
        self,
        sharedpath: str,
        uk: int,
        share_id: int,
        page: int = 1,
        size: int = 100,
    ) -> Dict:
        """获取分享目录下的文件列表"""
        url = PanNode.url(PanNode.SHARED_PATH_LIST)
        params = {
            "channel": "chunlei",
            "clienttype": "0",
            "web": "1",
            "page": str(page),
            "num": str(size),
            "dir": sharedpath,
            "t": str(random.random()),
            "uk": str(uk),
            "shareid": str(share_id),
            "desc": "1",
            "order": "other",
            "bdstoken": "null",
            "showempty": "0",
        }
        resp = self._request("GET", url, params=params)
        return self._check_response(resp.json())

    def _api_transfer_shared_paths(
        self,
        remotedir: str,
        fs_ids: List[int],
        uk: int,
        share_id: int,
        bdstoken: str,
        shared_url: str,
    ) -> Dict:
        """转存分享文件"""
        url = PanNode.url(PanNode.TRANSFER_SHARED)
        params = {
            "shareid": str(share_id),
            "from": str(uk),
            "bdstoken": bdstoken,
            "channel": "chunlei",
            "clienttype": "0",
            "web": "1",
        }
        data = {
            "fsidlist": _dump_json(fs_ids),
            "path": remotedir,
        }

        headers = dict(PAN_HEADERS)
        headers["X-Requested-With"] = "XMLHttpRequest"
        headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
        headers["Origin"] = "https://pan.baidu.com"
        headers["Referer"] = shared_url

        resp = self._request("POST", url, params=params, headers=headers, data=data)
        info = resp.json()

        # 处理嵌套错误码
        if info.get("info") and info["info"][0].get("errno"):
            info["errno"] = info["info"][0]["errno"]

        return self._check_response(info)

    # ==================== 分享目录树 BFS ====================
    def _get_item_path(self, item: Dict) -> str:
        """从 item 中获取路径"""
        if "path" in item:
            return item["path"]
        parent_path = item.get("parent_path", "")
        if parent_path:
            parent_path = unquote(parent_path)
        server_filename = item.get("server_filename", "")
        if parent_path:
            return f"{parent_path}/{server_filename}"
        return server_filename

    def _bfs_share_tree(
        self,
        file_list: List[Dict],
        uk: int,
        share_id: int,
        bdstoken: str,
        target_fid: str,
        max_depth: int = 5,
    ) -> Tuple[str, List[Dict]]:
        """
        在分享目录树中 BFS 查找 target_fid (fs_id)。

        Returns:
            (path_string, breadcrumb) 其中 breadcrumb 格式为
            [{"fid": "...", "file_name": "..."}, ...]
            未找到时返回 ("", [])
        """
        # 先检查根级条目
        for item in file_list:
            fs_id = str(item.get("fs_id", ""))
            if fs_id == target_fid:
                path = self._get_item_path(item)
                filename = item.get("server_filename", path.split("/")[-1])
                return path, [{"fid": fs_id, "file_name": filename}]

        # BFS 队列: [(目录路径, 累计面包屑)]
        queue: List[Tuple[str, List[Dict]]] = []
        for item in file_list:
            if item.get("isdir") == 1:
                path = self._get_item_path(item)
                fs_id = str(item.get("fs_id", ""))
                filename = item.get("server_filename", path.split("/")[-1])
                queue.append((path, [{"fid": fs_id, "file_name": filename}]))

        for _ in range(max_depth):
            next_queue: List[Tuple[str, List[Dict]]] = []
            for current_path, current_breadcrumb in queue:
                try:
                    info = self._api_list_shared_paths(current_path, uk, share_id)
                    items = info.get("list", [])
                except Exception as e:
                    logger.debug(f"[Baidu] 列出分享目录 {current_path} 失败: {e}")
                    continue

                for item in items:
                    item_fid = str(item.get("fs_id", ""))
                    item_name = item.get("server_filename", "")
                    item_path = self._get_item_path(item)
                    new_breadcrumb = current_breadcrumb + [
                        {"fid": item_fid, "file_name": item_name}
                    ]
                    if item_fid == target_fid:
                        return item_path, new_breadcrumb
                    if item.get("isdir") == 1:
                        next_queue.append((item_path, new_breadcrumb))

            if not next_queue:
                break
            queue = next_queue

        logger.warning(
            f"[Baidu] 分享目录树中未找到 fid={target_fid}，深度限制={max_depth}"
        )
        return "", []

    def _resolve_share_fid_to_path(
        self, share_url: str, passcode: str, fid: str
    ) -> str:
        """将分享链接中的 fid (fs_id) 解析为路径字符串"""
        if not fid or fid == "0" or fid == "/":
            return "/"
        if fid.startswith("/"):
            return fid
        if not fid.isdigit():
            logger.warning(f"[Baidu] share fid={fid} 格式无法识别")
            return "/"
        if not self._session:
            return "/"

        try:
            self._api_access_shared(share_url, passcode)
            shared_data = self._api_shared_paths(share_url)
            if not shared_data:
                return "/"

            uk = shared_data.get("share_uk") or shared_data.get("uk")
            if uk:
                uk = int(uk)
            share_id = shared_data.get("shareid")
            bdstoken = shared_data.get("bdstoken", "")

            file_list = shared_data.get("file_list", [])
            if isinstance(file_list, dict):
                file_list = file_list.get("list", [])

            if not file_list:
                return "/"

            path_str, _ = self._bfs_share_tree(
                file_list, uk, share_id, bdstoken, fid
            )
            return path_str if path_str else "/"
        except Exception as e:
            logger.error(f"[Baidu] _resolve_share_fid_to_path 失败: {e}")
            return "/"

    def _resolve_share_path(
        self,
        share_url: str,
        cid: str,
    ) -> List[Dict]:
        """
        在分享目录树中 BFS 查找 cid 的完整路径（面包屑）。
        返回格式与 Quark full_path 一致: [{"fid": "...", "file_name": "..."}]
        """
        if not cid or cid in ("0", "/"):
            return []
        if not self._session:
            return []

        try:
            shared_data = self._api_shared_paths(share_url)
            if not shared_data:
                return []

            uk = shared_data.get("share_uk") or shared_data.get("uk")
            if uk:
                uk = int(uk)
            share_id = shared_data.get("shareid")
            bdstoken = shared_data.get("bdstoken", "")

            file_list = shared_data.get("file_list", [])
            if isinstance(file_list, dict):
                file_list = file_list.get("list", [])

            if not file_list:
                return []

            _, breadcrumb = self._bfs_share_tree(
                file_list, uk, share_id, bdstoken, cid
            )
            return breadcrumb
        except Exception as e:
            logger.error(f"[Baidu] _resolve_share_path 失败: {e}")
            return []

    # ==================== 公共接口实现 ====================
    def get_stoken(self, pwd_id: str, passcode: str = "") -> Dict:
        """获取分享令牌（验证分享链接有效性）"""
        if not self._session:
            return {"status": 500, "code": 1, "message": "百度网盘客户端未初始化"}

        try:
            share_url = f"https://pan.baidu.com/s/{pwd_id}"
            self._api_access_shared(share_url, passcode)
            return {
                "status": 200,
                "code": 0,
                "data": {
                    "stoken": f"{pwd_id}:{passcode}",
                    "share_id": pwd_id,
                },
                "message": "success",
            }
        except Exception as e:
            error_msg = str(e)
            logger.error(f"[Baidu] 访问分享失败: {error_msg}")
            errno_match = re.search(r"errno[=:]?\s*(-?\d+)", error_msg)
            if errno_match:
                errno = int(errno_match.group(1))
                return {
                    "status": 400,
                    "code": errno,
                    "message": self._get_error_message(errno),
                }

        return {"status": 400, "code": 1, "message": "分享链接无效或已失效"}

    def get_detail(
        self,
        pwd_id: str,
        stoken: str,
        pdir_fid: str,
        _fetch_share: int = 0,
        fetch_share_full_path: int = 0,
    ) -> Dict:
        """获取分享文件详情列表"""
        if not self._session:
            return {"code": 1, "message": "百度网盘客户端未初始化", "data": {"list": []}}

        try:
            parts = stoken.split(":") if stoken else [pwd_id, ""]
            share_id = parts[0]
            passcode = parts[1] if len(parts) > 1 else ""

            share_url = f"https://pan.baidu.com/s/{share_id}"
            self._api_access_shared(share_url, passcode)

            # 获取分享数据
            shared_data = self._api_shared_paths(share_url)
            if not shared_data:
                return {
                    "code": 0,
                    "message": "success",
                    "data": {"list": [], "full_path": []},
                    "metadata": {"_total": 0},
                }

            uk = shared_data.get("share_uk") or shared_data.get("uk")
            if uk:
                uk = int(uk)
            share_id_num = shared_data.get("shareid")
            bdstoken = shared_data.get("bdstoken", "")

            file_list = shared_data.get("file_list", [])
            if isinstance(file_list, dict):
                file_list = file_list.get("list", [])

            if not file_list:
                return {
                    "code": 0,
                    "message": "success",
                    "data": {"list": [], "full_path": []},
                    "metadata": {"_total": 0},
                }

            # 解析 pdir_fid
            is_root = not pdir_fid or pdir_fid in ("0", "/")
            remote_path = ""
            full_path = []

            if is_root:
                # 根目录使用第一个文件的路径的父目录
                first_item = file_list[0]
                first_path = self._get_item_path(first_item)
                remote_path = "/".join(first_path.split("/")[:-1]) or "/"
            elif pdir_fid.startswith("/"):
                remote_path = pdir_fid
            elif pdir_fid.isdigit():
                # 通过 BFS 一次性获取路径和面包屑
                path_str, breadcrumb = self._bfs_share_tree(
                    file_list, uk, share_id_num, bdstoken, pdir_fid
                )
                if path_str:
                    remote_path = path_str
                else:
                    first_item = file_list[0]
                    remote_path = self._get_item_path(first_item)
                if fetch_share_full_path:
                    full_path = breadcrumb
            else:
                logger.warning(f"[Baidu] pdir_fid={pdir_fid} 格式无法识别，使用根目录")
                first_item = file_list[0]
                remote_path = self._get_item_path(first_item)

            # 获取文件列表
            if is_root:
                # 根目录直接使用 file_list
                folder_files = file_list
            else:
                # 子目录通过 API 获取
                info = self._api_list_shared_paths(remote_path, uk, share_id_num)
                folder_files = info.get("list", [])

            if not folder_files:
                return {
                    "code": 0,
                    "message": "success",
                    "data": {"list": [], "full_path": full_path},
                    "metadata": {"_total": 0},
                }

            # 转换文件列表
            result_list = [self._convert_shared_item(item) for item in folder_files]

            return {
                "code": 0,
                "message": "success",
                "data": {"list": result_list, "full_path": full_path},
                "metadata": {"_total": len(result_list)},
            }

        except Exception as e:
            logger.error(f"[Baidu] 获取分享详情失败: {e}")
            return {"code": 1, "message": f"获取分享详情失败: {e}", "data": {"list": []}}

    def _convert_shared_item(self, item: Dict) -> Dict:
        """转换百度分享文件项为统一格式"""
        is_dir = item.get("isdir") == 1
        fs_id = str(item.get("fs_id", ""))
        path = self._get_item_path(item)
        filename = item.get("server_filename") or path.split("/")[-1]

        return {
            "fid": fs_id,
            "file_name": filename,
            "file_type": 0 if is_dir else 1,
            "dir": is_dir,
            "size": item.get("size", 0),
            "updated_at": item.get("server_mtime", 0),
            "share_fid_token": fs_id,
            "path": path,
        }

    def ls_dir(self, pdir_fid: str, max_items: int = 0, **kwargs) -> Dict:
        """列出用户网盘目录内容"""
        if not self._session:
            return {"code": 1, "message": "百度网盘客户端未初始化", "data": {"list": []}}

        try:
            remote_path = self._resolve_fid_to_path(str(pdir_fid) if pdir_fid else "0")
            info = self._api_list(remote_path)

            if info.get("errno"):
                return {
                    "code": info.get("errno"),
                    "message": self._get_error_message(info.get("errno")),
                    "data": {"list": []},
                }

            file_list = []
            for item in info.get("list", []):
                fs_id = str(item.get("fs_id", ""))
                path = item.get("path", "")
                server_filename = path.split("/")[-1]
                is_dir = item.get("isdir") == 1

                file_info = {
                    "fid": path,  # 使用 path 作为 fid
                    "file_name": server_filename,
                    "file_type": 0 if is_dir else 1,
                    "dir": is_dir,
                    "size": item.get("size", 0),
                    "updated_at": item.get("server_mtime", 0),
                    "share_fid_token": fs_id,
                    "path": path,
                }
                file_list.append(file_info)

            return {
                "code": 0,
                "message": "success",
                "data": {"list": file_list},
                "metadata": {"_total": len(file_list)},
            }

        except Exception as e:
            logger.error(f"[Baidu] 列出目录失败: {e}")
            return {"code": 1, "message": f"列出目录失败: {e}", "data": {"list": []}}

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
        if not self._session:
            return {"code": 1, "message": "百度网盘客户端未初始化", "data": {}}

        try:
            parts = stoken.split(":") if stoken else [pwd_id, ""]
            share_id = parts[0]
            passcode = parts[1] if len(parts) > 1 else ""

            share_url = f"https://pan.baidu.com/s/{share_id}"
            remote_dir = self._resolve_fid_to_path(to_pdir_fid if to_pdir_fid else "0")

            # --- 记录转存前目标目录的文件列表 ---
            before_items = {}  # {fid: file_name}
            try:
                before_dir = self.ls_dir(to_pdir_fid if to_pdir_fid else "0")
                if before_dir.get("code") == 0:
                    for item in before_dir.get("data", {}).get("list", []):
                        before_items[item.get("fid", "")] = item.get("file_name", "")
            except Exception:
                pass

            # 访问分享并获取元数据
            self._api_access_shared(share_url, passcode)
            shared_data = self._api_shared_paths(share_url)

            if not shared_data:
                return {"code": 1, "message": "无法获取分享信息", "data": {}}

            uk = shared_data.get("share_uk") or shared_data.get("uk")
            if uk:
                uk = int(uk)
            share_id_num = shared_data.get("shareid")
            bdstoken = shared_data.get("bdstoken", "")

            # 转存文件
            fs_ids = [int(fid) for fid in fid_token_list if fid and fid.isdigit()]

            result = self._api_transfer_shared_paths(
                remote_dir, fs_ids, uk, share_id_num, bdstoken, share_url
            )

            # --- 转存后列目录，按文件名建立新 fid 映射 ---
            time.sleep(5)
            name_to_new_fid = {}  # {file_name: new_fid}
            try:
                after_dir = self.ls_dir(to_pdir_fid if to_pdir_fid else "0")
                if after_dir.get("code") == 0:
                    for item in after_dir.get("data", {}).get("list", []):
                        fid = item.get("fid", "")
                        fname = item.get("file_name", "")
                        # 只记录新增的文件（不在转存前的 fid 列表中）
                        if fid and fid not in before_items:
                            name_to_new_fid[fname] = fid
            except Exception as e:
                logger.error(f"[Baidu] 转存后获取目录失败: {e}")

            # --- 按 file_names 顺序组装 save_as_top_fids ---
            saved_fids = []
            if file_names:
                for fname in file_names:
                    new_fid = name_to_new_fid.get(fname, "")
                    if new_fid:
                        saved_fids.append(new_fid)
                    else:
                        # 如果按文件名找不到，可能是文件名有特殊字符被改变
                        # 尝试模糊匹配（去除特殊字符后比较）
                        fname_clean = re.sub(r'[^\w\s\.]', '', fname)
                        found = False
                        for k, v in name_to_new_fid.items():
                            k_clean = re.sub(r'[^\w\s\.]', '', k)
                            if fname_clean == k_clean:
                                saved_fids.append(v)
                                found = True
                                break
                        if not found:
                            logger.warning(f"[Baidu] 未找到文件 '{fname}' 的新 fid")
                            saved_fids.append("")  # 占位，保持索引对齐
            else:
                # 兼容旧调用方式：直接返回新增文件的 fid 列表
                saved_fids = list(name_to_new_fid.values())

            if result.get("errno") == 0 or not result.get("errno"):
                return {
                    "code": 0,
                    "message": "success",
                    "data": {
                        "task_id": f"baidu_sync_{share_id}",
                        "save_as_top_fids": saved_fids,
                        "_sync": True,
                    },
                }
            else:
                errno = result.get("errno", 1)
                return {
                    "code": errno,
                    "message": self._get_error_message(errno),
                    "data": {},
                }

        except Exception as e:
            error_msg = str(e)
            logger.error(f"[Baidu] 转存失败: {error_msg}")
            errno_match = re.search(r"errno[=:]?\s*(-?\d+)", error_msg)
            if errno_match:
                errno = int(errno_match.group(1))
                return {"code": errno, "message": self._get_error_message(errno), "data": {}}
            return {"code": 1, "message": f"转存失败: {error_msg}", "data": {}}

    def query_task(self, task_id: str) -> Dict:
        """查询任务状态（百度网盘转存是同步操作）"""
        return {
            "status": 200,
            "code": 0,
            "data": {
                "status": 2,  # 2 = 完成
                "task_title": "转存文件",
            },
            "message": "success",
        }

    def mkdir(self, dir_path: str) -> Dict:
        """创建目录"""
        if not self._session:
            return {"code": 1, "message": "百度网盘客户端未初始化"}

        try:
            if not dir_path.startswith("/"):
                dir_path = "/" + dir_path

            info = self._api_makedir(dir_path)

            if info.get("errno") and info.get("errno") != 0:
                errno = info.get("errno")
                # 目录已存在也算成功
                if errno == 31061:
                    dir_name = dir_path.rstrip("/").split("/")[-1]
                    return {
                        "code": 0,
                        "message": "目录已存在",
                        "data": {"fid": dir_path, "file_name": dir_name},
                    }
                return {"code": errno, "message": self._get_error_message(errno)}

            dir_name = dir_path.rstrip("/").split("/")[-1]
            return {
                "code": 0,
                "message": "success",
                "data": {"fid": dir_path, "file_name": dir_name},
            }

        except Exception as e:
            error_msg = str(e)
            logger.error(f"[Baidu] 创建目录失败: {error_msg}")
            if "31061" in error_msg or "already" in error_msg.lower():
                dir_name = dir_path.rstrip("/").split("/")[-1]
                return {
                    "code": 0,
                    "message": "目录已存在",
                    "data": {"fid": dir_path, "file_name": dir_name},
                }
            return {"code": 1, "message": f"创建目录失败: {error_msg}"}

    def rename(self, fid: str, file_name: str) -> Dict:
        """重命名文件"""
        if not self._session:
            return {"code": 1, "message": "百度网盘客户端未初始化"}

        try:
            old_path = self._resolve_fid_to_path(fid)
            if old_path == "/":
                return {"code": 1, "message": "未找到文件路径，请先刷新目录"}

            parent_path = "/".join(old_path.rstrip("/").split("/")[:-1]) or "/"
            new_path = f"{parent_path}/{file_name}"

            param = [{"from": old_path, "to": new_path}]
            info = self._api_file_operate("move", param)

            if info.get("errno") and info.get("errno") != 0:
                errno = info.get("errno")
                return {"code": errno, "message": self._get_error_message(errno)}

            return {"code": 0, "message": "success"}

        except Exception as e:
            logger.error(f"[Baidu] 重命名失败: {e}")
            return {"code": 1, "message": f"重命名失败: {e}"}

    def delete(self, filelist: List[str]) -> Dict:
        """删除文件"""
        if not self._session:
            return {"code": 1, "message": "百度网盘客户端未初始化"}

        try:
            paths = []
            for fid in filelist:
                path = self._resolve_fid_to_path(fid)
                if path != "/":
                    paths.append(path)

            if not paths:
                return {"code": 1, "message": "未找到要删除的文件"}

            param = [{"path": p} for p in paths]
            info = self._api_file_operate("delete", param)

            if info.get("errno") and info.get("errno") != 0:
                errno = info.get("errno")
                return {"code": errno, "message": self._get_error_message(errno)}

            return {"code": 0, "message": "success"}

        except Exception as e:
            logger.error(f"[Baidu] 删除失败: {e}")
            return {"code": 1, "message": f"删除失败: {e}"}

    def get_fids(self, file_paths: List[str]) -> List[Dict]:
        """根据路径获取文件 ID"""
        if not self._session:
            return []

        results = []
        for path in file_paths:
            if not path or path == "/":
                results.append({"file_path": "/", "fid": "/"})
                continue

            path = path.strip()
            if not path.startswith("/"):
                path = "/" + path

            try:
                parent_path = "/".join(path.rstrip("/").split("/")[:-1]) or "/"
                target_name = path.rstrip("/").split("/")[-1]
                info = self._api_list(parent_path)

                for item in info.get("list", []):
                    item_path = item.get("path", "")
                    if item_path.split("/")[-1] == target_name:
                        results.append({"file_path": path, "fid": path})
                        break
            except Exception:
                pass

        return results

    def extract_url(self, url: str) -> Tuple[Optional[str], str, Any, List]:
        """解析百度网盘分享链接"""
        pwd_id = None
        passcode = ""
        pdir_fid = "/"
        paths = []

        # 格式1: /s/1xxxxx
        match_s = re.search(r"/s/([a-zA-Z0-9_-]+)", url)
        if match_s:
            pwd_id = match_s.group(1)
        else:
            # 格式2: surl=xxxxx
            match_surl = re.search(r"surl=([a-zA-Z0-9_-]+)", url)
            if match_surl:
                pwd_id = "1" + match_surl.group(1)

        # 提取提取码
        match_pwd = re.search(r"(?:pwd|password)=([a-zA-Z0-9]+)", url)
        if match_pwd:
            passcode = match_pwd.group(1)
        else:
            match_hash = re.search(r"#([a-zA-Z0-9]{4})\b", url)
            if match_hash:
                passcode = match_hash.group(1)

        # 提取子目录 ID
        if "#/list/share/" in url:
            raw_fid = url.split("#/list/share/")[-1]
            match_fid = re.match(r"(\w+)", raw_fid)
            if match_fid:
                pdir_fid = match_fid.group(1)

        return pwd_id, passcode, pdir_fid, paths

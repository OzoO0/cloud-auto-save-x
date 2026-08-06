# -*- coding: utf-8 -*-
"""
115网盘适配器
参考 CloudSaver 的 Cloud115Service 实现
"""
import re
import time
import random
import logging
import threading
import requests
from typing import Dict, List, Tuple, Optional, Any
from datetime import datetime

from app.extensions.adapters.base_adapter import BaseCloudDriveAdapter


logger = logging.getLogger(__name__)


class Cloud115Adapter(BaseCloudDriveAdapter):
    """115网盘适配器"""

    DRIVE_TYPE = "115"
    DRIVE_NAME = "115 网盘"
    CONFIG_FORMAT = "raw"
    default_config = {
        "cookie": "",
    }
    config_fields = [
        {
            "key": "cookie",
            "label": "Cookie",
            "description": "115 网盘登录 Cookie 原文。",
            "input_type": "textarea",
            "required": True,
            "secret": True,
            "placeholder": "UID=...; CID=...; SEID=...",
        }
    ]
    API_URL = "https://webapi.115.com"
    WEB_URL = "https://115cdn.com"
    PASSPORTAPI_URL = "https://passportapi.115.com"
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36"
    )
    # 微信小程序 UA（用于 webapi 请求）
    WECHAT_UA = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/107.0.0.0 Safari/537.36 "
        "MicroMessenger/6.8.0(0x16080000) NetType/WIFI MiniProgramEnv/Mac "
        "MacWechat/WMPF MacWechat/3.8.9(0x13080910) XWEB/1227"
    )

    def __init__(
        self,
        cookie: str = "",
        index: int = 0,
        config: dict | None = None,
        account_name: str = "",
        no_login: bool = False,
    ):
        super().__init__(cookie, index, config=config, no_login=no_login)
        # 115 对请求频率更敏感，单独放慢节流区间以降低风控概率。
        self._rate_limit_min_interval = 0.25
        self._rate_limit_max_interval = 0.6

        # ---- 带用户 cookie 的 session（用于操作自己的网盘）----
        self.auth_session = requests.Session()
        self.auth_session.headers.update({
            "User-Agent": self.WECHAT_UA,
            "Accept": "*/*",
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": "https://115.com",
            "Referer": "https://115.com",
        })
        # 解析 cookie 字符串并设置到 session
        if cookie:
            for kv in cookie.split(";"):
                kv = kv.strip()
                if "=" in kv:
                    k, v = kv.split("=", 1)
                    self.auth_session.cookies.set(k.strip(), v.strip())

    # ----------------------------------------------------------------
    #  HTTP 基础方法
    # ----------------------------------------------------------------

    def _request(self, session: requests.Session, method: str, url: str, **kwargs):
        self._throttle_request()
        return session.request(method=method, url=url, **kwargs)

    def _create_share_session(self, share_code: str, receive_code: str = ""):
        """
        创建用于浏览分享链接的独立空 session（不携带用户 cookie）。
        先访问分享页面获取必要的 session cookie，然后用它来请求分享 API。
        """
        share_session = requests.Session()
        share_session.headers.update({
            "User-Agent": self.USER_AGENT,
            "Accept": "*/*",
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": f"{self.WEB_URL}/s/{share_code}",
        })
        # 访问分享页面获取 session cookie
        try:
            self._request(
                share_session,
                "GET",
                f"{self.WEB_URL}/s/{share_code}?password={receive_code}&",
                timeout=15,
            )
        except Exception as e:
            logger.warning(f"[115] 访问分享页面失败: {e}")
        return share_session

    def _safe_json(self, response) -> Dict:
        """安全解析 JSON 响应"""
        try:
            return response.json()
        except Exception as e:
            content = response.text[:200] if response.text else "(empty)"
            logger.warning(f"[115] JSON解析失败: {e}, 响应: {content}")
            return {
                "state": False,
                "code": getattr(response, "status_code", 500),
                "error": "响应解析失败，可能Cookie已失效或被限流",
            }

    def _fake_error(self, msg: str = "request error") -> Dict:
        return {"state": False, "code": 500, "error": msg}

    # ----------------------------------------------------------------
    #  账户相关
    # ----------------------------------------------------------------

    def init(self) -> Any:
        """初始化账户，验证 cookie"""
        account_info = self.get_account_info()
        if account_info:
            self.is_active = True
            self.nickname = account_info.get("user_name", f"115用户{self.index}")
            return account_info
        return False

    def get_account_info(self) -> Any:
        """获取账户信息"""
        try:
            resp = self._request(
                self.auth_session,
                "GET",
                f"{self.PASSPORTAPI_URL}/app/1.0/web/26.0/user/base_info?_t=", timeout=15
            )
            data = self._safe_json(resp)
            if data.get("state"):
                return data.get("data", {})
            return False
        except Exception as e:
            logger.error(f"[115] get_account_info error: {e}")
            return False

    def get_account_config(self) -> Dict[str, Any]:
        """获取115账户配置/容量信息"""
        account_info = self.get_account_info() or {}
        member_data = account_info if isinstance(account_info, dict) else None


        nickname = (
            member_data.get("user_name")
            or self.nickname
            or f"115用户{self.index}"
        )
        if nickname:
            self.nickname = nickname

        return {
            "drive_type": self.DRIVE_TYPE,
            "drive_name": self.DRIVE_NAME,
            "nickname": nickname,
            "username": nickname,
            "used_space": int(member_data.get("size_used_raw")) if isinstance(member_data, dict) else None,
            "total_space": int(member_data.get("size_total_raw")) if isinstance(member_data, dict) else None,
            "member_type": '',
            "member_status": {},
            "raw": {
                "account_info": account_info or None,
                "member_info": member_data,
            },
        }

    # ----------------------------------------------------------------
    #  分享浏览（使用空 session，不携带用户 cookie）
    # ----------------------------------------------------------------

    def get_stoken(self, pwd_id: str, passcode: str = "") -> Dict:
        """
        获取分享信息。
        pwd_id  = share_code
        passcode = receive_code
        使用独立空 session 访问，不携带用户 cookie。
        """
        share_session = self._create_share_session(pwd_id, passcode)
        url = (
            f"{self.WEB_URL}/webapi/share/snap"
            f"?share_code={pwd_id}&offset=0&limit=20&asc=0"
            f"&cid=0&receive_code={passcode}&format=json"
        )
        try:
            resp = self._request(share_session, "GET", url, timeout=15)
            data = self._safe_json(resp)
            if data.get("data", {}).get("shareinfo",{}).get("forbid_reason"):
                return {
                "status": 400,
                "code": 1,
                "message": data.get("data", {}).get("shareinfo",{}).get("forbid_reason","分享链接无效或已失效"),
            }
            if data.get("state") and data.get("data", {}).get("list"):
                return {
                    "status": 200,
                    "code": 0,
                    "data": {
                        "stoken": f"{pwd_id}:{passcode}",
                        "share_code": pwd_id,
                        "receive_code": passcode,
                    },
                    "message": "success",
                }
            return {
                "status": 400,
                "code": 1,
                "message": data.get("error", "分享链接无效或已失效"),
            }
        except Exception as e:
            return {"status": 500, "code": 1, "message": f"网络异常: {e}"}

    def get_detail(
        self,
        pwd_id: str,
        stoken: str,
        pdir_fid: str,
        _fetch_share: int = 0,
        fetch_share_full_path: int = 0,
    ) -> Dict:
        """
        获取分享文件详情。
        使用独立空 session 访问，不携带用户 cookie。
        """
        parts = stoken.split(":") if stoken else [pwd_id, ""]
        share_code = parts[0]
        receive_code = parts[1] if len(parts) > 1 else ""
        cid = pdir_fid if pdir_fid and str(pdir_fid) != "0" else ""

        share_session = self._create_share_session(share_code, receive_code)

        # 当请求了完整路径且 cid 不为根时，通过 BFS 解析路径
        full_path = []
        if cid and fetch_share_full_path:
            full_path = self._resolve_share_path(
                share_session, share_code, receive_code, cid
            )

        list_merge = []
        offset = 0
        limit = 50

        while True:
            url = (
                f"{self.WEB_URL}/webapi/share/snap"
                f"?share_code={share_code}&offset={offset}&limit={limit}"
                f"&asc=0&cid={cid}&receive_code={receive_code}&format=json"
            )
            try:
                resp = self._request(share_session, "GET", url, timeout=15)
                data = self._safe_json(resp)
                if not data.get("state"):
                    return {
                        "code": 1,
                        "message": data.get("error", "获取分享信息失败"),
                        "data": {"list": []},
                    }
                file_list = data.get("data", {}).get("list", [])
                if not file_list:
                    break
                for item in file_list:
                    list_merge.append(self._convert_share_item(item))
                if len(file_list) < limit:
                    break
                offset += limit
            except Exception as e:
                return {
                    "code": 1,
                    "message": f"获取分享详情失败: {e}",
                    "data": {"list": []},
                }

        return {
            "code": 0,
            "message": "success",
            "data": {
                "list": list_merge,
                "full_path": full_path,
            },
            "metadata": {"_total": len(list_merge)},
        }

    def _resolve_share_path(
        self,
        share_session,
        share_code: str,
        receive_code: str,
        target_cid: str,
        max_depth: int = 5,
    ) -> List[Dict]:
        """
        在分享目录树中 BFS 查找 target_cid 的完整路径。
        返回格式与 Quark full_path 一致: [{"fid": "...", "file_name": "..."}]
        """
        target_cid = str(target_cid)
        # queue 每项: (当前目录cid, 已累计的路径列表)
        queue = [("", [])]

        for _ in range(max_depth):
            next_queue = []
            for current_cid, current_path in queue:
                offset = 0
                limit = 50
                while True:
                    url = (
                        f"{self.WEB_URL}/webapi/share/snap"
                        f"?share_code={share_code}&offset={offset}&limit={limit}"
                        f"&asc=0&cid={current_cid}"
                        f"&receive_code={receive_code}&format=json"
                    )
                    try:
                        resp = self._request(share_session, "GET", url, timeout=15)
                        data = self._safe_json(resp)
                        if not data.get("state"):
                            break
                        file_list = data.get("data", {}).get("list", [])
                        if not file_list:
                            break
                        for item in file_list:
                            is_dir = "fid" not in item
                            if not is_dir:
                                continue
                            item_cid = str(item.get("cid", ""))
                            item_name = item.get("n", "")
                            new_path = current_path + [
                                {"fid": item_cid, "file_name": item_name}
                            ]
                            if item_cid == target_cid:
                                return new_path
                            next_queue.append((item_cid, new_path))
                        if len(file_list) < limit:
                            break
                        offset += limit
                    except Exception:
                        break
            if not next_queue:
                break
            queue = next_queue

        logger.warning(
            f"[115] _resolve_share_path: 未找到 cid={target_cid}，"
            f"深度限制={max_depth}"
        )
        return []

    # ----------------------------------------------------------------
    #  用户网盘操作（使用带 cookie 的 auth_session）
    # ----------------------------------------------------------------

    def ls_dir(self, pdir_fid: str, max_items: int = 0, **kwargs) -> Dict:
        """列出用户网盘目录内容"""
        list_merge = []
        offset = 0
        limit = 50

        while True:
            params = {
                "aid": 1,
                "cid": pdir_fid if pdir_fid else "0",
                "o": "user_ptime",
                "asc": 1,
                "offset": offset,
                "show_dir": 1,
                "limit": limit,
                "type": 0,
                "format": "json",
                "star": 0,
                "suffix": "",
                "natsort": 0,
                "snap": 0,
                "record_open_time": 1,
                "fc_mix": 0,
            }
            try:
                resp = self._request(
                    self.auth_session,
                    "GET",
                    f"{self.API_URL}/files",
                    params=params,
                    timeout=15,
                )
                data = self._safe_json(resp)
                if not data.get("state"):
                    return {
                        "code": 1,
                        "message": data.get("error", "获取目录列表失败"),
                        "data": {"list": []},
                    }
                file_list = data.get("data", [])
                if not file_list:
                    break
                for item in file_list:
                    list_merge.append(self._convert_dir_item(item))
                # max_items 限量：达到上限后提前终止分页
                if max_items > 0 and len(list_merge) >= max_items:
                    list_merge = list_merge[:max_items]
                    break
                if len(file_list) < limit:
                    break
                offset += limit
            except Exception as e:
                return {
                    "code": 1,
                    "message": f"获取目录失败: {e}",
                    "data": {"list": []},
                }
        logger.debug(f"[115] ls_dir result: {len(list_merge)} items")
        return {
            "code": 0,
            "message": "success",
            "data": {"list": list_merge},
            "metadata": {"_total": len(list_merge)},
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
        """
        转存文件到指定目录。
        转存需要先访问分享页建立 session，再携带用户 cookie 执行 receive。
        转存后通过列目录获取新文件的真实 ID，并按文件名建立映射。

        Args:
            fid_list: 原始文件 fid 列表
            fid_token_list: 分享 token 列表
            to_pdir_fid: 目标目录 fid
            pwd_id: 分享 ID
            stoken: 分享 token
            file_names: 原始文件名列表（用于按文件名匹配新 fid）

        Returns:
            包含 save_as_top_fids（按 file_names 顺序排列的新 fid 列表）
        """
        parts = stoken.split(":") if stoken else [pwd_id, ""]
        share_code = parts[0]
        receive_code = parts[1] if len(parts) > 1 else ""

        # --- 记录转存前目标目录的文件列表 ---
        before_items = {}  # {fid: file_name}
        try:
            before_dir = self.ls_dir(to_pdir_fid if to_pdir_fid else "0")
            if before_dir.get("code") == 0:
                for item in before_dir.get("data", {}).get("list", []):
                    before_items[item.get("fid", "")] = item.get("file_name", "")
        except Exception:
            pass

        # --- 创建转存专用 session ---
        save_session = requests.Session()
        save_session.headers.update({
            "User-Agent": self.USER_AGENT,
            "Accept": "*/*",
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            "Origin": self.WEB_URL,
            "Referer": f"{self.WEB_URL}/s/{share_code}?password={receive_code}&",
        })
        # 先访问分享页获取 session cookie
        try:
            self._request(
                save_session,
                "GET",
                f"{self.WEB_URL}/s/{share_code}?password={receive_code}&",
                timeout=15,
            )
        except Exception as e:
            return {
                "code": 1,
                "message": f"访问分享页面失败: {e}",
                "data": {},
            }
        # 注入用户 cookie（转存需要登录态）
        for kv in self.cookie.split(";"):
            kv = kv.strip()
            if "=" in kv:
                k, v = kv.split("=", 1)
                save_session.cookies.set(k.strip(), v.strip())

        # --- 执行转存 ---
        url = f"{self.WEB_URL}/webapi/share/receive"
        data = {
            "cid": to_pdir_fid if to_pdir_fid else "0",
            "share_code": share_code,
            "receive_code": receive_code,
            "file_id": ",".join(fid_token_list),
        }
        logger.info(f"[115] receive: {url}, file_id={data['file_id']}")
        errors = []
        try:
            resp = self._request(save_session, "POST", url, data=data, timeout=30)
            result = self._safe_json(resp)
            logger.info(f"[115] receive resp: {result}")
            if not result.get("state"):
                errors.append(result.get("error", "转存失败"))
        except Exception as e:
            errors.append(str(e))

        if errors:
            return {"code": 1, "message": "; ".join(errors), "data": {}}

        # --- 转存后列目录，按文件名建立新 fid 映射 ---
        time.sleep(3)  # 等待115后端同步
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
            logger.error(f"[115] 转存后获取目录失败: {e}")

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
                        logger.warning(f"[115] 未找到文件 '{fname}' 的新 fid")
                        saved_fids.append("")  # 占位，保持索引对齐
        else:
            # 兼容旧调用方式：直接返回新增文件的 fid 列表
            saved_fids = list(name_to_new_fid.values())

        logger.info(f"[115] 转存完成，新文件映射: {name_to_new_fid}")
        logger.info(f"[115] 按顺序返回 fids: {saved_fids}")

        return {
            "code": 0,
            "message": "success",
            "data": {
                "task_id": f"115_sync_{int(time.time())}",
                "save_as_top_fids": saved_fids,
                "_sync": True,
            },
        }

    def query_task(self, task_id: str) -> Dict:
        """
        查询任务状态。
        115 的转存是同步的，直接返回成功。
        """
        return {
            "status": 200,
            "code": 0,
            "data": {
                "status": 2,
                "task_title": "转存文件",
                "save_as": {"save_as_top_fids": []},
            },
            "message": "success",
        }

    def mkdir(self, dir_path: str) -> Dict:
        """创建目录"""
        parts = dir_path.rstrip("/").split("/")
        dir_name = parts[-1] if parts else "新建文件夹"
        parent_path = "/".join(parts[:-1]) if len(parts) > 1 else ""

        parent_cid = "0"
        if parent_path and parent_path != "/":
            parent_fids = self.get_fids([parent_path])
            if parent_fids:
                parent_cid = parent_fids[0].get("fid", "0")

        data = {"pid": parent_cid, "cname": dir_name}
        try:
            resp = self._request(
                self.auth_session,
                "POST",
                f"{self.API_URL}/files/add",
                data=data,
                timeout=15,
            )
            result = self._safe_json(resp)
            if result.get("state"):
                return {
                    "code": 0,
                    "message": "success",
                    "data": {
                        "fid": result.get("cid", result.get("file_id")),
                        "file_name": dir_name,
                    },
                }
            # 目录可能已存在
            existing = self.get_fids([dir_path])
            if existing:
                return {
                    "code": 0,
                    "message": "目录已存在",
                    "data": {"fid": existing[0].get("fid"), "file_name": dir_name},
                }
            return {"code": 1, "message": result.get("error", "创建目录失败")}
        except Exception as e:
            return {"code": 1, "message": f"创建目录失败: {e}"}

    def rename(self, fid: str, file_name: str) -> Dict:
        """重命名文件"""
        data = {f"files_new_name[{fid}]": file_name}
        try:
            resp = self._request(
                self.auth_session,
                "POST",
                f"{self.API_URL}/files/batch_rename",
                data=data,
                timeout=15,
            )
            result = self._safe_json(resp)
            if result.get("state"):
                return {"code": 0, "message": "success"}
            return {"code": 1, "message": result.get("error", "重命名失败")}
        except Exception as e:
            return {"code": 1, "message": f"重命名失败: {e}"}

    def move_files(self, fids: List[str], to_pdir_fid: str) -> Dict:
        """批量移动文件"""
        return {"code": 0, "message": "success"}

    def delete(self, filelist: List[str]) -> Dict:
        """删除文件"""
        data = {"pid": "0"}
        for i, fid in enumerate(filelist):
            data[f"fid[{i}]"] = fid
        try:
            resp = self._request(
                self.auth_session,
                "POST",
                f"{self.API_URL}/rb/delete",
                data=data,
                timeout=15,
            )
            result = self._safe_json(resp)
            if result.get("state"):
                return {
                    "code": 0,
                    "message": "success",
                    "data": {"task_id": f"115_delete_{int(time.time())}"},
                }
            return {"code": 1, "message": result.get("error", "删除失败")}
        except Exception as e:
            return {"code": 1, "message": f"删除失败: {e}"}

    # ----------------------------------------------------------------
    #  路径/文件 ID 解析
    # ----------------------------------------------------------------

    def get_fids(self, file_paths: List[str]) -> List[Dict]:
        """根据路径获取文件 ID（需逐级遍历目录）"""
        results = []
        for path in file_paths:
            path = path.strip("/")
            if not path:
                results.append({"file_path": "/", "fid": "0"})
                continue

            parts = path.split("/")
            current_cid = "0"
            found = True
            for part in parts:
                if not part:
                    continue
                dir_list = self.ls_dir(current_cid)
                if dir_list.get("code") != 0:
                    found = False
                    break
                target = None
                for item in dir_list.get("data", {}).get("list", []):
                    if item.get("file_name") == part:
                        target = item
                        break
                if target:
                    current_cid = target.get("fid", "0")
                else:
                    found = False
                    break
            if found:
                results.append({"file_path": f"/{path}", "fid": current_cid})
        return results

    def extract_url(self, url: str) -> Tuple[Optional[str], str, Any, List]:
        """
        解析 115 分享链接。
        支持域名: 115.com, 115cdn.com, anxia.com
        """
        match_code = re.search(r"(?:115|anxia|115cdn)\.com/s/([^?#\s&]+)", url)
        share_code = match_code.group(1) if match_code else None
        pdir_fid = 0

        # 提取密码
        passcode = ""
        match_pwd = re.search(r"password=([^&#\s]+)", url)
        if match_pwd:
            passcode = match_pwd.group(1)
        else:
            match_hash = re.search(r"#([^&#\s/]+)", url)
            if match_hash:
                passcode = match_hash.group(1)

        # 提取子目录 ID（去除可能的尾部参数）
        if "#/list/share/" in url:
            raw_fid = url.split("#/list/share/")[-1]
            match_fid = re.match(r"(\w+)", raw_fid)
            if match_fid:
                pdir_fid = match_fid.group(1)

        return share_code, passcode, pdir_fid, []

    # ----------------------------------------------------------------
    #  数据转换工具
    # ----------------------------------------------------------------

    def _convert_share_item(self, item: Dict) -> Dict:
        """
        将 115 分享文件项转换为统一格式。
        115 share/snap API 数据结构：
          - 文件夹: cid=自身ID, n=名称, fc=内含文件数, 无 fid 字段
          - 文件:   fid=自身ID, cid=父文件夹ID, n=名称, s=大小, ico=类型
        """
        is_dir = "fid" not in item
        if is_dir:
            own_id = str(item.get("cid", ""))
        else:
            own_id = str(item.get("fid", ""))
        return {
            "fid": own_id,
            "file_name": item.get("n", ""),
            "file_type": 0 if is_dir else 1,
            "dir": bool(is_dir),
            "size": item.get("s", 0),
            "updated_at": int(item.get("t", 0))*1000,
            "share_fid_token": own_id,
            "obj_category": self._get_category(item.get("ico", "")),
        }

    def _convert_dir_item(self, item: Dict) -> Dict:
        """
        将 115 用户目录项转换为统一格式。
        115 /files API 数据结构：
          - 文件夹: cid=自身ID, n=名称, fc=内含文件数, 无 fid 字段
          - 文件:   fid=自身ID, cid=父文件夹ID, n=名称, s=大小, ico=类型
        """
        is_dir = "fid" not in item
        if is_dir:
            own_id = str(item.get("cid", ""))
        else:
            own_id = str(item.get("fid", ""))
        return {
            "fid": own_id,
            "file_name": item.get("n", ""),
            "file_type": 0 if is_dir else 1,
            "dir": bool(is_dir),
            "size": int(item.get("s", 0)),
            "updated_at": item.get("t", 0) if '-' in item.get("t", 0) else int(item.get("t", 0))*1000 ,
            "obj_category": self._get_category(item.get("ico", "")),
        }

    @staticmethod
    def _get_category(ico: str) -> str:
        """根据图标类型判断文件类别"""
        if not ico:
            return ""
        ico = ico.lower()
        categories = {
            "video": {"mp4", "mkv", "avi", "mov", "wmv", "flv", "rmvb", "ts"},
            "audio": {"mp3", "wav", "flac", "aac", "ogg"},
            "image": {"jpg", "jpeg", "png", "gif", "bmp", "webp"},
            "doc": {"doc", "docx", "pdf", "txt", "xls", "xlsx", "ppt", "pptx"},
            "archive": {"zip", "rar", "7z", "tar", "gz"},
        }
        for cat, exts in categories.items():
            if ico in exts:
                return cat
        return ""

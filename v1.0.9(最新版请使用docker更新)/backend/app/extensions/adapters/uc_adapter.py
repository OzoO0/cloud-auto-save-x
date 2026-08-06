# -*- coding: utf-8 -*-
"""
UC网盘适配器
基于夸克网盘适配器模板（同属阿里系，API结构类似）
"""
import re
import time
import random
import logging
import requests
from typing import Dict, List, Tuple, Optional, Any
from datetime import datetime

from app.extensions.adapters.base_adapter import BaseCloudDriveAdapter


logger = logging.getLogger(__name__)


class UCAdapter(BaseCloudDriveAdapter):
    """UC网盘适配器"""

    DRIVE_TYPE = "uc"
    DRIVE_NAME = "UC 网盘"
    CONFIG_FORMAT = "raw"
    default_config = {
        "cookie": "",
    }
    config_fields = [
        {
            "key": "cookie",
            "label": "Cookie",
            "description": "UC 网盘登录 Cookie 原文。",
            "input_type": "textarea",
            "required": True,
            "secret": True,
            "placeholder": "service_ticket=...; __uid=...",
        }
    ]
    
    # UC 网盘 API 域名
    BASE_URL = "https://pc-api.uc.cn"
    BASE_URL_DRIVE = "https://drive.uc.cn"
    
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
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
        self._cookies_dict: Dict[str, str] = {}
        
        self._share_folder_fid: Optional[str] = None
        
        # 解析 cookie
        if cookie:
            for item in cookie.split(";"):
                item = item.strip()
                if "=" in item:
                    k, v = item.split("=", 1)
                    self._cookies_dict[k.strip()] = v.strip()

    def _send_request(self, method: str, url: str, **kwargs) -> requests.Response:
        """发送 HTTP 请求"""
        self._throttle_request()
        headers = {
            "cookie": self.cookie,
            "content-type": "application/json",
            "user-agent": self.USER_AGENT,
            "origin": self.BASE_URL_DRIVE,
            "referer": f"{self.BASE_URL_DRIVE}/",
        }
        if "headers" in kwargs:
            headers.update(kwargs["headers"])
            del kwargs["headers"]

        try:
            response = requests.request(method, url, headers=headers, timeout=30, **kwargs)
            return response
        except Exception as e:
            logger.error(f"[UC] 请求失败: {e}")
            fake_response = requests.Response()
            fake_response.status_code = 500
            fake_response._content = b'{"status": 500, "code": 1, "message": "request error"}'
            return fake_response

    def _safe_json(self, response: requests.Response) -> Dict:
        """安全解析 JSON 响应"""
        try:
            return response.json()
        except Exception as e:
            logger.warning(f"[UC] JSON解析失败: {e}")
            return {"code": 1, "status": 500, "message": "响应解析失败"}

    def init(self) -> Any:
        """初始化账户"""
        account_info = self.get_account_info()
        if account_info:
            self.is_active = True
            self.nickname = account_info.get("nickname", f"UC用户{self.index}")
            return account_info
        return False

    def get_account_info(self) -> Any:
        """获取账户信息"""
        # UC 网盘账户信息 API
        url = f"{self.BASE_URL_DRIVE}/account/info"
        params = {"pr": "UCBrowser", "fr": "pc"}
        
        try:
            response = self._send_request("GET", url, params=params)
            data = self._safe_json(response)
            if data.get("data"):
                return data["data"]
        except Exception as e:
            logger.error(f"[UC] 获取账户信息失败: {e}")
        
        return False

    def get_account_config(self) -> Dict[str, Any]:
        """获取 UC 账户配置/容量信息"""
        account_info = self.get_account_info() or {}
        member_info = self._get_member_info()
        member_data = member_info.get("data") if isinstance(member_info, dict) else None

        nickname = (
            account_info.get("nickname")
            or account_info.get("nick_name")
            or self.nickname
            or f"UC用户{self.index}"
        )
        if nickname:
            self.nickname = nickname

        return {
            "drive_type": self.DRIVE_TYPE,
            "drive_name": self.DRIVE_NAME,
            "nickname": nickname,
            "username": nickname,
            "used_space": member_data.get("use_capacity") if isinstance(member_data, dict) else None,
            "total_space": member_data.get("total_capacity") if isinstance(member_data, dict) else None,
            "member_type": member_data.get("member_type") if isinstance(member_data, dict) else None,
            "member_status": member_data.get("member_status") if isinstance(member_data, dict) else None,
            "raw": {
                "account_info": account_info or None,
                "member_info": member_data,
            },
        }

    def _get_member_info(self) -> Dict[str, Any]:
        """获取 UC 会员/容量信息"""
        url = f"{self.BASE_URL}/1/clouddrive/member"
        params = {
            "pr": "UCBrowser",
            "fr": "pc",
            "fetch_subscribe": "true",
            "_ch": "home",
        }

        try:
            response = self._send_request("GET", url, params=params)
            result = self._safe_json(response)
            if result.get("code") == 0 and result.get("data"):
                return result
        except Exception as e:
            logger.error(f"[UC] 获取会员信息失败: {e}")

        return {}

    def get_stoken(self, pwd_id: str, passcode: str = "") -> Dict:
        """获取分享令牌"""
        url = f"{self.BASE_URL}/1/clouddrive/share/sharepage/token"
        params = {"pr": "UCBrowser", "fr": "pc"}
        payload = {"pwd_id": pwd_id, "passcode": passcode}

        try:
            response = self._send_request("POST", url, json=payload, params=params)
            result = self._safe_json(response)
            return result
        except Exception as e:
            logger.error(f"[UC] 获取分享令牌失败: {e}")
            return {"status": 500, "code": 1, "message": f"获取分享令牌失败: {e}"}

    def get_detail(
        self,
        pwd_id: str,
        stoken: str,
        pdir_fid: str,
        _fetch_share: int = 0,
        fetch_share_full_path: int = 0,
    ) -> Dict:
        """获取分享文件详情"""
        list_merge = []
        page = 1
        result = {}

        while True:
            url = f"{self.BASE_URL}/1/clouddrive/share/sharepage/detail"
            params = {
                "pr": "UCBrowser",
                "fr": "pc",
                "pwd_id": pwd_id,
                "stoken": stoken,
                "pdir_fid": pdir_fid,
                "force": "0",
                "_page": page,
                "_size": "50",
                "_fetch_banner": "0",
                "_fetch_share": _fetch_share,
                "_fetch_total": "1",
                "_sort": "file_type:asc,updated_at:desc",
                "fetch_share_full_path": fetch_share_full_path,
            }

            try:
                response = self._send_request("GET", url, params=params)
                result = self._safe_json(response)
                
                if result.get("code") != 0:
                    return result
                
                file_list = result.get("data", {}).get("list", [])
                if file_list:
                    list_merge.extend(file_list)
                    page += 1
                else:
                    break
                
                total = result.get("metadata", {}).get("_total", 0)
                if len(list_merge) >= total:
                    break
                    
            except Exception as e:
                logger.error(f"[UC] 获取分享详情失败: {e}")
                return {"code": 1, "message": f"获取分享详情失败: {e}", "data": {"list": []}}

        # 保留完整的API响应（包含full_path等字段），仅替换合并后的文件列表
        if result.get("data"):
            result["data"]["list"] = list_merge
        else:
            result["data"] = {"list": list_merge}
        return result

    def ls_dir(self, pdir_fid: str, max_items: int = 0, **kwargs) -> Dict:
        """列出目录内容"""
        list_merge = []
        page = 1

        while True:
            url = f"{self.BASE_URL}/1/clouddrive/file/sort"
            params = {
                "pr": "UCBrowser",
                "fr": "pc",
                "pdir_fid": pdir_fid,
                "_page": page,
                "_size": "50",
                "_fetch_total": "1",
                "_fetch_sub_dirs": "0",
                "_sort": "file_type:asc,updated_at:desc",
                "_fetch_full_path": kwargs.get("fetch_full_path", 0),
            }

            try:
                response = self._send_request("GET", url, params=params)
                result = self._safe_json(response)
                
                if result.get("code") != 0:
                    return result
                
                file_list = result.get("data", {}).get("list", [])
                if file_list:
                    list_merge.extend(file_list)
                    page += 1
                else:
                    break
                
                # max_items 限量：达到上限后提前终止分页
                if max_items > 0 and len(list_merge) >= max_items:
                    list_merge = list_merge[:max_items]
                    break

                total = result.get("metadata", {}).get("_total", 0)
                if len(list_merge) >= total:
                    break
                    
            except Exception as e:
                logger.error(f"[UC] 列出目录失败: {e}")
                return {"code": 1, "message": f"列出目录失败: {e}", "data": {"list": []}}

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
    ) -> Dict:
        """转存文件"""
        url = f"{self.BASE_URL}/1/clouddrive/share/sharepage/save"
        params = {
            "entry": "update_share",
            "pr": "UCBrowser",
            "fr": "pc",
            "__dt": int(random.uniform(1, 5) * 60 * 1000),
            "__t": datetime.now().timestamp(),
        }
        payload = {
            "fid_list": fid_list,
            "fid_token_list": fid_token_list,
            "to_pdir_fid": to_pdir_fid,
            "pwd_id": pwd_id,
            "stoken": stoken,
            "pdir_fid": "0",
            "scene": "link",
        }
        logger.debug(f"[UC] 转存文件参数: {payload}")
        try:
            response = self._send_request("POST", url, json=payload, params=params)
            result = self._safe_json(response)

            # 检查容量限制错误
            msg = result.get("message", "")
            if "capacity limit" in msg.lower():
                logger.error("[UC] 网盘容量不足，无法转存")
                return {"code": 1, "status": 400, "message": "UC网盘容量不足，请清理空间后重试", "data": {}}
            logger.debug(f"[UC] 转存结果: {result}")
            return result
        except Exception as e:
            logger.error(f"[UC] 转存失败: {e}")
            return {"code": 1, "message": f"转存失败: {e}", "data": {}}

    def unarchive(self, fid: str, to_pdir_fid: str) -> Dict:
        url = f"{self.BASE_URL}/1/clouddrive/archive/unarchive"
        params = {
            "pr": "UCBrowser",
            "fr": "pc",
            "__dt": int(random.uniform(1, 5) * 60 * 1000),
            "__t": datetime.now().timestamp(),
        }
        payload = {
            "fid": fid,
            "pwd": "",
            "select_mode": 0,
            "path_no_list": [],
            "curr_path_no": 0,
            "remember_pwd": False,
            "conflict_mode": 3,
            "suffix_type": 0,
            "to_pdir_fid": to_pdir_fid,
        }
        try:
            response = self._send_request("POST", url, json=payload, params=params)
            return self._safe_json(response)
        except Exception as e:
            logger.error(f"[UC] 解压失败: {e}")
            return {"status": 500, "code": 1, "message": f"解压失败: {e}", "data": {}}

    def query_task(self, task_id: str) -> Dict:
        """查询任务状态"""
        retry_index = 0
        max_retries = 60
        result = {"status": 500, "code": 1, "message": "任务查询超时"}
        logger.debug(f"[UC] 查询任务: {task_id}")
        while retry_index < max_retries:
            url = f"{self.BASE_URL}/1/clouddrive/task"
            params = {
                "pr": "UCBrowser",
                "fr": "pc",
                "task_id": task_id,
                "retry_index": retry_index,
                "__dt": int(random.uniform(1, 5) * 60 * 1000),
                "__t": datetime.now().timestamp(),
            }

            try:
                response = self._send_request("GET", url, params=params)
                result = self._safe_json(response)

                # 检查容量限制错误
                msg = result.get("message", "")
                if "capacity limit" in msg.lower():
                    logger.error("[UC] 网盘容量不足")
                    return {"status": 400, "code": 1, "message": "UC网盘容量不足，请清理空间后重试", "data": {"status": -1}}

                if result.get("status") != 200:
                    return result

                task_status = result.get("data", {}).get("status")

                # 任务完成
                if task_status == 2:
                    if retry_index > 0:
                        logger.info("")
                    break

                # 任务失败
                if task_status == -1:
                    msg = result.get("data", {}).get("message", "任务执行失败")
                    logger.error(f"[UC] 任务失败: {msg}")
                    return result

                # 任务进行中
                if retry_index == 0:
                    task_title = result.get("data", {}).get("task_title", "任务")
                    logger.info(f"[UC] 等待任务[{task_title}]执行结果...")

                retry_index += 1
                time.sleep(0.5)

            except Exception as e:
                logger.error(f"[UC] 查询任务失败: {e}")
                return {"status": 500, "code": 1, "message": f"查询任务失败: {e}"}
        logger.debug(f"[UC] 任务结果: {result}")
        return result

    def mkdir(self, dir_path: str) -> Dict:
        """创建目录"""
        url = f"{self.BASE_URL}/1/clouddrive/file"
        params = {"pr": "UCBrowser", "fr": "pc"}
        payload = {
            "pdir_fid": "0",
            "file_name": "",
            "dir_path": dir_path,
            "dir_init_lock": False,
        }

        try:
            response = self._send_request("POST", url, json=payload, params=params)
            result = self._safe_json(response)
            return result
        except Exception as e:
            logger.error(f"[UC] 创建目录失败: {e}")
            return {"code": 1, "message": f"创建目录失败: {e}"}

    def rename(self, fid: str, file_name: str) -> Dict:
        """重命名文件"""
        url = f"{self.BASE_URL}/1/clouddrive/file/rename"
        params = {"pr": "UCBrowser", "fr": "pc"}
        payload = {"fid": fid, "file_name": file_name}

        try:
            response = self._send_request("POST", url, json=payload, params=params)
            result = self._safe_json(response)
            return result
        except Exception as e:
            logger.error(f"[UC] 重命名失败: {e}")
            return {"code": 1, "message": f"重命名失败: {e}"}

    def delete(self, filelist: List[str]) -> Dict:
        """删除文件"""
        url = f"{self.BASE_URL}/1/clouddrive/file/delete"
        params = {"pr": "UCBrowser", "fr": "pc"}
        payload = {"action_type": 2, "filelist": filelist, "exclude_fids": []}

        try:
            response = self._send_request("POST", url, json=payload, params=params)
            result = self._safe_json(response)
            return result
        except Exception as e:
            logger.error(f"[UC] 删除失败: {e}")
            return {"code": 1, "message": f"删除失败: {e}"}

    def move_file(self, filelist: List[str], to_pdir_fid: str) -> Dict:
        """移动文件到指定目录"""
        url = f"{self.BASE_URL}/1/clouddrive/file/move"
        params = {"pr": "UCBrowser", "fr": "pc"}
        payload = {
            "action_type": 1,
            "to_pdir_fid": to_pdir_fid,
            "filelist": filelist,
            "exclude_fids": [],
        }
        logger.debug(f"[UC] 移动文件: {filelist} -> {to_pdir_fid}")
        try:
            response = self._send_request("POST", url, json=payload, params=params)
            result = self._safe_json(response)
            logger.debug(f"[UC] 移动文件结果: {result}")
            return result
        except Exception as e:
            logger.error(f"[UC] 移动文件失败: {e}")
            return {"code": 1, "message": f"移动文件失败: {e}"}

    def move_files(self, fids: List[str], to_pdir_fid: str) -> Dict:
        return self.move_files_to_target(fids, to_pdir_fid)

    def get_or_create_share_folder(self) -> Optional[str]:
        """获取或创建'来自：分享'文件夹，返回其fid"""
        if self._share_folder_fid:
            return self._share_folder_fid

        # 列出根目录查找"来自：分享"文件夹
        try:
            root_list = self.ls_dir("0")
            if root_list.get("code") == 0:
                for item in root_list.get("data", {}).get("list", []):
                    if item.get("file_name") == "来自：分享" and item.get("dir"):
                        self._share_folder_fid = item["fid"]
                        return self._share_folder_fid
            else:
                logger.warning(f"[UC] 列出根目录失败: {root_list.get('message')}")
                return None
        except Exception as e:
            logger.warning(f"[UC] 列出根目录异常: {e}")
            return None

        # 未找到，创建文件夹
        try:
            mkdir_result = self.mkdir("/来自：分享")
            if mkdir_result.get("code") == 0:
                self._share_folder_fid = mkdir_result["data"]["fid"]
                logger.debug("[UC] 创建中转文件夹: 来自：分享")
                return self._share_folder_fid
            else:
                logger.warning(f"[UC] 创建'来自：分享'文件夹失败: {mkdir_result.get('message')}")
                return None
        except Exception as e:
            logger.warning(f"[UC] 创建'来自：分享'文件夹异常: {e}")
            return None

    def move_files_to_target(self, fid_list: List[str], to_pdir_fid: str) -> Dict:
        """将指定文件移动到目标目录，支持分批+轮询"""
        if not fid_list:
            return {"code": 0, "message": "无文件需要移动"}

        logger.debug(f"[UC] 移动 {len(fid_list)} 个文件到目标目录...")
        remaining = fid_list[:]
        while remaining:
            batch = remaining[:100]
            remaining = remaining[100:]

            move_result = self.move_file(batch, to_pdir_fid)
            if move_result.get("code") != 0:
                return move_result

            task_id = move_result.get("data", {}).get("task_id")
            if task_id:
                query_result = self.query_task(task_id)
                if query_result.get("code") != 0 or query_result.get("data", {}).get("status") == -1:
                    msg = query_result.get("data", {}).get("message", query_result.get("message", "移动任务失败"))
                    return {"code": 1, "message": msg}

        return {"code": 0, "message": "移动完成"}

    def get_fids(self, file_paths: List[str]) -> List[Dict]:
        """根据路径获取文件 ID"""
        fids = []
        
        while file_paths:
            url = f"{self.BASE_URL}/1/clouddrive/file/info/path_list"
            params = {"pr": "UCBrowser", "fr": "pc"}
            payload = {"file_path": file_paths[:50], "namespace": "0"}

            try:
                response = self._send_request("POST", url, json=payload, params=params)
                result = self._safe_json(response)
                
                if result.get("code") == 0:
                    fids.extend(result.get("data", []))
                    file_paths = file_paths[50:]
                else:
                    logger.error(f"[UC] 获取目录ID失败: {result.get('message')}")
                    break
                    
            except Exception as e:
                logger.error(f"[UC] 获取目录ID失败: {e}")
                break

        return fids

    def extract_url(self, url: str) -> Tuple[Optional[str], str, Any, List]:
        """
        解析UC网盘分享链接
        
        支持格式:
        - https://drive.uc.cn/s/{share_id}
        - https://drive.uc.cn/s/{share_id}?password=xxxx
        """
        import urllib.parse

        # pwd_id
        match_id = re.search(r"/s/(\w+)", url)
        pwd_id = match_id.group(1) if match_id else None
        
        # passcode
        match_pwd = re.search(r"(?:pwd|password)=(\w+)", url)
        passcode = match_pwd.group(1) if match_pwd else ""
        
        # path: fid-name
        paths = []
        matches = re.findall(r"/(\w{32})-?([^/]+)?", url)
        for match in matches:
            fid = match[0]
            name = urllib.parse.unquote(match[1]).replace("*101", "-") if match[1] else ""
            paths.append({"fid": fid, "name": name})
        
        pdir_fid = paths[-1]["fid"] if matches else 0

        return pwd_id, passcode, pdir_fid, paths

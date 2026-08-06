# -*- coding: utf-8 -*-
"""
云盘适配器基类
定义所有网盘适配器必须实现的接口
"""
from abc import ABC, abstractmethod
from typing import Dict, List, Tuple, Optional, Any
import logging
import random
import threading
import time


logger = logging.getLogger(__name__)


class BaseCloudDriveAdapter(ABC):
    """云盘适配器抽象基类"""

    # 网盘类型标识
    DRIVE_TYPE = "base"
    DRIVE_NAME = "基础网盘"
    CONFIG_FORMAT = "raw"
    default_config: dict[str, Any] = {"cookie": ""}
    config_fields: list[dict[str, Any]] = [
        {
            "key": "cookie",
            "label": "Cookie",
            "description": "登录态原文，按驱动要求填写。",
            "input_type": "textarea",
            "required": True,
            "secret": True,
            "placeholder": "",
        }
    ]

    def __init__(
        self,
        cookie: str = "",
        index: int = 0,
        config: dict[str, Any] | None = None,
        *,
        no_login: bool = False,
    ):
        self.config = self.resolve_runtime_config(config=config, cookie=cookie)
        self.cookie = self.serialize_config(self.config)
        self.index = index + 1
        self.is_active = False
        self.nickname = ""
        self.no_login = bool(no_login)

        self._rate_limit_min_interval = 0.05
        self._rate_limit_max_interval = 0.10
        self._rate_limit_lock = threading.Lock()
        self._last_request_at = 0.0

        self.savepath_fid: Dict[str, str] = {"/": "0"}

    def _throttle_request(self) -> None:
        with self._rate_limit_lock:
            now = time.monotonic()
            if self._last_request_at > 0:
                interval = random.uniform(
                    self._rate_limit_min_interval, self._rate_limit_max_interval
                )
                elapsed = now - self._last_request_at
                if elapsed < interval:
                    time.sleep(interval - elapsed)
                    now = time.monotonic()
            self._last_request_at = now

    @classmethod
    def get_config_meta(cls) -> dict[str, Any]:
        return {
            "drive_name": getattr(cls, "DRIVE_NAME", getattr(cls, "DRIVE_TYPE", "base")),
            "config_format": getattr(cls, "CONFIG_FORMAT", "raw"),
            "default_config": dict(getattr(cls, "default_config", {}) or {}),
            "config_fields": list(getattr(cls, "config_fields", []) or []),
        }

    @classmethod
    def normalize_config(cls, config: dict[str, Any] | None) -> dict[str, Any]:
        result = dict(getattr(cls, "default_config", {}) or {})
        for key, value in (config or {}).items():
            result[key] = value
        return result

    @classmethod
    def deserialize_cookie(cls, cookie: str | None) -> dict[str, Any]:
        config = cls.normalize_config(None)
        raw_cookie = str(cookie or "").strip()
        if not raw_cookie:
            return config
        if getattr(cls, "CONFIG_FORMAT", "raw") == "kv":
            parsed: dict[str, Any] = {}
            for chunk in raw_cookie.split(";"):
                chunk = chunk.strip()
                if not chunk or "=" not in chunk:
                    continue
                key, value = chunk.split("=", 1)
                parsed[key.strip()] = value.strip()
            for key, default_value in config.items():
                if key not in parsed:
                    continue
                if isinstance(default_value, bool):
                    config[key] = str(parsed[key]).strip().lower() in ("1", "true", "yes", "on")
                elif isinstance(default_value, int) and not isinstance(default_value, bool):
                    try:
                        config[key] = int(parsed[key])
                    except ValueError:
                        config[key] = parsed[key]
                else:
                    config[key] = parsed[key]
            for key, value in parsed.items():
                if key not in config:
                    config[key] = value
            return config
        config[cls.primary_config_key()] = raw_cookie
        return config

    @classmethod
    def resolve_runtime_config(
        cls,
        *,
        config: dict[str, Any] | None = None,
        cookie: str | None = None,
    ) -> dict[str, Any]:
        if config is not None:
            return cls.normalize_config(config)
        return cls.deserialize_cookie(cookie)

    @classmethod
    def serialize_config(cls, config: dict[str, Any] | None) -> str:
        payload = cls.normalize_config(config)
        if getattr(cls, "CONFIG_FORMAT", "raw") == "kv":
            parts: list[str] = []
            for key, value in payload.items():
                if not cls.keep_value(value):
                    continue
                parts.append(f"{key}={str(value).strip() if not isinstance(value, bool) else str(value)}")
            return ";".join(parts)
        return str(payload.get(cls.primary_config_key(), "") or "").strip()

    @classmethod
    def primary_config_key(cls) -> str:
        fields = getattr(cls, "config_fields", []) or []
        if fields and fields[0].get("key"):
            return str(fields[0]["key"])
        defaults = getattr(cls, "default_config", {}) or {}
        if defaults:
            return next(iter(defaults.keys()))
        return "cookie"

    @staticmethod
    def keep_value(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, int) and not isinstance(value, bool):
            return True
        return str(value or "").strip() != ""

    @abstractmethod
    def init(self) -> Any:
        """
        初始化账户，验证 cookie 有效性
        Returns:
            成功返回账户信息 dict，失败返回 False
        """
        pass

    @abstractmethod
    def get_stoken(self, pwd_id: str, passcode: str = "") -> Dict:
        """
        获取分享令牌，验证资源有效性
        Args:
            pwd_id: 分享ID
            passcode: 提取码
        Returns:
            响应字典，包含 status, data, message 等字段
        """
        pass

    @abstractmethod
    def get_detail(
        self,
        pwd_id: str,
        stoken: str,
        pdir_fid: str,
        _fetch_share: int = 0,
        fetch_share_full_path: int = 0,
    ) -> Dict:
        """
        获取分享文件详情列表
        Args:
            pwd_id: 分享ID
            stoken: 分享令牌
            pdir_fid: 父目录ID
            _fetch_share: 是否获取分享信息
            fetch_share_full_path: 是否获取完整路径
        Returns:
            响应字典，包含 code, data.list 等字段
        """
        pass

    @abstractmethod
    def ls_dir(self, pdir_fid: str, max_items: int = 0, **kwargs) -> Dict:
        """
        列出目录内容
        Args:
            pdir_fid: 目录ID
            max_items: 最大返回条目数，0 表示不限制（全量加载）
        Returns:
            响应字典，包含 code, data.list 等字段
        """
        pass

    @abstractmethod
    def save_file(
        self,
        fid_list: List[str],
        fid_token_list: List[str],
        to_pdir_fid: str,
        pwd_id: str,
        stoken: str,
    ) -> Dict:
        """
        转存文件到指定目录
        Args:
            fid_list: 文件ID列表
            fid_token_list: 文件token列表
            to_pdir_fid: 目标目录ID
            pwd_id: 分享ID
            stoken: 分享令牌
        Returns:
            响应字典，包含 code, data.task_id 等字段
        """
        pass

    @abstractmethod
    def query_task(self, task_id: str) -> Dict:
        """
        查询转存任务状态
        Args:
            task_id: 任务ID
        Returns:
            响应字典，包含任务状态信息
        """
        pass

    @abstractmethod
    def mkdir(self, dir_path: str) -> Dict:
        """
        创建目录
        Args:
            dir_path: 目录路径
        Returns:
            响应字典，包含 code, data.fid 等字段
        """
        pass

    @abstractmethod
    def rename(self, fid: str, file_name: str) -> Dict:
        """
        重命名文件
        Args:
            fid: 文件ID
            file_name: 新文件名
        Returns:
            响应字典
        """
        pass

    @abstractmethod
    def delete(self, filelist: List[str]) -> Dict:
        """
        删除文件
        Args:
            filelist: 文件ID列表
        Returns:
            响应字典
        """
        pass

    @abstractmethod
    def get_fids(self, file_paths: List[str]) -> List[Dict]:
        """
        根据路径获取文件ID
        Args:
            file_paths: 文件路径列表
        Returns:
            包含 file_path 和 fid 的字典列表
        """
        pass

    @abstractmethod
    def extract_url(self, url: str) -> Tuple[Optional[str], str, Any, List]:
        """
        解析分享链接
        Args:
            url: 分享链接
        Returns:
            (pwd_id, passcode, pdir_fid, paths) 元组
        """
        pass

    def unarchive(self, fid: str, to_pdir_fid: str) -> Dict:
        """
        云解压文件（可选实现）
        Args:
            fid: 压缩包文件ID
            to_pdir_fid: 解压到的目录ID
        Returns:
            响应字典，包含 code, data.task_id 等字段
        """
        return {"code": 0, "message": "success", "data": {"task_id": ""}}

    def move_files(self, fids: List[str], to_pdir_fid: str) -> Dict:
        """
        批量移动文件（可选实现）
        Args:
            fids: 文件ID列表
            to_pdir_fid: 目标目录ID
        Returns:
            响应字典
        """
        return {"code": 0, "message": "success"}

    def get_account_info(self) -> Any:
        """获取账户信息（可选实现）"""
        return False

    def get_account_config(self) -> Dict[str, Any]:
        """获取账号配置/概览信息（用于管理页展示）"""
        return {
            "drive_type": self.DRIVE_TYPE,
            "drive_name": self.DRIVE_NAME,
            "nickname": self.nickname or "",
            "username": "",
            "used_space": None,
            "total_space": None,
            "raw": None,
        }

    def sign_in(self) -> Dict[str, Any]:
        return {"supported": False, "message": "not supported"}

    def export_runtime_config(self) -> dict[str, Any]:
        return self.deserialize_cookie(self.cookie)

    def update_savepath_fid(self, tasklist: List[Dict]) -> bool:
        """
        更新保存路径的 fid 映射
        Args:
            tasklist: 任务列表
        Returns:
            是否成功
        """
        # 通用实现，子类可重写
        import re
        from datetime import datetime

        dir_paths = [
            re.sub(r"/{2,}", "/", f"/{item['savepath']}")
            for item in tasklist
            if not item.get("enddate")
            or (
                datetime.now().date()
                <= datetime.strptime(item["enddate"], "%Y-%m-%d").date()
            )
        ]
        if not dir_paths:
            return False

        dir_paths_exist_arr = self.get_fids(dir_paths)
        dir_paths_exist = [item["file_path"] for item in dir_paths_exist_arr]

        # 创建不存在的目录
        dir_paths_unexist = list(set(dir_paths) - set(dir_paths_exist) - set(["/"]))
        for dir_path in dir_paths_unexist:
            mkdir_return = self.mkdir(dir_path)
            if mkdir_return.get("code") == 0:
                new_dir = mkdir_return["data"]
                dir_paths_exist_arr.append(
                    {"file_path": dir_path, "fid": new_dir["fid"]}
                )
                logger.info("创建文件夹：%s", dir_path)
            else:
                logger.warning("创建文件夹：%s 失败, %s", dir_path, mkdir_return.get("message", "未知错误"))

        # 储存目标目录的fid
        for dir_path in dir_paths_exist_arr:
            self.savepath_fid[dir_path["file_path"]] = dir_path["fid"]

        return True

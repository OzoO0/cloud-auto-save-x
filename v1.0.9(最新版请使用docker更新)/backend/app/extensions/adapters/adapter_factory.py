# -*- coding: utf-8 -*-
"""
适配器工厂类
负责根据配置创建不同网盘的适配器实例
"""
import re
import hashlib
import json
import logging
from typing import Any, Dict, List, Optional, Type

from app.extensions.adapters.base_adapter import BaseCloudDriveAdapter
from app.extensions.adapters.quark_adapter import QuarkAdapter
from app.extensions.adapters.cloud115_adapter import Cloud115Adapter
from app.extensions.adapters.baidu_adapter import BaiduAdapter
from app.extensions.adapters.xunlei_adapter import XunleiAdapter
from app.extensions.adapters.aliyun_adapter import AliyunAdapter
from app.extensions.adapters.uc_adapter import UCAdapter
from app.extensions.adapters.pan123_adapter import Pan123Adapter
from app.extensions.adapters.cloud189_adapter import Cloud189Adapter
from app.extensions.adapters.cloud139_adapter import Cloud139Adapter
from app.extensions.adapters.guangya_adapter import GuangyaAdapter


logger = logging.getLogger(__name__)


class AdapterFactory:
    """适配器工厂"""

    # 适配器映射表
    ADAPTER_MAP: Dict[str, Type[BaseCloudDriveAdapter]] = {
        "quark": QuarkAdapter,
        "115": Cloud115Adapter,
        "baidu": BaiduAdapter,
        "xunlei": XunleiAdapter,
        "aliyun": AliyunAdapter,
        "uc": UCAdapter,
        "123pan": Pan123Adapter,
        "cloud189": Cloud189Adapter,
        "cloud139": Cloud139Adapter,
        "guangya": GuangyaAdapter,
    }

    # URL 模式映射
    URL_PATTERNS: Dict[str, str] = {
        r"pan\.quark\.cn": "quark",
        r"(?:115|anxia|115cdn)\.com": "115",  # 115网盘有多个域名
        r"pan\.baidu\.com": "baidu",
        r"pan\.xunlei\.com": "xunlei",
        r"(?:alipan|aliyundrive)\.com": "aliyun",
        r"drive\.uc\.cn": "uc",
        r"(?:123pan|123865|123684|123952|123912)\.com": "123pan",
        r"(?:cloud|m\.cloud)\.189\.cn": "cloud189",
        r"(?:yun|caiyun)\.139\.com": "cloud139",
        r"(?:www\.|app\.)?guangyapan\.com": "guangya",
    }

    # 实例缓存: (drive_type, config_hash) -> adapter_instance
    _instance_cache: Dict[str, BaseCloudDriveAdapter] = {}

    @classmethod
    def _make_cache_key(
        cls,
        drive_type: str,
        config_payload: dict[str, Any],
        account_name: str = "",
        *,
        no_login: bool = False,
    ) -> str:
        """生成缓存键"""
        raw = json.dumps(config_payload, ensure_ascii=False, sort_keys=True)
        config_hash = hashlib.md5(raw.encode("utf-8")).hexdigest()[:16]
        mode = "no_login" if bool(no_login) else "login"
        return f"{drive_type}:{account_name}:{mode}:{config_hash}"

    @classmethod
    def register_adapter(cls, drive_type: str, adapter_class: Type[BaseCloudDriveAdapter]):
        """
        注册新的适配器
        Args:
            drive_type: 网盘类型标识
            adapter_class: 适配器类
        """
        cls.ADAPTER_MAP[drive_type] = adapter_class

    @classmethod
    def register_url_pattern(cls, pattern: str, drive_type: str):
        """
        注册 URL 匹配模式
        Args:
            pattern: 正则表达式模式
            drive_type: 网盘类型标识
        """
        cls.URL_PATTERNS[pattern] = drive_type

    @classmethod
    def create_adapter(
        cls,
        drive_type: str,
        cookie: str = "",
        index: int = 0,
        *,
        config: dict[str, Any] | None = None,
        account_name: str = "",
        no_login: bool = False,
    ) -> Optional[BaseCloudDriveAdapter]:
        """
        创建或获取缓存的适配器实例。
        同一 (drive_type, cookie) 组合只创建一次实例，后续返回缓存。
        Args:
            drive_type: 网盘类型（quark, 115, baidu 等）
            cookie: 兼容旧链路的认证字符串
            index: 账户索引
            config: 结构化配置
            account_name: 账户名称
        Returns:
            适配器实例，失败返回 None
        """
        adapter_class = cls.ADAPTER_MAP.get(drive_type)
        if not adapter_class:
            logger.warning("未知的网盘类型: %s", drive_type)
            return None

        runtime_config = adapter_class.resolve_runtime_config(config=config, cookie=cookie)

        # 查找缓存
        cache_key = cls._make_cache_key(drive_type, runtime_config, account_name, no_login=no_login)
        cached = cls._instance_cache.get(cache_key)
        if cached is not None:
            setattr(cached, "account_name", account_name or "")
            return cached

        # 创建新实例并缓存
        try:
            adapter = adapter_class(
                cookie=cookie,
                index=index,
                config=runtime_config,
                account_name=account_name,
                no_login=no_login,
            )
            setattr(adapter, "account_name", account_name or "")
            cls._instance_cache[cache_key] = adapter
            return adapter
        except Exception as e:
            logger.exception("创建适配器失败: %s", e)
            return None

    @classmethod
    def clear_cache(cls):
        """清空实例缓存（配置更新时调用）"""
        cls._instance_cache.clear()

    @classmethod
    def get_drive_type_by_url(cls, url: str) -> Optional[str]:
        """
        根据 URL 判断网盘类型
        Args:
            url: 分享链接
        Returns:
            网盘类型标识，无法识别返回 None
        """
        for pattern, drive_type in cls.URL_PATTERNS.items():
            if re.search(pattern, url):
                return drive_type
        return None

    @classmethod
    def create_adapter_by_url(
        cls,
        url: str,
        cookie: str = "",
        index: int = 0,
        *,
        config: dict[str, Any] | None = None,
        account_name: str = "",
        no_login: bool = False,
    ) -> Optional[BaseCloudDriveAdapter]:
        """
        根据 URL 自动创建适配器
        Args:
            url: 分享链接
            cookie: 认证 cookie
            index: 账户索引
        Returns:
            适配器实例
        """
        drive_type = cls.get_drive_type_by_url(url)
        if not drive_type:
            logger.warning("无法识别的分享链接: %s", url)
            return None
        return cls.create_adapter(drive_type, cookie, index, config=config, account_name=account_name, no_login=no_login)

    @classmethod
    def get_supported_types(cls) -> List[str]:
        """获取支持的网盘类型列表"""
        return list(cls.ADAPTER_MAP.keys())


class AccountManager:
    """账户管理器"""

    def __init__(self):
        self.adapters: Dict[str, BaseCloudDriveAdapter] = {}
        self.default_adapter: Optional[BaseCloudDriveAdapter] = None

    def load_accounts(self, config_data: Dict, *, no_login: bool = False) -> bool:
        """
        从配置加载所有账户
        支持新格式（accounts）和旧格式（cookie）
        Args:
            config_data: 配置数据
        Returns:
            是否成功加载
        """
        self.adapters.clear()
        self.default_adapter = None

        # 新格式：accounts 列表
        if "accounts" in config_data:
            for i, account in enumerate(config_data["accounts"]):
                if not account.get("enabled", True):
                    continue

                name = account.get("name", f"账户{i+1}")
                drive_type = account.get("drive_type", "quark")
                cookie = account.get("cookie", "")
                config = account.get("config")

                adapter = AdapterFactory.create_adapter(
                    drive_type,
                    cookie,
                    i,
                    config=config,
                    account_name=name,
                    no_login=no_login,
                )
                if adapter:
                    self.adapters[name] = adapter
                    if account.get("default", False) or self.default_adapter is None:
                        self.default_adapter = adapter

        # 旧格式：cookie 字符串或列表（兼容现有配置）
        elif "cookie" in config_data:
            cookies = config_data["cookie"]
            if isinstance(cookies, str):
                cookies = [cookies] if cookies else []
            elif cookies and "\n" in cookies[0]:
                cookies = cookies[0].split("\n")

            for i, cookie in enumerate(cookies):
                if not cookie.strip():
                    continue

                name = f"夸克账户{i+1}"
                adapter = AdapterFactory.create_adapter("quark", cookie.strip(), i, no_login=no_login)
                if adapter:
                    self.adapters[name] = adapter
                    if self.default_adapter is None:
                        self.default_adapter = adapter

        return bool(self.adapters)

    def get_adapter(self, name: str) -> Optional[BaseCloudDriveAdapter]:
        """根据名称获取适配器"""
        return self.adapters.get(name)

    def get_default_adapter(self) -> Optional[BaseCloudDriveAdapter]:
        """获取默认适配器"""
        return self.default_adapter

    def get_adapter_for_task(self, task: Dict, *, allow_inactive: bool = False) -> Optional[BaseCloudDriveAdapter]:
        """
        为任务选择适配器
        优先使用任务指定的账户，否则根据 URL 自动选择
        Args:
            task: 任务配置
        Returns:
            适配器实例
        """
        # 1. 任务指定了账户名
        if account_name := task.get("account_name"):
            adapter = self.adapters.get(account_name)
            if adapter:
                return adapter
            logger.warning("指定的账户 '%s' 不存在，尝试自动选择", account_name)

        # 2. 根据 URL 判断网盘类型
        shareurl = task.get("shareurl", "")
        drive_type = AdapterFactory.get_drive_type_by_url(shareurl)

        if drive_type:
            # 查找该类型的第一个可用账户
            for adapter in self.adapters.values():
                if adapter.DRIVE_TYPE != drive_type:
                    continue
                if (not allow_inactive) and (not adapter.is_active):
                    continue
                return adapter
            logger.warning("分享链接推断网盘类型为 '%s'，但没有可用的同类型账户", drive_type)
            return None

        # 3. 使用默认适配器
        return self.default_adapter

    def get_all_adapters(self) -> Dict[str, BaseCloudDriveAdapter]:
        """获取所有适配器"""
        return self.adapters

    def get_adapters_by_type(self, drive_type: str) -> List[BaseCloudDriveAdapter]:
        """获取指定类型的所有适配器"""
        return [
            adapter
            for adapter in self.adapters.values()
            if adapter.DRIVE_TYPE == drive_type
        ]

    def init_all_adapters(self) -> int:
        """
        初始化所有适配器
        Returns:
            成功初始化的数量
        """
        return self._init_adapters(self.adapters)

    def init_adapters_for_tasks(self, tasklist: List[Dict]) -> int:
        """
        仅初始化与任务列表相关的适配器
        根据任务的 shareurl 和 account_name 确定需要的网盘类型和账户
        Args:
            tasklist: 任务列表
        Returns:
            成功初始化的数量
        """
        needed_names = set()
        needed_types = set()

        for task in tasklist:
            # 任务指定了账户名
            if account_name := task.get("account_name"):
                needed_names.add(account_name)
            # 根据分享链接判断网盘类型
            if shareurl := task.get("shareurl", ""):
                if drive_type := AdapterFactory.get_drive_type_by_url(shareurl):
                    needed_types.add(drive_type)

        # 筛选需要初始化的适配器
        needed_adapters = {
            name: adapter
            for name, adapter in self.adapters.items()
            if name in needed_names or adapter.DRIVE_TYPE in needed_types
        }

        if not needed_adapters:
            # 没有匹配到任何适配器，回退到全部初始化
            return self._init_adapters(self.adapters)

        return self._init_adapters(needed_adapters)

    def _init_adapters(self, adapters: Dict[str, "BaseCloudDriveAdapter"]) -> int:
        """
        初始化指定的适配器集合
        Args:
            adapters: 需要初始化的适配器字典
        Returns:
            成功初始化的数量
        """
        success_count = 0
        for name, adapter in adapters.items():
            if adapter.init():
                success_count += 1
                logger.info("账户 '%s' (%s) 登录成功: %s", name, adapter.DRIVE_TYPE, adapter.nickname)
            else:
                logger.warning("账户 '%s' (%s) 登录失败", name, adapter.DRIVE_TYPE)
        return success_count

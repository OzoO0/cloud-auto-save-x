# -*- coding: utf-8 -*-
"""
云盘适配器模块
支持多网盘的统一接口
"""

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
from app.extensions.adapters.adapter_factory import AdapterFactory, AccountManager

__all__ = [
    "BaseCloudDriveAdapter",
    "QuarkAdapter",
    "Cloud115Adapter",
    "BaiduAdapter",
    "XunleiAdapter",
    "AliyunAdapter",
    "UCAdapter",
    "Pan123Adapter",
    "Cloud189Adapter",
    "Cloud139Adapter",
    "AdapterFactory",
    "AccountManager",
]

__version__ = "1.1.0"

import logging
import requests


logger = logging.getLogger(__name__)


class Smartstrm:
    default_config = {
        "webhook": "",  # SmartStrm Webhook 地址
        "strmtask": "",  # SmartStrm 任务名，支持多个如 `tv,movie`
        "xlist_path_fix": "",  # 路径映射， SmartStrm 任务使用 quark 驱动时无须填写；使用 openlist 驱动时需填写 `/storage_mount_path:/quark_root_dir` ，例如把夸克根目录挂载在 OpenList 的 /quark 下，则填写 `/quark:/` ；以及 SmartStrm 会使 OpenList 强制刷新目录，无需再用 alist 插件刷新。
    }

    default_task_config = {
        "task_name": "",  # 任务名，支持多个如 `tv,movie`
        "storage_path": "",  # 存储路径，留空使用任务保存路径
        "incremental": False,  # 是否增量刷新
        "dir_time_check": False,  # 是否检查目录时间
        "keep_local_asset": True,  # 是否同步生成时保留本地刮削文件
        "delay": 0,  # 延迟时间，单位秒
    }

    is_active = False

    def __init__(self, **kwargs):
        self.plugin_name = self.__class__.__name__.lower()
        for key, value in {**self.default_config, **self.default_task_config}.items():
            setattr(self, key, value)
        if kwargs:
            for key in {**self.default_config, **self.default_task_config}:
                if key in kwargs:
                    setattr(self, key, kwargs[key])
            if not self.webhook:
                logger.warning("%s 模块缺少必要参数: webhook", self.plugin_name)
            elif not self.strmtask and not self.task_name:
                logger.warning("%s 模块缺少必要参数: strmtask/task_name", self.plugin_name)
            elif self.get_info():
                self.is_active = True

    def _get_task_savepath(self, task):
        savepath = ""
        if not isinstance(task, dict):
            return savepath
        target = task.get("target")
        if isinstance(target, dict):
            savepath = str(target.get("path") or "").strip()
        if not savepath:
            savepath = str(task.get("savepath") or "").strip()
        return savepath

    def _get_storage_path(self, task):
        storage_path = str(self.storage_path or "").strip()
        if storage_path:
            return storage_path
        return self._get_task_savepath(task)

    def _get_single_task_name(self):
        task_name = str(self.task_name or "").strip()
        if not task_name:
            return ""

        task_names = [item.strip() for item in task_name.split(",") if item.strip()]
        if len(task_names) > 1:
            logger.warning(
                "SmartStrm 触发任务: task_name 仅支持单个任务，当前仅使用第一个 %s",
                task_names[0],
            )
        return task_names[0] if task_names else ""

    def _build_payload(self, task):
        task_name = self._get_single_task_name()

        if task_name:
            storage_path = self._get_storage_path(task)
            payload = {
                "event": "a_task",
                "task": {
                    "name": task_name,
                    "dir_time_check": bool(self.dir_time_check),
                    "incremental": bool(self.incremental),
                    "keep_local_asset": bool(self.keep_local_asset),
                },
                "delay": self.delay,
            }
            if storage_path:
                payload["task"]["storage_path"] = storage_path
            return payload

        return {
            "event": "qas_strm",
            "data": {
                "strmtask": self.strmtask,
                "savepath": self._get_task_savepath(task),
                "xlist_path_fix": self.xlist_path_fix,
            },
        }

    def get_info(self):
        """获取 SmartStrm 信息"""
        try:
            response = requests.request(
                "GET",
                self.webhook,
                timeout=5,
            )
            response = response.json()
            if response.get("success"):
                logger.info("SmartStrm 触发任务: 连接成功 %s", response.get("version", ""))
                return response
            logger.warning("SmartStrm 触发任务：连接失败 %s", response.get("message", ""))
            return None
        except Exception as e:
            logger.exception("SmartStrm 触发任务：连接出错 %s", str(e))
            return None

    def run(self, task, **_kwargs):
        """
        插件主入口函数
        :param task: 任务配置
        :param kwargs: 其他参数
        """
        try:
            headers = {"Content-Type": "application/json"}
            payload = self._build_payload(task)
            response = requests.request(
                "POST",
                self.webhook,
                headers=headers,
                json=payload,
                timeout=5,
            )
            response = response.json()
            if response.get("success"):
                task_data = response.get("task") or {}
                logger.info(
                    "SmartStrm 触发任务: [%s] %s 成功",
                    (task_data or {}).get("name"),
                    (task_data or {}).get("storage_path"),
                )
            else:
                logger.warning("SmartStrm 触发任务: %s", response.get("message"))
        except Exception as e:
            logger.exception("SmartStrm 触发任务：出错 %s", str(e))

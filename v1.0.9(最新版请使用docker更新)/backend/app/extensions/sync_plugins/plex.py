import logging
import os
import posixpath

import requests


logger = logging.getLogger(__name__)


class Plex:

    default_config = {
        "url": "",  # Plex服务器URL
        "token": "",  # Plex Token，可F12在请求中抓取
        "openlist_root_path": "",  # 同步目标目录在 Plex 中的路径前缀；如 OpenList /媒体/tv 在 Plex 中是 /quark/媒体/tv，则填 /quark
    }
    default_task_config = {
        "enable": True,  # 任务级开关
    }
    is_active = False
    _libraries = None

    def __init__(self, **kwargs):
        self.plugin_name = self.__class__.__name__.lower()
        if kwargs:
            for key, value in self.default_config.items():
                if key in kwargs:
                    setattr(self, key, kwargs[key])
                else:
                    logger.warning("%s 模块缺少必要参数: %s", self.plugin_name, key)
            if self.url and self.token and self.openlist_root_path:
                if self.get_info():
                    self.is_active = True

    def run(self, task, **kwargs):
        task_config = task.get("addition", {}).get(self.plugin_name, self.default_task_config) or {}
        if not bool(task_config.get("enable", True)):
            return

        target = task.get("target") if isinstance(task, dict) else None
        if not isinstance(target, dict):
            return
        # if str(target.get("type") or "").lower() != "openlist":
            # return

        target_path = str(target.get("path") or "").strip()
        if not target_path:
            return

        if self._libraries is None:
            self._libraries = self._get_libraries()

        rel = posixpath.normpath("/" + target_path.lstrip("/")).lstrip("/")
        full_path = os.path.normpath(os.path.join(self.openlist_root_path, rel)).replace("\\", "/")
        self.refresh(full_path)

    def get_info(self):
        headers = {"Accept": "application/json", "X-Plex-Token": self.token}
        try:
            response = requests.get(f"{self.url}/", headers=headers)
            if response.status_code == 200:
                info = response.json()["MediaContainer"]
                logger.info("Plex媒体库: %s v%s", info.get("friendlyName", ""), info.get("version", ""))
                return True
            else:
                logger.warning("Plex媒体库: 连接失败 状态码：%s", response.status_code)
        except Exception as e:
            logger.exception("获取Plex媒体库信息出错: %s", e)
        return False

    def refresh(self, folder_path):
        if not folder_path:
            return False
        headers = {"Accept": "application/json", "X-Plex-Token": self.token}
        try:
            for library in self._libraries or []:
                for location in library.get("Location", []):
                    if os.path.commonpath([folder_path, location["path"]]) == location["path"]:
                        refresh_url = f"{self.url}/library/sections/{library['key']}/refresh?path={folder_path}"
                        refresh_response = requests.get(refresh_url, headers=headers)
                        if refresh_response.status_code == 200:
                            logger.info("🎞️ 刷新Plex媒体库：%s [%s] 成功", library.get("title"), folder_path)
                            return True
                        else:
                            logger.warning("🎞️ 刷新Plex媒体库：刷新请求失败 状态码：%s", refresh_response.status_code)
            logger.warning("🎞️ 刷新Plex媒体库：%s 未找到匹配的媒体库", folder_path)
        except Exception as e:
            logger.exception("刷新Plex媒体库出错: %s", e)
        return False

    def _get_libraries(self):
        url = f"{self.url}/library/sections"
        headers = {"Accept": "application/json", "X-Plex-Token": self.token}
        try:
            response = requests.get(url, headers=headers)
            if response.status_code == 200:
                libraries = response.json()["MediaContainer"].get("Directory", [])
                return libraries
            else:
                logger.warning("🎞️ 获取Plex媒体库信息失败 状态码：%s", response.status_code)
        except Exception as e:
            logger.exception("获取Plex媒体库信息出错: %s", e)
        return []


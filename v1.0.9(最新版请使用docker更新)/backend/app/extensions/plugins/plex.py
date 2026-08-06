import os
import logging
import requests


logger = logging.getLogger(__name__)


class Plex:

    default_config = {
        "url": "",  # Plex服务器URL
        "token": "",  # Plex Token，可F12在请求中抓取
        "quark_root_path": "",  # 夸克根目录在Plex中的路径；假设夸克目录/media/tv在plex中对应的路径为/quark/media/tv，则为/quark
    }
    is_active = False
    _libraries = None  # 缓存库信息

    def __init__(self, **kwargs):
        if kwargs:
            for key, value in self.default_config.items():
                if key in kwargs:
                    setattr(self, key, kwargs[key])
                else:
                    logger.warning("%s 模块缺少必要参数: %s", self.__class__.__name__, key)
            if self.url and self.token and self.quark_root_path:
                if self.get_info():
                    self.is_active = True

    def run(self, task, **kwargs):
        if task.get("savepath"):
            # 检查是否已缓存库信息
            if self._libraries is None:
                self._libraries = self._get_libraries()
            # 拼接完整路径
            full_path = os.path.normpath(
                os.path.join(self.quark_root_path, task["savepath"].lstrip("/"))
            ).replace("\\", "/")
            self.refresh(full_path)

    def get_info(self):
        """获取Plex服务器信息"""
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
        """刷新指定文件夹"""
        if not folder_path:
            return False
        headers = {"Accept": "application/json", "X-Plex-Token": self.token}
        try:
            for library in self._libraries:
                for location in library.get("Location", []):
                    if (
                        os.path.commonpath([folder_path, location["path"]])
                        == location["path"]
                    ):
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
        """获取Plex媒体库信息"""
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

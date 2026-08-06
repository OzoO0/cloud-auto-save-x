import logging
import requests


logger = logging.getLogger(__name__)


class Emby:

    default_config = {
        "url": "",  # Emby服务器地址
        "token": "",  # Emby服务器token
    }
    default_task_config = {
        "try_match": True,  # 是否尝试匹配
        "media_id": "",  # 媒体ID，当为0时不刷新
    }
    is_active = False

    def __init__(self, **kwargs):
        self.plugin_name = self.__class__.__name__.lower()
        if kwargs:
            for key, _ in self.default_config.items():
                if key in kwargs:
                    setattr(self, key, kwargs[key])
                else:
                    logger.warning("%s 模块缺少必要参数: %s", self.plugin_name, key)
            if self.url and self.token:
                if self.get_info():
                    self.is_active = True

    def run(self, task, **kwargs):
        task_config = task.get("addition", {}).get(
            self.plugin_name, self.default_task_config
        )
        if media_id := task_config.get("media_id"):
            if media_id != "0":
                self.refresh(media_id)
        elif task_config.get("try_match"):
            if match_media_id := self.search(task["taskname"]):
                self.refresh(match_media_id)
                task_config["media_id"] = match_media_id
                task.setdefault("addition", {})[self.plugin_name] = task_config
                return task

    def get_info(self):
        url = f"{self.url}/emby/System/Info"
        headers = {"X-Emby-Token": self.token}
        querystring = {}
        try:
            response = requests.request("GET", url, headers=headers, params=querystring)
            if "application/json" in response.headers["Content-Type"]:
                response = response.json()
                logger.info("Emby媒体库: %s v%s", response.get("ServerName", ""), response.get("Version", ""))
                return True
            else:
                logger.warning("Emby媒体库: 连接失败 %s", response.text)
        except Exception as e:
            logger.exception("获取Emby媒体库信息出错: %s", e)
        return False

    def refresh(self, emby_id):
        if not emby_id:
            return False
        url = f"{self.url}/emby/Items/{emby_id}/Refresh"
        headers = {"X-Emby-Token": self.token}
        querystring = {
            "Recursive": "true",
            "MetadataRefreshMode": "FullRefresh",
            "ImageRefreshMode": "FullRefresh",
            "ReplaceAllMetadata": "false",
            "ReplaceAllImages": "false",
        }
        try:
            response = requests.request(
                "POST", url, headers=headers, params=querystring
            )
            if response.text == "":
                logger.info("🎞️ 刷新Emby媒体库：成功")
                return True
            else:
                logger.warning("🎞️ 刷新Emby媒体库：%s", response.text)
        except Exception as e:
            logger.exception("刷新Emby媒体库出错: %s", e)
        return False

    def search(self, media_name):
        if not media_name:
            return ""
        url = f"{self.url}/emby/Items"
        headers = {"X-Emby-Token": self.token}
        querystring = {
            "IncludeItemTypes": "Series",
            "StartIndex": 0,
            "SortBy": "SortName",
            "SortOrder": "Ascending",
            "ImageTypeLimit": 0,
            "Recursive": "true",
            "SearchTerm": media_name,
            "Limit": 10,
            "IncludeSearchTypes": "false",
        }
        try:
            response = requests.request("GET", url, headers=headers, params=querystring)
            if "application/json" in response.headers["Content-Type"]:
                response = response.json()
                if response.get("Items"):
                    for item in response["Items"]:
                        if item["IsFolder"]:
                            logger.info("🎞️ 《%s》匹配到Emby媒体库ID：%s", item.get("Name"), item.get("Id"))
                            return item["Id"]
            else:
                logger.warning("🎞️ 搜索Emby媒体库：%s", response.text)
        except Exception as e:
            logger.exception("搜索Emby媒体库出错: %s", e)
        return ""

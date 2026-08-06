#!/usr/bin/python3
# -*- encoding: utf-8 -*-
import os
import posixpath
import re
import json
import logging
import requests
from urllib.parse import urlsplit, urlunsplit

from app.thirdparty.openlist_client import OpenListClient


logger = logging.getLogger(__name__)


class Alist_strm_gen:

    video_exts = ["mp4", "mkv", "flv", "mov", "m4v", "avi", "webm", "wmv", "cas"]
    default_config = {
        "tips_alist_refresh": "该插件需与 alist 刷新插件配合使用，否则可能出现 alist 未刷新导致无法生成 strm 的问题！",
        "url": "",  # OpenList/Alist 服务器 URL
        "token": "",  # OpenList/Alist 服务器 Token
        "storage_id": "",  # OpenList 存储ID(数字) 或 /挂载路径:/任务保存路径根目录(推荐)
        "strm_save_dir": "/media",  # 生成的 strm 文件保存的路径
        "strm_replace_host": "",  # strm 文件内链接的主机地址 （可选，缺省时=url）
    }
    default_task_config = {
        "auto_gen": True,  # 是否自动生成 strm 文件
    }
    is_active = False
    # 缓存参数
    storage_mount_path = None
    root_dir = None
    strm_server = None

    def __init__(self, **kwargs):
        self.plugin_name = self.__class__.__name__.lower()
        self.client: OpenListClient | None = None
        self.root_dir = ""
        self.use_raw_url = False
        for key, value in self.default_config.items():
            setattr(self, key, value)
        for key in self.default_config:
            if key in kwargs:
                setattr(self, key, kwargs[key])
        if "root_dir" in kwargs:
            self.root_dir = str(kwargs.get("root_dir") or "").strip()
        if "use_raw_url" in kwargs:
            self.use_raw_url = bool(kwargs.get("use_raw_url"))
        if self.url and self.token and self.storage_id:
            self.client = OpenListClient(self.url.strip(), token=self.token.strip())
            success, result = self.storage_id_to_path(self.storage_id)
            if success:
                self.is_active = True
                self.storage_mount_path, self.root_dir = result
                self.strm_replace_host = self.strm_replace_host.strip()
                if self.strm_replace_host:
                    if self.strm_replace_host.startswith("http"):
                        self.strm_server = f"{self.strm_replace_host}/d"
                    else:
                        self.strm_server = f"http://{self.strm_replace_host}/d"
                else:
                    self.strm_server = f"{self.url.strip()}/d"

    def run(self, task, **kwargs):
        task_config = task.get("addition", {}).get(
            self.plugin_name, self.default_task_config
        )
        if not task_config.get("auto_gen"):
            return
        savepath = str(task.get("savepath") or "")
        if not savepath or not self.storage_mount_path:
            return
        mapped = self._map_task_savepath(savepath)
        if not mapped:
            return
        self.check_dir(mapped)

    @staticmethod
    def _norm_path(path: str) -> str:
        p = str(path or "").strip() or "/"
        p = "/" + posixpath.normpath(p).lstrip("/")
        if p != "/" and p.endswith("/"):
            p = p.rstrip("/")
        return p

    @staticmethod
    def _pick_name(payload: dict) -> str:
        return str(
            payload.get("name")
            or payload.get("file_name")
            or payload.get("fileName")
            or payload.get("title")
            or ""
        )

    @staticmethod
    def _bool_is_dir(payload: dict) -> bool:
        if payload.get("is_dir") is not None:
            return bool(payload.get("is_dir"))
        if payload.get("isDir") is not None:
            return bool(payload.get("isDir"))
        if payload.get("isdir") is not None:
            return str(payload.get("isdir")) in ("1", "true", "True")
        if payload.get("dir") is not None:
            return bool(payload.get("dir"))
        if payload.get("type") in ("folder", "dir"):
            return True
        if payload.get("type") in ("file",):
            return False
        if payload.get("kind") in ("folder", "dir", "directory"):
            return True
        if payload.get("kind") in ("file",):
            return False
        return False

    @staticmethod
    def _extract_list_items(resp: dict) -> tuple[list[dict], int | None]:
        data = resp.get("data") if isinstance(resp, dict) else None
        raw_items = None
        total = None
        if isinstance(data, dict):
            raw_items = data.get("content") or data.get("items") or data.get("list") or data.get("files")
            total = data.get("total")
        if raw_items is None and isinstance(resp, dict):
            raw_items = resp.get("content") or resp.get("items") or resp.get("list") or resp.get("files")
            total = resp.get("total") if total is None else total
        items: list[dict] = []
        if isinstance(raw_items, list):
            for it in raw_items:
                if isinstance(it, dict):
                    items.append(it)
        if total is None:
            return items, None
        try:
            return items, int(total)
        except Exception:
            return items, None

    def _iter_dir_items(self, path: str, *, force_refresh: bool = False) -> list[dict]:
        if not self.client:
            return []
        normalized = self._norm_path(path)
        page = 1
        per_page = 100
        out: list[dict] = []
        while True:
            resp = self.client.fs_list(normalized, refresh=bool(force_refresh), page=page, per_page=per_page)
            items, total = self._extract_list_items(resp)
            if not items:
                break
            out.extend(items)
            if total is not None and page * per_page >= total:
                break
            if len(items) < per_page:
                break
            page += 1
        return out

    def _path_exists(self, path: str) -> bool:
        if not self.client:
            return False
        try:
            self.client.fs_list(self._norm_path(path), refresh=False, page=1, per_page=1)
            return True
        except Exception:
            return False

    def _map_task_savepath(self, savepath: str) -> str | None:
        if not self.client or not self.storage_mount_path:
            return None
        savepath = self._norm_path(savepath)

        def join_mount(rel: str) -> str:
            return os.path.normpath(
                os.path.join(self.storage_mount_path, rel.lstrip("/"))
            ).replace("\\", "/")

        configured_root = self._norm_path(self.root_dir) if str(self.root_dir or "").strip() else ""
        if configured_root and savepath.startswith(configured_root):
            candidate = join_mount(savepath.replace(configured_root, "", 1))
            if self._path_exists(candidate):
                return candidate

        candidate = join_mount(savepath)
        if self._path_exists(candidate):
            return candidate

        segments = [s for s in savepath.split("/") if s]
        for k in range(len(segments), 0, -1):
            prefix = "/" + "/".join(segments[:k])
            rel = "/" + "/".join(segments[k:])
            candidate = join_mount(rel)
            if self._path_exists(candidate):
                self.root_dir = prefix
                return candidate
        return None

    def storage_id_to_path(self, storage_id):
        storage_mount_path, root_dir = None, None
        storage_id = str(storage_id or "").strip()
        raw_root_dir = str(getattr(self, "root_dir", "") or "").strip()
        configured_root_dir = self._norm_path(raw_root_dir) if raw_root_dir else ""
        # 1. 检查是否符合 /aaa:/bbb 格式
        if match := re.match(r"^(\/[^:]*):(\/[^:]*)$", storage_id):
            # 存储挂载路径, 夸克根文件夹
            storage_mount_path, root_dir = self._norm_path(match.group(1)), self._norm_path(match.group(2))
            if not self.client:
                return False, (None, None)
            try:
                self.client.fs_list(storage_mount_path, refresh=False, page=1, per_page=1)
            except Exception as e:
                logger.warning("Alist-Strm生成: 获取挂载路径失败 %s", e)
                return False, (None, None)
        # 2. 检查是否数字，调用 Alist API 获取存储信息
        elif re.match(r"^\d+$", storage_id):
            if not self.client:
                return False, (None, None)
            try:
                resp = self.client.admin_storage_get(str(storage_id))
                storage_info = resp.get("data") if isinstance(resp, dict) else None
            except Exception as e:
                logger.warning("Alist-Strm生成: 获取存储失败 %s", e)
                storage_info = None
            if isinstance(storage_info, dict):
                mount_raw = str(
                    storage_info.get("mount_path")
                    or storage_info.get("mountPath")
                    or storage_info.get("mount")
                    or ""
                ).strip()
                if not mount_raw:
                    logger.warning("Alist-Strm生成: storage_id[%s] 未返回 mount_path", storage_id)
                    return False, (None, None)
                storage_mount_path = self._norm_path(mount_raw)
                root_dir = configured_root_dir or ""
                if (not configured_root_dir) and storage_info.get("driver") == "Quark":
                    try:
                        addition = json.loads(storage_info.get("addition") or "{}")
                        root_dir = self._norm_path(
                            self.get_root_folder_full_path(addition.get("cookie"), addition.get("root_folder_id"))
                        )
                    except Exception:
                        root_dir = ""
                if not root_dir:
                    logger.info(
                        "Alist-Strm生成: 未配置root_dir，将在运行时尝试根据任务savepath自动探测映射路径"
                    )
        else:
            if not storage_id:
                logger.warning("Alist-Strm生成: storage_id 为空")
            else:
                storage_mount_path = self._norm_path(storage_id)
                root_dir = configured_root_dir or ""
                if not root_dir:
                    logger.info(
                        "Alist-Strm生成: 未配置root_dir，将在运行时尝试根据任务savepath自动探测映射路径"
                    )
                if not self.client:
                    return False, (None, None)
                try:
                    self.client.fs_list(storage_mount_path, refresh=False, page=1, per_page=1)
                except Exception as e:
                    logger.warning("Alist-Strm生成: 获取挂载路径失败 %s", e)
                    return False, (None, None)
        # 返回结果
        if storage_mount_path and root_dir:
            logger.info("Alist-Strm生成: [%s:%s]", storage_mount_path, root_dir)
            return True, (storage_mount_path, root_dir)
        else:
            return False, (None, None)

    def check_dir(self, path):
        if not self.client:
            return
        normalized = self._norm_path(path)
        try:
            files = self._iter_dir_items(normalized, force_refresh=False)
        except Exception as e:
            logger.warning("📺 Alist-Strm生成: 获取文件列表失败 %s", e)
            return
        for item in files:
            name = self._pick_name(item).strip()
            if not name or name in {".", ".."}:
                continue
            item_path = self._norm_path(posixpath.join(normalized, name))
            if self._bool_is_dir(item):
                self.check_dir(item_path)
            else:
                self.generate_strm(item_path, item)

    def generate_strm(self, file_path, file_info):
        ext = file_path.split(".")[-1]
        if ext.lower() in self.video_exts:
            strm_path = (
                f"{self.strm_save_dir}{os.path.splitext(file_path)[0]}.strm".replace(
                    "//", "/"
                )
            )
            if os.path.exists(strm_path):
                return
            if not os.path.exists(os.path.dirname(strm_path)):
                os.makedirs(os.path.dirname(strm_path))
            url = None
            if bool(getattr(self, "use_raw_url", False)) and self.client:
                try:
                    data = self.client.fs_get(file_path)
                    raw = (data.get("data") or {}).get("raw_url") if isinstance(data, dict) else None
                    if raw:
                        url = str(raw)
                        if self.strm_replace_host:
                            base = self.strm_replace_host
                            if not base.startswith("http"):
                                base = f"http://{base}"
                            target = urlsplit(base)
                            src = urlsplit(url)
                            url = urlunsplit((target.scheme or src.scheme, target.netloc or src.netloc, src.path, src.query, src.fragment))
                except Exception as e:
                    logger.warning("📺 Alist-Strm生成: 获取 raw_url 失败 %s", e)
                    url = None
            if not url:
                sign_param = "" if not file_info.get("sign") else f"?sign={file_info['sign']}"
                url = f"{self.strm_server}{file_path}{sign_param}"
            with open(strm_path, "w", encoding="utf-8") as strm_file:
                strm_file.write(url)
            logger.info("📺 生成STRM文件 %s 成功", strm_path)

    def get_root_folder_full_path(self, cookie, pdir_fid):
        if pdir_fid == "0":
            return "/"
        url = "https://drive-h.quark.cn/1/clouddrive/file/sort"
        headers = {
            "cookie": cookie,
            "content-type": "application/json",
        }
        querystring = {
            "pr": "ucpro",
            "fr": "pc",
            "uc_param_str": "",
            "pdir_fid": pdir_fid,
            "_page": 1,
            "_size": "50",
            "_fetch_total": "1",
            "_fetch_sub_dirs": "0",
            "_sort": "file_type:asc,updated_at:desc",
            "_fetch_full_path": 1,
        }
        try:
            response = requests.request(
                "GET", url, headers=headers, params=querystring
            ).json()
            if response["code"] == 0:
                path = ""
                for item in response["data"]["full_path"]:
                    path = f"{path}/{item['file_name']}"
                return path
        except Exception as e:
            logger.exception("Alist-Strm生成: 获取Quark路径出错 %s", e)
        return ""

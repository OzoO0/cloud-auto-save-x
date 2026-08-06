import json
import logging
import os
import posixpath
import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import requests

from app.thirdparty.openlist_client import OpenListClient


logger = logging.getLogger(__name__)


class Alist_strm_gen:

    video_exts = ["mp4", "mkv", "flv", "mov", "m4v", "avi", "webm", "wmv", "cas"]
    default_config = {
        "url": "",  # Alist服务器URL
        "token": "",  # Alist服务器Token
        "storage_id": "",  # Alist存储ID 或 /挂载路径:/目标端点根目录 (推荐)
        "strm_save_dir": "/media",  # strm文件保存目录
        "strm_replace_host": "",  # 替换的 strm 服务器地址
    }
    default_task_config = {
        "auto_gen": True,  # 是否自动动生成 strm 文件
    }
    is_active = False
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
        task_config = task.get("addition", {}).get(self.plugin_name, self.default_task_config)
        if not task_config.get("auto_gen"):
            return

        target = task.get("target") if isinstance(task, dict) else None
        target_type = ""
        savepath = ""
        if isinstance(target, dict):
            target_type = str(target.get("type") or "").lower().strip()
        if isinstance(target, dict) and target_type == "openlist":
            savepath = str(target.get("path") or "").strip()
        if not savepath or not self.storage_mount_path:
            if target_type == "local":
                rel = self._norm_rel(str(target.get("path") or "")) if isinstance(target, dict) else ""
                if not rel:
                    return
                root = str(getattr(self, "root_dir", "") or "").strip() or "/"
                savepath = self._join_openlist(root, rel)
            else:
                return
        if target_type not in {"openlist", "local"}:
            return
        mapped = self._map_task_savepath(savepath)
        if not mapped:
            return
        tree = kwargs.get("tree")
        delta_files = self._extract_changed_openlist_video_files(tree, root_openlist_path=savepath, mapped_openlist_path=mapped, target_type=target_type, target_rel=str(target.get("path") or "") if isinstance(target, dict) else "")
        if delta_files:
            self._refresh_openlist_dirs(delta_files)
            for fp in delta_files:
                self.generate_strm(fp, {})
            return

        if target_type == "openlist":
            self.check_dir(mapped)
            return
        self._check_local_dir(self._local_sync_root() / self._norm_rel(str(target.get("path") or "")), mapped_openlist_path=mapped)

    def _extract_changed_openlist_video_files(
        self,
        tree,
        *,
        root_openlist_path: str,
        mapped_openlist_path: str,
        target_type: str,
        target_rel: str,
    ) -> list[str]:
        if not tree:
            return []
        root_openlist_path = self._norm_path(root_openlist_path)
        out: list[str] = []
        seen: set[str] = set()
        try:
            nodes = tree.all_nodes()
        except Exception:
            return []
        for node in nodes:
            data = getattr(node, "data", None)
            if not isinstance(data, dict):
                continue
            if bool(data.get("is_dir")):
                continue
            action = str(data.get("action") or "").lower()
            status = str(data.get("status") or "").lower()
            if action != "copy" or status != "success":
                continue
            path = str(data.get("path") or "").strip()
            if not path:
                continue
            openlist_file_path = None
            if target_type == "openlist":
                if not path.startswith("/"):
                    continue
                if not self._norm_path(path).startswith(root_openlist_path):
                    continue
                openlist_file_path = path
            elif target_type == "local":
                rel_base = self._norm_rel(target_rel)
                prefix = posixpath.normpath(posixpath.join("data", "sync", rel_base)).rstrip("/")
                if not path.startswith(prefix):
                    continue
                suffix = path[len(prefix) :].lstrip("/")
                if not suffix:
                    continue
                openlist_file_path = self._join_openlist(mapped_openlist_path, suffix)
            if not openlist_file_path:
                continue
            ext = openlist_file_path.rsplit(".", 1)[-1].lower() if "." in openlist_file_path else ""
            if ext not in self.video_exts:
                continue
            if openlist_file_path in seen:
                continue
            seen.add(openlist_file_path)
            out.append(openlist_file_path)
        return out

    def _refresh_openlist_dirs(self, file_paths: list[str]) -> None:
        if not self.client:
            return
        dirs: set[str] = set()
        for p in file_paths:
            parent = posixpath.dirname(str(p))
            if not parent:
                continue
            dirs.add(self._norm_path(parent))
        for d in sorted(dirs):
            try:
                self.client.fs_list(d, refresh=True, page=1, per_page=1)
            except Exception:
                continue

    @staticmethod
    def _norm_rel(p: str) -> str:
        p = str(p or "").replace("\\", "/").strip()
        p = p.lstrip("/")
        if not p:
            return ""
        p = posixpath.normpath(p)
        if p == ".":
            return ""
        return p

    @staticmethod
    def _join_openlist(root: str, rel: str) -> str:
        root = str(root or "").strip() or "/"
        if not root.startswith("/"):
            root = "/" + root
        root = posixpath.normpath(root)
        rel = Alist_strm_gen._norm_rel(rel)
        if not rel:
            return root
        return posixpath.normpath(posixpath.join(root, rel))

    @staticmethod
    def _local_sync_root() -> Path:
        backend_dir = Path(__file__).resolve().parents[3]
        return backend_dir / "data" / "sync"

    def _check_local_dir(self, path: Path, *, mapped_openlist_path: str) -> None:
        try:
            base = path.resolve()
        except Exception:
            base = path
        if not base.exists() or not base.is_dir():
            return
        for root, _dirs, files in os.walk(str(base)):
            for name in files:
                ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
                if ext not in self.video_exts:
                    continue
                full = Path(root) / name
                try:
                    rel = full.relative_to(base).as_posix()
                except Exception:
                    rel = name
                openlist_file_path = self._join_openlist(mapped_openlist_path, rel)
                self.generate_strm(openlist_file_path, {})

    @staticmethod
    def _norm_path(path: str) -> str:
        p = str(path or "").strip() or "/"
        p = "/" + posixpath.normpath(p).lstrip("/")
        if p != "/" and p.endswith("/"):
            p = p.rstrip("/")
        return p

    @staticmethod
    def _pick_name(payload: dict) -> str:
        return str(payload.get("name") or payload.get("file_name") or payload.get("fileName") or payload.get("title") or "")

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
            return os.path.normpath(os.path.join(self.storage_mount_path, rel.lstrip("/"))).replace("\\", "/")

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
        if match := re.match(r"^(\/[^:]*):(\/[^:]*)$", storage_id):
            storage_mount_path, root_dir = self._norm_path(match.group(1)), self._norm_path(match.group(2))
            if not self.client:
                return False, (None, None)
            try:
                self.client.fs_list(storage_mount_path, refresh=False, page=1, per_page=1)
            except Exception as e:
                logger.warning("Alist-Strm生成: 获取挂载路径失败 %s", e)
                return False, (None, None)
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
                mount_raw = str(storage_info.get("mount_path") or storage_info.get("mountPath") or storage_info.get("mount") or "").strip()
                if not mount_raw:
                    logger.warning("Alist-Strm生成: storage_id[%s] 未返回 mount_path", storage_id)
                    return False, (None, None)
                storage_mount_path = self._norm_path(mount_raw)
                root_dir = configured_root_dir or ""
                if (not configured_root_dir) and storage_info.get("driver") == "Quark":
                    try:
                        addition = json.loads(storage_info.get("addition") or "{}")
                        root_dir = self._norm_path(self.get_root_folder_full_path(addition.get("cookie"), addition.get("root_folder_id")))
                    except Exception:
                        root_dir = ""
                if not root_dir:
                    logger.info("Alist-Strm生成: 未配置root_dir，将在运行时尝试根据任务savepath自动探测映射路径")
        else:
            if not storage_id:
                logger.warning("Alist-Strm生成: storage_id 为空")
            else:
                storage_mount_path = self._norm_path(storage_id)
                root_dir = configured_root_dir or ""
                if not root_dir:
                    logger.info("Alist-Strm生成: 未配置root_dir，将在运行时尝试根据任务savepath自动探测映射路径")
                if not self.client:
                    return False, (None, None)
                try:
                    self.client.fs_list(storage_mount_path, refresh=False, page=1, per_page=1)
                except Exception as e:
                    logger.warning("Alist-Strm生成: 获取挂载路径失败 %s", e)
                    return False, (None, None)
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
            strm_path = f"{self.strm_save_dir}{os.path.splitext(file_path)[0]}.strm".replace("//", "/")
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
                            url = urlunsplit(
                                (target.scheme or src.scheme, target.netloc or src.netloc, src.path, src.query, src.fragment)
                            )
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
            response = requests.request("GET", url, headers=headers, params=querystring).json()
            if response["code"] == 0:
                path = ""
                for item in response["data"]["full_path"]:
                    path = f"{path}/{item['file_name']}"
                return path
        except Exception as e:
            logger.exception("Alist-Strm生成: 获取Quark路径出错 %s", e)
        return ""

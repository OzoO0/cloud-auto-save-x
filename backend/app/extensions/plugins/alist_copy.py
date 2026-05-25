import json
import posixpath

import requests


class Alist_copy:
    plugin_name = "alist_copy"

    default_config = {
        "url": "",  # Alist服务器URL
        "token": "",  # Alist服务器Token
        "global_enable": False,  # 全局开关，开启后任意任务完成都会触发复制
        "source_path": "",  # 默认源目录，例如 /网盘A/电视剧/某剧
        "target_path": "",  # 默认目标目录或目标父目录，例如 /网盘B/电视剧/某剧
        "overwrite": False,  # 开启后不跳过同名项，直接提交复制请求
        "refresh": True,  # 获取目录列表时刷新 Alist 缓存
        "recursive_incremental": True,  # 目标目录存在时递归增量复制
    }

    default_task_config = {
        "enable": False,  # 当前任务开关
        "source_path": "",  # 当前任务源目录，留空使用全局配置
        "target_path": "",  # 当前任务目标目录或目标父目录，留空使用全局配置
        "overwrite": False,  # 当前任务是否复制同名项
        "refresh": True,  # 当前任务是否刷新目录缓存
        "recursive_incremental": True,  # 当前任务是否递归增量复制
    }

    is_active = False

    def __init__(self, **kwargs):
        for key, value in self.default_config.items():
            setattr(self, key, value)

        if kwargs:
            for key in self.default_config:
                if key in kwargs:
                    setattr(self, key, kwargs[key])
                else:
                    print(f"{self.plugin_name} 模块缺少必要参数: {key}")

        if self.url and self.token and self.verify_server():
            self.is_active = True

    def run(self, task, **kwargs):
        try:
            task_config = task.get("addition", {}).get(self.plugin_name, {}) or {}
            if not self._is_enabled(task_config):
                return task

            use_task_config = bool(task_config.get("enable"))
            source_path = self._config_path(task_config, "source_path", use_task_config)
            target_path = self._config_path(task_config, "target_path", use_task_config)
            if not source_path or not target_path:
                print(f"{self.plugin_name}: source_path 或 target_path 为空，跳过复制")
                return task

            overwrite = self._config_bool(task_config, "overwrite", use_task_config)
            refresh = self._config_bool(task_config, "refresh", use_task_config)
            recursive = self._config_bool(task_config, "recursive_incremental", use_task_config)

            source_path = self._norm_path(source_path)
            target_path = self._norm_path(target_path)
            print(f"{self.plugin_name}: 开始复制 {source_path} -> {target_path}")
            self.copy_to_target(source_path, target_path, overwrite=overwrite, refresh=refresh, recursive=recursive)
            return task
        except Exception as e:
            print(f"{self.plugin_name}: 运行出错 {e}")
            return task

    def _is_enabled(self, task_config):
        return bool(task_config.get("enable")) or bool(getattr(self, "global_enable", False))

    def _config_path(self, task_config, key, use_task_config):
        value = task_config.get(key) if use_task_config else ""
        if value:
            return value
        return getattr(self, key, "")

    def _config_bool(self, task_config, key, use_task_config):
        if use_task_config and key in task_config:
            return bool(task_config.get(key))
        return bool(getattr(self, key, self.default_config.get(key, False)))

    def verify_server(self):
        try:
            response = self._send_request("GET", "/api/me")
            data = response.json()
            if response.status_code == 200 and data.get("code") == 200:
                username = (data.get("data") or {}).get("username")
                if username == "guest":
                    print(f"{self.plugin_name}: Alist登陆失败，请检查token")
                    return False
                print(f"{self.plugin_name}: Alist登陆成功，当前用户: {username}")
                return True
            print(f"{self.plugin_name}: 连接服务器失败 {data.get('message')}")
        except Exception as e:
            print(f"{self.plugin_name}: 获取Alist信息出错 {e}")
        return False

    def copy_to_target(self, source_path, target_path, *, overwrite=False, refresh=True, recursive=True):
        source_name = posixpath.basename(source_path.rstrip("/"))
        source_parent = self._parent_path(source_path)
        if not source_name:
            print(f"{self.plugin_name}: 源路径不能为根目录")
            return False

        print(f"{self.plugin_name}: 检查源目录 {source_path}")
        source_entries = self.list_dir(source_path, refresh=refresh)
        if source_entries is None:
            return self.copy_file(source_parent, source_name, target_path, overwrite=overwrite, refresh=refresh)

        target_name = posixpath.basename(target_path.rstrip("/"))
        if target_name == source_name:
            return self.copy_to_final_dir(
                source_path,
                source_parent,
                source_name,
                target_path,
                overwrite=overwrite,
                refresh=refresh,
                recursive=recursive,
            )

        target_parent = target_path
        print(f"{self.plugin_name}: 检查目标父目录 {target_parent}")
        target_entries = self.list_dir(target_parent, refresh=refresh)
        if target_entries is None:
            print(f"{self.plugin_name}: 目标父目录不存在或不可访问 {target_parent}")
            return False
        target_item = self._find_by_name(target_entries, source_name)
        if not target_item:
            ok = self.copy_names(source_parent, target_parent, [source_name])
            if ok:
                print(f"{self.plugin_name}: 目标目录不存在，已复制整个目录 {source_name}")
            return ok

        if not target_item.get("is_dir"):
            print(f"{self.plugin_name}: 目标已存在同名文件，无法作为目录增量复制 {source_name}")
            return False

        target_dir = self._join_path(target_parent, source_name)
        return self.copy_dir_contents(
            source_path,
            target_dir,
            overwrite=overwrite,
            refresh=refresh,
            recursive=recursive,
        )

    def copy_to_final_dir(
        self,
        source_path,
        source_parent,
        source_name,
        target_dir,
        *,
        overwrite=False,
        refresh=True,
        recursive=True,
    ):
        print(f"{self.plugin_name}: 检查目标目录 {target_dir}")
        target_entries = self.list_dir(target_dir, refresh=refresh)
        if target_entries is not None:
            return self.copy_dir_contents(
                source_path,
                target_dir,
                overwrite=overwrite,
                refresh=refresh,
                recursive=recursive,
            )

        target_parent = self._parent_path(target_dir)
        print(f"{self.plugin_name}: 目标目录不存在，检查目标上级目录 {target_parent}")
        parent_entries = self.list_dir(target_parent, refresh=refresh)
        if parent_entries is None:
            print(f"{self.plugin_name}: 目标上级目录不存在或不可访问 {target_parent}")
            return False

        target_name = posixpath.basename(target_dir.rstrip("/"))
        if target_name != source_name:
            print(f"{self.plugin_name}: 目标目录名 {target_name} 与源目录名 {source_name} 不一致，Alist复制不能自动重命名")
            return False

        ok = self.copy_names(source_parent, target_parent, [source_name])
        if ok:
            print(f"{self.plugin_name}: 目标目录不存在，已复制整个目录到 {target_dir}")
        return ok

    def copy_file(self, source_parent, source_name, target_parent, *, overwrite=False, refresh=True):
        print(f"{self.plugin_name}: 检查源上级目录 {source_parent}")
        source_entries = self.list_dir(source_parent, refresh=refresh)
        if source_entries is None or not self._find_by_name(source_entries, source_name):
            print(f"{self.plugin_name}: 源文件或源目录不存在 {self._join_path(source_parent, source_name)}")
            return False

        print(f"{self.plugin_name}: 检查目标目录 {target_parent}")
        target_entries = self.list_dir(target_parent, refresh=refresh)
        if target_entries is None:
            print(f"{self.plugin_name}: 目标目录不存在或不可访问 {target_parent}")
            target_parent_parent = self._parent_path(target_parent)
            if target_parent_parent != target_parent:
                print(f"{self.plugin_name}: 继续检查目标上级目录 {target_parent_parent}")
                self.list_dir(target_parent_parent, refresh=refresh)
            return False

        if not overwrite and self._find_by_name(target_entries, source_name):
            print(f"{self.plugin_name}: 目标已存在同名文件，跳过 {source_name}")
            return True

        return self.copy_names(source_parent, target_parent, [source_name])

    def copy_dir_contents(self, source_dir, target_dir, *, overwrite=False, refresh=True, recursive=True):
        print(f"{self.plugin_name}: 检查源子目录 {source_dir}")
        source_entries = self.list_dir(source_dir, refresh=refresh)
        if source_entries is None:
            print(f"{self.plugin_name}: 源目录不存在或不可访问 {source_dir}")
            return False

        print(f"{self.plugin_name}: 检查目标子目录 {target_dir}")
        target_entries = self.list_dir(target_dir, refresh=refresh)
        if target_entries is None:
            print(f"{self.plugin_name}: 目标目录不存在或不可访问 {target_dir}")
            return False

        names = [item.get("name") for item in source_entries if item.get("name")]
        if overwrite:
            return self.copy_names(source_dir, target_dir, names)

        target_by_name = {item.get("name"): item for item in target_entries if item.get("name")}
        missing_names = []
        common_dirs = []
        for item in source_entries:
            name = item.get("name")
            if not name:
                continue
            target_item = target_by_name.get(name)
            if not target_item:
                missing_names.append(name)
            elif recursive and item.get("is_dir") and target_item.get("is_dir"):
                common_dirs.append(name)

        copied = 0
        success = True
        if missing_names:
            if self.copy_names(source_dir, target_dir, missing_names):
                copied += len(missing_names)
                print(f"{self.plugin_name}: 增量复制 {len(missing_names)} 项 -> {target_dir}")
            else:
                success = False

        for name in common_dirs:
            source_child = self._join_path(source_dir, name)
            target_child = self._join_path(target_dir, name)
            child_ok = self.copy_dir_contents(
                source_child,
                target_child,
                overwrite=overwrite,
                refresh=refresh,
                recursive=recursive,
            )
            if child_ok:
                copied += 1
            else:
                success = False

        if copied == 0:
            print(f"{self.plugin_name}: 无需复制，目标已包含源目录内容 {target_dir}")
        return success

    def copy_names(self, source_dir, target_dir, names):
        names = [name for name in names if name]
        if not names:
            return True

        payload = {
            "src_dir": source_dir,
            "dst_dir": target_dir,
            "names": names,
        }
        response = self._send_request("POST", "/api/fs/copy", data=json.dumps(payload))
        try:
            data = response.json()
        except Exception:
            data = {}
        if response.status_code == 200 and data.get("code", 200) == 200:
            print(f"{self.plugin_name}: Alist复制任务创建成功 {source_dir} -> {target_dir}")
            return True
        print(f"{self.plugin_name}: Alist复制任务创建失败 {data.get('message') or response.text}")
        return False

    def list_dir(self, path, *, refresh=True):
        payload = {
            "path": path,
            "password": "",
            "page": 1,
            "per_page": 0,
            "refresh": bool(refresh),
        }
        response = self._send_request("POST", "/api/fs/list", data=json.dumps(payload))
        try:
            data = response.json()
        except Exception:
            print(f"{self.plugin_name}: 获取目录失败 {path}，HTTP {response.status_code}，响应不是JSON: {response.text}")
            return None

        if response.status_code != 200 or data.get("code") != 200:
            print(
                f"{self.plugin_name}: 目录不可访问 {path}，"
                f"HTTP {response.status_code}，code={data.get('code')}，message={data.get('message')}"
            )
            return None
        content = (data.get("data") or {}).get("content") or []
        print(f"{self.plugin_name}: 目录可访问 {path}，包含 {len(content) if isinstance(content, list) else 0} 项")
        return content if isinstance(content, list) else []

    def _send_request(self, method, endpoint, **kwargs):
        headers = {"Authorization": self.token, "Content-Type": "application/json"}
        endpoint = "/" + endpoint.lstrip("/")
        return requests.request(method, f"{self.url.rstrip('/')}{endpoint}", headers=headers, **kwargs)

    def _find_by_name(self, entries, name):
        for item in entries:
            if item.get("name") == name:
                return item
        return None

    def _parent_path(self, path):
        parent = posixpath.dirname(path.rstrip("/"))
        return parent if parent else "/"

    def _join_path(self, parent, name):
        return self._norm_path(posixpath.join(parent, name))

    def _norm_path(self, path):
        path = str(path or "").strip().replace("\\", "/")
        if not path:
            return ""
        if not path.startswith("/"):
            path = "/" + path
        path = posixpath.normpath(path)
        return "/" if path == "." else path

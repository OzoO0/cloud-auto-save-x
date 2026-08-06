# 同步任务插件开发指南

本目录下的插件用于在“同步任务”执行完成后扩展能力（例如：生成 strm、刷新 Emby/Plex、通知等）。

转存/追剧任务插件请看 `../plugins/README.md`。

## 目录与命名

- **插件位置**：`backend/app/extensions/sync_plugins/`
- **命名规范**
  - 文件名：小写（如 `smartstrm.py`, `alist_strm_gen.py`）
  - 类名：使用 `module_name.capitalize()` 规则（如 `smartstrm.py` → `Smartstrm`；`alist_strm_gen.py` → `Alist_strm_gen`）

## 配置来源（数据库）

- **全局配置**：在前端“同步任务插件”管理页配置，后端存入同步插件配置表（`config_json`）。
- **任务级配置**：保存在同步任务的 `addition_json` 中（JSON 对象），结构为：

```json
{
  "alist_strm_gen": { "auto_gen": true },
  "emby": { "try_match": true, "media_id": "0" },
  "plex": { "enable": true }
}
```

说明：
- `default_config` / `default_task_config` 中的行尾注释会被解析为字段说明，用于前端渲染表单。
- 插件 key 默认等于文件名（也可在类里用 `plugin_name` 覆盖）。

## 插件结构与钩子

```python
class YourPlugin:
    default_config = {
        "url": "",  # 服务地址
        "token": "",  # token
    }
    default_task_config = {
        "enable": True,  # 任务级开关
    }
    is_active = False

    def __init__(self, **kwargs):
        self.plugin_name = self.__class__.__name__.lower()
        for k in self.default_config:
            if k in kwargs:
                setattr(self, k, kwargs[k])
        if self._check_config():
            self.is_active = True

    def _check_config(self) -> bool:
        return True

    def task_before(self, tasklist, account):
        return tasklist

    def run(self, task, **kwargs):
        tree = kwargs.get("tree")
        task_config = task.get("addition", {}).get(self.plugin_name, self.default_task_config)
        if not task_config.get("enable", True):
            return task
        return task

    def task_after(self, tasklist, account):
        return {"tasklist": tasklist}
```

执行语义：
- `task_before(tasklist, account)`：同步插件阶段开始前
- `run(task, account=None, tree=...)`：同步任务“同步完成后”执行
- `task_after(tasklist, account)`：同步插件阶段结束后（可选）

注意：
- 同步任务插件当前不会传入网盘账号实例，`account` 固定为 `None`。
- 只有当插件实例 `is_active=True` 才会进入执行流程；若插件做了连通性校验（如 Emby/Plex/SmartStrm），校验失败会导致 `is_active=False`，从而被跳过。

## task / tree 入参形状（参考）

插件 `run(task, tree=...)` 中的 `task` 形状（关键字段）：

```json
{
  "uid": "2488c73caa9c4e3eaca4b9138365f662",
  "name": "我的同步任务",
  "source": { "type": "openlist", "path": "/源目录" },
  "target": { "type": "openlist", "path": "/目标目录" },
  "mode": "one_way",
  "strategy": { "overwrite": false, "force_refresh": false },
  "addition": { "alist_strm_gen": { "auto_gen": true } },
  "execution_id": 50,
  "stats": { "copied_files": 1 }
}
```

`tree` 为文件变动树（treelib.Tree），节点 `data` 常见字段：
- `path`: 变动文件路径（openlist 目标时通常以 `/` 开头；local 目标时可能是 `data/sync/...`）
- `action`: `copy` / `delete` / ...
- `status`: `success` / `failed` / `skipped` / ...
- `is_dir`: 是否目录
- `size`, `message`: 可选信息

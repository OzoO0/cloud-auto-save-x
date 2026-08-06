from __future__ import annotations

from typing import Any

from app.services.telegram_bot.callbacks import cb


def keyboard(rows: list[list[dict[str, str]]]) -> dict[str, Any]:
    return {"inline_keyboard": rows}


def button(text: str, *parts: object) -> dict[str, str]:
    return {"text": text, "callback_data": cb(*parts)}


def truncate(value: str, *, limit: int = 3500) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return text[: limit - 20] + "\n\n... 已截断 ..."


def bool_text(value: Any) -> str:
    return "是" if bool(value) else "否"


def switch_text(value: Any) -> str:
    return "开" if bool(value) else "关"


def file_size_text(value: Any) -> str:
    try:
        size = float(value or 0)
    except Exception:
        size = 0
    if size <= 0:
        return "-"
    units = ["B", "KB", "MB", "GB", "TB"]
    idx = 0
    while size >= 1024 and idx < len(units) - 1:
        size /= 1024
        idx += 1
    if idx == 0:
        return f"{int(size)} {units[idx]}"
    return f"{size:.1f} {units[idx]}"


def tmdb_brief_label(item: dict[str, Any]) -> str:
    title = str(item.get("display_title") or item.get("title") or item.get("name") or "-").strip() or "-"
    media_type = str(item.get("media_type") or "").strip().lower() or "-"
    date_text = str(item.get("display_date") or item.get("release_date") or item.get("first_air_date") or "").strip()
    return f"{title} [{media_type}{' ' + date_text if date_text else ''}]"


def _emoji_verify(value: Any) -> str:
    if value is True:
        return "✅"
    if value is False:
        return "❌"
    return "❔"


def _short_text(value: Any, limit: int = 72) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _nested_value(target: dict[str, Any], path: str) -> Any:
    node: Any = target
    for part in [p for p in str(path).split(".") if p]:
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    return node


def home_message() -> str:
    return (
        "TG 控制台已就绪\n\n"
        "可通过菜单查看任务、同步、资源搜索、账号管理、系统设置和运行状态。\n"
        "复杂输入会进入向导模式，随时可用 /cancel 取消。"
    )


def home_keyboard() -> dict[str, Any]:
    return keyboard(
        [
            [button("📋 任务管理", "menu", "tasks"), button("🔄 同步任务", "menu", "sync")],
            [button("🔎 资源搜索", "menu", "search"), button("👥 账号管理", "menu", "accounts")],
            [button("⚙️ 系统设置", "menu", "settings"), button("📊 运行状态", "menu", "status")],
        ]
    )


def pagination_row(prefix: str, page: int, total: int, page_size: int, *extra: object) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    max_page = max(1, (int(total or 0) + page_size - 1) // page_size)
    prev_page = max(1, page - 1)
    next_page = min(max_page, page + 1)
    rows.append(button("🔄 刷新", prefix, *extra, page))
    if page > 1:
        rows.append(button("⬅️ 上一页", prefix, *extra, prev_page))
    if page < max_page:
        rows.append(button("➡️ 下一页", prefix, *extra, next_page))
    rows.append(button("🏠 首页", "home"))
    return rows


def status_message(summary: dict[str, Any]) -> str:
    drama = summary.get("drama_summary") or {}
    cap = summary.get("capacity_summary") or {}
    return truncate(
        "\n".join(
            [
                "📊 系统状态",
                "",
                "🧩 任务",
                f"总数: {summary.get('tasks_total', 0)}",
                f"启用: {summary.get('tasks_enabled', 0)}",
                "",
                "🔄 同步",
                f"总数: {summary.get('sync_total', 0)}",
                f"运行中: {summary.get('sync_running', 0)}",
                "",
                "🎬 追剧执行",
                f"成功: {drama.get('execution_success', 0)}",
                f"失败: {drama.get('execution_failed', 0)}",
                "",
                "👤 账号",
                f"总数: {cap.get('account_count', 0)}",
                f"告警: {cap.get('warning_account_count', 0)}",
                "",
                f"🕒 更新时间: {summary.get('updated_at') or '-'}",
            ]
        )
    )


def tasks_message(payload: dict[str, Any], *, title: str = "任务列表") -> str:
    items = payload.get("items") or []
    lines = [f"📋 {title} · 第 {payload.get('page', 1)} 页"]
    if not items:
        lines.append("暂无数据")
    for item in items:
        status = "🟢 启用" if item.get("enabled") else "⚪ 停用"
        lines.append("")
        lines.append(f"#{item.get('id')} {_short_text(item.get('taskname') or '-', 58)}")
        lines.append(f"🎬 追剧任务 · {status}")
        if item.get("account_name"):
            lines.append(f"👤 {item.get('account_name')}")
        if item.get("savepath"):
            lines.append(f"💾 {_short_text(item.get('savepath') or '-', 72)}")
    lines.append("")
    lines.append(f"共 {payload.get('total', 0)} 条")
    return truncate("\n".join(lines))


def task_detail_message(item: dict[str, Any]) -> str:
    execution = item.get("latest_execution") or {}
    linked_sync = item.get("sync_task_names") or item.get("sync_task_uids") or []
    status_text = "🟢 启用" if item.get("enabled") else "⚪ 停用"
    tmdb_media_type = str(item.get("tmdb_media_type") or "").strip() or "-"
    tmdb_id = item.get("tmdb_id") or "-"
    exec_status = str(execution.get("status") or "-")
    exec_message = _short_text(execution.get("message") or "-", 72)
    lines = [
        f"📌 任务详情 · #{item.get('id')}",
        f"📝 {_short_text(item.get('taskname') or '-', 72)}",
        f"🎬 追剧任务 · {status_text}",
        "",
        f"💾 保存路径: {_short_text(item.get('savepath') or '-', 88)}",
        f"👤 执行账号: {item.get('account_name') or '-'}",
        f"🎬 TMDB: {tmdb_media_type} / {tmdb_id}",
        f"🔗 关联同步: {_short_text(', '.join(linked_sync) or '-', 88)}",
        "",
        f"🚦 最近执行: {exec_status}",
        f"📣 执行说明: {exec_message}",
        f"🔗 分享链接: {_short_text(item.get('shareurl') or '-', 88)}",
    ]
    return truncate("\n".join(lines))


def task_detail_keyboard(task_id: int, enabled: bool, *, back_page: int = 1, task_type: str | None = None) -> dict[str, Any]:
    toggle_text = "⏸️ 停用" if enabled else "▶️ 启用"
    list_button = button("📋 返回列表", "tsk", "list", task_type or "all", back_page) if task_type else button("📋 返回列表", "tsk", "list", back_page)
    return keyboard(
        [
            [button("▶️ 运行", "tsk", "run", task_id), button(toggle_text, "tsk", "toggle", task_id)],
            [button("✏️ 编辑", "tsk", "edit", task_id), button("🔎 搜索换链", "tsk", "search", task_id)],
            [button("🧾 执行记录", "tsk", "execs", task_id), button("🗑️ 删除", "tsk", "delete", task_id)],
            [list_button, button("🏠 首页", "home")],
        ]
    )


def sync_tasks_message(payload: dict[str, Any]) -> str:
    items = payload.get("items") or []
    lines = [f"🔄 同步任务 · 第 {payload.get('page', 1)} 页"]
    if not items:
        lines.append("暂无数据")
    for item in items:
        status = "🟢 启用" if item.get("enabled") else "⚪ 停用"
        lines.append("")
        lines.append(f"#{item.get('id')} {_short_text(item.get('name') or '-', 58)}")
        lines.append(f"🏷️ {item.get('mode') or '-'} · {status}")
        source = item.get("source", {}) or {}
        target = item.get("target", {}) or {}
        if source.get("path"):
            lines.append(f"📥 {_short_text(source.get('path') or '-', 68)}")
        if target.get("path"):
            lines.append(f"📤 {_short_text(target.get('path') or '-', 68)}")
    lines.append("")
    lines.append(f"共 {payload.get('total', 0)} 条")
    return truncate("\n".join(lines))


def sync_detail_message(item: dict[str, Any]) -> str:
    execution = item.get("latest_execution") or {}
    linked_drama = item.get("drama_task_names") or item.get("drama_task_uids") or []
    status_text = "🟢 启用" if item.get("enabled") else "⚪ 停用"
    source = item.get("source", {}) or {}
    target = item.get("target", {}) or {}
    exec_status = str(execution.get("status") or "-")
    exec_message = _short_text(execution.get("message") or "-", 72)
    lines = [
        f"🔄 同步详情 · #{item.get('id')}",
        f"📝 {_short_text(item.get('name') or '-', 72)}",
        f"🏷️ {item.get('mode') or '-'} · {status_text}",
        "",
        f"📥 源: {source.get('type') or '-'}",
        f"   {_short_text(source.get('path') or '-', 88)}",
        f"📤 目标: {target.get('type') or '-'}",
        f"   {_short_text(target.get('path') or '-', 88)}",
        f"🎬 关联追剧: {_short_text(', '.join(linked_drama) or '-', 88)}",
        "",
        f"🚦 最近执行: {exec_status}",
        f"📣 执行说明: {exec_message}",
    ]
    return truncate("\n".join(lines))


def sync_detail_keyboard(sync_task_id: int, enabled: bool, *, back_page: int = 1) -> dict[str, Any]:
    toggle_text = "⏸️ 停用" if enabled else "▶️ 启用"
    return keyboard(
        [
            [button("▶️ 运行", "syn", "run", sync_task_id), button("⏹️ 取消运行", "syn", "cancel", sync_task_id)],
            [button(toggle_text, "syn", "toggle", sync_task_id), button("✏️ 编辑", "syn", "edit", sync_task_id)],
            [button("🧾 执行记录", "syn", "execs", sync_task_id), button("🗑️ 删除", "syn", "delete", sync_task_id)],
            [button("📋 返回列表", "syn", "list", back_page), button("🏠 首页", "home")],
        ]
    )


def accounts_message(payload: dict[str, Any]) -> str:
    items = payload.get("items") or []
    lines = [f"👥 账号列表 · 第 {payload.get('page', 1)} 页"]
    if not items:
        lines.append("暂无数据")
    for item in items:
        status = "🟢 启用" if item.get("enabled") else "⚪ 停用"
        default = "⭐ 默认" if item.get("is_default") else ""
        lines.append("")
        lines.append(f"#{item.get('id')} {_short_text(item.get('name') or '-', 58)}")
        lines.append(f"🏷️ {item.get('drive_type') or '-'} · {status}")
        lines.append(f"📡 {item.get('runtime_status') or '-'} {default}".rstrip())
        if item.get("last_error"):
            lines.append(f"⚠️ {_short_text(item.get('last_error') or '-', 68)}")
    lines.append("")
    lines.append(f"共 {payload.get('total', 0)} 条")
    return truncate("\n".join(lines))


def account_detail_message(item: dict[str, Any]) -> str:
    enabled_text = "🟢 启用" if item.get("enabled") else "⚪ 停用"
    default_text = "⭐ 默认账号" if item.get("is_default") else "普通账号"
    runtime_status = str(item.get("runtime_status") or "-")
    last_error = _short_text(item.get("last_error") or "-", 88)
    lines = [
        f"👤 账号详情 · #{item.get('id')}",
        f"📝 {_short_text(item.get('name') or '-', 72)}",
        f"🏷️ {item.get('drive_type') or '-'} · {enabled_text}",
        f"{default_text}",
        "",
        f"📡 运行状态: {runtime_status}",
        f"⚠️ 最近错误: {last_error}",
        f"📦 容量告警阈值: {item.get('capacity_warning_threshold')}",
    ]
    return truncate("\n".join(lines))


def account_detail_keyboard(account_id: int, enabled: bool, is_default: bool, *, back_page: int = 1) -> dict[str, Any]:
    toggle_text = "⏸️ 停用" if enabled else "▶️ 启用"
    default_text = "⭐ 已默认" if is_default else "⭐ 设默认"
    return keyboard(
        [
            [button(toggle_text, "acc", "toggle", account_id), button(default_text, "acc", "default", account_id)],
            [button("🛰️ 探测", "acc", "probe", account_id), button("🪪 签到", "acc", "signin", account_id)],
            [button("🔐 认证", "acc", "auth", account_id), button("✏️ 编辑", "acc", "edit", account_id)],
            [button("📋 返回列表", "acc", "list", back_page), button("🏠 首页", "home")],
        ]
    )


def settings_domains_message(_domains: list[dict[str, str]]) -> str:
    return truncate(
        "\n".join(
            [
                "⚙️ 系统设置",
                "",
                "选择要查看或修改的配置域。",
                "布尔开关可直接点击切换，其他字段会进入输入模式。",
            ]
        )
    )


def settings_domains_keyboard(domains: list[dict[str, str]]) -> dict[str, Any]:
    rows = [[button(item.get("label") or item.get("key") or "", "cfg", "domain", item.get("key"))] for item in domains]
    rows.append([button("🏠 首页", "home")])
    return keyboard(rows)


def setting_domain_message(
    domain: dict[str, Any],
    fields: list[dict[str, Any]],
    *,
    current_field: str | None = None,
    values: dict[str, Any] | None = None,
) -> str:
    values = values if values is not None else (domain.get("values") or {})
    updated_at = str(domain.get("updated_at") or "").strip()
    lines = [f"⚙️ {domain.get('label') or domain.get('key') or '配置'}"]
    if updated_at:
        lines.append(f"🕒 更新时间: {updated_at}")
    lines.append("")
    if not fields:
        lines.append("暂无可编辑字段")
    for field in fields:
        key = str(field.get("key") or "")
        label = str(field.get("label") or key)
        marker = "  <- 当前" if current_field == key else ""
        lines.append(f"{label}: {_editor_field_value(field, values)}{marker}")
    lines.append("")
    lines.append("点击字段直接修改，开关会直接切换。")
    return truncate("\n".join(lines))


def setting_domain_keyboard(
    domain_key: str,
    fields: list[dict[str, Any]],
    values: dict[str, Any],
    *,
    page: int = 1,
    total: int | None = None,
    page_size: int | None = None,
    test_notify: bool = False,
) -> dict[str, Any]:
    rows: list[list[dict[str, str]]] = []
    for field in fields:
        key = str(field.get("key") or "")
        label = str(field.get("label") or key)
        rows.append([button(f"{label}: {_editor_field_value(field, values)[:24]}", "cfg", "field", domain_key, key)])
    if test_notify:
        rows.append([button("📨 发送测试通知", "cfg", "testnotify")])
    if total is not None and page_size:
        rows.append(pagination_row(f"cfg:domain:{domain_key}", page, total, page_size))
    rows.append([button("⚙️ 返回设置菜单", "menu", "settings"), button("🏠 首页", "home")])
    return keyboard(rows)


def _editor_field_value(field: dict[str, Any], draft: dict[str, Any]) -> str:
    key = str(field.get("key") or "")
    display_key = str(field.get("display_key") or "")
    value = _nested_value(draft, display_key) if display_key else _nested_value(draft, key)
    raw_value = _nested_value(draft, key)
    field_type = str(field.get("type") or "")
    if key == "account_name":
        return str(value if value not in (None, "") else "自动")
    if key == "__share_folder__":
        return str(value if value not in (None, "") else "根目录 (/)")
    if field_type == "bool":
        return switch_text(raw_value)
    if field_type == "list":
        return ", ".join([str(x) for x in value or []]) if value else "-"
    if field_type == "action":
        return str(value if value not in (None, "") else "-")
    if isinstance(value, dict):
        return json_like(value)
    secret_markers = ("token", "api_key", "password", "secret", "cookie")
    if (key in {"config", "WEBHOOK_HEADERS", "WEBHOOK_BODY"} or any(marker in key.lower() for marker in secret_markers)) and value:
        return "***"
    return str(value if value not in (None, "") else "-")


def editor_message(title: str, draft: dict[str, Any], fields: list[dict[str, Any]], current_field: str | None = None) -> str:
    lines = [title]
    for field in fields:
        key = str(field.get("key") or "")
        label = str(field.get("label") or key)
        marker = " <- 当前" if current_field == key else ""
        lines.append(f"{label}: {_editor_field_value(field, draft)}{marker}")
    lines.append("")
    lines.append("点击字段直接修改，开关会直接切换。")
    return truncate("\n".join(lines))


def json_like(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, (dict, list)):
        return str(value)
    return str(value)


def editor_keyboard(prefix: str, target_id: int | None, fields: list[dict[str, Any]], draft: dict[str, Any]) -> dict[str, Any]:
    rows: list[list[dict[str, str]]] = []
    for field in fields:
        key = str(field.get("key") or "")
        label = str(field.get("label") or key)
        rows.append([button(f"{label}: {_editor_field_value(field, draft)[:28]}", prefix, "field", target_id if target_id is not None else "new", key)])
    rows.append([button("💾 保存", prefix, "save", target_id if target_id is not None else "new"), button("✖️ 取消", "cancel")])
    rows.append([button("🏠 首页", "home")])
    return keyboard(rows)


def search_results_message(keyword: str, payload: dict[str, Any], *, page: int, page_size: int, replace_mode: bool = False) -> str:
    items = payload.get("items") or []
    total = len(items)
    start = (page - 1) * page_size
    sliced = items[start : start + page_size]
    mode_text = "替换任务链接" if replace_mode else "创建任务"
    lines = [f"🔎 资源搜索 · 第 {page} 页", f"关键词: {keyword}", f"操作: {mode_text}"]
    selected_tmdb = payload.get("selected_tmdb") or {}
    if selected_tmdb:
        lines.append(f"🎬 TMDB: {tmdb_brief_label(selected_tmdb)}")
        if selected_tmdb.get("progress_text"):
            lines.append(f"   {selected_tmdb.get('progress_text')}")
    if payload.get("message"):
        lines.append(f"ℹ️ {payload.get('message')}")
    if not sliced:
        lines.append("")
        lines.append("暂无结果")
    for idx, item in enumerate(sliced, start=start + 1):
        tags: list[str] = []
        verify = item.get("verify")
        if verify is True:
            tags.append("可用")
        elif verify is False:
            tags.append("不可用")
        if item.get("max_video"):
            tags.append("文件最大")
        if item.get("source"):
            tags.append(str(item.get("source")))
        if item.get("channel"):
            tags.append(str(item.get("channel")))
        latest_video = item.get("latest_video") or {}
        latest_name = str(latest_video.get("name") or "").strip()
        latest_size = file_size_text(latest_video.get("size"))
        lines.append("")
        lines.append(f"{_emoji_verify(verify)} #{idx} {_short_text(item.get('taskname') or '-', 54)}")
        if tags:
            lines.append(f"🏷️ {' · '.join(tags)}")
        if latest_name:
            lines.append(f"📄 {_short_text(latest_name, 68)}")
        if latest_size != "-":
            lines.append(f"📦 {latest_size}")
        if item.get("datetime"):
            lines.append(f"🕒 {item.get('datetime')}")
        lines.append(f"🔗 {_short_text(item.get('shareurl'), 88)}")
    lines.append("")
    lines.append(f"共 {total} 条")
    return truncate("\n".join(lines))


def search_loading_message(keyword: str, *, replace_mode: bool = False) -> str:
    mode_text = "替换任务链接" if replace_mode else "创建任务"
    return truncate(
        "\n".join(
            [
                "⏳ 正在搜索资源",
                f"关键词: {keyword}",
                f"操作: {mode_text}",
                "",
                "正在搜索资源并校验链接可用性。",
                "结果较多时可能需要一些时间，请稍候…",
            ]
        )
    )


def tmdb_loading_message(keyword: str, *, replace_mode: bool = False) -> str:
    mode_text = "替换任务链接" if replace_mode else "创建任务"
    return truncate(
        "\n".join(
            [
                "🎬 正在检索 TMDB",
                f"关键词: {keyword}",
                f"操作: {mode_text}",
                "",
                "正在搜索 TMDB 并整理影视信息。",
                "选中条目后可按标准标题继续搜索资源。",
            ]
        )
    )


def tmdb_results_message(keyword: str, payload: dict[str, Any], *, page: int, page_size: int, replace_mode: bool = False, bind_mode: bool = False) -> str:
    items = payload.get("items") or []
    total = len(items)
    start = (page - 1) * page_size
    sliced = items[start : start + page_size]
    mode_text = "绑定 TMDB" if bind_mode else ("替换任务链接" if replace_mode else "创建任务")
    lines = [f"🎬 TMDB 搜索 · 第 {page} 页", f"关键词: {keyword}", f"操作: {mode_text}"]
    if payload.get("message"):
        lines.append(f"ℹ️ {payload.get('message')}")
    if not sliced:
        lines.append("暂无 TMDB 结果")
    for idx, item in enumerate(sliced, start=start + 1):
        title = str(item.get("display_title") or item.get("title") or item.get("name") or "-")
        media_type = str(item.get("media_type") or "-")
        date_text = str(item.get("display_date") or "").strip()
        vote = item.get("vote_average")
        overview = str(item.get("overview") or "").strip()
        progress = str(item.get("progress_text") or "").strip()
        lines.append("")
        line = f"#{idx} {_short_text(title, 52)}"
        if date_text:
            line += f" · {date_text}"
        if vote not in (None, ""):
            line += f" · ⭐ {vote}"
        lines.append(line)
        lines.append(f"🏷️ {media_type}")
        if progress:
            lines.append(f"📺 {progress}")
        if overview:
            lines.append(f"📝 {_short_text(overview, 88)}")
    lines.append("")
    lines.append(f"共 {total} 条")
    if bind_mode:
        lines.append("👇 选择条目后会自动回填到任务草稿")
    else:
        lines.append("👇 可先选择 TMDB 自动继续搜资源，也可跳过直接按原关键词搜索")
    return truncate("\n".join(lines))


def search_results_keyboard(total: int, *, page: int, page_size: int, replace_mode: bool) -> dict[str, Any]:
    rows: list[list[dict[str, str]]] = []
    start = (page - 1) * page_size
    end = min(total, start + page_size)
    for idx in range(start, end):
        if replace_mode:
            rows.append([button(f"🔁 选第 {idx + 1} 条", "sea", "replace", idx)])
        else:
            rows.append([button(f"➕ 选第 {idx + 1} 条", "sea", "create", idx)])
    rows.append(pagination_row("sea:list", page, total, page_size))
    rows.append([button("🔍 重新搜索", "menu", "search"), button("🏠 首页", "home")])
    return keyboard(rows)


def tmdb_results_keyboard(total: int, *, page: int, page_size: int, bind_mode: bool = False, has_binding: bool = False) -> dict[str, Any]:
    rows: list[list[dict[str, str]]] = []
    start = (page - 1) * page_size
    end = min(total, start + page_size)
    for idx in range(start, end):
        rows.append([button(f"🎬 选第 {idx + 1} 条", "tm", "pick", idx)])
    rows.append(pagination_row("tm:list", page, total, page_size))
    if bind_mode:
        rows.append([button("🔍 重新输入", "tm", "input"), button("✏️ 返回编辑器", "tm", "back")])
        if has_binding:
            rows.append([button("🧹 清空绑定", "tm", "clear"), button("🏠 首页", "home")])
        else:
            rows.append([button("🏠 首页", "home")])
    else:
        rows.append([button("⏭️ 跳过 TMDB", "tm", "skip"), button("🔍 重新输入", "menu", "search")])
        rows.append([button("🏠 首页", "home")])
    return keyboard(rows)

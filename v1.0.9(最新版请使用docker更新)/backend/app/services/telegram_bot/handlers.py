from __future__ import annotations

import base64
import logging
import os
import re
import threading
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.services.telegram_bot.actions import TelegramBotActions
from app.services.telegram_bot.callbacks import parse_callback
from app.services.telegram_bot.client import TelegramBotClient
from app.services.telegram_bot.config import TelegramBotConfig
from app.services.telegram_bot.formatters import (
    account_detail_keyboard,
    account_detail_message,
    accounts_message,
    button,
    editor_keyboard,
    editor_message,
    file_size_text,
    home_keyboard,
    home_message,
    keyboard,
    pagination_row,
    search_loading_message,
    search_results_keyboard,
    search_results_message,
    setting_domain_keyboard,
    setting_domain_message,
    settings_domains_keyboard,
    settings_domains_message,
    status_message,
    sync_detail_keyboard,
    sync_detail_message,
    sync_tasks_message,
    task_detail_keyboard,
    task_detail_message,
    tasks_message,
    tmdb_loading_message,
    tmdb_results_keyboard,
    tmdb_results_message,
)
from app.services.telegram_bot.session_store import (
    load_session_data,
    reset_session,
    save_session_data,
)


logger = logging.getLogger(__name__)


TASK_FIELDS: list[dict[str, Any]] = [
    {"key": "task_type", "label": "任务类型", "type": "enum", "options": ["drama"], "default": "drama", "editor": False},
    {"key": "taskname", "label": "任务名称", "type": "str", "default": ""},
    {"key": "shareurl", "label": "分享链接", "type": "str", "default": ""},
    {"key": "__share_folder__", "label": "分享目录", "type": "action", "default": "", "display_key": "__share_folder_label__", "transient": True},
    {"key": "savepath", "label": "保存路径", "type": "str", "default": ""},
    {"key": "account_name", "label": "执行账号", "type": "str", "default": ""},
    {"key": "__magic_rule__", "label": "内置规则", "type": "action", "default": "", "display_key": "__magic_rule_label__", "transient": True},
    {"key": "pattern", "label": "匹配规则", "type": "str", "default": ""},
    {"key": "replace", "label": "替换规则", "type": "str", "default": ""},
    {"key": "update_subdir", "label": "子目录模板", "type": "str", "default": ""},
    {"key": "__tmdb_bind__", "label": "TMDB 关联", "type": "action", "default": "", "display_key": "__tmdb_label__", "transient": True},
    {"key": "tmdb_id", "label": "TMDB ID", "type": "int", "default": None, "editor": False},
    {"key": "tmdb_media_type", "label": "TMDB 类型", "type": "enum", "options": ["", "tv", "movie"], "default": "", "editor": False},
    {"key": "sync_task_uids", "label": "关联同步任务", "type": "list", "default": [], "display_key": "sync_task_names"},
    {"key": "enabled", "label": "启用任务", "type": "bool", "default": True, "editor": False},
    {"key": "ignore_extension", "label": "忽略扩展名", "type": "bool", "default": False},
    {"key": "startfid", "label": "起始文件", "type": "str", "default": "", "display_key": "__startfid_label__"},
]

SYNC_FIELDS: list[dict[str, Any]] = [
    {"key": "name", "label": "同步名称", "type": "str", "default": ""},
    {"key": "enabled", "label": "启用同步", "type": "bool", "default": True, "editor": False},
    {"key": "source.type", "label": "源类型", "type": "enum", "options": ["local", "openlist"], "default": "local"},
    {"key": "source.path", "label": "源路径", "type": "str", "default": ""},
    {"key": "target.type", "label": "目标类型", "type": "enum", "options": ["local", "openlist"], "default": "openlist"},
    {"key": "target.path", "label": "目标路径", "type": "str", "default": ""},
    {"key": "mode", "label": "同步模式", "type": "enum", "options": ["one_way", "two_way"], "default": "one_way"},
    {"key": "strategy.overwrite", "label": "允许覆盖", "type": "bool", "default": False},
    {"key": "strategy.one_way_delete_extras", "label": "单向删除多余文件", "type": "bool", "default": False},
    {"key": "strategy.force_refresh", "label": "强制刷新目录", "type": "bool", "default": False},
    {"key": "strategy.concurrency", "label": "并发数", "type": "int", "default": 4},
    {"key": "strategy.request_interval_seconds", "label": "请求间隔秒数", "type": "float", "default": 0.0},
    {"key": "strategy.openlist_copy_batch_size", "label": "OpenList 批量拷贝数", "type": "int", "default": 200},
    {"key": "drama_task_uids", "label": "关联追剧任务", "type": "list", "default": [], "display_key": "drama_task_names"},
]

ACCOUNT_FIELDS: list[dict[str, Any]] = [
    {"key": "name", "label": "账号名称", "type": "str", "default": ""},
    {"key": "drive_type", "label": "网盘类型", "type": "enum_dynamic", "options_key": "drive_types", "default": ""},
    {"key": "cookie", "label": "Cookie", "type": "str", "default": ""},
    {"key": "config", "label": "配置 JSON", "type": "json", "default": {}},
    {"key": "enabled", "label": "启用账号", "type": "bool", "default": True, "editor": False},
    {"key": "is_default", "label": "默认账号", "type": "bool", "default": False, "editor": False},
    {"key": "capacity_warning_threshold", "label": "容量告警阈值", "type": "int", "default": 85},
]

SETTING_FIELD_MAP: dict[str, dict[str, dict[str, Any]]] = {
    "task_scheduler": {
        "enabled": {"label": "启用任务调度", "type": "bool"},
        "crontab": {"label": "Cron 表达式", "type": "str"},
        "timezone": {"label": "时区", "type": "str"},
    },
    "probe_scheduler": {
        "enabled": {"label": "启用账号探测", "type": "bool"},
        "crontab": {"label": "Cron 表达式", "type": "str"},
        "timezone": {"label": "时区", "type": "str"},
        "enabled_only": {"label": "仅探测启用账号", "type": "bool"},
    },
    "tmdb": {
        "api_key": {"label": "TMDB API Key", "type": "str"},
        "has_api_key": {"label": "已配置 API Key", "type": "bool", "editor": False},
        "language": {"label": "元数据语言", "type": "str"},
        "poster_language": {"label": "海报语言", "type": "str"},
        "disable_guessit_tmdb_fallback_rename": {"label": "关闭 Guessit 回退重命名", "type": "bool"},
        "guessit_tmdb_tv_rename_template": {"label": "剧集重命名模板", "type": "str"},
        "guessit_tmdb_movie_rename_template": {"label": "电影重命名模板", "type": "str"},
    },
    "openlist": {
        "url": {"label": "OpenList 地址", "type": "str"},
        "token": {"label": "访问令牌", "type": "str"},
        "has_token": {"label": "已配置访问令牌", "type": "bool", "editor": False},
    },
}

RESOURCE_SOURCE_FIELD_MAP: dict[str, dict[str, dict[str, Any]]] = {
    "enabled": {"label": "启用", "type": "bool"},
    "server": {"label": "服务地址", "type": "str"},
    "username": {"label": "用户名", "type": "str"},
    "password": {"label": "密码", "type": "str"},
    "token": {"label": "访问令牌", "type": "str"},
}

NOTIFICATION_FIELD_MAP: dict[str, dict[str, Any]] = {
    "HITOKOTO": {"label": "一言文案", "type": "bool"},
    "TG_BOT_TOKEN": {"label": "Telegram Bot Token", "type": "str"},
    "TG_USER_ID": {"label": "Telegram 用户 ID", "type": "str"},
    "TG_API_HOST": {"label": "Telegram API 地址", "type": "str"},
    "TG_PROXY_AUTH": {"label": "Telegram 代理认证", "type": "str"},
    "TG_PROXY_HOST": {"label": "Telegram 代理地址", "type": "str"},
    "TG_PROXY_PORT": {"label": "Telegram 代理端口", "type": "str"},
    "SMTP_SERVER": {"label": "SMTP 服务器", "type": "str"},
    "SMTP_SSL": {"label": "SMTP SSL", "type": "bool"},
    "SMTP_EMAIL": {"label": "SMTP 发件邮箱", "type": "str"},
    "SMTP_PASSWORD": {"label": "SMTP 密码", "type": "str"},
    "SMTP_NAME": {"label": "SMTP 发件名称", "type": "str"},
    "SMTP_EMAIL_TO": {"label": "SMTP 收件邮箱", "type": "str"},
    "SMTP_NAME_TO": {"label": "SMTP 收件名称", "type": "str"},
    "WEBHOOK_URL": {"label": "Webhook 地址", "type": "str"},
    "WEBHOOK_METHOD": {"label": "Webhook 方法", "type": "str"},
    "WEBHOOK_HEADERS": {"label": "Webhook 请求头", "type": "str"},
    "WEBHOOK_BODY": {"label": "Webhook 请求体", "type": "str"},
    "WEBHOOK_CONTENT_TYPE": {"label": "Webhook Content-Type", "type": "str"},
}


def _field_meta(fields: list[dict[str, Any]], key: str) -> dict[str, Any]:
    for item in fields:
        if item["key"] == key:
            return item
    raise KeyError(key)


def _editor_fields(fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [x for x in fields if x.get("editor", True) is not False]


def _pretty_setting_key(key: str) -> str:
    parts = [part for part in str(key).replace(".", " ").split() if part]
    tokens: list[str] = []
    preserve = {"tg", "tmdb", "smtp", "url", "api", "id", "qq"}
    for part in parts:
        for token in str(part).split("_"):
            raw = token.strip()
            if not raw:
                continue
            if raw.lower() in preserve:
                tokens.append(raw.upper())
            elif raw.isupper():
                tokens.append(raw)
            else:
                tokens.append(raw.replace("-", " ").title())
    return " ".join(tokens) or key


def _infer_setting_type(current: Any, field: str) -> str:
    if isinstance(current, bool):
        return "bool"
    if isinstance(current, int) and not isinstance(current, bool):
        return "int"
    if isinstance(current, float):
        return "float"
    lowered = str(field or "").lower()
    if lowered.startswith("has_") or lowered.endswith("_enabled") or lowered == "enabled":
        return "bool"
    return "str"


def _setting_field_meta(domain: str, field: str, current: Any) -> dict[str, Any]:
    if domain == "notifications":
        meta = dict(NOTIFICATION_FIELD_MAP.get(field, {}))
    else:
        meta = dict(SETTING_FIELD_MAP.get(domain, {}).get(field, {}))
    meta.setdefault("key", field)
    meta.setdefault("label", _pretty_setting_key(field))
    meta.setdefault("type", _infer_setting_type(current, field))
    return meta


def _resource_source_fields(values: dict[str, Any]) -> list[dict[str, Any]]:
    fields: list[dict[str, Any]] = []
    for item in values.get("sources") or []:
        source_key = str(item.get("key") or "").strip()
        if not source_key:
            continue
        source_name = source_key.upper() if source_key.islower() else source_key
        for inner_key, meta in RESOURCE_SOURCE_FIELD_MAP.items():
            if inner_key not in item:
                continue
            fields.append(
                {
                    "key": f"{source_key}.{inner_key}",
                    "label": f"{source_name} · {meta.get('label')}",
                    "type": meta.get("type") or _infer_setting_type(item.get(inner_key), inner_key),
                }
            )
    return fields


def _setting_fields(actions: TelegramBotActions, domain: str, values: dict[str, Any], *, page: int = 1) -> tuple[list[dict[str, Any]], int | None, int | None]:
    if domain == "resource_sources":
        return _resource_source_fields(values), None, None
    if domain == "notifications":
        keys = actions.raw_notification_keys()
        page_size = 12
        start = max(0, (page - 1) * page_size)
        fields = [_setting_field_meta(domain, key, values.get(key)) for key in keys[start : start + page_size]]
        return _editor_fields(fields), len(keys), page_size
    fields: list[dict[str, Any]] = []
    for key, value in values.items():
        fields.append(_setting_field_meta(domain, str(key), value))
    return _editor_fields(fields), None, None


def _setting_display_values(domain: str, values: dict[str, Any]) -> dict[str, Any]:
    if domain != "resource_sources":
        return dict(values or {})
    display: dict[str, Any] = {}
    for item in values.get("sources") or []:
        source_key = str(item.get("key") or "").strip()
        if not source_key:
            continue
        display[source_key] = {}
        for inner_key, inner_value in item.items():
            if inner_key == "key":
                continue
            display[source_key][str(inner_key)] = inner_value
    return display


def _set_nested(target: dict[str, Any], path: str, value: Any) -> None:
    parts = [p for p in str(path).split(".") if p]
    node = target
    for part in parts[:-1]:
        child = node.get(part)
        if not isinstance(child, dict):
            child = {}
            node[part] = child
        node = child
    node[parts[-1]] = value


def _get_nested(target: dict[str, Any], path: str) -> Any:
    node: Any = target
    for part in [p for p in str(path).split(".") if p]:
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    return node


def _flatten_seed(fields: list[dict[str, Any]], source: dict[str, Any] | None = None) -> dict[str, Any]:
    draft: dict[str, Any] = {}
    source = source or {}
    for item in fields:
        value = _get_nested(source, item["key"])
        if value is None:
            value = item.get("default")
        _set_nested(draft, item["key"], value)
        display_key = str(item.get("display_key") or "")
        if display_key:
            display_value = _get_nested(source, display_key)
            if display_value is None:
                display_value = []
            _set_nested(draft, display_key, display_value)
    return draft


def _collapse_payload(fields: list[dict[str, Any]], draft: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for item in fields:
        if item.get("transient"):
            continue
        key = item["key"]
        value = _get_nested(draft, key)
        if item["type"] == "str" and value == "":
            value = None
        if item["type"] == "enum" and value == "":
            value = None
        _set_nested(payload, key, value)
    return payload


def _parse_scalar(text: str, field_type: str) -> Any:
    raw = str(text or "").strip()
    if field_type == "str":
        return raw
    if field_type == "int":
        if not raw:
            return None
        return int(raw)
    if field_type == "float":
        if not raw:
            return None
        return float(raw)
    if field_type == "bool":
        return raw.lower() in {"1", "true", "yes", "y", "on", "是", "启用"}
    if field_type == "list":
        if not raw:
            return []
        return [x for x in [i.strip() for i in raw.replace("\n", ",").split(",")] if x]
    if field_type == "json":
        if not raw:
            return {}
        import json

        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError("JSON 必须是对象")
        return value
    return raw


def _field_prompt(meta: dict[str, Any]) -> str:
    label = str(meta.get("label") or meta.get("key") or "字段")
    field_type = str(meta.get("type") or "str")
    if field_type == "list":
        return f"请输入 {label}，多个值用逗号或换行分隔。留空可清空。"
    if field_type == "json":
        return f"请输入 {label}，内容必须是 JSON 对象。留空可清空。"
    if field_type == "int":
        return f"请输入 {label}，需要是整数。留空可清空。"
    if field_type == "float":
        return f"请输入 {label}，需要是数字。留空可清空。"
    return f"请输入 {label}。留空可清空。"


def _editor_title(kind: str, target_id: int | None = None) -> str:
    if kind == "task":
        return f"编辑任务 #{target_id}" if target_id else "新建任务"
    if kind == "sync":
        return f"编辑同步 #{target_id}" if target_id else "新建同步任务"
    return f"编辑账号 #{target_id}" if target_id else "新建账号"


def _sync_task_name_list(options: list[dict[str, Any]], uids: list[str]) -> list[str]:
    name_map = {str(item.get("uid") or ""): str(item.get("name") or item.get("uid") or "") for item in options}
    return [name_map.get(str(uid), str(uid)) for uid in uids if str(uid).strip()]


def _drama_task_name_list(options: list[dict[str, Any]], uids: list[str]) -> list[str]:
    name_map = {str(item.get("task_uid") or ""): str(item.get("taskname") or item.get("task_uid") or "") for item in options}
    return [name_map.get(str(uid), str(uid)) for uid in uids if str(uid).strip()]


def _local_parent_path(path: str) -> str:
    normalized = str(path or "").strip().replace("\\", "/").strip("/")
    if not normalized:
        return ""
    if "/" not in normalized:
        return ""
    return normalized.rsplit("/", 1)[0]


def _remote_parent_path(path: str) -> str:
    normalized = str(path or "").strip() or "/"
    normalized = "/" + "/".join([p for p in normalized.split("/") if p])
    if normalized == "/":
        return "/"
    parts = [p for p in normalized.split("/") if p]
    if len(parts) <= 1:
        return "/"
    return "/" + "/".join(parts[:-1])


def _suggest_taskname_from_share_text(text: str, shareurl: str, latest_video_name: str | None = None) -> str:
    candidate = str(text or "").strip()
    if shareurl:
        candidate = candidate.replace(str(shareurl).strip(), " ")
    candidate = re.sub(r"https?://[^\s]+", " ", candidate)
    candidate = re.sub(r"(提取码|访问码|密码|pwd|password)[：:\s#-]*[A-Za-z0-9]{4,8}", " ", candidate, flags=re.IGNORECASE)
    candidate = re.sub(r"[（(][A-Za-z0-9]{4}[)）]", " ", candidate)
    candidate = re.sub(r"\s+", " ", candidate).strip(" -_|,，:：")
    if len(candidate) >= 2:
        return candidate[:120]
    latest_name = str(latest_video_name or "").strip()
    if latest_name:
        fallback, _ext = os.path.splitext(latest_name)
        return (fallback or latest_name)[:120]
    return ""


def _preferred_task_id_from_session(scene: str, context: dict[str, Any]) -> int | None:
    if scene in {"task_detail", "task_editor"}:
        return int(context.get("task_id") or context.get("target_id") or 0) or None
    if scene in {"search", "search_results", "tmdb_results"}:
        return int(context.get("replace_task_id") or 0) or None
    return None


def _short_link_text(value: str, limit: int = 56) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _task_shareurl(shareurl: str, fid: str | None = None) -> str:
    raw = str(shareurl or "").strip()
    target_fid = str(fid or "").strip()
    if not raw:
        return raw
    if "yun.139.com" in raw or "caiyun.139.com" in raw:
        head, sep, frag = raw.partition("#")
        if sep:
            frag_path, frag_query = (frag.split("?", 1) + [""])[:2]
            pairs = [p for p in frag_query.split("&") if p and not p.startswith("fid=")]
            if target_fid and target_fid not in ("0", "root"):
                pairs.append(f"fid={target_fid}")
            next_frag = frag_path if not pairs else f"{frag_path}?{'&'.join(pairs)}"
            return f"{head}#{next_frag}".strip()
        head = re.sub(r"([?&])fid=[^&#]*", r"\1", head)
        head = re.sub(r"[?&]+$", "", head)
        head = re.sub(r"\?&", "?", head)
        if target_fid and target_fid not in ("0", "root"):
            head = f"{head}{'&' if '?' in head else '?'}fid={target_fid}"
        return head.strip()
    if not target_fid or target_fid == "0":
        match = re.search(r".*s/[a-zA-Z0-9\-_]+(\?[^#]*)?", raw)
        return str(match.group(0) if match else raw.split("#")[0]).strip()
    if target_fid in raw:
        match = re.search(rf".*/{re.escape(target_fid)}[^/]*", raw)
        if match:
            return str(match.group(0) or "").strip() or raw
    return f"{raw.split('#')[0]}#/list/share/{target_fid}"


def _extract_task_share_fid(shareurl: str) -> str | None:
    raw = str(shareurl or "").strip()
    if not raw:
        return None
    match_query = re.search(r"(?:\?|&)fid=([^&#]+)", raw)
    if match_query:
        fid = str(match_query.group(1) or "").strip()
        if fid and fid not in ("0", "root"):
            return fid
    match_hash = re.search(r"#/list/share/([a-zA-Z0-9]{6,64})", raw)
    if match_hash:
        return str(match_hash.group(1) or "").strip() or None
    match_tail = re.search(r"/([a-fA-F0-9]{32})-?[^/]*$", raw)
    if match_tail:
        return str(match_tail.group(1) or "").strip() or None
    return None


def _share_folder_label(shareurl: str, stack: list[dict[str, Any]] | None = None) -> str:
    parts = [str((item or {}).get("name") or "").strip() for item in (stack or []) if str((item or {}).get("name") or "").strip()]
    path = "/" + "/".join(parts) if parts else "/"
    fid = str(((stack or [])[-1] or {}).get("pdir_fid") or "").strip() if stack else str(_extract_task_share_fid(shareurl) or "").strip()
    return f"{path} · {fid}" if fid else f"根目录 ({path})"


def _startfid_label_from_item(item: dict[str, Any] | None) -> str:
    payload = dict(item or {})
    name = str(payload.get("file_name") or payload.get("name") or "").strip()
    fid = str(payload.get("fid") or "").strip()
    if name and fid:
        return f"{name} · {fid}"
    if name:
        return name
    return fid or "-"


def _tmdb_binding_label(draft: dict[str, Any]) -> str:
    tmdb_id_raw = _get_nested(draft, "tmdb_id")
    media_type = str(_get_nested(draft, "tmdb_media_type") or "").strip()
    try:
        tmdb_id = int(tmdb_id_raw or 0)
    except Exception:
        tmdb_id = 0
    if tmdb_id <= 0 or not media_type:
        return "未绑定"
    title = str(_get_nested(draft, "__tmdb_title__") or "").strip()
    if title:
        return f"{title} [{media_type} #{tmdb_id}]"
    return f"{media_type} #{tmdb_id}"


def _magic_rule_brief(item: dict[str, Any]) -> str:
    key = str(item.get("key") or "").strip()
    label = str(item.get("label") or "").strip()
    return f"{label}（{key}）" if label else key


def _magic_rule_binding_label(draft: dict[str, Any]) -> str:
    current = str(_get_nested(draft, "__magic_rule_label__") or "").strip()
    if current:
        return current
    pattern = str(_get_nested(draft, "pattern") or "").strip()
    replace = str(_get_nested(draft, "replace") or "").strip()
    if not pattern and not replace:
        return "未选择"
    if pattern.startswith("$"):
        return pattern
    return "手动填写"


def _display_datetime(value: Any) -> str:
    if value in (None, ""):
        return "-"
    raw = str(value).strip()
    if not raw:
        return "-"
    try:
        number = float(raw)
        if number > 0:
            if number > 1e12:
                number /= 1000.0
            dt = datetime.fromtimestamp(number)
            return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        pass
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return raw


def _is_video_preview_item(item: dict[str, Any]) -> bool:
    name = str(item.get("file_name") or item.get("name") or "").strip().lower()
    return bool(re.search(r"\.(mp4|mkv|mov|m4v|avi|mpeg|ts|flv|wmv|webm|cas)$", name))


@dataclass
class TelegramBotHandler:
    client: TelegramBotClient
    config: TelegramBotConfig

    def handle_update(self, update: dict[str, Any]) -> None:
        if isinstance(update.get("message"), dict):
            self._handle_message(update["message"])
            return
        if isinstance(update.get("callback_query"), dict):
            self._handle_callback(update["callback_query"])

    def _actions(self, db: Session) -> TelegramBotActions:
        return TelegramBotActions(db=db)

    def _allowed(self, chat_id: int, user_id: int) -> bool:
        return int(chat_id) == int(self.config.user_id) and int(user_id) == int(self.config.user_id)

    def _send(self, chat_id: int, text: str, *, reply_markup: dict[str, Any] | None = None) -> int | None:
        result = self.client.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)
        message_id = result.get("message_id")
        return int(message_id) if isinstance(message_id, int) else None

    def _send_photo(self, chat_id: int, photo_bytes: bytes, *, caption: str | None = None) -> int | None:
        result = self.client.send_photo(chat_id=chat_id, photo_bytes=photo_bytes, caption=caption)
        message_id = result.get("message_id")
        return int(message_id) if isinstance(message_id, int) else None

    def _edit_or_send(self, chat_id: int, text: str, *, message_id: int | None = None, reply_markup: dict[str, Any] | None = None) -> int | None:
        if message_id:
            try:
                result = self.client.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, reply_markup=reply_markup)
                message_id = result.get("message_id", message_id)
                return int(message_id) if isinstance(message_id, int) else message_id
            except Exception as exc:
                if "message is not modified" in str(exc).lower():
                    return message_id
        return self._send(chat_id, text, reply_markup=reply_markup)

    def _answer_callback(self, callback_query_id: str, text: str | None = None) -> None:
        try:
            self.client.answer_callback_query(callback_query_id=callback_query_id, text=text)
        except Exception:
            pass

    def _show_home(self, db: Session, chat_id: int, *, message_id: int | None = None) -> None:
        mid = self._edit_or_send(chat_id, home_message(), message_id=message_id, reply_markup=home_keyboard())
        save_session_data(db, chat_id=chat_id, user_id=self.config.user_id, scene="home", step="idle", context={}, last_message_id=mid)
        db.commit()

    def _show_tasks(self, db: Session, chat_id: int, *, page: int = 1, _task_type: str | None = None, message_id: int | None = None) -> None:
        effective_task_type = "drama"
        payload = self._actions(db).list_tasks(page=page, task_type=effective_task_type)
        rows = [[button(f"#{item['id']} {item['taskname'][:20]}", "tsk", "detail", item["id"])] for item in payload["items"]]
        rows.append([button("➕ 新建任务", "tsk", "new"), button("🏠 首页", "home")])
        rows.append(pagination_row("tsk:list", payload["page"], payload["total"], payload["page_size"], effective_task_type))
        mid = self._edit_or_send(chat_id, tasks_message(payload, title="追剧任务"), message_id=message_id, reply_markup=keyboard(rows))
        save_session_data(
            db,
            chat_id=chat_id,
            user_id=self.config.user_id,
            scene="tasks",
            step="idle",
            context={"page": page, "task_type": effective_task_type},
            last_message_id=mid,
        )
        db.commit()

    def _show_task_detail(
        self,
        db: Session,
        chat_id: int,
        task_id: int,
        *,
        message_id: int | None = None,
        back_page: int = 1,
        task_type: str | None = None,
    ) -> None:
        item = self._actions(db).get_task_detail(task_id)
        mid = self._edit_or_send(
            chat_id,
            task_detail_message(item),
            message_id=message_id,
            reply_markup=task_detail_keyboard(task_id, bool(item.get("enabled")), back_page=back_page, task_type=task_type),
        )
        save_session_data(
            db,
            chat_id=chat_id,
            user_id=self.config.user_id,
            scene="task_detail",
            step="idle",
            context={"task_id": task_id, "page": back_page, "task_type": task_type or ""},
            last_message_id=mid,
        )
        db.commit()

    def _show_sync_tasks(self, db: Session, chat_id: int, *, page: int = 1, message_id: int | None = None) -> None:
        payload = self._actions(db).list_sync_tasks(page=page)
        rows = [[button(f"#{item['id']} {item['name'][:20]}", "syn", "detail", item["id"])] for item in payload["items"]]
        rows.append([button("➕ 新建同步", "syn", "new")])
        rows.append(pagination_row("syn:list", payload["page"], payload["total"], payload["page_size"]))
        mid = self._edit_or_send(chat_id, sync_tasks_message(payload), message_id=message_id, reply_markup=keyboard(rows))
        save_session_data(db, chat_id=chat_id, user_id=self.config.user_id, scene="sync", step="idle", context={"page": page}, last_message_id=mid)
        db.commit()

    def _show_sync_detail(self, db: Session, chat_id: int, sync_task_id: int, *, message_id: int | None = None, back_page: int = 1) -> None:
        item = self._actions(db).get_sync_task_detail(sync_task_id)
        mid = self._edit_or_send(
            chat_id,
            sync_detail_message(item),
            message_id=message_id,
            reply_markup=sync_detail_keyboard(sync_task_id, bool(item.get("enabled")), back_page=back_page),
        )
        save_session_data(
            db,
            chat_id=chat_id,
            user_id=self.config.user_id,
            scene="sync_detail",
            step="idle",
            context={"sync_task_id": sync_task_id, "page": back_page},
            last_message_id=mid,
        )
        db.commit()

    def _show_accounts(self, db: Session, chat_id: int, *, page: int = 1, message_id: int | None = None) -> None:
        payload = self._actions(db).list_accounts(page=page)
        rows = [[button(f"#{item['id']} {item['name'][:20]}", "acc", "detail", item["id"])] for item in payload["items"]]
        rows.append([button("➕ 新建账号", "acc", "new"), button("🔄 刷新资料", "acc", "refresh")])
        rows.append(pagination_row("acc:list", payload["page"], payload["total"], payload["page_size"]))
        mid = self._edit_or_send(chat_id, accounts_message(payload), message_id=message_id, reply_markup=keyboard(rows))
        save_session_data(db, chat_id=chat_id, user_id=self.config.user_id, scene="accounts", step="idle", context={"page": page}, last_message_id=mid)
        db.commit()

    def _show_account_detail(self, db: Session, chat_id: int, account_id: int, *, message_id: int | None = None, back_page: int = 1) -> None:
        item = self._actions(db).get_account_detail(account_id)
        mid = self._edit_or_send(
            chat_id,
            account_detail_message(item),
            message_id=message_id,
            reply_markup=account_detail_keyboard(account_id, bool(item.get("enabled")), bool(item.get("is_default")), back_page=back_page),
        )
        save_session_data(
            db,
            chat_id=chat_id,
            user_id=self.config.user_id,
            scene="account_detail",
            step="idle",
            context={"account_id": account_id, "page": back_page},
            last_message_id=mid,
        )
        db.commit()

    def _show_status(self, db: Session, chat_id: int, *, message_id: int | None = None) -> None:
        summary = self._actions(db).build_status_summary()
        mid = self._edit_or_send(chat_id, status_message(summary), message_id=message_id, reply_markup=keyboard([[button("🏠 首页", "home")]]))
        save_session_data(db, chat_id=chat_id, user_id=self.config.user_id, scene="status", step="idle", context={}, last_message_id=mid)
        db.commit()

    def _show_settings_menu(self, db: Session, chat_id: int, *, message_id: int | None = None) -> None:
        domains = self._actions(db).list_setting_domains()
        mid = self._edit_or_send(chat_id, settings_domains_message(domains), message_id=message_id, reply_markup=settings_domains_keyboard(domains))
        save_session_data(db, chat_id=chat_id, user_id=self.config.user_id, scene="settings", step="idle", context={}, last_message_id=mid)
        db.commit()

    def _show_setting_domain(self, db: Session, chat_id: int, domain_key: str, *, page: int = 1, message_id: int | None = None) -> None:
        domain = self._actions(db).get_setting_domain(domain_key)
        values = domain.get("values") or {}
        display_values = _setting_display_values(domain_key, values)
        fields, total, page_size = _setting_fields(self._actions(db), domain_key, values, page=page)
        mid = self._edit_or_send(
            chat_id,
            setting_domain_message(domain, fields, values=display_values),
            message_id=message_id,
            reply_markup=setting_domain_keyboard(
                domain_key,
                fields,
                display_values,
                page=page,
                total=total,
                page_size=page_size,
                test_notify=(domain_key == "notifications"),
            ),
        )
        save_session_data(db, chat_id=chat_id, user_id=self.config.user_id, scene="settings_domain", step="idle", context={"domain": domain_key, "page": page}, last_message_id=mid)
        db.commit()

    def _show_search_prompt(self, db: Session, chat_id: int, *, replace_task_id: int | None = None, message_id: int | None = None) -> None:
        current = load_session_data(db, chat_id=chat_id, user_id=self.config.user_id)
        current_ctx = dict(current.context or {})
        text = "请输入搜索关键字。" if replace_task_id is None else f"请输入要为任务 #{replace_task_id} 搜索的新资源关键字。"
        if int(current_ctx.get("tmdb_id") or 0) > 0 and str(current_ctx.get("tmdb_media_type") or "").strip():
            text += f"\n\n当前已绑定 TMDB: {current_ctx.get('tmdb_media_type')} #{current_ctx.get('tmdb_id')}，输入后会优先按该 TMDB 标准标题搜索资源。"
        mid = self._edit_or_send(
            chat_id,
            text,
            message_id=message_id,
            reply_markup=keyboard([[button("⬅️ 返回", "back"), button("✖️ 取消", "cancel")], [button("🏠 首页", "home")]]),
        )
        save_session_data(
            db,
            chat_id=chat_id,
            user_id=self.config.user_id,
            scene="search",
            step="await_keyword",
            context={
                "replace_task_id": replace_task_id or 0,
                "page": int(current_ctx.get("page") or 1),
                "task_type": str(current_ctx.get("task_type") or ""),
                "tmdb_id": int(current_ctx.get("tmdb_id") or 0),
                "tmdb_media_type": str(current_ctx.get("tmdb_media_type") or ""),
                "tmdb_title": str(current_ctx.get("tmdb_title") or ""),
            },
            last_message_id=mid,
        )
        db.commit()

    def _show_search_results(self, db: Session, chat_id: int, *, keyword: str, results: list[dict[str, Any]], page: int = 1, replace_task_id: int | None = None, message_id: int | None = None) -> None:
        current = load_session_data(db, chat_id=chat_id, user_id=self.config.user_id)
        current_ctx = dict(current.context or {})
        selected_tmdb = dict(current_ctx.get("selected_tmdb") or {})
        payload = {"items": results, "selected_tmdb": selected_tmdb}
        mid = self._edit_or_send(
            chat_id,
            search_results_message(keyword, payload, page=page, page_size=6, replace_mode=bool(replace_task_id)),
            message_id=message_id,
            reply_markup=search_results_keyboard(len(results), page=page, page_size=6, replace_mode=bool(replace_task_id)),
        )
        save_session_data(
            db,
            chat_id=chat_id,
            user_id=self.config.user_id,
            scene="search_results",
            step="idle",
            context={
                "keyword": keyword,
                "results": results,
                "replace_task_id": replace_task_id or 0,
                "page": page,
                "selected_tmdb": selected_tmdb,
                "task_type": str(current_ctx.get("task_type") or ""),
            },
            last_message_id=mid,
        )
        db.commit()

    def _resume_task_editor(self, db: Session, chat_id: int, *, ctx: dict[str, Any], message_id: int | None = None) -> None:
        draft = dict(ctx.get("draft") or {})
        self._start_editor(
            db,
            chat_id,
            kind="task",
            title=_editor_title("task", int(ctx.get("target_id") or 0) or None),
            fields=TASK_FIELDS,
            draft=draft,
            target_id=int(ctx.get("target_id") or 0) or None,
            message_id=message_id,
            extras={k: v for k, v in ctx.items() if k != "draft"},
        )

    def _show_task_tmdb_prompt(self, db: Session, chat_id: int, *, message_id: int | None = None) -> None:
        session = load_session_data(db, chat_id=chat_id, user_id=self.config.user_id)
        ctx = dict(session.context or {})
        draft = dict(ctx.get("draft") or {})
        lines = [
            "请输入 TMDB 关键词。",
            f"当前绑定: {_tmdb_binding_label(draft)}",
            "会先搜索 TMDB，选择条目后自动回填到任务草稿。",
        ]
        rows = [[button("✏️ 返回编辑器", "tm", "back"), button("🏠 首页", "home")]]
        if int(_get_nested(draft, "tmdb_id") or 0) > 0 and str(_get_nested(draft, "tmdb_media_type") or "").strip():
            rows.insert(0, [button("🧹 清空绑定", "tm", "clear")])
        mid = self._edit_or_send(chat_id, "\n".join(lines), message_id=message_id or session.last_message_id, reply_markup=keyboard(rows))
        save_session_data(
            db,
            chat_id=chat_id,
            user_id=self.config.user_id,
            scene="task_tmdb_input",
            step="await_task_tmdb_keyword",
            context=ctx,
            last_message_id=mid,
        )
        db.commit()

    def _show_back_cancel_home(self, chat_id: int, text: str, *, message_id: int | None = None) -> None:
        self._edit_or_send(
            chat_id,
            text,
            message_id=message_id,
            reply_markup=keyboard(
                [
                    [button("⬅️ 返回", "back"), button("✖️ 取消", "cancel")],
                    [button("🏠 首页", "home")],
                ]
            ),
        )

    def _resume_editor(self, db: Session, chat_id: int, *, kind: str, ctx: dict[str, Any], message_id: int | None = None) -> None:
        draft = dict(ctx.get("draft") or {})
        fields = TASK_FIELDS if kind == "task" else SYNC_FIELDS if kind == "sync" else ACCOUNT_FIELDS
        self._start_editor(
            db,
            chat_id,
            kind=kind,
            title=_editor_title(kind, int(ctx.get("target_id") or 0) or None),
            fields=fields,
            draft=draft,
            target_id=int(ctx.get("target_id") or 0) or None,
            message_id=message_id,
            extras={k: v for k, v in ctx.items() if k != "draft"},
        )

    def _show_tmdb_results(
        self,
        db: Session,
        chat_id: int,
        *,
        keyword: str,
        items: list[dict[str, Any]],
        page: int = 1,
        replace_task_id: int | None = None,
        message_id: int | None = None,
        message: str | None = None,
        bind_mode: bool = False,
    ) -> None:
        current = load_session_data(db, chat_id=chat_id, user_id=self.config.user_id)
        current_ctx = dict(current.context or {})
        payload = {"items": items, "message": message}
        mid = self._edit_or_send(
            chat_id,
            tmdb_results_message(keyword, payload, page=page, page_size=5, replace_mode=bool(replace_task_id), bind_mode=bind_mode),
            message_id=message_id,
            reply_markup=tmdb_results_keyboard(
                len(items),
                page=page,
                page_size=5,
                bind_mode=bind_mode,
                has_binding=bool(int(current_ctx.get("tmdb_id") or 0) > 0 and str(current_ctx.get("tmdb_media_type") or "").strip()),
            ),
        )
        save_session_data(
            db,
            chat_id=chat_id,
            user_id=self.config.user_id,
            scene="tmdb_results",
            step="idle",
            context={
                **current_ctx,
                "keyword": keyword,
                "tmdb_results": items,
                "replace_task_id": replace_task_id or 0,
                "page": int(current_ctx.get("page") or 1),
                "task_type": str(current_ctx.get("task_type") or ""),
                "tmdb_bind_mode": bool(bind_mode),
            },
            last_message_id=mid,
        )
        db.commit()

    def _show_task_drive_browser(self, db: Session, chat_id: int, *, message_id: int | None = None) -> None:
        session = load_session_data(db, chat_id=chat_id, user_id=self.config.user_id)
        ctx = dict(session.context or {})
        draft = dict(ctx.get("draft") or {})
        browse_path = str(ctx.get("browse_path") or _get_nested(draft, "savepath") or "/")
        payload = self._actions(db).browse_task_drive(
            dir_path=browse_path,
            account_name=_get_nested(draft, "account_name"),
            shareurl=_get_nested(draft, "shareurl"),
            max_items=20,
        )
        rows: list[list[dict[str, str]]] = []
        if payload.get("dir_path") not in {"", "/"}:
            rows.append([button("⬆️ 上一级", "brw", "task", "up")])
        rows.append([button("✅ 选择当前目录", "brw", "task", "sel"), button("🔄 刷新", "brw", "task", "refresh")])
        for idx, item in enumerate(payload.get("items") or []):
            prefix = "[DIR] " if item.get("is_dir") else "[FILE] "
            rows.append([button(f"{prefix}{str(item.get('name') or '')[:26]}", "brw", "task", "open", idx)])
        rows.append([button("✏️ 返回编辑器", "brw", "task", "back"), button("🏠 首页", "home")])
        text_lines = [
            "选择任务保存目录",
            f"账号: {payload.get('account_name') or '-'}",
            f"路径: {payload.get('dir_path') or '/'}",
        ]
        if not payload.get("exists"):
            text_lines.append("当前路径不存在，可先返回后手动输入。")
        mid = self._edit_or_send(chat_id, "\n".join(text_lines), message_id=message_id or session.last_message_id, reply_markup=keyboard(rows))
        ctx["browse_path"] = payload.get("dir_path") or "/"
        save_session_data(db, chat_id=chat_id, user_id=self.config.user_id, scene="task_browser", step="idle", context=ctx, last_message_id=mid)
        db.commit()

    def _show_task_account_selector(self, db: Session, chat_id: int, *, message_id: int | None = None) -> None:
        session = load_session_data(db, chat_id=chat_id, user_id=self.config.user_id)
        ctx = dict(session.context or {})
        draft = dict(ctx.get("draft") or {})
        current = str(_get_nested(draft, "account_name") or "").strip()
        options = self._actions(db).list_account_names()
        rows: list[list[dict[str, str]]] = []
        auto_mark = "✓" if not current else "○"
        rows.append([button(f"{auto_mark} 自动", "asel", "pick", "auto")])
        for idx, name in enumerate(options):
            mark = "✓" if current == str(name) else "○"
            rows.append([button(f"{mark} {str(name)}", "asel", "pick", idx)])
        rows.append([button("✏️ 返回编辑器", "asel", "back"), button("🏠 首页", "home")])
        lines = [
            "选择执行账号",
            f"当前: {current or '自动'}",
            "自动模式会按分享链接类型匹配默认可用账号。",
        ]
        mid = self._edit_or_send(chat_id, "\n".join(lines), message_id=message_id or session.last_message_id, reply_markup=keyboard(rows))
        ctx["account_selector_options"] = options
        save_session_data(db, chat_id=chat_id, user_id=self.config.user_id, scene="task_account_selector", step="idle", context=ctx, last_message_id=mid)
        db.commit()

    def _show_task_magic_rule_selector(self, db: Session, chat_id: int, *, message_id: int | None = None) -> None:
        session = load_session_data(db, chat_id=chat_id, user_id=self.config.user_id)
        ctx = dict(session.context or {})
        draft = dict(ctx.get("draft") or {})
        page = max(1, int(ctx.get("magic_rule_page") or 1))
        rules = self._actions(db).list_magic_regex_rules()
        current_key = str(_get_nested(draft, "__magic_rule_key__") or "").strip()
        page_size = 8
        total = len(rules)
        max_page = max(1, (total + page_size - 1) // page_size)
        page = min(page, max_page)
        start = (page - 1) * page_size
        items = rules[start : start + page_size]
        rows: list[list[dict[str, str]]] = []
        for idx, rule in enumerate(items, start=start):
            mark = "✓" if current_key and current_key == str(rule.get("key") or "") else "○"
            rows.append([button(f"{mark} {_magic_rule_brief(rule)[:28]}", "rsel", "pick", idx)])
        rows.append([button("🧹 清空规则", "rsel", "clear"), button("✏️ 返回编辑器", "rsel", "back")])
        rows.append(pagination_row("rsel:list", page, total, page_size))
        rows.append([button("🏠 首页", "home")])
        lines = [
            "选择内置规则",
            f"当前: {_magic_rule_binding_label(draft)}",
            f"页码: {page}/{max_page}",
            "选择后会把默认 pattern / replace 自动填入，之后仍可继续手动修改。",
        ]
        mid = self._edit_or_send(chat_id, "\n".join(lines), message_id=message_id or session.last_message_id, reply_markup=keyboard(rows))
        ctx["magic_rule_options"] = rules
        ctx["magic_rule_page"] = page
        save_session_data(db, chat_id=chat_id, user_id=self.config.user_id, scene="task_magic_rule_selector", step="idle", context=ctx, last_message_id=mid)
        db.commit()

    def _task_preview_kwargs(self, draft: dict[str, Any]) -> dict[str, Any]:
        tmdb_id_raw = _get_nested(draft, "tmdb_id")
        tmdb_id = None
        if tmdb_id_raw not in (None, "", 0):
            try:
                tmdb_id = int(tmdb_id_raw)
            except Exception:
                tmdb_id = None
        return {
            "taskname": str(_get_nested(draft, "taskname") or "").strip() or None,
            "pattern": str(_get_nested(draft, "pattern") or "").strip() or None,
            "replace": str(_get_nested(draft, "replace") or "").strip() or None,
            "sort_index": int(_get_nested(draft, "sort_index") or 0) or None,
            "savepath": str(_get_nested(draft, "savepath") or "").strip() or None,
            "ignore_extension": bool(_get_nested(draft, "ignore_extension")) if _get_nested(draft, "ignore_extension") is not None else None,
            "update_subdir": str(_get_nested(draft, "update_subdir") or "").strip() or None,
            "startfid": str(_get_nested(draft, "startfid") or "").strip() or None,
            "tmdb_id": tmdb_id,
            "tmdb_media_type": str(_get_nested(draft, "tmdb_media_type") or "").strip() or None,
        }

    def _decorate_task_draft(self, draft: dict[str, Any], *, ctx: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = dict(draft or {})
        shareurl = str(_get_nested(payload, "shareurl") or "").strip()
        stack = list((ctx or {}).get("share_browse_stack") or [])
        _set_nested(payload, "__share_folder_label__", _share_folder_label(shareurl, stack))
        _set_nested(payload, "__magic_rule_label__", _magic_rule_binding_label(payload))
        _set_nested(payload, "__tmdb_label__", _tmdb_binding_label(payload))
        startfid = str(_get_nested(payload, "startfid") or "").strip()
        current_label = str(_get_nested(payload, "__startfid_label__") or "").strip()
        if startfid and not current_label:
            _set_nested(payload, "__startfid_label__", startfid)
        if not startfid:
            _set_nested(payload, "__startfid_label__", "-")
        return payload

    def _auto_resolve_task_share_folder(self, db: Session, draft: dict[str, Any]) -> str | None:
        shareurl = str(_get_nested(draft, "shareurl") or "").strip()
        if not shareurl:
            return None
        root_shareurl = _task_shareurl(shareurl, "0")
        current_shareurl = shareurl
        chosen_account = str(_get_nested(draft, "account_name") or "").strip() or None
        preview_kwargs = self._task_preview_kwargs(draft)
        last_items: list[dict[str, Any]] = []
        for _depth in range(12):
            current_fid = _extract_task_share_fid(current_shareurl)
            payload = self._actions(db).preview_task_share(
                shareurl=root_shareurl,
                account_name=chosen_account,
                pdir_fid=current_fid or None,
                max_items=50,
                **preview_kwargs,
            )
            items = list(payload.get("items") or [])
            last_items = items
            files = [x for x in items if not bool(x.get("is_dir"))]
            dirs = [x for x in items if bool(x.get("is_dir"))]
            if any(_is_video_preview_item(x) for x in files):
                return str(payload.get("resolved_shareurl") or current_shareurl).strip() or current_shareurl
            if len(dirs) == 1 and not files:
                current_shareurl = _task_shareurl(root_shareurl, str(dirs[0].get("fid") or ""))
                continue
            if len(dirs) > 1 and not files:
                picked = sorted(dirs, key=lambda x: _to_sort_ts(x.get("updated_at")), reverse=True)[0]
                current_shareurl = _task_shareurl(root_shareurl, str(picked.get("fid") or ""))
                continue
            break
        if any(_is_video_preview_item(x) for x in last_items if not bool(x.get("is_dir"))):
            return current_shareurl
        return None

    def _apply_task_share_autofill(
        self,
        db: Session,
        draft: dict[str, Any],
        *,
        raw_text: str | None = None,
        selected_shareurl: str | None = None,
    ) -> tuple[dict[str, Any], str | None]:
        shareurl = str(_get_nested(draft, "shareurl") or "").strip()
        if not shareurl:
            return draft, None
        parsed_text = str(raw_text or shareurl).strip() or shareurl
        picked_shareurl = str(selected_shareurl or shareurl).strip() or shareurl
        info = self._actions(db).inspect_share_candidate(parsed_text, picked_shareurl)
        if not info or not bool(info.get("parsed")):
            return draft, str(info.get("preview_message") or "无法解析分享链接") if info else "无法解析分享链接"
        resolved_shareurl = str(info.get("resolved_shareurl") or info.get("shareurl") or shareurl).strip() or shareurl
        suggested_account_name = str(info.get("suggested_account_name") or "").strip()
        latest_video = dict(info.get("latest_video") or {})
        suggested_taskname = _suggest_taskname_from_share_text(parsed_text, resolved_shareurl, str(latest_video.get("name") or ""))
        if suggested_account_name:
            _set_nested(draft, "account_name", suggested_account_name)
        if suggested_taskname and not str(_get_nested(draft, "taskname") or "").strip():
            _set_nested(draft, "taskname", suggested_taskname)
        _set_nested(draft, "shareurl", resolved_shareurl)
        auto_resolved_shareurl = self._auto_resolve_task_share_folder(db, draft) or resolved_shareurl
        _set_nested(draft, "shareurl", auto_resolved_shareurl)
        _set_nested(draft, "startfid", "")
        _set_nested(draft, "__startfid_label__", "-")
        _set_nested(draft, "__share_folder_label__", _share_folder_label(auto_resolved_shareurl))
        return draft, str(info.get("preview_message") or "").strip() or None

    def _show_task_share_browser(self, db: Session, chat_id: int, *, picker: str = "folder", message_id: int | None = None) -> None:
        session = load_session_data(db, chat_id=chat_id, user_id=self.config.user_id)
        ctx = dict(session.context or {})
        draft = dict(ctx.get("draft") or {})
        shareurl = str(_get_nested(draft, "shareurl") or "").strip()
        if not shareurl:
            raise ValueError("请先填写分享链接")
        root_shareurl = str(ctx.get("share_root_shareurl") or _task_shareurl(shareurl, "0")).strip() or shareurl
        stack = list(ctx.get("share_browse_stack") or [])
        current_pdir_fid = str((stack[-1] or {}).get("pdir_fid") or "").strip() if stack else str(_extract_task_share_fid(shareurl) or "").strip()
        payload = self._actions(db).preview_task_share(
            shareurl=root_shareurl,
            account_name=_get_nested(draft, "account_name"),
            pdir_fid=current_pdir_fid or None,
            max_items=500 if picker == "startfid" else 200,
            **self._task_preview_kwargs(draft),
        )
        current_shareurl = str(payload.get("resolved_shareurl") or _task_shareurl(root_shareurl, payload.get("pdir_fid"))).strip() or root_shareurl
        current_fid = str(payload.get("pdir_fid") or "").strip()
        if not stack:
            if current_fid and current_fid != "0":
                stack = [{"name": "当前目录", "pdir_fid": current_fid}]
            else:
                stack = []
        items = list(payload.get("items") or [])
        rows: list[list[dict[str, str]]] = []
        lines: list[str] = []
        current_folder_label = _share_folder_label(current_shareurl, stack)
        if picker == "folder":
            dir_items = [x for x in items if bool(x.get("is_dir"))]
            lines = [
                "选择分享目录",
                f"目录: {current_folder_label}",
                f"执行账号: {str(payload.get('suggested_account_name') or payload.get('account_name') or '自动')}",
            ]
            if stack:
                rows.append([button("⬆️ 上一级", "brw", "share", "up")])
            rows.append([button("✅ 选择当前目录", "brw", "share", "sel"), button("🔄 刷新", "brw", "share", "refresh")])
            for idx, item in enumerate(dir_items):
                rows.append([button(f"[DIR] {str(item.get('name') or '')[:26]}", "brw", "share", "open", idx)])
            preview_items = items[:12]
            if preview_items:
                lines.append("")
                lines.append("当前目录内容")
                for item in preview_items:
                    if bool(item.get("is_dir")):
                        count = int(item.get("children_count") or item.get("include_items") or 0) or None
                        suffix = f" · {count} 项" if count is not None else ""
                        updated = str(item.get("updated_at_display") or _display_datetime(item.get("updated_at"))).strip()
                        time_text = f" · {updated}" if updated else ""
                        lines.append(f"📁 {str(item.get('name') or '-')}{suffix}{time_text}")
                    else:
                        original = str(item.get("file_name") or item.get("name") or "-")
                        renamed = str(item.get("file_name_re") or item.get("file_name_saved") or "x")
                        size_text = file_size_text(item.get("size"))
                        updated = str(item.get("updated_at_display") or _display_datetime(item.get("updated_at"))).strip()
                        lines.append(f"📄 {_short_link_text(original, 52)}")
                        lines.append(f"   -> {_short_link_text(renamed, 52)}")
                        lines.append(f"   {size_text} · {updated}")
            ctx["share_dir_items"] = dir_items
        else:
            files = sorted([x for x in items if not bool(x.get("is_dir"))], key=lambda x: str(x.get("updated_at") or ""), reverse=True)
            lines = [
                "选择起始文件",
                f"目录: {current_folder_label}",
                "点击文件后会写入 startfid。",
            ]
            rows.append([button("🧹 清空起始文件", "brw", "start", "clear"), button("🔄 刷新", "brw", "start", "refresh")])
            for idx, item in enumerate(files):
                file_name = str(item.get("file_name") or item.get("name") or "")
                rows.append([button(f"[FILE] {file_name[:24]}", "brw", "start", "pick", idx)])
            preview_files = files[:12]
            if preview_files:
                lines.append("")
                lines.append("可选文件")
                for idx, item in enumerate(preview_files, start=1):
                    original = str(item.get("file_name") or item.get("name") or "-")
                    renamed = str(item.get("file_name_re") or item.get("file_name_saved") or "x")
                    size_text = file_size_text(item.get("size"))
                    updated = str(item.get("updated_at_display") or _display_datetime(item.get("updated_at"))).strip()
                    lines.append(f"#{idx} 📄 {_short_link_text(original, 48)}")
                    lines.append(f"   -> {_short_link_text(renamed, 48)}")
                    lines.append(f"   {size_text} · {updated}")
            ctx["share_startfid_items"] = files
        _set_nested(draft, "__share_folder_label__", current_folder_label)
        rows.append([button("✏️ 返回编辑器", "brw", picker if picker == "start" else "share", "back"), button("🏠 首页", "home")])
        mid = self._edit_or_send(chat_id, "\n".join(lines), message_id=message_id or session.last_message_id, reply_markup=keyboard(rows))
        ctx["draft"] = draft
        ctx["share_picker_mode"] = picker
        ctx["share_root_shareurl"] = root_shareurl
        ctx["share_browse_shareurl"] = current_shareurl
        ctx["share_browse_stack"] = stack
        save_session_data(db, chat_id=chat_id, user_id=self.config.user_id, scene="task_share_browser", step="idle", context=ctx, last_message_id=mid)
        db.commit()

    def _show_task_sync_selector(self, db: Session, chat_id: int, *, message_id: int | None = None) -> None:
        session = load_session_data(db, chat_id=chat_id, user_id=self.config.user_id)
        ctx = dict(session.context or {})
        draft = dict(ctx.get("draft") or {})
        page = max(1, int(ctx.get("sync_selector_page") or 1))
        options = self._actions(db).list_sync_task_options()
        selected = [str(x) for x in (_get_nested(draft, "sync_task_uids") or []) if str(x).strip()]
        _set_nested(draft, "sync_task_names", _sync_task_name_list(options, selected))
        ctx["draft"] = draft

        page_size = 8
        total = len(options)
        max_page = max(1, (total + page_size - 1) // page_size)
        page = min(page, max_page)
        start = (page - 1) * page_size
        items = options[start : start + page_size]

        rows: list[list[dict[str, str]]] = []
        for item in items:
            uid = str(item.get("uid") or "")
            checked = "✓" if uid in selected else "○"
            status = "" if item.get("enabled") else " [停用]"
            rows.append([button(f"{checked} {item.get('name') or uid}{status}", "msel", "sync", "toggle", uid)])
        rows.append([button("🧹 清空已选", "msel", "sync", "clear"), button("✅ 完成", "msel", "sync", "done")])
        rows.append(pagination_row("msel:sync:list", page, total, page_size))
        rows.append([button("✏️ 返回编辑器", "msel", "sync", "done"), button("🏠 首页", "home")])
        selected_names = _sync_task_name_list(options, selected)
        lines = [
            "选择关联同步任务",
            f"已选: {', '.join(selected_names) if selected_names else '-'}",
            f"页码: {page}/{max_page}",
            "点击任务可切换选中状态。",
        ]
        mid = self._edit_or_send(chat_id, "\n".join(lines), message_id=message_id or session.last_message_id, reply_markup=keyboard(rows))
        save_session_data(
            db,
            chat_id=chat_id,
            user_id=self.config.user_id,
            scene="task_sync_selector",
            step="idle",
            context={**ctx, "draft": draft, "sync_selector_page": page},
            last_message_id=mid,
        )
        db.commit()

    def _show_sync_drama_selector(self, db: Session, chat_id: int, *, message_id: int | None = None) -> None:
        session = load_session_data(db, chat_id=chat_id, user_id=self.config.user_id)
        ctx = dict(session.context or {})
        draft = dict(ctx.get("draft") or {})
        page = max(1, int(ctx.get("drama_selector_page") or 1))
        options = self._actions(db).list_drama_task_options()
        selected = [str(x) for x in (_get_nested(draft, "drama_task_uids") or []) if str(x).strip()]
        _set_nested(draft, "drama_task_names", _drama_task_name_list(options, selected))
        ctx["draft"] = draft

        page_size = 8
        total = len(options)
        max_page = max(1, (total + page_size - 1) // page_size)
        page = min(page, max_page)
        start = (page - 1) * page_size
        items = options[start : start + page_size]

        rows: list[list[dict[str, str]]] = []
        for item in items:
            uid = str(item.get("task_uid") or "")
            checked = "✓" if uid in selected else "○"
            status = "" if item.get("enabled") else " [停用]"
            rows.append([button(f"{checked} {item.get('taskname') or uid}{status}", "msel", "drama", "toggle", uid)])
        rows.append([button("🧹 清空已选", "msel", "drama", "clear"), button("✅ 完成", "msel", "drama", "done")])
        rows.append(pagination_row("msel:drama:list", page, total, page_size))
        rows.append([button("✏️ 返回编辑器", "msel", "drama", "done"), button("🏠 首页", "home")])
        selected_names = _drama_task_name_list(options, selected)
        lines = [
            "选择关联追剧任务",
            f"已选: {', '.join(selected_names) if selected_names else '-'}",
            f"页码: {page}/{max_page}",
            "点击任务可切换选中状态。",
        ]
        mid = self._edit_or_send(chat_id, "\n".join(lines), message_id=message_id or session.last_message_id, reply_markup=keyboard(rows))
        save_session_data(
            db,
            chat_id=chat_id,
            user_id=self.config.user_id,
            scene="sync_drama_selector",
            step="idle",
            context={**ctx, "draft": draft, "drama_selector_page": page},
            last_message_id=mid,
        )
        db.commit()

    def _show_sync_path_browser(self, db: Session, chat_id: int, *, field: str, message_id: int | None = None) -> None:
        session = load_session_data(db, chat_id=chat_id, user_id=self.config.user_id)
        ctx = dict(session.context or {})
        draft = dict(ctx.get("draft") or {})
        path_type = str(_get_nested(draft, field.replace(".path", ".type")) or "")
        browse_key = f"browse_path:{field}"
        browse_path = str(ctx.get(browse_key) or _get_nested(draft, field) or ("" if path_type == "local" else "/"))
        payload = self._actions(db).browse_sync_path(path_type=path_type, dir_path=browse_path, max_items=20)
        rows: list[list[dict[str, str]]] = []
        dir_path = str(payload.get("dir_path") or "")
        is_root = dir_path in {"", "/"}
        if not is_root:
            rows.append([button("⬆️ 上一级", "brw", "sync", "up")])
        if not (path_type == "local" and dir_path == ""):
            rows.append([button("✅ 选择当前目录", "brw", "sync", "sel"), button("🔄 刷新", "brw", "sync", "refresh")])
        else:
            rows.append([button("🔄 刷新", "brw", "sync", "refresh")])
        for idx, item in enumerate(payload.get("items") or []):
            prefix = "[DIR] " if item.get("is_dir") else "[FILE] "
            rows.append([button(f"{prefix}{str(item.get('name') or '')[:26]}", "brw", "sync", "open", idx)])
        rows.append([button("✏️ 返回编辑器", "brw", "sync", "back"), button("🏠 首页", "home")])
        text_lines = [
            f"选择同步路径: {field}",
            f"类型: {path_type}",
            f"路径: {dir_path or '/'}",
        ]
        if path_type == "local" and dir_path == "":
            text_lines.append("本地根目录仅用于浏览，请继续进入子目录后再选择。")
        if not payload.get("exists"):
            text_lines.append("当前路径不存在，可先返回后手动输入。")
        mid = self._edit_or_send(chat_id, "\n".join(text_lines), message_id=message_id or session.last_message_id, reply_markup=keyboard(rows))
        ctx["browse_field"] = field
        ctx[browse_key] = dir_path
        save_session_data(db, chat_id=chat_id, user_id=self.config.user_id, scene="sync_browser", step="idle", context=ctx, last_message_id=mid)
        db.commit()

    def _show_account_auth(self, db: Session, chat_id: int, auth_payload: dict[str, Any], *, message_id: int | None = None, back_page: int = 1) -> None:
        account_id = int(auth_payload.get("account_id") or 0)
        method = str(auth_payload.get("method") or "")
        payload = auth_payload.get("payload") or {}
        rows: list[list[dict[str, str]]] = []
        lines = [f"账号 #{account_id} 认证", f"方式: {method or '-'}"]
        if method == "qrcode":
            lines.append(f"二维码链接: {payload.get('qrcode_url') or '-'}")
            lines.append(f"状态: {payload.get('status') or 'NEW'}")
            if payload.get("message"):
                lines.append(f"说明: {payload.get('message')}")
            rows.append([button("🔄 轮询状态", "auth", "poll"), button("🔁 重新开始", "auth", "restart")])
        elif method == "sms":
            lines.append(f"手机号: {payload.get('mobile') or '-'}")
            if payload.get("show_name"):
                lines.append(f"账号: {payload.get('show_name')}")
            rows.append([button("📨 发送短信", "auth", "smssend"), button("🔢 输入验证码", "auth", "input")])
        elif method == "captcha":
            lines.append("已发送验证码图片，请直接回复验证码。")
            rows.append([button("🔢 输入验证码", "auth", "input"), button("🔁 重新开始", "auth", "restart")])
            image_base64 = str(payload.get("image_base64") or "")
            if image_base64:
                try:
                    self._send_photo(chat_id, base64.b64decode(image_base64), caption="cloud189 图形验证码")
                except Exception:
                    logger.exception("telegram captcha image send failed")
        elif method == "done":
            lines.append("认证已完成，账号状态已更新。")
        else:
            lines.append(str(auth_payload.get("message") or "当前账号无需额外认证"))
        rows.append([button("👤 返回账号详情", "acc", "detail", account_id), button("🏠 首页", "home")])
        mid = self._edit_or_send(chat_id, "\n".join(lines), message_id=message_id, reply_markup=keyboard(rows))
        save_session_data(
            db,
            chat_id=chat_id,
            user_id=self.config.user_id,
            scene="account_auth",
            step="idle",
            context={"account_id": account_id, "auth_session_id": auth_payload.get("session_id") or "", "auth_method": method, "page": back_page},
            last_message_id=mid,
        )
        db.commit()

    def _start_editor(
        self,
        db: Session,
        chat_id: int,
        *,
        kind: str,
        title: str,
        fields: list[dict[str, Any]],
        draft: dict[str, Any],
        target_id: int | None = None,
        message_id: int | None = None,
        extras: dict[str, Any] | None = None,
    ) -> None:
        active_fields = _editor_fields(fields)
        field_order = [str(x.get("key") or "") for x in active_fields]
        prefix = {"task": "tsk", "sync": "syn", "account": "acc"}[kind]
        if kind == "task":
            draft = self._decorate_task_draft(draft, ctx=extras)
        mid = self._edit_or_send(
            chat_id,
            editor_message(title, draft, active_fields),
            message_id=message_id,
            reply_markup=editor_keyboard(prefix, target_id, active_fields, draft),
        )
        context = {"kind": kind, "draft": draft, "target_id": target_id or 0, "field_order": field_order}
        if extras:
            context.update(extras)
        save_session_data(db, chat_id=chat_id, user_id=self.config.user_id, scene=f"{kind}_editor", step="idle", context=context, last_message_id=mid)
        db.commit()

    def _run_search_resources(
        self,
        db: Session,
        chat_id: int,
        *,
        input_keyword: str,
        resource_keyword: str,
        replace_task_id: int | None,
        message_id: int | None,
        selected_tmdb: dict[str, Any] | None = None,
    ) -> None:
        loading_mid = self._edit_or_send(
            chat_id,
            search_loading_message(resource_keyword, replace_mode=bool(replace_task_id)),
            message_id=message_id,
            reply_markup=keyboard([[button("✖️ 取消", "cancel"), button("🏠 首页", "home")]]),
        )
        ctx = dict(load_session_data(db, chat_id=chat_id, user_id=self.config.user_id).context or {})
        ctx["selected_tmdb"] = dict(selected_tmdb or {})
        save_session_data(
            db,
            chat_id=chat_id,
            user_id=self.config.user_id,
            scene="search",
            step="searching",
            context=ctx,
            last_message_id=loading_mid or message_id,
        )
        db.commit()
        result = self._actions(db).search_resources(resource_keyword)
        save_session_data(
            db,
            chat_id=chat_id,
            user_id=self.config.user_id,
            context={**ctx, "selected_tmdb": dict(selected_tmdb or {})},
            last_message_id=loading_mid or message_id,
        )
        db.commit()
        self._show_search_results(
            db,
            chat_id,
            keyword=input_keyword,
            results=list(result.get("items") or []),
            page=1,
            replace_task_id=replace_task_id,
            message_id=loading_mid or message_id,
        )

    def _show_share_candidate_picker(
        self,
        db: Session,
        chat_id: int,
        *,
        text: str,
        candidates: list[dict[str, Any]],
        session,
        message_id: int | None = None,
    ) -> None:
        rows: list[list[dict[str, str]]] = []
        lines = [
            "🔗 检测到多条网盘链接",
            "",
            "请选择要用于创建或修改任务的链接：",
        ]
        for idx, item in enumerate(candidates):
            shareurl = str(item.get("shareurl") or "").strip()
            drive_type = str(item.get("drive_type") or "-").strip() or "-"
            lines.append(f"#{idx + 1} {drive_type} · {_short_link_text(shareurl, 72)}")
            rows.append([button(f"#{idx + 1} {drive_type} · {_short_link_text(shareurl, 28)}", "shr", "pick", idx)])
        rows.append([button("✖️ 取消", "cancel"), button("🏠 首页", "home")])
        mid = self._edit_or_send(chat_id, "\n".join(lines), message_id=message_id or session.last_message_id, reply_markup=keyboard(rows))
        ctx = dict(session.context or {})
        ctx["share_text"] = text
        ctx["share_candidates"] = candidates
        save_session_data(
            db,
            chat_id=chat_id,
            user_id=self.config.user_id,
            scene="share_picker",
            step="idle",
            context=ctx,
            last_message_id=mid,
        )
        db.commit()

    def _apply_share_text(self, db: Session, chat_id: int, text: str, session, *, selected_shareurl: str | None = None) -> bool:
        shareurl_hint = str(selected_shareurl or "").strip()
        candidates = self._actions(db).extract_share_candidates(text)
        if not candidates:
            return False
        if not shareurl_hint and len(candidates) > 1:
            self._show_share_candidate_picker(db, chat_id, text=text, candidates=candidates, session=session)
            return True
        picked_shareurl = shareurl_hint or str(candidates[0].get("shareurl") or "")
        loading_mid = self._edit_or_send(
            chat_id,
            "⏳ 正在解析分享链接并准备任务草稿...\n\n识别到消息中包含网盘链接，正在自动进入任务流程。",
            message_id=session.last_message_id,
            reply_markup=keyboard([[button("✖️ 取消", "cancel"), button("🏠 首页", "home")]]),
        )
        info = self._actions(db).inspect_share_candidate(text, picked_shareurl)
        if not info or not bool(info.get("parsed")):
            self._edit_or_send(
                chat_id,
                "未能解析这条网盘分享链接，请检查链接或提取码后重试。",
                message_id=loading_mid or session.last_message_id,
                reply_markup=keyboard([[button("🏠 首页", "home")]]),
            )
            return True
        ctx = dict(session.context or {})
        scene = str(getattr(session, "scene", "") or "")
        preferred_task_id = _preferred_task_id_from_session(scene, ctx)
        matched_task = dict(info.get("matched_task") or {})
        target_task_id = preferred_task_id or (int(matched_task.get("id") or 0) or None)
        shareurl = str(info.get("resolved_shareurl") or info.get("shareurl") or text).strip()
        preview_message = str(info.get("preview_message") or "").strip()

        if target_task_id:
            item = self._actions(db).get_task_detail(target_task_id)
            current_shareurl = str(item.get("shareurl") or "").strip()
            if shareurl and shareurl != current_shareurl:
                item["shareurl"] = shareurl
                item["startfid"] = ""
            item, preview_message = self._apply_task_share_autofill(
                db,
                item,
                raw_text=text,
                selected_shareurl=picked_shareurl,
            )
            title = f"基于分享链接修改任务 #{target_task_id}"
            if preview_message and not bool(info.get("preview_ok")):
                title += f"\n⚠️ 预检: {preview_message}"
            self._start_editor(
                db,
                chat_id,
                kind="task",
                title=title,
                fields=TASK_FIELDS,
                draft=_flatten_seed(TASK_FIELDS, item),
                target_id=target_task_id,
                message_id=loading_mid or session.last_message_id,
                extras={"page": int(ctx.get("page") or 1), "task_type": str(ctx.get("task_type") or item.get("task_type") or "")},
            )
            return True

        seed: dict[str, Any] = {
            "task_type": "drama",
            "shareurl": shareurl,
            "enabled": True,
            "startfid": "",
        }
        seed, preview_message = self._apply_task_share_autofill(
            db,
            seed,
            raw_text=text,
            selected_shareurl=picked_shareurl,
        )
        title = "基于分享链接新建任务"
        if preview_message and not bool(info.get("preview_ok")):
            title += f"\n⚠️ 预检: {preview_message}"
        self._start_editor(
            db,
            chat_id,
            kind="task",
            title=title,
            fields=TASK_FIELDS,
            draft=_flatten_seed(TASK_FIELDS, seed),
            target_id=None,
            message_id=loading_mid or session.last_message_id,
            extras={"page": int(ctx.get("page") or 1), "task_type": str(ctx.get("task_type") or "")},
        )
        return True

    def _handle_share_text(self, db: Session, chat_id: int, text: str, session) -> bool:
        return self._apply_share_text(db, chat_id, text, session)

    def _handle_message(self, message: dict[str, Any]) -> None:
        chat_id = int(((message.get("chat") or {}).get("id")) or 0)
        user_id = int(((message.get("from") or {}).get("id")) or 0)
        if not self._allowed(chat_id, user_id):
            return
        text = str(message.get("text") or "").strip()
        with SessionLocal() as db:
            session = load_session_data(db, chat_id=chat_id, user_id=user_id)
            if text.startswith("/"):
                self._handle_command(db, chat_id, text, session.last_message_id)
                return
            if session.step == "await_keyword":
                if self._handle_share_text(db, chat_id, text, session):
                    return
                replace_task_id = int((session.context.get("replace_task_id") or 0) or 0) or None
                selected_tmdb: dict[str, Any] = {}
                if int(session.context.get("tmdb_id") or 0) > 0 and str(session.context.get("tmdb_media_type") or "").strip():
                    selected_tmdb = {
                        "id": int(session.context.get("tmdb_id") or 0),
                        "media_type": str(session.context.get("tmdb_media_type") or ""),
                        "display_title": str(session.context.get("tmdb_title") or text),
                        "standard_keyword": str(session.context.get("tmdb_title") or text),
                    }
                    self._run_search_resources(
                        db,
                        chat_id,
                        input_keyword=text,
                        resource_keyword=str(selected_tmdb.get("standard_keyword") or text),
                        replace_task_id=replace_task_id,
                        message_id=session.last_message_id,
                        selected_tmdb=selected_tmdb,
                    )
                    return
                loading_mid = self._edit_or_send(
                    chat_id,
                    tmdb_loading_message(text, replace_mode=bool(replace_task_id)),
                    message_id=session.last_message_id,
                    reply_markup=keyboard([[button("✖️ 取消", "cancel"), button("🏠 首页", "home")]]),
                )
                result = self._actions(db).search_tmdb_media(text)
                if bool(result.get("configured")) and list(result.get("items") or []):
                    self._show_tmdb_results(
                        db,
                        chat_id,
                        keyword=text,
                        items=list(result.get("items") or []),
                        page=1,
                        replace_task_id=replace_task_id,
                        message_id=loading_mid or session.last_message_id,
                    )
                else:
                    self._run_search_resources(
                        db,
                        chat_id,
                        input_keyword=text,
                        resource_keyword=text,
                        replace_task_id=replace_task_id,
                        message_id=loading_mid or session.last_message_id,
                    )
                return
            if session.step == "await_field_input":
                self._handle_field_input(db, chat_id, user_id, text, session)
                return
            if session.step == "await_auth_code":
                self._handle_auth_code_input(db, chat_id, text, session)
                return
            if session.step == "await_task_tmdb_keyword":
                self._edit_or_send(
                    chat_id,
                    tmdb_loading_message(text, replace_mode=False),
                    message_id=session.last_message_id,
                    reply_markup=keyboard([[button("✖️ 取消", "cancel"), button("🏠 首页", "home")]]),
                )
                result = self._actions(db).search_tmdb_media(text)
                self._show_tmdb_results(
                    db,
                    chat_id,
                    keyword=text,
                    items=list(result.get("items") or []),
                    page=1,
                    message_id=session.last_message_id,
                    message=str(result.get("message") or "").strip() or None,
                    bind_mode=True,
                )
                return
            if self._handle_share_text(db, chat_id, text, session):
                return
            self._show_home(db, chat_id, message_id=session.last_message_id)

    def _handle_command(self, db: Session, chat_id: int, text: str, message_id: int | None) -> None:
        cmd = text.split()[0].lower()
        if cmd in {"/start", "/help", "/menu"}:
            self._show_home(db, chat_id, message_id=message_id)
        elif cmd == "/tasks":
            self._show_tasks(db, chat_id, page=1, message_id=message_id)
        elif cmd == "/sync":
            self._show_sync_tasks(db, chat_id, page=1, message_id=message_id)
        elif cmd == "/accounts":
            self._show_accounts(db, chat_id, page=1, message_id=message_id)
        elif cmd == "/search":
            self._show_search_prompt(db, chat_id, message_id=message_id)
        elif cmd == "/settings":
            self._show_settings_menu(db, chat_id, message_id=message_id)
        elif cmd == "/status":
            self._show_status(db, chat_id, message_id=message_id)
        elif cmd == "/cancel":
            reset_session(db, chat_id=chat_id, user_id=self.config.user_id, preserve_message_id=False)
            db.commit()
            self._show_home(db, chat_id, message_id=None)
        else:
            self._send(chat_id, "未知命令，可使用 /menu 返回主菜单。")

    def _handle_callback(self, callback_query: dict[str, Any]) -> None:
        data = str(callback_query.get("data") or "")
        parts = parse_callback(data)
        callback_id = str(callback_query.get("id") or "")
        message = callback_query.get("message") or {}
        chat_id = int(((message.get("chat") or {}).get("id")) or 0)
        message_id = int(message.get("message_id") or 0)
        user_id = int(((callback_query.get("from") or {}).get("id")) or 0)
        if not self._allowed(chat_id, user_id):
            self._answer_callback(callback_id, "无权限")
            return
        with SessionLocal() as db:
            try:
                self._dispatch_callback(db, chat_id, message_id, parts)
                self._answer_callback(callback_id)
            except Exception as exc:
                logger.exception("telegram callback failed parts=%s", parts)
                self._answer_callback(callback_id, str(exc)[:100])
                self._send(chat_id, f"处理失败: {exc}")

    def _dispatch_callback(self, db: Session, chat_id: int, message_id: int, parts: list[str]) -> None:
        if not parts:
            self._show_home(db, chat_id, message_id=message_id)
            return
        head = parts[0]
        if head == "home":
            self._show_home(db, chat_id, message_id=message_id)
            return
        if head == "cancel":
            reset_session(db, chat_id=chat_id, user_id=self.config.user_id, preserve_message_id=False)
            db.commit()
            self._show_home(db, chat_id, message_id=message_id)
            return
        if head == "back":
            self._dispatch_back(db, chat_id, message_id)
            return
        if head == "menu":
            target = parts[1] if len(parts) > 1 else "home"
            if target == "tasks":
                self._show_tasks(db, chat_id, page=1, message_id=message_id)
            elif target == "sync":
                self._show_sync_tasks(db, chat_id, page=1, message_id=message_id)
            elif target == "accounts":
                self._show_accounts(db, chat_id, page=1, message_id=message_id)
            elif target == "search":
                self._show_search_prompt(db, chat_id, message_id=message_id)
            elif target == "settings":
                self._show_settings_menu(db, chat_id, message_id=message_id)
            elif target == "status":
                self._show_status(db, chat_id, message_id=message_id)
            else:
                self._show_home(db, chat_id, message_id=message_id)
            return
        if head == "tsk":
            self._dispatch_task(db, chat_id, message_id, parts[1:])
            return
        if head == "syn":
            self._dispatch_sync(db, chat_id, message_id, parts[1:])
            return
        if head == "acc":
            self._dispatch_account(db, chat_id, message_id, parts[1:])
            return
        if head == "cfg":
            self._dispatch_settings(db, chat_id, message_id, parts[1:])
            return
        if head == "sea":
            self._dispatch_search_results(db, chat_id, message_id, parts[1:])
            return
        if head == "tm":
            self._dispatch_tmdb_results(db, chat_id, message_id, parts[1:])
            return
        if head == "brw":
            self._dispatch_browser(db, chat_id, message_id, parts[1:])
            return
        if head == "msel":
            self._dispatch_multi_select(db, chat_id, message_id, parts[1:])
            return
        if head == "auth":
            self._dispatch_auth(db, chat_id, message_id, parts[1:])
            return
        if head == "asel":
            self._dispatch_task_account_selector(db, chat_id, message_id, parts[1:])
            return
        if head == "rsel":
            self._dispatch_task_magic_rule_selector(db, chat_id, message_id, parts[1:])
            return
        if head == "shr":
            self._dispatch_share_picker(db, chat_id, message_id, parts[1:])
            return
        if head == "confirm":
            self._dispatch_confirm(db, chat_id, message_id, parts[1:])
            return
        self._show_home(db, chat_id, message_id=message_id)

    def _dispatch_task(self, db: Session, chat_id: int, message_id: int, parts: list[str]) -> None:
        session = load_session_data(db, chat_id=chat_id, user_id=self.config.user_id)
        ctx = dict(session.context or {})
        action = parts[0] if parts else "list"
        if action == "list":
            page = 1
            task_type = None
            if len(parts) > 1:
                if str(parts[1]).isdigit():
                    page = int(parts[1])
                    if len(parts) > 2 and parts[2] not in {"all", ""}:
                        task_type = parts[2]
                else:
                    task_type = parts[1] if parts[1] not in {"all", ""} else None
                    if len(parts) > 2 and str(parts[2]).isdigit():
                        page = int(parts[2])
            task_type = "drama"
            self._show_tasks(db, chat_id, page=page, task_type=task_type, message_id=message_id)
        elif action == "detail":
            back_page = int(ctx.get("page") or 1)
            task_type = str(ctx.get("task_type") or "")
            self._show_task_detail(db, chat_id, int(parts[1]), message_id=message_id, back_page=back_page, task_type=task_type or None)
        elif action == "run":
            task_id = int(parts[1])
            self._run_async(chat_id, message_id, f"任务 #{task_id} 执行中...", lambda adb: self._actions(adb).run_task(task_id), "任务执行完成")
        elif action == "toggle":
            item = self._actions(db).toggle_task(int(parts[1]))
            self._show_task_detail(
                db,
                chat_id,
                int(item["id"]),
                message_id=message_id,
                back_page=int(ctx.get("page") or 1),
                task_type=str(ctx.get("task_type") or "") or None,
            )
        elif action == "edit":
            task_id = int(parts[1])
            item = self._actions(db).get_task_detail(task_id)
            self._start_editor(
                db,
                chat_id,
                kind="task",
                title=_editor_title("task", task_id),
                fields=TASK_FIELDS,
                draft=_flatten_seed(TASK_FIELDS, item),
                target_id=task_id,
                message_id=message_id,
                extras={"page": int(ctx.get("page") or 1), "task_type": str(ctx.get("task_type") or "")},
            )
        elif action == "new":
            self._start_editor(
                db,
                chat_id,
                kind="task",
                title=_editor_title("task"),
                fields=TASK_FIELDS,
                draft=_flatten_seed(TASK_FIELDS),
                target_id=None,
                message_id=message_id,
                extras={"page": int(ctx.get("page") or 1), "task_type": str(ctx.get("task_type") or "")},
            )
        elif action == "field":
            target_id = None if parts[1] == "new" else int(parts[1])
            field = parts[2]
            self._handle_editor_field_click(db, chat_id, message_id, kind="task", fields=TASK_FIELDS, target_id=target_id, field=field)
        elif action == "save":
            target_id = None if parts[1] == "new" else int(parts[1])
            self._handle_editor_save(db, chat_id, message_id, kind="task", fields=TASK_FIELDS, target_id=target_id)
        elif action == "search":
            task_id = int(parts[1])
            item = self._actions(db).get_task_detail(task_id)
            self._show_search_prompt(db, chat_id, replace_task_id=task_id, message_id=message_id)
            save_session_data(
                db,
                chat_id=chat_id,
                user_id=self.config.user_id,
                scene="search",
                step="await_keyword",
                context={
                    "replace_task_id": task_id,
                    "page": int(ctx.get("page") or 1),
                    "task_type": str(ctx.get("task_type") or ""),
                    "tmdb_id": int(item.get("tmdb_id") or 0),
                    "tmdb_media_type": str(item.get("tmdb_media_type") or ""),
                    "tmdb_title": str(item.get("taskname") or ""),
                },
                last_message_id=message_id,
            )
            db.commit()
        elif action == "execs":
            task_id = int(parts[1])
            rows = self._actions(db).list_task_executions(task_id, limit=5)
            lines = [f"任务 #{task_id} 最近执行"]
            for item in rows:
                lines.append(f"#{item.get('id')} {item.get('status')} {item.get('message') or '-'}")
            self._edit_or_send(chat_id, "\n".join(lines), message_id=message_id, reply_markup=keyboard([[button("📌 返回任务详情", "tsk", "detail", task_id)], [button("🏠 首页", "home")]]))
        elif action == "delete":
            task_id = int(parts[1])
            self._edit_or_send(chat_id, f"⚠️ 确认删除任务 #{task_id} 吗？", message_id=message_id, reply_markup=keyboard([[button("🗑️ 确认删除", "confirm", "taskdel", task_id)], [button("✖️ 取消", "tsk", "detail", task_id)]]))

    def _dispatch_sync(self, db: Session, chat_id: int, message_id: int, parts: list[str]) -> None:
        session = load_session_data(db, chat_id=chat_id, user_id=self.config.user_id)
        ctx = dict(session.context or {})
        action = parts[0] if parts else "list"
        if action == "list":
            page = int(parts[1]) if len(parts) > 1 and str(parts[1]).isdigit() else 1
            self._show_sync_tasks(db, chat_id, page=page, message_id=message_id)
        elif action == "detail":
            self._show_sync_detail(db, chat_id, int(parts[1]), message_id=message_id, back_page=int(ctx.get("page") or 1))
        elif action == "run":
            sync_task_id = int(parts[1])
            self._run_async(chat_id, message_id, f"同步任务 #{sync_task_id} 执行中...", lambda adb: self._actions(adb).run_sync_task(sync_task_id), "同步执行完成")
        elif action == "cancel":
            sync_task_id = int(parts[1])
            result = self._actions(db).cancel_sync_task(sync_task_id)
            text = f"已请求取消同步任务 #{sync_task_id}" if result else "当前没有运行中的同步执行"
            self._edit_or_send(chat_id, text, message_id=message_id, reply_markup=keyboard([[button("🔄 返回同步详情", "syn", "detail", sync_task_id)], [button("🏠 首页", "home")]]))
        elif action == "toggle":
            item = self._actions(db).toggle_sync_task(int(parts[1]))
            self._show_sync_detail(db, chat_id, int(item["id"]), message_id=message_id, back_page=int(ctx.get("page") or 1))
        elif action == "edit":
            sync_task_id = int(parts[1])
            item = self._actions(db).get_sync_task_detail(sync_task_id)
            self._start_editor(
                db,
                chat_id,
                kind="sync",
                title=_editor_title("sync", sync_task_id),
                fields=SYNC_FIELDS,
                draft=_flatten_seed(SYNC_FIELDS, item),
                target_id=sync_task_id,
                message_id=message_id,
                extras={"page": int(ctx.get("page") or 1)},
            )
        elif action == "new":
            self._start_editor(
                db,
                chat_id,
                kind="sync",
                title=_editor_title("sync"),
                fields=SYNC_FIELDS,
                draft=_flatten_seed(SYNC_FIELDS),
                message_id=message_id,
                extras={"page": int(ctx.get("page") or 1)},
            )
        elif action == "field":
            target_id = None if parts[1] == "new" else int(parts[1])
            field = parts[2]
            self._handle_editor_field_click(db, chat_id, message_id, kind="sync", fields=SYNC_FIELDS, target_id=target_id, field=field)
        elif action == "save":
            target_id = None if parts[1] == "new" else int(parts[1])
            self._handle_editor_save(db, chat_id, message_id, kind="sync", fields=SYNC_FIELDS, target_id=target_id)
        elif action == "execs":
            sync_task_id = int(parts[1])
            rows = self._actions(db).list_sync_executions(sync_task_id, limit=5)
            lines = [f"同步 #{sync_task_id} 最近执行"]
            for item in rows:
                lines.append(f"#{item.get('id')} {item.get('status')} {item.get('message') or '-'}")
            self._edit_or_send(chat_id, "\n".join(lines), message_id=message_id, reply_markup=keyboard([[button("🔄 返回同步详情", "syn", "detail", sync_task_id)], [button("🏠 首页", "home")]]))
        elif action == "delete":
            sync_task_id = int(parts[1])
            self._edit_or_send(chat_id, f"⚠️ 确认删除同步任务 #{sync_task_id} 吗？", message_id=message_id, reply_markup=keyboard([[button("🗑️ 确认删除", "confirm", "syncdel", sync_task_id)], [button("✖️ 取消", "syn", "detail", sync_task_id)]]))

    def _dispatch_account(self, db: Session, chat_id: int, message_id: int, parts: list[str]) -> None:
        session = load_session_data(db, chat_id=chat_id, user_id=self.config.user_id)
        ctx = dict(session.context or {})
        action = parts[0] if parts else "list"
        if action == "list":
            page = int(parts[1]) if len(parts) > 1 and str(parts[1]).isdigit() else 1
            self._show_accounts(db, chat_id, page=page, message_id=message_id)
        elif action == "detail":
            self._show_account_detail(db, chat_id, int(parts[1]), message_id=message_id, back_page=int(ctx.get("page") or 1))
        elif action == "default":
            item = self._actions(db).set_account_default(int(parts[1]))
            self._show_account_detail(db, chat_id, int(item["id"]), message_id=message_id, back_page=int(ctx.get("page") or 1))
        elif action == "toggle":
            item = self._actions(db).toggle_account(int(parts[1]))
            self._show_account_detail(db, chat_id, int(item["id"]), message_id=message_id, back_page=int(ctx.get("page") or 1))
        elif action == "probe":
            item = self._actions(db).probe_account(int(parts[1]))
            self._show_account_detail(db, chat_id, int(item["id"]), message_id=message_id, back_page=int(ctx.get("page") or 1))
        elif action == "signin":
            account_id = int(parts[1])
            result = self._actions(db).sign_in_account(account_id)
            lines = [f"账号 #{account_id} 签到结果", str(result)]
            self._edit_or_send(chat_id, "\n".join(lines), message_id=message_id, reply_markup=keyboard([[button("👤 返回账号详情", "acc", "detail", account_id)], [button("🏠 首页", "home")]]))
        elif action == "auth":
            account_id = int(parts[1])
            payload = self._actions(db).start_account_auth(account_id)
            if payload.get("method") == "done":
                self._show_account_detail(db, chat_id, account_id, message_id=message_id, back_page=int(ctx.get("page") or 1))
            else:
                self._show_account_auth(db, chat_id, payload, message_id=message_id, back_page=int(ctx.get("page") or 1))
        elif action == "refresh":
            items = self._actions(db).refresh_accounts()
            self._edit_or_send(chat_id, f"已刷新 {len(items)} 个账号资料", message_id=message_id, reply_markup=keyboard([[button("👥 返回账号列表", "acc", "list", 1)], [button("🏠 首页", "home")]]))
        elif action == "edit":
            account_id = int(parts[1])
            item = self._actions(db).get_account_detail(account_id)
            draft = _flatten_seed(ACCOUNT_FIELDS, item)
            drive_types = [x.get("code") for x in self._actions(db).get_drive_types()]
            self._start_editor(
                db,
                chat_id,
                kind="account",
                title=f"编辑账号 #{account_id}",
                fields=ACCOUNT_FIELDS,
                draft=draft,
                target_id=account_id,
                message_id=message_id,
                extras={"drive_types": [x for x in drive_types if x], "page": int(ctx.get("page") or 1)},
            )
        elif action == "new":
            drive_types = [x.get("code") for x in self._actions(db).get_drive_types()]
            draft = _flatten_seed(ACCOUNT_FIELDS)
            if drive_types:
                _set_nested(draft, "drive_type", drive_types[0])
            self._start_editor(
                db,
                chat_id,
                kind="account",
                title="新建账号",
                fields=ACCOUNT_FIELDS,
                draft=draft,
                message_id=message_id,
                extras={"drive_types": [x for x in drive_types if x], "page": int(ctx.get("page") or 1)},
            )
        elif action == "field":
            target_id = None if parts[1] == "new" else int(parts[1])
            field = parts[2]
            self._handle_editor_field_click(db, chat_id, message_id, kind="account", fields=ACCOUNT_FIELDS, target_id=target_id, field=field)
        elif action == "save":
            target_id = None if parts[1] == "new" else int(parts[1])
            self._handle_editor_save(db, chat_id, message_id, kind="account", fields=ACCOUNT_FIELDS, target_id=target_id)

    def _dispatch_settings(self, db: Session, chat_id: int, message_id: int, parts: list[str]) -> None:
        action = parts[0] if parts else "menu"
        if action == "domain":
            domain = parts[1]
            page = int(parts[2]) if len(parts) > 2 and str(parts[2]).isdigit() else 1
            self._show_setting_domain(db, chat_id, domain, page=page, message_id=message_id)
        elif action == "field":
            domain = parts[1]
            field = parts[2]
            self._handle_settings_field_click(db, chat_id, message_id, domain, field)
        elif action == "testnotify":
            current = load_session_data(db, chat_id=chat_id, user_id=self.config.user_id)
            current_page = int((current.context or {}).get("page") or 1)
            results = self._actions(db).send_notification_test("TG 测试通知", "这是一条来自 TG 控制台的测试消息。")
            lines = ["通知测试结果"] + [f"{x.get('channel')}: {'ok' if x.get('ok') else x.get('error') or 'failed'}" for x in results]
            self._edit_or_send(
                chat_id,
                "\n".join(lines),
                message_id=message_id,
                reply_markup=keyboard([[button("⚙️ 返回通知配置", "cfg", "domain", "notifications", current_page)], [button("🏠 首页", "home")]]),
            )
        else:
            self._show_settings_menu(db, chat_id, message_id=message_id)

    def _dispatch_tmdb_results(self, db: Session, chat_id: int, message_id: int, parts: list[str]) -> None:
        session = load_session_data(db, chat_id=chat_id, user_id=self.config.user_id)
        ctx = dict(session.context or {})
        items = list(ctx.get("tmdb_results") or [])
        keyword = str(ctx.get("keyword") or "")
        replace_task_id = int(ctx.get("replace_task_id") or 0) or None
        action = parts[0] if parts else "list"
        bind_mode = bool(ctx.get("tmdb_bind_mode"))
        if action == "list":
            page = int(parts[1]) if len(parts) > 1 and str(parts[1]).isdigit() else 1
            self._show_tmdb_results(db, chat_id, keyword=keyword, items=items, page=page, replace_task_id=replace_task_id, message_id=message_id, bind_mode=bind_mode)
            return
        if action == "pick":
            idx = int(parts[1]) if len(parts) > 1 else -1
            if idx < 0 or idx >= len(items):
                raise ValueError("TMDB 条目不存在")
            item = dict(items[idx] or {})
            if bind_mode:
                draft = dict(ctx.get("draft") or {})
                _set_nested(draft, "tmdb_id", int(item.get("id") or 0) or None)
                _set_nested(draft, "tmdb_media_type", str(item.get("media_type") or ""))
                _set_nested(draft, "__tmdb_title__", str(item.get("display_title") or item.get("title") or item.get("name") or "").strip())
                ctx["draft"] = draft
                ctx.pop("tmdb_results", None)
                ctx.pop("keyword", None)
                ctx.pop("tmdb_bind_mode", None)
                save_session_data(db, chat_id=chat_id, user_id=self.config.user_id, scene="task_editor", step="idle", context=ctx, last_message_id=message_id)
                db.commit()
                self._resume_task_editor(db, chat_id, ctx=ctx, message_id=message_id)
                return
            resource_keyword = str(item.get("standard_keyword") or item.get("display_title") or keyword).strip() or keyword
            self._run_search_resources(
                db,
                chat_id,
                input_keyword=keyword,
                resource_keyword=resource_keyword,
                replace_task_id=replace_task_id,
                message_id=message_id,
                selected_tmdb=item,
            )
            return
        if action == "input" and bind_mode:
            self._show_task_tmdb_prompt(db, chat_id, message_id=message_id)
            return
        if action == "back" and bind_mode:
            ctx.pop("tmdb_results", None)
            ctx.pop("keyword", None)
            ctx.pop("tmdb_bind_mode", None)
            save_session_data(db, chat_id=chat_id, user_id=self.config.user_id, scene="task_editor", step="idle", context=ctx, last_message_id=message_id)
            db.commit()
            self._resume_task_editor(db, chat_id, ctx=ctx, message_id=message_id)
            return
        if action == "clear" and bind_mode:
            draft = dict(ctx.get("draft") or {})
            _set_nested(draft, "tmdb_id", None)
            _set_nested(draft, "tmdb_media_type", "")
            _set_nested(draft, "__tmdb_title__", "")
            ctx["draft"] = draft
            ctx.pop("tmdb_results", None)
            ctx.pop("keyword", None)
            ctx.pop("tmdb_bind_mode", None)
            save_session_data(db, chat_id=chat_id, user_id=self.config.user_id, scene="task_editor", step="idle", context=ctx, last_message_id=message_id)
            db.commit()
            self._resume_task_editor(db, chat_id, ctx=ctx, message_id=message_id)
            return
        if action == "skip":
            self._run_search_resources(
                db,
                chat_id,
                input_keyword=keyword,
                resource_keyword=keyword,
                replace_task_id=replace_task_id,
                message_id=message_id,
                selected_tmdb=None,
            )
            return
        self._show_tmdb_results(db, chat_id, keyword=keyword, items=items, page=1, replace_task_id=replace_task_id, message_id=message_id)

    def _dispatch_search_results(self, db: Session, chat_id: int, message_id: int, parts: list[str]) -> None:
        session = load_session_data(db, chat_id=chat_id, user_id=self.config.user_id)
        ctx = session.context or {}
        results = list(ctx.get("results") or [])
        keyword = str(ctx.get("keyword") or "")
        replace_task_id = int(ctx.get("replace_task_id") or 0) or None
        selected_tmdb = dict(ctx.get("selected_tmdb") or {})
        action = parts[0] if parts else "list"
        if action == "list":
            page = int(parts[1]) if len(parts) > 1 and str(parts[1]).isdigit() else 1
            self._show_search_results(db, chat_id, keyword=keyword, results=results, page=page, replace_task_id=replace_task_id, message_id=message_id)
        elif action == "create":
            idx = int(parts[1])
            if idx >= len(results):
                raise ValueError("搜索结果不存在")
            item = results[idx]
            seed = {"task_type": "drama", "taskname": item.get("taskname") or "", "shareurl": item.get("shareurl") or "", "enabled": True}
            if int(selected_tmdb.get("id") or 0) > 0 and str(selected_tmdb.get("media_type") or "").strip():
                seed["tmdb_id"] = int(selected_tmdb.get("id") or 0)
                seed["tmdb_media_type"] = str(selected_tmdb.get("media_type") or "")
                seed["__tmdb_title__"] = str(selected_tmdb.get("display_title") or selected_tmdb.get("title") or selected_tmdb.get("name") or "")
                seed["taskname"] = str(selected_tmdb.get("display_title") or selected_tmdb.get("title") or selected_tmdb.get("name") or seed["taskname"])
            draft = _flatten_seed(TASK_FIELDS, seed)
            self._start_editor(db, chat_id, kind="task", title="基于搜索结果新建任务", fields=TASK_FIELDS, draft=draft, message_id=message_id)
        elif action == "replace":
            idx = int(parts[1])
            if idx >= len(results):
                raise ValueError("搜索结果不存在")
            if not replace_task_id:
                raise ValueError("没有指定要替换的任务")
            item = results[idx]
            task = self._actions(db).replace_task_shareurl(
                replace_task_id,
                str(item.get("shareurl") or ""),
                tmdb_id=int(selected_tmdb.get("id") or 0) or None,
                tmdb_media_type=str(selected_tmdb.get("media_type") or "") or None,
            )
            self._show_task_detail(
                db,
                chat_id,
                int(task["id"]),
                message_id=message_id,
                back_page=int(ctx.get("page") or 1),
                task_type=str(ctx.get("task_type") or "") or None,
            )

    def _dispatch_browser(self, db: Session, chat_id: int, message_id: int, parts: list[str]) -> None:
        session = load_session_data(db, chat_id=chat_id, user_id=self.config.user_id)
        ctx = dict(session.context or {})
        mode = parts[0] if parts else ""
        action = parts[1] if len(parts) > 1 else "refresh"
        if mode == "task":
            current_path = str(ctx.get("browse_path") or "/")
            if action == "up":
                ctx["browse_path"] = _remote_parent_path(current_path)
                save_session_data(db, chat_id=chat_id, user_id=self.config.user_id, context=ctx)
                db.commit()
                self._show_task_drive_browser(db, chat_id, message_id=message_id)
                return
            if action == "open":
                idx = int(parts[2]) if len(parts) > 2 else -1
                payload = self._actions(db).browse_task_drive(
                    dir_path=current_path,
                    account_name=_get_nested(ctx.get("draft") or {}, "account_name"),
                    shareurl=_get_nested(ctx.get("draft") or {}, "shareurl"),
                    max_items=20,
                )
                items = list(payload.get("items") or [])
                if idx < 0 or idx >= len(items):
                    raise ValueError("目录项不存在")
                item = items[idx]
                if not item.get("is_dir"):
                    raise ValueError("只能选择目录")
                next_path = f"{current_path.rstrip('/')}/{item.get('name')}".replace("//", "/") if current_path not in {"", "/"} else f"/{item.get('name')}"
                ctx["browse_path"] = next_path
                save_session_data(db, chat_id=chat_id, user_id=self.config.user_id, context=ctx)
                db.commit()
                self._show_task_drive_browser(db, chat_id, message_id=message_id)
                return
            if action == "sel":
                draft = dict(ctx.get("draft") or {})
                _set_nested(draft, "savepath", current_path if current_path != "/" else "/")
                ctx["draft"] = draft
                ctx.pop("browse_path", None)
                save_session_data(db, chat_id=chat_id, user_id=self.config.user_id, scene="task_editor", step="idle", context=ctx, last_message_id=message_id)
                db.commit()
                self._start_editor(
                    db,
                    chat_id,
                    kind="task",
                    title=_editor_title("task", int(ctx.get("target_id") or 0) or None),
                    fields=TASK_FIELDS,
                    draft=draft,
                    target_id=int(ctx.get("target_id") or 0) or None,
                    message_id=message_id,
                    extras={k: v for k, v in ctx.items() if k != "draft"},
                )
                return
            if action in {"refresh", "back"}:
                if action == "back":
                    ctx.pop("browse_path", None)
                    save_session_data(db, chat_id=chat_id, user_id=self.config.user_id, scene="task_editor", step="idle", context=ctx, last_message_id=message_id)
                    db.commit()
                    self._start_editor(
                        db,
                        chat_id,
                        kind="task",
                        title=_editor_title("task", int(ctx.get("target_id") or 0) or None),
                        fields=TASK_FIELDS,
                        draft=dict(ctx.get("draft") or {}),
                        target_id=int(ctx.get("target_id") or 0) or None,
                        message_id=message_id,
                        extras={k: v for k, v in ctx.items() if k != "draft"},
                    )
                    return
                self._show_task_drive_browser(db, chat_id, message_id=message_id)
                return
        if mode in {"share", "start"}:
            draft = dict(ctx.get("draft") or {})
            root_shareurl = str(ctx.get("share_root_shareurl") or _task_shareurl(_get_nested(draft, "shareurl"), "0")).strip()
            current_shareurl = str(ctx.get("share_browse_shareurl") or _get_nested(draft, "shareurl") or "").strip()
            stack = list(ctx.get("share_browse_stack") or [])
            if action == "open":
                idx = int(parts[2]) if len(parts) > 2 else -1
                items = list(ctx.get("share_dir_items") or [])
                if idx < 0 or idx >= len(items):
                    raise ValueError("目录项不存在")
                item = dict(items[idx] or {})
                if not bool(item.get("is_dir")):
                    raise ValueError("只能选择目录")
                stack.append({"name": str(item.get("name") or ""), "pdir_fid": str(item.get("fid") or "")})
                ctx["share_browse_stack"] = stack
                ctx["share_browse_shareurl"] = _task_shareurl(root_shareurl, str(item.get("fid") or ""))
                save_session_data(db, chat_id=chat_id, user_id=self.config.user_id, context=ctx)
                db.commit()
                self._show_task_share_browser(db, chat_id, picker="folder", message_id=message_id)
                return
            if action == "up":
                if stack:
                    stack.pop()
                target_fid = str((stack[-1] or {}).get("pdir_fid") or "0") if stack else "0"
                ctx["share_browse_stack"] = stack
                ctx["share_browse_shareurl"] = _task_shareurl(root_shareurl, target_fid)
                save_session_data(db, chat_id=chat_id, user_id=self.config.user_id, context=ctx)
                db.commit()
                self._show_task_share_browser(db, chat_id, picker="folder", message_id=message_id)
                return
            if action == "sel":
                draft["shareurl"] = current_shareurl
                draft["startfid"] = ""
                draft["__startfid_label__"] = "-"
                draft["__share_folder_label__"] = _share_folder_label(current_shareurl, stack)
                ctx["draft"] = draft
                for key in ("share_root_shareurl", "share_browse_shareurl", "share_browse_stack", "share_dir_items", "share_startfid_items", "share_picker_mode"):
                    ctx.pop(key, None)
                save_session_data(db, chat_id=chat_id, user_id=self.config.user_id, scene="task_editor", step="idle", context=ctx, last_message_id=message_id)
                db.commit()
                self._start_editor(
                    db,
                    chat_id,
                    kind="task",
                    title=_editor_title("task", int(ctx.get("target_id") or 0) or None),
                    fields=TASK_FIELDS,
                    draft=draft,
                    target_id=int(ctx.get("target_id") or 0) or None,
                    message_id=message_id,
                    extras={k: v for k, v in ctx.items() if k != "draft"},
                )
                return
            if action == "pick":
                files = list(ctx.get("share_startfid_items") or [])
                idx = int(parts[2]) if len(parts) > 2 else -1
                if idx < 0 or idx >= len(files):
                    raise ValueError("文件不存在")
                item = dict(files[idx] or {})
                draft["startfid"] = str(item.get("fid") or "")
                draft["__startfid_label__"] = _startfid_label_from_item(item)
                draft["shareurl"] = current_shareurl
                draft["__share_folder_label__"] = _share_folder_label(current_shareurl, stack)
                ctx["draft"] = draft
                for key in ("share_root_shareurl", "share_browse_shareurl", "share_browse_stack", "share_dir_items", "share_startfid_items", "share_picker_mode"):
                    ctx.pop(key, None)
                save_session_data(db, chat_id=chat_id, user_id=self.config.user_id, scene="task_editor", step="idle", context=ctx, last_message_id=message_id)
                db.commit()
                self._start_editor(
                    db,
                    chat_id,
                    kind="task",
                    title=_editor_title("task", int(ctx.get("target_id") or 0) or None),
                    fields=TASK_FIELDS,
                    draft=draft,
                    target_id=int(ctx.get("target_id") or 0) or None,
                    message_id=message_id,
                    extras={k: v for k, v in ctx.items() if k != "draft"},
                )
                return
            if action == "clear":
                draft["startfid"] = ""
                draft["__startfid_label__"] = "-"
                ctx["draft"] = draft
                save_session_data(db, chat_id=chat_id, user_id=self.config.user_id, scene="task_editor", step="idle", context=ctx, last_message_id=message_id)
                db.commit()
                self._start_editor(
                    db,
                    chat_id,
                    kind="task",
                    title=_editor_title("task", int(ctx.get("target_id") or 0) or None),
                    fields=TASK_FIELDS,
                    draft=draft,
                    target_id=int(ctx.get("target_id") or 0) or None,
                    message_id=message_id,
                    extras={k: v for k, v in ctx.items() if k != "draft"},
                )
                return
            if action in {"refresh", "back"}:
                if action == "back":
                    for key in ("share_root_shareurl", "share_browse_shareurl", "share_browse_stack", "share_dir_items", "share_startfid_items", "share_picker_mode"):
                        ctx.pop(key, None)
                    save_session_data(db, chat_id=chat_id, user_id=self.config.user_id, scene="task_editor", step="idle", context=ctx, last_message_id=message_id)
                    db.commit()
                    self._start_editor(
                        db,
                        chat_id,
                        kind="task",
                        title=_editor_title("task", int(ctx.get("target_id") or 0) or None),
                        fields=TASK_FIELDS,
                        draft=dict(ctx.get("draft") or {}),
                        target_id=int(ctx.get("target_id") or 0) or None,
                        message_id=message_id,
                        extras={k: v for k, v in ctx.items() if k != "draft"},
                    )
                    return
                self._show_task_share_browser(db, chat_id, picker="startfid" if mode == "start" else "folder", message_id=message_id)
                return
        if mode == "sync":
            field = str(ctx.get("browse_field") or "")
            if not field:
                raise ValueError("缺少浏览字段")
            browse_key = f"browse_path:{field}"
            current_path = str(ctx.get(browse_key) or "")
            if action == "up":
                draft = dict(ctx.get("draft") or {})
                path_type = str(_get_nested(draft, field.replace(".path", ".type")) or "")
                ctx[browse_key] = _local_parent_path(current_path) if path_type == "local" else _remote_parent_path(current_path)
                save_session_data(db, chat_id=chat_id, user_id=self.config.user_id, context=ctx)
                db.commit()
                self._show_sync_path_browser(db, chat_id, field=field, message_id=message_id)
                return
            if action == "open":
                idx = int(parts[2]) if len(parts) > 2 else -1
                draft = dict(ctx.get("draft") or {})
                path_type = str(_get_nested(draft, field.replace(".path", ".type")) or "")
                payload = self._actions(db).browse_sync_path(path_type=path_type, dir_path=current_path, max_items=20)
                items = list(payload.get("items") or [])
                if idx < 0 or idx >= len(items):
                    raise ValueError("目录项不存在")
                item = items[idx]
                if not item.get("is_dir"):
                    raise ValueError("只能选择目录")
                ctx[browse_key] = str(item.get("path") or "")
                save_session_data(db, chat_id=chat_id, user_id=self.config.user_id, context=ctx)
                db.commit()
                self._show_sync_path_browser(db, chat_id, field=field, message_id=message_id)
                return
            if action == "sel":
                draft = dict(ctx.get("draft") or {})
                path_type = str(_get_nested(draft, field.replace(".path", ".type")) or "")
                if path_type == "local" and current_path == "":
                    raise ValueError("请先进入本地子目录后再选择")
                _set_nested(draft, field, current_path)
                ctx["draft"] = draft
                ctx.pop(browse_key, None)
                ctx.pop("browse_field", None)
                save_session_data(db, chat_id=chat_id, user_id=self.config.user_id, scene="sync_editor", step="idle", context=ctx, last_message_id=message_id)
                db.commit()
                self._start_editor(
                    db,
                    chat_id,
                    kind="sync",
                    title=_editor_title("sync", int(ctx.get("target_id") or 0) or None),
                    fields=SYNC_FIELDS,
                    draft=draft,
                    target_id=int(ctx.get("target_id") or 0) or None,
                    message_id=message_id,
                    extras={k: v for k, v in ctx.items() if k != "draft"},
                )
                return
            if action in {"refresh", "back"}:
                if action == "back":
                    ctx.pop(browse_key, None)
                    ctx.pop("browse_field", None)
                    save_session_data(db, chat_id=chat_id, user_id=self.config.user_id, scene="sync_editor", step="idle", context=ctx, last_message_id=message_id)
                    db.commit()
                    self._start_editor(
                        db,
                        chat_id,
                        kind="sync",
                        title=_editor_title("sync", int(ctx.get("target_id") or 0) or None),
                        fields=SYNC_FIELDS,
                        draft=dict(ctx.get("draft") or {}),
                        target_id=int(ctx.get("target_id") or 0) or None,
                        message_id=message_id,
                        extras={k: v for k, v in ctx.items() if k != "draft"},
                    )
                    return
                self._show_sync_path_browser(db, chat_id, field=field, message_id=message_id)
                return
        raise ValueError("不支持的浏览动作")

    def _dispatch_multi_select(self, db: Session, chat_id: int, message_id: int, parts: list[str]) -> None:
        session = load_session_data(db, chat_id=chat_id, user_id=self.config.user_id)
        ctx = dict(session.context or {})
        draft = dict(ctx.get("draft") or {})
        mode = parts[0] if parts else ""
        action = parts[1] if len(parts) > 1 else "list"
        if mode == "sync":
            options = self._actions(db).list_sync_task_options()
            value_key = "sync_task_uids"
            display_key = "sync_task_names"
            page_key = "sync_selector_page"
            kind = "task"
            fields = TASK_FIELDS
            title = _editor_title("task", int(ctx.get("target_id") or 0) or None)
            selected = [str(x) for x in (_get_nested(draft, value_key) or []) if str(x).strip()]
        elif mode == "drama":
            options = self._actions(db).list_drama_task_options()
            value_key = "drama_task_uids"
            display_key = "drama_task_names"
            page_key = "drama_selector_page"
            kind = "sync"
            fields = SYNC_FIELDS
            title = _editor_title("sync", int(ctx.get("target_id") or 0) or None)
            selected = [str(x) for x in (_get_nested(draft, value_key) or []) if str(x).strip()]
        else:
            raise ValueError("不支持的多选动作")
        if action == "list":
            page = int(parts[2]) if len(parts) > 2 and str(parts[2]).isdigit() else 1
            ctx[page_key] = page
            save_session_data(db, chat_id=chat_id, user_id=self.config.user_id, context={**ctx, "draft": draft}, last_message_id=message_id)
            db.commit()
            if mode == "sync":
                self._show_task_sync_selector(db, chat_id, message_id=message_id)
            else:
                self._show_sync_drama_selector(db, chat_id, message_id=message_id)
            return
        if action == "toggle":
            uid = str(parts[2] or "") if len(parts) > 2 else ""
            if uid:
                if uid in selected:
                    selected = [x for x in selected if x != uid]
                else:
                    selected.append(uid)
            _set_nested(draft, value_key, selected)
            if mode == "sync":
                _set_nested(draft, display_key, _sync_task_name_list(options, selected))
            else:
                _set_nested(draft, display_key, _drama_task_name_list(options, selected))
            ctx["draft"] = draft
            save_session_data(db, chat_id=chat_id, user_id=self.config.user_id, context=ctx, last_message_id=message_id)
            db.commit()
            if mode == "sync":
                self._show_task_sync_selector(db, chat_id, message_id=message_id)
            else:
                self._show_sync_drama_selector(db, chat_id, message_id=message_id)
            return
        if action == "clear":
            _set_nested(draft, value_key, [])
            _set_nested(draft, display_key, [])
            ctx["draft"] = draft
            save_session_data(db, chat_id=chat_id, user_id=self.config.user_id, context=ctx, last_message_id=message_id)
            db.commit()
            if mode == "sync":
                self._show_task_sync_selector(db, chat_id, message_id=message_id)
            else:
                self._show_sync_drama_selector(db, chat_id, message_id=message_id)
            return
        if action == "done":
            ctx.pop(page_key, None)
            ctx["draft"] = draft
            save_session_data(db, chat_id=chat_id, user_id=self.config.user_id, scene=f"{kind}_editor", step="idle", context=ctx, last_message_id=message_id)
            db.commit()
            self._start_editor(
                db,
                chat_id,
                kind=kind,
                title=title,
                fields=fields,
                draft=draft,
                target_id=int(ctx.get("target_id") or 0) or None,
                message_id=message_id,
                extras={k: v for k, v in ctx.items() if k != "draft"},
            )
            return
        raise ValueError("不支持的多选动作")

    def _dispatch_auth(self, db: Session, chat_id: int, message_id: int, parts: list[str]) -> None:
        session = load_session_data(db, chat_id=chat_id, user_id=self.config.user_id)
        ctx = dict(session.context or {})
        account_id = int(ctx.get("account_id") or 0)
        auth_session_id = str(ctx.get("auth_session_id") or "")
        page = int(ctx.get("page") or 1)
        action = parts[0] if parts else "status"
        if action == "restart":
            payload = self._actions(db).start_account_auth(account_id)
            self._show_account_auth(db, chat_id, payload, message_id=message_id, back_page=page)
            return
        if not auth_session_id:
            raise ValueError("认证会话已失效")
        if action == "poll":
            result = self._actions(db).poll_account_auth_qrcode(auth_session_id)
            if result.get("done"):
                self._show_account_detail(db, chat_id, int(result["account"]["id"]), message_id=message_id, back_page=page)
            else:
                self._show_account_auth(db, chat_id, result, message_id=message_id, back_page=page)
            return
        if action == "smssend":
            result = self._actions(db).send_account_auth_sms(auth_session_id)
            info = self._actions(db).get_account_auth_status(auth_session_id)
            info["payload"] = {**dict(info.get("payload") or {}), "message": str(result.get("message") or "短信已发送")}
            self._show_account_auth(db, chat_id, info, message_id=message_id, back_page=page)
            return
        if action == "input":
            save_session_data(
                db,
                chat_id=chat_id,
                user_id=self.config.user_id,
                scene="account_auth_input",
                step="await_auth_code",
                context=ctx,
                last_message_id=message_id,
            )
            db.commit()
            self._show_back_cancel_home(chat_id, "请输入认证验证码。", message_id=message_id)
            return

    def _dispatch_confirm(self, db: Session, chat_id: int, message_id: int, parts: list[str]) -> None:
        session = load_session_data(db, chat_id=chat_id, user_id=self.config.user_id)
        ctx = dict(session.context or {})
        action = parts[0] if parts else ""
        target_id = int(parts[1]) if len(parts) > 1 else 0
        if action == "taskdel":
            self._actions(db).delete_task(target_id)
            self._show_tasks(db, chat_id, page=int(ctx.get("page") or 1), task_type=str(ctx.get("task_type") or "") or None, message_id=message_id)
        elif action == "syncdel":
            self._actions(db).delete_sync_task(target_id)
            self._show_sync_tasks(db, chat_id, page=int(ctx.get("page") or 1), message_id=message_id)

    def _dispatch_back(self, db: Session, chat_id: int, message_id: int) -> None:
        session = load_session_data(db, chat_id=chat_id, user_id=self.config.user_id)
        ctx = dict(session.context or {})
        step = str(session.step or "")
        scene = str(session.scene or "")
        if step == "await_field_input":
            kind = str(ctx.get("kind") or "")
            ctx.pop("field", None)
            if kind == "settings":
                save_session_data(
                    db,
                    chat_id=chat_id,
                    user_id=self.config.user_id,
                    scene="settings_domain",
                    step="idle",
                    context={"domain": str(ctx.get("domain") or ""), "page": int(ctx.get("page") or 1)},
                    last_message_id=message_id,
                )
                db.commit()
                self._show_setting_domain(db, chat_id, str(ctx.get("domain") or ""), page=int(ctx.get("page") or 1), message_id=message_id)
                return
            if kind in {"task", "sync", "account"}:
                save_session_data(db, chat_id=chat_id, user_id=self.config.user_id, scene=f"{kind}_editor", step="idle", context=ctx, last_message_id=message_id)
                db.commit()
                self._resume_editor(db, chat_id, kind=kind, ctx=ctx, message_id=message_id)
                return
        if step == "await_keyword" and scene == "search":
            replace_task_id = int(ctx.get("replace_task_id") or 0) or None
            if replace_task_id:
                save_session_data(db, chat_id=chat_id, user_id=self.config.user_id, scene="task_detail", step="idle", context=ctx, last_message_id=message_id)
                db.commit()
                self._show_task_detail(
                    db,
                    chat_id,
                    replace_task_id,
                    message_id=message_id,
                    back_page=int(ctx.get("page") or 1),
                    task_type=str(ctx.get("task_type") or "") or None,
                )
                return
            reset_session(db, chat_id=chat_id, user_id=self.config.user_id, preserve_message_id=False)
            db.commit()
            self._show_home(db, chat_id, message_id=message_id)
            return
        if step == "await_auth_code":
            auth_session_id = str(ctx.get("auth_session_id") or "")
            if auth_session_id:
                info = self._actions(db).get_account_auth_status(auth_session_id)
                self._show_account_auth(db, chat_id, info, message_id=message_id, back_page=int(ctx.get("page") or 1))
                return
        if step == "await_task_tmdb_keyword":
            save_session_data(db, chat_id=chat_id, user_id=self.config.user_id, scene="task_editor", step="idle", context=ctx, last_message_id=message_id)
            db.commit()
            self._resume_editor(db, chat_id, kind="task", ctx=ctx, message_id=message_id)
            return
        self._show_home(db, chat_id, message_id=message_id)

    def _dispatch_share_picker(self, db: Session, chat_id: int, message_id: int, parts: list[str]) -> None:
        session = load_session_data(db, chat_id=chat_id, user_id=self.config.user_id)
        ctx = dict(session.context or {})
        candidates = list(ctx.get("share_candidates") or [])
        text = str(ctx.get("share_text") or "")
        action = parts[0] if parts else "list"
        if action == "pick":
            idx = int(parts[1]) if len(parts) > 1 else -1
            if idx < 0 or idx >= len(candidates):
                raise ValueError("分享链接不存在")
            shareurl = str((candidates[idx] or {}).get("shareurl") or "").strip()
            if not shareurl:
                raise ValueError("分享链接不存在")
            self._apply_share_text(db, chat_id, text, session, selected_shareurl=shareurl)
            return
        self._show_home(db, chat_id, message_id=message_id)

    def _dispatch_task_account_selector(self, db: Session, chat_id: int, message_id: int, parts: list[str]) -> None:
        session = load_session_data(db, chat_id=chat_id, user_id=self.config.user_id)
        ctx = dict(session.context or {})
        draft = dict(ctx.get("draft") or {})
        options = list(ctx.get("account_selector_options") or [])
        action = parts[0] if parts else "back"
        if action == "pick":
            token = str(parts[1] or "") if len(parts) > 1 else ""
            if token == "auto":
                _set_nested(draft, "account_name", "")
            else:
                idx = int(token) if token.isdigit() else -1
                if idx < 0 or idx >= len(options):
                    raise ValueError("账号不存在")
                _set_nested(draft, "account_name", str(options[idx] or ""))
            ctx["draft"] = draft
            ctx.pop("account_selector_options", None)
            save_session_data(db, chat_id=chat_id, user_id=self.config.user_id, scene="task_editor", step="idle", context=ctx, last_message_id=message_id)
            db.commit()
            self._start_editor(
                db,
                chat_id,
                kind="task",
                title=_editor_title("task", int(ctx.get("target_id") or 0) or None),
                fields=TASK_FIELDS,
                draft=draft,
                target_id=int(ctx.get("target_id") or 0) or None,
                message_id=message_id,
                extras={k: v for k, v in ctx.items() if k != "draft"},
            )
            return
        ctx.pop("account_selector_options", None)
        save_session_data(db, chat_id=chat_id, user_id=self.config.user_id, scene="task_editor", step="idle", context=ctx, last_message_id=message_id)
        db.commit()
        self._start_editor(
            db,
            chat_id,
            kind="task",
            title=_editor_title("task", int(ctx.get("target_id") or 0) or None),
            fields=TASK_FIELDS,
            draft=draft,
            target_id=int(ctx.get("target_id") or 0) or None,
            message_id=message_id,
            extras={k: v for k, v in ctx.items() if k != "draft"},
        )

    def _dispatch_task_magic_rule_selector(self, db: Session, chat_id: int, message_id: int, parts: list[str]) -> None:
        session = load_session_data(db, chat_id=chat_id, user_id=self.config.user_id)
        ctx = dict(session.context or {})
        draft = dict(ctx.get("draft") or {})
        rules = list(ctx.get("magic_rule_options") or self._actions(db).list_magic_regex_rules())
        action = parts[0] if parts else "back"
        if action == "list":
            page = int(parts[1]) if len(parts) > 1 and str(parts[1]).isdigit() else 1
            ctx["magic_rule_page"] = page
            save_session_data(db, chat_id=chat_id, user_id=self.config.user_id, context=ctx, last_message_id=message_id)
            db.commit()
            self._show_task_magic_rule_selector(db, chat_id, message_id=message_id)
            return
        if action == "pick":
            idx = int(parts[1]) if len(parts) > 1 and str(parts[1]).isdigit() else -1
            if idx < 0 or idx >= len(rules):
                raise ValueError("内置规则不存在")
            rule = dict(rules[idx] or {})
            _set_nested(draft, "pattern", str(rule.get("pattern") or ""))
            _set_nested(draft, "replace", str(rule.get("replace") or ""))
            _set_nested(draft, "__magic_rule_key__", str(rule.get("key") or ""))
            _set_nested(draft, "__magic_rule_label__", _magic_rule_brief(rule))
            ctx["draft"] = draft
        elif action == "clear":
            _set_nested(draft, "pattern", "")
            _set_nested(draft, "replace", "")
            _set_nested(draft, "__magic_rule_key__", "")
            _set_nested(draft, "__magic_rule_label__", "")
            ctx["draft"] = draft
        ctx.pop("magic_rule_options", None)
        ctx.pop("magic_rule_page", None)
        save_session_data(db, chat_id=chat_id, user_id=self.config.user_id, scene="task_editor", step="idle", context=ctx, last_message_id=message_id)
        db.commit()
        self._resume_task_editor(db, chat_id, ctx=ctx, message_id=message_id)

    def _handle_editor_field_click(
        self,
        db: Session,
        chat_id: int,
        message_id: int,
        *,
        kind: str,
        fields: list[dict[str, Any]],
        target_id: int | None,
        field: str,
    ) -> None:
        session = load_session_data(db, chat_id=chat_id, user_id=self.config.user_id)
        ctx = dict(session.context or {})
        draft = dict(ctx.get("draft") or {})
        if kind == "task" and field == "account_name":
            self._show_task_account_selector(db, chat_id, message_id=message_id)
            return
        if kind == "task" and field == "savepath":
            self._show_task_drive_browser(db, chat_id, message_id=message_id)
            return
        if kind == "task" and field == "__share_folder__":
            self._show_task_share_browser(db, chat_id, picker="folder", message_id=message_id)
            return
        if kind == "task" and field == "__magic_rule__":
            self._show_task_magic_rule_selector(db, chat_id, message_id=message_id)
            return
        if kind == "task" and field == "__tmdb_bind__":
            self._show_task_tmdb_prompt(db, chat_id, message_id=message_id)
            return
        if kind == "task" and field == "startfid":
            self._show_task_share_browser(db, chat_id, picker="startfid", message_id=message_id)
            return
        if kind == "task" and field == "sync_task_uids":
            self._show_task_sync_selector(db, chat_id, message_id=message_id)
            return
        if kind == "sync" and field == "drama_task_uids":
            self._show_sync_drama_selector(db, chat_id, message_id=message_id)
            return
        if kind == "sync" and field in {"source.path", "target.path"}:
            self._show_sync_path_browser(db, chat_id, field=field, message_id=message_id)
            return
        meta = _field_meta(fields, field)
        field_type = meta["type"]
        if field_type == "bool":
            current = bool(_get_nested(draft, field))
            _set_nested(draft, field, not current)
            ctx["draft"] = draft
            save_session_data(db, chat_id=chat_id, user_id=self.config.user_id, context=ctx)
            db.commit()
            self._start_editor(
                db,
                chat_id,
                kind=kind,
                title=_editor_title(kind, target_id),
                fields=fields,
                draft=draft,
                target_id=target_id,
                message_id=message_id,
                extras={k: v for k, v in ctx.items() if k != "draft"},
            )
            return
        if field_type in {"enum", "enum_dynamic"}:
            options = list(meta.get("options") or [])
            if field_type == "enum_dynamic":
                options = list(ctx.get(str(meta.get("options_key") or "")) or [])
            if not options:
                raise ValueError("没有可用选项")
            current = _get_nested(draft, field)
            try:
                idx = options.index(current)
            except ValueError:
                idx = -1
            _set_nested(draft, field, options[(idx + 1) % len(options)])
            ctx["draft"] = draft
            save_session_data(db, chat_id=chat_id, user_id=self.config.user_id, context=ctx)
            db.commit()
            self._start_editor(
                db,
                chat_id,
                kind=kind,
                title=_editor_title(kind, target_id),
                fields=fields,
                draft=draft,
                target_id=target_id,
                message_id=message_id,
                extras={k: v for k, v in ctx.items() if k != "draft"},
            )
            return
        prompt = _field_prompt(meta)
        save_session_data(
            db,
            chat_id=chat_id,
            user_id=self.config.user_id,
            step="await_field_input",
            context={**ctx, "draft": draft, "field": field, "kind": kind, "target_id": target_id or 0},
            last_message_id=message_id,
        )
        db.commit()
        self._show_back_cancel_home(chat_id, prompt, message_id=message_id)

    def _handle_editor_save(self, db: Session, chat_id: int, message_id: int, *, kind: str, fields: list[dict[str, Any]], target_id: int | None) -> None:
        session = load_session_data(db, chat_id=chat_id, user_id=self.config.user_id)
        ctx = dict(session.context or {})
        draft = dict(ctx.get("draft") or {})
        if kind == "task":
            _set_nested(draft, "task_type", "drama")
        payload = _collapse_payload(fields, draft)
        actions = self._actions(db)
        if kind == "task":
            item = actions.save_task(task_id=target_id, payload=payload)
            self._show_task_detail(
                db,
                chat_id,
                int(item["id"]),
                message_id=message_id,
                back_page=int(ctx.get("page") or 1),
                task_type=str(ctx.get("task_type") or "") or None,
            )
            return
        if kind == "sync":
            item = actions.save_sync_task(sync_task_id=target_id, payload=payload)
            self._show_sync_detail(db, chat_id, int(item["id"]), message_id=message_id, back_page=int(ctx.get("page") or 1))
            return
        if kind == "account":
            item = actions.save_account(account_id=target_id, payload=payload)
            self._show_account_detail(db, chat_id, int(item["id"]), message_id=message_id, back_page=int(ctx.get("page") or 1))
            return

    def _handle_field_input(self, db: Session, chat_id: int, user_id: int, text: str, session) -> None:
        ctx = dict(session.context or {})
        field = str(ctx.get("field") or "")
        kind = str(ctx.get("kind") or "")
        if kind == "settings":
            domain = str(ctx.get("domain") or "")
            current_domain = self._actions(db).get_setting_domain(domain)
            current_values = current_domain.get("values") or {}
            current = None
            if domain == "resource_sources":
                source_key, _, source_field = field.partition(".")
                for item in current_values.get("sources") or []:
                    if str(item.get("key") or "") == source_key:
                        current = item.get(source_field)
                        break
            else:
                current = current_values.get(field)
            meta = _setting_field_meta(domain, field, current)
            value = _parse_scalar(text, str(meta.get("type") or "str"))
            self._actions(db).update_setting_value(domain, field, value)
            self._show_setting_domain(db, chat_id, domain, page=int(ctx.get("page") or 1), message_id=session.last_message_id)
            return
        if kind == "auth":
            self._handle_auth_code_input(db, chat_id, text, session)
            return
        target_id = int(ctx.get("target_id") or 0) or None
        draft = dict(ctx.get("draft") or {})
        fields = TASK_FIELDS if kind == "task" else SYNC_FIELDS if kind == "sync" else ACCOUNT_FIELDS
        meta = _field_meta(fields, field)
        try:
            value = _parse_scalar(text, meta["type"])
        except Exception as exc:
            self._send(chat_id, f"输入无效: {exc}")
            return
        _set_nested(draft, field, value)
        if kind == "task" and field == "shareurl":
            draft, _message = self._apply_task_share_autofill(db, draft)
            for key in ("share_root_shareurl", "share_browse_shareurl", "share_browse_stack", "share_dir_items", "share_startfid_items", "share_picker_mode"):
                ctx.pop(key, None)
        if kind == "task" and field in {"pattern", "replace"}:
            if str(_get_nested(draft, "__magic_rule_key__") or "").strip():
                _set_nested(draft, "__magic_rule_key__", "")
                _set_nested(draft, "__magic_rule_label__", "已手动修改")
        ctx["draft"] = draft
        ctx.pop("field", None)
        save_session_data(db, chat_id=chat_id, user_id=user_id, step="idle", context=ctx)
        db.commit()
        self._start_editor(
            db,
            chat_id,
            kind=kind,
            title=_editor_title(kind, target_id),
            fields=fields,
            draft=draft,
            target_id=target_id,
            message_id=session.last_message_id,
            extras={k: v for k, v in ctx.items() if k != "draft"},
        )

    def _handle_auth_code_input(self, db: Session, chat_id: int, text: str, session) -> None:
        ctx = dict(session.context or {})
        auth_session_id = str(ctx.get("auth_session_id") or "")
        if not auth_session_id:
            raise ValueError("认证会话已失效")
        result = self._actions(db).submit_account_auth_code(auth_session_id, text)
        if result.get("done"):
            self._show_account_detail(db, chat_id, int(result["account"]["id"]), message_id=session.last_message_id, back_page=int(ctx.get("page") or 1))
            return
        self._show_account_auth(db, chat_id, result, message_id=session.last_message_id, back_page=int(ctx.get("page") or 1))

    def _handle_settings_field_click(self, db: Session, chat_id: int, message_id: int, domain: str, field: str) -> None:
        session = load_session_data(db, chat_id=chat_id, user_id=self.config.user_id)
        page = int((session.context or {}).get("page") or 1)
        domain_data = self._actions(db).get_setting_domain(domain)
        values = domain_data.get("values") or {}
        if domain == "resource_sources":
            source_key, _, source_field = field.partition(".")
            current = None
            for item in values.get("sources") or []:
                if str(item.get("key") or "") == source_key:
                    current = item.get(source_field)
                    break
        else:
            current = values.get(field)
        meta = _setting_field_meta(domain, field, current)
        if str(meta.get("type") or "") == "bool":
            self._actions(db).update_setting_value(domain, field, not current)
            self._show_setting_domain(db, chat_id, domain, page=page, message_id=message_id)
            return
        save_session_data(
            db,
            chat_id=chat_id,
            user_id=self.config.user_id,
            scene="settings_input",
            step="await_field_input",
            context={"domain": domain, "field": field, "kind": "settings", "page": page},
            last_message_id=message_id,
        )
        db.commit()
        self._show_back_cancel_home(chat_id, _field_prompt(meta), message_id=message_id)

    def _run_async(self, chat_id: int, message_id: int, pending_text: str, job, success_title: str) -> None:
        self._edit_or_send(chat_id, pending_text, message_id=message_id, reply_markup=keyboard([[button("🏠 首页", "home")]]))

        def worker() -> None:
            with SessionLocal() as db:
                try:
                    result = job(db)
                    lines = [success_title, str(result)]
                except Exception as exc:
                    lines = [f"{success_title}失败", str(exc)]
                self._send(chat_id, "\n".join(lines), reply_markup=keyboard([[button("🏠 首页", "home")]]))

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import bad_request, not_found
from app.extensions.runtime.magic_rename import MagicRename
from app.models.magic_regex_rule import MagicRegexRule


def builtin_magic_regex() -> dict[str, dict[str, str]]:
    return dict(MagicRename.magic_regex)


def builtin_magic_regex_labels() -> dict[str, str]:
    return {
        "$TV_REGEX": "剧集集数（SxxExx）",
        "$TV_MAGIC": "通用视频命名",
        "$SHOW_MAGIC": "综艺期数命名",
        "$SHOW_PRO": "综艺期数命名（含日期）",
        "$BLACK_WORD": "黑名单过滤（仅筛选不改名）",
    }


def _validate_regex_pattern(pattern: str) -> None:
    if not pattern:
        return
    try:
        re.compile(pattern)
    except re.error as exc:
        raise bad_request("MAGIC_REGEX_PATTERN_INVALID", f"pattern 正则无效：{exc}") from exc


def get_rule(db: Session, key: str) -> MagicRegexRule | None:
    return db.execute(select(MagicRegexRule).where(MagicRegexRule.key == key)).scalars().first()


def list_rules(db: Session) -> list[dict[str, Any]]:
    builtins = builtin_magic_regex()
    labels = builtin_magic_regex_labels()
    db_rules = db.execute(select(MagicRegexRule).order_by(MagicRegexRule.key.asc())).scalars().all()
    db_by_key = {r.key: r for r in db_rules}

    preferred_order = ["$TV_REGEX", "$TV_MAGIC", "$SHOW_MAGIC", "$SHOW_PRO", "$BLACK_WORD"]
    ordered_keys: list[str] = []
    seen: set[str] = set()
    for key in preferred_order:
        if key in builtins:
            ordered_keys.append(key)
            seen.add(key)
    for key in sorted([k for k in builtins.keys() if k not in seen]):
        ordered_keys.append(key)
        seen.add(key)
    for key in sorted([k for k in db_by_key.keys() if k not in seen]):
        ordered_keys.append(key)
        seen.add(key)

    result: list[dict[str, Any]] = []
    for key in ordered_keys:
        builtin = builtins.get(key)
        row = db_by_key.get(key)
        built_in = builtin is not None
        overridden = bool(row is not None and row.enabled and built_in)
        enabled = True if built_in else bool(row.enabled) if row is not None else False
        label = (row.label if row is not None and (not built_in or row.enabled) else None) or labels.get(key)
        if built_in:
            if row is not None and row.enabled:
                pattern = str(row.pattern or "")
                replace = str(row.replace or "")
            else:
                pattern = str((builtin or {}).get("pattern") or "")
                replace = str((builtin or {}).get("replace") or "")
        else:
            pattern = str((row.pattern if row is not None else None) or "")
            replace = str((row.replace if row is not None else None) or "")
        result.append(
            {
                "key": key,
                "label": label,
                "enabled": enabled,
                "built_in": built_in,
                "overridden": overridden,
                "pattern": pattern,
                "replace": replace,
                "default_pattern": str(((builtin or {}).get("pattern") or "")) if built_in else None,
                "default_replace": str(((builtin or {}).get("replace") or "")) if built_in else None,
            }
        )
    return result


def list_enabled_effective_rules_for_picker(db: Session) -> list[dict[str, str]]:
    items = list_rules(db)
    rules: list[dict[str, str]] = []
    for item in items:
        if not item.get("built_in") and not item.get("enabled"):
            continue
        rules.append(
            {
                "key": str(item["key"]),
                "label": str(item.get("label") or "") or None,
                "pattern": str(item.get("pattern") or ""),
                "replace": str(item.get("replace") or ""),
            }
        )
    return rules


def get_enabled_magic_regex_map(db: Session) -> dict[str, dict[str, str]]:
    rules = list_enabled_effective_rules_for_picker(db)
    return {r["key"]: {"pattern": r["pattern"], "replace": r["replace"]} for r in rules}


def upsert_rule(db: Session, *, key: str, payload: dict[str, Any]) -> MagicRegexRule:
    key = str(key or "").strip()
    if not key.startswith("$"):
        raise bad_request("MAGIC_REGEX_KEY_INVALID", "key 必须以 $ 开头")
    if " " in key:
        raise bad_request("MAGIC_REGEX_KEY_INVALID", "key 不能包含空格")
    if len(key) > 64:
        raise bad_request("MAGIC_REGEX_KEY_INVALID", "key 长度不能超过 64")

    builtins = builtin_magic_regex()
    builtin = builtins.get(key)

    label = payload.get("label")
    enabled = payload.get("enabled")
    pattern = payload.get("pattern")
    replace = payload.get("replace")

    row = get_rule(db, key)
    if row is None:
        if pattern is None:
            if builtin is not None:
                pattern = str(builtin.get("pattern") or "")
            else:
                raise bad_request("MAGIC_REGEX_PATTERN_REQUIRED", "pattern 不能为空")
        if replace is None:
            if builtin is not None:
                replace = str(builtin.get("replace") or "")
            else:
                replace = ""

        pattern = str(pattern)
        replace = str(replace)
        _validate_regex_pattern(pattern)
        row = MagicRegexRule(key=key, label=(str(label) if label is not None else None), pattern=pattern, replace=replace, enabled=bool(True if enabled is None else enabled))
        db.add(row)
        db.flush()
        return row

    if label is not None:
        row.label = str(label) if str(label).strip() else None
    if enabled is not None:
        row.enabled = bool(enabled)
    if payload.get("pattern") is not None:
        pattern = str(pattern or "")
        _validate_regex_pattern(pattern)
        row.pattern = pattern
    if payload.get("replace") is not None:
        row.replace = str(replace or "")
    db.flush()
    return row


def delete_rule(db: Session, *, key: str) -> None:
    row = get_rule(db, key)
    if row is None:
        raise not_found("MAGIC_REGEX_RULE_NOT_FOUND", "规则不存在")
    db.delete(row)
    db.flush()

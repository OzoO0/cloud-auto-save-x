from __future__ import annotations

import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apscheduler.triggers.cron import CronTrigger

from app.core.errors import ApiError


DEFAULT_SCHEDULER_TIMEZONE = "Asia/Shanghai"


def normalize_crontab(value: str | None) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\s+", " ", text)
    return text


def normalize_timezone(value: str | None) -> str:
    text = str(value or "").strip()
    return text or DEFAULT_SCHEDULER_TIMEZONE


def validate_scheduler_setting(crontab: str | None, timezone: str | None) -> tuple[str, str]:
    normalized_crontab = normalize_crontab(crontab)
    if not normalized_crontab:
        raise ApiError(code="SCHEDULER_CRONTAB_INVALID", message="crontab 不能为空", http_status=400)

    parts = normalized_crontab.split(" ")
    if len(parts) != 5:
        raise ApiError(
            code="SCHEDULER_CRONTAB_INVALID",
            message="crontab 必须是 5 段：minute hour day month day_of_week",
            http_status=400,
            detail=normalized_crontab,
        )

    normalized_timezone = normalize_timezone(timezone)
    try:
        tzinfo = ZoneInfo(normalized_timezone)
    except ZoneInfoNotFoundError as exc:
        raise ApiError(
            code="SCHEDULER_TIMEZONE_INVALID",
            message=f"timezone 无效：{normalized_timezone}",
            http_status=400,
            detail=str(exc),
        )

    try:
        CronTrigger.from_crontab(normalized_crontab, timezone=tzinfo)
    except Exception as exc:
        raise ApiError(
            code="SCHEDULER_CRONTAB_INVALID",
            message=f"crontab 无效：{normalized_crontab}",
            http_status=400,
            detail=str(exc),
        )

    return normalized_crontab, normalized_timezone

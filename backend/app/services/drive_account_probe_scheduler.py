from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.drive_account_probe_scheduler_setting import DriveAccountProbeSchedulerSetting
from app.services.scheduler_validation import validate_scheduler_setting


DEFAULT_DRIVE_ACCOUNT_PROBE_SCHEDULER_SETTING_ID = 1


def get_or_create_drive_account_probe_scheduler_setting(db: Session) -> DriveAccountProbeSchedulerSetting:
    item = db.get(DriveAccountProbeSchedulerSetting, DEFAULT_DRIVE_ACCOUNT_PROBE_SCHEDULER_SETTING_ID)
    if item is not None:
        return item
    item = DriveAccountProbeSchedulerSetting(id=DEFAULT_DRIVE_ACCOUNT_PROBE_SCHEDULER_SETTING_ID)
    db.add(item)
    db.flush()
    return item


def update_drive_account_probe_scheduler_setting(
    db: Session,
    *,
    enabled: bool | None = None,
    crontab: str | None = None,
    timezone: str | None = None,
    enabled_only: bool | None = None,
) -> DriveAccountProbeSchedulerSetting:
    item = get_or_create_drive_account_probe_scheduler_setting(db)
    next_crontab = crontab if crontab is not None else getattr(item, "crontab", None)
    next_timezone = timezone if timezone is not None else getattr(item, "timezone", None)
    normalized_crontab, normalized_timezone = validate_scheduler_setting(next_crontab, next_timezone)
    if enabled is not None:
        item.enabled = enabled
    item.crontab = normalized_crontab
    item.timezone = normalized_timezone
    if enabled_only is not None:
        item.enabled_only = enabled_only
    db.flush()
    return item

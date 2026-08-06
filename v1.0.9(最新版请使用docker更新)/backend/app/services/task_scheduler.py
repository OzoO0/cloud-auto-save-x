from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.task_scheduler_setting import TaskSchedulerSetting
from app.services.scheduler_validation import validate_scheduler_setting


DEFAULT_TASK_SCHEDULER_SETTING_ID = 1


def get_or_create_task_scheduler_setting(db: Session) -> TaskSchedulerSetting:
    setting = (
        db.execute(select(TaskSchedulerSetting).where(TaskSchedulerSetting.id == DEFAULT_TASK_SCHEDULER_SETTING_ID))
        .scalars()
        .first()
    )
    if setting is not None:
        return setting
    setting = TaskSchedulerSetting(id=DEFAULT_TASK_SCHEDULER_SETTING_ID)
    db.add(setting)
    db.flush()
    return setting


def update_task_scheduler_setting(db: Session, *, enabled: bool | None = None, crontab: str | None = None, timezone: str | None = None) -> TaskSchedulerSetting:
    setting = get_or_create_task_scheduler_setting(db)
    next_crontab = crontab if crontab is not None else getattr(setting, "crontab", None)
    next_timezone = timezone if timezone is not None else getattr(setting, "timezone", None)
    normalized_crontab, normalized_timezone = validate_scheduler_setting(next_crontab, next_timezone)
    if enabled is not None:
        setting.enabled = enabled
    setting.crontab = normalized_crontab
    setting.timezone = normalized_timezone
    db.flush()
    return setting

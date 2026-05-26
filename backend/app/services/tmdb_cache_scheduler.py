from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.tmdb_cache_scheduler_setting import TMDBCacheSchedulerSetting
from app.services.scheduler_validation import validate_scheduler_setting


DEFAULT_TMDB_CACHE_SCHEDULER_SETTING_ID = 1


def get_or_create_tmdb_cache_scheduler_setting(db: Session) -> TMDBCacheSchedulerSetting:
    item = db.get(TMDBCacheSchedulerSetting, DEFAULT_TMDB_CACHE_SCHEDULER_SETTING_ID)
    if item is not None:
        return item
    item = TMDBCacheSchedulerSetting(id=DEFAULT_TMDB_CACHE_SCHEDULER_SETTING_ID)
    db.add(item)
    db.flush()
    return item


def update_tmdb_cache_scheduler_setting(
    db: Session,
    *,
    enabled: bool | None = None,
    crontab: str | None = None,
    timezone: str | None = None,
    max_items_per_run: int | None = None,
    only_refresh_linked_tasks: bool | None = None,
    retention_days: int | None = None,
) -> TMDBCacheSchedulerSetting:
    item = get_or_create_tmdb_cache_scheduler_setting(db)
    next_crontab = crontab if crontab is not None else getattr(item, "crontab", None)
    next_timezone = timezone if timezone is not None else getattr(item, "timezone", None)
    normalized_crontab, normalized_timezone = validate_scheduler_setting(next_crontab, next_timezone)
    if enabled is not None:
        item.enabled = enabled
    item.crontab = normalized_crontab
    item.timezone = normalized_timezone
    if max_items_per_run is not None:
        item.max_items_per_run = max(1, int(max_items_per_run))
    if only_refresh_linked_tasks is not None:
        item.only_refresh_linked_tasks = only_refresh_linked_tasks
    if retention_days is not None:
        item.retention_days = max(1, int(retention_days))
    db.flush()
    return item

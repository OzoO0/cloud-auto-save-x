from __future__ import annotations

import os
import logging
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from app.core.settings import settings
from app.db.session import SessionLocal
from app.models.task import Task
from app.services.notifications.sender import send_runtime
from app.services.notifications.task_notify import DRAMA_NOTIFY_TITLE, build_task_section
from app.services.task_scheduler import get_or_create_task_scheduler_setting
from app.services.drama_share_repair import repair_banned_drama_tasks
from app.services.tmdb_cache import purge_cold_cache, refresh_expired_cache, refresh_linked_tasks
from app.services.tmdb_cache_scheduler import get_or_create_tmdb_cache_scheduler_setting
from app.services.drive_account_probe_scheduler import get_or_create_drive_account_probe_scheduler_setting
from app.services.drive_accounts import probe_drive_account, sign_in_drive_account
from app.services.sync_execution_cleanup import purge_old_sync_executions
from app.services.sync_execution_recovery import abort_stale_running_sync_executions
from app.services.sync_task_triggers import should_trigger_linked_sync_for_drama_execution, trigger_linked_sync_tasks_async
from app.models.drive_account import DriveAccount
from app.extensions.runtime.task_executor import TaskExecutor
from app.core.errors import ApiError


class TaskSchedulerManager:
    def __init__(self):
        self.scheduler: BackgroundScheduler | None = None

    def start(self) -> None:
        if settings.environment == "test" or os.environ.get("PYTEST_CURRENT_TEST"):
            return
        if self.scheduler is not None:
            return
        self.scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
        self.scheduler.start()
        self.reload()
        try:
            self.scheduler.add_job(
                run_sync_execution_recovery,
                trigger=CronTrigger(minute="*/10", timezone="Asia/Shanghai"),
                id="sync_execution_recovery",
                replace_existing=True,
                max_instances=1,
                coalesce=True,
                misfire_grace_time=60,
            )
        except Exception as e:
            logging.error(f"同步执行兜底调度加载失败: {e}")

    def shutdown(self) -> None:
        if self.scheduler is None:
            return
        self.scheduler.shutdown(wait=False)
        self.scheduler = None

    def reload(self) -> None:
        if self.scheduler is None:
            return
        with SessionLocal() as db:
            try:
                setting = get_or_create_task_scheduler_setting(db)
                db.commit()
                db.refresh(setting)
                self._apply_setting(setting)
            except OperationalError as e:
                logging.error(f"任务调度配置加载失败: {e}")
                return
            except Exception as e:
                logging.error(f"任务调度配置应用失败: {e}")

            try:
                tmdb_cache_setting = get_or_create_tmdb_cache_scheduler_setting(db)
                db.commit()
                db.refresh(tmdb_cache_setting)
                self._apply_tmdb_cache_setting(tmdb_cache_setting)
            except OperationalError as e:
                logging.error(f"TMDB 缓存调度配置加载失败: {e}")
                return
            except Exception as e:
                logging.error(f"TMDB 缓存调度配置应用失败: {e}")

            try:
                drive_probe_setting = get_or_create_drive_account_probe_scheduler_setting(db)
                db.commit()
                db.refresh(drive_probe_setting)
                self._apply_drive_account_probe_setting(drive_probe_setting)
            except OperationalError as e:
                logging.error(f"驱动账号探测调度配置加载失败: {e}")
                return
            except Exception as e:
                logging.error(f"驱动账号探测调度配置应用失败: {e}")

    def _apply_setting(self, setting: Any) -> None:
        if self.scheduler is None:
            return
        job_id = "drama_tasks"
        if not bool(setting.enabled):
            if self.scheduler.get_job(job_id):
                self.scheduler.remove_job(job_id)
            return
        try:
            trigger = CronTrigger.from_crontab(str(setting.crontab), timezone=str(setting.timezone or "Asia/Shanghai"))
            self.scheduler.add_job(
                run_drama_tasks,
                trigger=trigger,
                id=job_id,
                replace_existing=True,
                max_instances=1,
                coalesce=True,
                misfire_grace_time=60,
            )
        except Exception as e:
            logging.error(f"任务调度 crontab 无效 job_id={job_id} crontab={getattr(setting, 'crontab', '')}: {e}")
            if self.scheduler.get_job(job_id):
                self.scheduler.remove_job(job_id)
            return

    def _apply_tmdb_cache_setting(self, setting: Any) -> None:
        if self.scheduler is None:
            return
        job_id = "tmdb_cache_refresh"
        if not bool(getattr(setting, "enabled", False)):
            if self.scheduler.get_job(job_id):
                self.scheduler.remove_job(job_id)
                logging.info("已移除 TMDB 缓存定时刷新调度")
            return
        try:
            trigger = CronTrigger.from_crontab(str(setting.crontab), timezone=str(setting.timezone or "Asia/Shanghai"))
            self.scheduler.add_job(
                run_tmdb_cache_refresh,
                trigger=trigger,
                id=job_id,
                replace_existing=True,
                max_instances=1,
                coalesce=True,
                misfire_grace_time=60,
            )
        except Exception as e:
            logging.error(f"TMDB 缓存调度 crontab 无效 job_id={job_id} crontab={getattr(setting, 'crontab', '')}: {e}")
            if self.scheduler.get_job(job_id):
                self.scheduler.remove_job(job_id)
            return
        job = self.scheduler.get_job(job_id)
        logging.info(
            "已加载 TMDB 缓存定时刷新调度 only_refresh_linked_tasks=%s max_items_per_run=%s crontab=%s timezone=%s next_run=%s",
            bool(getattr(setting, "only_refresh_linked_tasks", True)),
            int(getattr(setting, "max_items_per_run", 200) or 200),
            str(getattr(setting, "crontab", "")),
            str(getattr(setting, "timezone", "")),
            getattr(job, "next_run_time", None),
        )


    def _apply_drive_account_probe_setting(self, setting: Any) -> None:
        if self.scheduler is None:
            return
        job_id = "drive_account_probe"
        if not bool(getattr(setting, "enabled", False)):
            if self.scheduler.get_job(job_id):
                self.scheduler.remove_job(job_id)
                logging.info("已移除驱动账号探测调度")
            return
        try:
            trigger = CronTrigger.from_crontab(str(setting.crontab), timezone=str(setting.timezone or "Asia/Shanghai"))
            self.scheduler.add_job(
                run_drive_account_probe,
                trigger=trigger,
                id=job_id,
                replace_existing=True,
                max_instances=1,
                coalesce=True,
                misfire_grace_time=60,
            )
        except Exception as e:
            logging.error(f"驱动账号探测调度 crontab 无效 job_id={job_id} crontab={getattr(setting, 'crontab', '')}: {e}")
            if self.scheduler.get_job(job_id):
                self.scheduler.remove_job(job_id)
            return
        job = self.scheduler.get_job(job_id)
        logging.info(
            "已加载驱动账号探测调度 enabled_only=%s crontab=%s timezone=%s next_run=%s",
            bool(getattr(setting, "enabled_only", True)),
            str(getattr(setting, "crontab", "")),
            str(getattr(setting, "timezone", "")),
            getattr(job, "next_run_time", None),
        )


def run_drama_tasks() -> None:
    with SessionLocal() as db:
        tasks = (
            db.execute(select(Task).where(Task.enabled.is_(True), Task.task_type == "drama").order_by(Task.id.asc()))
            .scalars()
            .all()
        )
        executor = TaskExecutor(db)
        pairs: list[tuple[Task, object]] = []
        for task in tasks:
            execution = executor.run_task(task)
            pairs.append((task, execution))
        db.commit()
        sections: list[str] = []
        for task, execution in pairs:
            try:
                section, should_notify = build_task_section(task, execution)
                if should_notify and section:
                    sections.append(section)
            except Exception:
                continue
        if sections:
            try:
                send_runtime(db, DRAMA_NOTIFY_TITLE, "\n\n".join(sections))
            except Exception:
                pass
        try:
            repair_banned_drama_tasks(db)
        except Exception:
            db.rollback()
        success_task_uids: list[str] = []
        for task, execution in pairs:
            if should_trigger_linked_sync_for_drama_execution(execution):
                uid = str(getattr(task, "task_uid", "") or "").strip()
                if uid:
                    success_task_uids.append(uid)
        if success_task_uids:
            trigger_linked_sync_tasks_async(success_task_uids, source="scheduler.run_drama_tasks")


def run_sync_execution_recovery() -> None:
    with SessionLocal() as db:
        try:
            n = abort_stale_running_sync_executions(db, threshold_seconds=2 * 60 * 60)
            cleanup = purge_old_sync_executions(db, keep_per_task=3)
            if n or int(cleanup.get("deleted_executions") or 0) or int(cleanup.get("deleted_files") or 0):
                db.commit()
                if cleanup.get("deleted_executions") or cleanup.get("deleted_files"):
                    logging.info(
                        "同步执行历史清理完成 sync_tasks=%s deleted_executions=%s deleted_files=%s",
                        int(cleanup.get("sync_tasks") or 0),
                        int(cleanup.get("deleted_executions") or 0),
                        int(cleanup.get("deleted_files") or 0),
                    )
            else:
                db.rollback()
        except OperationalError as e:
            logging.error(f"同步执行兜底调度失败: {e}")
            db.rollback()
        except Exception as e:
            logging.error(f"同步执行兜底调度异常: {e}")
            db.rollback()


def run_tmdb_cache_refresh() -> None:
    with SessionLocal() as db:
        setting = get_or_create_tmdb_cache_scheduler_setting(db)
        db.commit()
        db.refresh(setting)

        max_items = int(getattr(setting, "max_items_per_run", 200) or 200)
        only_linked = bool(getattr(setting, "only_refresh_linked_tasks", True))
        retention_days = int(getattr(setting, "retention_days", 60) or 60)

        try:
            if only_linked:
                result = refresh_linked_tasks(db, enabled_only=True, max_items=max_items, force=True)
            else:
                result = refresh_expired_cache(db, max_items=max_items, force=True)
            deleted = purge_cold_cache(db, retention_days=retention_days)
            db.commit()
            logging.info(
                "TMDB 缓存定时刷新执行完成 only_refresh_linked_tasks=%s max_items_per_run=%s refreshed=%s targets=%s configured=%s purged=%s",
                only_linked,
                max_items,
                int(result.get("refreshed") or 0),
                int(result.get("targets") or 0),
                int(result.get("configured") or 0),
                int(deleted),
            )
        except Exception as e:
            db.rollback()
            logging.warning(
                "TMDB 缓存定时刷新执行失败 only_refresh_linked_tasks=%s max_items_per_run=%s retention_days=%s err=%s",
                only_linked,
                max_items,
                retention_days,
                str(e),
            )


def run_drive_account_probe() -> None:
    with SessionLocal() as db:
        setting = get_or_create_drive_account_probe_scheduler_setting(db)
        db.commit()
        db.refresh(setting)
        enabled_only = bool(getattr(setting, "enabled_only", True))
        accounts = (
            db.execute(select(DriveAccount).order_by(DriveAccount.is_default.desc(), DriveAccount.id.asc()))
            .scalars()
            .all()
        )
        logging.info("开始执行驱动账号自动探测 enabled_only=%s accounts=%s", enabled_only, len(accounts))
        ok = 0
        skipped = 0
        failed = 0
        for account in accounts:
            if enabled_only and not bool(getattr(account, "enabled", False)):
                skipped += 1
                continue
            try:
                probed = probe_drive_account(db, int(account.id))
                ok += 1
                if getattr(probed, "runtime_status", None) != "active":
                    continue
                try:
                    sign_in_drive_account(db, int(account.id))
                except ApiError as exc:
                    if exc.code in {"DRIVE_SIGNIN_UNSUPPORTED"}:
                        logging.info("驱动账号自动签到不支持 account_id=%s", getattr(account, "id", None))
                    else:
                        logging.warning(
                            "驱动账号自动签到失败 account_id=%s code=%s msg=%s",
                            getattr(account, "id", None),
                            exc.code,
                            exc.message,
                        )
                except Exception as exc:
                    logging.warning("驱动账号自动签到异常 account_id=%s err=%s", getattr(account, "id", None), str(exc))
            except Exception as exc:
                failed += 1
                try:
                    account.runtime_status = "inactive"
                    account.last_error = str(exc)
                except Exception:
                    pass
                logging.warning("驱动账号自动探测失败 account_id=%s err=%s", getattr(account, "id", None), str(exc))
                continue
        db.commit()
        logging.info("驱动账号自动探测完成 ok=%s skipped=%s failed=%s", ok, skipped, failed)


task_scheduler_manager = TaskSchedulerManager()

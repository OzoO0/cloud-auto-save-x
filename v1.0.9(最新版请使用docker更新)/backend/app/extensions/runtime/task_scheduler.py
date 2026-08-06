from __future__ import annotations

import os
import time
import logging
import json
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
from app.extensions.runtime.account_manager import DatabaseAccountManager
from app.extensions.runtime.task_executor import TaskExecutor
from app.extensions.runtime.plugin_loader import sync_plugin_definitions
from app.extensions.runtime.plugin_registry import PluginRegistry
from app.core.errors import ApiError


logger = logging.getLogger(__name__)


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
            logger.error(f"同步执行兜底调度加载失败: {e}")

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
                logger.error(f"任务调度配置加载失败: {e}")
                return
            except Exception as e:
                logger.error(f"任务调度配置应用失败: {e}")

            try:
                tmdb_cache_setting = get_or_create_tmdb_cache_scheduler_setting(db)
                db.commit()
                db.refresh(tmdb_cache_setting)
                self._apply_tmdb_cache_setting(tmdb_cache_setting)
            except OperationalError as e:
                logger.error(f"TMDB 缓存调度配置加载失败: {e}")
                return
            except Exception as e:
                logger.error(f"TMDB 缓存调度配置应用失败: {e}")

            try:
                drive_probe_setting = get_or_create_drive_account_probe_scheduler_setting(db)
                db.commit()
                db.refresh(drive_probe_setting)
                self._apply_drive_account_probe_setting(drive_probe_setting)
            except OperationalError as e:
                logger.error(f"驱动账号探测调度配置加载失败: {e}")
                return
            except Exception as e:
                logger.error(f"驱动账号探测调度配置应用失败: {e}")

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
            logger.error(f"任务调度 crontab 无效 job_id={job_id} crontab={getattr(setting, 'crontab', '')}: {e}")
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
                logger.info("已移除 TMDB 缓存定时刷新调度")
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
            logger.error(f"TMDB 缓存调度 crontab 无效 job_id={job_id} crontab={getattr(setting, 'crontab', '')}: {e}")
            if self.scheduler.get_job(job_id):
                self.scheduler.remove_job(job_id)
            return
        job = self.scheduler.get_job(job_id)
        logger.info(
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
                logger.info("已移除驱动账号探测调度")
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
            logger.error(f"驱动账号探测调度 crontab 无效 job_id={job_id} crontab={getattr(setting, 'crontab', '')}: {e}")
            if self.scheduler.get_job(job_id):
                self.scheduler.remove_job(job_id)
            return
        job = self.scheduler.get_job(job_id)
        logger.info(
            "已加载驱动账号探测调度 enabled_only=%s crontab=%s timezone=%s next_run=%s",
            bool(getattr(setting, "enabled_only", True)),
            str(getattr(setting, "crontab", "")),
            str(getattr(setting, "timezone", "")),
            getattr(job, "next_run_time", None),
        )


def run_drama_tasks() -> None:
    task_ids: list[int] = []
    task_payloads: list[dict[str, Any]] = []
    with SessionLocal() as db:
        try:
            from app.extensions.runtime.plugin_loader import sync_plugin_definitions

            sync_plugin_definitions(db)
            db.commit()
        except Exception:
            db.rollback()
        rows = (
            db.execute(select(Task.id, Task.task_uid, Task.account_name, Task.shareurl).where(Task.enabled.is_(True), Task.task_type == "drama").order_by(Task.id.asc()))
            .all()
        )
        for tid, uid, account_name, shareurl in rows:
            if tid is None:
                continue
            task_ids.append(int(tid))
            task_payloads.append({"task_uid": uid, "account_name": account_name, "shareurl": shareurl})

    account_manager = None
    if task_payloads:
        try:
            with SessionLocal() as adb:
                account_manager = DatabaseAccountManager(adb)
            if account_manager is not None:
                account_manager.init_for_tasks(task_payloads)
        except Exception:
            account_manager = None

    sections: list[str] = []
    success_task_uids: list[str] = []
    plugin_candidates: list[object] = []

    for task_id in task_ids:
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            with SessionLocal() as db:
                try:
                    task = db.get(Task, int(task_id))
                    if task is None:
                        break
                    executor = TaskExecutor(db)
                    execution = executor.run_task(
                        task,
                        account_manager=account_manager,
                        init_account_for_task=False,
                        defer_plugins=True,
                        keep_runtime_tree=True,
                    )
                    should_notify = False
                    try:
                        section, should_notify = build_task_section(task, execution)
                        if should_notify and section:
                            sections.append(section)
                    except Exception:
                        pass
                    try:
                        if should_trigger_linked_sync_for_drama_execution(execution):
                            uid = str(getattr(task, "task_uid", "") or "").strip()
                            if uid:
                                success_task_uids.append(uid)
                    except Exception:
                        pass
                    try:
                        if getattr(execution, "status", None) == "success" and bool(getattr(execution, "_has_new_files", False)):
                            plugin_candidates.append(execution)
                    except Exception:
                        pass
                    db.commit()
                    break
                except OperationalError as exc:
                    db.rollback()
                    if attempt < max_attempts and "database is locked" in str(exc).lower():
                        time.sleep(0.2 * attempt)
                        continue
                    logger.warning("追剧任务调度执行异常 task_id=%s err=%s", task_id, str(exc))
                    break
                except Exception as exc:
                    db.rollback()
                    logger.warning("追剧任务调度执行失败 task_id=%s err=%s", task_id, str(exc))
                    break

    with SessionLocal() as db:
        if sections:
            try:
                send_runtime(db, DRAMA_NOTIFY_TITLE, "\n\n".join(sections))
                db.commit()
            except Exception:
                db.rollback()
        try:
            repair_banned_drama_tasks(db)
            db.commit()
        except Exception:
            db.rollback()
    if success_task_uids:
        trigger_linked_sync_tasks_async(success_task_uids, source="scheduler.run_drama_tasks")
    plugin_candidates_count = len(plugin_candidates)
    logger.info(
        "追剧任务调度后置插件阶段: 候选任务数=%d success_task_uids=%s",
        plugin_candidates_count,
        success_task_uids,
    )
    if not plugin_candidates:
        return
    try:
        with SessionLocal() as pdb:
            try:
                logger.debug("追剧调度后置插件: 同步插件定义")
                sync_plugin_definitions(pdb)
                pdb.commit()
                logger.debug("追剧调度后置插件: 插件定义同步完成")
            except Exception:
                pdb.rollback()
                logger.exception("追剧调度后置插件: 插件定义同步失败")
            try:
                plugins = PluginRegistry(pdb).load_active_plugins()
                logger.info(
                    "追剧调度后置插件: 加载到插件数=%d",
                    len(plugins),
                )
                pdb.rollback()
            except Exception:
                plugins = []
                logger.exception("追剧调度后置插件: 加载插件失败")
    except Exception:
        plugins = []
        logger.exception("追剧调度后置插件: 创建插件注册表失败")
    if not plugins:
        logger.warning("追剧调度后置插件: 无可用插件（可能尚未安装或全部禁用）")
        return
    deduped: dict[str, tuple[object, dict[str, Any], object, object]] = {}
    for item in plugins:
        plugin = item.get("instance")
        definition = item.get("definition")
        plugin_key = str(getattr(plugin, "plugin_name", "") or getattr(definition, "plugin_key", "") or "").strip()
        if not bool(getattr(plugin, "is_active", False)):
            logger.debug("追剧调度后置插件: 跳过（is_active=false） plugin=%s", plugin_key)
            continue
        if not hasattr(plugin, "run"):
            logger.debug("追剧调度后置插件: 跳过（缺少 run 方法） plugin=%s", plugin_key)
            continue
        if not plugin_key:
            continue
        base_task_cfg = getattr(plugin, "default_task_config", None)
        if not isinstance(base_task_cfg, dict):
            base_task_cfg = {}
        for execution in plugin_candidates:
            task_data = getattr(execution, "_runtime_task_data", None)
            adapter = getattr(execution, "_runtime_adapter", None)
            tree = getattr(execution, "_runtime_tree", None)
            if not isinstance(task_data, dict) or adapter is None or tree is None:
                logger.debug("追剧调度后置插件: 跳过（执行结果缺少必要数据） plugin=%s", plugin_key)
                continue
            merged_cfg = dict(base_task_cfg)
            addition_cfg = (task_data.get("addition") or {}).get(plugin_key)
            if isinstance(addition_cfg, dict):
                merged_cfg.update(addition_cfg)
            cfg_key = json.dumps(merged_cfg, ensure_ascii=False, sort_keys=True)
            context_key = json.dumps(
                {
                    "taskname": str(task_data.get("taskname") or ""),
                    "savepath": str(task_data.get("savepath") or ""),
                    "task_type": str(task_data.get("task_type") or ""),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            account_key = f"{str(getattr(adapter, 'DRIVE_TYPE', '') or '')}:{str(getattr(adapter, 'account_name', '') or '')}"
            dedupe_key = f"{plugin_key}|{account_key}|{cfg_key}|{context_key}"
            if dedupe_key not in deduped:
                deduped[dedupe_key] = (plugin, task_data, adapter, tree)
    logger.info(
        "追剧调度后置插件: 去重后待执行插件任务数=%d",
        len(deduped),
    )
    for _k, payload in deduped.items():
        plugin, task_data, adapter, tree = payload
        plugin_key = str(getattr(plugin, "plugin_name", "") or getattr(plugin, "__class__", type(plugin)).__name__ or "").strip()
        try:
            logger.info("追剧调度后置插件: 执行 plugin=%s taskname=%s", plugin_key, str(task_data.get("taskname") or ""))
            plugin.run(task_data, account=adapter, tree=tree)
            logger.info("追剧调度后置插件: 成功 plugin=%s", plugin_key)
        except Exception:
            logger.exception("追剧调度后置插件: 执行失败 plugin=%s", plugin_key)


def run_sync_execution_recovery() -> None:
    with SessionLocal() as db:
        try:
            n = abort_stale_running_sync_executions(db, threshold_seconds=2 * 60 * 60)
            cleanup = purge_old_sync_executions(db, keep_per_task=3)
            if n or int(cleanup.get("deleted_executions") or 0) or int(cleanup.get("deleted_files") or 0):
                db.commit()
                if cleanup.get("deleted_executions") or cleanup.get("deleted_files"):
                    logger.info(
                        "同步执行历史清理完成 sync_tasks=%s deleted_executions=%s deleted_files=%s",
                        int(cleanup.get("sync_tasks") or 0),
                        int(cleanup.get("deleted_executions") or 0),
                        int(cleanup.get("deleted_files") or 0),
                    )
            else:
                db.rollback()
        except OperationalError as e:
            logger.error(f"同步执行兜底调度失败: {e}")
            db.rollback()
        except Exception as e:
            logger.error(f"同步执行兜底调度异常: {e}")
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
            logger.info(
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
            logger.warning(
                "TMDB 缓存定时刷新执行失败 only_refresh_linked_tasks=%s max_items_per_run=%s retention_days=%s err=%s",
                only_linked,
                max_items,
                retention_days,
                str(e),
            )


def run_drive_account_probe() -> None:
    def _is_sqlite_locked(exc: Exception) -> bool:
        if not isinstance(exc, OperationalError):
            return False
        return "database is locked" in str(exc).lower()

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
        account_ids = []
        skipped = 0
        for account in accounts:
            if enabled_only and not bool(getattr(account, "enabled", False)):
                skipped += 1
                continue
            account_id = int(getattr(account, "id", 0) or 0)
            if account_id > 0:
                account_ids.append(account_id)

    logger.info("开始执行驱动账号自动探测 enabled_only=%s accounts=%s", enabled_only, len(account_ids) + skipped)
    ok = 0
    failed = 0

    for account_id in account_ids:
        probed_status: str | None = None
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            with SessionLocal() as db:
                try:
                    account = db.get(DriveAccount, account_id)
                    prev_status = getattr(account, "runtime_status", None) if account is not None else None
                    prev_enabled = bool(getattr(account, "enabled", True)) if account is not None else True
                    probed = probe_drive_account(db, account_id)
                    new_status = getattr(probed, "runtime_status", None)
                    new_enabled = bool(getattr(probed, "enabled", True))
                    last_error = str(getattr(probed, "last_error", "") or "").strip()
                    notify_content = None
                    if (prev_enabled and not new_enabled) or (
                        prev_status == "active" and new_status in {"inactive", "error"} and new_status != prev_status
                    ):
                        lines = [
                            "驱动账号状态异常",
                            "触发: 自动探测",
                            f"账号: {getattr(probed, 'name', '')} (id={account_id})",
                            f"类型: {getattr(probed, 'drive_type', '')}",
                            f"状态: {prev_status or '-'} -> {new_status or '-'}",
                            f"启用: {prev_enabled} -> {new_enabled}",
                        ]
                        if last_error:
                            lines.append(f"错误: {last_error}")
                        notify_content = "\n".join(lines)
                    db.commit()
                    if notify_content:
                        send_runtime(db, DRAMA_NOTIFY_TITLE, notify_content)
                    probed_status = str(new_status or "").strip() or None
                    ok += 1
                    break
                except OperationalError as exc:
                    db.rollback()
                    if attempt < max_attempts and _is_sqlite_locked(exc):
                        time.sleep(0.2 * attempt)
                        continue
                    logger.warning("驱动账号自动探测异常 account_id=%s err=%s", account_id, str(exc))
                    failed += 1
                    break
                except Exception as exc:
                    db.rollback()
                    try:
                        account = db.get(DriveAccount, account_id)
                        prev_status = getattr(account, "runtime_status", None) if account is not None else None
                        prev_enabled = bool(getattr(account, "enabled", True)) if account is not None else True
                        if account is not None:
                            account.runtime_status = "inactive"
                            account.last_error = str(exc)
                            db.commit()
                            if prev_enabled or prev_status == "active":
                                lines = [
                                    "驱动账号状态异常",
                                    "触发: 自动探测",
                                    f"账号: {getattr(account, 'name', '')} (id={account_id})",
                                    f"类型: {getattr(account, 'drive_type', '')}",
                                    f"状态: {prev_status or '-'} -> inactive",
                                    f"启用: {prev_enabled} -> {bool(getattr(account, 'enabled', True))}",
                                    f"错误: {str(exc)}",
                                ]
                                send_runtime(db, DRAMA_NOTIFY_TITLE, "\n".join(lines))
                    except Exception:
                        db.rollback()
                    logger.warning("驱动账号自动探测失败 account_id=%s err=%s", account_id, str(exc))
                    failed += 1
                    break

        if probed_status != "active":
            continue

        max_signin_attempts = 3
        for attempt in range(1, max_signin_attempts + 1):
            with SessionLocal() as sdb:
                try:
                    sign_in_drive_account(sdb, account_id)
                    sdb.commit()
                    break
                except ApiError as exc:
                    sdb.rollback()
                    if exc.code in {"DRIVE_SIGNIN_UNSUPPORTED"}:
                        logger.info("驱动账号自动签到不支持 account_id=%s", account_id)
                    else:
                        logger.warning(
                            "驱动账号自动签到失败 account_id=%s code=%s msg=%s",
                            account_id,
                            exc.code,
                            exc.message,
                        )
                    break
                except OperationalError as exc:
                    sdb.rollback()
                    if attempt < max_signin_attempts and _is_sqlite_locked(exc):
                        time.sleep(0.2 * attempt)
                        continue
                    logger.warning("驱动账号自动签到异常 account_id=%s err=%s", account_id, str(exc))
                    break
                except Exception as exc:
                    sdb.rollback()
                    logger.warning("驱动账号自动签到异常 account_id=%s err=%s", account_id, str(exc))
                    break

    logger.info("驱动账号自动探测完成 ok=%s skipped=%s failed=%s", ok, skipped, failed)


task_scheduler_manager = TaskSchedulerManager()

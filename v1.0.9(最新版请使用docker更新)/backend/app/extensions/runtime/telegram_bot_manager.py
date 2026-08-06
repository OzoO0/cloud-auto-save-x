from __future__ import annotations

import logging
import threading
import time

from sqlalchemy.exc import OperationalError

from app.db.session import SessionLocal, is_sqlite_locked_error
from app.services.telegram_bot.client import TelegramBotClient
from app.services.telegram_bot.config import TelegramBotConfig, load_telegram_bot_config
from app.services.telegram_bot.handlers import TelegramBotHandler
from app.services.telegram_bot.session_store import get_last_update_id, mark_poll_error, mark_polled, save_last_update_id


logger = logging.getLogger(__name__)


def _commit_with_retry(db, *, attempts: int = 3, base_delay: float = 0.2) -> None:
    for attempt in range(1, attempts + 1):
        try:
            db.commit()
            return
        except OperationalError as exc:
            db.rollback()
            if attempt < attempts and is_sqlite_locked_error(exc):
                time.sleep(base_delay * attempt)
                continue
            raise


class TelegramBotManager:
    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._config_signature: tuple[str, int, str, str, str, str] | None = None
        self._client: TelegramBotClient | None = None
        self._handler: TelegramBotHandler | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="telegram-bot-manager", daemon=True)
        self._thread.start()

    def shutdown(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

    def _load_runtime(self) -> tuple[TelegramBotConfig | None, TelegramBotClient | None, TelegramBotHandler | None]:
        with SessionLocal() as db:
            config = load_telegram_bot_config(db)
        if not config.enabled:
            return None, None, None
        signature = (
            config.token,
            config.user_id,
            config.api_host,
            config.proxy_host,
            config.proxy_port,
            config.proxy_auth,
        )
        if signature != self._config_signature or self._client is None or self._handler is None:
            self._client = TelegramBotClient(config)
            self._handler = TelegramBotHandler(client=self._client, config=config)
            self._config_signature = signature
            try:
                self._client.set_my_commands(
                    [
                        {"command": "start", "description": "启动控制台"},
                        {"command": "menu", "description": "主菜单"},
                        {"command": "tasks", "description": "任务管理"},
                        {"command": "sync", "description": "同步任务"},
                        {"command": "accounts", "description": "账号管理"},
                        {"command": "search", "description": "资源搜索"},
                        {"command": "settings", "description": "系统设置"},
                        {"command": "status", "description": "运行状态"},
                        {"command": "cancel", "description": "取消当前操作"},
                    ]
                )
            except Exception:
                logger.exception("telegram setMyCommands failed")
        return config, self._client, self._handler

    def _run(self) -> None:
        backoff = 2.0
        while not self._stop.is_set():
            config, client, handler = self._load_runtime()
            if not config or not client or not handler:
                time.sleep(5)
                continue
            try:
                with SessionLocal() as db:
                    last_update_id = get_last_update_id(db)
                    mark_polled(db)
                    _commit_with_retry(db)
                updates = client.get_updates(offset=last_update_id + 1, timeout=20)
                for update in updates:
                    if self._stop.is_set():
                        break
                    update_id = int(update.get("update_id") or 0)
                    try:
                        handler.handle_update(update)
                    except Exception as exc:
                        logger.exception("telegram update handling failed update_id=%s", update_id or None)
                        with SessionLocal() as db:
                            mark_poll_error(db, f"update_id={update_id or 0}: {str(exc)}")
                            _commit_with_retry(db)
                    finally:
                        if update_id > 0:
                            with SessionLocal() as db:
                                save_last_update_id(db, update_id)
                                _commit_with_retry(db)
                backoff = 2.0
            except Exception as exc:
                logger.exception("telegram polling loop failed")
                with SessionLocal() as db:
                    mark_poll_error(db, str(exc))
                    try:
                        _commit_with_retry(db)
                    except Exception:
                        logger.exception("telegram poll error state persist failed")
                time.sleep(backoff)
                backoff = min(backoff * 2, 30.0)


telegram_bot_manager = TelegramBotManager()

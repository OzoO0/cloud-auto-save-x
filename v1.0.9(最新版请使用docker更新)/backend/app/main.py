from __future__ import annotations

from contextlib import asynccontextmanager
import logging
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from alembic import command
from alembic.config import Config

from app.api.router import api_router
from app.core.exception_handlers import api_error_handler, http_error_handler, validation_error_handler
from app.core.errors import ApiError
from app.core.logging import setup_logging
from app.core.settings import settings
from app.db.session import SessionLocal
from app.extensions.runtime.telegram_bot_manager import telegram_bot_manager
from app.extensions.runtime.task_scheduler import task_scheduler_manager
from app.middlewares.timing import TimingMiddleware
from app.services.proxy_image_cache import ensure_dir, resolve_proxy_image_cache_dir
from app.services.sync_execution_recovery import abort_running_sync_executions_on_startup, release_all_sync_task_locks_on_startup
from app.services.setup import ensure_permissions_and_roles


logger = logging.getLogger(__name__)


def _ensure_sqlite_dir() -> None:
    if not settings.database_url.startswith("sqlite"):
        return
    if "///" not in settings.database_url:
        return
    path = settings.database_url.split("///", 1)[1]
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)


def _ensure_proxy_image_cache_dir() -> None:
    path = resolve_proxy_image_cache_dir(database_url=settings.database_url, explicit_dir=settings.media_proxy_image_cache_dir)
    ensure_dir(path)


def _run_db_migrations_if_needed() -> None:
    flag = os.getenv("RUN_MIGRATIONS", "1").strip().lower()
    if flag in {"0", "false", "no", "off"}:
        return

    backend_dir = Path(__file__).resolve().parents[1]
    alembic_ini = backend_dir / "alembic.ini"
    cfg = Config(str(alembic_ini))
    cfg.set_main_option("script_location", str(backend_dir / "alembic"))
    cfg.set_main_option("prepend_sys_path", str(backend_dir))
    command.upgrade(cfg, "head")
    setup_logging(force=True)


def create_app() -> FastAPI:
    setup_logging()
    _ensure_sqlite_dir()
    _ensure_proxy_image_cache_dir()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        _run_db_migrations_if_needed()
        try:
            with SessionLocal() as db:
                ensure_permissions_and_roles(db)
                abort_running_sync_executions_on_startup(db)
                release_all_sync_task_locks_on_startup(db)
                db.commit()
        except Exception as e:
            logger.warning("权限初始化失败: %s", e, exc_info=True)
        if bool(getattr(settings, "scheduler_enabled", True)):
            task_scheduler_manager.start()
        telegram_bot_manager.start()
        yield
        telegram_bot_manager.shutdown()
        if bool(getattr(settings, "scheduler_enabled", True)):
            task_scheduler_manager.shutdown()

    app = FastAPI(title=settings.app_name, lifespan=lifespan)

    app.add_middleware(TimingMiddleware)

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=[str(o) for o in settings.cors_origins],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(Exception, http_error_handler)

    app.include_router(api_router, prefix=settings.api_prefix)
    return app


app = create_app()

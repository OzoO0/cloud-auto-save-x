from __future__ import annotations

import logging
import logging.config
import os
import sys
from typing import Any


_configured = False


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _resolve_log_level() -> str:
    level = (os.getenv("LOG_LEVEL") or "").strip().upper()
    if level:
        return level
    if _env_bool("DEBUG", default=False):
        return "DEBUG"
    return "INFO"


def setup_logging(*, force: bool = False) -> None:
    global _configured
    if _configured and not force:
        return

    level = _resolve_log_level()

    config: dict[str, Any] = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "format": "%(asctime)s %(levelname)-5s [%(name)s] %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S",
            }
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "default",
                "stream": "ext://sys.stdout",
            }
        },
        "root": {"level": level, "handlers": ["console"]},
        "loggers": {
            "uvicorn": {"level": level, "handlers": ["console"], "propagate": False},
            "uvicorn.error": {"level": level, "handlers": ["console"], "propagate": False},
            "uvicorn.access": {"level": level, "handlers": ["console"], "propagate": False},
            "app.access": {"level": level, "handlers": ["console"], "propagate": False},
            "rebulk": {"level": "INFO", "handlers": ["console"], "propagate": False},
        },
    }

    logging.config.dictConfig(config)
    logging.captureWarnings(True)

    for stream in (sys.stdout, sys.stderr):
        try:
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(line_buffering=True)
        except Exception:
            pass

    _configured = True


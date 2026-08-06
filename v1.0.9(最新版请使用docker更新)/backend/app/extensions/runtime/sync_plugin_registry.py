from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.sync_plugin_definition import SyncPluginDefinition


class SyncPluginRegistry:
    def __init__(self, db: Session):
        self.db = db

    def load_active_plugins(self) -> list[dict[str, Any]]:
        rows = (
            self.db.execute(
                select(SyncPluginDefinition)
                .options(selectinload(SyncPluginDefinition.config))
                .where(SyncPluginDefinition.installed.is_(True))
                .order_by(SyncPluginDefinition.plugin_key.asc())
            )
            .scalars()
            .all()
        )
        items: list[dict[str, Any]] = []
        now = datetime.now()
        for definition in rows:
            config = definition.config
            if config is None or not config.enabled:
                continue
            try:
                module = __import__(f"app.extensions.sync_plugins.{definition.module_name}", fromlist=["*"])
                plugin_class = getattr(module, definition.module_name.capitalize())
                payload = json.loads(config.config_json) if config.config_json else {}
                plugin = plugin_class(**payload)
                config.runtime_status = "active" if getattr(plugin, "is_active", False) else "inactive"
                config.last_error = None
                config.last_checked_at = now
                items.append({"definition": definition, "config": config, "instance": plugin})
            except Exception as exc:
                config.runtime_status = "error"
                config.last_error = str(exc)
                config.last_checked_at = now
        return sorted(items, key=lambda item: item["config"].priority)

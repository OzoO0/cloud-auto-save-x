from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.errors import not_found
from app.extensions.runtime.sync_plugin_loader import sync_sync_plugin_definitions
from app.models.sync_plugin_definition import SyncPluginDefinition


def list_sync_plugins(db: Session) -> list[SyncPluginDefinition]:
    sync_sync_plugin_definitions(db)
    return (
        db.execute(
            select(SyncPluginDefinition)
            .options(selectinload(SyncPluginDefinition.config))
            .order_by(SyncPluginDefinition.plugin_key.asc())
        )
        .scalars()
        .all()
    )


def get_sync_plugin(db: Session, plugin_key: str) -> SyncPluginDefinition:
    sync_sync_plugin_definitions(db)
    plugin = (
        db.execute(
            select(SyncPluginDefinition)
            .options(selectinload(SyncPluginDefinition.config))
            .where(SyncPluginDefinition.plugin_key == plugin_key)
        )
        .scalars()
        .first()
    )
    if plugin is None:
        raise not_found("SYNC_PLUGIN_NOT_FOUND", "同步插件不存在")
    return plugin


def refresh_sync_plugins(db: Session) -> list[SyncPluginDefinition]:
    sync_sync_plugin_definitions(db)
    return list_sync_plugins(db)


def update_sync_plugin(
    db: Session,
    plugin_key: str,
    *,
    enabled: bool | None = None,
    priority: int | None = None,
    config: dict[str, Any] | None = None,
) -> SyncPluginDefinition:
    plugin = get_sync_plugin(db, plugin_key)
    if plugin.config is None:
        raise not_found("SYNC_PLUGIN_CONFIG_NOT_FOUND", "同步插件配置不存在")
    if enabled is not None:
        plugin.config.enabled = enabled
    if priority is not None:
        plugin.config.priority = priority
    if config is not None:
        plugin.config.config_json = json.dumps(config, ensure_ascii=False)
    db.flush()
    return plugin


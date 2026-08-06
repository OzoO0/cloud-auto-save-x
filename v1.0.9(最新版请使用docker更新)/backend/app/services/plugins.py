from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.errors import not_found
from app.extensions.runtime.plugin_loader import sync_plugin_definitions
from app.models.plugin_definition import PluginDefinition


def list_plugins(db: Session) -> list[PluginDefinition]:
    sync_plugin_definitions(db)
    return (
        db.execute(
            select(PluginDefinition)
            .options(selectinload(PluginDefinition.config))
            .order_by(PluginDefinition.plugin_key.asc())
        )
        .scalars()
        .all()
    )


def get_plugin(db: Session, plugin_key: str) -> PluginDefinition:
    sync_plugin_definitions(db)
    plugin = (
        db.execute(
            select(PluginDefinition)
            .options(selectinload(PluginDefinition.config))
            .where(PluginDefinition.plugin_key == plugin_key)
        )
        .scalars()
        .first()
    )
    if plugin is None:
        raise not_found('PLUGIN_NOT_FOUND', '插件不存在')
    return plugin


def refresh_plugins(db: Session) -> list[PluginDefinition]:
    sync_plugin_definitions(db)
    return list_plugins(db)


def update_plugin(
    db: Session,
    plugin_key: str,
    *,
    enabled: bool | None = None,
    priority: int | None = None,
    config: dict[str, Any] | None = None,
) -> PluginDefinition:
    plugin = get_plugin(db, plugin_key)
    if plugin.config is None:
        raise not_found('PLUGIN_CONFIG_NOT_FOUND', '插件配置不存在')
    if enabled is not None:
        plugin.config.enabled = enabled
    if priority is not None:
        plugin.config.priority = priority
    if config is not None:
        plugin.config.config_json = json.dumps(config, ensure_ascii=False)
    db.flush()
    return plugin

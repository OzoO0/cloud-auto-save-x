import json

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.deps import CurrentUser, get_current_user, require_permissions
from app.core.permissions import PLUGIN_READ, PLUGIN_WRITE
from app.db.session import get_db
from app.extensions.runtime.plugin_loader import PluginLoader
from app.schemas.plugin import PluginOut, PluginUpdateIn
from app.services import audit
from app.services.plugins import list_plugins, refresh_plugins, update_plugin

router = APIRouter()


def _descriptor_map() -> dict[str, object]:
    loader = PluginLoader()
    return {item.plugin_key: item for item in loader.discover()}


def _out(item, descriptors: dict[str, object] | None = None) -> PluginOut:
    config = item.config
    descriptor = (descriptors or {}).get(item.plugin_key)
    return PluginOut(
        id=item.id,
        plugin_key=item.plugin_key,
        module_name=item.module_name,
        source_type=item.source_type,
        version=item.version,
        installed=item.installed,
        discovered_at=item.discovered_at,
        enabled=bool(config.enabled) if config else False,
        priority=int(config.priority) if config else 0,
        runtime_status=config.runtime_status if config else None,
        last_checked_at=config.last_checked_at if config else None,
        last_error=config.last_error if config else None,
        config=json.loads(config.config_json) if config and config.config_json else {},
        config_fields=getattr(descriptor, 'config_fields', []),
        default_task_config=json.loads(config.default_task_config_json) if config and config.default_task_config_json else {},
        task_config_fields=getattr(descriptor, 'task_config_fields', []),
    )


@router.get('', response_model=list[PluginOut], dependencies=[Depends(require_permissions(PLUGIN_READ))])
def get_plugins(db: Session = Depends(get_db)):
    descriptors = _descriptor_map()
    return [_out(item, descriptors) for item in list_plugins(db)]


@router.post('/refresh', response_model=list[PluginOut], dependencies=[Depends(require_permissions(PLUGIN_WRITE))])
def post_refresh_plugins(request: Request, current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    items = refresh_plugins(db)
    audit.write_audit_log(db, actor_user_id=current.user.id, action='plugin.refresh', target_type='plugin', target_id='*', ip=request.client.host if request.client else None, user_agent=request.headers.get('user-agent'), success=True)
    db.commit()
    descriptors = _descriptor_map()
    return [_out(item, descriptors) for item in items]


@router.patch('/{plugin_key}', response_model=PluginOut, dependencies=[Depends(require_permissions(PLUGIN_WRITE))])
def patch_plugin(request: Request, plugin_key: str, payload: PluginUpdateIn, current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    item = update_plugin(db, plugin_key, **payload.model_dump(exclude_unset=True))
    audit.write_audit_log(db, actor_user_id=current.user.id, action='plugin.update', target_type='plugin', target_id=plugin_key, ip=request.client.host if request.client else None, user_agent=request.headers.get('user-agent'), success=True)
    db.commit()
    db.refresh(item)
    if item.config is not None:
        db.refresh(item.config)
    return _out(item, _descriptor_map())

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.deps import CurrentUser, get_current_user, require_permissions
from app.core.permissions import NOTIFY_READ, NOTIFY_WRITE
from app.db.session import get_db
from app.schemas.notification import NotificationConfigOut, NotificationConfigUpdateIn, NotificationTestIn, NotificationTestOut
from app.services import audit
from app.services.notifications import legacy_notify
from app.services.notifications.sender import send_test
from app.services.notifications.settings import get_or_create_notification_setting, load_notification_config, update_notification_setting


router = APIRouter()


@router.get("/config", response_model=NotificationConfigOut, dependencies=[Depends(require_permissions(NOTIFY_READ))])
def get_notification_config(db: Session = Depends(get_db)):
    item = get_or_create_notification_setting(db)
    config = load_notification_config(item)
    return NotificationConfigOut(
        config=config,
        default_config=dict(legacy_notify.DEFAULT_PUSH_CONFIG),
        updated_at=item.updated_at,
    )


@router.patch("/config", response_model=NotificationConfigOut, dependencies=[Depends(require_permissions(NOTIFY_WRITE))])
def patch_notification_config(
    request: Request,
    payload: NotificationConfigUpdateIn,
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    item = update_notification_setting(db, config=payload.config)
    audit.write_audit_log(
        db,
        actor_user_id=current.user.id,
        action="notify.config.update",
        target_type="notification_setting",
        target_id="config",
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        success=True,
    )
    db.commit()
    db.refresh(item)
    config = load_notification_config(item)
    return NotificationConfigOut(
        config=config,
        default_config=dict(legacy_notify.DEFAULT_PUSH_CONFIG),
        updated_at=item.updated_at,
    )


@router.post("/test", response_model=NotificationTestOut, dependencies=[Depends(require_permissions(NOTIFY_WRITE))])
def post_notification_test(
    request: Request,
    payload: NotificationTestIn,
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    item = get_or_create_notification_setting(db)
    config = load_notification_config(item)
    results = send_test(payload.title, payload.content, config=config, channels=payload.channels)
    audit.write_audit_log(
        db,
        actor_user_id=current.user.id,
        action="notify.test.send",
        target_type="notification_setting",
        target_id="config",
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        success=True,
        detail=f"channels={len(results)} filter={'1' if payload.channels else '0'}",
    )
    db.commit()
    return NotificationTestOut(results=results)

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import require_permissions
from app.core.permissions import AUDIT_READ
from app.db.session import get_db
from app.schemas.audit_log import AuditLogItemOut, AuditLogListOut
from app.services.audit_logs import list_audit_logs


router = APIRouter()


@router.get("", response_model=AuditLogListOut, dependencies=[Depends(require_permissions(AUDIT_READ))])
def get_audit_logs(
    page: int = 1,
    page_size: int = 20,
    q: str | None = None,
    action: str | None = None,
    success: bool | None = None,
    db: Session = Depends(get_db),
):
    rows, total = list_audit_logs(db, page=page, page_size=page_size, q=q, action=action, success=success)
    items = [
        AuditLogItemOut(
            id=row.id,
            actor_user_id=row.actor_user_id,
            actor_username=username,
            action=row.action,
            target_type=row.target_type,
            target_id=row.target_id,
            ip=row.ip,
            user_agent=row.user_agent,
            success=bool(row.success),
            detail=row.detail,
            created_at=row.created_at,
        )
        for row, username in rows
    ]
    return AuditLogListOut(page=page, page_size=page_size, total=total, items=items)


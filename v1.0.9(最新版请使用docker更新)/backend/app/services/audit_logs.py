from __future__ import annotations

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.models.user import User


def list_audit_logs(
    db: Session,
    *,
    page: int = 1,
    page_size: int = 20,
    q: str | None = None,
    action: str | None = None,
    success: bool | None = None,
) -> tuple[list[tuple[AuditLog, str | None]], int]:
    page = max(1, int(page))
    page_size = min(200, max(1, int(page_size)))

    stmt: Select = (
        select(AuditLog, User.username)
        .select_from(AuditLog)
        .join(User, User.id == AuditLog.actor_user_id, isouter=True)
        .order_by(AuditLog.id.desc())
    )

    q_value = (q or "").strip()
    if q_value:
        stmt = stmt.where(
            or_(
                AuditLog.action.contains(q_value),
                AuditLog.target_type.contains(q_value),
                AuditLog.target_id.contains(q_value),
                AuditLog.detail.contains(q_value),
                User.username.contains(q_value),
            )
        )

    action_value = (action or "").strip()
    if action_value:
        stmt = stmt.where(AuditLog.action == action_value)

    if success is not None:
        stmt = stmt.where(AuditLog.success.is_(bool(success)))

    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()

    rows = (
        db.execute(stmt.offset((page - 1) * page_size).limit(page_size))
        .all()
    )
    return rows, int(total)


from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.deps import CurrentUser, get_current_user, require_permissions
from app.core.permissions import USER_READ, USER_WRITE
from app.db.session import get_db
from app.schemas.user import (
    RoleOut,
    UserBatchRolesIn,
    UserBatchStatusIn,
    UserCreateIn,
    UserListOut,
    UserOut,
    UserSetRolesIn,
    UserStatusUpdateIn,
)
from app.services import audit
from app.services.users import batch_set_roles, batch_set_status, create_user, list_users, set_user_roles, set_user_status


router = APIRouter()


def _role_out(r) -> RoleOut:
    return RoleOut(id=r.id, name=r.name, description=r.description)


def _user_out(u) -> UserOut:
    return UserOut(id=u.id, username=u.username, email=u.email, is_active=u.is_active, roles=[_role_out(r) for r in u.roles])


@router.get("", response_model=UserListOut, dependencies=[Depends(require_permissions(USER_READ))])
def get_users(page: int = 1, page_size: int = 20, q: str | None = None, db: Session = Depends(get_db)):
    items, total = list_users(db, page=page, page_size=page_size, q=q)
    return UserListOut(page=page, page_size=page_size, total=total, items=[_user_out(u) for u in items])


@router.post("", response_model=UserOut, dependencies=[Depends(require_permissions(USER_WRITE))])
def post_user(
    request: Request,
    payload: UserCreateIn,
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user = create_user(db, username=payload.username, email=payload.email, password=payload.password)
    audit.write_audit_log(
        db,
        actor_user_id=current.user.id,
        action="user.create",
        target_type="user",
        target_id=str(user.id),
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        success=True,
    )
    db.commit()
    db.refresh(user)
    return _user_out(user)


@router.patch("/{user_id}/status", response_model=UserOut, dependencies=[Depends(require_permissions(USER_WRITE))])
def patch_user_status(
    request: Request,
    user_id: int,
    payload: UserStatusUpdateIn,
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user = set_user_status(db, user_id=user_id, is_active=payload.is_active)
    audit.write_audit_log(
        db,
        actor_user_id=current.user.id,
        action="user.set_status",
        target_type="user",
        target_id=str(user_id),
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        success=True,
        detail=f"is_active={payload.is_active}",
    )
    db.commit()
    db.refresh(user)
    return _user_out(user)


@router.post("/{user_id}/roles", response_model=UserOut, dependencies=[Depends(require_permissions(USER_WRITE))])
def post_user_roles(
    request: Request,
    user_id: int,
    payload: UserSetRolesIn,
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user = set_user_roles(db, user_id=user_id, role_ids=payload.role_ids)
    audit.write_audit_log(
        db,
        actor_user_id=current.user.id,
        action="user.set_roles",
        target_type="user",
        target_id=str(user_id),
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        success=True,
        detail=f"role_ids={payload.role_ids}",
    )
    db.commit()
    db.refresh(user)
    return _user_out(user)


@router.post("/batch/status", dependencies=[Depends(require_permissions(USER_WRITE))])
def post_batch_status(
    request: Request,
    payload: UserBatchStatusIn,
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    updated = batch_set_status(db, user_ids=payload.user_ids, is_active=payload.is_active)
    audit.write_audit_log(
        db,
        actor_user_id=current.user.id,
        action="user.batch_set_status",
        target_type="user",
        target_id=",".join(str(i) for i in payload.user_ids),
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        success=True,
        detail=f"is_active={payload.is_active}",
    )
    db.commit()
    return {"updated": updated}


@router.post("/batch/roles", dependencies=[Depends(require_permissions(USER_WRITE))])
def post_batch_roles(
    request: Request,
    payload: UserBatchRolesIn,
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    updated = batch_set_roles(db, user_ids=payload.user_ids, role_ids=payload.role_ids)
    audit.write_audit_log(
        db,
        actor_user_id=current.user.id,
        action="user.batch_set_roles",
        target_type="user",
        target_id=",".join(str(i) for i in payload.user_ids),
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        success=True,
        detail=f"role_ids={payload.role_ids}",
    )
    db.commit()
    return {"updated": updated}

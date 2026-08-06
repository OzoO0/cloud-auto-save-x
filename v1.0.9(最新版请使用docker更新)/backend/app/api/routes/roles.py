from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.deps import CurrentUser, get_current_user, require_permissions
from app.core.permissions import ROLE_READ, ROLE_WRITE
from app.db.session import get_db
from app.schemas.role import PermissionOut, RoleCreateIn, RoleOut, RoleSetPermissionsIn, RoleUpdateIn
from app.services import audit
from app.services.roles import create_role, delete_role, list_roles, set_role_permissions, update_role


router = APIRouter()


def _permission_out(p) -> PermissionOut:
    return PermissionOut(id=p.id, code=p.code, name=p.name, description=p.description)


def _role_out(r) -> RoleOut:
    return RoleOut(id=r.id, name=r.name, description=r.description, permissions=[_permission_out(p) for p in r.permissions])


@router.get("", response_model=list[RoleOut], dependencies=[Depends(require_permissions(ROLE_READ))])
def get_roles(db: Session = Depends(get_db)):
    roles = list_roles(db)
    return [_role_out(r) for r in roles]


@router.post("", response_model=RoleOut, dependencies=[Depends(require_permissions(ROLE_WRITE))])
def post_role(
    request: Request,
    payload: RoleCreateIn,
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    role = create_role(db, name=payload.name, description=payload.description)
    audit.write_audit_log(
        db,
        actor_user_id=current.user.id,
        action="role.create",
        target_type="role",
        target_id=str(role.id),
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        success=True,
    )
    db.commit()
    db.refresh(role)
    return _role_out(role)


@router.patch("/{role_id}", response_model=RoleOut, dependencies=[Depends(require_permissions(ROLE_WRITE))])
def patch_role(
    request: Request,
    role_id: int,
    payload: RoleUpdateIn,
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    role = update_role(db, role_id=role_id, description=payload.description)
    audit.write_audit_log(
        db,
        actor_user_id=current.user.id,
        action="role.update",
        target_type="role",
        target_id=str(role_id),
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        success=True,
    )
    db.commit()
    db.refresh(role)
    return _role_out(role)


@router.delete("/{role_id}", dependencies=[Depends(require_permissions(ROLE_WRITE))])
def delete_role_by_id(
    request: Request,
    role_id: int,
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    delete_role(db, role_id=role_id)
    audit.write_audit_log(
        db,
        actor_user_id=current.user.id,
        action="role.delete",
        target_type="role",
        target_id=str(role_id),
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        success=True,
    )
    db.commit()
    return {"ok": True}


@router.post("/{role_id}/permissions", response_model=RoleOut, dependencies=[Depends(require_permissions(ROLE_WRITE))])
def post_role_permissions(
    request: Request,
    role_id: int,
    payload: RoleSetPermissionsIn,
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    role = set_role_permissions(db, role_id=role_id, permission_ids=payload.permission_ids)
    audit.write_audit_log(
        db,
        actor_user_id=current.user.id,
        action="role.set_permissions",
        target_type="role",
        target_id=str(role_id),
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        success=True,
        detail=f"permission_ids={payload.permission_ids}",
    )
    db.commit()
    db.refresh(role)
    return _role_out(role)

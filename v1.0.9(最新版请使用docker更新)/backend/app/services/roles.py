from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.errors import bad_request, not_found
from app.models.permission import Permission
from app.models.role import Role


def list_roles(db: Session) -> list[Role]:
    return db.execute(select(Role).options(selectinload(Role.permissions)).order_by(Role.id.asc())).scalars().all()


def create_role(db: Session, *, name: str, description: str | None) -> Role:
    exists = db.execute(select(Role.id).where(Role.name == name)).first()
    if exists:
        raise bad_request("ROLE_EXISTS", "角色名已存在")
    role = Role(name=name, description=description)
    db.add(role)
    db.flush()
    return role


def update_role(db: Session, *, role_id: int, description: str | None) -> Role:
    role = db.get(Role, role_id)
    if role is None:
        raise not_found("ROLE_NOT_FOUND", "角色不存在")
    role.description = description
    return role


def delete_role(db: Session, *, role_id: int) -> None:
    role = db.get(Role, role_id)
    if role is None:
        raise not_found("ROLE_NOT_FOUND", "角色不存在")
    db.delete(role)


def set_role_permissions(db: Session, *, role_id: int, permission_ids: list[int]) -> Role:
    role = db.get(Role, role_id)
    if role is None:
        raise not_found("ROLE_NOT_FOUND", "角色不存在")

    permissions: list[Permission] = []
    if permission_ids:
        permissions = db.execute(select(Permission).where(Permission.id.in_(permission_ids))).scalars().all()
        if len(permissions) != len(set(permission_ids)):
            raise bad_request("PERMISSION_NOT_FOUND", "存在无效权限")

    role.permissions = permissions
    return role

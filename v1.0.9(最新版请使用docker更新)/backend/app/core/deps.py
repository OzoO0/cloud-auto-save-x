from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import forbidden, unauthorized
from app.core.security import decode_access_token
from app.db.session import SessionLocal, get_db
from app.models.permission import Permission
from app.models.role import Role
from app.models.user import User


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


@dataclass(frozen=True)
class CurrentUser:
    user: User
    roles: list[str]
    permissions: set[str]


def _load_permissions(db: Session, user_id: int) -> tuple[list[str], set[str]]:
    role_stmt = (
        select(Role.name)
        .join_from(User, User.roles)
        .where(User.id == user_id)
        .distinct()
    )
    roles = [r[0] for r in db.execute(role_stmt).all()]

    perm_stmt = (
        select(Permission.code)
        .join_from(User, User.roles)
        .join(Role.permissions)
        .where(User.id == user_id)
        .distinct()
    )
    permissions = {p[0] for p in db.execute(perm_stmt).all()}
    return roles, permissions


def load_user_roles_permissions(db: Session, user_id: int) -> tuple[list[str], list[str]]:
    roles, permissions = _load_permissions(db, user_id)
    return roles, sorted(permissions)


def get_current_user(
    request: Request,
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> CurrentUser:
    cached: CurrentUser | None = getattr(request.state, "current_user", None)
    if cached is not None:
        return cached

    try:
        payload = decode_access_token(token)
    except ValueError:
        raise unauthorized("AUTH_INVALID_TOKEN", "登录已失效")

    sub = payload.get("sub")
    if not isinstance(sub, str) or not sub.isdigit():
        raise unauthorized("AUTH_INVALID_TOKEN", "登录已失效")

    user = db.get(User, int(sub))
    if user is None or not user.is_active:
        raise unauthorized("AUTH_INVALID_USER", "账号不可用")

    roles, permissions = _load_permissions(db, user.id)
    current = CurrentUser(user=user, roles=roles, permissions=permissions)
    request.state.current_user = current
    return current


def get_current_user_scoped(
    request: Request,
    token: str = Depends(oauth2_scheme),
) -> CurrentUser:
    cached: CurrentUser | None = getattr(request.state, "current_user", None)
    if cached is not None:
        return cached

    try:
        payload = decode_access_token(token)
    except ValueError:
        raise unauthorized("AUTH_INVALID_TOKEN", "登录已失效")

    sub = payload.get("sub")
    if not isinstance(sub, str) or not sub.isdigit():
        raise unauthorized("AUTH_INVALID_TOKEN", "登录已失效")

    with SessionLocal() as db:
        user = db.get(User, int(sub))
        if user is None or not user.is_active:
            raise unauthorized("AUTH_INVALID_USER", "账号不可用")

        roles, permissions = _load_permissions(db, user.id)
        current = CurrentUser(user=user, roles=roles, permissions=permissions)
        request.state.current_user = current
        return current


def require_permissions(*codes: str):
    def _dep(current: CurrentUser = Depends(get_current_user)) -> None:
        missing = [c for c in codes if c not in current.permissions]
        if missing:
            raise forbidden("AUTH_FORBIDDEN", "权限不足", detail=",".join(missing))

    return _dep


def require_permissions_scoped(*codes: str):
    def _dep(current: CurrentUser = Depends(get_current_user_scoped)) -> None:
        missing = [c for c in codes if c not in current.permissions]
        if missing:
            raise forbidden("AUTH_FORBIDDEN", "权限不足", detail=",".join(missing))

    return _dep

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.errors import bad_request, not_found
from app.core.security import hash_password
from app.models.role import Role
from app.models.user import User
from app.services.auth import ensure_password_policy


def list_users(db: Session, *, page: int, page_size: int, q: str | None) -> tuple[list[User], int]:
    stmt = select(User).options(selectinload(User.roles))
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where((User.username.like(like)) | (User.email.like(like)))

    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    items = (
        db.execute(stmt.order_by(User.id.desc()).offset((page - 1) * page_size).limit(page_size))
        .scalars()
        .all()
    )
    return items, int(total)


def create_user(db: Session, *, username: str, email: str, password: str) -> User:
    ensure_password_policy(password)

    exists = db.execute(select(User.id).where((User.username == username) | (User.email == email))).first()
    if exists:
        raise bad_request("USER_EXISTS", "用户名或邮箱已存在")

    user = User(username=username, email=email, hashed_password=hash_password(password), is_active=True)
    db.add(user)
    db.flush()
    return user


def set_user_status(db: Session, *, user_id: int, is_active: bool) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise not_found("USER_NOT_FOUND", "用户不存在")
    user.is_active = is_active
    return user


def set_user_roles(db: Session, *, user_id: int, role_ids: list[int]) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise not_found("USER_NOT_FOUND", "用户不存在")

    roles: list[Role] = []
    if role_ids:
        roles = db.execute(select(Role).where(Role.id.in_(role_ids))).scalars().all()
        if len(roles) != len(set(role_ids)):
            raise bad_request("ROLE_NOT_FOUND", "存在无效角色")

    user.roles = roles
    return user


def batch_set_status(db: Session, *, user_ids: list[int], is_active: bool) -> int:
    users = db.execute(select(User).where(User.id.in_(user_ids))).scalars().all()
    for u in users:
        u.is_active = is_active
    return len(users)


def batch_set_roles(db: Session, *, user_ids: list[int], role_ids: list[int]) -> int:
    roles: list[Role] = []
    if role_ids:
        roles = db.execute(select(Role).where(Role.id.in_(role_ids))).scalars().all()
        if len(roles) != len(set(role_ids)):
            raise bad_request("ROLE_NOT_FOUND", "存在无效角色")

    users = db.execute(select(User).where(User.id.in_(user_ids)).options(selectinload(User.roles))).scalars().all()
    for u in users:
        u.roles = roles
    return len(users)

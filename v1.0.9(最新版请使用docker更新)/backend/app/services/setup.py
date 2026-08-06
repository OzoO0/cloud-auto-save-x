from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import Session

from app.core.permission_seed import PERMISSIONS_SEED
from app.core.security import hash_password
from app.models.permission import Permission
from app.models.role import Role
from app.models.user import User
from app.services.auth import ensure_password_policy


def is_initialized(db: Session) -> bool:
    try:
        return db.execute(select(User.id).limit(1)).first() is not None
    except (OperationalError, ProgrammingError):
        return False


def seed_permissions(db: Session) -> dict[str, Permission]:
    perms_by_code: dict[str, Permission] = {}
    for code, name in PERMISSIONS_SEED:
        permission = db.execute(select(Permission).where(Permission.code == code)).scalars().first()
        if permission is None:
            permission = Permission(code=code, name=name)
            db.add(permission)
        perms_by_code[code] = permission
    return perms_by_code


def ensure_permissions_and_roles(db: Session) -> None:
    perms_by_code = seed_permissions(db)

    admin_role = db.execute(select(Role).where(Role.name == "admin")).scalars().first()
    if admin_role is None:
        admin_role = Role(name="admin", description="系统管理员")
        db.add(admin_role)
    admin_role.permissions = list(perms_by_code.values())


def create_initial_admin(db: Session, *, username: str, email: str, password: str) -> User:
    ensure_password_policy(password)

    ensure_permissions_and_roles(db)
    admin_role = db.execute(select(Role).where(Role.name == "admin")).scalars().first()

    user = User(
        username=username,
        email=email,
        hashed_password=hash_password(password),
        is_active=True,
    )
    db.add(user)
    user.roles = [admin_role]
    return user

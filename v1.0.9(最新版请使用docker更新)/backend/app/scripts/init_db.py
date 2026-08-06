from __future__ import annotations

import os

from sqlalchemy import select

from app.core.permission_seed import PERMISSIONS_SEED
from app.core.permissions import (
    DRIVE_ACCOUNT_READ,
    DRIVE_ACCOUNT_WRITE,
    NOTIFY_READ,
    NOTIFY_WRITE,
    PERMISSION_READ,
    PLUGIN_READ,
    PLUGIN_WRITE,
    ROLE_READ,
    ROLE_WRITE,
    SYNC_READ,
    TASK_READ,
    TASK_RUN,
    TASK_WRITE,
    USER_READ,
    USER_WRITE,
)
from app.db.session import SessionLocal
from app.models.permission import Permission
from app.models.role import Role
from app.models.user import User
from app.core.security import hash_password
from app.services.auth import ensure_password_policy


def _get_env(name: str, default: str) -> str:
    v = os.getenv(name)
    return v if v else default


def main() -> None:
    admin_username = _get_env("DEFAULT_ADMIN_USERNAME", "admin")
    admin_email = _get_env("DEFAULT_ADMIN_EMAIL", "admin@example.com")
    admin_password = _get_env("DEFAULT_ADMIN_PASSWORD", "Admin@1234!")
    viewer_username = _get_env("DEFAULT_VIEWER_USERNAME", "viewer")
    viewer_email = _get_env("DEFAULT_VIEWER_EMAIL", "viewer@example.com")
    viewer_password = _get_env("DEFAULT_VIEWER_PASSWORD", "Viewer@1234!")

    ensure_password_policy(admin_password)
    ensure_password_policy(viewer_password)

    with SessionLocal() as db:
        perms_by_code: dict[str, Permission] = {}
        for code, name in PERMISSIONS_SEED:
            p = db.execute(select(Permission).where(Permission.code == code)).scalars().first()
            if p is None:
                p = Permission(code=code, name=name)
                db.add(p)
            perms_by_code[code] = p

        admin_role = db.execute(select(Role).where(Role.name == "admin")).scalars().first()
        if admin_role is None:
            admin_role = Role(name="admin", description="系统管理员")
            db.add(admin_role)
        admin_role.permissions = list(perms_by_code.values())

        viewer_role = db.execute(select(Role).where(Role.name == "viewer")).scalars().first()
        if viewer_role is None:
            viewer_role = Role(name="viewer", description="只读用户")
            db.add(viewer_role)
        viewer_role.permissions = [
            perms_by_code[USER_READ],
            perms_by_code[ROLE_READ],
            perms_by_code[PERMISSION_READ],
            perms_by_code[DRIVE_ACCOUNT_READ],
            perms_by_code[PLUGIN_READ],
            perms_by_code[NOTIFY_READ],
            perms_by_code[TASK_READ],
            perms_by_code[SYNC_READ],
        ]

        admin_user = db.execute(select(User).where(User.username == admin_username)).scalars().first()
        if admin_user is None:
            admin_user = User(
                username=admin_username,
                email=admin_email,
                hashed_password=hash_password(admin_password),
                is_active=True,
            )
            db.add(admin_user)
        admin_user.roles = [admin_role]

        viewer_user = db.execute(select(User).where(User.username == viewer_username)).scalars().first()
        if viewer_user is None:
            viewer_user = User(
                username=viewer_username,
                email=viewer_email,
                hashed_password=hash_password(viewer_password),
                is_active=True,
            )
            db.add(viewer_user)
        viewer_user.roles = [viewer_role]

        db.commit()


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import logging
import os

from sqlalchemy import select

from app.core.logging import setup_logging
from app.core.permission_seed import PERMISSIONS_SEED
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models.permission import Permission
from app.models.role import Role
from app.models.user import User
from app.services.auth import ensure_password_policy


logger = logging.getLogger(__name__)


def _default(name: str, fallback: str) -> str:
    value = os.getenv(name, "").strip()
    return value or fallback


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="确保管理员账号存在，并可按需重置密码")
    parser.add_argument("--username", default=_default("DEFAULT_ADMIN_USERNAME", "admin"), help="管理员用户名")
    parser.add_argument("--email", default=_default("DEFAULT_ADMIN_EMAIL", "admin@example.com"), help="管理员邮箱")
    parser.add_argument("--password", default=_default("DEFAULT_ADMIN_PASSWORD", "Admin@1234!"), help="管理员密码")
    parser.add_argument("--reset-password", action="store_true", help="如果管理员已存在，也强制重置密码")
    parser.add_argument("--activate", action="store_true", help="强制将管理员设置为启用状态")
    return parser.parse_args()


def ensure_admin(
    *,
    username: str,
    email: str,
    password: str,
    reset_password: bool = False,
    activate: bool = False,
) -> tuple[bool, bool]:
    ensure_password_policy(password)

    with SessionLocal() as db:
        perms_by_code: dict[str, Permission] = {}
        for code, name in PERMISSIONS_SEED:
            permission = db.execute(select(Permission).where(Permission.code == code)).scalars().first()
            if permission is None:
                permission = Permission(code=code, name=name)
                db.add(permission)
            perms_by_code[code] = permission

        admin_role = db.execute(select(Role).where(Role.name == "admin")).scalars().first()
        if admin_role is None:
            admin_role = Role(name="admin", description="系统管理员")
            db.add(admin_role)
        admin_role.permissions = list(perms_by_code.values())

        user = db.execute(select(User).where(User.username == username)).scalars().first()
        created = user is None
        password_reset = False

        if user is None:
            user = User(
                username=username,
                email=email,
                hashed_password=hash_password(password),
                is_active=True,
            )
            db.add(user)
            password_reset = True
        else:
            if not user.email or user.email != email:
                user.email = email
            if activate:
                user.is_active = True
            if reset_password:
                user.hashed_password = hash_password(password)
                password_reset = True

        user.roles = [admin_role]
        if activate:
            user.is_active = True

        db.commit()
        return created, password_reset


def main() -> None:
    setup_logging()
    args = parse_args()
    created, password_reset = ensure_admin(
        username=args.username,
        email=args.email,
        password=args.password,
        reset_password=args.reset_password,
        activate=args.activate,
    )
    action = "已创建" if created else "已修复"
    reset_info = "，并重置密码" if password_reset else ""
    logger.info("%s管理员账号: %s%s", action, args.username, reset_info)


if __name__ == "__main__":
    main()

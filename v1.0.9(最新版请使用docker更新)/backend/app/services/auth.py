from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import bad_request, unauthorized
from app.core.security import (
    create_access_token,
    generate_refresh_token,
    hash_refresh_token,
    verify_password,
)
from app.core.settings import settings
from app.core.deps import load_user_roles_permissions
from app.models.refresh_token import RefreshToken
from app.models.user import User


def _utcnow() -> datetime:
    return datetime.now()


def _normalize_dt(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value
    return value.astimezone().replace(tzinfo=None)


def _client_ip(request: Request) -> str | None:
    if request.client is None:
        return None
    return request.client.host


def _user_agent(request: Request) -> str | None:
    return request.headers.get("user-agent")


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=settings.refresh_token_cookie_name,
        value=token,
        httponly=True,
        secure=settings.refresh_token_cookie_secure,
        samesite=settings.refresh_token_cookie_samesite,
        domain=settings.refresh_token_cookie_domain,
        path="/",
        max_age=settings.refresh_token_expires_seconds,
    )


def clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.refresh_token_cookie_name,
        domain=settings.refresh_token_cookie_domain,
        path="/",
    )


def authenticate_user(db: Session, username: str, password: str) -> User:
    stmt = select(User).where(User.username == username)
    user = db.execute(stmt).scalars().first()
    if user is None or not user.is_active:
        raise unauthorized("AUTH_BAD_CREDENTIALS", "用户名或密码错误")
    if not verify_password(password, user.hashed_password):
        raise unauthorized("AUTH_BAD_CREDENTIALS", "用户名或密码错误")
    return user


def issue_tokens(db: Session, *, user: User, permissions: list[str], request: Request, response: Response) -> str:
    refresh_plain = generate_refresh_token()
    refresh_hash = hash_refresh_token(refresh_plain)
    now = _utcnow()

    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=refresh_hash,
            expires_at=now + timedelta(seconds=settings.refresh_token_expires_seconds),
            ip=_client_ip(request),
            user_agent=_user_agent(request),
            last_used_at=now,
        )
    )
    _set_refresh_cookie(response, refresh_plain)
    return create_access_token(str(user.id), permissions)


def refresh_access_token(db: Session, *, request: Request, response: Response) -> tuple[User, str]:
    refresh_plain = request.cookies.get(settings.refresh_token_cookie_name)
    if not refresh_plain:
        raise unauthorized("AUTH_NO_REFRESH", "请重新登录")

    token_hash = hash_refresh_token(refresh_plain)
    stmt = select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    token = db.execute(stmt).scalars().first()
    if token is None:
        raise unauthorized("AUTH_REFRESH_INVALID", "请重新登录")

    now = _utcnow()
    if token.revoked_at is not None or _normalize_dt(token.expires_at) <= now:
        raise unauthorized("AUTH_REFRESH_EXPIRED", "请重新登录")

    user = db.get(User, token.user_id)
    if user is None or not user.is_active:
        raise unauthorized("AUTH_INVALID_USER", "账号不可用")

    token.revoked_at = now
    token.last_used_at = now

    _, permissions = load_user_roles_permissions(db, user.id)
    return user, issue_tokens(db, user=user, permissions=permissions, request=request, response=response)


def revoke_refresh_token(db: Session, *, request: Request) -> None:
    refresh_plain = request.cookies.get(settings.refresh_token_cookie_name)
    if not refresh_plain:
        return

    token_hash = hash_refresh_token(refresh_plain)
    stmt = select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    token = db.execute(stmt).scalars().first()
    if token is None:
        return
    if token.revoked_at is None:
        token.revoked_at = _utcnow()


def ensure_password_policy(password: str) -> None:
    if len(password) < 8 or not any(not c.isalnum() for c in password):
        raise bad_request("PASSWORD_WEAK", "密码强度不足", detail="至少8位且包含特殊字符")

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta

import bcrypt
from jose import JWTError, jwt

from app.core.settings import settings


def hash_password(plain: str) -> str:
    hashed = bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt())
    return hashed.decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


def validate_password_strength(password: str) -> None:
    if len(password) < 8:
        raise ValueError("密码至少8位")
    if not any(not c.isalnum() for c in password):
        raise ValueError("密码需包含特殊字符")


def create_access_token(subject: str, permissions: list[str]) -> str:
    now = datetime.now()
    expire = now + timedelta(seconds=settings.access_token_expires_seconds)
    payload = {"sub": subject, "perms": permissions, "iat": int(now.timestamp()), "exp": int(expire.timestamp())}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, object]:
    try:
        return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError as e:
        raise ValueError("invalid_token") from e


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_refresh_token(token: str) -> str:
    raw = f"{token}:{settings.refresh_token_pepper}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from threading import Lock
from typing import Any


@dataclass
class DriveAccountAuthSession:
    session_id: str
    account_id: int
    drive_type: str
    method: str
    adapter: Any
    payload: dict[str, Any]
    expires_at: float


_LOCK = Lock()
_SESSIONS: dict[str, DriveAccountAuthSession] = {}


def create_auth_session(
    *,
    account_id: int,
    drive_type: str,
    method: str,
    adapter: Any,
    payload: dict[str, Any],
    ttl_seconds: int = 600,
) -> DriveAccountAuthSession:
    now = time.time()
    session_id = uuid.uuid4().hex
    session = DriveAccountAuthSession(
        session_id=session_id,
        account_id=account_id,
        drive_type=drive_type,
        method=method,
        adapter=adapter,
        payload=dict(payload or {}),
        expires_at=now + ttl_seconds,
    )
    with _LOCK:
        _SESSIONS[session_id] = session
    return session


def get_auth_session(session_id: str) -> DriveAccountAuthSession | None:
    now = time.time()
    with _LOCK:
        session = _SESSIONS.get(session_id)
        if session is None:
            return None
        if session.expires_at <= now:
            _SESSIONS.pop(session_id, None)
            return None
        return session


def delete_auth_session(session_id: str) -> None:
    with _LOCK:
        _SESSIONS.pop(session_id, None)


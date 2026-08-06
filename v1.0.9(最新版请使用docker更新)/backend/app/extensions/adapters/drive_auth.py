from __future__ import annotations

from typing import Any, Literal

AuthMethod = Literal["captcha", "sms", "qrcode"]


class DriveAuthRequired(Exception):
    def __init__(
        self,
        *,
        method: AuthMethod,
        message: str,
        payload: dict[str, Any] | None = None,
        adapter: Any | None = None,
    ):
        super().__init__(message)
        self.method = method
        self.message = message
        self.payload = payload or {}
        self.adapter = adapter


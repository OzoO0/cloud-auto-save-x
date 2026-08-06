from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class AuditLogItemOut(BaseModel):
    id: int
    actor_user_id: int | None = None
    actor_username: str | None = None

    action: str = Field(default="", max_length=64)
    target_type: str | None = Field(default=None, max_length=64)
    target_id: str | None = Field(default=None, max_length=64)

    ip: str | None = Field(default=None, max_length=64)
    user_agent: str | None = Field(default=None, max_length=255)

    success: bool = True
    detail: str | None = Field(default=None, max_length=1024)
    created_at: datetime


class AuditLogListOut(BaseModel):
    page: int = 1
    page_size: int = 20
    total: int = 0
    items: list[AuditLogItemOut] = []


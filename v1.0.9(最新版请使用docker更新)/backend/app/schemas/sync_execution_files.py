from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class SyncExecutionFileOut(BaseModel):
    id: int
    sync_execution_id: int
    path: str
    action: str
    status: str
    size: int | None = None
    message: str | None = None
    updated_at: datetime
    created_at: datetime


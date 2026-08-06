from __future__ import annotations

from pydantic import BaseModel


class RepairBannedTaskItemOut(BaseModel):
    task_id: int
    taskname: str
    drive_type: str | None = None
    old_shareurl: str | None = None
    new_shareurl: str | None = None
    season: int | None = None
    episode: int | None = None
    size: int | None = None


class RepairBannedTasksOut(BaseModel):
    checked: int = 0
    repaired: int = 0
    items: list[RepairBannedTaskItemOut] = []


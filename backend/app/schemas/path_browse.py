from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class PathBrowseIn(BaseModel):
    path: str = Field(default="")
    refresh: bool = False
    max_items: int = Field(default=200, ge=1, le=5000)


class PathBrowsePathOut(BaseModel):
    name: str
    path: str


class PathBrowseItemOut(BaseModel):
    name: str
    path: str
    is_dir: bool
    updated_at: Any | None = None
    size: int | None = None


class PathBrowseOut(BaseModel):
    dir_path: str
    exists: bool
    paths: list[PathBrowsePathOut] = []
    items: list[PathBrowseItemOut] = []
    scanned_at: datetime = Field(default_factory=datetime.now)


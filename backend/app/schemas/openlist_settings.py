from __future__ import annotations

from pydantic import BaseModel, Field


class OpenListConfigOut(BaseModel):
    url: str | None = None
    has_token: bool = False


class OpenListConfigUpdateIn(BaseModel):
    url: str | None = Field(default=None)
    token: str | None = Field(default=None)


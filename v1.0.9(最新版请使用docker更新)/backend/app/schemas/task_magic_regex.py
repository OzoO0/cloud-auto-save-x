from __future__ import annotations

from pydantic import BaseModel, Field


class MagicRegexRuleOut(BaseModel):
    key: str = Field(min_length=1, max_length=64)
    label: str | None = Field(default=None, max_length=128)
    pattern: str = Field(default="", max_length=2048)
    replace: str = Field(default="", max_length=2048)


class MagicRegexOut(BaseModel):
    rules: list[MagicRegexRuleOut] = []

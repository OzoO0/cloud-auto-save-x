from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class MagicRegexRuleUpsertIn(BaseModel):
    label: str | None = Field(default=None, max_length=128)
    pattern: str | None = Field(default=None, max_length=2048)
    replace: str | None = Field(default=None, max_length=2048)
    enabled: bool | None = None


class MagicRegexRuleItemOut(BaseModel):
    key: str = Field(min_length=1, max_length=64)
    label: str | None = Field(default=None, max_length=128)
    enabled: bool
    built_in: bool
    overridden: bool
    pattern: str = Field(default="", max_length=2048)
    replace: str = Field(default="", max_length=2048)
    default_pattern: str | None = Field(default=None, max_length=2048)
    default_replace: str | None = Field(default=None, max_length=2048)


class MagicRegexRuleListOut(BaseModel):
    rules: list[MagicRegexRuleItemOut] = []


def validate_magic_regex_key(value: str) -> str:
    value = str(value or "").strip()
    if not value.startswith("$"):
        raise ValueError("key 必须以 $ 开头")
    if " " in value:
        raise ValueError("key 不能包含空格")
    if len(value) > 64:
        raise ValueError("key 长度不能超过 64")
    return value


class MagicRegexRuleCreateIn(MagicRegexRuleUpsertIn):
    key: str = Field(min_length=1, max_length=64)

    _validate_key = field_validator("key")(validate_magic_regex_key)

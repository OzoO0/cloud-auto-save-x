from __future__ import annotations

from pydantic import BaseModel, Field


class TMDBConfigOut(BaseModel):
    has_api_key: bool = False
    language: str = Field(default="zh-CN", max_length=32)
    poster_language: str = Field(default="zh-CN", max_length=32)
    disable_guessit_tmdb_fallback_rename: bool = False
    guessit_tmdb_tv_rename_template: str = Field(default="", max_length=512)
    guessit_tmdb_movie_rename_template: str = Field(default="", max_length=512)


class TMDBConfigUpdateIn(BaseModel):
    api_key: str | None = Field(default=None, max_length=256)
    language: str | None = Field(default=None, max_length=32)
    poster_language: str | None = Field(default=None, max_length=32)
    disable_guessit_tmdb_fallback_rename: bool | None = None
    guessit_tmdb_tv_rename_template: str | None = Field(default=None, max_length=512)
    guessit_tmdb_movie_rename_template: str | None = Field(default=None, max_length=512)

from __future__ import annotations

from pydantic import BaseModel, Field


class DoubanSubCategoryOut(BaseModel):
    key: str
    label: str


class DoubanCategoryOut(BaseModel):
    key: str
    label: str
    media_type: str
    subs: list[DoubanSubCategoryOut] = []


class DoubanCategoryListOut(BaseModel):
    categories: list[DoubanCategoryOut] = []


class TMDBBriefOut(BaseModel):
    id: int | None = None
    media_type: str
    title: str | None = None
    original_title: str | None = None
    release_date: str | None = None
    name: str | None = None
    original_name: str | None = None
    first_air_date: str | None = None
    overview: str | None = None
    poster_path: str | None = None
    vote_average: float | None = None


class DoubanRatingOut(BaseModel):
    value: float | None = None


class DoubanPicOut(BaseModel):
    normal: str | None = None


class MediaDiscoverItemOut(BaseModel):
    id: str = ""
    title: str
    year: str | None = None
    url: str | None = None
    pic: DoubanPicOut | None = None
    rating: DoubanRatingOut | None = None
    card_subtitle: str | None = None
    tmdb: TMDBBriefOut | None = None


class MediaDiscoverListOut(BaseModel):
    success: bool = True
    message: str | None = None
    notice: str | None = None
    tmdb_configured: bool = False
    is_mock_data: bool | None = None
    mock_reason: str | None = None
    total: int = 0
    items: list[MediaDiscoverItemOut] = []


class TMDBSearchListOut(BaseModel):
    configured: bool = False
    page: int = 1
    total_pages: int = 0
    total_results: int = 0
    items: list[TMDBBriefOut] = []


class TMDBDetailOut(BaseModel):
    media_type: str = Field(min_length=1, max_length=8)
    data: dict = {}
    update_weekdays: list[int] = []
    episode_weekdays: list[int] = []

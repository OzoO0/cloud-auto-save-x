from __future__ import annotations

from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from typing import Any, Literal

from cachetools import TTLCache
from sqlalchemy.orm import Session

from app.services.tmdb_cache import get_tmdb_detail_cached
from app.services.tmdb_settings import get_or_create_tmdb_setting, get_tmdb_runtime_config
from app.thirdparty.douban_client import DoubanClient
from app.thirdparty.tmdb_client import TMDBClient


_douban_client = DoubanClient()
_match_cache: TTLCache[tuple[str, str, str], dict[str, Any] | None] = TTLCache(maxsize=5000, ttl=60 * 60 * 12)
_executor = ThreadPoolExecutor(max_workers=6)


MediaType = Literal["movie", "tv"]


def list_douban_categories() -> list[dict[str, Any]]:
    raw = _douban_client.get_categories()
    out: list[dict[str, Any]] = []
    for key, item in raw.items():
        out.append(
            {
                "key": key,
                "label": item.get("label"),
                "media_type": item.get("media_type"),
                "subs": [{"key": x, "label": x} for x in (item.get("subs") or [])],
            }
        )
    return out


def _get_media_type(main_category: str) -> MediaType:
    if main_category.startswith("movie_"):
        return "movie"
    return "tv"


def fetch_douban_list(*, main_category: str, sub_category: str, start: int = 0, limit: int = 20) -> dict[str, Any]:
    return _douban_client.get_list_data(main_category, sub_category, start=start, limit=limit)


def _pick_best_by_year(results: list[dict[str, Any]], *, media_type: MediaType, year: str | None) -> dict[str, Any] | None:
    if not results:
        return None
    y = str(year or "").strip()
    if not y:
        return results[0]
    date_key = "release_date" if media_type == "movie" else "first_air_date"
    for item in results:
        d = str(item.get(date_key) or "")
        if d.startswith(y):
            return item
    return results[0]


def _to_tmdb_brief(item: dict[str, Any], *, media_type: MediaType) -> dict[str, Any]:
    if media_type == "movie":
        return {
            "id": item.get("id"),
            "media_type": "movie",
            "title": item.get("title"),
            "original_title": item.get("original_title"),
            "overview": item.get("overview"),
            "poster_path": item.get("poster_path"),
            "vote_average": item.get("vote_average"),
            "release_date": item.get("release_date"),
        }
    return {
        "id": item.get("id"),
        "media_type": "tv",
        "name": item.get("name"),
        "original_name": item.get("original_name"),
        "overview": item.get("overview"),
        "poster_path": item.get("poster_path"),
        "vote_average": item.get("vote_average"),
        "first_air_date": item.get("first_air_date"),
    }


def _match_one(
    client: TMDBClient,
    *,
    media_type: MediaType,
    title: str,
    year: str | None,
) -> dict[str, Any] | None:
    key = (media_type, title, str(year or ""))
    cached = _match_cache.get(key)
    if cached is not None or key in _match_cache:
        return cached

    if media_type == "movie":
        results = client.search_movie_all(title, year=year)
    else:
        results = client.search_tv_all(title, year=year)
    best = _pick_best_by_year(results, media_type=media_type, year=year)
    brief = _to_tmdb_brief(best, media_type=media_type) if best else None
    _match_cache[key] = brief
    return brief


def enrich_douban_items(db: Session, *, main_category: str, items: list[dict[str, Any]]) -> tuple[bool, list[dict[str, Any]]]:
    setting = get_or_create_tmdb_setting(db)
    cfg = get_tmdb_runtime_config(setting)
    api_key = str(cfg.get("api_key") or "").strip()
    if not api_key:
        return False, [{**x, "tmdb": None} for x in items]

    language = str(cfg.get("language") or "zh-CN")
    client = TMDBClient(api_key, language=language)
    media_type = _get_media_type(main_category)

    futures = {}
    for i, item in enumerate(items):
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        year = str(item.get("year") or "").strip() or None
        futures[_executor.submit(_match_one, client, media_type=media_type, title=title, year=year)] = i

    enriched = list(items)
    for f in as_completed(futures):
        idx = futures[f]
        try:
            tmdb = f.result()
        except Exception:
            tmdb = None
        enriched[idx] = {**enriched[idx], "tmdb": tmdb}
    for i, item in enumerate(enriched):
        if "tmdb" not in item:
            enriched[i] = {**item, "tmdb": None}
    return True, enriched


def tmdb_search(
    db: Session, *, q: str, search_type: str = "multi", page: int = 1, year: str | None = None
) -> tuple[bool, list[dict[str, Any]], int, int, int]:
    setting = get_or_create_tmdb_setting(db)
    cfg = get_tmdb_runtime_config(setting)
    api_key = str(cfg.get("api_key") or "").strip()
    if not api_key:
        return False, [], 1, 0, 0
    language = str(cfg.get("language") or "zh-CN")
    client = TMDBClient(api_key, language=language)

    st = str(search_type or "multi").strip().lower()
    if st == "movie":
        raw = client.search_movie_page(q, year=year, page=page)
        results = list(raw.get("results") or [])
        out = [_to_tmdb_brief(x, media_type="movie") for x in results]
        return True, out, int(raw.get("page") or page), int(raw.get("total_pages") or 0), int(raw.get("total_results") or 0)
    if st == "tv":
        raw = client.search_tv_page(q, year=year, page=page)
        results = list(raw.get("results") or [])
        out = [_to_tmdb_brief(x, media_type="tv") for x in results]
        return True, out, int(raw.get("page") or page), int(raw.get("total_pages") or 0), int(raw.get("total_results") or 0)

    raw = client.search_multi_page(q, page=page)
    results = list(raw.get("results") or [])
    out: list[dict[str, Any]] = []
    for item in results:
        t = str(item.get("media_type") or "").strip()
        if t not in ("movie", "tv"):
            continue
        out.append(_to_tmdb_brief(item, media_type=t))  # type: ignore[arg-type]
    return True, out, int(raw.get("page") or page), int(raw.get("total_pages") or 0), int(raw.get("total_results") or 0)


def tmdb_detail(
    db: Session,
    *,
    media_type: MediaType,
    tmdb_id: int,
) -> tuple[bool, dict[str, Any] | None, list[int], list[int]]:
    configured, data, update_weekdays, episode_weekdays, _row = get_tmdb_detail_cached(db, media_type=media_type, tmdb_id=tmdb_id)
    return configured, data, update_weekdays, episode_weekdays


def _infer_tv_update_weekdays(tv_id: int, details: dict[str, Any], client: TMDBClient) -> list[int]:
    def parse_day(value: Any) -> int | None:
        try:
            ds = str(value or "").strip()
            if not ds:
                return None
            return date.fromisoformat(ds).isoweekday()
        except Exception:
            return None

    next_episode = details.get("next_episode_to_air")
    next_day = parse_day(next_episode.get("air_date") if isinstance(next_episode, dict) else None)

    last_ep = details.get("last_episode_to_air")
    season_number = int(last_ep.get("season_number") or 0) if isinstance(last_ep, dict) else 0
    if season_number <= 0:
        seasons = details.get("seasons") if isinstance(details.get("seasons"), list) else []
        best = 0
        for s in seasons:
            if not isinstance(s, dict):
                continue
            n = int(s.get("season_number") or 0)
            if n > best:
                best = n
        season_number = best

    weekdays: list[int] = []
    if season_number > 0:
        season = client.get_tv_season(tv_id, season_number) or {}
        episodes = season.get("episodes") if isinstance(season.get("episodes"), list) else []
        air_dates: list[str] = []
        for ep in episodes:
            if not isinstance(ep, dict):
                continue
            ad = str(ep.get("air_date") or "").strip()
            if ad:
                air_dates.append(ad)
        air_dates.sort()
        for ad in air_dates[-10:]:
            d = parse_day(ad)
            if d is not None:
                weekdays.append(d)

    if next_day is not None:
        weekdays.append(next_day)

    if not weekdays:
        return []

    total = len(weekdays)
    counts = Counter(weekdays)
    most_day, most_count = counts.most_common(1)[0]
    picked: list[int] = []
    if total >= 4 and (most_count / total) >= 0.6:
        picked = [int(most_day)]
    else:
        for d, c in counts.most_common():
            if c >= 2 and (c / total) >= 0.2:
                picked.append(int(d))
        if not picked:
            picked = list({int(x) for x in weekdays})

    picked = sorted({int(x) for x in picked if 1 <= int(x) <= 7})
    return picked[:3]

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.models.tmdb_setting import TMDBSetting


DEFAULT_TMDB_SETTING_ID = 1
DEFAULT_GUESSIT_TMDB_TV_RENAME_TEMPLATE = "{title}.S{season}E{episode}{ext}"
DEFAULT_GUESSIT_TMDB_MOVIE_RENAME_TEMPLATE = "{title_dot}.{year}{ext}"


def get_or_create_tmdb_setting(db: Session) -> TMDBSetting:
    item = db.get(TMDBSetting, DEFAULT_TMDB_SETTING_ID)
    if item is not None:
        return item
    item = TMDBSetting(id=DEFAULT_TMDB_SETTING_ID, config_json=json.dumps({}, ensure_ascii=False))
    db.add(item)
    db.flush()
    return item


def _load_json(payload: str | None) -> dict[str, Any]:
    if not payload:
        return {}
    try:
        data = json.loads(payload)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def load_tmdb_config(item: TMDBSetting) -> dict[str, Any]:
    raw = _load_json(item.config_json)
    api_key = str(raw.get("api_key") or "").strip()
    disable_guessit = bool(raw.get("disable_guessit_tmdb_fallback_rename") or False) if api_key else False
    tv_tpl = str(raw.get("guessit_tmdb_tv_rename_template") or "").strip() or DEFAULT_GUESSIT_TMDB_TV_RENAME_TEMPLATE
    movie_tpl = str(raw.get("guessit_tmdb_movie_rename_template") or "").strip() or DEFAULT_GUESSIT_TMDB_MOVIE_RENAME_TEMPLATE
    return {
        "has_api_key": bool(api_key),
        "language": str(raw.get("language") or "zh-CN"),
        "poster_language": str(raw.get("poster_language") or "zh-CN"),
        "disable_guessit_tmdb_fallback_rename": disable_guessit,
        "guessit_tmdb_tv_rename_template": tv_tpl,
        "guessit_tmdb_movie_rename_template": movie_tpl,
    }


def get_tmdb_runtime_config(item: TMDBSetting) -> dict[str, Any]:
    raw = _load_json(item.config_json)
    api_key = str(raw.get("api_key") or "").strip()
    disable_guessit = bool(raw.get("disable_guessit_tmdb_fallback_rename") or False) if api_key else False
    tv_tpl = str(raw.get("guessit_tmdb_tv_rename_template") or "").strip() or DEFAULT_GUESSIT_TMDB_TV_RENAME_TEMPLATE
    movie_tpl = str(raw.get("guessit_tmdb_movie_rename_template") or "").strip() or DEFAULT_GUESSIT_TMDB_MOVIE_RENAME_TEMPLATE
    return {
        "api_key": api_key,
        "language": str(raw.get("language") or "zh-CN"),
        "poster_language": str(raw.get("poster_language") or "zh-CN"),
        "disable_guessit_tmdb_fallback_rename": disable_guessit,
        "guessit_tmdb_tv_rename_template": tv_tpl,
        "guessit_tmdb_movie_rename_template": movie_tpl,
    }


def update_tmdb_setting(db: Session, *, payload: dict[str, Any] | None = None) -> TMDBSetting:
    item = get_or_create_tmdb_setting(db)
    if payload is None:
        return item

    raw = _load_json(item.config_json)

    if "language" in payload and payload.get("language") is not None:
        raw["language"] = str(payload.get("language") or "").strip() or "zh-CN"

    if "poster_language" in payload and payload.get("poster_language") is not None:
        raw["poster_language"] = str(payload.get("poster_language") or "").strip() or "zh-CN"

    if "api_key" in payload:
        api_key = payload.get("api_key")
        if api_key is not None:
            value = str(api_key).strip()
            if value:
                raw["api_key"] = value

    if "disable_guessit_tmdb_fallback_rename" in payload and payload.get("disable_guessit_tmdb_fallback_rename") is not None:
        api_key = str(raw.get("api_key") or "").strip()
        raw["disable_guessit_tmdb_fallback_rename"] = bool(payload.get("disable_guessit_tmdb_fallback_rename")) if api_key else False

    if "guessit_tmdb_tv_rename_template" in payload and payload.get("guessit_tmdb_tv_rename_template") is not None:
        raw["guessit_tmdb_tv_rename_template"] = str(payload.get("guessit_tmdb_tv_rename_template") or "").strip() or DEFAULT_GUESSIT_TMDB_TV_RENAME_TEMPLATE

    if "guessit_tmdb_movie_rename_template" in payload and payload.get("guessit_tmdb_movie_rename_template") is not None:
        raw["guessit_tmdb_movie_rename_template"] = (
            str(payload.get("guessit_tmdb_movie_rename_template") or "").strip() or DEFAULT_GUESSIT_TMDB_MOVIE_RENAME_TEMPLATE
        )

    if not str(raw.get("api_key") or "").strip():
        raw["disable_guessit_tmdb_fallback_rename"] = False

    item.config_json = json.dumps(raw, ensure_ascii=False)
    db.flush()
    return item

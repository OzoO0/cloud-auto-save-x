from __future__ import annotations

import json
import logging
import os
import re
from functools import lru_cache


logger = logging.getLogger(__name__)

_RE_CJK = re.compile(r"[\u4e00-\u9fff]+")
_RE_SPECIAL = re.compile(r"[\|\%\$]+")
_RE_INVALID_FS = re.compile(r'[\\/:*?"<>|]+')
_RE_SPACES = re.compile(r"\s+")

_TRACE = os.getenv("DEBUG", "0").strip().lower() in {"1", "true", "yes", "y", "on"}

def _max_episode_number() -> int:
    raw = str(os.getenv("XXM_GUESSIT_MAX_EPISODE") or "").strip()
    if not raw:
        return 9999
    try:
        n = int(raw)
    except Exception:
        return 9999
    if n < 1:
        return 9999
    if n > 999999:
        return 999999
    return n


_MAX_EPISODE_NUMBER = _max_episode_number()

_VIDEO_EXTS = {
    ".mp4",
    ".mkv",
    ".avi",
    ".mov",
    ".wmv",
    ".flv",
    ".webm",
    ".m4v",
    ".ts",
    ".m2ts",
    ".mpg",
    ".mpeg",
    ".3gp",
    ".cas",
}


class _SafeDict(dict):
    def __missing__(self, key: object) -> str:
        return ""


def _join_guessit_value(value: object, *, sep: str = ".") -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        parts = []
        for x in value:
            s = str(x or "").strip()
            if s:
                parts.append(s)
        return sep.join(parts)
    return str(value).strip()


def _build_guessit_tags(info: dict) -> dict[str, str]:
    screen_size = _join_guessit_value(info.get("screen_size"))
    source = _join_guessit_value(info.get("source"))
    video_codec = _join_guessit_value(info.get("video_codec"))
    audio_codec = _join_guessit_value(info.get("audio_codec"))
    audio_channels = _join_guessit_value(info.get("audio_channels"))
    release_group = _join_guessit_value(info.get("release_group"))
    container = _join_guessit_value(info.get("container"))
    language = _join_guessit_value(info.get("language"))
    subtitle_language = _join_guessit_value(info.get("subtitle_language"))
    other = _join_guessit_value(info.get("other"))

    flat = [screen_size, source, video_codec, audio_codec, audio_channels, language, subtitle_language, other, release_group]
    flat = [x for x in flat if x]
    tags_dot = ".".join(flat)
    tags_space = " ".join(flat)
    return {
        "screen_size": screen_size,
        "source": source,
        "video_codec": video_codec,
        "audio_codec": audio_codec,
        "audio_channels": audio_channels,
        "release_group": release_group,
        "container": container,
        "language": language,
        "subtitle_language": subtitle_language,
        "other": other,
        "tags_dot": tags_dot,
        "tags_space": tags_space,
        "tags": tags_dot,
    }


def _trace(tag: str | None, message: str) -> None:
    if not _TRACE:
        return
    prefix = "[guessit_fallback]"
    if tag:
        prefix = f"{prefix}[{tag}]"
    logger.debug("%s %s", prefix, message)


def sanitize_for_guessit(name: str) -> str:
    s = str(name or "")
    s = _RE_CJK.sub(" ", s)
    s = _RE_SPECIAL.sub(" ", s)
    s = _RE_INVALID_FS.sub(" ", s)
    s = _RE_SPACES.sub(" ", s).strip()
    return s


def _clean_title(title: str) -> str:
    s = str(title or "")
    s = _RE_INVALID_FS.sub(" ", s)
    s = _RE_SPACES.sub(" ", s).strip()
    return s.strip(".")


def _dot_title(title: str) -> str:
    s = _clean_title(title)
    if not s:
        return ""
    s = s.replace(" ", ".")
    s = re.sub(r"\.+", ".", s).strip(".")
    return s


def _pick_episode(value: object) -> int | None:
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, list):
        eps = []
        for x in value:
            if isinstance(x, int) and x > 0:
                eps.append(x)
        return min(eps) if eps else None
    return None


def _pick_leading_episode(base: str) -> int | None:
    s = sanitize_for_guessit(base)
    if not s:
        return None
    m = re.match(r"^\s*(\d{1,4})\s*(?:[-._\s]+|$)", s)
    if not m:
        return None
    try:
        ep = int(m.group(1))
    except Exception:
        return None
    if ep <= 0 or ep > _MAX_EPISODE_NUMBER:
        return None
    return ep


_DEFAULT_STRICT_KNOWN_EP_PATTERNS = [
    r"^\s*(\d{1,4})\s*[\s._\-\\/／~]+\s*(?:4k|8k|2160p|1080p|720p)(?:[\s._\-\\/／].*)?$",
    r"^\s*(\d{1,4})\s*$",
]


def _load_strict_known_ep_patterns() -> list[str]:
    raw = str(os.getenv("XXM_GUESSIT_STRICT_KNOWN_EP_PATTERNS") or "").strip()
    if not raw:
        return list(_DEFAULT_STRICT_KNOWN_EP_PATTERNS)

    if raw.startswith("["):
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                out: list[str] = []
                for x in data:
                    s = str(x or "").strip()
                    if s:
                        out.append(s)
                if out:
                    return out
        except Exception:
            pass

    parts: list[str] = []
    for p in re.split(r"(?:\r?\n|;;)+", raw):
        s = str(p or "").strip()
        if s:
            parts.append(s)
    return parts or list(_DEFAULT_STRICT_KNOWN_EP_PATTERNS)


def _compile_strict_known_ep_rules() -> list[re.Pattern[str]]:
    rules: list[re.Pattern[str]] = []
    for p in _load_strict_known_ep_patterns():
        try:
            rules.append(re.compile(p, re.IGNORECASE))
        except Exception:
            continue
    return rules


_RE_STRICT_KNOWN_EP_RULES = _compile_strict_known_ep_rules()


def _pick_known_episode_strict_detail(base: str) -> tuple[int | None, str | None]:
    origin = str(base or "").strip()
    if not origin:
        return None, None
    s = origin
    root, ext = os.path.splitext(origin)
    if root and ext and ext.lower() in _VIDEO_EXTS:
        s = root.strip()
    if not s:
        return None, None
    for rule in _RE_STRICT_KNOWN_EP_RULES:
        m = rule.match(s)
        if not m:
            continue
        try:
            ep = int(m.group(1))
        except Exception:
            continue
        if ep <= 0 or ep > _MAX_EPISODE_NUMBER:
            continue
        return ep, None
    return None, None


def _pick_known_episode_strict(base: str) -> int | None:
    ep, _ = _pick_known_episode_strict_detail(base)
    return ep


def _map_absolute_episode_to_season(abs_episode: int, tv_seasons: list[dict] | None) -> int | None:
    if not tv_seasons or abs_episode <= 0:
        return None
    seasons: list[tuple[int, int]] = []
    for raw in tv_seasons:
        if not isinstance(raw, dict):
            continue
        sn = raw.get("season_number")
        ec = raw.get("episode_count")
        if not isinstance(sn, int) or not isinstance(ec, int):
            continue
        if sn <= 0 or ec <= 0:
            continue
        seasons.append((sn, ec))
    if not seasons:
        return None
    seasons.sort(key=lambda x: x[0])
    remaining = abs_episode
    for sn, ec in seasons:
        if remaining <= ec:
            return sn
        remaining -= ec
    return None


def _pick_latest_season(tv_seasons: list[dict] | None) -> tuple[int, int] | None:
    if not tv_seasons:
        return None
    seasons: list[tuple[int, int]] = []
    for raw in tv_seasons:
        if not isinstance(raw, dict):
            continue
        sn = raw.get("season_number")
        ec = raw.get("episode_count")
        if not isinstance(sn, int) or not isinstance(ec, int):
            continue
        if sn <= 0 or ec <= 0:
            continue
        seasons.append((sn, ec))
    if not seasons:
        return None
    seasons.sort(key=lambda x: x[0])
    return seasons[-1]


def _pick_year(value: object) -> int | None:
    try:
        y = int(value) if value is not None else 0
    except Exception:
        return None
    if y < 1900 or y > 2100:
        return None
    return y


@lru_cache(maxsize=4096)
def _guessit_parse(
    sanitized: str,
    *,
    media_type: str | None = None,
    trace_tag: str | None = None,
) -> dict:
    try:
        from guessit import guessit
    except Exception as exc:
        _trace(trace_tag, f"error: import guessit failed: {type(exc).__name__}: {exc}")
        return {}

    mt = str(media_type or "").strip().lower()
    try:
        if mt == "tv":
            info = guessit(sanitized) or {}
            if str(info.get("type") or "").lower() == "episode":
                return info
            return guessit(sanitized, options={"type": "episode"}) or {}
        if mt == "movie":
            return guessit(sanitized, options={"type": "movie"}) or {}
        return guessit(sanitized) or {}
    except Exception as exc:
        _trace(trace_tag, f"error: guessit() failed: {type(exc).__name__}: {exc}")
        return {}


def guessit_episode_target(
    file_name: str,
    *,
    series_title: str | None = None,
    tv_seasons: list[dict] | None = None,
    rename_template: str | None = None,
    trace_tag: str | None = None,
) -> str | None:
    origin = str(file_name or "").strip()
    _trace(trace_tag, f"start file_name={origin!r} series_title={str(series_title or '').strip()!r} tv_seasons={len(tv_seasons or [])}")
    base, ext = os.path.splitext(origin)
    if not base or not ext:
        _trace(trace_tag, "skip: missing base/ext")
        return None
    if ext.lower() not in _VIDEO_EXTS:
        _trace(trace_tag, f"skip: non-video ext={ext.lower()!r}")
        return None

    strict_known_episode, _ = _pick_known_episode_strict_detail(base)
    if strict_known_episode is not None:
        _trace(trace_tag, f"match strict-known pattern -> episode={strict_known_episode!r}")

    sanitized = sanitize_for_guessit(base)
    _trace(trace_tag, f"sanitize base={base!r} -> sanitized={sanitized!r}")
    if not sanitized:
        _trace(trace_tag, "skip: sanitized empty")
        return None

    info = _guessit_parse(sanitized, media_type="tv", trace_tag=trace_tag)
    guessed_is_episode = str(info.get("type") or "").lower() == "episode"
    _trace(trace_tag, f"guessit type={str(info.get('type') or '').lower()!r} title={info.get('title')!r} series={info.get('series')!r} season={info.get('season')!r} episode={info.get('episode')!r}")

    season_raw = info.get("season")
    season = int(season_raw) if isinstance(season_raw, int) and season_raw > 0 else 0
    episode = _pick_episode(info.get("episode")) if guessed_is_episode else None
    inferred_abs = False
    if strict_known_episode is not None:
        episode = strict_known_episode
        season = 0
        inferred_abs = True
        _trace(trace_tag, f"episode override strict-known -> season={season!r} episode={episode!r}")
    if episode is None:
        episode = _pick_known_episode_strict(base)
        if episode is not None:
            inferred_abs = True
            _trace(trace_tag, f"episode strict-known -> episode={episode!r}")
        else:
            episode = _pick_leading_episode(base)
            inferred_abs = True
            _trace(trace_tag, f"episode fallback leading-number -> episode={episode!r}")
    if episode is None:
        _trace(trace_tag, "skip: episode not found")
        return None
    if season <= 0:
        mapped_season = None
        if inferred_abs or guessed_is_episode:
            latest = _pick_latest_season(tv_seasons)
            if latest and episode <= latest[1]:
                mapped_season = latest[0]
            else:
                mapped_season = _map_absolute_episode_to_season(episode, tv_seasons)
        if mapped_season:
            season = mapped_season
            _trace(trace_tag, f"season missing -> mapped by tmdb seasons: S{season:02d}E{episode:02d}")
        else:
            if tv_seasons:
                _trace(trace_tag, "skip: season missing and tmdb seasons can't map")
                return None
            season = 1
            _trace(trace_tag, "season missing -> default season=1")

    title = _clean_title(series_title or info.get("title") or info.get("series") or "")
    if not title:
        _trace(trace_tag, "skip: title empty")
        return None

    template = str(rename_template or "").strip() or "{title}.S{season}E{episode}{ext}"
    if "{ext}" not in template:
        template = f"{template}{{ext}}"
    tags = _build_guessit_tags(info)
    origin_full = origin
    origin_base = base
    ctx = _SafeDict(
        {
            "title": title,
            "title_dot": _dot_title(title),
            "season": f"{season:02d}",
            "episode": f"{episode:02d}",
            "season_num": str(season),
            "episode_num": str(episode),
            "year": "",
            "ext": ext,
            "orig": origin_full,
            "orig_base": origin_base,
            "orig_base_dot": _dot_title(origin_base),
            **tags,
        }
    )
    try:
        target = template.format_map(ctx)
    except Exception as exc:
        _trace(trace_tag, f"error: template.format failed: {type(exc).__name__}: {exc}")
        target = f"{title}.S{season:02d}E{episode:02d}{ext}"
    target = _RE_INVALID_FS.sub(" ", str(target or ""))
    target = re.sub(r"\s*\.\s*", ".", target)
    target = re.sub(r"\.{2,}", ".", target)
    target = _RE_SPACES.sub(" ", target).strip()
    if ext and not target.lower().endswith(ext.lower()):
        target = f"{target}{ext}"
    target = target.strip(". ")
    _trace(trace_tag, f"done target={target!r}")
    return target


@lru_cache(maxsize=4096)
def _guessit_episode_numbers_cached(
    sanitized_base: str,
    tv_seasons_tuple: tuple | None,
) -> tuple[int | None, int | None]:
    """Cached implementation - tv_seasons must be tuple or None."""
    tv_seasons = (
        [{"season_number": s, "episode_count": e} for s, e in tv_seasons_tuple]
        if tv_seasons_tuple
        else None
    )
    info = _guessit_parse(sanitized_base, media_type="tv")
    guessed_is_episode = str(info.get("type") or "").lower() == "episode"

    season_raw = info.get("season")
    season = int(season_raw) if isinstance(season_raw, int) and season_raw > 0 else 0
    episode = _pick_episode(info.get("episode")) if guessed_is_episode else None
    inferred_abs = False

    strict_known_episode, _ = _pick_known_episode_strict_detail(sanitized_base)
    if strict_known_episode is not None:
        episode = strict_known_episode
        season = 0
        inferred_abs = True
    if episode is None:
        episode = _pick_known_episode_strict(sanitized_base)
        if episode is not None:
            inferred_abs = True
        else:
            episode = _pick_leading_episode(sanitized_base)
            if episode is not None:
                inferred_abs = True

    if episode is None:
        return None, None

    if season <= 0:
        mapped_season = None
        if inferred_abs or guessed_is_episode:
            latest = _pick_latest_season(tv_seasons)
            if latest and episode <= latest[1]:
                mapped_season = latest[0]
            else:
                mapped_season = _map_absolute_episode_to_season(episode, tv_seasons)
        if mapped_season:
            season = mapped_season
        else:
            if tv_seasons:
                return None, None
            season = 1

    if season <= 0 or episode <= 0:
        return None, None
    return season, episode


@lru_cache(maxsize=4096)
def _guessit_title_episode_numbers_cached(
    sanitized_title: str,
    tv_seasons_tuple: tuple | None,
) -> tuple[int | None, int | None]:
    """Parse season/episode from a share title without requiring a video extension."""
    tv_seasons = (
        [{"season_number": s, "episode_count": e} for s, e in tv_seasons_tuple]
        if tv_seasons_tuple
        else None
    )
    info = _guessit_parse(sanitized_title, media_type="tv")
    guessed_is_episode = str(info.get("type") or "").lower() == "episode"
    if not guessed_is_episode:
        return None, None

    season_raw = info.get("season")
    season = int(season_raw) if isinstance(season_raw, int) and season_raw > 0 else 0
    episode = _pick_episode(info.get("episode"))
    if episode is None:
        return None, None

    if season <= 0:
        mapped_season = None
        latest = _pick_latest_season(tv_seasons)
        if latest and episode <= latest[1]:
            mapped_season = latest[0]
        else:
            mapped_season = _map_absolute_episode_to_season(episode, tv_seasons)
        if mapped_season:
            season = mapped_season
        else:
            if tv_seasons:
                return None, None
            season = 1

    if season <= 0 or episode <= 0:
        return None, None
    return season, episode


def guessit_episode_numbers(
    file_name: str,
    *,
    tv_seasons: list[dict] | None = None,
    trace_tag: str | None = None,
) -> tuple[int | None, int | None]:
    origin = str(file_name or "").strip()
    base, ext = os.path.splitext(origin)
    if not base or not ext:
        return None, None
    if ext.lower() not in _VIDEO_EXTS:
        return None, None

    sanitized = sanitize_for_guessit(base)
    _trace(trace_tag, f"file sanitize origin={origin!r} -> sanitized={sanitized!r}")
    if not sanitized:
        return None, None

    # Convert tv_seasons to hashable tuple for caching
    if tv_seasons:
        tv_seasons_tuple = tuple(
            (s.get("season_number", 0), s.get("episode_count", 0))
            for s in tv_seasons
            if isinstance(s, dict)
        )
    else:
        tv_seasons_tuple = None

    return _guessit_episode_numbers_cached(sanitized, tv_seasons_tuple)


def guessit_title_episode_numbers(
    title: str,
    *,
    tv_seasons: list[dict] | None = None,
    trace_tag: str | None = None,
) -> tuple[int | None, int | None]:
    origin = str(title or "").strip()
    if not origin:
        return None, None

    sanitized = sanitize_for_guessit(origin)
    _trace(trace_tag, f"title sanitize origin={origin!r} -> sanitized={sanitized!r}")
    if not sanitized:
        return None, None

    if tv_seasons:
        tv_seasons_tuple = tuple(
            (s.get("season_number", 0), s.get("episode_count", 0))
            for s in tv_seasons
            if isinstance(s, dict)
        )
    else:
        tv_seasons_tuple = None

    return _guessit_title_episode_numbers_cached(sanitized, tv_seasons_tuple)


def guessit_media_target(
    file_name: str,
    *,
    media_type: str | None = None,
    tmdb_title: str | None = None,
    tmdb_year: int | None = None,
    tv_seasons: list[dict] | None = None,
    tv_rename_template: str | None = None,
    movie_rename_template: str | None = None,
    trace_tag: str | None = None,
) -> str | None:
    mt = str(media_type or "").strip().lower()
    if mt not in {"movie", "tv"}:
        mt = "tv"
    if mt == "tv":
        return guessit_episode_target(
            file_name,
            series_title=tmdb_title,
            tv_seasons=tv_seasons,
            rename_template=tv_rename_template,
            trace_tag=trace_tag,
        )

    origin = str(file_name or "").strip()
    _trace(trace_tag, f"start(movie) file_name={origin!r} tmdb_title={str(tmdb_title or '').strip()!r} tmdb_year={tmdb_year!r}")
    base, ext = os.path.splitext(origin)
    if not base or not ext:
        _trace(trace_tag, "skip(movie): missing base/ext")
        return None
    if ext.lower() not in _VIDEO_EXTS:
        _trace(trace_tag, f"skip(movie): non-video ext={ext.lower()!r}")
        return None

    sanitized = sanitize_for_guessit(base)
    _trace(trace_tag, f"sanitize(movie) base={base!r} -> sanitized={sanitized!r}")
    if not sanitized:
        _trace(trace_tag, "skip(movie): sanitized empty")
        return None

    info = _guessit_parse(sanitized, media_type="movie", trace_tag=trace_tag)
    _trace(trace_tag, f"guessit(movie) type={str(info.get('type') or '').lower()!r} title={info.get('title')!r} year={info.get('year')!r}")
    if str(info.get("type") or "").lower() != "movie":
        _trace(trace_tag, "skip(movie): guessit type is not movie")
        return None

    title = _clean_title(tmdb_title or info.get("title") or info.get("movie") or "")
    if not title:
        _trace(trace_tag, "skip(movie): title empty")
        return None

    year = _pick_year(tmdb_year) or _pick_year(info.get("year"))
    dot = _dot_title(title)
    template = str(movie_rename_template or "").strip() or "{title_dot}.{year}{ext}"
    if "{ext}" not in template:
        template = f"{template}{{ext}}"
    tags = _build_guessit_tags(info)
    origin_full = origin
    origin_base = base
    ctx = _SafeDict(
        {
            "title": title,
            "title_dot": dot,
            "season": "",
            "episode": "",
            "season_num": "",
            "episode_num": "",
            "year": str(year) if year else "",
            "ext": ext,
            "orig": origin_full,
            "orig_base": origin_base,
            "orig_base_dot": _dot_title(origin_base),
            **tags,
        }
    )
    try:
        target = template.format_map(ctx)
    except Exception as exc:
        _trace(trace_tag, f"error: movie template.format failed: {type(exc).__name__}: {exc}")
        target = f"{dot}.{year}{ext}" if year else f"{dot}{ext}"
    target = _RE_INVALID_FS.sub(" ", str(target or ""))
    target = re.sub(r"\s*\.\s*", ".", target)
    target = re.sub(r"\.{2,}", ".", target)
    target = _RE_SPACES.sub(" ", target).strip()
    target = re.sub(r"\.(?:\s*\.)+", ".", target)
    target = re.sub(r"\(\s*\)", "", target).strip()
    if ext and not target.lower().endswith(ext.lower()):
        target = f"{target}{ext}"
    target = target.strip(". ")
    _trace(trace_tag, f"done(movie) target={target!r}")
    return target

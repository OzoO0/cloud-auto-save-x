from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import and_, delete, exists, func, or_, select, update
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.task import Task
from app.models.tmdb_media_cache import TMDBMediaCache
from app.services.tmdb_settings import get_or_create_tmdb_setting, get_tmdb_runtime_config
from app.thirdparty.tmdb_client import TMDBClient


MediaType = Literal["movie", "tv"]

_executor = ThreadPoolExecutor(max_workers=4)
_lock_timeout = timedelta(minutes=10)


def _now() -> datetime:
    return datetime.now()


def _load_json(payload: str | None) -> Any:
    if not payload:
        return None
    try:
        return json.loads(payload)
    except Exception:
        return None


def _dump_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False)


def _pick_date(value: Any) -> str | None:
    v = str(value or "").strip()
    return v or None


def _pick_year(value: Any) -> str | None:
    d = _pick_date(value)
    if not d or len(d) < 4:
        return None
    y = d[:4]
    return y if y.isdigit() else None


def _parse_date(value: Any) -> date | None:
    try:
        ds = str(value or "").strip()
        if not ds:
            return None
        return date.fromisoformat(ds)
    except Exception:
        return None


def compute_expires_at(details: dict[str, Any], *, media_type: MediaType, now: datetime, fail_count: int = 0) -> datetime:
    if fail_count > 0:
        hours = min((2 ** max(0, fail_count - 1)), 24)
        return now + timedelta(hours=int(hours))

    if media_type == "movie":
        rd = _parse_date(details.get("release_date"))
        if rd is not None:
            if abs((rd - now.date()).days) <= 90:
                return now + timedelta(days=7)
        return now + timedelta(days=30)

    status = str(details.get("status") or "").strip()
    if status in ("Returning Series", "In Production"):
        next_ep = details.get("next_episode_to_air") if isinstance(details.get("next_episode_to_air"), dict) else None
        next_day = _parse_date(next_ep.get("air_date") if isinstance(next_ep, dict) else None)
        if next_day is not None and 0 <= (next_day - now.date()).days <= 14:
            return now + timedelta(hours=6)
        return now + timedelta(hours=12)
    if status in ("Ended", "Canceled"):
        return now + timedelta(days=30)
    return now + timedelta(hours=24)


def _infer_weekdays_from_weekday_samples(weekdays: list[int]) -> list[int]:
    samples = [int(x) for x in weekdays if 1 <= int(x) <= 7]
    if not samples:
        return []
    unique = sorted({int(x) for x in samples if 1 <= int(x) <= 7})
    total = len(samples)
    decay = 0.9
    raw_counts: dict[int, int] = {}
    weighted_counts: dict[int, float] = {}
    weighted_total = 0.0
    for i, day in enumerate(samples):
        age = (total - 1) - i
        w = float(decay**age)
        weighted_total += w
        raw_counts[int(day)] = int(raw_counts.get(int(day), 0)) + 1
        weighted_counts[int(day)] = float(weighted_counts.get(int(day), 0.0)) + w

    most_day, most_weight = max(weighted_counts.items(), key=lambda x: x[1])
    picked: list[int] = []
    if total >= 4 and weighted_total > 0 and (most_weight / weighted_total) >= 0.6:
        picked = [int(most_day)]
    else:
        for d, w in sorted(weighted_counts.items(), key=lambda x: x[1], reverse=True):
            if int(raw_counts.get(int(d), 0)) >= 2 and weighted_total > 0 and (w / weighted_total) >= 0.2:
                picked.append(int(d))
        if not picked:
            picked = list({int(x) for x in samples})

    picked = sorted({int(x) for x in picked if 1 <= int(x) <= 7})
    if total >= 7 and len(unique) >= 5 and weighted_total > 0 and (most_weight / weighted_total) <= 0.4:
        return unique
    return picked[:3]


def infer_tv_episode_weekdays_from_details(details: dict[str, Any]) -> list[int]:
    def compute(*, season_number: int | None) -> list[int]:
        out: list[date] = []
        seen: set[date] = set()

        seasons_full = details.get("seasons_full") if isinstance(details.get("seasons_full"), list) else []
        for s in seasons_full:
            if not isinstance(s, dict):
                continue
            try:
                sn = int(s.get("season_number") or 0)
            except Exception:
                sn = 0
            if sn <= 0:
                continue
            if season_number is not None and sn != int(season_number):
                continue
            episodes = s.get("episodes") if isinstance(s.get("episodes"), list) else []
            for ep in episodes:
                if not isinstance(ep, dict):
                    continue
                dt = _parse_date(ep.get("air_date"))
                if dt is None or dt in seen:
                    continue
                seen.add(dt)
                out.append(dt)

        last_ep = details.get("last_episode_to_air") if isinstance(details.get("last_episode_to_air"), dict) else None
        last_dt = _parse_date(last_ep.get("air_date") if isinstance(last_ep, dict) else None)
        if last_dt is not None and last_dt not in seen:
            seen.add(last_dt)
            out.append(last_dt)

        next_ep = details.get("next_episode_to_air") if isinstance(details.get("next_episode_to_air"), dict) else None
        next_dt = _parse_date(next_ep.get("air_date") if isinstance(next_ep, dict) else None)
        if next_dt is not None and next_dt not in seen:
            seen.add(next_dt)
            out.append(next_dt)

        out.sort()
        if not out:
            return []
        if len(out) > 100:
            out = out[-100:]
        weekdays = [d.isoweekday() for d in out]
        return _infer_weekdays_from_weekday_samples(weekdays)

    last_ep = details.get("last_episode_to_air") if isinstance(details.get("last_episode_to_air"), dict) else None
    last_season_number = int(last_ep.get("season_number") or 0) if isinstance(last_ep, dict) else 0
    if last_season_number > 0:
        picked = compute(season_number=last_season_number)
        if picked:
            return picked
    return compute(season_number=None)


def infer_tv_update_weekdays(tv_id: int, details: dict[str, Any], client: TMDBClient) -> list[int]:
    def parse_weekday(value: Any) -> int | None:
        dt = _parse_date(value)
        return dt.isoweekday() if dt is not None else None

    next_ep = details.get("next_episode_to_air") if isinstance(details.get("next_episode_to_air"), dict) else None
    next_day = parse_weekday(next_ep.get("air_date") if isinstance(next_ep, dict) else None)

    last_ep = details.get("last_episode_to_air") if isinstance(details.get("last_episode_to_air"), dict) else None
    season_number = int(last_ep.get("season_number") or 0) if isinstance(last_ep, dict) else 0
    if season_number <= 0:
        seasons = details.get("seasons") if isinstance(details.get("seasons"), list) else []
        best = 0
        for s in seasons:
            if not isinstance(s, dict):
                continue
            try:
                n = int(s.get("season_number") or 0)
            except Exception:
                continue
            if n > best:
                best = n
        season_number = best

    weekdays: list[int] = []
    if season_number > 0:
        picked = None
        seasons_full = details.get("seasons_full") if isinstance(details.get("seasons_full"), list) else []
        for s in seasons_full:
            if not isinstance(s, dict):
                continue
            try:
                sn = int(s.get("season_number") or 0)
            except Exception:
                continue
            if sn == int(season_number):
                picked = s
                break

        season = picked if isinstance(picked, dict) else (client.get_tv_season(tv_id, season_number) or {})
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
            d = parse_weekday(ad)
            if d is not None:
                weekdays.append(d)

    if next_day is not None:
        weekdays.append(next_day)

    return _infer_weekdays_from_weekday_samples(weekdays)


def _extract_summary(details: dict[str, Any], *, media_type: MediaType) -> dict[str, Any]:
    if media_type == "movie":
        title = str(details.get("title") or "").strip() or None
        original = str(details.get("original_title") or "").strip() or None
        release_date = _pick_date(details.get("release_date"))
        return {
            "display_title": title,
            "original_title": original,
            "year": _pick_year(release_date),
            "status": str(details.get("status") or "").strip() or None,
            "release_date": release_date,
            "poster_path": _pick_date(details.get("poster_path")),
            "vote_average": details.get("vote_average"),
            "vote_count": details.get("vote_count"),
        }

    name = str(details.get("name") or "").strip() or None
    original_name = str(details.get("original_name") or "").strip() or None
    first_air_date = _pick_date(details.get("first_air_date"))
    last_air_date = _pick_date(details.get("last_air_date"))
    next_ep = details.get("next_episode_to_air") if isinstance(details.get("next_episode_to_air"), dict) else None
    next_episode_air_date = _pick_date(next_ep.get("air_date") if isinstance(next_ep, dict) else None)
    return {
        "display_title": name,
        "original_title": original_name,
        "year": _pick_year(first_air_date),
        "status": str(details.get("status") or "").strip() or None,
        "first_air_date": first_air_date,
        "last_air_date": last_air_date,
        "next_episode_air_date": next_episode_air_date,
        "poster_path": _pick_date(details.get("poster_path")),
        "vote_average": details.get("vote_average"),
        "vote_count": details.get("vote_count"),
    }


def _get_runtime_tmdb_config(db: Session) -> tuple[bool, str, str, str]:
    setting = get_or_create_tmdb_setting(db)
    cfg = get_tmdb_runtime_config(setting)
    api_key = str(cfg.get("api_key") or "").strip()
    if not api_key:
        return False, "", "", ""
    language = str(cfg.get("language") or "zh-CN").strip() or "zh-CN"
    poster_language = str(cfg.get("poster_language") or "zh-CN").strip() or "zh-CN"
    return True, api_key, language, poster_language


def _new_tmdb_client(*, api_key: str, language: str) -> TMDBClient:
    return TMDBClient(api_key, language=language)


def _fetch_tmdb_detail(
    client: TMDBClient,
    *,
    media_type: MediaType,
    tmdb_id: int,
    language: str,
    poster_language: str,
) -> tuple[dict[str, Any] | None, list[int], list[int]]:
    if media_type == "movie":
        details = client.get_movie_details(tmdb_id)
    else:
        details = client.get_tv_details(tmdb_id)
    if not details:
        return None, [], []

    if poster_language == "original":
        original_language = str(details.get("original_language") or "")
        if original_language == "zh":
            original_language = "zh-CN"
        if original_language and original_language != language:
            if media_type == "movie":
                alt = client.get_movie_details(tmdb_id, language=original_language)
            else:
                alt = client.get_tv_details(tmdb_id, language=original_language)
            if alt and alt.get("poster_path"):
                details["poster_path"] = alt.get("poster_path")

    update_weekdays: list[int] = []
    episode_weekdays: list[int] = []
    if media_type == "tv":
        seasons = details.get("seasons") if isinstance(details.get("seasons"), list) else []
        season_numbers: list[int] = []
        for s in seasons:
            if not isinstance(s, dict):
                continue
            try:
                sn = int(s.get("season_number"))
            except Exception:
                continue
            if sn >= 0:
                season_numbers.append(sn)
        season_numbers = sorted({int(x) for x in season_numbers})

        seasons_full: list[dict[str, Any]] = []
        failed: list[int] = []
        for sn in season_numbers:
            season = client.get_tv_season(tmdb_id, int(sn))
            if isinstance(season, dict) and season:
                seasons_full.append(season)
            else:
                failed.append(int(sn))
        if seasons_full:
            details["seasons_full"] = seasons_full
            details["seasons_full_meta"] = {"expected": len(season_numbers), "fetched": len(seasons_full), "failed": failed[:50]}
        update_weekdays = infer_tv_update_weekdays(tmdb_id, details, client)
        episode_weekdays = infer_tv_episode_weekdays_from_details(details)
    return details, update_weekdays, episode_weekdays


def _get_cache_row(db: Session, *, media_type: MediaType, tmdb_id: int, language: str, poster_language: str) -> TMDBMediaCache | None:
    return (
        db.execute(
            select(TMDBMediaCache).where(
                TMDBMediaCache.media_type == media_type,
                TMDBMediaCache.tmdb_id == tmdb_id,
                TMDBMediaCache.language == language,
                TMDBMediaCache.poster_language == poster_language,
            )
        )
        .scalars()
        .first()
    )


def _try_acquire_refresh_lock(db: Session, *, row_id: int, now: datetime) -> bool:
    deadline = now - _lock_timeout
    stmt = (
        update(TMDBMediaCache)
        .where(
            TMDBMediaCache.id == row_id,
            or_(
                TMDBMediaCache.refresh_in_progress.is_(False),
                TMDBMediaCache.refresh_started_at.is_(None),
                TMDBMediaCache.refresh_started_at < deadline,
            ),
        )
        .values(refresh_in_progress=True, refresh_started_at=now)
    )
    res = db.execute(stmt)
    return bool(getattr(res, "rowcount", 0))


def _release_refresh_lock(db: Session, *, row_id: int) -> None:
    db.execute(
        update(TMDBMediaCache)
        .where(TMDBMediaCache.id == row_id)
        .values(refresh_in_progress=False, refresh_started_at=None)
    )


def refresh_tmdb_detail_sync(
    db: Session,
    *,
    media_type: MediaType,
    tmdb_id: int,
    language: str,
    poster_language: str,
    force: bool = False,
) -> tuple[TMDBMediaCache | None, dict[str, Any] | None, list[int], list[int]]:
    now = _now()
    row = _get_cache_row(db, media_type=media_type, tmdb_id=tmdb_id, language=language, poster_language=poster_language)
    if row is None:
        row = TMDBMediaCache(media_type=media_type, tmdb_id=tmdb_id, language=language, poster_language=poster_language)
        db.add(row)
        db.flush()

    if not force and row.expires_at is not None and row.expires_at > now and row.payload_json:
        payload = _load_json(row.payload_json)
        stored = _load_json(row.update_weekdays_json) if row.update_weekdays_json else None
        update_weekdays = stored if isinstance(stored, list) else []
        episode_weekdays = (
            infer_tv_episode_weekdays_from_details(payload) if isinstance(payload, dict) and media_type == "tv" else []
        )
        return row, payload if isinstance(payload, dict) else None, update_weekdays, episode_weekdays

    configured, api_key, _, _ = _get_runtime_tmdb_config(db)
    if not configured:
        return row, None, [], []
    client = _new_tmdb_client(api_key=api_key, language=language)

    if not _try_acquire_refresh_lock(db, row_id=row.id, now=now):
        payload = _load_json(row.payload_json)
        stored = _load_json(row.update_weekdays_json) if row.update_weekdays_json else None
        update_weekdays = stored if isinstance(stored, list) else []
        episode_weekdays = (
            infer_tv_episode_weekdays_from_details(payload) if isinstance(payload, dict) and media_type == "tv" else []
        )
        return row, payload if isinstance(payload, dict) else None, update_weekdays, episode_weekdays

    try:
        details, update_weekdays, episode_weekdays = _fetch_tmdb_detail(
            client, media_type=media_type, tmdb_id=tmdb_id, language=language, poster_language=poster_language
        )
        if details is None:
            row.last_error = None
            row.fail_count = 0
            row.fetched_at = now
            row.expires_at = compute_expires_at({}, media_type=media_type, now=now, fail_count=0)
            db.flush()
            return row, None, [], []

        summary = _extract_summary(details, media_type=media_type)
        row.payload_json = _dump_json(details)
        row.update_weekdays_json = _dump_json(update_weekdays)
        row.fetched_at = now
        row.expires_at = compute_expires_at(details, media_type=media_type, now=now, fail_count=0)
        row.fail_count = 0
        row.last_error = None
        for k, v in summary.items():
            setattr(row, k, v)
        db.flush()
        return row, details, update_weekdays, episode_weekdays
    except Exception as e:
        row.fail_count = int(row.fail_count or 0) + 1
        row.last_error = str(e)
        row.expires_at = compute_expires_at({}, media_type=media_type, now=now, fail_count=row.fail_count)
        db.flush()
        payload = _load_json(row.payload_json)
        stored = _load_json(row.update_weekdays_json) if row.update_weekdays_json else None
        update_weekdays = stored if isinstance(stored, list) else []
        episode_weekdays = (
            infer_tv_episode_weekdays_from_details(payload) if isinstance(payload, dict) and media_type == "tv" else []
        )
        return row, payload if isinstance(payload, dict) else None, update_weekdays, episode_weekdays
    finally:
        _release_refresh_lock(db, row_id=row.id)


def _refresh_tmdb_detail_background(media_type: MediaType, tmdb_id: int, language: str, poster_language: str) -> None:
    with SessionLocal() as db:
        row = _get_cache_row(db, media_type=media_type, tmdb_id=tmdb_id, language=language, poster_language=poster_language)
        if row is None:
            refresh_tmdb_detail_sync(db, media_type=media_type, tmdb_id=tmdb_id, language=language, poster_language=poster_language, force=True)
            db.commit()
            return
        refresh_tmdb_detail_sync(db, media_type=media_type, tmdb_id=tmdb_id, language=language, poster_language=poster_language, force=True)
        db.commit()


def trigger_refresh_async(db: Session, *, media_type: MediaType, tmdb_id: int, language: str, poster_language: str) -> None:
    row = _get_cache_row(db, media_type=media_type, tmdb_id=tmdb_id, language=language, poster_language=poster_language)
    if row is None:
        return
    now = _now()
    if row.refresh_in_progress and row.refresh_started_at and row.refresh_started_at > (now - _lock_timeout):
        return
    _executor.submit(_refresh_tmdb_detail_background, media_type, tmdb_id, language, poster_language)


def get_tmdb_detail_cached(
    db: Session,
    *,
    media_type: MediaType,
    tmdb_id: int,
    force_refresh: bool = False,
) -> tuple[bool, dict[str, Any] | None, list[int], list[int], TMDBMediaCache | None]:
    configured, _, language, poster_language = _get_runtime_tmdb_config(db)
    if not configured:
        return False, None, [], [], None

    now = _now()
    row = _get_cache_row(db, media_type=media_type, tmdb_id=tmdb_id, language=language, poster_language=poster_language)
    if row is not None:
        row.last_accessed_at = now
        db.flush()
        if force_refresh:
            row2, details, update_weekdays, episode_weekdays = refresh_tmdb_detail_sync(
                db,
                media_type=media_type,
                tmdb_id=tmdb_id,
                language=language,
                poster_language=poster_language,
                force=True,
            )
            return True, details, update_weekdays, episode_weekdays, row2
        if row.expires_at is not None and row.expires_at > now and row.payload_json:
            payload = _load_json(row.payload_json)
            stored = _load_json(row.update_weekdays_json) if row.update_weekdays_json else None
            update_weekdays = stored if isinstance(stored, list) else []
            episode_weekdays = (
                infer_tv_episode_weekdays_from_details(payload) if isinstance(payload, dict) and media_type == "tv" else []
            )
            return True, payload if isinstance(payload, dict) else None, update_weekdays, episode_weekdays, row
        if row.payload_json:
            trigger_refresh_async(db, media_type=media_type, tmdb_id=tmdb_id, language=language, poster_language=poster_language)
            payload = _load_json(row.payload_json)
            stored = _load_json(row.update_weekdays_json) if row.update_weekdays_json else None
            update_weekdays = stored if isinstance(stored, list) else []
            episode_weekdays = (
                infer_tv_episode_weekdays_from_details(payload) if isinstance(payload, dict) and media_type == "tv" else []
            )
            return True, payload if isinstance(payload, dict) else None, update_weekdays, episode_weekdays, row

    row2, details, update_weekdays, episode_weekdays = refresh_tmdb_detail_sync(
        db,
        media_type=media_type,
        tmdb_id=tmdb_id,
        language=language,
        poster_language=poster_language,
        force=True,
    )
    return True, details, update_weekdays, episode_weekdays, row2


def refresh_linked_tasks(
    db: Session,
    *,
    enabled_only: bool = True,
    max_items: int = 200,
    force: bool = True,
) -> dict[str, int]:
    configured, _, language, poster_language = _get_runtime_tmdb_config(db)
    if not configured:
        return {"configured": 0, "targets": 0, "refreshed": 0}

    stmt = select(Task.tmdb_media_type, Task.tmdb_id).where(Task.tmdb_id.is_not(None))
    if enabled_only:
        stmt = stmt.where(Task.enabled.is_(True))
    pairs = db.execute(stmt).all()

    targets: list[tuple[str, int]] = []
    seen: set[tuple[str, int]] = set()
    for mt, tid in pairs:
        t = str(mt or "").strip().lower()
        if t not in ("movie", "tv"):
            continue
        if tid is None:
            continue
        key = (t, int(tid))
        if key in seen:
            continue
        seen.add(key)
        targets.append(key)

    refreshed = 0
    for t, tid in targets[: max(0, int(max_items))]:
        row, _, _, _ = refresh_tmdb_detail_sync(
            db,
            media_type=t,  # type: ignore[arg-type]
            tmdb_id=tid,
            language=language,
            poster_language=poster_language,
            force=force,
        )
        if row is not None:
            refreshed += 1
    return {"configured": 1, "targets": len(targets), "refreshed": refreshed}


def refresh_expired_cache(
    db: Session,
    *,
    max_items: int = 200,
    force: bool = True,
) -> dict[str, int]:
    configured, _, language, poster_language = _get_runtime_tmdb_config(db)
    if not configured:
        return {"configured": 0, "targets": 0, "refreshed": 0}

    now = _now()
    rows = (
        db.execute(
            select(TMDBMediaCache)
            .where(
                TMDBMediaCache.language == language,
                TMDBMediaCache.poster_language == poster_language,
                or_(TMDBMediaCache.expires_at.is_(None), TMDBMediaCache.expires_at <= now),
            )
            .order_by(TMDBMediaCache.expires_at.asc().nullsfirst())
            .limit(max(1, int(max_items)))
        )
        .scalars()
        .all()
    )

    refreshed = 0
    for row in rows:
        r, _, _, _ = refresh_tmdb_detail_sync(
            db,
            media_type=row.media_type,  # type: ignore[arg-type]
            tmdb_id=int(row.tmdb_id),
            language=language,
            poster_language=poster_language,
            force=force,
        )
        if r is not None:
            refreshed += 1
    return {"configured": 1, "targets": len(rows), "refreshed": refreshed}


def purge_cold_cache(db: Session, *, retention_days: int = 60) -> int:
    cutoff = _now() - timedelta(days=max(1, int(retention_days)))
    referenced = exists(
        select(1).where(and_(Task.tmdb_id == TMDBMediaCache.tmdb_id, Task.tmdb_media_type == TMDBMediaCache.media_type))
    )
    stmt = delete(TMDBMediaCache).where(
        TMDBMediaCache.last_accessed_at.is_not(None),
        TMDBMediaCache.last_accessed_at < cutoff,
        ~referenced,
    )
    res = db.execute(stmt)
    return int(getattr(res, "rowcount", 0) or 0)


def list_cache(
    db: Session,
    *,
    page: int = 1,
    page_size: int = 20,
    media_type: str | None = None,
    q: str | None = None,
    status: str | None = None,
    expired_only: bool = False,
) -> tuple[bool, int, str, str, list[TMDBMediaCache]]:
    configured, _, language, poster_language = _get_runtime_tmdb_config(db)
    if not configured:
        return False, 0, language, poster_language, []

    p = max(1, int(page))
    ps = max(1, min(200, int(page_size)))
    stmt = select(TMDBMediaCache).where(TMDBMediaCache.language == language, TMDBMediaCache.poster_language == poster_language)

    mt = str(media_type or "").strip().lower()
    if mt in ("movie", "tv"):
        stmt = stmt.where(TMDBMediaCache.media_type == mt)

    s = str(status or "").strip()
    if s:
        stmt = stmt.where(TMDBMediaCache.status == s)

    keyword = str(q or "").strip()
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(or_(TMDBMediaCache.display_title.ilike(like), TMDBMediaCache.original_title.ilike(like)))

    if expired_only:
        now = _now()
        stmt = stmt.where(or_(TMDBMediaCache.expires_at.is_(None), TMDBMediaCache.expires_at <= now))

    total = int(db.execute(select(func.count()).select_from(stmt.subquery())).scalar() or 0)

    rows = (
        db.execute(stmt.order_by(TMDBMediaCache.expires_at.asc().nullsfirst(), TMDBMediaCache.id.desc()).offset((p - 1) * ps).limit(ps))
        .scalars()
        .all()
    )
    return True, total, language, poster_language, rows


def set_ttl_seconds(db: Session, *, media_type: MediaType, tmdb_id: int, ttl_seconds: int) -> tuple[bool, TMDBMediaCache | None]:
    configured, _, language, poster_language = _get_runtime_tmdb_config(db)
    if not configured:
        return False, None
    row = _get_cache_row(db, media_type=media_type, tmdb_id=tmdb_id, language=language, poster_language=poster_language)
    if row is None:
        return True, None
    now = _now()
    row.expires_at = now + timedelta(seconds=max(60, int(ttl_seconds)))
    db.flush()
    return True, row


def delete_cache_item(db: Session, *, media_type: MediaType, tmdb_id: int) -> tuple[bool, int]:
    configured, _, language, poster_language = _get_runtime_tmdb_config(db)
    if not configured:
        return False, 0
    stmt = delete(TMDBMediaCache).where(
        TMDBMediaCache.media_type == media_type,
        TMDBMediaCache.tmdb_id == tmdb_id,
        TMDBMediaCache.language == language,
        TMDBMediaCache.poster_language == poster_language,
    )
    res = db.execute(stmt)
    return True, int(getattr(res, "rowcount", 0) or 0)

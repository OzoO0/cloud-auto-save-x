from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.models.task_savepath_snapshot import TaskSavepathSnapshot
from app.schemas.task import DramaUpdateProgressOut

logger = logging.getLogger(__name__)


_SH_TZ = ZoneInfo("Asia/Shanghai")


def _parse_air_date(value: Any) -> date | None:
    try:
        s = str(value or "").strip()
        if not s:
            return None
        return date.fromisoformat(s)
    except Exception:
        return None


def resolve_tmdb_latest_aired_episode(details: dict[str, Any] | None) -> tuple[int | None, int | None, str | None]:
    if not isinstance(details, dict):
        return None, None, "TMDB 缓存缺失"

    next_ep = details.get("next_episode_to_air") if isinstance(details.get("next_episode_to_air"), dict) else None
    last_ep = details.get("last_episode_to_air") if isinstance(details.get("last_episode_to_air"), dict) else None

    picked = None
    if isinstance(next_ep, dict):
        ad = _parse_air_date(next_ep.get("air_date"))
        if ad is not None and ad <= datetime.now().date():
            picked = next_ep
    if picked is None:
        picked = last_ep if isinstance(last_ep, dict) else None
    if not isinstance(picked, dict):
        return None, None, "TMDB 缓存缺少 last/next episode"

    try:
        season = int(picked.get("season_number") or 0)
        episode = int(picked.get("episode_number") or 0)
    except Exception:
        return None, None, "TMDB last/next episode 数据异常"
    if season <= 0 or episode <= 0:
        return None, None, "TMDB last/next episode 数据缺失"
    return season, episode, None


def resolve_saved_latest_episode_from_snapshot(
    *,
    snapshot: TaskSavepathSnapshot,
    tmdb_season: int,
) -> tuple[int | None, int | None, str | None]:
    try:
        saved_season = int(getattr(snapshot, "saved_latest_season", None) or 0)
    except Exception:
        saved_season = 0
    try:
        saved_episode = int(getattr(snapshot, "saved_latest_episode", None) or 0)
    except Exception:
        saved_episode = 0

    if saved_season <= 0 or saved_episode <= 0:
        return None, None, "快照未记录已存最新集数"
    if int(saved_season) != int(tmdb_season):
        return None, None, "当前季无匹配文件"
    return int(saved_season), int(saved_episode), None


def build_drama_update_progress(
    *,
    tmdb_details: dict[str, Any] | None,
    snapshot: TaskSavepathSnapshot | None,
) -> DramaUpdateProgressOut:
    tmdb_season, tmdb_episode, tmdb_reason = resolve_tmdb_latest_aired_episode(tmdb_details)
    if tmdb_season is None or tmdb_episode is None:
        return DramaUpdateProgressOut(
            available=False,
            tmdb_season=tmdb_season,
            tmdb_episode=tmdb_episode,
            snapshot_captured_at=snapshot.captured_at if snapshot is not None else None,
            reason=tmdb_reason or "TMDB 解析失败",
        )

    if snapshot is None:
        return DramaUpdateProgressOut(available=False, tmdb_season=tmdb_season, tmdb_episode=tmdb_episode, reason="无快照")

    saved_season, saved_episode, saved_reason = resolve_saved_latest_episode_from_snapshot(
        snapshot=snapshot,
        tmdb_season=int(tmdb_season),
    )

    if saved_season is None or saved_episode is None:
        return DramaUpdateProgressOut(
            available=False,
            tmdb_season=tmdb_season,
            tmdb_episode=tmdb_episode,
            saved_season=saved_season,
            saved_episode=saved_episode,
            snapshot_captured_at=snapshot.captured_at,
            reason=saved_reason or "快照解析失败",
        )

    behind = max(0, int(tmdb_episode) - int(saved_episode))
    is_latest = behind == 0
    return DramaUpdateProgressOut(
        available=True,
        tmdb_season=tmdb_season,
        tmdb_episode=tmdb_episode,
        saved_season=saved_season,
        saved_episode=saved_episode,
        behind_episodes=behind,
        is_latest=is_latest,
        snapshot_captured_at=snapshot.captured_at,
        reason=saved_reason,
    )

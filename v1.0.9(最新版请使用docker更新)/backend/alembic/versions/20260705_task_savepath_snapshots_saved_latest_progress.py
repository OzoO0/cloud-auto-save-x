"""task savepath snapshots saved latest progress

Revision ID: 20260705_task_savepath_snapshots_saved_latest_progress
Revises: 20260704_tmdb_cache_lookup_index
Create Date: 2026-07-05 00:00:00.000000

"""

from __future__ import annotations

import json
import os

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text

from app.extensions.runtime.guessit_fallback import guessit_episode_numbers


revision = "20260705_task_savepath_snapshots_saved_latest_progress"
down_revision = "20260704_tmdb_cache_lookup_index"
branch_labels = None
depends_on = None


_VIDEO_EXTS = {
    ".mp4",
    ".mkv",
    ".avi",
    ".ts",
    ".m2ts",
    ".mov",
    ".wmv",
    ".flv",
    ".webm",
    ".m4v",
    ".cas",
}


def _is_video_name(name: str) -> bool:
    base, ext = os.path.splitext(str(name or ""))
    if not base:
        return False
    if not ext:
        return True
    return ext.lower() in _VIDEO_EXTS


def _pick_tv_seasons(payload_json: str | None) -> list[dict] | None:
    if not payload_json:
        return None
    try:
        payload = json.loads(payload_json)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    seasons = payload.get("seasons")
    return seasons if isinstance(seasons, list) else None


def _resolve_saved_latest_progress(files_json: str | None, tv_seasons: list[dict] | None) -> tuple[int | None, int | None, str | None]:
    if not files_json:
        return None, None, None
    try:
        payload = json.loads(files_json)
    except Exception:
        return None, None, None
    if not isinstance(payload, list):
        return None, None, None

    best_key: tuple[int, int] | None = None
    best_name: str | None = None
    for item in payload:
        if not isinstance(item, dict):
            continue
        name = str(item.get("file_name") or "").strip()
        if not name or not _is_video_name(name):
            continue
        season, episode = guessit_episode_numbers(name, tv_seasons=tv_seasons)
        if season is None or episode is None:
            continue
        try:
            key = (int(season), int(episode))
        except Exception:
            continue
        if key[0] <= 0 or key[1] <= 0:
            continue
        if best_key is None or key > best_key:
            best_key = key
            best_name = name
    if best_key is None:
        return None, None, None
    return int(best_key[0]), int(best_key[1]), best_name


def _load_tv_seasons_map(bind, tmdb_ids: list[int]) -> dict[int, list[dict] | None]:
    out: dict[int, list[dict] | None] = {}
    if not tmdb_ids:
        return out
    for tmdb_id in tmdb_ids:
        row = bind.execute(
            text(
                """
                SELECT payload_json
                FROM tmdb_media_cache
                WHERE media_type = 'tv' AND tmdb_id = :tmdb_id
                ORDER BY updated_at DESC, id DESC
                LIMIT 1
                """
            ),
            {"tmdb_id": int(tmdb_id)},
        ).first()
        out[int(tmdb_id)] = _pick_tv_seasons(row[0] if row is not None else None)
    return out


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "task_savepath_snapshots" not in inspector.get_table_names():
        return

    cols = {c["name"] for c in inspector.get_columns("task_savepath_snapshots")}
    if "saved_latest_season" not in cols:
        op.add_column("task_savepath_snapshots", sa.Column("saved_latest_season", sa.Integer(), nullable=True))
    if "saved_latest_episode" not in cols:
        op.add_column("task_savepath_snapshots", sa.Column("saved_latest_episode", sa.Integer(), nullable=True))
    if "saved_latest_name" not in cols:
        op.add_column("task_savepath_snapshots", sa.Column("saved_latest_name", sa.String(length=255), nullable=True))

    rows = bind.execute(
        text(
            """
            SELECT s.id, s.files_json, t.tmdb_id
            FROM task_savepath_snapshots s
            JOIN tasks t ON t.task_uid = s.task_uid
            WHERE t.task_type = 'drama'
              AND lower(coalesce(t.tmdb_media_type, '')) = 'tv'
              AND t.tmdb_id IS NOT NULL
            ORDER BY s.id ASC
            """
        )
    ).mappings().all()
    if not rows:
        return

    tmdb_ids = sorted({int(row["tmdb_id"]) for row in rows if row.get("tmdb_id") is not None and int(row["tmdb_id"]) > 0})
    seasons_map = _load_tv_seasons_map(bind, tmdb_ids)
    stmt = text(
        """
        UPDATE task_savepath_snapshots
        SET saved_latest_season = :saved_latest_season,
            saved_latest_episode = :saved_latest_episode,
            saved_latest_name = :saved_latest_name
        WHERE id = :id
        """
    )
    for row in rows:
        tmdb_id = int(row["tmdb_id"] or 0)
        season, episode, name = _resolve_saved_latest_progress(
            row.get("files_json"),
            seasons_map.get(tmdb_id),
        )
        bind.execute(
            stmt,
            {
                "id": int(row["id"]),
                "saved_latest_season": season,
                "saved_latest_episode": episode,
                "saved_latest_name": name,
            },
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "task_savepath_snapshots" not in inspector.get_table_names():
        return

    cols = {c["name"] for c in inspector.get_columns("task_savepath_snapshots")}
    if "saved_latest_name" in cols:
        op.drop_column("task_savepath_snapshots", "saved_latest_name")
    if "saved_latest_episode" in cols:
        op.drop_column("task_savepath_snapshots", "saved_latest_episode")
    if "saved_latest_season" in cols:
        op.drop_column("task_savepath_snapshots", "saved_latest_season")

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models.share_preview_batch_cache import SharePreviewBatchCache


def _utcnow() -> datetime:
    return datetime.now()


def get_cached_preview_batch_item(db: Session, *, shareurl: str) -> tuple[SharePreviewBatchCache | None, bool]:
    url = str(shareurl or "").strip()
    if not url:
        return (None, False)

    row = db.get(SharePreviewBatchCache, url)
    if row is None:
        return (None, False)

    now = _utcnow()
    expires = row.expires_at
    if expires is None or expires <= now:
        return (None, False)

    row.hit_count = int(getattr(row, "hit_count", 0) or 0) + 1
    db.flush()
    return (row, True)


def upsert_preview_batch_cache(
    db: Session,
    *,
    shareurl: str,
    drive_type: str | None,
    ok: bool,
    message: str | None,
    ttl_seconds: int,
) -> bool:
    url = str(shareurl or "").strip()
    if not url:
        return False

    ttl = max(1, int(ttl_seconds or 0))
    now = _utcnow()
    expires_at = now + timedelta(seconds=ttl)

    row = db.get(SharePreviewBatchCache, url)
    if row is None:
        row = SharePreviewBatchCache(shareurl=url, expires_at=expires_at)
        db.add(row)

    row.drive_type = str(drive_type or "").strip() or None
    row.ok = bool(ok)
    row.message = str(message or "").strip() or None
    row.checked_at = now
    row.expires_at = expires_at
    db.flush()
    return True


def purge_old_preview_batch_cache(db: Session, *, retention_seconds: int) -> int:
    keep = max(1, int(retention_seconds or 0))
    threshold = _utcnow() - timedelta(seconds=keep)
    res = db.execute(delete(SharePreviewBatchCache).where(SharePreviewBatchCache.expires_at < threshold))
    db.flush()
    return int(getattr(res, "rowcount", 0) or 0)


def list_preview_batch_cache(
    db: Session,
    *,
    page: int,
    page_size: int,
    q: str | None,
    drive_type: str | None,
    ok: bool | None,
    expired_only: bool,
) -> tuple[list[SharePreviewBatchCache], int]:
    stmt = select(SharePreviewBatchCache)
    if q:
        like = f"%{str(q).strip()}%"
        stmt = stmt.where(SharePreviewBatchCache.shareurl.like(like))
    if drive_type:
        dt = str(drive_type).strip()
        if dt:
            stmt = stmt.where(SharePreviewBatchCache.drive_type == dt)
    if ok is not None:
        stmt = stmt.where(SharePreviewBatchCache.ok.is_(bool(ok)))
    if expired_only:
        stmt = stmt.where(SharePreviewBatchCache.expires_at <= _utcnow())

    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = (
        db.execute(
            stmt.order_by(SharePreviewBatchCache.checked_at.desc())
            .offset((max(int(page), 1) - 1) * max(int(page_size), 1))
            .limit(max(int(page_size), 1))
        )
        .scalars()
        .all()
    )
    return rows, int(total)


def delete_preview_batch_cache_item(db: Session, *, shareurl: str) -> int:
    url = str(shareurl or "").strip()
    if not url:
        return 0
    res = db.execute(delete(SharePreviewBatchCache).where(SharePreviewBatchCache.shareurl == url))
    db.flush()
    return int(getattr(res, "rowcount", 0) or 0)


def purge_expired_preview_batch_cache(db: Session) -> int:
    threshold = _utcnow()
    res = db.execute(delete(SharePreviewBatchCache).where(SharePreviewBatchCache.expires_at < threshold))
    db.flush()
    return int(getattr(res, "rowcount", 0) or 0)

from __future__ import annotations

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models.invalid_share_link import InvalidShareLink


def upsert_invalid_share_link(
    db: Session,
    *,
    shareurl: str,
    drive_type: str | None = None,
    message: str | None = None,
) -> bool:
    url = str(shareurl or "").strip()
    if not url:
        return False

    item = db.get(InvalidShareLink, url)
    if item is None:
        item = InvalidShareLink(shareurl=url)
        db.add(item)

    item.drive_type = str(drive_type or "").strip() or None
    item.message = str(message or "").strip() or None
    item.hit_count = int(getattr(item, "hit_count", 0) or 0) + 1
    db.flush()
    return True


def list_invalid_shareurls(db: Session, *, shareurls: list[str]) -> set[str]:
    urls = [str(x or "").strip() for x in (shareurls or [])]
    urls = [x for x in urls if x]
    if not urls:
        return set()

    rows = db.execute(select(InvalidShareLink.shareurl).where(InvalidShareLink.shareurl.in_(urls))).scalars().all()
    return {str(x) for x in rows if x}


def list_invalid_share_links(
    db: Session,
    *,
    page: int,
    page_size: int,
    q: str | None,
    drive_type: str | None,
) -> tuple[list[InvalidShareLink], int]:
    stmt = select(InvalidShareLink)
    if q:
        like = f"%{str(q).strip()}%"
        stmt = stmt.where(InvalidShareLink.shareurl.like(like))
    if drive_type:
        dt = str(drive_type).strip()
        if dt:
            stmt = stmt.where(InvalidShareLink.drive_type == dt)

    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = (
        db.execute(
            stmt.order_by(InvalidShareLink.updated_at.desc())
            .offset((max(int(page), 1) - 1) * max(int(page_size), 1))
            .limit(max(int(page_size), 1))
        )
        .scalars()
        .all()
    )
    return rows, int(total)


def delete_invalid_share_link(db: Session, *, shareurl: str) -> int:
    url = str(shareurl or "").strip()
    if not url:
        return 0
    res = db.execute(delete(InvalidShareLink).where(InvalidShareLink.shareurl == url))
    db.flush()
    return int(getattr(res, "rowcount", 0) or 0)


def clear_invalid_share_links(db: Session, *, drive_type: str | None = None) -> int:
    stmt = delete(InvalidShareLink)
    if drive_type:
        dt = str(drive_type).strip()
        if dt:
            stmt = stmt.where(InvalidShareLink.drive_type == dt)
    res = db.execute(stmt)
    db.flush()
    return int(getattr(res, "rowcount", 0) or 0)

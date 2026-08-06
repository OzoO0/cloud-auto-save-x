from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.openlist_setting import OpenListSetting


def get_or_create_openlist_setting(db: Session) -> OpenListSetting:
    item = db.execute(select(OpenListSetting).order_by(OpenListSetting.id.asc())).scalars().first()
    if item is None:
        item = OpenListSetting(url=None, token=None)
        db.add(item)
        db.flush()
    return item


def load_openlist_config(item: OpenListSetting) -> dict[str, object]:
    url = str(getattr(item, "url", "") or "").strip() or None
    token = str(getattr(item, "token", "") or "").strip()
    return {"url": url, "has_token": bool(token)}


def update_openlist_setting(db: Session, *, payload: dict[str, object]) -> OpenListSetting:
    item = get_or_create_openlist_setting(db)
    if "url" in payload:
        url = payload.get("url")
        if url is None:
            item.url = None
        else:
            item.url = str(url).strip() or None
    if "token" in payload:
        token = payload.get("token")
        if token is not None:
            t = str(token).strip()
            if t:
                item.token = t
    db.flush()
    return item


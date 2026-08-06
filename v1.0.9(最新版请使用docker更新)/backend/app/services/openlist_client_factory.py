from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import bad_request
from app.models.openlist_setting import OpenListSetting
from app.thirdparty.openlist_client import OpenListClient


def get_openlist_client(db: Session) -> OpenListClient:
    setting = db.execute(select(OpenListSetting).order_by(OpenListSetting.id.asc())).scalars().first()
    if setting is not None:
        url = str(getattr(setting, "url", "") or "").strip()
        token = str(getattr(setting, "token", "") or "").strip()
        if url and token:
            return OpenListClient(url, token=token)
    raise bad_request("OPENLIST_NOT_CONFIGURED", '请到"系统设置"中配置 OpenList')

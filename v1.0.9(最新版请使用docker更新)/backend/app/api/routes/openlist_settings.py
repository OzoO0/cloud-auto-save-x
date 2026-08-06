from __future__ import annotations

import posixpath

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.deps import CurrentUser, get_current_user, require_permissions
from app.core.permissions import SYNC_READ, TASK_READ, TASK_WRITE
from app.db.session import get_db
from app.schemas.path_browse import PathBrowseIn, PathBrowseItemOut, PathBrowseOut, PathBrowsePathOut
from app.schemas.openlist_settings import OpenListConfigOut, OpenListConfigUpdateIn
from app.services import audit
from app.services.openlist_client_factory import get_openlist_client
from app.services.openlist_settings import get_or_create_openlist_setting, load_openlist_config, update_openlist_setting


router = APIRouter()


@router.get("/config", response_model=OpenListConfigOut, dependencies=[Depends(require_permissions(TASK_READ))])
def get_openlist_config(db: Session = Depends(get_db)) -> OpenListConfigOut:
    item = get_or_create_openlist_setting(db)
    data = load_openlist_config(item)
    return OpenListConfigOut(**data)


@router.patch("/config", response_model=OpenListConfigOut, dependencies=[Depends(require_permissions(TASK_WRITE))])
def patch_openlist_config(
    request: Request,
    payload: OpenListConfigUpdateIn,
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OpenListConfigOut:
    item = update_openlist_setting(db, payload=payload.model_dump(exclude_unset=True))
    audit.write_audit_log(
        db,
        actor_user_id=current.user.id,
        action="openlist.config.update",
        target_type="openlist_setting",
        target_id="config",
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        success=True,
    )
    db.commit()
    db.refresh(item)
    data = load_openlist_config(item)
    return OpenListConfigOut(**data)


def _bool_is_dir(payload: dict) -> bool:
    if payload.get("is_dir") is not None:
        return bool(payload.get("is_dir"))
    if payload.get("isDir") is not None:
        return bool(payload.get("isDir"))
    if payload.get("isdir") is not None:
        return str(payload.get("isdir")) in ("1", "true", "True")
    if payload.get("dir") is not None:
        return bool(payload.get("dir"))
    if payload.get("type") in ("folder", "dir"):
        return True
    if payload.get("type") in ("file",):
        return False
    if payload.get("kind") in ("folder", "dir", "directory"):
        return True
    if payload.get("kind") in ("file",):
        return False
    return False


def _pick_name(payload: dict) -> str:
    return str(payload.get("name") or payload.get("file_name") or payload.get("fileName") or payload.get("title") or "")


def _pick_updated_at(payload: dict):
    return payload.get("updated_at") or payload.get("modified_at") or payload.get("mtime") or payload.get("updatedAt")


def _pick_size(payload: dict) -> int | None:
    value = payload.get("size")
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return None


@router.post("/browse", response_model=PathBrowseOut, dependencies=[Depends(require_permissions(SYNC_READ))])
def post_openlist_browse(payload: PathBrowseIn, db: Session = Depends(get_db)) -> PathBrowseOut:
    client = get_openlist_client(db)

    raw_path = str(payload.path or "").strip() or "/"
    normalized = "/" + posixpath.normpath(raw_path).lstrip("/")
    if normalized != "/" and normalized.endswith("/"):
        normalized = normalized.rstrip("/")

    segments = [s for s in normalized.split("/") if s]
    accum: list[PathBrowsePathOut] = []
    for i, name in enumerate(segments):
        p = "/" + "/".join(segments[: i + 1])
        accum.append(PathBrowsePathOut(name=name, path=p))

    try:
        resp = client.fs_list(normalized, refresh=bool(payload.refresh), page=1, per_page=int(payload.max_items))
    except Exception:
        return PathBrowseOut(dir_path=normalized, exists=False, paths=accum, items=[])

    data = resp.get("data") if isinstance(resp, dict) else None
    raw_items = None
    if isinstance(data, dict):
        raw_items = data.get("content") or data.get("items") or data.get("list") or data.get("files")
    if raw_items is None and isinstance(resp, dict):
        raw_items = resp.get("content") or resp.get("items") or resp.get("list") or resp.get("files")
    if not isinstance(raw_items, list):
        raw_items = []

    items: list[PathBrowseItemOut] = []
    for it in raw_items[: int(payload.max_items)]:
        if not isinstance(it, dict):
            continue
        name = _pick_name(it).strip()
        if not name or name in {".", ".."}:
            continue
        is_dir = _bool_is_dir(it)
        full = posixpath.join(normalized.rstrip("/") or "/", name)
        if not full.startswith("/"):
            full = "/" + full
        items.append(
            PathBrowseItemOut(
                name=name,
                path=full,
                is_dir=is_dir,
                updated_at=_pick_updated_at(it),
                size=_pick_size(it),
            )
        )

    items.sort(key=lambda x: (not x.is_dir, x.name.lower()))
    return PathBrowseOut(dir_path=normalized, exists=True, paths=accum, items=items)

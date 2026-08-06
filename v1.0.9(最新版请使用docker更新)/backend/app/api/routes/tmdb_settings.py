from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.deps import CurrentUser, get_current_user, require_permissions
from app.core.permissions import TASK_READ, TASK_WRITE
from app.db.session import get_db
from app.schemas.tmdb_settings import TMDBConfigOut, TMDBConfigUpdateIn
from app.services import audit
from app.services.tmdb_settings import get_or_create_tmdb_setting, load_tmdb_config, update_tmdb_setting


router = APIRouter()


@router.get("/config", response_model=TMDBConfigOut, dependencies=[Depends(require_permissions(TASK_READ))])
def get_tmdb_config(db: Session = Depends(get_db)) -> TMDBConfigOut:
    item = get_or_create_tmdb_setting(db)
    data = load_tmdb_config(item)
    return TMDBConfigOut(**data)


@router.patch("/config", response_model=TMDBConfigOut, dependencies=[Depends(require_permissions(TASK_WRITE))])
def patch_tmdb_config(
    request: Request,
    payload: TMDBConfigUpdateIn,
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TMDBConfigOut:
    item = update_tmdb_setting(db, payload=payload.model_dump(exclude_unset=True))
    audit.write_audit_log(
        db,
        actor_user_id=current.user.id,
        action="tmdb.config.update",
        target_type="tmdb_setting",
        target_id="config",
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        success=True,
    )
    db.commit()
    db.refresh(item)
    data = load_tmdb_config(item)
    return TMDBConfigOut(**data)


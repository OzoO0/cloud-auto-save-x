from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import CurrentUser, get_current_user
from app.db.session import get_db
from app.schemas.dashboard import CapacityOverviewOut, DramaOverviewOut
from app.services.dashboard_drama import build_drama_overview
from app.services.drive_accounts import build_capacity_overview

router = APIRouter()


@router.get('/capacity-overview', response_model=CapacityOverviewOut)
def get_capacity_overview(_current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    return CapacityOverviewOut(**build_capacity_overview(db))


@router.get('/drama-overview', response_model=DramaOverviewOut)
def get_drama_overview(
    days: int = Query(default=30, ge=1, le=365),
    _current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return DramaOverviewOut(**build_drama_overview(db, days=days))

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import require_permissions
from app.core.permissions import PERMISSION_READ
from app.db.session import get_db
from app.schemas.role import PermissionOut
from app.services.permissions import list_permissions


router = APIRouter()


@router.get("", response_model=list[PermissionOut], dependencies=[Depends(require_permissions(PERMISSION_READ))])
def get_permissions(db: Session = Depends(get_db)):
    items = list_permissions(db)
    return [PermissionOut(id=p.id, code=p.code, name=p.name, description=p.description) for p in items]

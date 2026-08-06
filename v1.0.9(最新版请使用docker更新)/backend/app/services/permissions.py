from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.permission import Permission


def list_permissions(db: Session) -> list[Permission]:
    return db.execute(select(Permission).order_by(Permission.id.asc())).scalars().all()

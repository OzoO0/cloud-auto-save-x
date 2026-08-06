from datetime import datetime
import os

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_db


router = APIRouter()


@router.get("/health")
def health(db: Session = Depends(get_db)):
    db_connected = False
    try:
        db.execute(text("SELECT 1"))
        db_connected = True
    except Exception:
        db_connected = False

    build_sha = (os.getenv("BUILD_SHA") or "").strip() or None
    build_tag = (os.getenv("BUILD_TAG") or "").strip() or None

    return {
        "status": "ok" if db_connected else "degraded",
        "db_connected": db_connected,
        "time": datetime.now().isoformat(),
        "build_sha": build_sha,
        "build_tag": build_tag,
    }

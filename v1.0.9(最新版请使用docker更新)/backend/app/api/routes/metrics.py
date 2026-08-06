from fastapi import APIRouter

from app.core.metrics import metrics_store


router = APIRouter()


@router.get("/metrics")
def metrics():
    return {"metrics": metrics_store.snapshot()}

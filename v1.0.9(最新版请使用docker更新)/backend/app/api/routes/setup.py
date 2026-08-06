from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import Session

from app.core.deps import load_user_roles_permissions
from app.core.errors import ApiError
from app.core.settings import settings
from app.db.session import get_db
from app.schemas.auth import LoginOut, MeOut
from app.schemas.setup import SetupAdminIn, SetupStatusOut
from app.services import audit
from app.services.auth import issue_tokens
from app.services.setup import create_initial_admin, is_initialized

router = APIRouter()


@router.get("/status", response_model=SetupStatusOut)
def get_status(db: Session = Depends(get_db)):
    return SetupStatusOut(initialized=is_initialized(db))


@router.post("/admin", response_model=LoginOut)
def post_admin(request: Request, response: Response, payload: SetupAdminIn, db: Session = Depends(get_db)):
    if is_initialized(db):
        raise ApiError(code="SETUP_ALREADY_INITIALIZED", message="系统已初始化", http_status=409)

    try:
        user = create_initial_admin(db, username=payload.username, email=str(payload.email), password=payload.password)
        db.flush()
    except (OperationalError, ProgrammingError):
        db.rollback()
        raise ApiError(code="DB_NOT_READY", message="数据库初始化中，请稍后重试", http_status=503)

    roles, permissions = load_user_roles_permissions(db, user.id)
    access_token = issue_tokens(db, user=user, permissions=permissions, request=request, response=response)

    audit.write_audit_log(
        db,
        actor_user_id=None,
        action="setup.init_admin",
        target_type="user",
        target_id=str(user.id),
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        success=True,
    )
    db.commit()

    return LoginOut(
        access_token=access_token,
        expires_in=settings.access_token_expires_seconds,
        user=MeOut(
            id=user.id,
            username=user.username,
            email=user.email,
            roles=roles,
            permissions=permissions,
        ),
    )

from fastapi import APIRouter, Depends, Request, Response
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.core.deps import CurrentUser, get_current_user, load_user_roles_permissions
from app.core.settings import settings
from app.db.session import get_db
from app.schemas.auth import LoginOut, MeOut, TokenOut
from app.services import audit
from app.services.auth import authenticate_user, clear_refresh_cookie, refresh_access_token, revoke_refresh_token, issue_tokens


router = APIRouter()


@router.post("/login", response_model=LoginOut)
def login(
    request: Request,
    response: Response,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    user = authenticate_user(db, form_data.username, form_data.password)
    roles, permissions = load_user_roles_permissions(db, user.id)
    access_token = issue_tokens(db, user=user, permissions=permissions, request=request, response=response)

    audit.write_audit_log(
        db,
        actor_user_id=user.id,
        action="auth.login",
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


@router.post("/refresh", response_model=TokenOut)
def refresh(request: Request, response: Response, db: Session = Depends(get_db)):
    user, access_token = refresh_access_token(db, request=request, response=response)
    # audit.write_audit_log(
    #     db,
    #     actor_user_id=user.id,
    #     action="auth.refresh",
    #     ip=request.client.host if request.client else None,
    #     user_agent=request.headers.get("user-agent"),
    #     success=True,
    # )
    db.commit()

    return TokenOut(access_token=access_token, expires_in=settings.access_token_expires_seconds)


@router.post("/logout")
def logout(request: Request, response: Response, current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    revoke_refresh_token(db, request=request)
    clear_refresh_cookie(response)

    audit.write_audit_log(
        db,
        actor_user_id=current.user.id,
        action="auth.logout",
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        success=True,
    )
    db.commit()

    return {"ok": True}


@router.get("/me", response_model=MeOut)
def me(current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    roles, permissions = load_user_roles_permissions(db, current.user.id)
    return MeOut(
        id=current.user.id,
        username=current.user.username,
        email=current.user.email,
        roles=roles,
        permissions=permissions,
    )

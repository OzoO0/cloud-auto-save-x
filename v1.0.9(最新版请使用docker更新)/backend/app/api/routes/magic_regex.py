from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.deps import CurrentUser, get_current_user, require_permissions
from app.core.permissions import TASK_READ, TASK_WRITE
from app.db.session import get_db
from app.schemas.magic_regex_rule import MagicRegexRuleListOut, MagicRegexRuleUpsertIn
from app.services import audit
from app.services.magic_regex import delete_rule, list_rules, upsert_rule


router = APIRouter()


@router.get("/rules", response_model=MagicRegexRuleListOut, dependencies=[Depends(require_permissions(TASK_READ))])
def get_magic_regex_rules(db: Session = Depends(get_db)) -> MagicRegexRuleListOut:
    return MagicRegexRuleListOut(rules=list_rules(db))


@router.patch("/rules/{key}", response_model=MagicRegexRuleListOut, dependencies=[Depends(require_permissions(TASK_WRITE))])
def patch_magic_regex_rule(
    request: Request,
    key: str,
    payload: MagicRegexRuleUpsertIn,
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MagicRegexRuleListOut:
    row = upsert_rule(db, key=key, payload=payload.model_dump(exclude_unset=True))
    audit.write_audit_log(
        db,
        actor_user_id=current.user.id,
        action="magic_regex.upsert",
        target_type="magic_regex_rule",
        target_id=str(row.key),
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        success=True,
    )
    db.commit()
    return MagicRegexRuleListOut(rules=list_rules(db))


@router.delete("/rules/{key}", response_model=MagicRegexRuleListOut, dependencies=[Depends(require_permissions(TASK_WRITE))])
def delete_magic_regex_rule(
    request: Request, key: str, current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)
) -> MagicRegexRuleListOut:
    delete_rule(db, key=key)
    audit.write_audit_log(
        db,
        actor_user_id=current.user.id,
        action="magic_regex.delete",
        target_type="magic_regex_rule",
        target_id=str(key),
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        success=True,
    )
    db.commit()
    return MagicRegexRuleListOut(rules=list_rules(db))

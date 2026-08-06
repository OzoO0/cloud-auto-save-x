from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

import json

from app.core.errors import ApiError, bad_request, not_found
from app.core.deps import CurrentUser, get_current_user, require_permissions
from app.core.permissions import DRIVE_ACCOUNT_READ, DRIVE_ACCOUNT_WRITE
from app.db.session import get_db
from app.schemas.drive_account import DriveAccountCreateIn, DriveAccountOut, DriveAccountStatusIn, DriveAccountUpdateIn, DriveTypeOut
from app.schemas.drive_account_auth import DriveAccountCaptchaSubmitIn, DriveAccountSmsSubmitIn
from app.schemas.drive_account_probe_scheduler import DriveAccountProbeSchedulerSettingOut, DriveAccountProbeSchedulerSettingUpdateIn
from app.extensions.adapters.drive_auth import DriveAuthRequired
from app.extensions.adapters.aliyun_adapter import AliyunAdapter
from app.extensions.runtime.adapter_registry import AdapterRegistry
from app.extensions.runtime.task_scheduler import task_scheduler_manager
from app.models.drive_account import DriveAccount
from app.services.drive_account_probe_scheduler import get_or_create_drive_account_probe_scheduler_setting, update_drive_account_probe_scheduler_setting
from app.services.drive_account_auth_sessions import create_auth_session, delete_auth_session, get_auth_session
from app.services import audit
from app.services.drive_accounts import (
    create_drive_account,
    delete_drive_account,
    list_drive_accounts,
    probe_drive_account,
    refresh_drive_account_profiles,
    serialize_drive_account,
    sign_in_drive_account,
    set_default_drive_account,
    set_drive_account_enabled,
    supported_drive_types,
    update_drive_account,
)

router = APIRouter()


def _out(item) -> DriveAccountOut:
    return DriveAccountOut(**serialize_drive_account(item))


@router.get('/auth/{session_id}', dependencies=[Depends(require_permissions(DRIVE_ACCOUNT_READ))])
def get_auth_session_status(session_id: str):
    session = get_auth_session(session_id)
    if session is None:
        raise not_found("DRIVE_ACCOUNT_AUTH_SESSION_NOT_FOUND", "认证会话已失效")
    return {"account_id": session.account_id, "drive_type": session.drive_type, "method": session.method, "session_id": session.session_id, "payload": session.payload}


@router.get('', response_model=list[DriveAccountOut], dependencies=[Depends(require_permissions(DRIVE_ACCOUNT_READ))])
def get_accounts(db: Session = Depends(get_db)):
    return [_out(item) for item in list_drive_accounts(db)]


def _probe_scheduler_out(item) -> DriveAccountProbeSchedulerSettingOut:
    return DriveAccountProbeSchedulerSettingOut(
        enabled=bool(getattr(item, "enabled", True)),
        crontab=str(getattr(item, "crontab", "0 4 * * *") or "0 4 * * *"),
        timezone=str(getattr(item, "timezone", "Asia/Shanghai") or "Asia/Shanghai"),
        enabled_only=bool(getattr(item, "enabled_only", True)),
    )


@router.get('/types', response_model=list[DriveTypeOut], dependencies=[Depends(require_permissions(DRIVE_ACCOUNT_READ))])
def get_drive_types():
    return [DriveTypeOut(**item) for item in supported_drive_types()]


@router.get('/probe/scheduler', response_model=DriveAccountProbeSchedulerSettingOut, dependencies=[Depends(require_permissions(DRIVE_ACCOUNT_READ))])
def get_drive_account_probe_scheduler_setting(db: Session = Depends(get_db)):
    setting = get_or_create_drive_account_probe_scheduler_setting(db)
    db.commit()
    db.refresh(setting)
    return _probe_scheduler_out(setting)


@router.patch('/probe/scheduler', response_model=DriveAccountProbeSchedulerSettingOut, dependencies=[Depends(require_permissions(DRIVE_ACCOUNT_WRITE))])
def patch_drive_account_probe_scheduler_setting(request: Request, payload: DriveAccountProbeSchedulerSettingUpdateIn, current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    setting = update_drive_account_probe_scheduler_setting(db, **payload.model_dump(exclude_unset=True))
    audit.write_audit_log(db, actor_user_id=current.user.id, action='drive_account.probe_scheduler.update', target_type='drive_account_probe_scheduler_setting', target_id=str(setting.id), ip=request.client.host if request.client else None, user_agent=request.headers.get('user-agent'), success=True)
    db.commit()
    db.refresh(setting)
    task_scheduler_manager.reload()
    return _probe_scheduler_out(setting)


@router.post('', response_model=DriveAccountOut, dependencies=[Depends(require_permissions(DRIVE_ACCOUNT_WRITE))])
def post_account(request: Request, payload: DriveAccountCreateIn, current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    account = create_drive_account(db, **payload.model_dump())
    audit.write_audit_log(db, actor_user_id=current.user.id, action='drive_account.create', target_type='drive_account', target_id=str(account.id), ip=request.client.host if request.client else None, user_agent=request.headers.get('user-agent'), success=True)
    db.commit()
    db.refresh(account)
    return _out(account)


@router.patch('/{account_id}', response_model=DriveAccountOut, dependencies=[Depends(require_permissions(DRIVE_ACCOUNT_WRITE))])
def patch_account(request: Request, account_id: int, payload: DriveAccountUpdateIn, current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    account = update_drive_account(db, account_id, **payload.model_dump(exclude_unset=True))
    audit.write_audit_log(db, actor_user_id=current.user.id, action='drive_account.update', target_type='drive_account', target_id=str(account_id), ip=request.client.host if request.client else None, user_agent=request.headers.get('user-agent'), success=True)
    db.commit()
    db.refresh(account)
    return _out(account)


@router.patch('/{account_id}/status', response_model=DriveAccountOut, dependencies=[Depends(require_permissions(DRIVE_ACCOUNT_WRITE))])
def patch_account_status(request: Request, account_id: int, payload: DriveAccountStatusIn, current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    if payload.enabled:
        account = probe_drive_account(db, account_id)
        if account.runtime_status != "active":
            account.enabled = False
            audit.write_audit_log(
                db,
                actor_user_id=current.user.id,
                action="drive_account.status",
                target_type="drive_account",
                target_id=str(account_id),
                ip=request.client.host if request.client else None,
                user_agent=request.headers.get("user-agent"),
                success=False,
                detail=f"enabled=True probe=failed fail_count={getattr(account, 'probe_fail_count', 0) or 0} error={account.last_error or ''}",
            )
            db.commit()
            db.refresh(account)
            raise bad_request("DRIVE_ACCOUNT_PROBE_FAILED", "账号探测失败，无法启用", detail=account.last_error or "驱动初始化失败")
        account.enabled = True
        account.probe_fail_count = 0
        audit.write_audit_log(
            db,
            actor_user_id=current.user.id,
            action="drive_account.status",
            target_type="drive_account",
            target_id=str(account_id),
            ip=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
            success=True,
            detail="enabled=True probe=ok",
        )
        db.commit()
        db.refresh(account)
        return _out(account)

    account = set_drive_account_enabled(db, account_id, False)
    audit.write_audit_log(
        db,
        actor_user_id=current.user.id,
        action="drive_account.status",
        target_type="drive_account",
        target_id=str(account_id),
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        success=True,
        detail="enabled=False",
    )
    db.commit()
    db.refresh(account)
    return _out(account)


@router.post('/{account_id}/default', response_model=DriveAccountOut, dependencies=[Depends(require_permissions(DRIVE_ACCOUNT_WRITE))])
def post_account_default(request: Request, account_id: int, current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    account = set_default_drive_account(db, account_id)
    audit.write_audit_log(db, actor_user_id=current.user.id, action='drive_account.default', target_type='drive_account', target_id=str(account_id), ip=request.client.host if request.client else None, user_agent=request.headers.get('user-agent'), success=True)
    db.commit()
    db.refresh(account)
    return _out(account)


@router.delete('/{account_id}', dependencies=[Depends(require_permissions(DRIVE_ACCOUNT_WRITE))])
def delete_account(request: Request, account_id: int, current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    delete_drive_account(db, account_id)
    audit.write_audit_log(db, actor_user_id=current.user.id, action='drive_account.delete', target_type='drive_account', target_id=str(account_id), ip=request.client.host if request.client else None, user_agent=request.headers.get('user-agent'), success=True)
    db.commit()
    return {'ok': True}


@router.post('/{account_id}/probe', response_model=DriveAccountOut, dependencies=[Depends(require_permissions(DRIVE_ACCOUNT_WRITE))])
def post_account_probe(request: Request, account_id: int, current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    account = probe_drive_account(db, account_id)
    audit.write_audit_log(db, actor_user_id=current.user.id, action='drive_account.probe', target_type='drive_account', target_id=str(account_id), ip=request.client.host if request.client else None, user_agent=request.headers.get('user-agent'), success=True)
    db.commit()
    db.refresh(account)
    return _out(account)


@router.post('/{account_id}/auth/start', response_model=DriveAccountOut, dependencies=[Depends(require_permissions(DRIVE_ACCOUNT_WRITE))])
def post_account_auth_start(request: Request, account_id: int, current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    account = probe_drive_account(db, account_id)
    audit.write_audit_log(db, actor_user_id=current.user.id, action='drive_account.auth_start', target_type='drive_account', target_id=str(account_id), ip=request.client.host if request.client else None, user_agent=request.headers.get('user-agent'), success=True)
    db.commit()
    db.refresh(account)
    return _out(account)


@router.post('/{account_id}/auth/qrcode/start', dependencies=[Depends(require_permissions(DRIVE_ACCOUNT_WRITE))])
def post_account_auth_qrcode_start(request: Request, account_id: int, current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    account = db.get(DriveAccount, account_id)
    if account is None:
        raise not_found("DRIVE_ACCOUNT_NOT_FOUND", "驱动账号不存在")
    if account.drive_type != "aliyun":
        raise bad_request("DRIVE_ACCOUNT_AUTH_UNSUPPORTED", "当前账号不支持扫码认证")
    resp = AliyunAdapter.generate_qrcode()
    if not isinstance(resp, dict) or not resp.get("success"):
        raise bad_request("DRIVE_ACCOUNT_AUTH_FAILED", "生成二维码失败", detail=str((resp or {}).get("message") or ""))
    data = resp.get("data") or {}
    session = create_auth_session(
        account_id=account.id,
        drive_type=account.drive_type,
        method="qrcode",
        adapter={"t": data.get("t") or "", "ck": data.get("ck") or ""},
        payload={"qrcode_url": data.get("qrCodeUrl") or "", "status": "NEW"},
    )
    audit.write_audit_log(db, actor_user_id=current.user.id, action='drive_account.auth_qrcode_start', target_type='drive_account', target_id=str(account_id), ip=request.client.host if request.client else None, user_agent=request.headers.get('user-agent'), success=True)
    db.commit()
    return {"account_id": account.id, "drive_type": account.drive_type, "method": "qrcode", "session_id": session.session_id, "payload": session.payload}


@router.post('/auth/{session_id}/qrcode/poll', response_model=DriveAccountOut, dependencies=[Depends(require_permissions(DRIVE_ACCOUNT_WRITE))])
def post_account_auth_qrcode_poll(request: Request, session_id: str, current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    session = get_auth_session(session_id)
    if session is None:
        raise not_found("DRIVE_ACCOUNT_AUTH_SESSION_NOT_FOUND", "认证会话已失效")
    if session.method != "qrcode":
        raise bad_request("DRIVE_ACCOUNT_AUTH_METHOD_MISMATCH", "认证方式不匹配")
    meta = session.adapter or {}
    t = str(meta.get("t") or "")
    ck = str(meta.get("ck") or "")
    resp = AliyunAdapter.query_qrcode_status(t, ck)
    if not isinstance(resp, dict) or not resp.get("success"):
        raise bad_request("DRIVE_ACCOUNT_AUTH_FAILED", "查询二维码状态失败", detail=str((resp or {}).get("message") or ""))
    data = resp.get("data") or {}
    if str(data.get("status") or "") == "CONFIRMED" and str(data.get("refresh_token") or ""):
        delete_auth_session(session_id)
        account = db.get(DriveAccount, session.account_id)
        if account is None:
            raise not_found("DRIVE_ACCOUNT_NOT_FOUND", "驱动账号不存在")
        config = AdapterRegistry.parse_config_json(account.drive_type, account.config_json, account.cookie)
        config["refresh_token"] = str(data.get("refresh_token") or "")
        update_drive_account(db, account.id, config=config)
        account = probe_drive_account(db, account.id)
        audit.write_audit_log(db, actor_user_id=current.user.id, action='drive_account.auth_qrcode_confirm', target_type='drive_account', target_id=str(account.id), ip=request.client.host if request.client else None, user_agent=request.headers.get('user-agent'), success=True)
        db.commit()
        db.refresh(account)
        return _out(account)
    session.payload.update({"status": str(data.get("status") or ""), "message": str(data.get("message") or "")})
    audit.write_audit_log(db, actor_user_id=current.user.id, action='drive_account.auth_qrcode_poll', target_type='drive_account', target_id=str(session.account_id), ip=request.client.host if request.client else None, user_agent=request.headers.get('user-agent'), success=True)
    db.commit()
    raise ApiError(
        code="DRIVE_ACCOUNT_AUTH_PENDING",
        message="扫码未完成",
        http_status=409,
        detail=json.dumps(
            {
                "account_id": session.account_id,
                "drive_type": session.drive_type,
                "method": "qrcode",
                "session_id": session.session_id,
                "payload": session.payload,
            },
            ensure_ascii=False,
        ),
    )


@router.post('/auth/{session_id}/captcha', response_model=DriveAccountOut, dependencies=[Depends(require_permissions(DRIVE_ACCOUNT_WRITE))])
def post_account_auth_captcha_submit(request: Request, session_id: str, payload: DriveAccountCaptchaSubmitIn, current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    session = get_auth_session(session_id)
    if session is None:
        raise not_found("DRIVE_ACCOUNT_AUTH_SESSION_NOT_FOUND", "认证会话已失效")
    if session.method != "captcha":
        raise bad_request("DRIVE_ACCOUNT_AUTH_METHOD_MISMATCH", "认证方式不匹配")
    adapter = session.adapter
    try:
        adapter.submit_captcha(payload.code)
    except DriveAuthRequired as exc:
        delete_auth_session(session_id)
        new_session = create_auth_session(
            account_id=session.account_id,
            drive_type=session.drive_type,
            method=exc.method,
            adapter=exc.adapter or adapter,
            payload=exc.payload,
        )
        raise ApiError(
            code="DRIVE_ACCOUNT_AUTH_REQUIRED",
            message=exc.message or "需要二次认证",
            http_status=409,
            detail=json.dumps(
                {
                    "account_id": session.account_id,
                    "drive_type": session.drive_type,
                    "method": exc.method,
                    "session_id": new_session.session_id,
                    "payload": exc.payload,
                },
                ensure_ascii=False,
            ),
        )
    delete_auth_session(session_id)
    update_drive_account(db, session.account_id, config=adapter.export_runtime_config())
    account = probe_drive_account(db, session.account_id)
    audit.write_audit_log(db, actor_user_id=current.user.id, action='drive_account.auth_captcha', target_type='drive_account', target_id=str(session.account_id), ip=request.client.host if request.client else None, user_agent=request.headers.get('user-agent'), success=True)
    db.commit()
    db.refresh(account)
    return _out(account)


@router.post('/auth/{session_id}/sms/send', dependencies=[Depends(require_permissions(DRIVE_ACCOUNT_WRITE))])
def post_account_auth_sms_send(request: Request, session_id: str, current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    session = get_auth_session(session_id)
    if session is None:
        raise not_found("DRIVE_ACCOUNT_AUTH_SESSION_NOT_FOUND", "认证会话已失效")
    if session.method != "sms":
        raise bad_request("DRIVE_ACCOUNT_AUTH_METHOD_MISMATCH", "认证方式不匹配")
    adapter = session.adapter
    result = adapter.send_sms()
    audit.write_audit_log(db, actor_user_id=current.user.id, action='drive_account.auth_sms_send', target_type='drive_account', target_id=str(session.account_id), ip=request.client.host if request.client else None, user_agent=request.headers.get('user-agent'), success=True)
    db.commit()
    return result


@router.post('/auth/{session_id}/sms/submit', response_model=DriveAccountOut, dependencies=[Depends(require_permissions(DRIVE_ACCOUNT_WRITE))])
def post_account_auth_sms_submit(request: Request, session_id: str, payload: DriveAccountSmsSubmitIn, current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    session = get_auth_session(session_id)
    if session is None:
        raise not_found("DRIVE_ACCOUNT_AUTH_SESSION_NOT_FOUND", "认证会话已失效")
    if session.method != "sms":
        raise bad_request("DRIVE_ACCOUNT_AUTH_METHOD_MISMATCH", "认证方式不匹配")
    adapter = session.adapter
    adapter.submit_sms(payload.code)
    delete_auth_session(session_id)
    config_snapshot = adapter.export_runtime_config()
    update_drive_account(db, session.account_id, config=config_snapshot)
    try:
        account = probe_drive_account(db, session.account_id)
    except ApiError as exc:
        # 光鸭当前账号信息接口不稳定，短信登录成功后可能在二次 probe 时误判为仍需短信认证。
        if exc.code != "DRIVE_ACCOUNT_AUTH_REQUIRED" or str(session.drive_type or "") != "guangya":
            raise
        account = db.get(DriveAccount, session.account_id)
        if account is None:
            raise not_found("DRIVE_ACCOUNT_NOT_FOUND", "驱动账号不存在")
        nickname = str(getattr(adapter, "nickname", "") or config_snapshot.get("phone_number") or account.name or "").strip()
        username = str(config_snapshot.get("phone_number") or nickname).strip()
        account.runtime_status = "active"
        account.last_error = None
        account.probe_fail_count = 0
        account.profile_json = json.dumps(
            {
                "drive_type": str(session.drive_type or ""),
                "drive_name": str(getattr(adapter, "DRIVE_NAME", session.drive_type) or session.drive_type or ""),
                "nickname": nickname,
                "username": username,
                "used_space": None,
                "total_space": None,
                "raw": {"auth_completed": True, "probe_fallback": True},
            },
            ensure_ascii=False,
        )
    audit.write_audit_log(db, actor_user_id=current.user.id, action='drive_account.auth_sms_submit', target_type='drive_account', target_id=str(session.account_id), ip=request.client.host if request.client else None, user_agent=request.headers.get('user-agent'), success=True)
    db.commit()
    db.refresh(account)
    return _out(account)


@router.post('/{account_id}/sign-in', dependencies=[Depends(require_permissions(DRIVE_ACCOUNT_WRITE))])
def post_account_sign_in(request: Request, account_id: int, current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        result = sign_in_drive_account(db, account_id)
        audit.write_audit_log(db, actor_user_id=current.user.id, action='drive_account.sign_in', target_type='drive_account', target_id=str(account_id), ip=request.client.host if request.client else None, user_agent=request.headers.get('user-agent'), success=True)
        db.commit()
        return result
    except ApiError as e:
        audit.write_audit_log(
            db,
            actor_user_id=current.user.id,
            action='drive_account.sign_in',
            target_type='drive_account',
            target_id=str(account_id),
            ip=request.client.host if request.client else None,
            user_agent=request.headers.get('user-agent'),
            success=False,
            detail=f"{e.code}:{e.message}",
        )
        db.commit()
        raise
    except Exception as e:
        audit.write_audit_log(
            db,
            actor_user_id=current.user.id,
            action='drive_account.sign_in',
            target_type='drive_account',
            target_id=str(account_id),
            ip=request.client.host if request.client else None,
            user_agent=request.headers.get('user-agent'),
            success=False,
            detail=str(e)[:500],
        )
        db.commit()
        raise ApiError(code="DRIVE_ACCOUNT_SIGN_IN_FAILED", message="签到失败", http_status=500, detail=str(e))


@router.post('/refresh-profiles', response_model=list[DriveAccountOut], dependencies=[Depends(require_permissions(DRIVE_ACCOUNT_WRITE))])
def post_refresh_profiles(request: Request, current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    items = refresh_drive_account_profiles(db)
    audit.write_audit_log(db, actor_user_id=current.user.id, action='drive_account.refresh_profiles', target_type='drive_account', target_id='*', ip=request.client.host if request.client else None, user_agent=request.headers.get('user-agent'), success=True)
    db.commit()
    for item in items:
        db.refresh(item)
    return [_out(item) for item in items]

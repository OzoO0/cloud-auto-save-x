from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApiError, bad_request, not_found
from app.extensions.adapters.adapter_factory import AdapterFactory
from app.extensions.adapters.drive_auth import DriveAuthRequired
from app.extensions.runtime.adapter_registry import AdapterRegistry
from app.models.drive_account import DriveAccount
from app.services.drive_account_auth_sessions import create_auth_session

BEIJING_TZ = ZoneInfo('Asia/Shanghai')


def list_drive_accounts(db: Session) -> list[DriveAccount]:
    return db.execute(select(DriveAccount).order_by(DriveAccount.is_default.desc(), DriveAccount.id.asc())).scalars().all()


def get_drive_account(db: Session, account_id: int) -> DriveAccount:
    account = db.get(DriveAccount, account_id)
    if account is None:
        raise not_found('DRIVE_ACCOUNT_NOT_FOUND', '驱动账号不存在')
    return account


def create_drive_account(db: Session, **payload) -> DriveAccount:
    if payload['drive_type'] not in AdapterFactory.get_supported_types():
        raise bad_request('DRIVE_TYPE_INVALID', '不支持的驱动类型')
    exists = db.execute(select(DriveAccount.id).where(DriveAccount.name == payload['name'])).first()
    if exists:
        raise bad_request('DRIVE_ACCOUNT_EXISTS', '驱动账号名称已存在')
    config, cookie = _normalize_account_payload(
        payload['drive_type'],
        payload.get('config'),
        payload.get('cookie'),
    )
    account = DriveAccount(
        name=payload['name'],
        drive_type=payload['drive_type'],
        cookie=cookie,
        enabled=payload.get('enabled', True),
        is_default=payload.get('is_default', False),
        capacity_warning_threshold=payload.get('capacity_warning_threshold', 85),
    )
    account.config_json = json.dumps(config, ensure_ascii=False)
    db.add(account)
    db.flush()
    if account.is_default:
        set_default_drive_account(db, account.id)
    return account


def update_drive_account(db: Session, account_id: int, **payload) -> DriveAccount:
    account = get_drive_account(db, account_id)
    for key, value in payload.items():
        if key in {'cookie', 'config'}:
            continue
        if value is not None:
            setattr(account, key, value)
    if 'config' in payload or 'cookie' in payload:
        config, cookie = _normalize_account_payload(
            account.drive_type,
            payload.get('config'),
            payload.get('cookie'),
            current_config_json=account.config_json,
            current_cookie=account.cookie,
        )
        account.config_json = json.dumps(config, ensure_ascii=False)
        account.cookie = cookie
    db.flush()
    if payload.get('is_default'):
        set_default_drive_account(db, account.id)
    return account


def set_drive_account_enabled(db: Session, account_id: int, enabled: bool) -> DriveAccount:
    account = get_drive_account(db, account_id)
    account.enabled = enabled
    return account


def set_default_drive_account(db: Session, account_id: int) -> DriveAccount:
    account = get_drive_account(db, account_id)
    items = db.execute(select(DriveAccount)).scalars().all()
    for item in items:
        item.is_default = item.id == account.id
    return account


def delete_drive_account(db: Session, account_id: int) -> None:
    account = get_drive_account(db, account_id)
    db.delete(account)


def probe_drive_account(db: Session, account_id: int) -> DriveAccount:
    account = get_drive_account(db, account_id)
    runtime_config = AdapterRegistry.parse_config_json(account.drive_type, account.config_json, account.cookie)
    runtime_cookie = AdapterRegistry.serialize_config(account.drive_type, runtime_config)
    if runtime_cookie and runtime_cookie != account.cookie:
        account.cookie = runtime_cookie
    adapter = AdapterFactory.create_adapter(
        account.drive_type,
        runtime_cookie,
        config=runtime_config,
        account_name=account.name,
    )
    account.last_checked_at = datetime.now()
    ok = False
    if adapter is None:
        account.runtime_status = 'error'
        account.last_error = '驱动实例创建失败'
    else:
        try:
            ok = adapter.init()
            account.runtime_status = 'active' if ok else 'inactive'
            account.last_error = None if ok else '驱动初始化失败'
            if ok:
                config_snapshot = adapter.export_runtime_config()
                account.config_json = json.dumps(config_snapshot, ensure_ascii=False)
                account.cookie = AdapterRegistry.serialize_config(account.drive_type, config_snapshot)
                profile = _build_account_profile(adapter, account)
                if profile is not None:
                    account.profile_json = json.dumps(profile, ensure_ascii=False)
        except DriveAuthRequired as exc:
            session = create_auth_session(
                account_id=account.id,
                drive_type=account.drive_type,
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
                        "account_id": account.id,
                        "drive_type": account.drive_type,
                        "method": exc.method,
                        "session_id": session.session_id,
                        "payload": exc.payload,
                    },
                    ensure_ascii=False,
                ),
            )
        except Exception as exc:
            account.runtime_status = 'error'
            account.last_error = str(exc)

    if ok:
        account.probe_fail_count = 0
        return account

    current_fail_count = int(getattr(account, "probe_fail_count", 0) or 0)
    account.probe_fail_count = current_fail_count + 1
    if account.probe_fail_count >= 3:
        account.enabled = False
    return account


def sign_in_drive_account(db: Session, account_id: int) -> dict[str, Any]:
    account = get_drive_account(db, account_id)
    runtime_config = AdapterRegistry.parse_config_json(account.drive_type, account.config_json, account.cookie)
    runtime_cookie = AdapterRegistry.serialize_config(account.drive_type, runtime_config)
    adapter = AdapterFactory.create_adapter(
        account.drive_type,
        runtime_cookie,
        config=runtime_config,
        account_name=account.name,
    )
    if adapter is None:
        raise bad_request("DRIVE_SIGNIN_FAILED", "驱动实例创建失败")
    result = adapter.sign_in()
    if not isinstance(result, dict) or not result.get("supported"):
        raise bad_request("DRIVE_SIGNIN_UNSUPPORTED", "该网盘暂不支持签到")
    if not result.get("ok", True):
        raise bad_request("DRIVE_SIGNIN_FAILED", result.get("message") or "签到失败", detail=str(result.get("reward") or result.get("message") or ""))
    config_snapshot = adapter.export_runtime_config()
    if isinstance(config_snapshot, dict) and config_snapshot:
        account.config_json = json.dumps(config_snapshot, ensure_ascii=False)
        account.cookie = AdapterRegistry.serialize_config(account.drive_type, config_snapshot)
        db.flush()
    return result


def supported_drive_types() -> list[dict[str, str]]:
    return AdapterRegistry.supported_drive_types()


def resolve_drive_account_config(account: DriveAccount) -> dict:
    return AdapterRegistry.parse_config_json(account.drive_type, account.config_json, account.cookie)


def resolve_drive_account_profile(account: DriveAccount) -> dict[str, Any]:
    if not account.profile_json:
        return {}
    try:
        profile = json.loads(account.profile_json)
    except (TypeError, ValueError):
        return {}
    return profile if isinstance(profile, dict) else {}


def extract_capacity_metrics(profile: dict[str, Any]) -> tuple[int | None, int | None, float | None]:
    used_value = profile.get('used_space')
    total_value = profile.get('total_space')
    try:
        used_space = int(used_value) if used_value is not None else None
    except (TypeError, ValueError):
        used_space = None
    try:
        total_space = int(total_value) if total_value is not None else None
    except (TypeError, ValueError):
        total_space = None

    usage_ratio: float | None = None
    if used_space is not None and total_space and total_space > 0:
        usage_ratio = round(used_space / total_space, 4)
    return used_space, total_space, usage_ratio


def serialize_drive_account(account: DriveAccount) -> dict[str, Any]:
    profile = resolve_drive_account_profile(account)
    used_space, total_space, usage_ratio = extract_capacity_metrics(profile)
    return {
        'id': account.id,
        'name': account.name,
        'drive_type': account.drive_type,
        'config': resolve_drive_account_config(account),
        'profile': profile,
        'enabled': account.enabled,
        'is_default': account.is_default,
        'capacity_warning_threshold': account.capacity_warning_threshold,
        'used_space': used_space,
        'total_space': total_space,
        'usage_ratio': usage_ratio,
        'runtime_status': account.runtime_status,
        'probe_fail_count': int(getattr(account, "probe_fail_count", 0) or 0),
        'last_checked_at': normalize_api_datetime(account.last_checked_at),
        'profile_updated_at': normalize_api_datetime(account.last_checked_at),
        'last_error': account.last_error,
        'created_at': normalize_api_datetime(account.created_at),
        'updated_at': normalize_api_datetime(account.updated_at),
    }


def refresh_drive_account_profiles(db: Session) -> list[DriveAccount]:
    accounts = list_drive_accounts(db)
    for account in accounts:
        probe_drive_account(db, account.id)
    return accounts


def build_capacity_overview(db: Session) -> dict[str, Any]:
    accounts = [serialize_drive_account(item) for item in list_drive_accounts(db)]
    total_used_space = 0
    total_capacity = 0
    capacity_account_count = 0
    warning_accounts: list[dict[str, Any]] = []
    unsupported_accounts: list[dict[str, Any]] = []

    for item in accounts:
        usage_ratio = item['usage_ratio']
        total_space = item['total_space']
        used_space = item['used_space']
        threshold = item['capacity_warning_threshold']
        if used_space is not None and total_space is not None and total_space > 0:
            total_used_space += used_space
            total_capacity += total_space
            capacity_account_count += 1
            if usage_ratio is not None and usage_ratio >= threshold / 100:
                warning_accounts.append(item)
        else:
            unsupported_accounts.append(item)

    warning_accounts.sort(key=lambda item: (item['usage_ratio'] is None, -(item['usage_ratio'] or 0), item['name']))
    usage_ratio = round(total_used_space / total_capacity, 4) if total_capacity > 0 else None

    return {
        'summary': {
            'account_count': len(accounts),
            'enabled_account_count': sum(1 for item in accounts if item['enabled']),
            'capacity_account_count': capacity_account_count,
            'warning_account_count': len(warning_accounts),
            'total_used_space': total_used_space or None,
            'total_space': total_capacity or None,
            'usage_ratio': usage_ratio,
        },
        'accounts': accounts,
        'warning_accounts': warning_accounts,
        'unsupported_accounts': unsupported_accounts,
        'updated_at': max((item['profile_updated_at'] for item in accounts if item['profile_updated_at']), default=None),
    }


def _build_account_profile(adapter: Any, account: DriveAccount) -> dict[str, Any] | None:
    profile = adapter.get_account_config()
    if not isinstance(profile, dict):
        return None
    profile.setdefault('drive_type', account.drive_type)
    profile.setdefault('drive_name', account.drive_type)
    profile.setdefault('nickname', '')
    profile.setdefault('username', '')
    profile.setdefault('used_space', None)
    profile.setdefault('total_space', None)
    profile.setdefault('raw', None)
    return profile


def normalize_api_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(BEIJING_TZ)


def _normalize_account_payload(
    drive_type: str,
    config: dict | None,
    cookie: str | None,
    *,
    current_config_json: str | None = None,
    current_cookie: str | None = None,
) -> tuple[dict, str]:
    if config is not None:
        normalized_config = AdapterRegistry.normalize_config(drive_type, config)
    elif cookie is not None:
        normalized_config = AdapterRegistry.deserialize_cookie(drive_type, cookie)
    elif current_config_json is not None or current_cookie is not None:
        normalized_config = AdapterRegistry.parse_config_json(drive_type, current_config_json, current_cookie)
    else:
        raise bad_request('DRIVE_ACCOUNT_CONFIG_REQUIRED', '请填写驱动账号登录参数')
    runtime_cookie = AdapterRegistry.serialize_config(drive_type, normalized_config)
    if not runtime_cookie.strip():
        raise bad_request('DRIVE_ACCOUNT_CONFIG_REQUIRED', '请填写驱动账号登录参数')
    return normalized_config, runtime_cookie

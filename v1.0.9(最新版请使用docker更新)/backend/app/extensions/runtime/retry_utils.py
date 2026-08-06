from __future__ import annotations

import json
import logging
import random
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping, TypeVar


logger = logging.getLogger(__name__)

T = TypeVar("T")

_SENSITIVE_KEYS = {"authorization", "token", "password", "passcode", "cookie", "set-cookie", "stoken", "refresh_token"}


def _redact_key(key: str) -> bool:
    k = str(key or "").strip().lower()
    if not k:
        return False
    if k in _SENSITIVE_KEYS:
        return True
    for x in _SENSITIVE_KEYS:
        if x in k:
            return True
    return False


def _truncate(s: str, max_len: int) -> str:
    s = str(s or "")
    if max_len <= 0:
        return ""
    if len(s) <= max_len:
        return s
    return f"{s[:max_len]}...(truncated,len={len(s)})"


def _safe_obj(value: Any, *, max_items: int, depth: int) -> Any:
    if value is None:
        return None
    if isinstance(value, (int, float, bool)):
        return value
    if isinstance(value, str):
        return _truncate(value, 2000)
    if isinstance(value, (bytes, bytearray)):
        return f"<bytes len={len(value)}>"
    if isinstance(value, Mapping):
        if depth >= 2:
            return f"<dict keys={len(value)}>"
        out: dict[str, Any] = {}
        for idx, (k, v) in enumerate(value.items()):
            if idx >= max_items:
                out["...(truncated)"] = f"items>{max_items}"
                break
            ks = str(k)
            if _redact_key(ks):
                out[ks] = "***"
                continue
            out[ks] = _safe_obj(v, max_items=max(10, int(max_items / 2)), depth=depth + 1)
        return out
    if isinstance(value, (list, tuple, set)):
        seq = list(value)
        if depth >= 2:
            return f"<{type(value).__name__} len={len(seq)}>"
        head: list[Any] = []
        for x in seq[: max_items if max_items > 0 else 0]:
            head.append(_safe_obj(x, max_items=max(10, int(max_items / 2)), depth=depth + 1))
        return {"len": len(seq), "head": head}
    return _truncate(repr(value), 2000)


def summarize_payload(value: Any, *, max_len: int = 2000, max_items: int = 20) -> str:
    try:
        obj = _safe_obj(value, max_items=max_items, depth=0)
        return _truncate(json.dumps(obj, ensure_ascii=False), max_len)
    except Exception:
        return _truncate(repr(value), max_len)


def _extract_status(payload: Any) -> int | None:
    if not isinstance(payload, dict):
        return None
    for key in ("status", "http_status", "status_code"):
        v = payload.get(key)
        try:
            if v is not None:
                return int(v)
        except Exception:
            pass
    return None


def _extract_code(payload: Any) -> int | None:
    if not isinstance(payload, dict):
        return None
    for key in ("code", "errno", "error_code"):
        v = payload.get(key)
        try:
            if v is not None:
                return int(v)
        except Exception:
            pass
    return None


def is_transient_error(exc: Exception | None = None, payload: Any | None = None) -> bool:
    status = _extract_status(payload)
    if status in (408, 425, 429, 500, 502, 503, 504):
        return True

    text = ""
    if exc is not None:
        text = str(exc).strip().lower()
    if not text and isinstance(payload, dict):
        text = str(payload.get("message") or payload.get("error") or "").strip().lower()

    if not text:
        return False

    keywords = [
        "timeout",
        "timed out",
        "connection reset",
        "connection aborted",
        "connection refused",
        "connection error",
        "remote disconnected",
        "temporarily unavailable",
        "service unavailable",
        "bad gateway",
        "gateway timeout",
        "request error",
        "网络异常",
        "连接失败",
        "连接重置",
        "超时",
        "临时",
    ]
    return any(k in text for k in keywords)


@dataclass(slots=True)
class RetryResult:
    value: Any | None
    ok: bool
    error_message: str | None = None


def retry_call(
    *,
    action: str,
    fn: Callable[[], T],
    validate: Callable[[T], RetryResult] | None = None,
    attempts: int = 3,
    backoff_seconds: float = 1.0,
    max_backoff_seconds: float = 8.0,
    jitter_ratio: float = 0.2,
    emit: Callable[[str], None] | None = None,
    log: logging.Logger | None = None,
) -> T:
    action = str(action or "").strip() or "action"
    attempts = max(1, int(attempts))
    backoff_seconds = max(0.0, float(backoff_seconds))
    max_backoff_seconds = max(0.0, float(max_backoff_seconds))
    jitter_ratio = max(0.0, float(jitter_ratio))

    last_exc: Exception | None = None

    for attempt in range(1, attempts + 1):
        payload: Any | None = None
        try:
            value = fn()
            payload = value
            if validate is None:
                return value
            rs = validate(value)
            if rs.ok:
                return value
            raise RuntimeError(rs.error_message or f"{action} failed")
        except Exception as e:
            last_exc = e
            err_text = str(e).strip() or type(e).__name__
            if emit is not None:
                emit(f"ERROR: {action} attempt={attempt}/{attempts} err={err_text}")
            if log is not None:
                try:
                    log.warning("retry failed action=%s attempt=%s/%s err=%s payload=%s", action, attempt, attempts, err_text, summarize_payload(payload))
                except Exception:
                    pass
            if attempt >= attempts:
                break
            if not is_transient_error(e, payload):
                break
            if backoff_seconds <= 0:
                continue
            sleep_s = backoff_seconds * (2 ** (attempt - 1))
            if max_backoff_seconds > 0:
                sleep_s = min(sleep_s, max_backoff_seconds)
            if jitter_ratio > 0:
                sleep_s = sleep_s + random.random() * max(0.0, sleep_s * jitter_ratio)
            if emit is not None and sleep_s > 0:
                emit(f"RETRY: {action} sleep={sleep_s:.2f}s")
            if sleep_s > 0:
                time.sleep(sleep_s)

    raise RuntimeError(f"{action} failed: {str(last_exc).strip() or type(last_exc).__name__}") from last_exc


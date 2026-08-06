from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ApiError(Exception):
    code: str
    message: str
    http_status: int = 400
    detail: str | None = None


def bad_request(code: str, message: str, detail: str | None = None) -> ApiError:
    return ApiError(code=code, message=message, http_status=400, detail=detail)


def unauthorized(code: str, message: str, detail: str | None = None) -> ApiError:
    return ApiError(code=code, message=message, http_status=401, detail=detail)


def forbidden(code: str, message: str, detail: str | None = None) -> ApiError:
    return ApiError(code=code, message=message, http_status=403, detail=detail)


def not_found(code: str, message: str, detail: str | None = None) -> ApiError:
    return ApiError(code=code, message=message, http_status=404, detail=detail)

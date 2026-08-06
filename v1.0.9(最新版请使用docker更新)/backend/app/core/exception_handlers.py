from __future__ import annotations

import logging

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette import status

from app.core.errors import ApiError


logger = logging.getLogger(__name__)


def api_error_handler(_: Request, exc: ApiError) -> JSONResponse:
    if exc.http_status >= 500:
        logger.error("API error: %s", exc.code, exc_info=True)
    return JSONResponse(
        status_code=exc.http_status,
        content={"code": exc.code, "message": exc.message, "detail": exc.detail},
    )


def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    logger.warning("Request validation error: %s", exc, exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"code": "VALIDATION_ERROR", "message": "请求参数错误", "detail": str(exc)},
    )


def http_error_handler(_: Request, exc: Exception) -> JSONResponse:
    logger.error("Unhandled exception", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"code": "INTERNAL_ERROR", "message": "服务器内部错误"},
    )

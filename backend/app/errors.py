from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.logging import request_id_ctx

logger = logging.getLogger(__name__)


def _request_id() -> str | None:
    return request_id_ctx.get()


def error_envelope(
    *,
    code: str,
    message: str,
    request_id: str | None = None,
) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "request_id": request_id if request_id is not None else _request_id(),
        }
    }


def _http_error_code(status_code: int) -> str:
    mapping = {
        400: "bad_request",
        401: "unauthorized",
        403: "forbidden",
        404: "not_found",
        405: "method_not_allowed",
        409: "conflict",
        422: "validation_error",
        429: "too_many_requests",
    }
    return mapping.get(status_code, "http_error")


def _detail_message(detail: Any) -> str:
    if isinstance(detail, str):
        return detail
    if isinstance(detail, list):
        return "Request validation failed."
    return str(detail)


async def http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, HTTPException)
    message = _detail_message(exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content=error_envelope(
            code=_http_error_code(exc.status_code),
            message=message,
        ),
        headers=getattr(exc, "headers", None),
    )


async def validation_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    return JSONResponse(
        status_code=422,
        content=error_envelope(
            code="validation_error",
            message="Request validation failed.",
        ),
    )


async def unhandled_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    logger.exception("Unhandled exception")
    return JSONResponse(
        status_code=500,
        content=error_envelope(
            code="internal_error",
            message="An unexpected error occurred.",
        ),
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)

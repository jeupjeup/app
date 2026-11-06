"""HTTP error envelope and exception mapping from PRD 5.8.1/5.9."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from jupjup.domain.errors import (
    ContentValidationError,
    IndexNotReadyError,
    InvalidFilterError,
    InvalidQueryError,
    InvalidUserError,
    JupjupError,
    NotFoundError,
)

logger = logging.getLogger(__name__)


class Utf8JSONResponse(JSONResponse):
    media_type = "application/json; charset=utf-8"


class ApiError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: dict[str, Any] | list[dict[str, Any]] | None = None,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


def error_response(
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any] | list[dict[str, Any]] | None = None,
) -> Utf8JSONResponse:
    error: dict[str, Any] = {"code": code, "message": message}
    if details:
        error["details"] = details
    return Utf8JSONResponse(status_code=status_code, content={"error": error})


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> Utf8JSONResponse:
        if exc.status_code == 404:
            return error_response(404, "NOT_FOUND", "요청한 경로를 찾을 수 없어요.")
        if exc.status_code == 405:
            return error_response(405, "METHOD_NOT_ALLOWED", "허용되지 않은 요청 메서드예요.")
        return error_response(exc.status_code, "HTTP_ERROR", str(exc.detail))

    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> Utf8JSONResponse:
        return error_response(exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> Utf8JSONResponse:
        details = [
            {
                "type": str(error.get("type", "validation_error")),
                "loc": list(error.get("loc", ())),
                "msg": str(error["msg"]),
            }
            for error in exc.errors()
        ]
        return error_response(422, "VALIDATION_ERROR", "요청 형식이 올바르지 않아요.", details)

    @app.exception_handler(JupjupError)
    async def _domain_error(_: Request, exc: JupjupError) -> Utf8JSONResponse:
        if isinstance(exc, ContentValidationError):
            return error_response(422, "INVALID_CONTENT", "콘텐츠 형식이 올바르지 않습니다")
        if isinstance(exc, InvalidUserError):
            return error_response(400, exc.code, exc.message, exc.details)
        if isinstance(exc, (InvalidQueryError, InvalidFilterError)):
            return error_response(422, exc.code, exc.message, exc.details)
        if isinstance(exc, IndexNotReadyError):
            return error_response(503, exc.code, exc.message, exc.details)
        if isinstance(exc, NotFoundError):
            return error_response(404, exc.code, exc.message, exc.details)
        if exc.code in {"STORAGE_UNAVAILABLE", "INDEX_UNAVAILABLE", "ANALYZER_UNAVAILABLE"}:
            return error_response(503, exc.code, "일시적으로 처리할 수 없습니다")
        logger.error("unmapped Jupjup API error: %s", type(exc).__name__)
        return error_response(500, "INTERNAL", "서버 내부 오류가 발생했어요.")

    @app.exception_handler(Exception)
    async def _internal_error(_: Request, exc: Exception) -> Utf8JSONResponse:
        if isinstance(exc, SQLAlchemyError):
            logger.error("storage request failed: %s", type(exc).__name__)
            return error_response(503, "STORAGE_UNAVAILABLE", "저장소를 사용할 수 없습니다")
        logger.error("unhandled Jupjup API error: %s", type(exc).__name__)
        return error_response(500, "INTERNAL", "서버 내부 오류가 발생했어요.")

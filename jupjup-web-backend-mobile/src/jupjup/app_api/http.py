"""Isolated /api transport: bounded JSON, CORS, rate limits, contract envelopes."""

from __future__ import annotations

import json
import logging
import os
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, Request
from sqlalchemy import Engine, text
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse, Response

from jupjup.app_api import auth, native_oauth, oauth, service
from jupjup.app_api.errors import ContractError
from jupjup.app_api.oauth_logging import install_access_filter

if TYPE_CHECKING:
    from jupjup.bridge.service import ContentBridge

logger = logging.getLogger(__name__)
OPERATIONS = (
    ("GET", "/health", "health", 200),
    ("POST", "/auth/register", "register", 201),
    ("POST", "/auth/login", "login", 200),
    ("POST", "/auth/logout", "logout", 204),
    ("GET", "/state", "getState", 200),
    ("GET", "/me", "getMe", 200),
    ("PATCH", "/me", "updateMe", 200),
    ("DELETE", "/me", "deleteMe", 204),
    ("POST", "/me/password/verify", "verifyPassword", 204),
    ("PATCH", "/me/password", "changePassword", 204),
    ("POST", "/contents", "createContent", 201),
    ("GET", "/contents", "listContent", 200),
    ("GET", "/contents/{id}", "getContent", 200),
    ("PATCH", "/contents/{id}", "updateContent", 200),
    ("DELETE", "/contents/{id}", "deleteContent", 204),
    ("POST", "/contents/{id}/restore", "restoreContent", 200),
    ("POST", "/contents/{id}/view", "viewContent", 204),
    ("DELETE", "/trash", "emptyTrash", 204),
    ("GET", "/notices", "listNotices", 200),
    ("POST", "/notices/read", "readAllNotices", 204),
    ("POST", "/notices/{id}/read", "readNotice", 204),
    ("GET", "/search-history", "getSearchHistory", 200),
    ("POST", "/search-history", "addSearchHistory", 200),
    ("DELETE", "/search-history", "clearSearchHistory", 204),
)
# The requested count is 25; the supplied OpenAPI document contains exactly these 24.


def create_api(engine: Engine, *, origins: set[str] | None = None, bridge: ContentBridge | None = None) -> FastAPI:
    api = FastAPI(title="줍줍저장소 앱 API", docs_url=None, redoc_url=None, openapi_url=None, redirect_slashes=False)
    api.state.bridge = bridge
    api.state.clock = lambda: datetime.now(UTC)
    api.state.lock = threading.RLock()
    oauth.install(api, engine)
    native_oauth.install(api, engine)
    install_access_filter()
    allowed = (
        origins
        if origins is not None
        else {origin.strip() for origin in os.environ.get("CORS_ORIGINS", "").split(",") if origin.strip()}
    )

    allowed.add(api.state.oauth_config.origin)

    def maintain(ip: str, limited: bool, now: datetime) -> None:
        with api.state.lock, engine.connect() as conn:
            conn.exec_driver_sql("BEGIN IMMEDIATE")
            if bridge:
                bridge.purge(conn, "a.deleted_at<=:cutoff", {"cutoff": auth.instant(now - timedelta(days=30))})
            else:
                conn.execute(
                    text("DELETE FROM api_contents WHERE deleted_at<=:cutoff"),
                    dict(cutoff=auth.instant(now - timedelta(days=30))),
                )
            conn.execute(text("DELETE FROM api_sessions WHERE expires_at<=:now"), dict(now=auth.instant(now)))
            if limited:
                stamp = now.timestamp()
                conn.execute(text("DELETE FROM api_rate_limits WHERE started_at<=:cutoff"), dict(cutoff=stamp - 60))
                row = conn.execute(text("SELECT requests FROM api_rate_limits WHERE ip=:ip"), dict(ip=ip)).first()
                if row and row.requests >= 30:
                    raise ContractError(429, "RATE_LIMITED")
                conn.execute(
                    text(
                        "INSERT INTO api_rate_limits VALUES (:ip,:now,1) "
                        "ON CONFLICT(ip) DO UPDATE SET requests=requests+1"
                    ),
                    dict(ip=ip, now=stamp),
                )
            conn.commit()

    @api.middleware("http")
    async def transport(request: Request, call_next: Any) -> Response:
        origin = request.headers.get("origin")
        try:
            if origin is not None and origin not in allowed:
                raise ContractError(403, "ORIGIN_FORBIDDEN")
            path = request.scope.get("path", "")
            root = request.scope.get("root_path", "")
            path = path.removeprefix(root)
            now = api.state.clock()
            limited = path.startswith("/auth/") or path in ("/me/password", "/me/password/verify")
            # Trust the socket peer only. Forwarded headers require deployment-level trusted proxy configuration.
            ip = request.client.host if request.client else "unknown"
            await run_in_threadpool(maintain, ip, limited, now)
            if request.method == "OPTIONS":
                if request.headers.get("access-control-request-method", "GET") not in {
                    "GET",
                    "POST",
                    "PATCH",
                    "DELETE",
                    "OPTIONS",
                }:
                    raise ContractError(403, "ORIGIN_FORBIDDEN")
                requested = request.headers.get("access-control-request-headers", "")
                if any(h.strip().lower() not in ("authorization", "content-type") for h in requested.split(",") if h):
                    raise ContractError(403, "ORIGIN_FORBIDDEN")
                response: Response = Response(status_code=204)
            else:
                request.state.now = now
                request.state.json = {}
                if request.method in ("POST", "PATCH"):
                    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                        raise ContractError(415, "UNSUPPORTED_MEDIA_TYPE")
                    data = bytearray()
                    async for chunk in request.stream():
                        data.extend(chunk)
                        if len(data) > 16 * 1024:
                            raise ContractError(413, "PAYLOAD_TOO_LARGE")
                    try:
                        body = json.loads(data.decode("utf-8"), parse_constant=reject_constant)
                    except (ValueError, UnicodeError, RecursionError):
                        raise ContractError(400, "INVALID_JSON") from None
                    if not isinstance(body, dict):
                        raise ContractError(400, "VALIDATION_ERROR")
                    request.state.json = body
                response = await call_next(request)
        except ContractError as exc:
            response = exc.response()
        except Exception as exc:
            if "/auth/oauth/" in request.url.path:
                logger.error("OAuth request failed")
            else:
                logger.error("app API request failed: %s", type(exc).__name__)
            response = ContractError(500, "INTERNAL_ERROR").response()
        if origin in allowed:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"
            response.headers["Access-Control-Allow-Credentials"] = "true"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, PATCH, DELETE, OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
        response.headers["Cache-Control"] = "no-store"
        return response

    def handler(operation: str, status: int) -> Callable[[Request], Response]:
        def endpoint(request: Request) -> Response:
            try:
                with api.state.lock, engine.connect() as conn:
                    conn.exec_driver_sql("BEGIN IMMEDIATE")
                    try:
                        user = None
                        token = ""
                        if operation not in ("health", "register", "login"):
                            user, token = auth.authenticate(
                                conn, request.headers.get("authorization", ""), request.state.now
                            )
                        result = service.execute(
                            conn,
                            operation,
                            request.state.json,
                            request.state.now,
                            user,
                            token,
                            request.path_params.get("id", ""),
                            request.query_params,
                            bridge,
                        )
                        conn.commit()
                    except BaseException:
                        conn.rollback()
                        raise
                return Response(status_code=204) if status == 204 else JSONResponse(result, status)
            except ContractError as exc:
                return exc.response()

        return endpoint

    for method, path, operation, status in OPERATIONS:
        api.add_api_route(
            path,
            handler(operation, status),
            methods=[method],
            operation_id=operation,
            status_code=status,
            response_class=Response,
        )

    @api.exception_handler(404)
    async def not_found(request: Request, exc: Exception) -> Response:
        return ContractError(404, "NOT_FOUND").response()

    @api.exception_handler(405)
    async def method_not_allowed(request: Request, exc: Exception) -> Response:
        return ContractError(404, "NOT_FOUND").response()

    return api


def reject_constant(value: str) -> Any:
    raise ValueError(value)

"""Authentication port and the loopback-only development adapter."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Protocol

from fastapi import Depends, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import Engine, text

from jupjup.api.errors import ApiError
from jupjup.app_api import auth as app_auth
from jupjup.app_api.errors import ContractError
from jupjup.domain.models import USER_ID_RE


class Principal(BaseModel):
    model_config = ConfigDict(frozen=True)

    user_id: str
    auth_kind: str
    scopes: frozenset[str] = frozenset()


class Authenticator(Protocol):
    def authenticate(self, request: Request) -> Principal: ...


class DevHeaderAuthenticator:
    def authenticate(self, request: Request) -> Principal:
        user_id = request.headers.get("X-User-Id")
        if user_id is None:
            raise ApiError(401, "UNAUTHORIZED", "로그인이 필요해요.")
        if user_id.startswith("u_account_"):
            raise ApiError(401, "UNAUTHORIZED", "로그인이 필요해요.")
        if not USER_ID_RE.fullmatch(user_id):
            raise ApiError(
                400,
                "INVALID_USER",
                "사용자 id 형식이 올바르지 않아요.",
                {"pattern": USER_ID_RE.pattern},
            )
        return Principal(user_id=user_id, auth_kind="dev_header", scopes=frozenset({"contents:read"}))


class CompositeAuthenticator:
    def __init__(self, engine: Engine, *, allow_dev: bool = False) -> None:
        self.engine = engine
        self.allow_dev = allow_dev

    def authenticate(self, request: Request) -> Principal:
        # Presence, including an empty/malformed value, forbids development fallback.
        if "authorization" in request.headers:
            try:
                with self.engine.connect() as conn:
                    user, _ = app_auth.authenticate(conn, request.headers["authorization"], datetime.now(UTC))
                    user_id = conn.scalar(
                        text("SELECT user_id FROM account_scopes WHERE account_id=:id"), {"id": user["id"]}
                    )
                    if user_id is None:
                        raise ValueError("missing account scope")
            except (ContractError, ValueError):
                raise ApiError(401, "UNAUTHORIZED", "로그인이 필요해요.") from None
            return Principal(
                user_id=user_id, auth_kind="app_session", scopes=frozenset({"contents:read", "contents:write"})
            )
        if self.allow_dev:
            return DevHeaderAuthenticator().authenticate(request)
        raise ApiError(401, "UNAUTHORIZED", "로그인이 필요해요.")


def get_principal(request: Request) -> Principal:
    authenticator: Authenticator = request.app.state.authenticator
    principal = authenticator.authenticate(request)
    if (
        principal.auth_kind == "dev_header"
        and request.method not in {"GET", "HEAD", "OPTIONS"}
        and request.url.path not in {"/v1/search", "/v1/query:parse"}
    ):
        raise ApiError(401, "UNAUTHORIZED", "저장하거나 변경하려면 로그인해 주세요.")
    return principal


PrincipalDependency = Annotated[Principal, Depends(get_principal)]

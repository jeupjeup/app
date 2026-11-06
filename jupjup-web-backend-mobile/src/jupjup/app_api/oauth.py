"""Server-side OAuth. Only one-time, browser-bound exchange codes reach the SPA."""

import base64
import hashlib
import json
import os
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, build_opener
from urllib.request import Request as HttpRequest
from uuid import uuid4

from fastapi import FastAPI, Request
from sqlalchemy import Connection, Engine, text
from starlette.responses import JSONResponse, RedirectResponse, Response

from jupjup.app_api import auth, validation
from jupjup.app_api.errors import ContractError

PROVIDERS = {
    "google": (
        "https://accounts.google.com/o/oauth2/v2/auth",
        "https://oauth2.googleapis.com/token",
        "https://openidconnect.googleapis.com/v1/userinfo",
    ),
    "naver": (
        "https://nid.naver.com/oauth2.0/authorize",
        "https://nid.naver.com/oauth2.0/token",
        "https://openapi.naver.com/v1/nid/me",
    ),
}
RETURN_PATHS = frozenset({"/dashboard", "/onboarding"})
COOKIE = "oauth_browser"


@dataclass(frozen=True)
class OAuthConfig:
    origin: str
    frontend_callback: str

    @classmethod
    def from_env(cls) -> "OAuthConfig":
        origin = os.environ.get("OAUTH_PUBLIC_ORIGIN", "http://127.0.0.1:5177").rstrip("/")
        parsed = urlsplit(origin)
        if (
            parsed.scheme not in {"https", "http"}
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path
            or parsed.query
            or parsed.fragment
            or (parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost"})
            or any(ord(c) <= 32 or c == "\\" for c in origin)
        ):
            raise ValueError("invalid OAUTH_PUBLIC_ORIGIN")
        callback = os.environ.get("OAUTH_FRONTEND_CALLBACK_URL", origin + "/auth/callback")
        if callback != origin + "/auth/callback":
            raise ValueError("OAUTH_FRONTEND_CALLBACK_URL must be the public origin /auth/callback")
        return cls(origin, callback)

    def credentials(self, provider: str) -> tuple[str, str]:
        if provider not in PROVIDERS:
            raise ContractError(404, "OAUTH_PROVIDER_UNKNOWN")
        client_id = os.environ.get(provider.upper() + "_OAUTH_CLIENT_ID", "")
        secret = os.environ.get(provider.upper() + "_OAUTH_CLIENT_SECRET", "")
        if not client_id or not secret:
            raise ContractError(503, "OAUTH_NOT_CONFIGURED")
        return client_id, secret

    def redirect_uri(self, provider: str) -> str:
        return self.origin + f"/api/auth/oauth/{provider}/callback"


class ProviderHTTP(Protocol):
    def request(self, url: str, *, form: dict[str, str] | None = None, bearer: str | None = None) -> dict[str, Any]: ...


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


class OfficialProviderHTTP:
    def request(self, url: str, *, form: dict[str, str] | None = None, bearer: str | None = None) -> dict[str, Any]:
        headers = {"Accept": "application/json"}
        if bearer:
            headers["Authorization"] = "Bearer " + bearer
        data = None
        if form is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            data = urlencode(form).encode()
        try:
            with build_opener(NoRedirect()).open(HttpRequest(url, data=data, headers=headers), timeout=8) as response:
                raw = response.read(65537)
            if len(raw) > 65536:
                raise ValueError
            result = json.loads(raw)
            if not isinstance(result, dict) or "error" in result:
                raise ValueError
            return result
        except Exception:
            # Do not propagate upstream exceptions: they can contain credentials or provider bodies.
            raise ContractError(502, "OAUTH_PROVIDER_FAILED") from None


def challenge(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


def identity(conn: Connection, provider: str, profile: dict[str, Any], now: datetime) -> tuple[str, bool]:
    if provider == "naver":
        if profile.get("resultcode") != "00" or not isinstance(profile.get("response"), dict):
            raise ContractError(502, "OAUTH_PROFILE_INVALID")
        profile = profile["response"]
    subject = profile.get("sub" if provider == "google" else "id")
    if not isinstance(subject, str) or not 1 <= len(subject) <= 255 or any(ord(c) < 33 for c in subject):
        raise ContractError(502, "OAUTH_PROFILE_INVALID")
    existing = conn.execute(
        text("SELECT user_id FROM oauth_identities WHERE provider=:p AND subject=:s"), dict(p=provider, s=subject)
    ).scalar_one_or_none()
    if existing is not None:
        return str(existing), False
    try:
        email = validation.email({"email": profile.get("email")})
    except ContractError:
        raise ContractError(400, "OAUTH_EMAIL_REQUIRED") from None
    local, domain = email.rsplit("@", 1)
    if (
        len(local) > 64
        or local.startswith(".")
        or local.endswith(".")
        or ".." in local
        or not re.fullmatch(r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+", local)
        or not all(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in domain.split("."))
    ):
        raise ContractError(400, "OAUTH_EMAIL_REQUIRED")
    if provider == "google" and profile.get("email_verified") is not True:
        raise ContractError(400, "OAUTH_EMAIL_UNVERIFIED")
    # No implicit linking, even for verified Google email. Password/Naver ownership is not proven by it.
    if conn.execute(text("SELECT 1 FROM api_users WHERE lower(email)=:email"), dict(email=email)).first():
        raise ContractError(409, "OAUTH_EMAIL_COLLISION")
    user_id = str(uuid4())
    nickname = profile.get("name" if provider == "google" else "nickname")
    if not isinstance(nickname, str) or not nickname.strip():
        nickname = "줍줍 사용자"
    conn.execute(
        text(
            "INSERT INTO api_users (id,email,nickname,consent_at,password_hash,password_salt) "
            "VALUES (:id,:email,:nickname,:now,:password_hash,:password_salt)"
        ),
        dict(
            id=user_id,
            email=email,
            nickname=nickname.strip()[:25],
            now=auth.instant(now),
            **auth.credentials(secrets.token_urlsafe(48)),
        ),
    )
    conn.execute(text("INSERT INTO oauth_identities VALUES (:p,:s,:u)"), dict(p=provider, s=subject, u=user_id))
    return user_id, True


def install(api: FastAPI, engine: Engine) -> None:
    config = OAuthConfig.from_env()
    api.state.oauth_http = OfficialProviderHTTP()
    api.state.oauth_config = config

    def browser_cookie(response: Response, value: str, *, delete: bool = False) -> None:
        response.set_cookie(
            COOKIE,
            "" if delete else value,
            max_age=0 if delete else 600,
            httponly=True,
            secure=config.origin.startswith("https:"),
            samesite="lax",
            path="/",
        )

    def redirect(*, code: str | None = None, error: str | None = None) -> Response:
        response = RedirectResponse(
            config.frontend_callback + "?" + urlencode({"code": code} if code else {"error": error}), status_code=303
        )
        response.headers["Referrer-Policy"] = "no-referrer"
        if error:
            browser_cookie(response, "", delete=True)
        return response

    @api.get("/auth/oauth/{provider}/start", name="oauthStart")
    def start(provider: str, request: Request) -> Response:
        try:
            client_id, _ = config.credentials(provider)
            return_path = request.query_params.get("return_path", "/dashboard")
            if return_path not in RETURN_PATHS:
                raise ContractError(400, "OAUTH_RETURN_PATH_INVALID")
            state, cookie = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            verifier = secrets.token_urlsafe(64) if provider == "google" else ""
            now = request.state.now
            with api.state.lock, engine.begin() as conn:
                conn.execute(text("DELETE FROM oauth_states WHERE expires_at<=:now"), dict(now=auth.instant(now)))
                conn.execute(
                    text("DELETE FROM oauth_exchange_codes WHERE expires_at<=:now"), dict(now=auth.instant(now))
                )
                conn.execute(
                    text("INSERT INTO oauth_states VALUES (:s,:p,:c,:v,:r,:e)"),
                    dict(
                        s=auth.digest(state),
                        p=provider,
                        c=auth.digest(cookie),
                        v=verifier,
                        r=return_path,
                        e=auth.instant(now + timedelta(minutes=5)),
                    ),
                )
            params = dict(
                response_type="code", client_id=client_id, redirect_uri=config.redirect_uri(provider), state=state
            )
            if provider == "google":
                params.update(
                    scope="openid profile email", code_challenge=challenge(verifier), code_challenge_method="S256"
                )
            response = RedirectResponse(PROVIDERS[provider][0] + "?" + urlencode(params), status_code=302)
            browser_cookie(response, cookie)
            response.headers["Referrer-Policy"] = "no-referrer"
            return response
        except ContractError as exc:
            return exc.response()

    @api.get("/auth/oauth/{provider}/callback", name="oauthCallback")
    def callback(provider: str, request: Request) -> Response:
        try:
            client_id, client_secret = config.credentials(provider)
            state = request.query_params.get("state", "")
            cookie = request.cookies.get(COOKIE, "")
            now = request.state.now
            with api.state.lock, engine.begin() as conn:
                row = (
                    conn.execute(
                        text(
                            "DELETE FROM oauth_states WHERE state_hash=:s AND provider=:p AND cookie_hash=:c "
                            "AND expires_at>:now RETURNING *"
                        ),
                        dict(s=auth.digest(state), p=provider, c=auth.digest(cookie), now=auth.instant(now)),
                    )
                    .mappings()
                    .first()
                )
            if row is None or not state or not cookie:
                raise ContractError(400, "OAUTH_STATE_INVALID")
            # Commit consumption before contacting the provider, including denial/error paths.
            if request.query_params.get("error"):
                raise ContractError(400, "OAUTH_DENIED")
            code = request.query_params.get("code", "")
            if not code or len(code) > 4096:
                raise ContractError(400, "OAUTH_CODE_INVALID")
            form = dict(
                grant_type="authorization_code",
                code=code,
                client_id=client_id,
                client_secret=client_secret,
                redirect_uri=config.redirect_uri(provider),
            )
            if provider == "google":
                form["code_verifier"] = row["verifier"]
            else:
                form["state"] = state
            http: ProviderHTTP = api.state.oauth_http
            tokens = http.request(PROVIDERS[provider][1], form=form)
            access = tokens.get("access_token")
            if not isinstance(access, str) or not access or tokens.get("error"):
                raise ContractError(502, "OAUTH_PROVIDER_FAILED")
            profile = http.request(PROVIDERS[provider][2], bearer=access)
            exchange = secrets.token_urlsafe(32)
            with api.state.lock, engine.connect() as conn:
                conn.exec_driver_sql("BEGIN IMMEDIATE")
                user_id, is_new = identity(conn, provider, profile, now)
                conn.execute(
                    text("INSERT INTO oauth_exchange_codes VALUES (:code,:cookie,:user,:path,:new,:expires)"),
                    dict(
                        code=auth.digest(exchange),
                        cookie=auth.digest(cookie),
                        user=user_id,
                        path=row["return_path"],
                        new=int(is_new),
                        expires=auth.instant(now + timedelta(seconds=60)),
                    ),
                )
                conn.commit()
            return redirect(code=exchange)
        except ContractError as exc:
            return redirect(error=exc.code)
        except Exception:
            # A faulty injected client or malformed response must not expose provider data in tracebacks.
            return redirect(error="OAUTH_PROVIDER_FAILED")

    @api.post("/auth/oauth/exchange", name="oauthExchange")
    def exchange(request: Request) -> Response:
        try:
            code = validation.string(request.state.json, "code", 128)
            cookie = request.cookies.get(COOKIE, "")
            with api.state.lock, engine.connect() as conn:
                conn.exec_driver_sql("BEGIN IMMEDIATE")
                row = (
                    conn.execute(
                        text(
                            "DELETE FROM oauth_exchange_codes WHERE code_hash=:code AND cookie_hash=:cookie "
                            "AND expires_at>:now RETURNING *"
                        ),
                        dict(code=auth.digest(code), cookie=auth.digest(cookie), now=auth.instant(request.state.now)),
                    )
                    .mappings()
                    .first()
                )
                if row is None or not cookie:
                    raise ContractError(400, "OAUTH_EXCHANGE_INVALID")
                user = (
                    conn.execute(text("SELECT * FROM api_users WHERE id=:u"), dict(u=row["user_id"])).mappings().one()
                )
                result = {
                    "session": auth.session(conn, dict(user), request.state.now),
                    "returnPath": row["return_path"],
                    "isNewUser": bool(row["is_new"]),
                }
                conn.commit()
            response = JSONResponse(result)
            browser_cookie(response, "", delete=True)
            return response
        except ContractError as exc:
            return exc.response()

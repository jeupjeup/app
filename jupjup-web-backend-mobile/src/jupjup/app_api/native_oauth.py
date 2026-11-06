"""Native SDK exchanges and Google browser PKCE using the common account store.

Provider credentials never reach the app; short-lived exchanges are process-local.
A server restart safely invalidates pending sign-ins.
"""

import hmac
import os
import re
import secrets
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlencode, urlsplit

from fastapi import FastAPI, Request
from sqlalchemy import Engine, text
from starlette.responses import JSONResponse, RedirectResponse, Response

from jupjup.app_api import auth, oauth, validation
from jupjup.app_api.errors import ContractError

APP_REDIRECT = "jeupjeupsave://login"


def install(api: FastAPI, engine: Engine) -> None:
    states: dict[str, dict[str, Any]] = {}
    codes: dict[str, dict[str, Any]] = {}

    def prune(now: datetime) -> None:
        for pending in (states, codes):
            for key in list(pending):
                if pending[key]["expires"] <= now:
                    del pending[key]

    def credentials() -> tuple[str, str]:
        cid = os.environ.get("GOOGLE_CLIENT_ID") or os.environ.get("GOOGLE_OAUTH_CLIENT_ID")
        secret = os.environ.get("GOOGLE_CLIENT_SECRET") or os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET")
        if not cid or not secret:
            raise ContractError(503, "OAUTH_NOT_CONFIGURED")
        return cid, secret

    def callback_url() -> str:
        origin = os.environ.get("API_PUBLIC_ORIGIN", "http://127.0.0.1:8000").rstrip("/")
        parts = urlsplit(origin)
        if (
            parts.scheme not in ("http", "https") or not parts.netloc or parts.path
            or parts.query or parts.fragment or parts.username or parts.password
            or (parts.scheme == "http" and parts.hostname not in ("localhost", "127.0.0.1"))
        ):
            raise ContractError(503, "OAUTH_NOT_CONFIGURED")
        return origin + "/api/auth/oauth/google/native-callback"

    def session(provider: str, profile: dict[str, Any], now: datetime) -> dict[str, Any]:
        with api.state.lock, engine.connect() as conn:
            conn.exec_driver_sql("BEGIN IMMEDIATE")
            uid, _ = oauth.identity(conn, provider, profile, now)
            user = conn.execute(text("SELECT * FROM api_users WHERE id=:id"), {"id": uid}).mappings().one()
            result = auth.session(conn, dict(user), now)
            conn.commit()
        return result

    @api.get("/auth/oauth/google/authorize")
    def authorize(request: Request) -> Response:
        try:
            cid, _ = credentials()
            query = request.query_params
            required = ("state", "redirect_uri", "code_challenge", "code_challenge_method", "keep_me_logged_in")
            if any(len(query.getlist(key)) != 1 for key in required):
                raise ContractError(400, "INVALID_OAUTH_REQUEST")
            state, challenge = query["state"], query["code_challenge"]
            if (
                not re.fullmatch(r"[a-f0-9]{64}", state)
                or not re.fullmatch(r"[A-Za-z0-9_-]{43}", challenge)
                or query["redirect_uri"] != APP_REDIRECT or query["code_challenge_method"] != "S256"
                or query["keep_me_logged_in"] not in ("true", "false")
            ):
                raise ContractError(400, "INVALID_OAUTH_REQUEST")
            server_state = secrets.token_urlsafe(32)
            redirect_uri = callback_url()
            with api.state.lock:
                prune(request.state.now)
                if len(states) >= 1000:
                    raise ContractError(429, "RATE_LIMITED")
                states[auth.digest(server_state)] = {
                    "state": state, "challenge": challenge, "redirect_uri": redirect_uri,
                    "expires": request.state.now + timedelta(minutes=5),
                }
            params = dict(
                client_id=cid, redirect_uri=redirect_uri, response_type="code", scope="openid email profile",
                state=server_state, code_challenge=challenge, code_challenge_method="S256",
            )
            return RedirectResponse(oauth.PROVIDERS["google"][0] + "?" + urlencode(params), 302)
        except ContractError as exc:
            return exc.response()

    @api.get("/auth/oauth/google/native-callback")
    def callback(request: Request) -> Response:
        # Store the provider authorization code until the app supplies its PKCE verifier.
        with api.state.lock:
            prune(request.state.now)
            row = states.pop(auth.digest(request.query_params.get("state", "")), None)
            if row is None:
                return ContractError(400, "OAUTH_STATE_INVALID").response()
            result = {"state": row["state"]}
            if request.query_params.get("error"):
                denied = request.query_params["error"] == "access_denied"
                result["error"] = "access_denied" if denied else "server_error"
            elif len(request.query_params.getlist("code")) != 1 or not request.query_params["code"]:
                result["error"] = "server_error"
            else:
                code = secrets.token_urlsafe(32)
                codes[auth.digest(code)] = {
                    **row, "provider_code": request.query_params["code"],
                    "expires": request.state.now + timedelta(seconds=60),
                }
                result["code"] = code
        response = RedirectResponse(APP_REDIRECT + "?" + urlencode(result), 303)
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @api.post("/auth/oauth/google/exchange")
    def exchange_google(request: Request) -> Response:
        try:
            body, now = request.state.json, request.state.now
            code = validation.string(body, "code", 128)
            verifier = validation.string(body, "code_verifier", 128)
            if not re.fullmatch(r"[A-Za-z0-9._~-]{43,128}", verifier) or body.get("redirect_uri") != APP_REDIRECT:
                raise ContractError(400, "INVALID_OAUTH_REQUEST")
            with api.state.lock:
                prune(now)
                row = codes.get(auth.digest(code))
                if (
                    row is None or row["state"] != body.get("state")
                    or not hmac.compare_digest(oauth.challenge(verifier), row["challenge"])
                ):
                    raise ContractError(401, "INVALID_OAUTH_CODE")
                del codes[auth.digest(code)]
            cid, secret = credentials()
            tokens = api.state.oauth_http.request(oauth.PROVIDERS["google"][1], form={
                "grant_type": "authorization_code", "code": row["provider_code"], "client_id": cid,
                "client_secret": secret, "redirect_uri": row["redirect_uri"], "code_verifier": verifier,
            })
            token = tokens.get("access_token")
            if not isinstance(token, str) or not token:
                raise ContractError(502, "OAUTH_PROVIDER_FAILED")
            profile = api.state.oauth_http.request(oauth.PROVIDERS["google"][2], bearer=token)
            return JSONResponse(session("google", profile, now))
        except ContractError as exc:
            return exc.response()

    @api.post("/auth/oauth/{provider}/exchange")
    def exchange_native(provider: str, request: Request) -> Response:
        try:
            if provider not in ("naver", "kakao"):
                raise ContractError(404, "OAUTH_PROVIDER_UNKNOWN")
            token = validation.string(request.state.json, "access_token", 8192, 10)
            if any(char.isspace() for char in token):
                raise ContractError(400, "VALIDATION_ERROR")
            http = api.state.oauth_http
            if provider == "naver":
                profile = http.request(oauth.PROVIDERS["naver"][2], bearer=token)
            else:
                app_id = os.environ.get("KAKAO_APP_ID", "")
                if not app_id:
                    raise ContractError(503, "OAUTH_NOT_CONFIGURED")
                info = http.request("https://kapi.kakao.com/v1/user/access_token_info", bearer=token)
                if (str(info.get("app_id")) != app_id
                    or not isinstance(info.get("expires_in"), int) or info["expires_in"] <= 0):
                    raise ContractError(401, "INVALID_PROVIDER_TOKEN")
                raw = http.request("https://kapi.kakao.com/v2/user/me", bearer=token)
                if not raw.get("id") or str(raw["id"]) != str(info.get("id")):
                    raise ContractError(401, "INVALID_PROVIDER_TOKEN")
                account = raw.get("kakao_account", {})
                if account.get("is_email_verified") is not True:
                    raise ContractError(400, "OAUTH_EMAIL_UNVERIFIED")
                profile = {"id": str(raw["id"]), "email": account.get("email"),
                           "nickname": account.get("profile", {}).get("nickname")}
            return JSONResponse(session(provider, profile, request.state.now))
        except ContractError as exc:
            return exc.response()

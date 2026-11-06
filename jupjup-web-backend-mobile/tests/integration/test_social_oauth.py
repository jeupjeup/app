"""Offline OAuth contract: provider HTTP is injected, all databases are in memory."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from jupjup.api.errors import ApiError
from jupjup.app_api import auth
from jupjup.app_api.http import create_api
from jupjup.app_api.oauth import COOKIE, PROVIDERS, OAuthConfig, OfficialProviderHTTP, challenge
from jupjup.app_api.oauth_logging import OAuthAccessFilter
from jupjup.auth import CompositeAuthenticator
from jupjup.domain.models import USER_ID_RE
from jupjup.storage.db import create_db_engine
from jupjup.storage.migration import MigrationError
from jupjup.storage.oauth_migration import run_migrations

NOW = datetime.now(UTC)


class FakeHTTP:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str] | None, str | None]] = []
        self.profile: dict[str, Any] = {
            "sub": "subject-one",
            "email": "social@example.com",
            "email_verified": True,
            "name": "Social",
        }
        self.tokens: dict[str, Any] = {"access_token": "fake-provider-access"}
        self.fail = False

    def request(self, url: str, *, form: dict[str, str] | None = None, bearer: str | None = None) -> dict[str, Any]:
        self.calls.append((url, form, bearer))
        if self.fail:
            raise RuntimeError("NEVER_LOG_PROVIDER_BODY")
        return self.tokens if url.endswith("/token") else self.profile


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    # Synthetic values only. These are deliberately not real provider credentials.
    for provider in ("GOOGLE", "NAVER"):
        monkeypatch.setenv(provider + "_OAUTH_CLIENT_ID", "fake-id")
        monkeypatch.setenv(provider + "_OAUTH_CLIENT_SECRET", "fake-secret")
    monkeypatch.delenv("OAUTH_PUBLIC_ORIGIN", raising=False)
    monkeypatch.delenv("OAUTH_FRONTEND_CALLBACK_URL", raising=False)
    engine = create_db_engine(None)
    api = create_api(engine)
    api.state.clock = lambda: NOW
    api.state.oauth_http = FakeHTTP()
    app = FastAPI()
    app.state.api, app.state.engine = api, engine
    app.mount("/api", api)
    with TestClient(app) as c:
        yield c
    engine.dispose()


def api(client: TestClient) -> Any:
    return client.app.state.api  # type: ignore[union-attr]


def engine(client: TestClient) -> Any:
    return client.app.state.engine  # type: ignore[union-attr]


def start(client: TestClient, provider: str = "google", path: str = "/dashboard") -> dict[str, list[str]]:
    response = client.get(f"/api/auth/oauth/{provider}/start", params={"return_path": path}, follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["cache-control"] == "no-store"
    assert "HttpOnly" in response.headers["set-cookie"] and "SameSite=lax" in response.headers["set-cookie"]
    return parse_qs(urlsplit(response.headers["location"]).query)


def callback(client: TestClient, state: str, provider: str = "google", **params: str) -> Any:
    return client.get(f"/api/auth/oauth/{provider}/callback", params={"state": state, **params}, follow_redirects=False)


def finish(client: TestClient, provider: str = "google") -> tuple[str, Any]:
    params = start(client, provider)
    response = callback(client, params["state"][0], provider, code="fake-provider-code")
    assert response.status_code == 303
    query = parse_qs(urlsplit(response.headers["location"]).query)
    assert set(query) == {"code"}, response.headers["location"]
    return query["code"][0], response


def exchange(client: TestClient, code: str) -> Any:
    return client.post("/api/auth/oauth/exchange", json={"code": code})


def test_google_pkce_cookie_state_exchange_and_no_token_in_redirect(client: TestClient) -> None:
    params = start(client)
    assert params["scope"] == ["openid profile email"]
    assert params["code_challenge_method"] == ["S256"]
    assert params["redirect_uri"] == ["http://127.0.0.1:5177/api/api/auth/oauth/google/callback"]
    with engine(client).connect() as conn:
        state = conn.exec_driver_sql("SELECT * FROM oauth_states").mappings().one()
        assert state["state_hash"] == auth.digest(params["state"][0])
        assert state["cookie_hash"] == auth.digest(client.cookies[COOKIE])
        assert params["code_challenge"] == [challenge(state["verifier"])]
    response = callback(client, params["state"][0], code="fake-provider-code")
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "fake-provider" not in response.headers["location"] and "token" not in response.headers["location"]
    code = parse_qs(urlsplit(response.headers["location"]).query)["code"][0]
    calls = api(client).state.oauth_http.calls
    assert calls[0][0] == PROVIDERS["google"][1]
    assert calls[0][1]["code_verifier"] == state["verifier"]
    assert calls[1] == (PROVIDERS["google"][2], None, "fake-provider-access")
    with engine(client).connect() as conn:
        assert conn.exec_driver_sql("SELECT count(*) FROM api_sessions").scalar_one() == 0
        assert conn.exec_driver_sql("SELECT code_hash FROM oauth_exchange_codes").scalar_one() == auth.digest(code)
    result = exchange(client, code)
    assert result.status_code == 200
    data = result.json()
    assert data["isNewUser"] and data["returnPath"] == "/dashboard"
    assert len(data["session"]["token"]) == 64
    assert data["session"]["expiresAt"] == auth.instant(NOW + timedelta(days=30))
    assert client.get("/api/me", headers={"Authorization": "Bearer " + data["session"]["token"]}).status_code == 200
    assert exchange(client, code).status_code == 400
    assert COOKIE not in client.cookies
    assert set(data["session"]) == {"token", "expiresAt", "user"}


def test_naver_flow_no_unsupported_pkce_and_subject_replay(client: TestClient) -> None:
    http = api(client).state.oauth_http
    http.profile = {"resultcode": "00", "response": {"id": "naver-subject", "email": "n@example.com"}}
    params = start(client, "naver", "/onboarding")
    assert "scope" not in params and "code_challenge" not in params
    response = callback(client, params["state"][0], "naver", code="naver-code")
    code = parse_qs(urlsplit(response.headers["location"]).query)["code"][0]
    first = exchange(client, code).json()
    assert first["returnPath"] == "/onboarding"
    assert http.calls[0][1]["state"] == params["state"][0]
    assert http.calls[1][0] == "https://openapi.naver.com/v1/nid/me"
    # Durable subject wins over absent/changed email on later logins.
    http.profile["response"] = {"id": "naver-subject"}
    code, _ = finish(client, "naver")
    second = exchange(client, code).json()
    assert second["session"]["user"]["id"] == first["session"]["user"]["id"]
    assert second["isNewUser"] is False


def test_wrong_cookie_provider_and_state_cannot_consume_state(client: TestClient) -> None:
    params = start(client)
    state, cookie = params["state"][0], client.cookies[COOKIE]
    client.cookies.clear()
    assert "OAUTH_STATE_INVALID" in callback(client, state, code="x").headers["location"]
    client.cookies.set(COOKIE, cookie)
    assert "OAUTH_STATE_INVALID" in callback(client, state, "naver", code="x").headers["location"]
    client.cookies.set(COOKIE, cookie)
    assert "OAUTH_STATE_INVALID" in callback(client, "forged", code="x").headers["location"]
    assert not api(client).state.oauth_http.calls
    client.cookies.set(COOKIE, cookie)
    assert "?code=" in callback(client, state, code="x").headers["location"]
    assert "OAUTH_STATE_INVALID" in callback(client, state, code="x").headers["location"]


@pytest.mark.parametrize("params,error", [({"error": "access_denied"}, "OAUTH_DENIED"), ({}, "OAUTH_CODE_INVALID")])
def test_callback_errors_are_fixed_and_consume_state(client: TestClient, params: dict[str, str], error: str) -> None:
    state = start(client)["state"][0]
    cookie = client.cookies[COOKIE]
    assert error in callback(client, state, **params).headers["location"]
    client.cookies.set(COOKIE, cookie)
    assert "OAUTH_STATE_INVALID" in callback(client, state, code="x").headers["location"]
    assert not api(client).state.oauth_http.calls


def test_expiry_and_exchange_cookie_binding(client: TestClient) -> None:
    state = start(client)["state"][0]
    api(client).state.clock = lambda: NOW + timedelta(minutes=5)
    assert "OAUTH_STATE_INVALID" in callback(client, state, code="x").headers["location"]
    api(client).state.clock = lambda: NOW
    code, _ = finish(client)
    cookie = client.cookies[COOKIE]
    client.cookies.clear()
    assert exchange(client, code).status_code == 400
    client.cookies.set(COOKIE, cookie)
    api(client).state.clock = lambda: NOW + timedelta(seconds=60)
    assert exchange(client, code).status_code == 400
    with engine(client).connect() as conn:
        assert conn.exec_driver_sql("SELECT count(*) FROM api_sessions").scalar_one() == 0


@pytest.mark.parametrize(
    "path", ["//evil.example", "https://evil.example", "/dashboard?x=1", "/dashboard/", "/%64ashboard"]
)
def test_exact_return_path_allowlist(client: TestClient, path: str) -> None:
    assert client.get("/api/auth/oauth/google/start", params={"return_path": path}).status_code == 400


@pytest.mark.parametrize(
    "profile,error",
    [
        ({"sub": "s"}, "OAUTH_EMAIL_REQUIRED"),
        ({"sub": "s", "email": "invalid"}, "OAUTH_EMAIL_REQUIRED"),
        ({"sub": "s", "email": "a@example.com", "email_verified": "true"}, "OAUTH_EMAIL_UNVERIFIED"),
        ({"email": "a@example.com"}, "OAUTH_PROFILE_INVALID"),
    ],
)
def test_invalid_profile_creates_no_user(client: TestClient, profile: dict[str, Any], error: str) -> None:
    api(client).state.oauth_http.profile = profile
    state = start(client)["state"][0]
    assert error in callback(client, state, code="x").headers["location"]
    with engine(client).connect() as conn:
        assert conn.exec_driver_sql("SELECT count(*) FROM api_users").scalar_one() == 0


def test_provider_isolation_and_email_collision_never_auto_link(client: TestClient) -> None:
    code, _ = finish(client)
    first = exchange(client, code).json()["session"]
    http = api(client).state.oauth_http
    http.profile = {"resultcode": "00", "response": {"id": "subject-one", "email": "social@example.com"}}
    state = start(client, "naver")["state"][0]
    assert "OAUTH_EMAIL_COLLISION" in callback(client, state, "naver", code="x").headers["location"]
    http.profile["response"]["email"] = "other@example.com"
    code, _ = finish(client, "naver")
    second = exchange(client, code).json()["session"]
    assert second["user"]["id"] != first["user"]["id"]
    http.profile = {"sub": "different-sub", "email": "social@example.com", "email_verified": True}
    state = start(client)["state"][0]
    assert "OAUTH_EMAIL_COLLISION" in callback(client, state, code="x").headers["location"]


def test_password_email_collision(client: TestClient) -> None:
    assert (
        client.post(
            "/api/auth/register",
            json={"email": "social@example.com", "password": "Password1!", "nickname": "User", "requiredConsent": True},
        ).status_code
        == 201
    )
    state = start(client)["state"][0]
    assert "OAUTH_EMAIL_COLLISION" in callback(client, state, code="x").headers["location"]
    assert (
        client.post("/api/auth/login", json={"email": "social@example.com", "password": "Password1!"}).status_code
        == 200
    )


def test_provider_failure_has_no_leaks(client: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    api(client).state.oauth_http.fail = True
    state = start(client)["state"][0]
    response = callback(client, state, code="private-provider-code")
    assert response.headers["location"] == "http://127.0.0.1:5177/auth/callback?error=OAUTH_PROVIDER_FAILED"
    assert "NEVER_LOG_PROVIDER_BODY" not in caplog.text
    assert "fake-secret" not in caplog.text
    with engine(client).connect() as conn:
        assert conn.exec_driver_sql("SELECT count(*) FROM oauth_states").scalar_one() == 0


def test_config_absent_and_origin_enforcement(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_SECRET")
    assert client.get("/api/auth/oauth/google/start").json()["error"]["code"] == "OAUTH_NOT_CONFIGURED"
    assert client.get("/api/auth/oauth/kakao/start").status_code == 404
    assert exchange(client, "bad").status_code == 400
    assert (
        client.post(
            "/api/auth/oauth/exchange", json={"code": "x"}, headers={"Origin": "https://evil.example"}
        ).status_code
        == 403
    )
    response = client.options(
        "/api/auth/oauth/exchange",
        headers={"Origin": "http://127.0.0.1:5177", "Access-Control-Request-Headers": "content-type"},
    )
    assert response.status_code == 204 and response.headers["access-control-allow-credentials"] == "true"
    monkeypatch.setenv("OAUTH_PUBLIC_ORIGIN", "https://app.example")
    monkeypatch.setenv("OAUTH_FRONTEND_CALLBACK_URL", "https://evil.example/auth/callback")
    with pytest.raises(ValueError):
        OAuthConfig.from_env()
    monkeypatch.setenv("OAUTH_FRONTEND_CALLBACK_URL", "https://app.example/auth/callback")
    assert OAuthConfig.from_env().redirect_uri("naver") == "https://app.example/api/api/auth/oauth/naver/callback"


def test_composite_bearer_uuid_mapping_no_failure_fallback(client: TestClient) -> None:
    code, _ = finish(client)
    session = exchange(client, code).json()["session"]
    authenticator = CompositeAuthenticator(engine(client), allow_dev=True)

    def request(value: str | None) -> Request:
        headers = [(b"x-user-id", b"u_dev")]
        if value is not None:
            headers.append((b"authorization", value.encode()))
        return Request({"type": "http", "headers": headers})

    principal = authenticator.authenticate(request("Bearer " + session["token"]))
    assert USER_ID_RE.fullmatch(principal.user_id)
    assert principal.user_id == "u_account_" + session["user"]["id"].replace("-", "")
    assert authenticator.authenticate(request("Bearer " + session["token"])) == principal
    assert authenticator.authenticate(request(None)).user_id == "u_dev"
    for bad in ("", "Bearer invalid", "Basic ignored", "Bearer " + "0" * 64):
        with pytest.raises(ApiError) as exc:
            authenticator.authenticate(request(bad))
        assert exc.value.status_code == 401
    with pytest.raises(ApiError):
        CompositeAuthenticator(engine(client)).authenticate(request(None))


def test_migration_idempotent_and_tamper_detection(client: TestClient) -> None:
    run_migrations(engine(client), auto_migrate=False)
    with engine(client).begin() as conn:
        conn.exec_driver_sql("UPDATE oauth_migrations SET checksum='modified'")
    with pytest.raises(MigrationError):
        run_migrations(engine(client))


def test_access_logging_redacts_queries() -> None:
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        "",
        0,
        "%s %s %s %s %s",
        ("peer", "GET", "/api/auth/oauth/google/callback?code=private&state=private", "1.1", 303),
        None,
    )
    assert OAuthAccessFilter().filter(record)
    assert "private" not in record.getMessage()


def test_official_http_converts_sensitive_transport_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    class FailingOpener:
        def open(self, *args: Any, **kwargs: Any) -> None:
            raise ValueError("sensitive body")

    monkeypatch.setattr("jupjup.app_api.oauth.build_opener", lambda *_: FailingOpener())
    with pytest.raises(Exception) as exc:
        OfficialProviderHTTP().request(PROVIDERS["google"][1], form={"client_secret": "fake"})
    assert str(exc.value) != "sensitive body"


def test_v1_social_session_smoke(container_factory: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from jupjup.api.app import create_app

    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "fake-id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "fake-secret")
    container = container_factory()
    app = create_app(container=container)
    mounted = next(route.app for route in app.routes if getattr(route, "path", None) == "/api")
    mounted.state.oauth_http = FakeHTTP()
    with TestClient(app) as c:
        code, _ = finish(c)
        session = exchange(c, code).json()["session"]
        headers = {"Authorization": "Bearer " + session["token"], "X-User-Id": "u_spoof"}
        assert c.get("/v1/contents", headers=headers).status_code == 200
        assert c.post("/v1/search", headers=headers, json={"query": "test"}).status_code == 200
        assert c.get("/v1/contents", headers={**headers, "Authorization": "Bearer invalid"}).status_code == 401
        assert c.post("/api/auth/logout", headers=headers, json={}).status_code == 204
        assert c.get("/v1/contents", headers=headers).status_code == 401
    container.engine.dispose()


@pytest.mark.parametrize("tokens", [{}, {"error": "private-provider-body"}, {"access_token": ""}])
def test_token_failures_are_fixed_errors(client: TestClient, tokens: dict[str, Any]) -> None:
    api(client).state.oauth_http.tokens = tokens
    state = start(client)["state"][0]
    response = callback(client, state, code="x")
    assert response.headers["location"].endswith("?error=OAUTH_PROVIDER_FAILED")
    assert len(api(client).state.oauth_http.calls) == 1


def test_exchange_single_use_even_when_browser_cookie_is_retained(client: TestClient) -> None:
    code, _ = finish(client)
    cookie = client.cookies[COOKIE]
    assert exchange(client, code).status_code == 200
    client.cookies.set(COOKIE, cookie)
    assert exchange(client, code).status_code == 400
    with engine(client).connect() as conn:
        assert conn.exec_driver_sql("SELECT count(*) FROM api_sessions").scalar_one() == 1


@pytest.mark.parametrize(
    "email", ["a..b@example.com", ".a@example.com", "a@-bad.example", "<a>@example.com", "a@ex..com"]
)
def test_strict_provider_email_validation(client: TestClient, email: str) -> None:
    api(client).state.oauth_http.profile["email"] = email
    state = start(client)["state"][0]
    assert callback(client, state, code="x").headers["location"].endswith("?error=OAUTH_EMAIL_REQUIRED")


def test_concurrent_exchange_has_one_winner(client: TestClient) -> None:
    from concurrent.futures import ThreadPoolExecutor

    code, _ = finish(client)
    cookie = client.cookies[COOKIE]

    def attempt(_: int) -> int:
        return client.post(
            "/api/auth/oauth/exchange", json={"code": code}, headers={"Cookie": f"{COOKIE}={cookie}"}
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(attempt, range(2))) == [200, 400]


def test_expired_bearer_never_uses_development_fallback(client: TestClient) -> None:
    code, _ = finish(client)
    session = exchange(client, code).json()["session"]
    with engine(client).begin() as conn:
        conn.exec_driver_sql("UPDATE api_sessions SET expires_at='2000-01-01T00:00:00.000Z'")
    request = Request(
        {
            "type": "http",
            "headers": [(b"authorization", ("Bearer " + session["token"]).encode()), (b"x-user-id", b"u_dev")],
        }
    )
    with pytest.raises(ApiError):
        CompositeAuthenticator(engine(client), allow_dev=True).authenticate(request)


def test_secure_host_only_production_cookie(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OAUTH_PUBLIC_ORIGIN", "https://app.example")
    monkeypatch.setenv("OAUTH_FRONTEND_CALLBACK_URL", "https://app.example/auth/callback")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "fake-id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "fake-secret")
    db = create_db_engine(None)
    app = create_api(db)
    with TestClient(app, base_url="https://app.example") as c:
        response = c.get("/auth/oauth/google/start", follow_redirects=False)
        cookie = response.headers["set-cookie"]
        assert "Secure" in cookie and "HttpOnly" in cookie and "Domain=" not in cookie
        assert "SameSite=lax" in cookie and "Max-Age=600" in cookie
    db.dispose()


def test_route_names_and_database_contains_no_provider_credentials(client: TestClient) -> None:
    routes = {route.name: (route.path, route.methods) for route in api(client).routes}
    assert routes["oauthStart"] == ("/auth/oauth/{provider}/start", {"GET"})
    assert routes["oauthCallback"] == ("/auth/oauth/{provider}/callback", {"GET"})
    assert routes["oauthExchange"] == ("/auth/oauth/exchange", {"POST"})
    code, _ = finish(client)
    result = exchange(client, code).json()
    with engine(client).connect() as conn:
        stored = repr(
            [
                conn.exec_driver_sql("SELECT * FROM " + table).all()
                for table in ("oauth_states", "oauth_exchange_codes", "oauth_identities", "api_users", "api_sessions")
            ]
        )
    for private in ("fake-secret", "fake-provider-code", "fake-provider-access", code, result["session"]["token"]):
        assert private not in stored

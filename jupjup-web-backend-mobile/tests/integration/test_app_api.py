"""Offline contract, tenant boundaries and security tests on an in-memory database."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator, FormatChecker
from sqlalchemy import Engine

from jupjup.api.app import create_app
from jupjup.app_api.auth import instant
from jupjup.app_api.http import OPERATIONS, create_api
from jupjup.container import AppContainer
from jupjup.storage.app_api_migration import run_migrations
from jupjup.storage.db import create_db_engine
from jupjup.storage.migration import MigrationError

SPEC = json.loads((Path(__file__).resolve().parents[2] / "specs/app_api_openapi.json").read_text())
NOW = datetime(2026, 11, 6, tzinfo=UTC)


@pytest.fixture
def client() -> Iterator[TestClient]:
    engine = create_db_engine(None)
    api = create_api(engine, origins={"https://app.example"})
    api.state.clock = lambda: NOW
    app = FastAPI()
    app.state.engine = engine
    app.state.api = api
    app.mount("/api", api)
    with TestClient(app, raise_server_exceptions=False) as result:
        yield result
    engine.dispose()


def db(client: TestClient) -> Engine:
    return client.app.state.engine  # type: ignore[union-attr,no-any-return]


def advance(client: TestClient, delta: timedelta) -> None:
    client.app.state.api.state.clock = lambda: NOW + delta  # type: ignore[union-attr]


def register(client: TestClient, email: str = "User@Example.com") -> dict[str, Any]:
    response = client.post(
        "/api/auth/register",
        json={
            "email": email,
            "nickname": "사용자",
            "password": "Password1!",
            "requiredConsent": True,
            "notificationsEnabled": False,
        },
    )
    assert response.status_code == 201, response.text
    data: dict[str, Any] = response.json()
    client.headers["Authorization"] = "Bearer " + data["token"]
    return data


def error(response: Any, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    assert response.json() == {"error": {"code": code, "message": "요청을 처리할 수 없습니다."}}


def create(client: TestClient, url: str = "https://example.com/article") -> dict[str, Any]:
    response = client.post("/api/contents", json={"url": url, "memo": "여행 준비"})
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


def test_auth_sessions_storage_expiry_logout(client: TestClient) -> None:
    session = register(client)
    assert session["expiresAt"] == instant(NOW + timedelta(days=30))
    assert session["user"]["email"] == "user@example.com"
    assert len(session["token"]) == 64
    with db(client).connect() as conn:
        user = conn.exec_driver_sql("SELECT * FROM api_users").mappings().one()
        assert user["consent_at"] == instant(NOW)
        assert user["password_hash"] != "Password1!" and len(user["password_salt"]) == 32
        assert (
            conn.exec_driver_sql("SELECT token_hash FROM api_sessions").scalar_one()
            == hashlib.sha256(session["token"].encode()).hexdigest()
        )
    error(
        client.post(
            "/api/auth/register",
            json={"email": "USER@example.com", "nickname": "n", "password": "Password1!", "requiredConsent": True},
        ),
        409,
        "EMAIL_EXISTS",
    )
    error(
        client.post("/api/auth/login", json={"email": "user@example.com", "password": "bad"}),
        401,
        "INVALID_CREDENTIALS",
    )
    error(
        client.post("/api/auth/login", json={"email": "absent@example.com", "password": "bad"}),
        401,
        "INVALID_CREDENTIALS",
    )
    second = client.post("/api/auth/login", json={"email": "USER@example.com", "password": "Password1!"}).json()
    assert second["token"] != session["token"]
    assert client.post("/api/auth/logout", json={}).content == b""
    error(client.get("/api/me"), 401, "UNAUTHORIZED")
    client.headers["Authorization"] = "Bearer " + second["token"]
    assert client.get("/api/me").json() == session["user"]
    advance(client, timedelta(days=30))
    error(client.get("/api/me"), 401, "UNAUTHORIZED")


def test_password_lock_shared_reset_and_expiry(client: TestClient) -> None:
    register(client)
    for _n in range(4):
        error(client.post("/api/me/password/verify", json={"currentPassword": "bad"}), 401, "INVALID_CREDENTIALS")
    assert client.post("/api/me/password/verify", json={"currentPassword": "Password1!"}).status_code == 204
    for n in range(5):
        response = client.patch("/api/me/password", json={"currentPassword": "bad", "newPassword": "Changed1!"})
        error(response, 429 if n == 4 else 401, "PASSWORD_LOCKED" if n == 4 else "INVALID_CREDENTIALS")
    error(client.post("/api/me/password/verify", json={"currentPassword": "Password1!"}), 429, "PASSWORD_LOCKED")
    assert (
        client.post("/api/auth/login", json={"email": "user@example.com", "password": "Password1!"}).status_code == 200
    )
    advance(client, timedelta(hours=24))
    assert client.post("/api/me/password/verify", json={"currentPassword": "Password1!"}).status_code == 204
    with db(client).connect() as conn:
        assert conn.exec_driver_sql("SELECT password_failures FROM api_users").scalar_one() == 0


def test_change_password_revokes_other_sessions_and_delete_cascades(client: TestClient) -> None:
    first = register(client)
    second = client.post("/api/auth/login", json={"email": "user@example.com", "password": "Password1!"}).json()
    create(client)
    client.post("/api/search-history", json={"query": "여행"})
    assert client.patch("/api/me", json={"nickname": "새 이름"}).json()["nickname"] == "새 이름"
    assert (
        client.patch("/api/me/password", json={"currentPassword": "Password1!", "newPassword": "Changed1!"}).status_code
        == 204
    )
    assert client.get("/api/me").status_code == 200
    error(client.get("/api/me", headers={"Authorization": "Bearer " + second["token"]}), 401, "UNAUTHORIZED")
    error(
        client.post("/api/auth/login", json={"email": "user@example.com", "password": "Password1!"}),
        401,
        "INVALID_CREDENTIALS",
    )
    assert (
        client.post("/api/auth/login", json={"email": "user@example.com", "password": "Changed1!"}).status_code == 200
    )
    assert client.delete("/api/me").content == b""
    error(client.get("/api/me", headers={"Authorization": "Bearer " + first["token"]}), 401, "UNAUTHORIZED")
    with db(client).connect() as conn:
        for table in ("api_users", "api_sessions", "api_contents", "api_notices", "api_search_history"):
            assert conn.exec_driver_sql(f"SELECT count(*) FROM {table}").scalar_one() == 0
        assert not conn.exec_driver_sql("PRAGMA foreign_key_check").all()


def test_content_lifecycle_duplicate_restore_and_trash(client: TestClient) -> None:
    register(client)
    item = create(client, "HTTPS://EXAMPLE.COM:443/a/../article#secret")
    assert item == {
        "id": item["id"],
        "title": "example.com",
        "url": "https://example.com/article",
        "memo": "여행 준비",
        "type": "기타",
        "source": "example.com",
        "description": "",
        "tags": [],
        "savedAt": instant(NOW),
        "status": "ready",
    }
    path = "/api/contents/" + item["id"]
    error(client.post("/api/contents", json={"url": item["url"] + "#different"}), 409, "DUPLICATE_CONTENT")
    assert client.post(path + "/view", json={}).status_code == 204
    changed = client.patch(path, json={"title": "여행", "type": "텍스트", "collection": "여행", "memo": "수정"}).json()
    assert changed["viewedAt"] == instant(NOW) and changed["collection"] == "여행"
    assert "collection" not in client.patch(path, json={"collection": None}).json()
    assert client.delete(path).status_code == 204
    deleted = client.get(path).json()["deletedAt"]
    advance(client, timedelta(days=1))
    assert client.delete(path).status_code == 204
    assert client.get(path).json()["deletedAt"] == deleted
    error(client.patch(path, json={"memo": "no"}), 409, "CONTENT_DELETED")
    error(client.post(path + "/view", json={}), 409, "CONTENT_DELETED")
    assert client.get("/api/state").json()["savedCount"] == 0
    assert client.get("/api/contents").json() == {"items": [], "total": 0}
    replacement = create(client)
    error(client.post(path + "/restore", json={}), 409, "DUPLICATE_CONTENT")
    client.delete("/api/contents/" + replacement["id"])
    assert client.post(path + "/restore", json={}).json()["id"] == item["id"]
    assert client.post(path + "/restore", json={}).status_code == 200
    assert client.delete("/api/trash").status_code == 204
    error(client.get("/api/contents/" + replacement["id"]), 404, "NOT_FOUND")
    assert client.get(path).status_code == 200


def test_purge_at_thirty_days_on_next_request(client: TestClient) -> None:
    register(client)
    item = create(client)
    path = "/api/contents/" + item["id"]
    client.delete(path)
    advance(client, timedelta(days=30) - timedelta(milliseconds=1))
    assert client.get(path).status_code == 200
    advance(client, timedelta(days=30))
    assert client.get("/api/health").status_code == 200
    with db(client).connect() as conn:
        assert conn.exec_driver_sql("SELECT count(*) FROM api_contents").scalar_one() == 0


def test_isolation_and_indistinguishable_missing_ids(client: TestClient) -> None:
    first = register(client)
    item = create(client)
    notice = client.get("/api/notices").json()["items"][0]
    client.post("/api/search-history", json={"query": "private"})
    register(client, "other@example.com")
    for method, suffix, payload in (
        ("GET", "", None),
        ("PATCH", "", {}),
        ("DELETE", "", None),
        ("POST", "/restore", {}),
        ("POST", "/view", {}),
    ):
        actual = client.request(method, "/api/contents/" + item["id"] + suffix, json=payload)
        absent = client.request(method, "/api/contents/absent" + suffix, json=payload)
        error(actual, 404, "NOT_FOUND")
        assert (actual.status_code, actual.content) == (absent.status_code, absent.content)
    error(client.post(f"/api/notices/{notice['id']}/read", json={}), 404, "NOT_FOUND")
    state = client.get("/api/state").json()
    assert state["contents"] == state["notices"] == state["searchHistory"] == []
    assert state["savedCount"] == 0
    create(client)  # Same URL is permitted for a different user.
    client.delete("/api/trash")
    client.post("/api/notices/read", json={})
    client.delete("/api/search-history")
    client.delete("/api/me")
    client.headers["Authorization"] = "Bearer " + first["token"]
    assert client.get("/api/contents/" + item["id"]).status_code == 200
    assert not client.get("/api/notices").json()["items"][0]["read"]
    assert client.get("/api/search-history").json()["items"] == ["private"]


def test_state_notices_history_and_filter_sort(client: TestClient) -> None:
    register(client)
    one = create(client, "https://one.example/")
    advance(client, timedelta(seconds=1))
    two = create(client, "https://two.example/")
    client.patch("/api/contents/" + one["id"], json={"title": "ALPHA", "collection": "여행", "type": "영상"})
    client.post("/api/contents/" + one["id"] + "/view", json={})
    assert client.get("/api/contents", params={"q": "alpha", "collection": "여행", "type": "영상"}).json()["total"] == 1
    for sort, first in (("newest", two), ("oldest", one), ("recent", one)):
        assert client.get("/api/contents", params={"sort": sort}).json()["items"][0]["id"] == first["id"]
    assert client.get("/api/contents", params={"q": "["}).json()["total"] == 0
    notices = client.get("/api/notices").json()["items"]
    assert len(notices) == 2 and notices[0]["description"] == "two.example"
    assert client.post(f"/api/notices/{notices[0]['id']}/read", json={}).status_code == 204
    assert client.get("/api/notices").json()["items"][0]["read"]
    client.post("/api/notices/read", json={})
    assert all(n["read"] for n in client.get("/api/notices").json()["items"])
    for i in range(12):
        client.post("/api/search-history", json={"query": f"term{i}"})
    history = client.post("/api/search-history", json={"query": "term5"}).json()["items"]
    assert len(history) == len(set(history)) == 10 and history[0] == "term5"
    state = client.get("/api/state").json()
    assert state["searchHistory"] == history and state["savedCount"] == 2
    assert state["notices"] == client.get("/api/notices").json()["items"]
    assert client.delete("/api/search-history").content == b""
    assert client.get("/api/search-history").json() == {"items": []}


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com",
        "javascript:alert(1)",
        "https://u:p@example.com/",
        "https://u@example.com/",
        "https://example.com:bad/",
        "https://",
        "https://example.com/\nsecret",
        "https://example.com\\@evil.com/",
        "https://%65xample.com/",
        "https://[invalid]/",
    ],
)
def test_unsafe_urls(client: TestClient, url: str) -> None:
    register(client)
    error(client.post("/api/contents", json={"url": url}), 400, "VALIDATION_ERROR")
    assert client.get("/api/state").json()["savedCount"] == 0


@pytest.mark.parametrize(
    ("url", "expected", "host"),
    [
        ("https://EXAMPLE.com", "https://example.com/", "example.com"),
        ("http://example.com:80/a#b", "http://example.com/a", "example.com"),
        ("https://example.com:8443/a?x=1#b", "https://example.com:8443/a?x=1", "example.com"),
        ("https://한글.com/길", "https://xn--bj0bj06e.com/%EA%B8%B8", "xn--bj0bj06e.com"),
        ("https://[::1]:443/", "https://[::1]/", "[::1]"),
    ],
)
def test_normalized_urls(client: TestClient, url: str, expected: str, host: str) -> None:
    register(client)
    item = create(client, url)
    assert item["url"] == expected and item["source"] == host


@pytest.mark.parametrize(
    ("path", "body", "code"),
    [
        ("/auth/register", {"email": "bad"}, "VALIDATION_ERROR"),
        ("/auth/register", {"email": "a@b.com", "password": "short"}, "INVALID_PASSWORD"),
        (
            "/auth/register",
            {"email": "a@b.com", "password": "Password1!", "nickname": "n", "requiredConsent": 1},
            "VALIDATION_ERROR",
        ),
        (
            "/auth/register",
            {
                "email": "a@b.com",
                "password": "Password1!",
                "nickname": "n",
                "requiredConsent": True,
                "notificationsEnabled": "false",
            },
            "VALIDATION_ERROR",
        ),
        ("/auth/login", {"email": "a@b.com", "password": ""}, "VALIDATION_ERROR"),
        ("/contents", {"url": "https://example.com/", "memo": "x" * 71}, "VALIDATION_ERROR"),
        ("/contents", {"url": "https://example.com/", "memo": None}, "VALIDATION_ERROR"),
        ("/search-history", {"query": ""}, "VALIDATION_ERROR"),
        ("/search-history", {"query": "x" * 201}, "VALIDATION_ERROR"),
        ("/me/password/verify", {"currentPassword": 123}, "VALIDATION_ERROR"),
    ],
)
def test_field_validation(client: TestClient, path: str, body: dict[str, Any], code: str) -> None:
    register(client)
    error(client.post("/api" + path, json=body), 400, code)


@pytest.mark.parametrize(
    "patch",
    [
        {"title": ""},
        {"title": "x" * 201},
        {"memo": False},
        {"memo": "x" * 71},
        {"type": "video"},
        {"collection": "invalid"},
        {"type": None},
    ],
)
def test_patch_validation(client: TestClient, patch: dict[str, Any]) -> None:
    register(client)
    item = create(client)
    path = "/api/contents/" + item["id"]
    error(client.patch(path, json=patch), 400, "VALIDATION_ERROR")
    assert client.get(path).json() == item


@pytest.mark.parametrize("params", [{"type": "wrong"}, {"collection": "wrong"}, {"deleted": "1"}, {"sort": "wrong"}])
def test_query_validation(client: TestClient, params: dict[str, str]) -> None:
    register(client)
    error(client.get("/api/contents", params=params), 400, "VALIDATION_ERROR")


@pytest.mark.parametrize(
    ("body", "status", "code"),
    [
        (b"", 400, "INVALID_JSON"),
        (b"{", 400, "INVALID_JSON"),
        (b"null", 400, "VALIDATION_ERROR"),
        (b"[]", 400, "VALIDATION_ERROR"),
        (b"true", 400, "VALIDATION_ERROR"),
        (b'{"x":NaN}', 400, "INVALID_JSON"),
        (b'{"x":"\xff"}', 400, "INVALID_JSON"),
        (b'{"x":"' + b"a" * 16384 + b'"}', 413, "PAYLOAD_TOO_LARGE"),
    ],
)
def test_json_validation(client: TestClient, body: bytes, status: int, code: str) -> None:
    error(client.post("/api/auth/logout", content=body, headers={"Content-Type": "application/json"}), status, code)


def test_json_size_boundary_chunked_and_content_type(client: TestClient) -> None:
    register(client)
    error(client.post("/api/auth/logout", content="{}"), 415, "UNSUPPORTED_MEDIA_TYPE")
    body = b'{"ignored":"' + b"x" * (16384 - 14) + b'"}'
    assert len(body) == 16384
    assert (
        client.post(
            "/api/notices/read", content=body, headers={"Content-Type": "application/json; charset=utf-8"}
        ).status_code
        == 204
    )
    error(
        client.post("/api/notices/read", content=iter([body, b" "]), headers={"Content-Type": "application/json"}),
        413,
        "PAYLOAD_TOO_LARGE",
    )
    for authorization in ("", "Basic abc", "Bearer x", "Bearer " + "a" * 64, "Bearer a b"):
        error(client.get("/api/me", headers={"Authorization": authorization, "X-User-Id": "user"}), 401, "UNAUTHORIZED")


def test_cors_allowlist_and_preflight(client: TestClient) -> None:
    error(client.get("/api/health", headers={"Origin": "https://evil.example"}), 403, "ORIGIN_FORBIDDEN")
    response = client.get("/api/health", headers={"Origin": "https://app.example"})
    assert response.json() == {"status": "ok"}
    assert response.headers["Access-Control-Allow-Origin"] == "https://app.example"
    response = client.get("/api/me", headers={"Origin": "https://app.example"})
    error(response, 401, "UNAUTHORIZED")
    assert response.headers["Access-Control-Allow-Origin"] == "https://app.example"
    preflight = client.options(
        "/api/contents",
        headers={
            "Origin": "https://app.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Authorization, Content-Type",
        },
    )
    assert preflight.status_code == 204 and not preflight.content
    error(
        client.options(
            "/api/contents", headers={"Origin": "https://app.example", "Access-Control-Request-Headers": "X-User-Id"}
        ),
        403,
        "ORIGIN_FORBIDDEN",
    )
    error(client.get("/api/does-not-exist"), 404, "NOT_FOUND")


def test_rate_limit_shared_across_auth_password_and_restart(client: TestClient) -> None:
    register(client)  # request 1
    for _i in range(29):
        error(client.post("/api/auth/login", json={}), 400, "VALIDATION_ERROR")
    error(client.post("/api/me/password/verify", json={"currentPassword": "Password1!"}), 429, "RATE_LIMITED")
    error(client.post("/api/auth/login", json={}, headers={"X-Forwarded-For": "1.2.3.4"}), 429, "RATE_LIMITED")
    assert client.get("/api/health").status_code == 200
    with TestClient(create_api(db(client))) as restarted:
        restarted.app.state.clock = lambda: NOW  # type: ignore[union-attr]
        error(restarted.post("/auth/login", json={}), 429, "RATE_LIMITED")
    advance(client, timedelta(seconds=60))
    assert client.post("/api/me/password/verify", json={"currentPassword": "Password1!"}).status_code == 204
    with TestClient(create_api(db(client)), client=("another-ip", 123)) as other:
        error(other.post("/auth/login", json={}), 400, "VALIDATION_ERROR")


def test_atomic_notices_on_insert_failure(client: TestClient) -> None:
    register(client)
    with db(client).begin() as conn:
        conn.exec_driver_sql(
            "CREATE TRIGGER reject_notice BEFORE INSERT ON api_notices "
            "BEGIN SELECT RAISE(ABORT,'private database error'); END"
        )
    response = client.post("/api/contents", json={"url": "https://example.com"})
    error(response, 500, "INTERNAL_ERROR")
    assert "private database" not in response.text
    assert client.get("/api/state").json()["contents"] == []


def test_additive_migration_idempotence_and_checksum(client: TestClient) -> None:
    register(client)
    create(client)
    run_migrations(db(client), auto_migrate=False)
    with db(client).begin() as conn:
        assert conn.exec_driver_sql("SELECT count(*) FROM api_contents").scalar_one() == 1
        assert conn.exec_driver_sql("SELECT max(version) FROM schema_migrations").scalar_one() == 29
        conn.exec_driver_sql("UPDATE app_api_migrations SET checksum='modified'")
    with pytest.raises(MigrationError, match="checksum"):
        run_migrations(db(client))


def test_all_contract_operations_status_and_response_schema(client: TestClient) -> None:
    operations = {
        (m.upper(), p, op["operationId"]): op for p, methods in SPEC["paths"].items() for m, op in methods.items()
    }
    assert {(m, p, op) for m, p, op, _ in OPERATIONS} == set(operations)
    assert len(operations) == 24
    session = register(client)
    item = create(client)
    notice = client.get("/api/notices").json()["items"][0]
    # Exercise and validate every operation; destructive operations go last.
    order = sorted(OPERATIONS, key=lambda item: {"deleteMe": 10, "logout": 9, "deleteContent": 7}.get(item[2], 0))
    for method, path, op, status in order:
        path_id = notice["id"] if op == "readNotice" else item["id"]
        actual_path = "/api" + path.replace("{id}", path_id)
        bodies = {
            "register": {
                "email": "schema@example.com",
                "nickname": "n",
                "password": "Password1!",
                "requiredConsent": True,
            },
            "login": {"email": "user@example.com", "password": "Password1!"},
            "updateMe": {"nickname": "new"},
            "verifyPassword": {"currentPassword": "Password1!"},
            "changePassword": {"currentPassword": "Password1!", "newPassword": "Changed1!"},
            "createContent": {"url": "https://schema.example/"},
            "addSearchHistory": {"query": "여행"},
        }
        if op == "deleteMe":
            fresh = client.post("/api/auth/login", json={"email": "user@example.com", "password": "Changed1!"}).json()
            client.headers["Authorization"] = "Bearer " + fresh["token"]
        response = client.request(method, actual_path, json=bodies.get(op, {}) if method in ("POST", "PATCH") else None)
        assert response.status_code == status, (op, response.text)
        schema = (
            operations[(method, path, op)]["responses"][str(status)]
            .get("content", {})
            .get("application/json", {})
            .get("schema")
        )
        if schema:
            validator = Draft202012Validator(SPEC, format_checker=FormatChecker()).evolve(schema=schema)
            validator.validate(response.json())
        else:
            assert response.content == b""
    assert session["user"]["nickname"] == "사용자"


def test_concurrent_duplicate_is_atomic(client: TestClient) -> None:
    register(client)

    def submit(index: int) -> int:
        return client.post("/api/contents", json={"url": "https://same.example/#" + str(index)}).status_code

    with ThreadPoolExecutor(max_workers=4) as pool:
        statuses = list(pool.map(submit, range(8)))
    assert sorted(statuses) == [201] + [409] * 7
    assert len(client.get("/api/state").json()["notices"]) == 1
    assert client.get("/api/state").json()["savedCount"] == 1


def test_credentials_use_independent_salts(client: TestClient) -> None:
    register(client)
    register(client, "other@example.com")
    with db(client).connect() as conn:
        rows = conn.exec_driver_sql("SELECT password_hash,password_salt FROM api_users").all()
        assert rows[0][0] != rows[1][0] and rows[0][1] != rows[1][1]


def test_mount_with_existing_app(container_factory: Callable[..., AppContainer]) -> None:
    container = container_factory()
    with TestClient(create_app(container=container)) as combined:
        assert combined.get("/api/health").json() == {"status": "ok"}
        register(combined)
        create(combined)
        assert combined.get("/healthz").status_code == 200
        result = combined.post("/v1/search", headers={"X-User-Id": "u_legacy"}, json={"query": "카페"})
        assert result.status_code == 200
        assert combined.get("/api/state").json()["savedCount"] == 1
    container.engine.dispose()


def test_text_lengths_and_preservation_follow_schema(client: TestClient) -> None:
    register(client)
    item = client.post("/api/contents", json={"url": "https://example.com", "memo": "  memo  "}).json()
    assert item["memo"] == "  memo  "
    assert client.patch("/api/me", json={"nickname": " n "}).json()["nickname"] == " n "
    error(client.patch("/api/me", json={"nickname": "n" * 25 + " "}), 400, "VALIDATION_ERROR")
    assert client.post("/api/search-history", json={"query": " term "}).json()["items"] == [" term "]

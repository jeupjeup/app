from __future__ import annotations

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from jupjup.api.app import create_app
from jupjup.auth import DevHeaderAuthenticator
from jupjup.config import Settings
from jupjup.container import build_container
from jupjup.storage.db import create_db_engine


def _request(headers: list[tuple[bytes, bytes]]) -> Request:
    return Request({"type": "http", "method": "GET", "path": "/", "headers": headers})


def test_dev_header_authenticator_returns_principal_and_preserves_errors() -> None:
    auth = DevHeaderAuthenticator()
    principal = auth.authenticate(_request([(b"x-user-id", b"u_alice")]))
    assert principal.user_id == "u_alice"
    assert principal.auth_kind == "dev_header"

    with pytest.raises(Exception) as missing:
        auth.authenticate(_request([]))
    assert missing.value.code == "UNAUTHORIZED"


def test_prod_rejects_dev_header_auth_at_startup() -> None:
    settings = Settings(env="prod", auth_backend="dev_header", db_path=":memory:")
    with pytest.raises(ValueError, match="dev_header"):
        create_app(settings)


def test_admin_routes_are_not_registered_outside_dev() -> None:
    settings = Settings(env="test", db_path=":memory:")
    container = build_container(settings, engine=create_db_engine(None))
    with TestClient(create_app(container=container)) as client:
        response = client.post(
            "/v1/admin/contents:bulkUpsert",
            headers={"X-User-Id": "u_alice"},
            json={"items": []},
        )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"

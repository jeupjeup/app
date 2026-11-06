from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.exc import SQLAlchemyError

from jupjup.api.app import create_app
from jupjup.config import Settings
from jupjup.container import build_container, build_ingest_service


def setup_app(path: Path | str):
    container = build_container(Settings(env="test", auth_backend="app_session", db_path=path))
    ingest = build_ingest_service(container)
    return container, ingest, create_app(container=container, ingest=ingest)


def register(client):
    result = client.post(
        "/api/auth/register",
        json={"email": "a@example.com", "password": "Password123!", "nickname": "A", "requiredConsent": True},
    )
    assert result.status_code == 201, result.text
    return {"Authorization": "Bearer " + result.json()["token"]}


def test_create_atomic_and_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    container, ingest, app = setup_app(tmp_path / "bridge.db")
    with TestClient(app, raise_server_exceptions=False) as client:
        headers = register(client)
        result = client.post("/api/contents", headers=headers, json={"url": "https://example.com/path", "memo": "memo"})
        assert result.status_code == 201, result.text
        assert result.json()["status"] == "analyzing"
        with container.engine.connect() as conn:
            assert conn.exec_driver_sql("SELECT user_note FROM contents").scalar_one() == "memo"
            assert conn.exec_driver_sql("SELECT count(*) FROM ingest_jobs").scalar_one() == 1
        rejected = client.post("/api/contents", headers=headers, json={"url": "https://instagram.com/private"})
        assert rejected.status_code == 201, rejected.text
        assert rejected.json()["status"] == "failed"
        with container.engine.connect() as conn:
            assert conn.exec_driver_sql("SELECT count(*) FROM contents").scalar_one() == 1
            assert conn.exec_driver_sql("SELECT count(*) FROM content_fingerprints").scalar_one() == 1

        def fail(*args, **kwargs):
            raise SQLAlchemyError("injected")

        monkeypatch.setattr(ingest.queue, "enqueue_in_transaction", fail)
        failed = client.post("/api/contents", headers=headers, json={"url": "https://example.com/fail"})
        assert failed.status_code == 500
        with container.engine.connect() as conn:
            assert conn.exec_driver_sql("SELECT count(*) FROM contents").scalar_one() == 1
            assert conn.exec_driver_sql("SELECT count(*) FROM api_contents").scalar_one() == 2
            assert conn.exec_driver_sql("SELECT count(*) FROM api_notices").scalar_one() == 2


@pytest.mark.parametrize("memory", [False, True])
def test_no_nested_connections(tmp_path: Path, memory: bool):
    container, _, app = setup_app(":memory:" if memory else tmp_path / "bridge.db")
    with TestClient(app) as client:
        headers = register(client)
        checkouts = []

        def checkout(*args):
            checkouts.append(1)

        event.listen(container.engine, "checkout", checkout)
        result = client.post("/api/contents", headers=headers, json={"url": "https://example.com/one"})
        assert result.status_code == 201, result.text
        assert len(checkouts) == 2
        checkouts.clear()
        item_id = result.json()["id"]
        assert client.delete(f"/api/contents/{item_id}", headers=headers).status_code == 204
        assert len(checkouts) == 2
        checkouts.clear()
        assert client.delete("/api/trash", headers=headers).status_code == 204
        assert len(checkouts) == 2
        event.remove(container.engine, "checkout", checkout)
        with container.engine.connect() as conn:
            assert conn.exec_driver_sql("SELECT count(*) FROM contents").scalar_one() == 0


def test_duplicates_trash_backfill_and_disabled(tmp_path: Path):
    container, _, app = setup_app(tmp_path / "bridge.db")
    with TestClient(app, raise_server_exceptions=False) as client:
        headers = register(client)
        first = client.post("/api/contents", headers=headers, json={"url": "https://example.com/one?utm_source=a"})
        assert first.status_code == 201, first.text
        assert client.post("/api/contents", headers=headers, json={"url": "https://example.com/one"}).status_code == 409
        item = first.json()["id"]
        assert client.delete(f"/api/contents/{item}", headers=headers).status_code == 204
        second = client.post("/api/contents", headers=headers, json={"url": "https://example.com/one"})
        assert second.status_code == 201, second.text
        assert client.post(f"/api/contents/{item}/restore", headers=headers, json={}).status_code == 409
        state = client.get("/api/state", headers=headers)
        assert state.status_code == 200, state.text
        assert len(state.json()["contents"]) == 2
        assert client.delete("/api/trash", headers=headers).status_code == 204
        with container.engine.connect() as conn:
            assert conn.exec_driver_sql("SELECT count(*) FROM contents").scalar_one() == 1
        web = client.post(
            "/v1/contents",
            headers={**headers, "Idempotency-Key": "web"},
            json={"source": {"kind": "url", "url": "https://example.com/web"}},
        )
        assert web.status_code == 202, web.text
        state = client.get("/api/state", headers=headers)
        assert state.status_code == 200, state.text
        assert len(state.json()["contents"]) == 2
        assert len(client.get("/api/state", headers=headers).json()["contents"]) == 2


def test_core_rejection_rolls_back_savepoint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from jupjup.bridge.ports import CoreRejected
    from jupjup.save.service import ContentCommandService

    container, _, app = setup_app(tmp_path / "bridge.db")
    original = ContentCommandService.create_in_transaction

    def reject_after_write(self, conn, user_id, body, now):
        original(self, conn, user_id, body, now)
        raise CoreRejected("core_rejected_url")

    monkeypatch.setattr(ContentCommandService, "create_in_transaction", reject_after_write)
    with TestClient(app) as client:
        headers = register(client)
        result = client.post("/api/contents", headers=headers, json={"url": "https://example.com/rejected"})
        assert result.status_code == 201
        assert result.json()["status"] == "failed"
        with container.engine.connect() as conn:
            for table in ("contents", "ingest_jobs", "content_fingerprints"):
                assert conn.exec_driver_sql(f"SELECT count(*) FROM {table}").scalar_one() == 0

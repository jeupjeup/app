"""Real session security boundary; no trusted development dependency overrides."""

import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from jupjup.api.app import create_app
from jupjup.config import Settings
from jupjup.container import build_container, build_ingest_service
from jupjup.domain.models import Content, ContentBundle
from jupjup.ingest.fetch import FetcherRouter, HttpResponse, HttpSourceFetcher
from jupjup.storage.account_migration import run_migrations
from jupjup.storage.migration import MigrationError


def register(client: TestClient, name: str) -> dict[str, str]:
    result = client.post(
        "/api/auth/register",
        json={
            "email": f"{name}@example.com",
            "password": "Password123!",
            "nickname": name,
            "requiredConsent": True,
        },
    )
    assert result.status_code == 201, result.text
    return {"Authorization": "Bearer " + result.json()["token"], "Idempotency-Key": "same-key"}


def test_account_content_collection_job_boundary_and_worker(tmp_path: Path) -> None:
    c = build_container(Settings(env="dev", mode="mock", db_path=tmp_path / "accounts.db", embedded_worker=True))
    service = build_ingest_service(c)
    service.worker.stages["fetch"].__self__.fetcher = FetcherRouter(
        [
            HttpSourceFetcher(
                resolver=lambda _: ["93.184.216.34"],
                transport=lambda *_: HttpResponse(
                    200,
                    {"content-type": "text/html; charset=utf-8"},
                    (
                        "<html><title>은하수 연구</title><article>"
                        "은하수 관찰 연구 기록과 별자리 여행 안내입니다.</article></html>"
                    ).encode(),
                ),
            )
        ]
    )
    # Legacy data remains in its original namespace across the additive migration.
    with c.engine.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO collections VALUES ('col_demo','u_frontend_dev','Demo','demo','#DDB8E5','x','x')"
        )
    now = datetime.now(UTC)
    c.repo.upsert(
        ContentBundle(
            content=Content(
                id="c_demo",
                user_id="u_frontend_dev",
                platform="web",
                content_type="webpage",
                saved_at=now,
                created_at=now,
                updated_at=now,
                title="Legacy demo",
            )
        )
    )
    run_migrations(c.engine)
    with TestClient(create_app(container=c, ingest=service)) as client:
        a, b = register(client, "alice"), register(client, "bob")
        body = {"source": {"kind": "url", "url": "https://example.com/account"}, "automation_level": "auto"}
        for headers in ({}, {"X-User-Id": "u_frontend_dev"}):
            assert client.post("/v1/contents", headers=headers, json=body).status_code == 401
            assert client.post("/v1/collections", headers=headers, json={"name": "Denied"}).status_code == 401
        demo = client.get("/v1/collections", headers={"X-User-Id": "u_frontend_dev"})
        assert demo.json()["items"][0]["id"] == "col_demo"
        assert client.get("/v1/collections", headers=a).json()["items"] == []
        assert client.get("/v1/contents", headers=a).json()["items"] == []
        assert client.get("/v1/contents/c_demo", headers={"X-User-Id": "u_frontend_dev"}).status_code == 200
        assert client.get("/v1/contents/c_demo", headers=a).status_code == 404
        assert client.post("/v1/admin/ingest", headers={"X-User-Id": "u_frontend_dev"}, json=body).status_code == 401
        assert (
            client.get(
                "/v1/contents", headers={**a, "Authorization": "Bearer invalid", "X-User-Id": "u_frontend_dev"}
            ).status_code
            == 401
        )
        saved = client.post("/v1/contents", headers={**a, "X-User-Id": "u_frontend_dev"}, json=body)
        assert saved.status_code == 202, saved.text
        cid, jid = saved.json()["content_id"], saved.json()["job_id"]
        for _ in range(100):
            job = client.get(f"/v1/jobs/{jid}", headers=a)
            if job.json()["status"] in {"succeeded", "failed"}:
                break
            time.sleep(0.05)
        assert job.json()["status"] == "succeeded", job.text
        assert client.get(f"/v1/contents/{cid}", headers=a).json()["status"] == "ready"
        assert client.get("/v1/contents", headers=b).json()["items"] == []
        assert client.post("/v1/search", headers=b, json={"query": "은하수"}).json()["results"] == []
        results = client.post("/v1/search", headers=a, json={"query": "은하수"}).json()["results"]
        assert cid in [row["content_id"] for row in results]
        collection = client.post("/v1/collections", headers=a, json={"name": "Private"}).json()["id"]
        assert client.put(f"/v1/collections/{collection}/contents/{cid}", headers=a).status_code == 204
        for method, url, payload in [
            ("GET", f"/v1/contents/{cid}", None),
            ("PATCH", f"/v1/contents/{cid}", {"summary": "intrusion"}),
            ("DELETE", f"/v1/contents/{cid}", None),
            ("GET", f"/v1/jobs/{jid}?trace=full", None),
            ("POST", f"/v1/contents/{cid}:reanalyze", {}),
            ("GET", f"/v1/collections/{collection}", None),
            ("PATCH", f"/v1/collections/{collection}", {"name": "intrusion"}),
            ("DELETE", f"/v1/collections/{collection}", None),
            ("PUT", f"/v1/collections/{collection}/contents/{cid}", None),
        ]:
            assert client.request(method, url, headers=b, json=payload).status_code == 404, url
        etag = client.get(f"/v1/contents/{cid}", headers=a).headers["etag"]
        assert (
            client.patch(
                f"/v1/contents/{cid}", headers={**a, "If-Match": etag}, json={"summary": "My summary"}
            ).status_code
            == 200
        )
        other = client.post("/v1/contents", headers=b, json=body)
        assert other.status_code == 202 and other.json()["content_id"] != cid
        assert client.post("/v1/contents", headers=a, json=body).headers["Idempotency-Replayed"] == "true"
        with c.engine.connect() as conn:
            scopes = list(conn.exec_driver_sql("SELECT user_id FROM account_scopes").scalars())
            assert len(scopes) == 2
            assert (
                conn.exec_driver_sql("SELECT user_id FROM collections WHERE id='col_demo'").scalar_one()
                == "u_frontend_dev"
            )
            assert not conn.exec_driver_sql("PRAGMA foreign_key_check").all()
        assert client.get("/v1/contents", headers={"X-User-Id": scopes[0]}).status_code == 401
        assert client.delete(f"/v1/contents/{cid}", headers=a).status_code == 204
        assert client.get(f"/v1/contents/{cid}", headers=a).status_code == 404
        assert client.delete("/api/me", headers=b).status_code == 204
        assert client.get("/v1/contents", headers=b).status_code == 401
        with c.engine.connect() as conn:
            assert conn.exec_driver_sql("SELECT count(*) FROM account_scopes").scalar_one() == 1
            assert (
                conn.exec_driver_sql(
                    "SELECT count(*) FROM contents WHERE id=?", (other.json()["content_id"],)
                ).scalar_one()
                == 0
            )
            assert conn.exec_driver_sql("SELECT count(*) FROM contents WHERE id='c_demo'").scalar_one() == 1
        assert client.post("/api/auth/logout", headers=a, json={}).status_code == 204
        assert client.get(f"/v1/contents/{cid}", headers=a).status_code == 401
    c.engine.dispose()


def test_account_migration_preserves_existing_users_and_requires_opt_in(container_factory: Any) -> None:
    c = container_factory()
    with c.engine.begin() as conn:
        conn.exec_driver_sql("DROP TRIGGER account_scope_on_register")
        conn.exec_driver_sql("DROP TABLE account_scopes")
    with TestClient(create_app(container=c)) as client:
        # Registration works before migration as on the previous PM database.
        register(client, "legacy")
    with pytest.raises(MigrationError):
        run_migrations(c.engine, auto_migrate=False)
    run_migrations(c.engine)
    run_migrations(c.engine, auto_migrate=False)
    with c.engine.connect() as conn:
        assert conn.exec_driver_sql("SELECT count(*) FROM account_scopes").scalar_one() == 1

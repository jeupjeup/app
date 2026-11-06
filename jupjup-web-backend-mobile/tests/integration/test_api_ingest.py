"""T23 dev ingest API: 202 submit, job status, user isolation, dev gate, input boundaries."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from jupjup.api.dto import MAX_INGEST_TEXT_CHARS
from jupjup.config import Settings
from jupjup.container import AppContainer, build_container, build_ingest_service
from jupjup.ingest.service import IngestService
from jupjup.storage.db import create_db_engine
from tests.conftest import DATA
from tests.legacy_api import create_app

FIXTURES = Path(__file__).parents[1] / "fixtures" / "ingest"
ALICE = {"X-User-Id": "u_alice"}
BOB = {"X-User-Id": "u_bob"}
NOW = datetime(2026, 10, 20, 10, 0, tzinfo=UTC)
TEXT_BODY = {"source": {"kind": "text", "text": "은하수조약돌 관찰 기록입니다. 보관 방법을 정리했어요."}}


def _container(env: str = "dev", fixtures: Path | None = FIXTURES) -> AppContainer:
    settings = Settings(
        env=env,  # type: ignore[arg-type]
        mode="mock",
        data_dir=DATA,
        db_path=":memory:",
        ingest_fixtures_dir=fixtures,
    )
    return build_container(settings, engine=create_db_engine(None))


@pytest.fixture
def system() -> Iterator[tuple[TestClient, IngestService, AppContainer]]:
    container = _container()
    service = build_ingest_service(container, clock=lambda: NOW, worker_id="api-test")
    with TestClient(create_app(container=container, ingest=service), raise_server_exceptions=False) as client:
        yield client, service, container


def _code(response: Any) -> str:
    return str(response.json()["error"]["code"])


def test_submit_returns_202_and_job_status_tracks_pipeline(
    system: tuple[TestClient, IngestService, AppContainer],
) -> None:
    client, service, container = system
    response = client.post("/v1/admin/ingest", headers=ALICE, json={**TEXT_BODY, "user_note": "주말에 읽기"})
    assert response.status_code == 202, response.text
    assert response.headers["content-type"] == "application/json; charset=utf-8"
    data = response.json()
    assert set(data) == {"content_id", "job_id", "status"}
    assert data["status"] == "queued"
    assert data["content_id"].startswith("c_") and data["job_id"].startswith("job_")

    status = client.get(f"/v1/admin/ingest/jobs/{data['job_id']}", headers=ALICE)
    assert status.status_code == 200, status.text
    body = status.json()
    assert set(body) == {"job_id", "content_id", "status", "stage", "attempts", "last_error", "updated_at"}
    assert body["job_id"] == data["job_id"] and body["content_id"] == data["content_id"]
    assert (body["status"], body["stage"], body["attempts"], body["last_error"]) == ("queued", "fetch", 0, None)
    assert datetime.fromisoformat(body["updated_at"]) == NOW

    bundle = container.repo.get_bundle("u_alice", data["content_id"])
    assert bundle.content.status == "pending" and bundle.content.user_note == "주말에 읽기"
    assert bundle.content.platform == "local" and bundle.content.saved_at == NOW

    service.run_inline(data["job_id"])
    done = client.get(f"/v1/admin/ingest/jobs/{data['job_id']}", headers=ALICE).json()
    assert (done["status"], done["stage"], done["attempts"], done["last_error"]) == ("succeeded", "index", 1, None)
    result = client.post("/v1/search", headers=ALICE, json={"query": "은하수조약돌"})
    assert [item["content_id"] for item in result.json()["results"]] == [data["content_id"]]


def test_submit_html_fixture_with_hints_and_saved_at(system: tuple[TestClient, IngestService, AppContainer]) -> None:
    client, service, container = system
    payload = {
        "source": {"kind": "url", "url": "https://example.com/article", "fixture": "html/article.html"},
        "platform_hint": "news",
        "title": "독립 서점 소식",
        "saved_at": "2026-10-20T19:00:00+09:00",
    }
    response = client.post("/v1/admin/ingest", headers=ALICE, json=payload)
    assert response.status_code == 202, response.text
    job = service.run_inline(response.json()["job_id"])
    assert job.status == "succeeded"
    bundle = container.repo.get_bundle("u_alice", response.json()["content_id"])
    assert bundle.content.platform == "news" and bundle.content.content_type == "article"
    assert bundle.content.title == "독립 서점 소식"
    assert bundle.content.source_url == "https://example.com/article"
    assert bundle.content.saved_at == datetime.fromisoformat("2026-10-20T19:00:00+09:00")
    assert bundle.summary is not None and bundle.content.status == "ready"


def test_failed_job_status_exposes_code_only(system: tuple[TestClient, IngestService, AppContainer]) -> None:
    client, service, _ = system
    response = client.post(
        "/v1/admin/ingest", headers=ALICE, json={"source": {"kind": "url", "fixture": "html/missing.html"}}
    )
    assert response.status_code == 202
    service.run_inline(response.json()["job_id"])
    body = client.get(f"/v1/admin/ingest/jobs/{response.json()['job_id']}", headers=ALICE).json()
    assert body["status"] == "failed" and body["stage"] == "fetch"
    assert body["last_error"]["code"] == "INGEST_UNSUPPORTED"
    assert "missing.html" not in str(body["last_error"])


def test_other_users_job_is_404_like_unknown_job(system: tuple[TestClient, IngestService, AppContainer]) -> None:
    client, _, _ = system
    job_id = client.post("/v1/admin/ingest", headers=ALICE, json=TEXT_BODY).json()["job_id"]
    other = client.get(f"/v1/admin/ingest/jobs/{job_id}", headers=BOB)
    unknown = client.get(f"/v1/admin/ingest/jobs/job_{'0' * 32}", headers=ALICE)
    malformed = client.get("/v1/admin/ingest/jobs/not-a-job", headers=ALICE)
    for response in (other, unknown, malformed):
        assert response.status_code == 404, response.text
        assert _code(response) == "NOT_FOUND"
    assert other.json()["error"]["message"] == unknown.json()["error"]["message"]
    assert client.get(f"/v1/admin/ingest/jobs/{job_id}", headers=ALICE).status_code == 200


@pytest.mark.parametrize("env", ["test"])
def test_ingest_routes_are_404_outside_dev(env: str) -> None:
    with TestClient(create_app(container=_container(env)), raise_server_exceptions=False) as client:
        submit = client.post("/v1/admin/ingest", headers=ALICE, json=TEXT_BODY)
        status = client.get(f"/v1/admin/ingest/jobs/job_{'0' * 32}", headers=ALICE)
        for response in (submit, status):
            assert response.status_code == 404
            assert _code(response) == "NOT_FOUND"
        assert "/v1/contents" in client.app.openapi()["paths"]  # public API remains available


def test_user_header_is_required(system: tuple[TestClient, IngestService, AppContainer]) -> None:
    client, _, _ = system
    assert _code(client.post("/v1/admin/ingest", json=TEXT_BODY)) == "UNAUTHORIZED"
    response = client.post("/v1/admin/ingest", headers={"X-User-Id": "alice"}, json=TEXT_BODY)
    assert response.status_code == 400 and _code(response) == "INVALID_USER"
    assert _code(client.get(f"/v1/admin/ingest/jobs/job_{'0' * 32}")) == "UNAUTHORIZED"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"source": {"kind": "text"}},
        {"source": {"kind": "text", "text": "   "}},
        {"source": {"kind": "text", "text": "x" * (MAX_INGEST_TEXT_CHARS + 1)}},
        {"source": {"kind": "text", "text": "본문", "fixture": "html/article.html"}},
        {"source": {"kind": "url", "url": "https://example.com/a"}},
        {"source": {"kind": "url", "fixture": "../secrets.html"}},
        {"source": {"kind": "url", "fixture": "/etc/passwd.html"}},
        {"source": {"kind": "url", "fixture": "html\\article.html"}},
        {"source": {"kind": "url", "fixture": "html/article.html", "url": "file:///etc/passwd"}},
        {"source": {"kind": "url", "fixture": "html/article.html", "url": "https://e.com/" + "a" * 2048}},
        {"source": {"kind": "image"}},
        {"source": {"kind": "image", "ocr_text": "입장권", "image_path": "../x.png"}},
        {"source": {"kind": "youtube", "fixture": "transcript/sample.vtt"}},
        {"source": {"kind": "ftp", "text": "본문"}},
        {**TEXT_BODY, "platform_hint": "myspace"},
        {**TEXT_BODY, "content_type_hint": "podcast"},
        {**TEXT_BODY, "saved_at": "2026-10-20T19:00:00"},
        {**TEXT_BODY, "user_note": "메" * 2001},
        {**TEXT_BODY, "title": "t" * 301},
        {**TEXT_BODY, "unexpected": True},
    ],
)
def test_invalid_ingest_inputs_are_422(
    system: tuple[TestClient, IngestService, AppContainer], payload: dict[str, Any]
) -> None:
    client, service, _ = system
    response = client.post("/v1/admin/ingest", headers=ALICE, json=payload)
    assert response.status_code == 422, response.text
    assert _code(response) == "VALIDATION_ERROR"
    assert service.queue.lease("probe", NOW) is None  # nothing was enqueued


def test_boundary_inputs_are_accepted(system: tuple[TestClient, IngestService, AppContainer]) -> None:
    client, service, _ = system
    accepted = [
        {"source": {"kind": "text", "text": "가" * MAX_INGEST_TEXT_CHARS}},
        {"source": {"kind": "text", "text": "가"}},
        {**TEXT_BODY, "user_note": "메" * 2000, "title": "t" * 300},
        {"source": {"kind": "image", "ocr_text": "청동나침반 전시 입장권", "image_path": "images/ticket.png"}},
        {"source": {"kind": "url", "fixture": "transcript/sample.vtt"}, "platform_hint": "youtube"},
    ]
    for payload in accepted:
        response = client.post("/v1/admin/ingest", headers=ALICE, json=payload)
        assert response.status_code == 202, response.text
        assert service.run_inline(response.json()["job_id"]).status == "succeeded"


def test_missing_fixture_root_still_accepts_and_fails_job_permanently(tmp_path: Path) -> None:
    container = _container(fixtures=tmp_path / "absent")
    service = build_ingest_service(container, clock=lambda: NOW)
    with TestClient(create_app(container=container, ingest=service), raise_server_exceptions=False) as client:
        response = client.post(
            "/v1/admin/ingest", headers=ALICE, json={"source": {"kind": "url", "fixture": "html/article.html"}}
        )
        assert response.status_code == 202
        job = service.run_inline(response.json()["job_id"])
        assert job.status == "failed" and job.last_error is not None
        assert job.last_error["code"] == "INGEST_UNSUPPORTED"


@pytest.mark.parametrize("text", ["1234567890", "010-1234-5678", "2026-10-20", "$$$ 100"])
def test_digits_and_symbols_only_text_succeeds(
    system: tuple[TestClient, IngestService, AppContainer], text: str
) -> None:
    client, service, _ = system
    response = client.post("/v1/admin/ingest", headers=ALICE, json={"source": {"kind": "text", "text": text}})
    assert response.status_code == 202, response.text
    service.run_inline(response.json()["job_id"])
    done = client.get(f"/v1/admin/ingest/jobs/{response.json()['job_id']}", headers=ALICE).json()
    assert (done["status"], done["last_error"]) == ("succeeded", None)

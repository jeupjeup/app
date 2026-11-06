"""T15 FastAPI contract, error mapping, dev gate, and user isolation."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from jupjup.config import Settings
from jupjup.container import AppContainer, build_container
from jupjup.domain.errors import EmbeddingCacheMiss
from jupjup.storage.db import create_db_engine
from tests.conftest import DATA
from tests.legacy_api import create_app

HEADERS = {"X-User-Id": "u_alice"}
NOW = "2026-10-15T12:00:00+09:00"


@pytest.fixture(scope="module")
def api_client(golden_container: AppContainer) -> Iterator[TestClient]:
    with TestClient(create_app(container=golden_container), raise_server_exceptions=False) as client:
        yield client


def _error(response: Any) -> str:
    return str(response.json()["error"]["code"])


def test_search_response_schema_and_parse(api_client: TestClient) -> None:
    response = api_client.post("/v1/search", headers=HEADERS, json={"query": "성수동 카페", "limit": 3})
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/json; charset=utf-8"
    data = response.json()
    assert set(data) == {
        "query_id",
        "query",
        "understanding",
        "results",
        "applied_relaxations",
        "empty_state",
        "degraded",
        "timing_ms",
    }
    assert data["query_id"].startswith("qry_")
    assert data["understanding"]["keywords"] == ["성수동", "카페"]
    assert data["results"] and len(data["results"]) <= 3
    assert "debug" not in data["results"][0]
    assert set(data["results"][0]) == {
        "content_id",
        "rank",
        "score",
        "title",
        "platform",
        "content_type",
        "summary",
        "representative_tags",
        "saved_at",
        "source_url",
        "original_available",
        "relaxed",
        "match_reasons",
    }

    parsed = api_client.post("/v1/query:parse", headers=HEADERS, json={"query": "지난달 인스타에서 본 카페"})
    assert parsed.status_code == 200
    understanding = parsed.json()["understanding"]
    assert understanding["time_range"]["expression"] == "지난달"
    assert understanding["platforms"] == [{"value": "instagram", "strength": "hard", "origin": "query"}]


def test_health(api_client: TestClient) -> None:
    response = api_client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "index_ready": True,
        "embedder": "hashing-v1",
        "mode": "mock",
    }


@pytest.mark.parametrize(
    ("headers", "status", "code"),
    [
        ({}, 401, "UNAUTHORIZED"),
        ({"X-User-Id": "alice"}, 400, "INVALID_USER"),
        ({"X-User-Id": "u_ABC"}, 400, "INVALID_USER"),
    ],
)
def test_user_header_errors(api_client: TestClient, headers: dict[str, str], status: int, code: str) -> None:
    response = api_client.post("/v1/search", headers=headers, json={"query": "카페"})
    assert response.status_code == status
    assert _error(response) == code


@pytest.mark.parametrize("query", ["", "x" * 201, "!!!"])
def test_invalid_query_boundaries(api_client: TestClient, query: str) -> None:
    response = api_client.post("/v1/search", headers=HEADERS, json={"query": query})
    assert response.status_code == 422
    assert _error(response) == "INVALID_QUERY"


@pytest.mark.parametrize(
    "body",
    [
        {"query": "카페", "filters": {"platforms": ["tiktok"]}},
        {
            "query": "카페",
            "filters": {"saved_from": "2026-10-02T00:00:00+09:00", "saved_to": "2026-10-01T00:00:00+09:00"},
        },
        {"query": "카페", "limit": 0},
        {"query": "카페", "limit": 51},
    ],
)
def test_invalid_filter_boundaries(api_client: TestClient, body: dict[str, Any]) -> None:
    response = api_client.post("/v1/search", headers=HEADERS, json=body)
    assert response.status_code == 422
    assert _error(response) == "INVALID_FILTER"


def test_schema_validation_and_now_rejected_outside_dev(api_client: TestClient) -> None:
    missing = api_client.post("/v1/search", headers=HEADERS, json={})
    assert missing.status_code == 422 and _error(missing) == "VALIDATION_ERROR"

    now = api_client.post("/v1/search", headers=HEADERS, json={"query": "카페", "now": NOW})
    assert now.status_code == 422 and _error(now) == "VALIDATION_ERROR"

    parse_now = api_client.post("/v1/query:parse", headers=HEADERS, json={"query": "카페", "now": NOW})
    assert parse_now.status_code == 422 and _error(parse_now) == "VALIDATION_ERROR"


def test_empty_result_is_http_200(container_factory: Callable[..., AppContainer]) -> None:
    with TestClient(create_app(container=container_factory())) as client:
        response = client.post("/v1/search", headers=HEADERS, json={"query": "성수동 카페"})
    assert response.status_code == 200
    assert response.json()["results"] == []
    assert response.json()["empty_state"]["message"] == "다른 표현으로 다시 찾아볼까요?"
    assert response.json()["empty_state"]["reason"] == "no_relevant_match"


def test_admin_is_404_outside_dev(api_client: TestClient) -> None:
    response = api_client.post("/v1/admin/contents:bulkUpsert", headers=HEADERS, json={"items": [], "strict": True})
    assert response.status_code == 404


def test_user_isolation(api_client: TestClient) -> None:
    response = api_client.post("/v1/search", headers={"X-User-Id": "u_bob"}, json={"query": "성수동 카페"})
    assert response.status_code == 200
    assert response.json()["results"]
    assert all(item["content_id"].startswith("c_bob_") for item in response.json()["results"])
    assert all(not item["content_id"].startswith("c_alice_") for item in response.json()["results"])


def test_explain_adds_debug(api_client: TestClient) -> None:
    response = api_client.post("/v1/search", headers=HEADERS, json={"query": "성수동 카페", "explain": True})
    assert response.status_code == 200
    debug = response.json()["results"][0]["debug"]
    assert set(debug) >= {"ranks", "rrf", "features"}


def test_index_not_ready_maps_to_503(api_client: TestClient) -> None:
    api_client.app.state.container.registry.ready = False
    try:
        response = api_client.post("/v1/search", headers=HEADERS, json={"query": "카페"})
    finally:
        api_client.app.state.container.registry.ready = True
    assert response.status_code == 503
    assert _error(response) == "INDEX_NOT_READY"


def test_internal_error_hides_message(
    container_factory: Callable[..., AppContainer], monkeypatch: pytest.MonkeyPatch
) -> None:
    container = container_factory()

    def fail(_: object) -> None:
        raise RuntimeError("secret database password")

    monkeypatch.setattr(container.search, "search", fail)
    with TestClient(create_app(container=container), raise_server_exceptions=False) as client:
        response = client.post("/v1/search", headers=HEADERS, json={"query": "카페"})
    assert response.status_code == 500
    assert _error(response) == "INTERNAL"
    assert "secret" not in response.text and "password" not in response.text


def _dev_container(data_dir: Path) -> AppContainer:
    settings = Settings(env="dev", mode="mock", data_dir=data_dir, db_path=":memory:")
    return build_container(settings, engine=create_db_engine(None))


def _api_item(content_id: str) -> dict[str, Any]:
    return {
        "id": content_id,
        "user_id": "u_alice",
        "platform": "blog",
        "content_type": "article",
        "title": "API로 저장한 성수동 카페",
        "saved_at": NOW,
        "original_status": "available",
        "snapshot": {"text": "성수동의 조용한 카페를 소개합니다."},
        "summary": {"text": "성수동 카페 소개", "source": "ai"},
        "tags": [{"name": "성수동", "source": "ai", "confidence": 0.9}],
    }


def test_dev_admin_bulk_upsert_delete_and_user_match() -> None:
    container = _dev_container(DATA)
    item = _api_item("c_api_1")
    with TestClient(create_app(container=container)) as client:
        mismatch = client.post(
            "/v1/admin/contents:bulkUpsert",
            headers={"X-User-Id": "u_bob"},
            json={"items": [item], "strict": True},
        )
        assert mismatch.status_code == 200
        assert mismatch.json()["upserted"] == 0
        assert mismatch.json()["failed"][0]["code"] == "INVALID_CONTENT"

        inserted = client.post("/v1/admin/contents:bulkUpsert", headers=HEADERS, json={"items": [item], "strict": True})
        assert inserted.status_code == 200, inserted.text
        assert inserted.json() == {"upserted": 1, "failed": [], "embedding_pending": 0}

        found = client.post("/v1/search", headers=HEADERS, json={"query": "성수동 카페", "now": NOW})
        assert found.status_code == 200
        assert found.json()["results"][0]["content_id"] == "c_api_1"

        deleted = client.delete("/v1/admin/contents/c_api_1", headers=HEADERS)
        assert deleted.status_code == 204 and deleted.content == b""
        assert container.repo.count("u_alice") == 0


@pytest.mark.parametrize("strict", [True, False])
def test_bulk_upsert_index_failure_leaves_response_database_and_index_consistent(strict: bool) -> None:
    class MissingEmbedder:
        model_id = "missing-test"
        dim = 384

        def embed(self, texts: object, kind: object) -> object:
            raise EmbeddingCacheMiss("test recording miss")

    container = _dev_container(DATA)
    container.indexer.embedder = MissingEmbedder()  # type: ignore[assignment]
    items = [_api_item("c_api_atomic_1"), _api_item("c_api_atomic_2")]
    with TestClient(create_app(container=container)) as client:
        response = client.post(
            "/v1/admin/contents:bulkUpsert",
            headers=HEADERS,
            json={"items": items, "strict": strict},
        )

    assert response.status_code == 200
    assert response.json()["upserted"] == 0
    assert [failure["code"] for failure in response.json()["failed"]] == [
        "EMBEDDING_CACHE_MISS",
        "EMBEDDING_CACHE_MISS",
    ]
    assert container.repo.count("u_alice") == 0
    assert "u_alice" not in container.registry.users()


def test_unknown_user_reads_do_not_persist_empty_indexes() -> None:
    container = _dev_container(DATA)
    with TestClient(create_app(container=container)) as client:
        before = container.registry.users()
        searched = client.post("/v1/search", headers={"X-User-Id": "u_nobody"}, json={"query": "성수동 카페"})
        parsed = client.post("/v1/query:parse", headers={"X-User-Id": "u_other"}, json={"query": "성수동 카페"})

    assert searched.status_code == 200 and searched.json()["results"] == []
    assert parsed.status_code == 200
    assert container.registry.users() == before


def test_bulk_upsert_rejects_duplicate_ids_without_writes() -> None:
    container = _dev_container(DATA)
    item = _api_item("c_api_duplicate")
    with TestClient(create_app(container=container)) as client:
        response = client.post(
            "/v1/admin/contents:bulkUpsert",
            headers=HEADERS,
            json={"items": [item, item], "strict": True},
        )
    assert response.status_code == 200
    assert response.json()["upserted"] == 0
    assert [failure["code"] for failure in response.json()["failed"]] == [
        "DUPLICATE_CONTENT",
        "DUPLICATE_CONTENT",
    ]
    assert container.repo.count("u_alice") == 0


@pytest.mark.parametrize("field,value", [("limit", "10"), ("limit", True), ("explain", "yes")])
def test_search_body_does_not_coerce_public_scalar_types(field: str, value: object) -> None:
    container = _dev_container(DATA)
    with TestClient(create_app(container=container)) as client:
        response = client.post("/v1/search", headers=HEADERS, json={"query": "카페", field: value})
    assert response.status_code == 422
    assert _error(response) == "VALIDATION_ERROR"


def test_openapi_documents_error_envelope() -> None:
    container = _dev_container(DATA)
    with TestClient(create_app(container=container)) as client:
        operation = client.get("/openapi.json").json()["paths"]["/v1/search"]["post"]
    assert set(operation["responses"]) >= {"200", "400", "422", "500", "503"}
    for status in ("400", "422", "500", "503"):
        content = operation["responses"][status]["content"]
        schema = content["application/json; charset=utf-8"]["schema"]
        assert schema["$ref"].endswith("/ErrorEnvelope")


def test_not_ready_health_and_method_error_are_explicit() -> None:
    container = _dev_container(DATA)
    with TestClient(create_app(container=container)) as client:
        container.registry.ready = False
        health = client.get("/healthz")
        method = client.get("/v1/search", headers=HEADERS)
    assert health.status_code == 503
    assert health.json()["status"] == "starting" and health.json()["index_ready"] is False
    assert method.status_code == 405 and _error(method) == "METHOD_NOT_ALLOWED"

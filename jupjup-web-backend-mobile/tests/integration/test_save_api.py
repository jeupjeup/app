from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from jupjup.container import AppContainer, build_ingest_service
from tests.legacy_api import create_app

NOW = datetime(2026, 11, 3, 1, 0, tzinfo=UTC)


def _client(container: AppContainer) -> TestClient:
    ingest = build_ingest_service(container, clock=lambda: NOW, worker_id="save-api-test")
    return TestClient(create_app(container=container, ingest=ingest))


def _post(client: TestClient, body: dict[str, object], *, user: str = "u_alice", key: str = "key-1"):
    return client.post(
        "/v1/contents",
        headers={"X-User-Id": user, "Idempotency-Key": key},
        json=body,
    )


def test_create_three_sources_and_exact_replay(container_factory: Callable[..., AppContainer]) -> None:
    container = container_factory()
    with _client(container) as client:
        text = _post(
            client,
            {"source": {"kind": "text", "text": "저장 API가 분석할 충분한 길이의 직접 입력 원문입니다."}},
        )
        assert text.status_code == 202
        assert text.headers["location"].endswith(text.json()["content_id"])
        replay = _post(
            client,
            {"source": {"text": "저장 API가 분석할 충분한 길이의 직접 입력 원문입니다.", "kind": "text"}},
        )
        assert replay.status_code == 202
        assert replay.json() == text.json()
        assert replay.headers["Idempotency-Replayed"] == "true"

        image = _post(
            client,
            {
                "source": {
                    "kind": "image",
                    "ocr_text": "이미지에서 추출한 충분한 길이의 OCR 원문입니다.",
                    "image": {"mime_type": "image/jpeg", "sha256": "a" * 64},
                },
                "automation_level": "confirm",
            },
            key="key-image",
        )
        assert image.status_code == 202
        url = _post(
            client,
            {"source": {"kind": "url", "url": "https://Example.com/a?utm_source=share#x"}},
            key="key-url",
        )
        assert url.status_code == 202


def test_tracking_url_dedupes_per_user_only(container_factory: Callable[..., AppContainer]) -> None:
    container = container_factory()
    with _client(container) as client:
        first = _post(
            client,
            {"source": {"kind": "url", "url": "https://example.com/a?utm_source=share"}},
            key="url-1",
        )
        duplicate = _post(
            client,
            {"source": {"kind": "url", "url": "https://EXAMPLE.com:443/a#fragment"}},
            key="url-2",
        )
        other_user = _post(
            client,
            {"source": {"kind": "url", "url": "https://example.com/a"}},
            user="u_bob",
            key="url-1",
        )
    assert first.status_code == 202
    assert duplicate.status_code == 200
    assert duplicate.json()["result_content_id"] == first.json()["content_id"]
    assert other_user.status_code == 202
    assert other_user.json()["content_id"] != first.json()["content_id"]


def test_same_key_different_text_is_409_without_second_content(
    container_factory: Callable[..., AppContainer],
) -> None:
    container = container_factory()
    with _client(container) as client:
        assert _post(client, {"source": {"kind": "text", "text": "첫 번째 private source"}}).status_code == 202
        conflict = _post(client, {"source": {"kind": "text", "text": "두 번째 private source"}})
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    assert container.repo.count("u_alice") == 1


def test_different_sources_same_hash_end_at_one_canonical(container_factory: Callable[..., AppContainer]) -> None:
    container = container_factory()
    with _client(container) as client:
        body = {"source": {"kind": "text", "text": "같은 본문을 여러 번 저장해도 정본은 하나만 남아야 합니다."}}
        first = _post(client, body, key="hash-1").json()
        second = _post(client, body, key="hash-2").json()
        client.app.state.ingest.run_inline(first["job_id"])
        job = client.app.state.ingest.run_inline(second["job_id"])
        assert job.status == "deduplicated"
        assert (
            container.repo.get_bundle("u_alice", second["content_id"]).content.duplicate_of_content_id
            == first["content_id"]
        )


def test_detail_list_cursor_and_isolation(container_factory: Callable[..., AppContainer]) -> None:
    container = container_factory()
    with _client(container) as client:
        ids = [
            _post(client, {"source": {"kind": "text", "text": f"보관함 원문 {i}"}}, key=f"list-{i}").json()[
                "content_id"
            ]
            for i in range(3)
        ]
        headers = {"X-User-Id": "u_alice"}
        detail = client.get(f"/v1/contents/{ids[0]}", headers=headers)
        assert detail.status_code == 200
        assert detail.headers["etag"] == f'"content:{ids[0]}:{detail.json()["revision"]}"'
        assert detail.json()["summary"]["effective"] is None
        assert client.get(f"/v1/contents/{ids[0]}", headers={"X-User-Id": "u_bob"}).status_code == 404
        page = client.get("/v1/contents?limit=2", headers=headers).json()
        assert page["has_more"]
        cursor = page["next_cursor"]
        tail = client.get("/v1/contents", params={"limit": 2, "cursor": cursor}, headers=headers).json()
        assert set(x["id"] for x in page["items"] + tail["items"]) == set(ids)
        for params, user in [
            ({"cursor": cursor, "hidden": "all"}, "u_alice"),
            ({"cursor": cursor}, "u_bob"),
            ({"cursor": cursor + "x"}, "u_alice"),
        ]:
            assert client.get("/v1/contents", params=params, headers={"X-User-Id": user}).status_code == 422


def test_patch_clear_noop_etag_hide_delete(container_factory: Callable[..., AppContainer]) -> None:
    container = container_factory()
    with _client(container) as client:
        result = _post(
            client, {"source": {"kind": "text", "text": "성수동 카페에서 커피와 디저트를 먹었습니다."}}
        ).json()
        client.app.state.ingest.run_inline(result["job_id"])
        url = f"/v1/contents/{result['content_id']}"
        headers = {"X-User-Id": "u_alice"}
        original = client.get(url, headers=headers)
        patched = client.patch(
            url,
            headers={**headers, "If-Match": original.headers["etag"]},
            json={
                "summary": "사용자 요약",
                "representative_tags": ["#성수 동", "성수동"],
                "detail_tags": {"topics": ["직접 수정"]},
                "hidden": True,
            },
        )
        assert patched.status_code == 200
        payload = patched.json()
        assert payload["summary"]["effective"] == "사용자 요약"
        assert payload["representative_tags"]["effective"] == ["성수동"]
        assert payload["hidden"] is True
        noop = client.patch(url, headers=headers, json={"summary": "사용자 요약"})
        assert noop.json()["revision"] == payload["revision"]
        assert (
            client.patch(
                url, headers={**headers, "If-Match": original.headers["etag"]}, json={"hidden": False}
            ).status_code
            == 409
        )
        assert client.get("/v1/contents", headers=headers).json()["items"] == []
        assert len(client.get("/v1/contents?hidden=true", headers=headers).json()["items"]) == 1
        cleared = client.patch(
            url,
            headers=headers,
            json={"summary": None, "representative_tags": None, "detail_tags": None, "hidden": False},
        )
        assert cleared.json()["summary"]["source"] == "ai"
        assert client.delete(url, headers=headers).status_code == 204
        assert client.get(url, headers=headers).status_code == 404
        assert client.get(f"/v1/jobs/{result['job_id']}", headers=headers).status_code == 404


def test_confirm_candidate_approve_reject_trace_and_reanalysis(container_factory: Callable[..., AppContainer]) -> None:
    container = container_factory()
    with _client(container) as client:
        result = _post(
            client,
            {
                "source": {"kind": "text", "text": "성수동 카페의 커피가 맛있어서 저장합니다."},
                "automation_level": "confirm",
            },
        ).json()
        ingest = client.app.state.ingest
        job = ingest.run_inline(result["job_id"])
        assert job.status == "awaiting_confirmation"
        headers = {"X-User-Id": "u_alice"}
        url = f"/v1/contents/{result['content_id']}"
        detail = client.get(url, headers=headers).json()
        assert detail["summary"]["effective"] is None
        from sqlalchemy import select

        from jupjup.storage import tables as T

        with container.engine.connect() as conn:
            run = (
                conn.execute(select(T.analysis_runs).where(T.analysis_runs.c.job_id == result["job_id"]))
                .mappings()
                .one()
            )
            assert run["accepted_at"] is None
        candidate = detail["analysis"]["candidate"]["id"]
        job_url = f"/v1/jobs/{result['job_id']}?trace=full"
        trace = client.get(job_url, headers=headers)
        assert trace.status_code == 200
        assert trace.headers["cache-control"] == "private, no-store"
        assert trace.json()["trace"]["result"]
        assert client.get(job_url, headers={"X-User-Id": "u_bob"}).status_code == 404
        review = {"candidate_id": candidate, "decision": "approve"}
        assert client.post(url + ":review", headers=headers, json=review).status_code == 202
        assert client.post(url + ":review", headers=headers, json=review).status_code == 202
        assert client.post(url + ":review", headers=headers, json={**review, "decision": "reject"}).status_code == 409
        assert ingest.run_inline(result["job_id"]).status == "succeeded"
        assert client.patch(url, headers=headers, json={"summary": "내 요약"}).status_code == 200
        reanalyze = client.post(
            url + ":reanalyze", headers={**headers, "Idempotency-Key": "re-1"}, json={"automation_level": "confirm"}
        )
        assert reanalyze.status_code == 202
        assert ingest.run_inline(reanalyze.json()["job_id"]).status == "awaiting_confirmation"
        detail = client.get(url, headers=headers).json()
        assert detail["summary"]["effective"] == "내 요약"
        assert (
            client.post(
                url + ":review",
                headers=headers,
                json={"candidate_id": detail["analysis"]["candidate"]["id"], "decision": "reject"},
            ).status_code
            == 200
        )
        assert client.get(url, headers=headers).json()["snapshot"] is not None
        assert client.get(url, headers=headers).json()["summary"]["effective"] == "내 요약"


def test_openapi_documents_union_responses_and_errors(container_factory: Callable[..., AppContainer]) -> None:
    with _client(container_factory()) as client:
        schema = client.get("/openapi.json").json()
    create = schema["paths"]["/v1/contents"]["post"]
    assert {"200", "202", "400", "404", "409", "422", "503"} <= set(create["responses"])
    assert next(iter(create["responses"]["202"]["content"].values()))["schema"]
    source = schema["components"]["schemas"]["CreateContent"]["properties"]["source"]
    assert source["discriminator"]["propertyName"] == "kind"


def test_delete_during_analyze_cannot_resurrect_content(container_factory: Callable[..., AppContainer]) -> None:
    import pytest

    from jupjup.domain.errors import NotFoundError

    container = container_factory()
    with _client(container) as client:
        result = _post(client, {"source": {"kind": "text", "text": "삭제 경쟁 검증을 위한 원문입니다."}}).json()
        ingest = client.app.state.ingest
        old = ingest.worker.stages["analyze"]

        def delete_then_analyze(job):
            assert (
                client.delete(f"/v1/contents/{result['content_id']}", headers={"X-User-Id": "u_alice"}).status_code
                == 204
            )
            old(job)

        ingest.worker.stages["analyze"] = delete_then_analyze
        with pytest.raises(NotFoundError):
            ingest.run_inline(result["job_id"])
        assert container.repo.count("u_alice") == 0


def test_create_rejects_contradictory_hints_without_reserving_key(
    container_factory: Callable[..., AppContainer],
) -> None:
    with _client(container_factory()) as client:
        response = _post(
            client,
            {"source": {"kind": "text", "text": "원문"}, "platform_hint": "kakaotalk", "content_type_hint": "article"},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "INVALID_CONTENT"
        valid = _post(client, {"source": {"kind": "text", "text": "원문"}})
        assert valid.status_code == 202

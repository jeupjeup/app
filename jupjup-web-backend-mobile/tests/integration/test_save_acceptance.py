"""Save API preservation, recovery, and security acceptance regressions."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from typer.testing import CliRunner

from jupjup.cli import app
from jupjup.config import Settings
from jupjup.container import AppContainer, build_container, build_ingest_service
from jupjup.domain.errors import AnalysisSchemaError
from jupjup.storage import tables as T
from tests.integration.test_save_api import _client, _post
from tests.legacy_api import create_app

ALICE = {"X-User-Id": "u_alice"}
TEXT = "독립 서점에서 새로운 책을 읽고 기록하는 즐거운 시간을 보냈습니다."


def test_successful_reanalysis_preserves_user_layers_and_snapshot(
    container_factory: Callable[..., AppContainer], monkeypatch: pytest.MonkeyPatch
) -> None:
    c = container_factory()
    with _client(c) as client:
        result = _post(client, {"source": {"kind": "text", "text": TEXT}}).json()
        ingest = client.app.state.ingest
        assert ingest.run_inline(result["job_id"]).status == "succeeded"
        url = f"/v1/contents/{result['content_id']}"
        detail = client.get(url, headers=ALICE).json()
        old_ai = detail["representative_tags"]["ai"]
        assert (
            client.patch(
                url,
                headers=ALICE,
                json={
                    "summary": "사용자 요약",
                    "representative_tags": ["직접태그"],
                    "detail_tags": {"topics": None},
                    "hidden": True,
                },
            ).status_code
            == 200
        )

        def forbidden(*args, **kwargs):
            raise AssertionError("public commands must not use bundle upsert")

        monkeypatch.setattr(c.repo, "upsert_in_transaction", forbidden)
        monkeypatch.setattr(c.repo, "upsert", forbidden)
        submit = client.post(url + ":reanalyze", json={}, headers={**ALICE, "Idempotency-Key": "reanalyze"})
        assert submit.status_code == 202
        assert ingest.run_inline(submit.json()["job_id"]).status == "succeeded"
        saved = client.get(url, headers=ALICE).json()
        assert saved["summary"]["effective"] == "사용자 요약"
        assert saved["representative_tags"]["hidden_ai"] == old_ai
        assert saved["representative_tags"]["effective"] == ["직접태그"]
        assert saved["detail_tags"]["user_patch"] == {"topics": None}
        assert "topics" not in saved["detail_tags"]["effective"]
        assert saved["snapshot"] == detail["snapshot"]
        assert saved["hidden"]


def test_reanalyze_failure_restores_previous_ready_analysis(container_factory: Callable[..., AppContainer]) -> None:
    c = container_factory()
    with _client(c) as client:
        result = _post(client, {"source": {"kind": "text", "text": TEXT}}).json()
        ingest = client.app.state.ingest
        ingest.run_inline(result["job_id"])
        url = f"/v1/contents/{result['content_id']}"
        before = client.get(url, headers=ALICE).json()
        submit = client.post(url + ":reanalyze", json={}, headers={**ALICE, "Idempotency-Key": "failure"}).json()

        def fail(job):
            raise AnalysisSchemaError("private source should not be logged")

        ingest.worker.stages["analyze"] = fail
        assert ingest.run_inline(submit["job_id"]).status == "failed"
        after = client.get(url, headers=ALICE).json()
        assert after["status"] == "ready"
        assert after["summary"] == before["summary"]
        assert after["snapshot"] == before["snapshot"]


def test_concurrent_create_exact_replay_is_atomic(tmp_path: Path) -> None:
    settings = Settings(env="test", db_path=tmp_path / "race.db")
    c = build_container(settings)
    ingest = build_ingest_service(c, clock=lambda: datetime(2026, 11, 3, tzinfo=UTC))
    with TestClient(create_app(container=c, ingest=ingest)) as client:

        def submit(_):
            return _post(client, {"source": {"kind": "text", "text": TEXT}})

        with ThreadPoolExecutor(max_workers=4) as pool:
            responses = list(pool.map(submit, range(4)))
        assert [r.status_code for r in responses] == [202] * 4
        assert len({r.json()["content_id"] for r in responses}) == 1
        assert c.repo.count("u_alice") == 1
        with c.engine.connect() as conn:
            assert len(conn.execute(select(T.ingest_jobs)).all()) == 1


def test_confirm_reject_keeps_snapshot_and_reduced_search(container_factory: Callable[..., AppContainer]) -> None:
    with _client(container_factory()) as client:
        result = _post(
            client,
            {
                "source": {"kind": "text", "text": "은하수조약돌 보관 방법입니다. 영구 저장할 원문입니다."},
                "automation_level": "confirm",
            },
        ).json()
        ingest = client.app.state.ingest
        ingest.run_inline(result["job_id"])
        url = f"/v1/contents/{result['content_id']}"
        candidate = client.get(url, headers=ALICE).json()["analysis"]["candidate"]["id"]
        assert (
            client.post(
                url + ":review", headers=ALICE, json={"candidate_id": candidate, "decision": "reject"}
            ).status_code
            == 200
        )
        after = client.get(url, headers=ALICE).json()
        assert after["status"] == "analysis_rejected" and after["snapshot"]
        assert after["summary"]["effective"] is None
        search = client.post("/v1/search", headers=ALICE, json={"query": "은하수조약돌"}).json()
        assert result["content_id"] in [r["content_id"] for r in search["results"]]


def test_dev_header_rejects_external_bind_even_with_override() -> None:
    result = CliRunner().invoke(app, ["api", "serve", "--host", "0.0.0.0", "--allow-external-bind"])
    assert result.exit_code == 2
    assert "바인딩할 수 없습니다" in result.output


def test_error_and_logs_do_not_contain_source_fixture_or_note(
    container_factory: Callable[..., AppContainer], caplog
) -> None:
    with _client(container_factory()) as client:
        response = _post(
            client,
            {
                "source": {"kind": "text", "text": "PRIVATE_SOURCE", "fixture": "PRIVATE_PATH"},
                "user_note": "PRIVATE_NOTE",
            },
            key="PRIVATE_KEY",
        )
        assert response.status_code == 422
        for private in ("PRIVATE_SOURCE", "PRIVATE_PATH", "PRIVATE_NOTE", "PRIVATE_KEY"):
            assert private not in response.text and private not in caplog.text


def test_failed_reanalysis_after_persist_restores_ai_without_losing_concurrent_patch(
    container_factory: Callable[..., AppContainer],
) -> None:
    with _client(container_factory()) as client:
        first = _post(client, {"source": {"kind": "text", "text": TEXT}}).json()
        ingest = client.app.state.ingest
        ingest.run_inline(first["job_id"])
        url = f"/v1/contents/{first['content_id']}"
        before = client.get(url, headers=ALICE).json()
        new = client.post(url + ":reanalyze", json={}, headers={**ALICE, "Idempotency-Key": "fail-after-i6"}).json()

        def fail(job):
            assert client.patch(url, headers=ALICE, json={"summary": "분석 도중 사용자 수정"}).status_code == 200
            raise AnalysisSchemaError("permanent embed failure")

        ingest.worker.stages["embed"] = fail
        assert ingest.run_inline(new["job_id"]).status == "failed"
        after = client.get(url, headers=ALICE).json()
        assert after["status"] == "ready"
        assert after["summary"]["ai"] == before["summary"]["ai"]
        assert after["summary"]["user"] == "분석 도중 사용자 수정"
        with ingest.repo.engine.connect() as conn:
            accepted = conn.scalar(
                select(T.analysis_runs.c.accepted_at).where(T.analysis_runs.c.job_id == new["job_id"])
            )
        assert accepted is None


def test_trace_omits_unavailable_scores_and_contains_no_fake_progress(
    container_factory: Callable[..., AppContainer],
) -> None:
    with _client(container_factory()) as client:
        created = _post(client, {"source": {"kind": "text", "text": TEXT}}).json()
        client.app.state.ingest.run_inline(created["job_id"])
        job = client.get(f"/v1/jobs/{created['job_id']}?trace=full", headers=ALICE).json()
        assert "progress" not in job
        assert "chain_of_thought" not in str(job) and "reasoning_trace" not in str(job)
        assert "scores" not in job["trace"]["model_processing"]
        assert job["trace"]["validation"]["schema_valid"] is True
        assert [step["stage"] for step in job["steps"]] == [
            "fetch",
            "extract",
            "vision",
            "chunk",
            "analyze",
            "confirm",
            "persist",
            "embed",
            "index",
        ]
        assert all(step["attempts"] == 1 for step in job["steps"] if step["stage"] not in ("vision", "confirm"))
        assert job["steps"][5]["status"] == "skipped"
        assert all(
            step["started_at"] is not None and step["finished_at"] is not None
            for step in job["steps"]
            if step["stage"] not in ("vision", "confirm")
        )


def test_hide_removes_search_hit_and_unhide_restores_it(container_factory: Callable[..., AppContainer]) -> None:
    with _client(container_factory()) as client:
        result = _post(client, {"source": {"kind": "text", "text": "은하수조약돌 관찰 기록과 보관 방법입니다."}}).json()
        client.app.state.ingest.run_inline(result["job_id"])
        url = f"/v1/contents/{result['content_id']}"
        for hidden in (False, True, False):
            assert client.patch(url, headers=ALICE, json={"hidden": hidden}).status_code == 200
            search = client.post("/v1/search", headers=ALICE, json={"query": "은하수조약돌"}).json()
            assert (result["content_id"] in [r["content_id"] for r in search["results"]]) is not hidden


def test_other_user_content_job_candidate_trace_all_404_and_delete_cascades(
    container_factory: Callable[..., AppContainer],
) -> None:
    c = container_factory()
    with _client(c) as client:
        result = _post(client, {"source": {"kind": "text", "text": TEXT}, "automation_level": "confirm"}).json()
        client.app.state.ingest.run_inline(result["job_id"])
        url = f"/v1/contents/{result['content_id']}"
        candidate = client.get(url, headers=ALICE).json()["analysis"]["candidate"]["id"]
        bob = {"X-User-Id": "u_bob"}
        assert client.get(url, headers=bob).status_code == 404
        assert client.get(f"/v1/jobs/{result['job_id']}?trace=full", headers=bob).status_code == 404
        assert (
            client.post(
                url + ":review", headers=bob, json={"candidate_id": candidate, "decision": "approve"}
            ).status_code
            == 404
        )
        assert client.patch(url, headers=bob, json={"hidden": True}).status_code == 404
        assert client.delete(url, headers=bob).status_code == 404
        assert client.delete(url, headers=ALICE).status_code == 204
        with c.engine.connect() as conn:
            for table in (
                T.snapshots,
                T.analysis_candidates,
                T.ingest_trace_artifacts,
                T.ingest_jobs,
                T.content_fingerprints,
                T.embeddings,
            ):
                assert conn.execute(select(table)).all() == []


def test_effective_tag_filter_and_saved_time_boundaries(container_factory: Callable[..., AppContainer]) -> None:
    with _client(container_factory()) as client:
        result = _post(client, {"source": {"kind": "text", "text": TEXT}}).json()
        client.app.state.ingest.run_inline(result["job_id"])
        url = f"/v1/contents/{result['content_id']}"
        assert (
            client.patch(url, headers=ALICE, json={"representative_tags": ["직접태그", "둘째태그"]}).status_code == 200
        )
        assert len(client.get("/v1/contents?tag=직접태그&tag=둘째태그", headers=ALICE).json()["items"]) == 1
        assert client.get("/v1/contents?tag=없는태그", headers=ALICE).json()["items"] == []
        assert (
            client.get("/v1/contents", params={"saved_to": "2026-11-03T10:00:00+09:00"}, headers=ALICE).json()["items"]
            == []
        )
        assert (
            len(
                client.get("/v1/contents", params={"saved_from": "2026-11-03T10:00:00+09:00"}, headers=ALICE).json()[
                    "items"
                ]
            )
            == 1
        )
        assert client.get("/v1/contents?saved_from=2026-11-03", headers=ALICE).status_code == 422


def test_original_404_does_not_remove_snapshot_or_summary(
    container_factory: Callable[..., AppContainer], monkeypatch: pytest.MonkeyPatch
) -> None:
    from jupjup.ingest.fetch import HttpResponse, HttpSourceFetcher

    calls = []

    def transport(url, timeout):
        calls.append(url)
        if len(calls) > 1:
            return HttpResponse(404, {"content-type": "text/plain"}, b"deleted")
        return HttpResponse(
            200, {"content-type": "text/html"}, ("<html><body><p>" + TEXT + "</p></body></html>").encode()
        )

    fetcher = HttpSourceFetcher(resolver=lambda _: ["93.184.216.34"], transport=transport)
    monkeypatch.setattr("jupjup.container.HttpSourceFetcher", lambda **kwargs: fetcher)
    with _client(container_factory()) as client:
        result = _post(client, {"source": {"kind": "url", "url": "https://example.com/original"}}).json()
        ingest = client.app.state.ingest
        assert ingest.run_inline(result["job_id"]).status == "succeeded"
        url = f"/v1/contents/{result['content_id']}"
        before = client.get(url, headers=ALICE).json()
        reanalyze = client.post(
            url + ":reanalyze", json={}, headers={**ALICE, "Idempotency-Key": "original-gone"}
        ).json()
        assert ingest.run_inline(reanalyze["job_id"]).status == "succeeded"
        after = client.get(url, headers=ALICE).json()
        assert after["snapshot"] == before["snapshot"]
        assert after["summary"] == before["summary"]
        assert len(calls) == 1


def test_confirm_candidate_is_not_indexed_before_approve(container_factory: Callable[..., AppContainer]) -> None:
    from unittest.mock import Mock

    c = container_factory()
    ingest = build_ingest_service(c)
    runners = ingest.worker.stages["analyze"].__self__
    original = runners.analyzer

    def analyze(value):
        output, meta = original.analyze(value)
        return output.model_copy(
            update={"summary": "승인전비밀표식은 사용자가 승인하기 전 검색에 반영되면 안 되는 분석 요약입니다."}
        ), meta

    runners.analyzer = Mock(analyze=analyze)
    with TestClient(create_app(container=c, ingest=ingest)) as client:
        result = _post(client, {"source": {"kind": "text", "text": TEXT}, "automation_level": "confirm"}).json()
        ingest.run_inline(result["job_id"])

        def search():
            return client.post("/v1/search", headers=ALICE, json={"query": "승인전비밀표식"}).json()["results"]

        assert search() == []
        url = f"/v1/contents/{result['content_id']}"
        candidate = client.get(url, headers=ALICE).json()["analysis"]["candidate"]["id"]
        assert (
            client.post(
                url + ":review", headers=ALICE, json={"candidate_id": candidate, "decision": "approve"}
            ).status_code
            == 202
        )
        assert ingest.run_inline(result["job_id"]).status == "succeeded"
        assert [item["content_id"] for item in search()] == [result["content_id"]]


def test_reanalyze_key_scope_includes_path_parameters(container_factory: Callable[..., AppContainer]) -> None:
    with _client(container_factory()) as client:
        results = [
            _post(client, {"source": {"kind": "text", "text": TEXT + str(i)}}, key=str(i)).json() for i in range(2)
        ]
        for result in results:
            client.app.state.ingest.run_inline(result["job_id"])
        responses = [
            client.post(
                f"/v1/contents/{result['content_id']}:reanalyze",
                json={},
                headers={**ALICE, "Idempotency-Key": "shared-reanalysis-key"},
            )
            for result in results
        ]
        assert [response.status_code for response in responses] == [202, 409]


def test_concurrent_hash_claim_has_one_canonical_and_alias_is_not_listed(tmp_path: Path) -> None:
    c = build_container(Settings(env="test", db_path=tmp_path / "hash-race.db"))
    ingest = build_ingest_service(c)
    with TestClient(create_app(container=c, ingest=ingest)) as client:
        results = [
            _post(client, {"source": {"kind": "text", "text": TEXT}}, key=f"hash-race-{i}").json() for i in range(2)
        ]
        with ThreadPoolExecutor(max_workers=2) as pool:
            jobs = list(pool.map(lambda item: ingest.run_inline(item["job_id"]), results))
        assert sorted(job.status for job in jobs) == ["deduplicated", "succeeded"]
        alias = next(job for job in jobs if job.status == "deduplicated")
        canonical = next(job for job in jobs if job.status == "succeeded")
        detail = client.get(f"/v1/contents/{alias.content_id}", headers=ALICE).json()
        assert detail["canonical_id"] == canonical.content_id
        assert "snapshot" not in detail
        assert [item["id"] for item in client.get("/v1/contents", headers=ALICE).json()["items"]] == [
            canonical.content_id
        ]


def test_patch_during_i6_and_approve_preserves_latest_user_rows(container_factory: Callable[..., AppContainer]) -> None:
    with _client(container_factory()) as client:
        created = _post(client, {"source": {"kind": "text", "text": TEXT}, "automation_level": "confirm"}).json()
        ingest = client.app.state.ingest
        ingest.run_inline(created["job_id"])
        url = f"/v1/contents/{created['content_id']}"
        candidate = client.get(url, headers=ALICE).json()["analysis"]["candidate"]["id"]
        assert client.patch(url, headers=ALICE, json={"summary": "승인 전에 수정"}).status_code == 200
        assert (
            client.post(
                url + ":review", headers=ALICE, json={"candidate_id": candidate, "decision": "approve"}
            ).status_code
            == 202
        )
        assert client.patch(url, headers=ALICE, json={"detail_tags": {"topics": ["선행 수정"]}}).status_code == 200
        original = ingest.worker.stages["persist"]

        def patch_then_persist(job):
            assert (
                client.patch(
                    url,
                    headers=ALICE,
                    json={
                        "summary": "I6 직전 최종 수정",
                        "detail_tags": {"topics": None},
                        "representative_tags": ["내태그"],
                    },
                ).status_code
                == 200
            )
            original(job)

        ingest.worker.stages["persist"] = patch_then_persist
        assert ingest.run_inline(created["job_id"]).status == "succeeded"
        detail = client.get(url, headers=ALICE).json()
        assert detail["summary"]["effective"] == "I6 직전 최종 수정"
        assert detail["detail_tags"]["user_patch"] == {"topics": None}
        assert detail["representative_tags"]["user"] == ["내태그"]


def test_terminal_and_waiting_jobs_clear_workspace_and_replay_durable_trace(
    container_factory: Callable[..., AppContainer],
) -> None:
    c = container_factory()
    with _client(c) as client:
        result = _post(client, {"source": {"kind": "text", "text": TEXT}, "automation_level": "confirm"}).json()
        ingest = client.app.state.ingest
        ingest.run_inline(result["job_id"])
        assert ingest.queue.get(result["job_id"]).stage_data == {}
        job = client.get(f"/v1/jobs/{result['job_id']}?trace=full", headers=ALICE).json()
        assert job["trace"]["input"] and job["trace"]["result"]
        candidate = job["candidate"]["id"]
        assert (
            client.post(
                f"/v1/contents/{result['content_id']}:review",
                headers=ALICE,
                json={"candidate_id": candidate, "decision": "approve"},
            ).status_code
            == 202
        )
        assert ingest.run_inline(result["job_id"]).status == "succeeded"
        assert ingest.queue.get(result["job_id"]).stage_data == {}
        job = client.get(f"/v1/jobs/{result['job_id']}?trace=full", headers=ALICE).json()
        assert job["trace"]["result"] and job["trace"]["input"]
        for event in ingest.queue.events(result["job_id"]):
            assert "attempt" in event.detail
            if event.event != "started":
                assert "duration_ms" in event.detail


def test_image_metadata_is_preserved_in_snapshot(container_factory: Callable[..., AppContainer]) -> None:
    c = container_factory()
    with _client(c) as client:
        metadata = {"mime_type": "image/jpeg", "sha256": "a" * 64}
        result = _post(client, {"source": {"kind": "image", "ocr_text": TEXT, "image": metadata}}).json()
        assert client.app.state.ingest.run_inline(result["job_id"]).status == "succeeded"
        snapshot = c.repo.get_bundle("u_alice", result["content_id"]).snapshot
        assert snapshot is not None and snapshot.raw_meta["image"] == metadata


def test_invalid_detail_patch_uses_patch_error_code(container_factory: Callable[..., AppContainer]) -> None:
    with _client(container_factory()) as client:
        result = _post(client, {"source": {"kind": "text", "text": TEXT}}).json()
        response = client.patch(
            f"/v1/contents/{result['content_id']}", headers=ALICE, json={"detail_tags": {"unknown_field": "invalid"}}
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "INVALID_PATCH"


def test_reanalysis_cannot_commit_an_unreadable_effective_tag_set(
    container_factory: Callable[..., AppContainer],
) -> None:
    from unittest.mock import Mock

    with _client(container_factory()) as client:
        first = _post(client, {"source": {"kind": "text", "text": TEXT}}).json()
        ingest = client.app.state.ingest
        ingest.run_inline(first["job_id"])
        url = f"/v1/contents/{first['content_id']}"
        names = [f"사용자태그{i}" for i in range(15)]
        assert client.patch(url, headers=ALICE, json={"representative_tags": names}).status_code == 200
        runners = ingest.worker.stages["analyze"].__self__
        original = runners.analyzer

        def analyze(value):
            output, meta = original.analyze(value)
            return output.model_copy(update={"representative_tags": ["새AI1", "새AI2", "새AI3"]}), meta

        runners.analyzer = Mock(analyze=analyze)
        new = client.post(url + ":reanalyze", headers={**ALICE, "Idempotency-Key": "tag-limit"}, json={}).json()
        assert ingest.run_inline(new["job_id"]).status == "failed"
        detail = client.get(url, headers=ALICE)
        assert detail.status_code == 200
        assert detail.json()["status"] == "ready"
        assert detail.json()["representative_tags"]["effective"] == names

"""Full public save/job/review and safe index projection on an isolated DB."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from jupjup.container import build_ingest_service
from jupjup.domain.errors import SourceTextUnavailableError
from jupjup.ingest.fetch import FetcherRouter, RawSource
from jupjup.save.dto import ContentDetail
from jupjup.storage import tables as T
from tests.integration.test_youtube_legacy_notice import bundle
from tests.legacy_api import create_app
from tests.unit.test_youtube_metadata import public_fetch

HEADERS = {"X-User-Id": "u_alice", "Idempotency-Key": "metadata-1"}


class FixedFetcher:
    def __init__(self, raw):
        self.raw = raw

    def supports(self, spec):
        return True

    def fetch(self, spec):
        if isinstance(self.raw, Exception):
            raise self.raw
        return self.raw


def setup(c, raw):
    ingest = build_ingest_service(c, worker_id="metadata-test")
    ingest.worker.stages["fetch"].__self__.fetcher = FetcherRouter([FixedFetcher(raw)])
    return ingest, TestClient(create_app(container=c, ingest=ingest))


def submit(client, level="auto", key="metadata-1"):
    return client.post(
        "/v1/contents/c_legacy:reanalyze",
        headers={**HEADERS, "Idempotency-Key": key},
        json={"mode": "youtube_metadata", "automation_level": level},
    )


@pytest.mark.parametrize("level", ["auto", "confirm"])
def test_existing_item_preserves_layers_and_projects_index(container_factory, level):
    c = container_factory()
    c.repo.upsert(bundle({"source": "http"}, "all"))
    before = c.repo.get_bundle("u_alice", "c_legacy")
    raw, _ = public_fetch()
    ingest, client = setup(c, raw)
    with client:
        response = submit(client, level)
        assert response.status_code == 202
        job = response.json()["job_id"]
        assert submit(client, level).json() == response.json()
        assert submit(client, level, "other").status_code == 409
        assert (
            client.post("/v1/contents/c_legacy:reanalyze", headers=HEADERS, json={"mode": "snapshot"}).status_code
            == 409
        )
        ingest.run_inline(job)
        if level == "confirm":
            detail = client.get("/v1/contents/c_legacy", headers=HEADERS).json()
            candidate = detail["analysis"]["candidate"]
            assert candidate["source_scope"] == "youtube_metadata" and "summary" not in candidate
            assert detail["analysis"]["metadata"] is None
            assert detail["representative_tags"]["effective"] == ["사용자태그"]
            decision = {"candidate_id": candidate["id"], "decision": "approve"}
            assert client.post("/v1/contents/c_legacy:review", headers=HEADERS, json=decision).status_code == 202
            assert client.post("/v1/contents/c_legacy:review", headers=HEADERS, json=decision).status_code == 202
            ingest.run_inline(job)
        record = ingest.status("u_alice", job)
        assert record.status == "succeeded", record.last_error
        result = client.get("/v1/contents/c_legacy", headers=HEADERS).json()
        ContentDetail.model_validate(result)
        assert result["analysis"]["metadata"]["detail_tags"]["category"] == "tech"
        assert result["analysis"]["metadata"]["metadata"]["description"] == raw.meta["youtube_metadata"]["description"]
        assert result["summary"]["ai"] is None and result["summary"]["effective"] == "직접 작성한 요약"
        assert "C++" in result["representative_tags"]["effective"]
        assert result["detail_tags"]["effective"]["topics"] == ["사용자주제"]
        assert result["user_note"] == "내 메모"
        after = c.repo.get_bundle("u_alice", "c_legacy")
        assert after.snapshot == before.snapshot and after.summaries == before.summaries
        assert after.detail_tags.user_patch == before.detail_tags.user_patch
        assert after.content.hidden_tags == before.content.hidden_tags
        doc = c.indexer.prepare_bundle(after).document
        assert doc.fields["body"] == raw.meta["youtube_metadata"]["description"]
        assert doc.fields["summary"] == "직접 작성한 요약"
        assert "잘못된" not in str(doc.fields) and "평범한 문자열" not in str(doc.fields)
        c.indexer.reload_user("u_alice")
        # Reload uses the same projection, and a user patch triggers the same safe path.
        patch = client.patch(
            "/v1/contents/c_legacy",
            headers={**HEADERS, "If-Match": f'"content:c_legacy:{result["revision"]}"'},
            json={"summary": "분류 후 직접 수정"},
        )
        assert patch.status_code == 200
        assert (
            c.indexer.prepare_bundle(c.repo.get_bundle("u_alice", "c_legacy")).document.fields["summary"]
            == "분류 후 직접 수정"
        )


def test_reject_and_fetch_failure_do_not_replace_existing_data(container_factory):
    for failure in (False, True):
        c = container_factory()
        c.repo.upsert(bundle({"source": "http"}, "all"))
        before = c.repo.get_bundle("u_alice", "c_legacy")
        raw, _ = public_fetch()
        ingest, client = setup(c, SourceTextUnavailableError("blocked", {"retryable": False}) if failure else raw)
        with client:
            job = submit(client, "confirm").json()["job_id"]
            ingest.run_inline(job)
            if not failure:
                cand = client.get("/v1/contents/c_legacy", headers=HEADERS).json()["analysis"]["candidate"]
                assert (
                    client.post(
                        "/v1/contents/c_legacy:review",
                        headers=HEADERS,
                        json={"candidate_id": cand["id"], "decision": "reject"},
                    ).status_code
                    == 200
                )
            after = c.repo.get_bundle("u_alice", "c_legacy")
            assert after.snapshot == before.snapshot and after.summaries == before.summaries
            assert after.tags == before.tags and after.detail_tags == before.detail_tags


def test_new_save_and_duplicate_keep_metadata_searchable(container_factory):
    c = container_factory()
    raw, _ = public_fetch()
    ingest, client = setup(c, raw)
    with client:
        body = {"source": {"kind": "url", "url": raw.final_url}}
        submitted = client.post("/v1/contents", headers=HEADERS, json=body).json()
        job = submitted["job_id"]
        ingest.run_inline(job)
        assert ingest.status("u_alice", job).status == "succeeded"
        duplicate = client.post("/v1/contents", headers={**HEADERS, "Idempotency-Key": "duplicate"}, json=body)
        assert duplicate.status_code == 200 and duplicate.json()["content_id"] == submitted["content_id"]
        assert duplicate.json()["job_id"] is None
        detail = client.get("/v1/contents/" + submitted["content_id"], headers=HEADERS).json()
        assert (
            detail["summary"]["effective"] is None
            and detail["analysis"]["metadata"]["source_scope"] == "youtube_metadata"
        )
        response = client.post("/v1/search", headers=HEADERS, json={"query": "C++ 프로그래밍"})
        assert response.status_code == 200
        assert submitted["content_id"] in [r["content_id"] for r in response.json()["results"]]
        with c.engine.connect() as conn:
            assert not conn.execute(select(T.summaries)).all()


@pytest.mark.parametrize("level", ["auto", "confirm"])
def test_live_capture_in_isolated_db(container_factory, level):
    path = Path("var/metadata-validation/live_explicit_raw.json")
    if not path.exists():
        pytest.skip("explicit live read capture not present")
    raw = RawSource.model_validate_json(path.read_text())
    c = container_factory()
    c.repo.upsert(bundle({"source": "http"}, "all"))
    ingest, client = setup(c, raw)
    with client:
        job = submit(client, level).json()["job_id"]
        ingest.run_inline(job)
        if level == "confirm":
            candidate = client.get("/v1/contents/c_legacy", headers=HEADERS).json()["analysis"]["candidate"]
            assert candidate["source_scope"] == "youtube_metadata"
            assert (
                client.post(
                    "/v1/contents/c_legacy:review",
                    headers=HEADERS,
                    json={"candidate_id": candidate["id"], "decision": "approve"},
                ).status_code
                == 202
            )
            ingest.run_inline(job)
        assert ingest.status("u_alice", job).status == "succeeded"
        detail = client.get("/v1/contents/c_legacy", headers=HEADERS).json()
        result = detail["analysis"]["metadata"]
        assert "cpp_lecture_material" in result["metadata"]["description"]
        assert result["detail_tags"]["category"] == "tech" and result["detail_tags"]["purpose"] == ["공부자료"]
        assert result["representative_tags"] == ["C++", "프로그래밍", "강의"]
        assert result["metadata"]["transcript_reason"] == "not_requested"
        indexed = c.registry.get("u_alice").documents["c_legacy"]
        assert indexed.fields["body"] == result["metadata"]["description"]
        assert "잘못된" not in str(indexed.fields)
        c.indexer.reload_user("u_alice")
        assert c.registry.get("u_alice").documents["c_legacy"].fields == indexed.fields
        Path("var/metadata-validation/live_result.json").write_text(
            __import__("json").dumps(result, ensure_ascii=False)
        )


def test_failure_after_persist_rolls_back_ai_and_preserves_concurrent_user_patch(container_factory):
    from jupjup.domain.errors import AnalysisSchemaError

    c = container_factory()
    c.repo.upsert(bundle({"source": "http"}, "all"))
    before = c.repo.get_bundle("u_alice", "c_legacy")
    raw, _ = public_fetch()
    ingest, client = setup(c, raw)
    with client:
        job = submit(client).json()["job_id"]

        def fail_embed(user_id, content_id):
            # SQL-only patch models a user edit committed while worker is in provider work.
            from jupjup.save.dto import ContentPatch
            from jupjup.save.patch import apply_user_patch

            apply_user_patch(c.repo, user_id, content_id, ContentPatch(summary="동시 사용자 수정"), None)
            raise AnalysisSchemaError("permanent test embed failure")

        c.indexer.embed_content = fail_embed
        ingest.run_inline(job)
        assert ingest.status("u_alice", job).status == "failed"
        after = c.repo.get_bundle("u_alice", "c_legacy")
        assert after.tags == before.tags and after.detail_tags.ai_json == before.detail_tags.ai_json
        assert after.snapshot == before.snapshot
        assert after.summary.text == "동시 사용자 수정"
        detail = client.get("/v1/contents/c_legacy", headers=HEADERS).json()
        assert detail["analysis"]["metadata"] is None and detail["summary"]["ai"] is None


def test_concurrent_metadata_requests_reserve_one_job(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    from jupjup.api.errors import ApiError
    from jupjup.config import Settings
    from jupjup.container import build_container
    from jupjup.save.dto import ReanalyzeRequest
    from jupjup.save.service import ContentCommandService
    from jupjup.storage.db import create_db_engine

    c = build_container(Settings(env="test", mode="mock"), engine=create_db_engine(tmp_path / "isolated.sqlite"))
    c.repo.upsert(bundle({"source": "http"}, "all"))
    ingest = build_ingest_service(c)
    service = ContentCommandService(ingest)

    def send(key):
        try:
            return service.submit("u_alice", ReanalyzeRequest(mode="youtube_metadata"), key, "c_legacy")[0]
        except ApiError as error:
            return error.status_code

    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(send, ["a", "b", "c"]))
    assert sorted(results) == [202, 409, 409]
    with c.engine.connect() as conn:
        jobs = conn.execute(select(T.ingest_jobs)).mappings().all()
        assert len(jobs) == 1
        assert __import__("json").loads(jobs[0]["source_spec"])["youtube_metadata_only"] is True

"""Service wiring uses scripted LLM here; real GGUF evidence lives in the live report."""

from __future__ import annotations

import copy
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from jupjup.collections.automatic import add_category_collection
from jupjup.config import Settings
from jupjup.container import build_container, build_ingest_service
from jupjup.domain.errors import LLMProviderError
from jupjup.ingest.fetch import FetcherRouter, RawSource
from jupjup.ingest.validation import AnalysisValidator
from tests.integration.test_youtube_metadata import FixedFetcher
from tests.legacy_api import create_app
from tests.unit.test_llm_analyzer import SOURCE, VALID, ScriptedLLM, analyzer_for, ok

H = {"X-User-Id": "u_alice", "Idempotency-Key": "llm-save"}


def setup(c, value=VALID, metadata=False):

    llm = ScriptedLLM(
        responder=lambda call: (
            value
            if isinstance(value, Exception)
            else ok({key: "primary_topic" for key in call.schema.model_fields})
            if call.schema.__name__ == "SalienceSelection"
            else ok(value)
        )
    )
    analyzer = analyzer_for(llm, AnalysisValidator(c.lexicon))
    service = build_ingest_service(c, analyzer=analyzer)
    if metadata:
        raw = RawSource(
            kind="youtube",
            mime="text/plain",
            body="",
            fetched_at=datetime.now(UTC),
            final_url="https://www.youtube.com/watch?v=wpk7AM6FPRc",
            meta={
                "source": "youtube_metadata",
                "youtube_metadata": {
                    "title": "카페 소식",
                    "description": SOURCE,
                    "description_source": "videoDetails.shortDescription",
                    "description_status": "available",
                    "transcript_reason": "not_requested",
                },
            },
        )
        service.worker.stages["fetch"].__self__.fetcher = FetcherRouter([FixedFetcher(raw)])
    return service, TestClient(create_app(container=c, ingest=service)), llm


@pytest.mark.parametrize("metadata", [False, True])
@pytest.mark.parametrize("level", ["auto", "confirm"])
def test_llm_save_collection_and_user_preservation(container_factory, metadata, level):
    c = container_factory()
    service, client, llm = setup(c, metadata=metadata)
    with client:
        source = (
            {"kind": "url", "url": "https://www.youtube.com/watch?v=wpk7AM6FPRc"}
            if metadata
            else {"kind": "text", "text": SOURCE}
        )
        ids = client.post(
            "/v1/contents", headers=H, json={"source": source, "automation_level": level, "user_note": "개인 메모"}
        ).json()
        cid = ids["content_id"]
        service.run_inline(ids["job_id"])
        detail = client.get(f"/v1/contents/{cid}", headers=H).json()
        if level == "confirm":
            assert not detail["collection_ids"]
            candidate = detail["analysis"]["candidate"]
            patched = client.patch(
                f"/v1/contents/{cid}",
                headers={**H, "If-Match": f'"content:{cid}:{detail["revision"]}"'},
                json={
                    "summary": "내가 작성한 요약",
                    "representative_tags": ["내태그"],
                    "detail_tags": {"topics": ["수동주제"]},
                },
            )
            assert patched.status_code == 200, patched.text
            response = client.post(
                f"/v1/contents/{cid}:review", headers=H, json={"candidate_id": candidate["id"], "decision": "approve"}
            )
            assert response.status_code == 202, response.text
            service.run_inline(ids["job_id"])
        job = service.status("u_alice", ids["job_id"])
        assert job.status == "succeeded", job.last_error
        detail = client.get(f"/v1/contents/{cid}", headers=H).json()
        assert detail["summary"]["ai"] == VALID["summary"]
        assert len(detail["representative_tags"]["ai"]) == 3
        assert detail["collection_ids"]
        if level == "confirm":
            assert detail["summary"]["effective"] == "내가 작성한 요약"
            assert "내태그" in detail["representative_tags"]["effective"]
            assert detail["user_note"] == "개인 메모"
            assert detail["detail_tags"]["effective"]["topics"] == ["수동주제"]
        if metadata:
            assert detail["analysis"]["metadata"]["model"] == llm.model_id
        with c.engine.connect() as conn:
            assert conn.scalar(text("SELECT name FROM collections")) == "음식·음료"


def test_focused_metadata_save_persists_only_safe_detail_fields(container_factory):
    c = container_factory()
    value = copy.deepcopy(VALID)
    value["summary"] = "레디언트 게임 장면 #발로란티"
    value["evidence"] = [{"claim": "발로란티", "source_span": "#발로란티"}]
    value["representative_tags"] = ["발로란티", "레디언트", "게임"]
    value["detail_tags"].update(
        {
            "category": "culture_media",
            "topics": ["잘못된 주제"],
            "keywords": ["잘못된 키워드"],
            "entities": [{"type": "other", "name": "발로란티"}],
            "locations": [{"name": "서울", "level": "city"}],
            "purpose": ["학술자료"],
            "save_intent": {"labels": ["학술자료"], "confidence": 0.9, "inferred": True},
            "attributes": ["academic"],
            "time_mentions": ["#발로란티"],
            "media": ["video"],
        }
    )
    service, client, _ = setup(c, value, metadata=True)
    raw = RawSource(
        kind="youtube",
        mime="text/plain",
        body="",
        fetched_at=datetime.now(UTC),
        final_url="https://www.youtube.com/watch?v=wpk7AM6FPRc",
        meta={
            "source": "youtube_metadata",
            "youtube_metadata": {
                "title": "레디언트 게임 장면",
                "description": "#발로란티",
                "description_source": "videoDetails.shortDescription",
                "description_status": "available",
                "transcript_reason": "not_requested",
            },
        },
    )
    service.worker.stages["fetch"].__self__.fetcher = FetcherRouter([FixedFetcher(raw)])
    with client:
        submitted = client.post(
            "/v1/contents",
            headers=H,
            json={"source": {"kind": "url", "url": raw.final_url}, "automation_level": "auto"},
        ).json()
        service.run_inline(submitted["job_id"])
        job = service.status("u_alice", submitted["job_id"])
        assert job.status == "succeeded", job.last_error
        detail = client.get(f"/v1/contents/{submitted['content_id']}", headers=H).json()
        saved = detail["analysis"]["metadata"]["detail_tags"]
        assert set(saved) == {
            "schema_version", "category", "topics", "keywords", "entities", "locations", "purpose", "save_intent"
        }
        assert saved["entities"] == [{"type": "other", "name": "발로란티"}] and saved["locations"] == []
        assert saved["topics"] == ["발로란티"] and saved["purpose"] == ["정보보관"]


@pytest.mark.parametrize("metadata", [False, True])
@pytest.mark.parametrize("failure", ["tags", "provider", "rollback"])
def test_failures_never_save_fake_success(container_factory, monkeypatch, metadata, failure):
    c = container_factory()
    value = copy.deepcopy(VALID)
    if failure == "tags":
        value["representative_tags"] = []
    elif failure == "provider":
        value = LLMProviderError("모델 실패", {"retryable": False})
    else:
        import jupjup.collections.automatic as automatic

        original = automatic.add_category_collection

        def fail(*args):
            original(*args)
            raise IntegrityError("forced rollback", {}, None)

        monkeypatch.setattr(automatic, "add_category_collection", fail)
    service, client, llm = setup(c, value, metadata)
    with client:
        source = (
            {"kind": "url", "url": "https://www.youtube.com/watch?v=wpk7AM6FPRc"}
            if metadata
            else {"kind": "text", "text": SOURCE}
        )
        ids = client.post("/v1/contents", headers=H, json={"source": source, "automation_level": "auto"}).json()
        service.run_inline(ids["job_id"])
        assert service.status("u_alice", ids["job_id"]).status != "succeeded"
        with c.engine.connect() as conn:
            for table in ["summaries", "tags", "analysis_runs", "collections", "collection_contents"]:
                assert conn.scalar(text(f"SELECT count(*) FROM {table}")) == 0
        assert len(llm.calls) <= (4 if metadata else 3)


def test_collection_race_idempotency_and_ownership(tmp_path):
    c = build_container(Settings(mode="mock", db_path=tmp_path / "race.db"))
    # Actual saved content provides both ownership constraints and manual memberships.
    _service, client, _ = setup(c)
    with client:
        cid = client.post("/v1/contents", headers=H, json={"source": {"kind": "text", "text": SOURCE}}).json()[
            "content_id"
        ]
        manual = client.post("/v1/collections", headers=H, json={"name": "수동"}).json()["id"]
        client.put(f"/v1/collections/{manual}/contents/{cid}", headers=H)

    def add(_):
        with c.engine.begin() as conn:
            conn.exec_driver_sql("UPDATE contents SET revision=revision WHERE 0")
            add_category_collection(conn, "u_alice", cid, "tech", datetime.now(UTC).isoformat())

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(add, range(8)))
    with pytest.raises(IntegrityError), c.engine.begin() as conn:
        add_category_collection(conn, "u_bob", cid, "tech", datetime.now(UTC).isoformat())
    with c.engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM collections WHERE name='기술'")) == 1
        assert conn.scalar(text("SELECT count(*) FROM collection_contents")) == 2
        assert conn.scalar(text("SELECT count(*) FROM collections WHERE user_id='u_bob'")) == 0
        assert not conn.exec_driver_sql("PRAGMA foreign_key_check").all()


def test_salience_is_separate_call_and_only_primary_reaches_analysis(container_factory):
    from tests.unit.test_youtube_salience import gaming_metadata

    c = container_factory()
    generated = copy.deepcopy(VALID)
    generated.update(
        summary="발로란티브 게임의 인기 캐릭터 김된모를 소개하는 영상입니다.",
        representative_tags=["발로란트트랙", "ncs공개곡", "음악소개"],
        evidence=[{"claim": "발로란트 관련 영상", "source_span": "#발로란트 #김된모"}],
        detail_tags={
            "schema_version": 1,
            "category": "culture_media",
            "topics": ["발로란티브 게임"],
            "keywords": ["발로란티브", "공부자료"],
            "entities": [{"type": "person", "name": "김된모"}, {"type": "work", "name": "발로란티브"}],
            "purpose": ["과제", "공부자료"],
        },
        save_intent={"labels": ["과제", "공부자료"], "confidence": 0.9, "rationale": "공부할 내용이다."},
    )
    service, client, llm = setup(c, generated, metadata=True)
    llm.responder = lambda call: (
        ok(
            {
                key: ("primary_topic" if key in {"block_0", "block_3"} else "background_music_credit")
                for key in call.schema.model_fields
            }
        )
        if call.schema.__name__ == "SalienceSelection"
        else ok(generated)
    )
    metadata = gaming_metadata()
    raw = RawSource(
        kind="youtube",
        mime="text/plain",
        body="",
        fetched_at=datetime.now(UTC),
        final_url="https://www.youtube.com/watch?v=ZZ4QNu0YYGw",
        meta={"source": "youtube_metadata", "youtube_metadata": metadata.model_dump()},
    )
    service.worker.stages["fetch"].__self__.fetcher = FetcherRouter([FixedFetcher(raw)])
    with client:
        ids = client.post(
            "/v1/contents",
            headers=H,
            json={
                "source": {"kind": "url", "url": raw.final_url},
                "automation_level": "auto",
            },
        ).json()
        service.run_inline(ids["job_id"])
        assert service.status("u_alice", ids["job_id"]).status == "succeeded"
        assert len(llm.calls) == 2
        assert "NCS" in llm.calls[0].user
        assert "NCS" not in llm.calls[1].user and "Lost Sky" not in llm.calls[1].user
        assert "#발로란트 #김된모" in llm.calls[1].user
        detail = client.get(f"/v1/contents/{ids['content_id']}", headers=H).json()
        result = detail["analysis"]["metadata"]
        assert result["metadata"] == metadata.model_dump()
        assert result["source_scope"] == "youtube_metadata" and result["basis"] == "title_description"
        assert result["metadata"]["transcript_reason"] == "empty_captions"
        assert result["detail_tags"]["category"] == "culture_media"
        assert result["representative_tags"] == ["발로란트", "김된모", "레디언트"]
        assert result["summary"] == (
            "제목·설명 기준으로, 이 영상은 발로란트 관련 콘텐츠입니다. "
            "제목은 '모든 레디언트는 결국 저를 통합니다'이며 설명에는 #발로란트, #김된모가 표시되어 있습니다."
        )
        assert result["detail_tags"]["keywords"] == ["발로란트", "김된모", "레디언트"]
        assert result["detail_tags"]["topics"] == ["발로란트"]
        assert result["detail_tags"]["entities"] == [{"type": "person", "name": "김된모"}]
        assert result["detail_tags"]["purpose"] == ["정보보관"]
        assert result["detail_tags"]["save_intent"]["labels"] == ["정보보관"]
        assert result["salience"]["auxiliary"]
        artifact = service.queue.artifact("u_alice", ids["job_id"], "youtube_salience")
        assert artifact == result["salience"]


@pytest.mark.parametrize("selection", [{"primary_ids": []}, {"primary_ids": [999]}, "not json"])
def test_invalid_salience_never_calls_summary_or_saves(container_factory, selection):
    c = container_factory()
    service, client, llm = setup(c, metadata=True)
    llm.responder = lambda _: ok(selection)
    with client:
        ids = client.post(
            "/v1/contents",
            headers=H,
            json={
                "source": {"kind": "url", "url": "https://www.youtube.com/watch?v=wpk7AM6FPRc"},
                "automation_level": "auto",
            },
        ).json()
        service.run_inline(ids["job_id"])
        assert service.status("u_alice", ids["job_id"]).status != "succeeded"

        assert all(call.schema.__name__ == "SalienceSelection" for call in llm.calls)
        with c.engine.connect() as conn:
            for table in ["summaries", "tags", "analysis_runs", "collections", "collection_contents"]:
                assert conn.scalar(text(f"SELECT count(*) FROM {table}")) == 0


@pytest.mark.parametrize("failure", ["invalid", "provider"])
def test_salience_reanalysis_failure_preserves_saved_layers_and_memberships(container_factory, failure):
    c = container_factory()
    service, client, llm = setup(c, metadata=True)
    with client:
        ids = client.post(
            "/v1/contents",
            headers=H,
            json={
                "source": {"kind": "url", "url": "https://www.youtube.com/watch?v=wpk7AM6FPRc"},
                "automation_level": "auto",
                "user_note": "내 메모",
            },
        ).json()
        cid = ids["content_id"]
        service.run_inline(ids["job_id"])
        detail = client.get(f"/v1/contents/{cid}", headers=H).json()
        assert (
            client.patch(
                f"/v1/contents/{cid}",
                headers={**H, "If-Match": f'"content:{cid}:{detail["revision"]}"'},
                json={"summary": "수동 요약", "representative_tags": ["수동태그"]},
            ).status_code
            == 200
        )
        manual = client.post("/v1/collections", headers=H, json={"name": "내 모음"}).json()["id"]
        assert client.put(f"/v1/collections/{manual}/contents/{cid}", headers=H).status_code < 300
        before = c.repo.get_bundle("u_alice", cid)
        before_detail = client.get(f"/v1/contents/{cid}", headers=H).json()

        def fail(_):
            if failure == "provider":
                raise LLMProviderError("local provider failed", {"retryable": False})
            return ok({"primary_ids": []})

        llm.responder = fail
        response = client.post(
            f"/v1/contents/{cid}:reanalyze",
            headers={**H, "Idempotency-Key": "failed-refresh"},
            json={"mode": "youtube_metadata", "automation_level": "auto"},
        )
        assert response.status_code == 202, response.text
        jid = response.json()["job_id"]
        service.run_inline(jid)
        assert service.status("u_alice", jid).status != "succeeded"
        after = c.repo.get_bundle("u_alice", cid)
        after_detail = client.get(f"/v1/contents/{cid}", headers=H).json()
        assert after.snapshot == before.snapshot and after.summaries == before.summaries
        assert after.tags == before.tags and after.detail_tags == before.detail_tags
        assert after.content.user_note == "내 메모"
        assert set(after_detail["collection_ids"]) == set(before_detail["collection_ids"])
        assert after_detail["summary"]["effective"] == "수동 요약"

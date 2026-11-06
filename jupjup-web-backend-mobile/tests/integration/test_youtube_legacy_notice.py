"""Read-only legacy source projections; all fixtures use the isolated in-memory DB."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from jupjup.domain.models import Content, ContentBundle, DetailTags, Snapshot, Summary, Tag
from jupjup.storage import tables as T
from tests.integration.test_save_api import _client

NOW = datetime(2026, 11, 5, tzinfo=UTC)
URL = "https://www.youtube.com/watch?v=wpk7AM6FPRc"


def bundle(raw_meta, user_layers="none", source_kind="url"):
    summaries = [Summary(id="s_ai", content_id="c_legacy", version=1, text="잘못된 AI 요약", created_at=NOW)]
    tags = [Tag(name="잘못된ai태그", source="ai")]
    if user_layers == "all":
        summaries.append(
            Summary(
                id="s_user", content_id="c_legacy", version=2, text="직접 작성한 요약", source="user", created_at=NOW
            )
        )
    if user_layers != "none":
        tags.append(Tag(name="사용자태그", source="user"))
    return ContentBundle(
        content=Content(
            id="c_legacy",
            user_id="u_alice",
            source_kind=source_kind,
            source_url=URL,
            platform="youtube",
            content_type="video",
            title="C++ 강의",
            status="analysis_rejected",
            saved_at=NOW,
            user_note="내 메모",
            revision=7,
            hidden_tags=["숨긴태그"],
        ),
        snapshot=Snapshot(
            id="snap_legacy",
            content_id="c_legacy",
            captured_at=NOW,
            text="평범한 문자열이어도 메타데이터로 판정하는 저장 원문",
            raw_meta=raw_meta,
        ),
        summaries=summaries,
        tags=tags,
        detail_tags=DetailTags(
            content_id="c_legacy",
            ai_json={"schema_version": 1, "topics": ["AI주제"], "keywords": ["AI키워드"]},
            user_patch={"topics": ["사용자주제"], "keywords": None} if user_layers != "none" else None,
        ),
    )


def database_rows(c):
    with c.engine.connect() as conn:
        return {table.name: conn.execute(select(table)).all() for table in T.metadata.sorted_tables}


@pytest.mark.parametrize("user_layers", ["none", "tags", "all"])
@pytest.mark.parametrize("raw_meta", [{"source": "http"}, {"source": "http", "source_mime": "text/html"}])
def test_rejected_legacy_snapshot_hides_only_ai_without_any_write(container_factory, user_layers, raw_meta):
    c = container_factory()
    original = bundle(raw_meta, user_layers)
    c.repo.upsert(original)
    with _client(c) as client:
        stored_before = c.repo.get_bundle("u_alice", "c_legacy").model_dump()
        before = database_rows(c)
        response = client.get("/v1/contents/c_legacy", headers={"X-User-Id": "u_alice"})
        assert response.status_code == 200
        detail = response.json()
        assert detail["analysis"]["source_text_available"] is False
        assert detail["analysis"]["source_text_reason"] == "legacy_watch_snapshot"
        assert detail["analysis"]["candidate"] is None
        assert detail["analysis"]["latest_job_id"] is None  # No job/error is needed for the notice.
        assert detail["status"] == "analysis_rejected" and detail["revision"] == 7
        assert detail["summary"]["ai"] is None
        assert detail["summary"]["effective"] == ("직접 작성한 요약" if user_layers == "all" else None)
        assert detail["summary"]["user"] == detail["summary"]["effective"]
        assert detail["summary"]["source"] == ("user" if user_layers == "all" else None)
        assert detail["representative_tags"]["ai"] == []
        assert detail["representative_tags"]["effective"] == (["사용자태그"] if user_layers != "none" else [])
        assert detail["representative_tags"]["user"] == detail["representative_tags"]["effective"]
        assert detail["representative_tags"]["hidden_ai"] == ["숨긴태그"]
        assert detail["detail_tags"]["effective"] == (
            {"schema_version": 1, "topics": ["사용자주제"]} if user_layers != "none" else {"schema_version": 1}
        )
        assert detail["detail_tags"]["user_patch"] == original.detail_tags.user_patch
        assert detail["snapshot"]["text"] == original.snapshot.text
        assert "raw_meta" not in detail["snapshot"]
        assert detail["user_note"] == "내 메모" and detail["source"]["url"] == URL
        row = client.get("/v1/contents", headers={"X-User-Id": "u_alice"}).json()["items"][0]
        assert row["summary"] == detail["summary"]["effective"]
        assert row["representative_tags"] == detail["representative_tags"]["effective"]
        assert row["summary_is_mock"] is False
        assert row["status"] == detail["status"] and row["revision"] == 7
        assert database_rows(c) == before
        assert c.repo.get_bundle("u_alice", "c_legacy").model_dump() == stored_before


@pytest.mark.parametrize(
    "raw_meta,source_kind",
    [
        ({"source": "http", "transcript_segments": [{"start_sec": 0, "offset": 0}]}, "url"),
        ({"source": "http", "source_mime": "text/vtt"}, "url"),
        ({"source": "http", "source_mime": "application/x-subrip"}, "url"),
        ({"source": "http", "source_mime": "application/json"}, "url"),
        ({"source": "text"}, "text"),
    ],
)
def test_transcript_and_direct_text_keep_existing_effective_results(container_factory, raw_meta, source_kind):
    c = container_factory()
    c.repo.upsert(bundle(raw_meta, source_kind=source_kind))
    with _client(c) as client:
        detail = client.get("/v1/contents/c_legacy", headers={"X-User-Id": "u_alice"}).json()
        assert detail["analysis"]["source_text_available"] is True
        assert detail["analysis"]["source_text_reason"] is None
        assert detail["summary"]["effective"] == "잘못된 AI 요약"
        assert detail["representative_tags"]["effective"] == ["잘못된ai태그"]
        assert detail["detail_tags"]["effective"]["keywords"] == ["AI키워드"]
        row = client.get("/v1/contents", headers={"X-User-Id": "u_alice"}).json()["items"][0]
        assert row["summary"] == detail["summary"]["effective"]
        assert row["representative_tags"] == detail["representative_tags"]["effective"]

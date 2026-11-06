"""T22 AC-24/26: network-free I1-I8 integration and idempotent persistence."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select, update

from jupjup.container import AppContainer
from jupjup.domain.errors import AnalysisSchemaError, LLMRefusalError
from jupjup.domain.models import DetailTags, Summary, Tag
from jupjup.index.document import HardFilter
from jupjup.ingest.analyzer import AnalysisRunMeta
from jupjup.ingest.fetch import (
    FetcherRouter,
    FixtureHtmlFetcher,
    FixtureTranscriptFetcher,
    InlineTextFetcher,
    SourceSpec,
)
from jupjup.ingest.jobs import JOB_STAGES, JobQueue
from jupjup.ingest.schemas import AnalysisOutput
from jupjup.ingest.service import IngestRequest, IngestService
from jupjup.ingest.worker import IngestStageRunners, IngestWorker, RetryPolicy
from jupjup.providers.embedding import RecordedEmbedder
from jupjup.providers.vision import OcrOnlyUnderstander
from jupjup.search.service import SearchRequest
from jupjup.storage import tables as T

FIXTURES = Path(__file__).parents[1] / "fixtures" / "ingest"
NOW = datetime(2026, 10, 20, 10, 0, tzinfo=UTC)


class DeterministicAnalyzer:
    profile_name = "test"

    def analyze(self, inp: object) -> tuple[AnalysisOutput, AnalysisRunMeta]:
        from jupjup.ingest.chunking import AnalysisInput

        value = AnalysisInput.model_validate(inp)
        text = value.text if value.mode == "single" else " ".join(chunk.text for chunk in value.chunks or [])
        span = text[: min(40, len(text))]
        output = AnalysisOutput.model_validate(
            {
                "summary": (
                    "저장된 원문을 결정적으로 분석한 요약입니다. 검색과 재실행 검증에 사용하는 두 번째 문장입니다."
                ),
                "representative_tags": ["원문", "분석", "검색"],
                "detail_tags": {"schema_version": 1, "category": "other", "topics": ["통합테스트"]},
                "save_intent": {"labels": ["정보보관"], "confidence": 0.9, "rationale": "테스트 저장"},
                "title_suggestion": "분석된 저장물",
                "language": "ko",
                "evidence": [{"claim": "원문 내용", "source_span": span}],
            }
        )
        meta = AnalysisRunMeta(
            model="deterministic-test",
            prompt_version="test_v1",
            attempts=1,
            input_tokens=len(text),
            output_tokens=100,
            cost_usd=0,
            latency_ms=0,
            first_pass_ok=True,
        )
        return output, meta


def ingest_system(container: AppContainer) -> tuple[IngestService, IngestStageRunners]:
    queue = JobQueue(container.engine)
    fetcher = FetcherRouter(
        [
            InlineTextFetcher(clock=lambda: NOW),
            FixtureHtmlFetcher(FIXTURES, clock=lambda: NOW),
            FixtureTranscriptFetcher(FIXTURES, clock=lambda: NOW),
        ]
    )
    stages = IngestStageRunners(
        queue,
        container.repo,
        container.indexer,
        fetcher,
        DeterministicAnalyzer(),
        OcrOnlyUnderstander(),
        clock=lambda: NOW,
    )
    worker = IngestWorker(queue, stages.mapping(), lambda: NOW, RetryPolicy(), worker_id="integration")
    return IngestService(container.repo, queue, worker), stages


def test_snapshot_is_searchable_immediately_after_reduced_i2(container_factory: Callable[..., AppContainer]) -> None:
    container = container_factory()
    service, stages = ingest_system(container)
    submitted = service.submit(
        "u_ingest",
        IngestRequest(source=SourceSpec(kind="text", text="은하수조약돌 희귀 표본을 관찰한 기록입니다."), saved_at=NOW),
    )
    job = service.queue.lease("integration", NOW)
    assert job is not None and job.lease_id is not None
    job = service.queue.begin_stage(job.id, NOW, "integration", job.lease_id)
    stages.fetch(job)
    service.queue.advance(job.id, "extract", NOW, lease_id=job.lease_id)
    job = service.queue.begin_stage(job.id, NOW, "integration", job.lease_id)
    stages.extract(job)

    bundle = container.repo.get_bundle("u_ingest", submitted.content_id)
    assert bundle.content.status == "pending" and bundle.content.analysis_pending
    hits = container.registry.get("u_ingest").morph.search(["은하수조약돌"], HardFilter(), 10)
    assert [hit.content_id for hit in hits] == [submitted.content_id]
    result = container.search.search(SearchRequest(user_id="u_ingest", query="은하수조약돌", now=NOW))
    assert [item.content_id for item in result.results] == [submitted.content_id]
    assert container.emb_repo.get(submitted.content_id, container.embedder.model_id)


def test_ac24_text_html_transcript_and_ocr_reach_ready_and_search(
    container_factory: Callable[..., AppContainer],
) -> None:
    container = container_factory()
    service, _ = ingest_system(container)
    cases = [
        (SourceSpec(kind="text", text="은하수조약돌 관찰 기록과 보관 방법을 소개합니다."), "local", "은하수조약돌"),
        (SourceSpec(kind="url", fixture="html/article.html"), "news", "서점"),
        (SourceSpec(kind="youtube", fixture="transcript/sample.vtt"), "youtube", "성수동"),
        (SourceSpec(kind="image", ocr_text="청동나침반 전시 입장권과 관람 시간"), "local", "청동나침반"),
    ]
    ids: list[str] = []
    for source, platform, term in cases:
        result = service.submit("u_ingest", IngestRequest(source=source, platform_hint=platform, saved_at=NOW))  # type: ignore[arg-type]
        done = service.run_inline(result.job_id)
        assert done.status == "succeeded"
        bundle = container.repo.get_bundle("u_ingest", result.content_id)
        assert bundle.content.status == "ready" and not bundle.content.analysis_pending
        assert bundle.summary is not None and bundle.detail_tags is not None
        hits = container.registry.get("u_ingest").morph.search([term], HardFilter(), 20)
        assert result.content_id in [hit.content_id for hit in hits]
        search = container.search.search(SearchRequest(user_id="u_ingest", query=term, now=NOW, limit=20))
        assert result.content_id in [item.content_id for item in search.results]
        ids.append(result.content_id)
    assert len(set(ids)) == 4


def test_same_job_twice_is_idempotent_and_reanalysis_preserves_user_values(
    container_factory: Callable[..., AppContainer],
) -> None:
    container = container_factory()
    service, stages = ingest_system(container)
    submitted = service.submit(
        "u_ingest",
        IngestRequest(
            source=SourceSpec(kind="text", text="사용자 수정 보존을 검증하는 충분한 길이의 원문입니다."),
            saved_at=NOW,
        ),
    )
    assert service.run_inline(submitted.job_id).status == "succeeded"
    job = service.status("u_ingest", submitted.job_id)
    before = container.repo.get_bundle("u_ingest", submitted.content_id)

    # Simulate a crash after each stage side effect but before its advance commit.
    replay_lease = "lease_replay"
    with container.engine.begin() as conn:
        conn.execute(
            update(T.ingest_jobs)
            .where(T.ingest_jobs.c.id == job.id)
            .values(status="running", leased_by="replay", lease_id=replay_lease)
        )
    for stage in JOB_STAGES:
        with container.engine.begin() as conn:
            conn.execute(update(T.ingest_jobs).where(T.ingest_jobs.c.id == job.id).values(stage=stage))
        stages.mapping()[stage](
            job.model_copy(
                update={"stage": stage, "status": "running", "leased_by": "replay", "lease_id": replay_lease}
            )
        )
    with container.engine.begin() as conn:
        conn.execute(
            update(T.ingest_jobs)
            .where(T.ingest_jobs.c.id == job.id)
            .values(status="succeeded", leased_by=None, lease_id=None, lease_until=None)
        )
    replayed = container.repo.get_bundle("u_ingest", submitted.content_id)
    assert [(s.text, s.analysis_run_id) for s in replayed.summaries] == [
        (s.text, s.analysis_run_id) for s in before.summaries
    ]
    with container.engine.connect() as conn:
        assert conn.scalar(select(func.count()).select_from(T.analysis_runs)) == 1

    user_summary = Summary(
        id="sum_user",
        content_id=submitted.content_id,
        version=99,
        text="사용자가 직접 고친 요약",
        model="human",
        source="user",
        created_at=NOW,
    )
    modified = replayed.model_copy(
        update={
            "content": replayed.content.model_copy(update={"user_note": "사용자 메모", "hidden_tags": ["분석"]}),
            "summaries": [*replayed.summaries, user_summary],
            "tags": [*replayed.tags, Tag(name="사용자태그", source="user")],
            "detail_tags": DetailTags(
                content_id=submitted.content_id,
                ai_json=replayed.detail_tags.ai_json if replayed.detail_tags else {"schema_version": 1},
                user_patch={"topics": ["사용자주제"]},
            ),
        }
    )
    container.repo.upsert(modified)

    reanalysis = service.reanalyze("u_ingest", submitted.content_id)
    assert service.run_inline(reanalysis.job_id).status == "succeeded"
    final = container.repo.get_bundle("u_ingest", submitted.content_id)
    assert final.content.user_note == "사용자 메모" and final.content.hidden_tags == ["분석"]
    assert final.summary is not None and final.summary.source == "user" and final.summary.text == user_summary.text
    assert any(tag.source == "user" and tag.name == "사용자태그" for tag in final.tags)
    assert final.detail_tags is not None and final.detail_tags.effective()["topics"] == ["사용자주제"]
    with container.engine.connect() as conn:
        assert conn.scalar(select(func.count()).select_from(T.analysis_runs)) == 2


def test_recorded_embedding_cache_miss_publishes_reduced_index_then_fails_once(
    container_factory: Callable[..., AppContainer], tmp_path: Path
) -> None:
    container = container_factory()
    empty_recording = tmp_path / "empty-embeddings.jsonl"
    empty_recording.write_text("", encoding="utf-8")
    container.indexer.embedder = RecordedEmbedder(empty_recording, "bge-m3", 1024)
    service, _ = ingest_system(container)
    submitted = service.submit(
        "u_recorded",
        IngestRequest(source=SourceSpec(kind="text", text="녹화본밖고유문구를 검색하는 원문입니다."), saved_at=NOW),
    )

    done = service.run_inline(submitted.job_id)

    assert done.status == "failed" and done.stage == "embed"
    assert done.attempts["embed"] == 1
    assert done.last_error is not None and done.last_error["code"] == "EMBEDDING_CACHE_MISS"
    hits = container.registry.get("u_recorded").morph.search(["원문"], HardFilter(), 10)
    assert [hit.content_id for hit in hits] == [submitted.content_id]


def test_failed_reanalysis_keeps_previous_ready_content(
    container_factory: Callable[..., AppContainer],
) -> None:
    container = container_factory()
    service, stages = ingest_system(container)
    submitted = service.submit(
        "u_ingest",
        IngestRequest(
            source=SourceSpec(kind="text", text="기존 분석을 유지해야 하는 충분한 원문입니다."), saved_at=NOW
        ),
    )
    assert service.run_inline(submitted.job_id).status == "succeeded"

    class InvalidAnalyzer:
        profile_name = "invalid"

        def analyze(self, inp: object) -> tuple[AnalysisOutput, AnalysisRunMeta]:
            raise AnalysisSchemaError("invalid")

    stages.analyzer = InvalidAnalyzer()
    reanalysis = service.reanalyze("u_ingest", submitted.content_id)
    failed = service.run_inline(reanalysis.job_id)
    bundle = container.repo.get_bundle("u_ingest", submitted.content_id)

    assert failed.status == "failed"
    assert bundle.content.status == "ready" and not bundle.content.analysis_pending
    assert bundle.summary is not None


# --- T22 loop 2 M1: 재분석 실패는 재분석 직전 콘텐츠 상태로 되돌린다 ---


class RefusingAnalyzer:
    profile_name = "refusing"

    def analyze(self, inp: object) -> tuple[AnalysisOutput, AnalysisRunMeta]:
        raise LLMRefusalError("refused", {"attempts": 1})


class SchemaFailingAnalyzer:
    profile_name = "schema-failing"

    def analyze(self, inp: object) -> tuple[AnalysisOutput, AnalysisRunMeta]:
        raise AnalysisSchemaError("invalid")


def _submit_text(service: IngestService, user_id: str, text: str) -> str:
    submitted = service.submit(user_id, IngestRequest(source=SourceSpec(kind="text", text=text), saved_at=NOW))
    return submitted.job_id


def test_refused_reanalysis_of_never_analyzed_content_stays_analysis_failed(
    container_factory: Callable[..., AppContainer],
) -> None:
    container = container_factory()
    service, stages = ingest_system(container)
    stages.analyzer = RefusingAnalyzer()
    first = service.run_inline(_submit_text(service, "u_refuse", "거절당한 원문을 다시 분석하는 시나리오입니다."))
    assert first.status == "needs_review"
    before = container.repo.get_bundle("u_refuse", first.content_id).content
    assert before.status == "analysis_failed" and before.analysis_pending

    reanalysis = service.reanalyze("u_refuse", first.content_id)
    assert service.queue.get(reanalysis.job_id).stage_data["prior_content"] == {
        "status": "analysis_failed",
        "analysis_pending": True,
    }
    second = service.run_inline(reanalysis.job_id)
    after = container.repo.get_bundle("u_refuse", first.content_id)

    assert second.status == "needs_review"
    assert after.content.status == "analysis_failed" and after.content.analysis_pending
    assert after.summary is None and after.tags == []


def test_schema_failed_reanalysis_of_failed_content_stays_analysis_failed(
    container_factory: Callable[..., AppContainer],
) -> None:
    container = container_factory()
    service, stages = ingest_system(container)
    stages.analyzer = SchemaFailingAnalyzer()
    first = service.run_inline(
        _submit_text(service, "u_schema", "검증 실패가 반복되는 원문입니다. 두 번째 문장입니다.")
    )
    assert first.status == "failed"

    second = service.run_inline(service.reanalyze("u_schema", first.content_id).job_id)
    content = container.repo.get_bundle("u_schema", first.content_id).content
    assert second.status == "failed"
    assert content.status == "analysis_failed" and content.analysis_pending


def test_cache_miss_reanalysis_of_failed_content_stays_analysis_failed(
    container_factory: Callable[..., AppContainer], tmp_path: Path
) -> None:
    container = container_factory()
    empty_recording = tmp_path / "empty-embeddings.jsonl"
    empty_recording.write_text("", encoding="utf-8")
    container.indexer.embedder = RecordedEmbedder(empty_recording, "bge-m3", 1024)
    service, _ = ingest_system(container)
    first = service.run_inline(_submit_text(service, "u_miss", "녹화본밖고유문구를 다시 분석하는 원문입니다."))
    assert first.status == "failed"

    second = service.run_inline(service.reanalyze("u_miss", first.content_id).job_id)
    content = container.repo.get_bundle("u_miss", first.content_id).content
    assert second.status == "failed" and second.stage == "embed"
    assert content.status == "analysis_failed"


def _drop_prior_state(container: AppContainer, job_id: str) -> None:
    with container.engine.begin() as conn:
        conn.execute(update(T.ingest_jobs).where(T.ingest_jobs.c.id == job_id).values(stage_data="{}"))


def test_legacy_reanalyze_job_without_prior_state_uses_job_history(
    container_factory: Callable[..., AppContainer],
) -> None:
    """수정 전에 큐에 들어간 재분석 잡(stage_data에 이전 상태 없음)은 성공한 잡 이력이 있을 때만 ready로 둔다."""
    container = container_factory()
    service, stages = ingest_system(container)
    ready = service.run_inline(_submit_text(service, "u_legacy", "레거시 재분석 잡을 확인하는 원문입니다."))
    assert ready.status == "succeeded"
    stages.analyzer = SchemaFailingAnalyzer()
    never = service.run_inline(_submit_text(service, "u_legacy", "한 번도 분석되지 않은 레거시 원문입니다."))
    assert never.status == "failed"

    for job in (ready, never):
        reanalysis = service.reanalyze("u_legacy", job.content_id)
        _drop_prior_state(container, reanalysis.job_id)
        assert service.run_inline(reanalysis.job_id).status == "failed"

    assert container.repo.get_bundle("u_legacy", ready.content_id).content.status == "ready"
    assert container.repo.get_bundle("u_legacy", never.content_id).content.status == "analysis_failed"


def test_bad_youtube_source_never_analyzed_or_persisted(container_factory):
    from jupjup.ingest.fetch import RawSource

    service, stages = ingest_system(container_factory())

    class BadWatch:
        def supports(self, spec):
            return True

        def fetch(self, spec):
            return RawSource(
                kind="url",
                mime="text/html",
                body="<div>저작권 약관 개인정보처리방침 Google LLC</div>",
                final_url=spec.url,
                fetched_at=NOW,
            )

    class NeverAnalyze:
        def analyze(self, inp):
            raise AssertionError("invalid source reached analyzer")

    stages.fetcher = FetcherRouter([BadWatch()])
    stages.analyzer = NeverAnalyze()
    submitted = service.submit(
        "u_ingest", IngestRequest(source=SourceSpec(kind="url", url="https://www.youtube.com/watch?v=EbL67RhCGbY"))
    )
    result = service.run_inline(submitted.job_id)
    assert result.status == "failed"
    assert result.last_error["code"] == "SOURCE_TEXT_UNAVAILABLE"
    bundle = service.repo.get_bundle("u_ingest", submitted.content_id)
    assert bundle.content.status == "analysis_failed"
    assert not bundle.summaries and not bundle.tags and bundle.snapshot is None
    with service.repo.engine.connect() as conn:
        assert conn.scalar(select(func.count()).select_from(T.analysis_candidates)) == 0
        assert conn.scalar(select(func.count()).select_from(T.analysis_runs)) == 0


def test_legacy_http_youtube_transcript_can_reanalyze(container_factory):
    from jupjup.domain.models import Content, ContentBundle, Snapshot

    service, _stages = ingest_system(container_factory())
    service.repo.upsert(
        ContentBundle(
            content=Content(
                id="legacy-caption",
                user_id="u_ingest",
                platform="youtube",
                content_type="video",
                source_url="https://www.youtube.com/api/timedtext?v=test",
                saved_at=NOW,
            ),
            snapshot=Snapshot(
                id="legacy-caption-snapshot",
                content_id="legacy-caption",
                text="정상 자막 원문으로 재분석합니다.",
                captured_at=NOW,
                raw_meta={"source": "http", "transcript_segments": [{"start_sec": 0, "offset": 0}]},
            ),
        )
    )
    submitted = service.reanalyze("u_ingest", "legacy-caption")
    assert service.run_inline(submitted.job_id).status == "succeeded"


def test_legacy_watch_snapshot_reanalysis_is_blocked(container_factory):
    from jupjup.domain.models import Content, ContentBundle, Snapshot

    service, _stages = ingest_system(container_factory())
    service.repo.upsert(
        ContentBundle(
            content=Content(
                id="legacy-watch",
                user_id="u_ingest",
                platform="youtube",
                content_type="video",
                source_url="https://www.youtube.com/watch?v=test",
                saved_at=NOW,
            ),
            snapshot=Snapshot(
                id="legacy-watch-snapshot",
                content_id="legacy-watch",
                text="저작권 약관 개인정보처리방침 Google LLC",
                captured_at=NOW,
                raw_meta={"source": "http"},
            ),
        )
    )
    submitted = service.reanalyze("u_ingest", "legacy-watch")
    assert service.run_inline(submitted.job_id).status == "failed"
    assert not service.repo.get_bundle("u_ingest", "legacy-watch").summaries

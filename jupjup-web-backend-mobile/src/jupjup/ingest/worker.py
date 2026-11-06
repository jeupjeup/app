"""Ingest worker, retry policy, and the concrete I1-I8 stage runners."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import threading
import uuid
from collections.abc import Callable, Mapping
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, cast, runtime_checkable

from sqlalchemy import insert, update
from sqlalchemy.exc import SQLAlchemyError

from jupjup.domain.errors import (
    AnalysisSchemaError,
    EmbeddingCacheMiss,
    EmbeddingProviderError,
    ExtractionError,
    FetchError,
    IndexingError,
    JupjupError,
    LeaseLostError,
    LLMCacheMiss,
    LLMProviderError,
    LLMRefusalError,
    LLMTimeoutError,
    StorageError,
    UnsupportedSourceError,
    VisionProviderError,
)
from jupjup.domain.models import Snapshot
from jupjup.index.service import IndexingService
from jupjup.ingest.analyzer import AnalysisRunMeta, ContentAnalyzer
from jupjup.ingest.chunking import AnalysisInput, ChunkSettings, ContentMeta, chunk_for_analysis
from jupjup.ingest.extract import extract_snapshot
from jupjup.ingest.fetch import FetcherRouter, RawSource
from jupjup.ingest.jobs import JOB_STAGES, JobQueue, JobRecord, JobStage
from jupjup.ingest.schemas import AnalysisOutput
from jupjup.ingest.youtube_metadata import MetadataClassification, YoutubeMetadata, classify_metadata
from jupjup.providers.vision import ImageInput, ImageUnderstander
from jupjup.storage import tables as T
from jupjup.storage.repositories import SqlContentRepository

Clock = Callable[[], datetime]
logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(UTC)


@runtime_checkable
class StageRunner(Protocol):
    def run(self, job: JobRecord) -> None: ...


class RetryPolicy:
    """Stage limits and deterministic capped exponential backoff."""

    DEFAULT_MAX_ATTEMPTS: Mapping[JobStage, int] = {
        "fetch": 4,
        "extract": 3,
        "vision": 3,
        "chunk": 3,
        "analyze": 3,
        "persist": 3,
        "embed": 5,
        "index": 5,
    }

    def __init__(
        self,
        max_attempts: Mapping[JobStage, int] | None = None,
        *,
        base_s: float = 2.0,
        cap_s: float = 300.0,
        jitter: float = 0.2,
    ) -> None:
        merged = dict(self.DEFAULT_MAX_ATTEMPTS)
        if max_attempts:
            merged.update(max_attempts)
        if any(value < 1 for value in merged.values()) or base_s <= 0 or cap_s <= 0 or not 0 <= jitter <= 1:
            raise ValueError("재시도 설정값이 올바르지 않습니다")
        self.max_attempts: dict[JobStage, int] = merged
        self.base_s: float = base_s
        self.cap_s: float = cap_s
        self.jitter: float = jitter

    def limit(self, stage: JobStage) -> int:
        return self.max_attempts[stage]

    def delay(self, job_id: str, stage: JobStage, attempt: int) -> float:
        if attempt < 1:
            raise ValueError("attempt는 1 이상이어야 합니다")
        digest = hashlib.sha256(f"{job_id}:{stage}:{attempt}".encode()).digest()
        unit = int.from_bytes(digest[:8], "big") / ((1 << 64) - 1)
        factor = 1.0 + self.jitter * (2.0 * unit - 1.0)
        delay: float = self.base_s * (2 ** (attempt - 1)) * factor
        return min(self.cap_s, delay)


# 결정적 모델은 같은 입력에서 또 타임아웃될 가능성이 높다. analyze 단계 timeout 재시도는 1회만 한다 (설계 6.7절).
ANALYZE_TIMEOUT_RETRIES = 1


def is_retryable_error(error: JupjupError) -> bool:
    """Classify only transient transport/provider/storage/index failures as retryable."""
    status = error.details.get("status")
    if isinstance(status, int) and not isinstance(status, bool):
        return status == 429 or status >= 500
    explicit = error.details.get("retryable")
    if isinstance(explicit, bool):
        return explicit
    if isinstance(error, (EmbeddingCacheMiss, LLMCacheMiss)):
        return False
    if isinstance(error, (UnsupportedSourceError, ExtractionError, AnalysisSchemaError, LLMRefusalError)):
        return False
    return isinstance(
        error,
        (FetchError, VisionProviderError, LLMProviderError, EmbeddingProviderError, StorageError, IndexingError),
    )


class IngestWorker:
    def __init__(
        self,
        queue: JobQueue,
        stages: Mapping[JobStage, StageRunner | Callable[[JobRecord], None]],
        clock: Clock = _utc_now,
        retry: RetryPolicy | None = None,
        *,
        worker_id: str | None = None,
        lease_s: int = 300,
        concurrency: int = 2,
    ) -> None:
        if concurrency < 1:
            raise ValueError("concurrency는 1 이상이어야 합니다")
        self.queue = queue
        self.stages = dict(stages)
        self.clock = clock
        self.retry = retry or RetryPolicy()
        self.worker_id = worker_id or f"worker_{uuid.uuid4().hex[:12]}"
        self.lease_s = lease_s
        self.concurrency = concurrency

    def run_once(self) -> bool:
        job = self.queue.lease(self.worker_id, self.clock(), self.lease_s)
        if job is None:
            return False
        self._run_leased(job)
        return True

    def run_job(self, job_id: str) -> JobRecord:
        job = self.queue.lease_job(job_id, self.worker_id, self.clock(), self.lease_s)
        if job is None:
            return self.queue.get(job_id)
        self._run_leased(job)
        return self.queue.get(job_id)

    def _run_leased(self, job: JobRecord) -> None:
        try:
            while True:
                if job.lease_id is None:
                    raise LeaseLostError("잡에 lease 식별자가 없습니다", {"job_id": job.id})
                now = self.clock()
                job = self.queue.begin_stage(job.id, now, self.worker_id, job.lease_id, self.lease_s)
                lease_id = job.lease_id
                if lease_id is None:
                    raise LeaseLostError("잡에 lease 식별자가 없습니다", {"job_id": job.id})
                runner = self.stages.get(job.stage)
                if runner is None:
                    self.queue.fail(
                        job.id,
                        JupjupError("단계 실행기가 없습니다", {"stage": job.stage}),
                        now,
                        False,
                        lease_id=lease_id,
                    )
                    return
                try:
                    self._run_stage_with_heartbeat(job, runner)
                except LeaseLostError:
                    raise
                except SQLAlchemyError as exc:
                    self._handle_error(job, StorageError("SQLite 작업에 실패했습니다", {"type": type(exc).__name__}))
                    return
                except JupjupError as exc:
                    self._handle_error(job, exc)
                    return
                except Exception as exc:  # fail closed without recording source contents
                    self._handle_error(job, JupjupError("단계 실행 중 내부 오류", {"type": type(exc).__name__}))
                    return

                if self.queue.get(job.id).status != "running":
                    return
                current_index = JOB_STAGES.index(job.stage)
                next_stage = JOB_STAGES[current_index + 1] if current_index + 1 < len(JOB_STAGES) else None
                self.queue.advance(job.id, next_stage, self.clock(), lease_id=lease_id)
                if next_stage is None:
                    return
                job = self.queue.get(job.id)
        except LeaseLostError:
            # A newer lease owns recovery. The stale execution must not record any result.
            return

    def _run_stage_with_heartbeat(self, job: JobRecord, runner: StageRunner | Callable[[JobRecord], None]) -> None:
        if job.lease_id is None:
            raise LeaseLostError("잡에 lease 식별자가 없습니다", {"job_id": job.id})
        stop = threading.Event()
        lease_lost = threading.Event()
        interval = max(0.05, self.lease_s / 3)

        def heartbeat() -> None:
            while not stop.wait(interval):
                try:
                    self.queue.renew_lease(job.id, self.worker_id, job.lease_id or "", self.clock(), self.lease_s)
                except LeaseLostError:
                    lease_lost.set()
                    return
                except SQLAlchemyError as exc:
                    logger.warning(
                        "ingest lease heartbeat failed",
                        extra={"job_id": job.id, "error_type": type(exc).__name__},
                    )

        thread = threading.Thread(target=heartbeat, name=f"{self.worker_id}-heartbeat", daemon=True)
        thread.start()
        try:
            if isinstance(runner, StageRunner):
                runner.run(job)
            else:
                runner(job)
        finally:
            stop.set()
            thread.join()
        if lease_lost.is_set():
            raise LeaseLostError("단계 실행 중 잡 lease 소유권을 잃었습니다", {"job_id": job.id})

    def _handle_error(self, job: JobRecord, error: JupjupError) -> None:
        now = self.clock()
        attempt = job.attempts.get(job.stage, 0)
        retryable = is_retryable_error(error) and attempt < self.retry.limit(job.stage)
        if job.stage == "analyze" and isinstance(error, LLMTimeoutError):
            used = self._timeout_retries(job.id)
            error.details["timeout_retries"] = used
            retryable = retryable and used < ANALYZE_TIMEOUT_RETRIES
        next_run = None
        if retryable:
            next_run = now + timedelta(seconds=self.retry.delay(job.id, job.stage, attempt))
        if job.lease_id is None:
            raise LeaseLostError("잡에 lease 식별자가 없습니다", {"job_id": job.id})
        self.queue.fail(job.id, error, now, retryable, lease_id=job.lease_id, next_run_at=next_run)

    def _timeout_retries(self, job_id: str) -> int:
        """이 잡의 analyze 단계에서 이미 쓴 timeout 재시도 횟수 (잡 이벤트의 retry + LLM_TIMEOUT)."""
        return sum(
            1
            for event in self.queue.events(job_id)
            if event.stage == "analyze" and event.event == "retry" and event.detail.get("code") == LLMTimeoutError.code
        )

    def run_forever(self, stop: threading.Event) -> None:
        """Keep polling after task failures; an uncommitted stage recovers when its lease expires."""
        pending: set[Future[bool]] = set()
        with ThreadPoolExecutor(max_workers=self.concurrency, thread_name_prefix=self.worker_id) as pool:
            while not stop.is_set():
                while len(pending) < self.concurrency and not stop.is_set():
                    pending.add(pool.submit(self.run_once))
                done, pending = wait(pending, timeout=0.1, return_when=FIRST_COMPLETED)
                if not done:
                    continue
                idle = True
                for future in done:
                    try:
                        idle = not future.result() and idle
                    except Exception as exc:
                        idle = False
                        logger.warning("ingest worker task failed", extra={"error_type": type(exc).__name__})
                if idle:
                    stop.wait(0.1)


class IngestStageRunners:
    """Concrete, durable and idempotent I1-I8 implementation."""

    def __init__(
        self,
        queue: JobQueue,
        repo: SqlContentRepository,
        indexer: IndexingService,
        fetcher: FetcherRouter,
        analyzer: ContentAnalyzer,
        vision: ImageUnderstander,
        *,
        chunk_settings: ChunkSettings | None = None,
        clock: Clock = _utc_now,
    ) -> None:
        self.queue = queue
        self.repo = repo
        self.indexer = indexer
        self.fetcher = fetcher
        self.analyzer = analyzer
        self.vision = vision
        self.chunk_settings = chunk_settings or ChunkSettings()
        self.clock = clock

    def mapping(self) -> dict[JobStage, Callable[[JobRecord], None]]:
        return {
            "fetch": self.fetch,
            "extract": self.extract,
            "vision": self.vision_stage,
            "chunk": self.chunk,
            "analyze": self.analyze,
            "persist": self.persist,
            "embed": self.embed,
            "index": self.index,
        }

    def fetch(self, job: JobRecord) -> None:
        if job.source_spec is None:
            raise UnsupportedSourceError("인제스트 source_spec이 없습니다")
        raw = self.fetcher.fetch(job.source_spec)
        if "image_metadata" in job.stage_data:
            raw = raw.model_copy(update={"meta": {**raw.meta, "image": job.stage_data["image_metadata"]}})
        if isinstance(raw.body, bytes):
            body = {"encoding": "base64", "value": base64.b64encode(raw.body).decode("ascii")}
        else:
            body = {"encoding": "text", "value": raw.body}
        artifact = raw.model_dump(mode="json", exclude={"body"})
        artifact["body"] = body
        self.queue.put_artifact(job.id, "raw", artifact, self.clock(), lease_id=self._lease_id(job))

    def extract(self, job: JobRecord) -> None:
        raw_data = self._artifact(job.id, "raw")
        encoded = raw_data["body"]
        body = (
            base64.b64decode(encoded["value"], validate=True) if encoded["encoding"] == "base64" else encoded["value"]
        )
        raw = RawSource.model_validate({**raw_data, "body": body})
        if raw.meta.get("source") == "youtube_metadata":
            metadata = YoutubeMetadata.model_validate(raw.meta["youtube_metadata"])
            self.queue.put_artifact(
                job.id, "youtube_metadata", metadata.model_dump(mode="json"), self.clock(), lease_id=self._lease_id(job)
            )
            return
        bundle = self.repo.get_bundle(job.user_id, job.content_id)
        draft = extract_snapshot(raw, bundle.content.platform)
        raw_meta = dict(draft.raw_meta)
        raw_meta["language"] = draft.language
        snapshot = Snapshot(
            id=f"snap_{job.content_id}_{draft.content_hash[:16]}",
            content_id=job.content_id,
            captured_at=raw.fetched_at,
            text=draft.text,
            ocr_text=draft.ocr_text,
            raw_meta=raw_meta,
            content_hash=draft.content_hash,
            truncated=draft.truncated,
        )
        self.repo.append_snapshot(job.user_id, job.content_id, snapshot)
        self.repo.update_extracted_content(
            job.user_id,
            job.content_id,
            source_url=raw.final_url,
            title=draft.title_guess,
            author=draft.author_guess,
            published_at=draft.published_at_guess,
            now=self.clock(),
        )
        if job.result_content_id is not None:
            from jupjup.save.dedupe import CONTENT_HASH_VERSION
            from jupjup.storage.save_repositories import FingerprintRepository

            won, canonical = FingerprintRepository(self.repo.engine).claim(
                job.user_id, "content_hash", CONTENT_HASH_VERSION, snapshot.content_hash, job.content_id, self.clock()
            )
            if not won and canonical != job.content_id:
                with self.repo.engine.begin() as conn:
                    conn.exec_driver_sql("UPDATE ingest_jobs SET status=status WHERE 0")
                    self.queue._event(conn, job, self.clock(), "succeeded", {"deduplicated": True})
                    conn.execute(
                        update(T.content_fingerprints)
                        .where(
                            T.content_fingerprints.c.user_id == job.user_id,
                            T.content_fingerprints.c.content_id == job.content_id,
                        )
                        .values(content_id=canonical)
                    )
                    conn.execute(
                        update(T.contents)
                        .where(T.contents.c.id == job.content_id, T.contents.c.user_id == job.user_id)
                        .values(status="duplicate", duplicate_of_content_id=canonical)
                    )
                    conn.execute(
                        update(T.ingest_jobs)
                        .where(
                            T.ingest_jobs.c.id == job.id,
                            T.ingest_jobs.c.user_id == job.user_id,
                            T.ingest_jobs.c.lease_id == job.lease_id,
                        )
                        .values(
                            status="deduplicated",
                            stage_data="{}",
                            result_content_id=canonical,
                            lease_id=None,
                            lease_until=None,
                            completed_at=self.clock().isoformat(),
                        )
                    )
                return
        try:
            self.indexer.index_reduced(job.user_id, job.content_id)
        except JupjupError:
            raise
        except Exception as exc:
            raise IndexingError("축약 인덱싱에 실패했습니다", {"type": type(exc).__name__}) from exc

    def vision_stage(self, job: JobRecord) -> None:
        if job.source_spec is None or job.source_spec.kind != "image":
            self.queue.put_artifact(job.id, "vision", None, self.clock(), lease_id=self._lease_id(job))
            return
        description = self.vision.describe(
            ImageInput(
                path=None if job.source_spec.image_path is None else job.source_spec.image_path,
                ocr_text=job.source_spec.ocr_text,
            )
        )
        bundle = self.repo.get_bundle(job.user_id, job.content_id)
        if bundle.snapshot is None:
            raise ExtractionError("이미지 설명을 반영할 스냅샷이 없습니다")
        meta = dict(bundle.snapshot.raw_meta)
        meta["vision"] = description.model_dump(mode="json", exclude={"ocr_text"})
        content_hash = hashlib.sha256(
            (bundle.snapshot.text + "\x00" + description.ocr_text).encode("utf-8")
        ).hexdigest()
        self.repo.update_snapshot_ocr(
            job.user_id,
            job.content_id,
            bundle.snapshot.id,
            ocr_text=description.ocr_text,
            raw_meta=meta,
            content_hash=content_hash,
        )
        self.queue.put_artifact(
            job.id, "vision", description.model_dump(mode="json"), self.clock(), lease_id=self._lease_id(job)
        )

    def chunk(self, job: JobRecord) -> None:
        metadata = self.queue.artifact(job.user_id, job.id, "youtube_metadata")
        if metadata is not None:
            self.queue.put_artifact(
                job.id,
                "analysis_input",
                {
                    "source_scope": "youtube_metadata",
                    "mode": "youtube_metadata",
                    "coverage": "title_description" if metadata["description"].strip() else "title_only",
                    "metadata": metadata,
                },
                self.clock(),
                lease_id=self._lease_id(job),
            )
            return
        bundle = self.repo.get_bundle(job.user_id, job.content_id)
        if bundle.snapshot is None:
            raise ExtractionError("분석할 스냅샷이 없습니다")
        from jupjup.ingest.extract import validate_html_body
        from jupjup.ingest.youtube import has_transcript_evidence, is_legacy_watch_snapshot, unavailable

        source = bundle.snapshot.raw_meta.get("source")
        transcript = has_transcript_evidence(bundle.snapshot.raw_meta)
        if is_legacy_watch_snapshot(bundle.content.source_url, bundle.snapshot.raw_meta):
            raise unavailable("legacy_watch_snapshot")
        if source == "http" and not transcript:
            validate_html_body(bundle.snapshot.text)
        meta = ContentMeta(
            source_id=job.content_id,
            title=bundle.content.title,
            author=bundle.content.author,
            platform=bundle.content.platform,
            content_type=bundle.content.content_type,
            language=cast(str | None, bundle.snapshot.raw_meta.get("language")),
            user_note=bundle.content.user_note,
        )
        if source == "instagram_metadata":
            value = AnalysisInput(mode="single", text=bundle.snapshot.text, meta=meta)
            data = {**value.model_dump(mode="json"), "source_scope": "instagram_metadata"}
        else:
            value = chunk_for_analysis(bundle.snapshot, meta, self.chunk_settings)
            data = value.model_dump(mode="json")
        self.queue.put_artifact(
            job.id, "analysis_input", data, self.clock(), lease_id=self._lease_id(job)
        )

    def analyze(self, job: JobRecord) -> None:
        inp = self._artifact(job.id, "analysis_input")
        output: AnalysisOutput | MetadataClassification
        if inp.get("source_scope") == "youtube_metadata":
            from jupjup.ingest.analyzer import LLMContentAnalyzer

            metadata = YoutubeMetadata.model_validate(inp["metadata"])
            if isinstance(self.analyzer, LLMContentAnalyzer):
                from jupjup.ingest.youtube_salience import filter_metadata

                salience = filter_metadata(metadata, self.analyzer)
                self.queue.put_artifact(
                    job.id,
                    "youtube_salience",
                    salience.model_dump(mode="json"),
                    self.clock(),
                    lease_id=self._lease_id(job),
                )
                text = salience.primary_text()
                generated, meta = self.analyzer.analyze_youtube_metadata(
                    AnalysisInput(
                        mode="single",
                        text=text,
                        source_token_count=len(text),
                        meta=ContentMeta(
                            source_id=job.content_id,
                            title=next((b.text for b in salience.primary if b.field == "title"), None),
                            platform="youtube",
                            content_type="video",
                            language="ko",
                        ),
                    )
                )
                output = MetadataClassification(
                    classifier="local-metadata-llm-v1",
                    model=meta.model,
                    summary=generated.summary,
                    basis="title_description" if metadata.description.strip() else "title_only",
                    metadata=metadata,
                    representative_tags=generated.representative_tags,
                    detail_tags=generated.materialized_detail_tags(),
                    evidence=[],
                    salience=salience.model_dump(mode="json"),
                )
            else:
                # Keep the explicit mock evaluation baseline; unavailable live analyzers must fail.
                from jupjup.ingest.extractive import ExtractiveMockAnalyzer

                if not isinstance(self.analyzer, ExtractiveMockAnalyzer):
                    self.analyzer.analyze(AnalysisInput(mode="single", text=metadata.title))
                    raise AnalysisSchemaError("로컬 LLM 분석기가 필요합니다")
                output = classify_metadata(metadata)
                meta = AnalysisRunMeta(
                    model=output.classifier,
                    prompt_version="none",
                    attempts=1,
                    input_tokens=0,
                    output_tokens=0,
                    cost_usd=0,
                    latency_ms=0,
                    first_pass_ok=True,
                )
        elif inp.get("source_scope") == "instagram_metadata":
            from jupjup.ingest.analyzer import LLMContentAnalyzer
            from jupjup.ingest.instagram import InstagramMetadata
            from jupjup.ingest.instagram_repair import repair_instagram_output

            bundle = self.repo.get_bundle(job.user_id, job.content_id)
            assert bundle.snapshot is not None
            instagram_metadata = InstagramMetadata.model_validate(bundle.snapshot.raw_meta["instagram_metadata"])
            analysis_input = AnalysisInput.model_validate({k: v for k, v in inp.items() if k != "source_scope"})
            if isinstance(self.analyzer, LLMContentAnalyzer):
                output, meta = self.analyzer.analyze_instagram_metadata(analysis_input, instagram_metadata)
            else:
                generated, meta = self.analyzer.analyze(analysis_input)
                repaired = repair_instagram_output(generated.model_dump(), instagram_metadata)
                output = AnalysisOutput.model_validate(repaired)
        else:
            output, meta = self.analyzer.analyze(AnalysisInput.model_validate(inp))
            output = AnalysisOutput.model_validate(output.model_dump())
        self.queue.put_artifact(
            job.id,
            "validation",
            {"schema_valid": True, "repairs": meta.repairs},
            self.clock(),
            lease_id=self._lease_id(job),
        )
        self.queue.put_artifact(
            job.id,
            "analysis",
            {"output": output.model_dump(mode="json"), "meta": meta.model_dump(mode="json")},
            self.clock(),
            lease_id=self._lease_id(job),
        )

        if job.automation_level == "confirm":
            candidate_id = f"cand_{job.id}"
            with self.repo.engine.begin() as conn:
                claimed = conn.execute(
                    update(T.ingest_jobs)
                    .where(
                        T.ingest_jobs.c.id == job.id,
                        T.ingest_jobs.c.user_id == job.user_id,
                        T.ingest_jobs.c.lease_id == job.lease_id,
                        T.ingest_jobs.c.status == "running",
                    )
                    .values(
                        status="awaiting_confirmation",
                        stage_data=json.dumps({k: v for k, v in job.stage_data.items() if k.startswith("prior_")}),
                        candidate_id=candidate_id,
                        lease_id=None,
                        lease_until=None,
                        leased_by=None,
                    )
                )
                if claimed.rowcount != 1:
                    raise LeaseLostError("잡 lease 소유권을 잃었습니다")
                conn.execute(
                    insert(T.analysis_candidates).values(
                        id=candidate_id,
                        user_id=job.user_id,
                        content_id=job.content_id,
                        job_id=job.id,
                        status="pending",
                        analysis_run_id=self._run_id(job, output),
                        output_json=output.model_dump_json(),
                        meta_json=meta.model_dump_json(),
                        created_at=self.clock().isoformat(),
                    )
                )
                self.repo.persist_ai_analysis(
                    job.user_id,
                    job.content_id,
                    run_id=self._run_id(job, output),
                    job_id=job.id,
                    profile=output.classifier if isinstance(output, MetadataClassification) else job.profile,
                    output=output,
                    meta=meta,
                    analysis_input=inp,
                    accepted_at=None,
                    candidate_id=candidate_id,
                    apply_layers=False,
                    connection=conn,
                )
                conn.execute(
                    update(T.contents)
                    .where(T.contents.c.id == job.content_id, T.contents.c.user_id == job.user_id)
                    .values(
                        status="awaiting_confirmation",
                        revision=T.contents.c.revision + 1,
                        updated_at=self.clock().isoformat(),
                    )
                )
                self.queue._event(conn, job, self.clock(), "succeeded", {})

    def persist(self, job: JobRecord) -> None:
        analysis = self._artifact(job.id, "analysis")
        output = (
            MetadataClassification if analysis["output"].get("source_scope") == "youtube_metadata" else AnalysisOutput
        ).model_validate(analysis["output"])
        meta = AnalysisRunMeta.model_validate(analysis["meta"])
        inp = self._artifact(job.id, "analysis_input")
        if isinstance(output, AnalysisOutput) and inp.get("source_scope") != "instagram_metadata":
            inp = AnalysisInput.model_validate(inp).model_dump(mode="json")
        run_id = self._run_id(job, output)
        self.repo.persist_ai_analysis(
            job.user_id,
            job.content_id,
            run_id=run_id,
            job_id=job.id,
            profile=output.classifier if isinstance(output, MetadataClassification) else job.profile,
            output=output,
            meta=meta,
            analysis_input=inp,
            accepted_at=self.clock(),
            candidate_id=job.candidate_id,
            lease_id=job.lease_id,
        )

    def embed(self, job: JobRecord) -> None:
        self.indexer.embed_content(job.user_id, job.content_id)

    def index(self, job: JobRecord) -> None:
        try:
            result = self.indexer.index_content(job.user_id, job.content_id)
        except JupjupError:
            raise
        except Exception as exc:
            raise IndexingError("완전 인덱싱에 실패했습니다", {"type": type(exc).__name__}) from exc
        if result.embedding_pending:
            raise EmbeddingProviderError("완전 인덱스 임베딩이 준비되지 않았습니다")
        self._mark_ready(job)

    @staticmethod
    def _run_id(job: JobRecord, output: AnalysisOutput | MetadataClassification) -> str:
        return f"ym_{job.id}" if isinstance(output, MetadataClassification) else f"run_{job.id}"

    def _mark_ready(self, job: JobRecord) -> None:
        with self.repo.engine.begin() as conn:
            conn.execute(
                update(T.contents)
                .where(T.contents.c.id == job.content_id, T.contents.c.user_id == job.user_id)
                .values(
                    status="ready",
                    analysis_pending=0,
                    revision=T.contents.c.revision + 1,
                    updated_at=self.clock().astimezone(UTC).isoformat(),
                )
            )

    def _artifact(self, job_id: str, key: str) -> Any:
        job = self.queue.get(job_id)
        if key in job.stage_data:
            return job.stage_data[key]
        artifact = self.queue.artifact(job.user_id, job_id, key)
        if artifact is None:
            raise StorageError("이전 단계 산출물이 없습니다", {"key": key})
        return artifact

    @staticmethod
    def _lease_id(job: JobRecord) -> str:
        if job.lease_id is None:
            raise LeaseLostError("잡에 lease 식별자가 없습니다", {"job_id": job.id})
        return job.lease_id

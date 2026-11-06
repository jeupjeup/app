"""Application service for submitting, reanalyzing, and observing ingest jobs."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from jupjup.domain.errors import JupjupError, NotFoundError, StorageError
from jupjup.domain.models import Content, ContentBundle, ContentType, Platform
from jupjup.ingest.fetch import SourceSpec
from jupjup.ingest.instagram import canonical_instagram_url, instagram_candidate
from jupjup.ingest.jobs import PRIOR_CONTENT_KEY, JobQueue, JobRecord, JobStatus
from jupjup.ingest.worker import IngestWorker
from jupjup.storage.repositories import SqlContentRepository


def _now() -> datetime:
    return datetime.now(UTC)


class IngestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source: SourceSpec
    platform_hint: Platform | None = None
    content_type_hint: ContentType | None = None
    title: str | None = None
    author: str | None = None
    user_note: str | None = Field(default=None, max_length=2000)
    saved_at: datetime = Field(default_factory=_now)

    @field_validator("saved_at")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
            raise ValueError("saved_at은 timezone-aware여야 합니다")
        return value


class SubmitResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    content_id: str
    job_id: str
    status: JobStatus


class IngestService:
    def __init__(self, repo: SqlContentRepository, queue: JobQueue, worker: IngestWorker) -> None:
        if repo.engine is not queue.engine:
            raise ValueError("ContentRepository와 JobQueue는 같은 SQLite 엔진을 사용해야 합니다")
        self.repo = repo
        self.queue = queue
        self.worker = worker

    def submit(self, user_id: str, req: IngestRequest) -> SubmitResult:
        content_id = f"c_{uuid.uuid4().hex}"
        platform = req.platform_hint or self._platform(req.source)
        content_type = req.content_type_hint or self._content_type(req.source, platform)
        if req.source.kind == "url" and req.source.url and instagram_candidate(req.source.url):
            canonical = canonical_instagram_url(req.source.url)
            platform = "instagram"
            content_type = "short_video" if "/reel/" in canonical else "post"
        now = self.worker.clock()
        bundle = ContentBundle(
            content=Content(
                id=content_id,
                user_id=user_id,
                source_url=req.source.url,
                platform=platform,
                content_type=content_type,
                title=req.title,
                author=req.author,
                saved_at=req.saved_at,
                user_note=req.user_note,
                status="pending",
                analysis_pending=False,
                created_at=now,
                updated_at=now,
            )
        )
        try:
            with self.repo.engine.begin() as conn:
                self.repo.upsert_in_transaction(conn, bundle)
                job_id = self.queue.enqueue_in_transaction(
                    conn,
                    content_id,
                    user_id,
                    "ingest",
                    10,
                    source_spec=req.source,
                    now=now,
                )
        except JupjupError:
            raise
        except Exception as exc:
            raise StorageError("콘텐츠와 인제스트 잡을 저장하지 못했습니다", {"type": type(exc).__name__}) from exc
        return SubmitResult(content_id=content_id, job_id=job_id, status="queued")

    def reanalyze(self, user_id: str, content_id: str, profile: str = "default") -> SubmitResult:
        bundle = self.repo.get_bundle(user_id, content_id)
        if bundle.snapshot is None:
            raise NotFoundError("재분석할 스냅샷을 찾을 수 없습니다", {"content_id": content_id})
        now = self.worker.clock()
        prior = {"status": bundle.content.status, "analysis_pending": bundle.content.analysis_pending}
        pending = bundle.model_copy(
            update={"content": bundle.content.model_copy(update={"status": "pending", "updated_at": now})}
        )
        try:
            with self.repo.engine.begin() as conn:
                self.repo.upsert_in_transaction(conn, pending)
                job_id = self.queue.enqueue_in_transaction(
                    conn,
                    content_id,
                    user_id,
                    "reanalyze",
                    1,
                    profile,
                    initial_stage="chunk",
                    now=now,
                    stage_data={PRIOR_CONTENT_KEY: prior},
                )
        except JupjupError:
            raise
        except Exception as exc:
            raise StorageError("재분석 잡을 저장하지 못했습니다", {"type": type(exc).__name__}) from exc
        return SubmitResult(content_id=content_id, job_id=job_id, status="queued")

    def run_inline(self, job_id: str) -> JobRecord:
        return self.worker.run_job(job_id)

    def status(self, user_id: str, job_id: str) -> JobRecord:
        job = self.queue.get(job_id)
        if job.user_id != user_id:
            raise NotFoundError("인제스트 잡을 찾을 수 없습니다", {"job_id": job_id})
        return job

    @staticmethod
    def _platform(source: SourceSpec) -> Platform:
        if source.kind == "youtube":
            return "youtube"
        if source.kind in ("text", "image"):
            return "local"
        return "web"

    @staticmethod
    def _content_type(source: SourceSpec, platform: Platform) -> ContentType:
        if source.kind == "image":
            return "image"
        if source.kind == "youtube" or platform == "youtube":
            return "video"
        if source.kind == "text":
            return "message"
        if platform in ("news", "blog"):
            return "article"
        return "webpage"

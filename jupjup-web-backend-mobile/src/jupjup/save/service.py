"""Transactional public content commands."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import Connection, delete, insert, select, update

from jupjup.api.errors import ApiError
from jupjup.domain.models import Content
from jupjup.ingest.fetch import SourceSpec
from jupjup.ingest.service import IngestService
from jupjup.ingest.youtube import is_youtube_url
from jupjup.save.dedupe import URL_NORMALIZATION_VERSION, fingerprint
from jupjup.save.dto import CreateContent, ReanalyzeRequest
from jupjup.save.recovery import capture_ai
from jupjup.storage import tables as T
from jupjup.storage.save_repositories import canonical_json, canonical_request_hash


@dataclass(frozen=True)
class CoreCreateOutcome:
    content_id: str
    job_id: str | None
    deduplicated: bool
    status: str


class ContentCommandService:
    def __init__(self, ingest: IngestService, profile: str = "mock") -> None:
        self.ingest = ingest
        self.profile = profile
        self.engine = ingest.repo.engine

    def create_in_transaction(
        self, conn: Connection, user_id: str, body: CreateContent, now: datetime
    ) -> CoreCreateOutcome:
        level = body.automation_level or "auto"
        at = now.isoformat()
        url = body.source.url if body.source.kind == "url" else None
        existing = None
        if url:
            existing = conn.scalar(
                select(T.content_fingerprints.c.content_id).where(
                    T.content_fingerprints.c.user_id == user_id,
                    T.content_fingerprints.c.kind == "normalized_url",
                    T.content_fingerprints.c.version == URL_NORMALIZATION_VERSION,
                    T.content_fingerprints.c.fingerprint == fingerprint(url),
                )
            )
        if existing:
            from jupjup.storage.bridge_sql import release_bridge_hide

            release_bridge_hide(conn, user_id, existing)
            status = conn.scalar(
                select(T.contents.c.status).where(T.contents.c.id == existing, T.contents.c.user_id == user_id)
            )
            assert status is not None
            return CoreCreateOutcome(existing, None, True, status)
        content_id = f"c_{uuid.uuid4().hex}"
        source = SourceSpec.model_validate(body.source.model_dump(exclude={"image"}))
        platform = body.platform_hint or self.ingest._platform(source)
        if url and body.platform_hint is None:
            host = urlsplit(url).hostname or ""
            if host in {"www.instagram.com", "instagram.com"}:
                platform = "instagram"
            elif host in {"youtube.com", "www.youtube.com", "youtu.be"}:
                platform = "youtube"
            elif host in {"x.com", "www.x.com", "twitter.com"}:
                platform = "x"
        content_type = body.content_type_hint or self.ingest._content_type(source, platform)
        if body.content_type_hint is None and platform in ("instagram", "x"):
            content_type = "short_video" if url and "/reel/" in url else "post"
        if url and urlsplit(url).hostname == "www.instagram.com":
            platform = "instagram"
            content_type = "short_video" if urlsplit(url).path.startswith("/reel/") else "post"
        content = Content(
            id=content_id,
            user_id=user_id,
            source_url=url,
            normalized_url=url,
            source_kind=body.source.kind,
            platform=platform,
            content_type=content_type,
            title=body.title,
            author=body.author,
            user_note=body.user_note,
            automation_level=level,
            saved_at=now,
            created_at=now,
            updated_at=now,
            status="pending",
        )
        # New rows only: never use bundle upsert on existing content.
        self.ingest.repo.create_in_transaction(conn, content)
        job_id = self.ingest.queue.enqueue_in_transaction(
            conn,
            content_id,
            user_id,
            "ingest",
            10,
            self.profile,
            source_spec=source,
            now=now,
            stage_data={"image_metadata": body.source.image.model_dump(mode="json", exclude_none=True)}
            if body.source.kind == "image" and body.source.image is not None
            else None,
        )
        if url:
            conn.execute(
                insert(T.content_fingerprints).values(
                    user_id=user_id,
                    kind="normalized_url",
                    version=URL_NORMALIZATION_VERSION,
                    fingerprint=fingerprint(url),
                    content_id=content_id,
                    created_at=at,
                )
            )
        conn.execute(
            update(T.ingest_jobs)
            .where(T.ingest_jobs.c.id == job_id, T.ingest_jobs.c.user_id == user_id)
            .values(automation_level=level, result_content_id=content_id)
        )
        return CoreCreateOutcome(content_id, job_id, False, "pending")

    def submit(
        self, user_id: str, body: CreateContent | ReanalyzeRequest, key: str | None, content_id: str | None = None
    ) -> tuple[int, dict[str, Any], bool]:
        if key is None:
            raise ApiError(400, "MISSING_IDEMPOTENCY_KEY", "Idempotency-Key가 필요합니다")
        if not 1 <= len(key) <= 128 or any(ord(c) < 32 or ord(c) > 126 for c in key):
            raise ApiError(400, "INVALID_IDEMPOTENCY_KEY", "Idempotency-Key 형식이 올바르지 않습니다")
        now = self.ingest.worker.clock()
        at = now.isoformat()
        operation = "POST /v1/contents" if content_id is None else "POST /v1/contents/{content_id}:reanalyze"
        key_hash = fingerprint(key)
        request_body = body.model_dump(mode="json")
        if isinstance(body, ReanalyzeRequest) and body.mode == "snapshot":
            request_body.pop("mode")  # Preserve pre-metadata idempotency hashes for existing clients.
        request_hash = canonical_request_hash({"path": {"content_id": content_id}, "body": request_body})
        with self.engine.begin() as conn:
            # Acquire SQLite's writer lock before looking up reservations or fingerprints.
            conn.exec_driver_sql("UPDATE idempotency_keys SET state=state WHERE 0")
            conn.execute(delete(T.idempotency_keys).where(T.idempotency_keys.c.expires_at <= at))
            old = (
                conn.execute(
                    select(T.idempotency_keys).where(
                        T.idempotency_keys.c.user_id == user_id,
                        T.idempotency_keys.c.operation == operation,
                        T.idempotency_keys.c.key_hash == key_hash,
                    )
                )
                .mappings()
                .first()
            )
            if old is not None:
                if old["request_hash"] != request_hash:
                    raise ApiError(409, "IDEMPOTENCY_CONFLICT", "같은 키에 다른 요청을 보낼 수 없습니다")
                return old["response_status"], json.loads(old["response_json"]), True
            if isinstance(body, CreateContent):
                outcome = self.create_in_transaction(conn, user_id, body, now)
                content_id, job_id = outcome.content_id, outcome.job_id
                if outcome.deduplicated:
                    row = (
                        conn.execute(
                            select(T.contents).where(T.contents.c.id == content_id, T.contents.c.user_id == user_id)
                        )
                        .mappings()
                        .one()
                    )
                    status = 200
                    response = dict(
                        content_id=content_id,
                        job_id=None,
                        status=outcome.status,
                        automation_level=row["automation_level"],
                        deduplicated=True,
                        duplicate_reason="normalized_url",
                        result_content_id=content_id,
                        warnings=["user_note_not_applied"] if body.user_note else [],
                    )
                else:
                    status = 202
                    response = dict(
                        content_id=content_id,
                        job_id=job_id,
                        status="queued",
                        automation_level=body.automation_level,
                        deduplicated=False,
                        result_content_id=content_id,
                    )
            else:
                assert content_id is not None
                owned_row = (
                    conn.execute(
                        select(T.contents).where(T.contents.c.id == content_id, T.contents.c.user_id == user_id)
                    )
                    .mappings()
                    .first()
                )
                if owned_row is None:
                    from jupjup.domain.errors import NotFoundError

                    raise NotFoundError("저장물을 찾을 수 없어요.")
                bundle = self.ingest.repo._assemble(conn, [dict(owned_row)])[content_id]
                refresh_metadata = body.mode == "youtube_metadata"
                if refresh_metadata and not is_youtube_url(bundle.content.source_url):
                    raise ApiError(422, "INVALID_SOURCE", "YouTube 공개 URL에만 사용할 수 있어요")
                if bundle.snapshot is None and not refresh_metadata:
                    raise ApiError(409, "INVALID_CONTENT_STATE", "재분석할 스냅샷이 없습니다")
                active = conn.scalar(
                    select(T.ingest_jobs.c.id).where(
                        T.ingest_jobs.c.user_id == user_id,
                        T.ingest_jobs.c.content_id == content_id,
                        T.ingest_jobs.c.status.in_(["queued", "running", "retry_wait", "awaiting_confirmation"]),
                    )
                )
                if active:
                    raise ApiError(409, "CONTENT_BUSY", "활성 잡이 있습니다")
                if bundle.content.status == "duplicate":
                    raise ApiError(409, "INVALID_CONTENT_STATE", "중복 저장물입니다")
                level = body.automation_level or bundle.content.automation_level
                conn.execute(
                    update(T.analysis_candidates)
                    .where(T.analysis_candidates.c.user_id == user_id, T.analysis_candidates.c.content_id == content_id)
                    .values(status="superseded")
                )
                prior = {"status": bundle.content.status, "analysis_pending": bundle.content.analysis_pending}
                job_id = self.ingest.queue.enqueue_in_transaction(
                    conn,
                    content_id,
                    user_id,
                    "reanalyze",
                    1,
                    self.profile,
                    initial_stage="fetch" if refresh_metadata else "chunk",
                    source_spec=SourceSpec(kind="youtube", url=bundle.content.source_url, youtube_metadata_only=True)
                    if refresh_metadata
                    else None,
                    now=now,
                    stage_data={"prior_content": prior, "prior_ai": capture_ai(conn, content_id)},
                )
                conn.execute(
                    update(T.contents)
                    .where(T.contents.c.id == content_id, T.contents.c.user_id == user_id)
                    .values(status="pending", automation_level=level, revision=T.contents.c.revision + 1, updated_at=at)
                )
                conn.execute(
                    update(T.ingest_jobs)
                    .where(T.ingest_jobs.c.id == job_id, T.ingest_jobs.c.user_id == user_id)
                    .values(automation_level=level, result_content_id=content_id)
                )
                status = 202
                response = dict(
                    content_id=content_id,
                    job_id=job_id,
                    status="queued",
                    automation_level=level,
                    deduplicated=False,
                    result_content_id=content_id,
                )
            from datetime import timedelta

            conn.execute(
                insert(T.idempotency_keys).values(
                    user_id=user_id,
                    operation=operation,
                    key_hash=key_hash,
                    request_hash=request_hash,
                    state="completed",
                    response_status=status,
                    response_json=canonical_json(response),
                    resource_id=response["content_id"],
                    job_id=response["job_id"],
                    created_at=at,
                    expires_at=(now + timedelta(hours=24)).isoformat(),
                )
            )
        return status, response, False

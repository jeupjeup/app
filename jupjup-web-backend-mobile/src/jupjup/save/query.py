"""Owned content views and signed keyset pagination."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import Field, field_validator
from sqlalchemy import and_, exists, func, or_, select, text

from jupjup.collections.service import collection_ids, owned_collection
from jupjup.domain.models import (
    ContentBundle,
    ContentStatus,
    ContentType,
    Platform,
    Summary,
    merge_patch,
    normalize_tag_name,
    require_aware,
)
from jupjup.ingest.youtube import is_legacy_watch_snapshot
from jupjup.save.cursor import cursor_scope, decode_cursor, encode_cursor
from jupjup.save.dto import StrictModel
from jupjup.storage import tables as T
from jupjup.storage.instant import utc_instant
from jupjup.storage.repositories import SqlContentRepository


class ContentListQuery(StrictModel):
    platform: list[Platform] = Field(default_factory=list, max_length=10)
    content_type: list[ContentType] = Field(default_factory=list, max_length=10)
    status: list[ContentStatus] = Field(default_factory=list, max_length=10)
    tag: list[str] = Field(default_factory=list, max_length=10)
    hidden: Literal["false", "true", "all"] = "false"
    saved_from: datetime | None = None
    saved_to: datetime | None = None
    sort: Literal["saved_at", "updated_at"] = "saved_at"
    order: Literal["asc", "desc"] = "desc"
    limit: int = Field(default=20, ge=1, le=100)
    collection_id: str | None = Field(default=None, min_length=1, max_length=200)
    cursor: str | None = Field(default=None, max_length=8192)

    @field_validator("saved_from", "saved_to")
    @classmethod
    def aware(cls, value: datetime | None) -> datetime | None:
        return require_aware(value) if value else value


def detail_run_id(bundle: ContentBundle) -> str | None:
    return bundle.detail_tags.analysis_run_id if bundle.detail_tags else None


def visible_analysis(bundle: ContentBundle, metadata: bool = False) -> tuple[bool, Summary | None, list[str]]:
    """Project only user layers for an invalid watch snapshot; never mutate the bundle."""
    legacy_watch = bool(
        bundle.snapshot and is_legacy_watch_snapshot(bundle.content.source_url, bundle.snapshot.raw_meta)
    )
    user = [s for s in bundle.summaries if s.source == "user"]
    metadata_ai = [
        s
        for s in bundle.summaries
        if metadata and bundle.detail_tags and s.analysis_run_id == bundle.detail_tags.analysis_run_id
    ]
    summary = (
        (max(user or metadata_ai, key=lambda s: (s.version, s.created_at)) if user or metadata_ai else None)
        if legacy_watch or metadata
        else bundle.summary
    )
    tags = [t.name for t in bundle.effective_tags() if not legacy_watch or metadata or t.source == "user"]
    return legacy_watch, summary, tags


_visible_analysis = visible_analysis

class ContentQueryService:
    def __init__(self, repo: SqlContentRepository, secret: str) -> None:
        self.repo = repo
        self.secret = secret

    def get(self, user_id: str, content_id: str) -> dict[str, Any]:
        bundle = self.repo.get_bundle(user_id, content_id)
        c = bundle.content
        if c.status == "duplicate":
            return dict(
                id=c.id,
                canonical_id=c.duplicate_of_content_id,
                status="duplicate",
                revision=c.revision,
                collection_ids=self._collection_ids(user_id, content_id),
            )
        ai = [s for s in bundle.summaries if s.source == "ai"]
        user = [s for s in bundle.summaries if s.source == "user"]
        metadata = self.repo.metadata_for(bundle)
        if metadata is not None:
            ai = [
                s
                for s in ai
                if metadata.classifier == "local-metadata-llm-v1" and detail_run_id(bundle) == s.analysis_run_id
            ]
        legacy_watch, summary, effective_tags = visible_analysis(bundle, metadata is not None)
        detail = bundle.detail_tags
        source_reason = None
        if legacy_watch:
            source_reason = "legacy_watch_snapshot"
        elif bundle.snapshot is None:
            source_reason = "missing_snapshot"
        elif not (bundle.snapshot.text or bundle.snapshot.ocr_text or "").strip():
            source_reason = "empty_snapshot"
        effective_detail = detail.effective() if detail else {"schema_version": 1}
        if legacy_watch and detail and metadata is None:
            effective_detail = merge_patch({"schema_version": 1}, detail.user_patch or {})
        with self.repo.engine.connect() as conn:
            job = (
                conn.execute(
                    select(T.ingest_jobs)
                    .where(T.ingest_jobs.c.user_id == user_id, T.ingest_jobs.c.content_id == content_id)
                    .order_by(T.ingest_jobs.c.created_at.desc(), T.ingest_jobs.c.id.desc())
                    .limit(1)
                )
                .mappings()
                .first()
            )
            candidate = (
                conn.execute(
                    select(T.analysis_candidates).where(
                        T.analysis_candidates.c.user_id == user_id,
                        T.analysis_candidates.c.content_id == content_id,
                        T.analysis_candidates.c.status == "pending",
                    )
                )
                .mappings()
                .first()
            )
        with self.repo.engine.connect() as conn:
            memberships = collection_ids(conn, user_id, content_id)
        return dict(
            collection_ids=memberships,
            id=c.id,
            canonical_id=c.duplicate_of_content_id or c.id,
            revision=c.revision,
            status=c.status,
            hidden=c.is_hidden,
            source=dict(kind=c.source_kind, url=c.source_url, original_status=c.original_status),
            platform=c.platform,
            content_type=c.content_type,
            title=c.title or (metadata.metadata.title if metadata else None),
            author=c.author,
            published_at=c.published_at,
            saved_at=c.saved_at,
            user_note=c.user_note,
            summary=dict(
                model=max(ai, key=lambda s: s.version).model if ai else None,
                effective=summary.text if summary else None,
                source=summary.source if summary else None,
                is_mock=bool(summary and summary.source == "ai" and (summary.model or "").startswith("mock")),
                ai=max(ai, key=lambda s: s.version).text if ai and (not legacy_watch or metadata is not None) else None,
                user=max(user, key=lambda s: s.version).text if user else None,
            ),
            representative_tags=dict(
                effective=effective_tags,
                ai=[t.name for t in bundle.tags if t.source == "ai"] if not legacy_watch or metadata else [],
                user=[t.name for t in bundle.tags if t.source == "user"],
                hidden_ai=c.hidden_tags,
            ),
            detail_tags=dict(
                effective=effective_detail,
                ai=detail.ai_json if detail and (not legacy_watch or metadata) else {"schema_version": 1},
                user_patch=detail.user_patch if detail else None,
            ),
            snapshot=bundle.snapshot.model_dump(mode="json", exclude={"raw_meta", "content_id"})
            if bundle.snapshot
            else None,
            analysis=dict(
                metadata=metadata.model_dump(mode="json") if metadata else None,
                source_text_available=source_reason is None,
                source_text_reason=source_reason,
                automation_level=c.automation_level,
                analysis_pending=c.analysis_pending,
                latest_job_id=job["id"] if job else None,
                candidate=dict(
                    id=candidate["id"], **json.loads(candidate["output_json"]), meta=json.loads(candidate["meta_json"])
                )
                if candidate
                and (not legacy_watch or json.loads(candidate["output_json"]).get("source_scope") == "youtube_metadata")
                else None,
            ),
            created_at=c.created_at,
            updated_at=c.updated_at,
        )

    def _collection_ids(self, user_id: str, content_id: str) -> list[str]:
        with self.repo.engine.connect() as conn:
            return collection_ids(conn, user_id, content_id)

    def list(self, user_id: str, query: ContentListQuery) -> dict[str, Any]:
        filters = query.model_dump(mode="json", exclude={"cursor", "limit"})
        if query.collection_id is None:
            filters.pop("collection_id")
        else:
            with self.repo.engine.connect() as conn:
                owned_collection(conn, user_id, query.collection_id)
        scope = cursor_scope(user_id, filters)
        column = T.contents.c[query.sort + "_instant"]
        conditions = [T.contents.c.user_id == user_id]
        if query.collection_id is not None:
            conditions.append(
                T.contents.c.id.in_(
                    text(
                        "SELECT content_id FROM collection_contents WHERE collection_id=:collection AND user_id=:owner"
                    ).bindparams(collection=query.collection_id, owner=user_id)
                )
            )
        for name in ("platform", "content_type", "status"):
            values = getattr(query, name)
            if values:
                conditions.append(T.contents.c[name].in_(values))
        if "duplicate" not in query.status:
            conditions.append(T.contents.c.status != "duplicate")
        if query.hidden != "all":
            conditions.append(T.contents.c.is_hidden == int(query.hidden == "true"))
        if query.saved_from:
            conditions.append(T.contents.c.saved_at_instant >= query.saved_from.astimezone(UTC).isoformat())
        if query.saved_to:
            conditions.append(T.contents.c.saved_at_instant < query.saved_to.astimezone(UTC).isoformat())
        if query.cursor:
            value, content_id = decode_cursor(query.cursor, scope, self.secret)
            compare = column < value if query.order == "desc" else column > value
            tie = T.contents.c.id < content_id if query.order == "desc" else T.contents.c.id > content_id
            conditions.append(or_(compare, and_(column == value, tie)))
        for tag in query.tag:
            hidden = func.json_each(T.contents.c.hidden_tags).table_valued("value").alias()
            is_hidden = exists(select(1).select_from(hidden).where(hidden.c.value == T.tags.c.name)).correlate(
                T.contents, T.tags
            )
            conditions.append(
                exists(
                    select(1)
                    .select_from(T.tags)
                    .where(
                        T.tags.c.content_id == T.contents.c.id,
                        T.tags.c.name == normalize_tag_name(tag),
                        or_(T.tags.c.source == "user", and_(T.tags.c.source == "ai", ~is_hidden)),
                    )
                )
            )
        ordering = [column.desc(), T.contents.c.id.desc()] if query.order == "desc" else [column, T.contents.c.id]
        # Effective tag filtering and the keyset boundary are applied before the SQL LIMIT.
        items: list[dict[str, Any]] = []
        with self.repo.engine.connect() as conn:
            rows = (
                conn.execute(select(T.contents).where(*conditions).order_by(*ordering).limit(query.limit + 1))
                .mappings()
                .all()
            )
        for row in rows:
            bundle = self.repo.get_bundle(user_id, row["id"])
            names = [t.name for t in bundle.effective_tags()]
            if not all(normalize_tag_name(tag) in names for tag in query.tag):
                continue
            _legacy_watch, summary, visible_names = visible_analysis(
                bundle, self.repo.metadata_for(bundle) is not None
            )
            items.append(
                dict(
                    collection_ids=self._collection_ids(user_id, row["id"]),
                    id=row["id"],
                    revision=row["revision"],
                    status=row["status"],
                    hidden=bool(row["is_hidden"]),
                    title=row["title"],
                    platform=row["platform"],
                    content_type=row["content_type"],
                    summary=summary.text if summary else None,
                    summary_is_mock=bool(
                        summary and summary.source == "ai" and (summary.model or "").startswith("mock")
                    ),
                    representative_tags=visible_names,
                    saved_at=row["saved_at"],
                    updated_at=row["updated_at"],
                    source_url=row["source_url"],
                    original_available=row["original_status"] != "deleted",
                    analysis_pending=bool(row["analysis_pending"]),
                )
            )
            if len(items) > query.limit:
                break
        has_more = len(items) > query.limit
        items = items[: query.limit]
        token = None
        if has_more:
            token = encode_cursor(
                dict(version=1, scope=scope, sort_value=utc_instant(items[-1][query.sort]), id=items[-1]["id"]),
                self.secret,
            )
        return dict(items=items, has_more=has_more, next_cursor=token)

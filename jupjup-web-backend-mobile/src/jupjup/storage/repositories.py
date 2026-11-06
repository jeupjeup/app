"""저장소 계층 (설계서 5.8.7절). 모든 조회는 user_id로 범위를 좁힌다."""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from contextlib import nullcontext
from datetime import UTC, datetime
from typing import Any, Protocol

import numpy as np
from sqlalchemy import Connection, Engine, case, delete, func, insert, select, update

from jupjup.domain.errors import AnalysisSchemaError, ContentValidationError, NotFoundError
from jupjup.domain.models import (
    Content,
    ContentBundle,
    DetailTags,
    Snapshot,
    StoredEmbedding,
    Summary,
    Tag,
    effective_tags,
)
from jupjup.ingest.youtube_metadata import MetadataClassification
from jupjup.storage import tables as T


class ContentRepository(Protocol):
    def upsert(self, bundle: ContentBundle) -> None: ...
    def upsert_many(self, bundles: Sequence[ContentBundle], *, replace_users: Sequence[str] = ()) -> None: ...
    def upsert_many_with_embeddings(
        self,
        bundles: Sequence[ContentBundle],
        embedding_updates: Sequence[tuple[str, str, Sequence[StoredEmbedding]]],
    ) -> None: ...
    def get_bundle(self, user_id: str, content_id: str) -> ContentBundle: ...
    def metadata_for(self, bundle: ContentBundle) -> MetadataClassification | None: ...
    def get_bundles(self, user_id: str, ids: Sequence[str]) -> dict[str, ContentBundle]: ...
    def iter_bundles(self, user_id: str | None = None) -> Iterator[ContentBundle]: ...
    def delete(self, user_id: str, content_id: str) -> None: ...
    def count(self, user_id: str | None = None) -> int: ...
    def user_ids(self) -> list[str]: ...
    def index_fingerprint(self, user_id: str) -> tuple[Any, ...]: ...


class EmbeddingRepository(Protocol):
    def get(self, content_id: str, model_id: str) -> list[StoredEmbedding]: ...
    def replace(self, content_id: str, model_id: str, rows: Sequence[StoredEmbedding]) -> None: ...


def _iso(dt: datetime | None) -> str | None:
    return None if dt is None else dt.isoformat()


def _dt(s: str | None) -> datetime | None:
    return None if s is None else datetime.fromisoformat(s)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class SqlContentRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def metadata_for(self, bundle: ContentBundle) -> MetadataClassification | None:
        with self.engine.connect() as conn:
            return self.metadata_in(conn, bundle)

    def metadata_in(self, conn: Connection, bundle: ContentBundle) -> MetadataClassification | None:
        run_id = bundle.detail_tags.analysis_run_id if bundle.detail_tags else None
        if not run_id or not run_id.startswith("ym_"):
            return None
        value = conn.scalar(
            select(T.analysis_runs.c.output_json).where(
                T.analysis_runs.c.id == run_id,
                T.analysis_runs.c.content_id == bundle.content.id,
                T.analysis_runs.c.accepted_at.is_not(None),
            )
        )
        return MetadataClassification.model_validate_json(value) if value else None

    # ------------------------------------------------------------------ 쓰기
    def upsert(self, bundle: ContentBundle) -> None:
        self.upsert_many([bundle])

    def upsert_many(self, bundles: Sequence[ContentBundle], *, replace_users: Sequence[str] = ()) -> None:
        """한 트랜잭션. 실패하면 전부 롤백된다. replace_users의 기존 저장물은 먼저 지운다."""
        with self.engine.begin() as conn:
            for uid in replace_users:
                conn.execute(delete(T.contents).where(T.contents.c.user_id == uid))
            for b in bundles:
                self._upsert(conn, b)

    def upsert_many_with_embeddings(
        self,
        bundles: Sequence[ContentBundle],
        embedding_updates: Sequence[tuple[str, str, Sequence[StoredEmbedding]]],
    ) -> None:
        """Atomically persist content bundles and their prepared embedding cache rows."""
        with self.engine.begin() as conn:
            for bundle in bundles:
                self._upsert(conn, bundle)
            for content_id, model_id, rows in embedding_updates:
                _replace_embeddings(conn, content_id, model_id, rows)

    def _upsert(self, conn: Connection, b: ContentBundle) -> None:
        c = b.content
        existing = conn.execute(
            select(T.contents.c.user_id, T.contents.c.created_at).where(T.contents.c.id == c.id)
        ).first()
        if existing is not None and existing.user_id != c.user_id:
            # 다른 사용자의 저장물을 덮어쓰지 못하게 막는다 (격리)
            raise ContentValidationError("다른 사용자의 저장물 id입니다", {"id": c.id})
        now = _now_iso()
        created = existing.created_at if existing is not None else _iso(c.created_at) or now
        cid = c.id
        for tbl in (T.snapshots, T.summaries, T.tags, T.detail_tags):
            conn.execute(delete(tbl).where(tbl.c.content_id == cid))
        row = {
            "id": cid,
            "user_id": c.user_id,
            "source_url": c.source_url,
            "source_kind": c.source_kind,
            "normalized_url": c.normalized_url,
            "platform": c.platform,
            "content_type": c.content_type,
            "title": c.title,
            "author": c.author,
            "published_at": _iso(c.published_at),
            "saved_at": _iso(c.saved_at),
            "original_status": c.original_status,
            "user_note": c.user_note,
            "hidden_tags": json.dumps(c.hidden_tags, ensure_ascii=False),
            "status": c.status,
            "analysis_pending": int(c.analysis_pending),
            "automation_level": c.automation_level,
            "is_hidden": int(c.is_hidden),
            "revision": c.revision,
            "duplicate_of_content_id": c.duplicate_of_content_id,
            "created_at": created,
            "updated_at": now,
        }
        if existing is None:
            conn.execute(insert(T.contents).values(**row))
        else:
            conn.execute(T.contents.update().where(T.contents.c.id == cid).values(**row))
        if b.snapshot is not None:
            s = b.snapshot
            conn.execute(
                insert(T.snapshots).values(
                    id=s.id,
                    content_id=cid,
                    captured_at=_iso(s.captured_at),
                    text=s.text,
                    ocr_text=s.ocr_text,
                    raw_meta=json.dumps(s.raw_meta, ensure_ascii=False),
                    content_hash=s.content_hash,
                    truncated=int(s.truncated),
                )
            )
        for sm in b.summaries:
            conn.execute(
                insert(T.summaries).values(
                    id=sm.id,
                    content_id=cid,
                    version=sm.version,
                    text=sm.text,
                    model=sm.model,
                    source=sm.source,
                    analysis_run_id=sm.analysis_run_id,
                    created_at=_iso(sm.created_at),
                )
            )
        for pos, t in enumerate(b.tags):
            conn.execute(
                insert(T.tags).values(
                    content_id=cid,
                    name=t.name,
                    source=t.source,
                    confidence=t.confidence,
                    position=pos,
                    created_at=now,
                )
            )
        if b.detail_tags is not None:
            d = b.detail_tags
            conn.execute(
                insert(T.detail_tags).values(
                    content_id=cid,
                    ai_json=json.dumps(d.ai_json, ensure_ascii=False),
                    user_patch=None if d.user_patch is None else json.dumps(d.user_patch, ensure_ascii=False),
                    schema_version=d.schema_version,
                    analysis_run_id=d.analysis_run_id,
                    updated_at=now,
                )
            )

    def create_in_transaction(self, conn: Connection, content: Content) -> None:
        """Insert a new content row without touching any existing child rows."""
        values = content.model_dump(mode="json")
        values["hidden_tags"] = json.dumps(content.hidden_tags, ensure_ascii=False)
        for field in ("saved_at", "published_at", "created_at", "updated_at"):
            values[field] = _iso(getattr(content, field))
        values["created_at"] = _iso(content.created_at) or _now_iso()
        values["updated_at"] = _iso(content.updated_at) or _now_iso()
        conn.execute(insert(T.contents).values(**values))

    def upsert_in_transaction(self, conn: Connection, bundle: ContentBundle) -> None:
        """Write a bundle on a caller-owned transaction (ingest submit and I6)."""
        self._upsert(conn, bundle)

    def append_snapshot(self, user_id: str, content_id: str, snapshot: Snapshot) -> None:
        """Append a captured snapshot without replacing summaries or user layers."""
        if snapshot.content_id != content_id:
            raise ContentValidationError("snapshot.content_id 불일치")
        with self.engine.begin() as conn:
            owned = conn.scalar(
                select(func.count())
                .select_from(T.contents)
                .where(T.contents.c.id == content_id, T.contents.c.user_id == user_id)
            )
            if not owned:
                raise NotFoundError("저장물을 찾을 수 없어요.", {"content_id": content_id})
            exists = conn.scalar(select(func.count()).select_from(T.snapshots).where(T.snapshots.c.id == snapshot.id))
            if not exists:
                conn.execute(
                    insert(T.snapshots).values(
                        id=snapshot.id,
                        content_id=content_id,
                        captured_at=_iso(snapshot.captured_at),
                        text=snapshot.text,
                        ocr_text=snapshot.ocr_text,
                        raw_meta=json.dumps(snapshot.raw_meta, ensure_ascii=False),
                        content_hash=snapshot.content_hash,
                        truncated=int(snapshot.truncated),
                    )
                )

    def update_extracted_content(
        self,
        user_id: str,
        content_id: str,
        *,
        source_url: str | None,
        title: str | None,
        author: str | None,
        published_at: datetime | None,
        now: datetime,
    ) -> None:
        """Update only extraction-owned metadata and state."""
        with self.engine.begin() as conn:
            current = (
                conn.execute(select(T.contents).where(T.contents.c.id == content_id, T.contents.c.user_id == user_id))
                .mappings()
                .first()
            )
            if current is None:
                raise NotFoundError("저장물을 찾을 수 없어요.", {"content_id": content_id})
            result = conn.execute(
                update(T.contents)
                .where(T.contents.c.id == content_id, T.contents.c.user_id == user_id)
                .values(
                    source_url=current["source_url"] or source_url,
                    title=current["title"] or title,
                    author=current["author"] or author,
                    published_at=current["published_at"] or _iso(published_at),
                    analysis_pending=1,
                    status="pending",
                    revision=T.contents.c.revision + 1,
                    updated_at=_iso(now),
                )
            )
            if result.rowcount != 1:
                raise NotFoundError("저장물을 찾을 수 없어요.", {"content_id": content_id})

    def update_snapshot_ocr(
        self,
        user_id: str,
        content_id: str,
        snapshot_id: str,
        *,
        ocr_text: str,
        raw_meta: dict[str, Any],
        content_hash: str,
    ) -> None:
        with self.engine.begin() as conn:
            owned = conn.scalar(
                select(func.count())
                .select_from(T.contents)
                .where(T.contents.c.id == content_id, T.contents.c.user_id == user_id)
            )
            if not owned:
                raise NotFoundError("저장물을 찾을 수 없어요.", {"content_id": content_id})
            result = conn.execute(
                update(T.snapshots)
                .where(T.snapshots.c.id == snapshot_id, T.snapshots.c.content_id == content_id)
                .values(
                    ocr_text=ocr_text,
                    raw_meta=json.dumps(raw_meta, ensure_ascii=False),
                    content_hash=content_hash,
                )
            )
            if result.rowcount != 1:
                raise NotFoundError("스냅샷을 찾을 수 없어요.", {"content_id": content_id})

    def persist_ai_analysis(
        self,
        user_id: str,
        content_id: str,
        *,
        run_id: str,
        job_id: str,
        profile: str,
        output: Any,
        meta: Any,
        analysis_input: dict[str, Any],
        accepted_at: datetime | None,
        candidate_id: str | None = None,
        apply_layers: bool = True,
        connection: Connection | None = None,
        lease_id: str | None = None,
    ) -> None:
        """Persist only the AI-owned layers; user rows are never replaced."""
        now = accepted_at or datetime.now(UTC)
        with self.engine.begin() if connection is None else nullcontext(connection) as conn:
            conn.exec_driver_sql("UPDATE contents SET revision=revision WHERE 0")
            if lease_id is not None:
                active = conn.scalar(
                    select(T.ingest_jobs.c.id).where(
                        T.ingest_jobs.c.id == job_id,
                        T.ingest_jobs.c.user_id == user_id,
                        T.ingest_jobs.c.lease_id == lease_id,
                        T.ingest_jobs.c.status == "running",
                    )
                )
                if not active:
                    from jupjup.domain.errors import LeaseLostError

                    raise LeaseLostError("잡 lease 소유권을 잃었습니다")
            content = (
                conn.execute(select(T.contents).where(T.contents.c.id == content_id, T.contents.c.user_id == user_id))
                .mappings()
                .first()
            )
            if content is None:
                raise NotFoundError("저장물을 찾을 수 없어요.", {"content_id": content_id})
            snapshot_id = conn.scalar(
                select(T.snapshots.c.id)
                .where(T.snapshots.c.content_id == content_id)
                .order_by(T.snapshots.c.captured_at.desc(), T.snapshots.c.id.desc())
                .limit(1)
            )
            existing_created = conn.scalar(select(T.analysis_runs.c.created_at).where(T.analysis_runs.c.id == run_id))
            run_values = {
                "id": run_id,
                "job_id": job_id,
                "content_id": content_id,
                "profile": profile,
                "model": meta.model,
                "chunk_model": None,
                "prompt_version": meta.prompt_version,
                "mode": str(analysis_input.get("mode", "single")),
                "coverage": str(analysis_input.get("coverage", "full")),
                "attempts": meta.attempts,
                "first_pass_ok": int(meta.first_pass_ok),
                "partial": int(meta.partial),
                "repairs": json.dumps(meta.repairs, ensure_ascii=False),
                "input_tokens": meta.input_tokens,
                "output_tokens": meta.output_tokens,
                "cost_usd": meta.cost_usd,
                "latency_ms": round(meta.latency_ms),
                "output_json": output.model_dump_json(),
                "snapshot_id": snapshot_id,
                "candidate_id": candidate_id,
                "model_fingerprint": None,
                "validator_json": "{}",
                "accepted_at": _iso(accepted_at),
                "created_at": existing_created or _iso(now),
            }
            if existing_created is None:
                conn.execute(insert(T.analysis_runs).values(**run_values))
            else:
                conn.execute(update(T.analysis_runs).where(T.analysis_runs.c.id == run_id).values(**run_values))

            if not apply_layers:
                return
            user_tags = [
                Tag(name=name, source="user")
                for name in conn.scalars(
                    select(T.tags.c.name).where(T.tags.c.content_id == content_id, T.tags.c.source == "user")
                )
            ]
            ai_tags = [Tag(name=name, source="ai") for name in output.representative_tags]
            if len(effective_tags(user_tags + ai_tags, json.loads(content["hidden_tags"]))) > 15:
                raise AnalysisSchemaError("사용자 층과 합친 유효 태그가 최대 개수를 초과합니다")
            existing_summary = (
                conn.execute(
                    select(T.summaries).where(
                        T.summaries.c.content_id == content_id, T.summaries.c.analysis_run_id == run_id
                    )
                )
                .mappings()
                .first()
            )
            version = (
                existing_summary["version"]
                if existing_summary is not None
                else int(
                    conn.scalar(
                        select(func.coalesce(func.max(T.summaries.c.version), 0)).where(
                            T.summaries.c.content_id == content_id, T.summaries.c.source == "ai"
                        )
                    )
                    or 0
                )
                + 1
            )
            if isinstance(output, MetadataClassification) and output.summary is None:
                pass  # Legacy rule results have no summary.
            elif existing_summary is None:
                conn.execute(
                    insert(T.summaries).values(
                        id=f"sum_{run_id}",
                        content_id=content_id,
                        version=version,
                        text=output.summary,
                        model=meta.model,
                        source="ai",
                        analysis_run_id=run_id,
                        created_at=_iso(now),
                    )
                )
            else:
                conn.execute(
                    update(T.summaries)
                    .where(T.summaries.c.id == existing_summary["id"])
                    .values(text=output.summary, model=meta.model)
                )
            conn.execute(delete(T.tags).where(T.tags.c.content_id == content_id, T.tags.c.source == "ai"))
            for position, name in enumerate(output.representative_tags):
                conn.execute(
                    insert(T.tags).values(
                        content_id=content_id,
                        name=Tag(name=name, source="ai").name,
                        source="ai",
                        confidence=None,
                        position=position,
                        created_at=_iso(now),
                    )
                )
            ai_json = output.materialized_detail_tags()
            detail = (
                conn.execute(select(T.detail_tags).where(T.detail_tags.c.content_id == content_id)).mappings().first()
            )
            detail_values = {
                "ai_json": json.dumps(ai_json, ensure_ascii=False),
                "schema_version": 1,
                "analysis_run_id": run_id,
                "updated_at": _iso(now),
            }
            if detail is None:
                conn.execute(insert(T.detail_tags).values(content_id=content_id, user_patch=None, **detail_values))
            else:
                conn.execute(
                    update(T.detail_tags).where(T.detail_tags.c.content_id == content_id).values(**detail_values)
                )
            if (
                accepted_at is not None
                and meta.model != "local-metadata-rules-v1"
                and not str(meta.model).startswith("mock")
            ):
                from jupjup.collections.automatic import add_category_collection

                add_category_collection(conn, user_id, content_id, ai_json.get("category"), _iso(now))
            values: dict[str, Any] = {"revision": T.contents.c.revision + 1, "updated_at": _iso(now)}
            if content["title"] is None and output.title_suggestion:
                values["title"] = output.title_suggestion
            conn.execute(
                update(T.contents)
                .where(T.contents.c.id == content_id, T.contents.c.user_id == user_id)
                .values(**values)
            )

    def delete(self, user_id: str, content_id: str) -> None:
        with self.engine.begin() as conn:
            if not self.delete_in_transaction(conn, user_id, content_id):
                raise NotFoundError("저장물을 찾을 수 없어요.", {"content_id": content_id})

    def delete_in_transaction(self, conn: Connection, user_id: str, content_id: str) -> bool:
        conn.execute(
            update(T.ingest_jobs)
            .where(
                T.ingest_jobs.c.user_id == user_id,
                T.ingest_jobs.c.content_id == content_id,
                T.ingest_jobs.c.status.in_(["queued", "running", "retry_wait", "awaiting_confirmation"]),
            )
            .values(status="cancelled", lease_id=None, lease_until=None)
        )
        res = conn.execute(delete(T.contents).where(T.contents.c.id == content_id, T.contents.c.user_id == user_id))
        return res.rowcount > 0

    # ------------------------------------------------------------------ 읽기
    def get_bundle(self, user_id: str, content_id: str) -> ContentBundle:
        found = self.get_bundles(user_id, [content_id])
        if content_id not in found:
            raise NotFoundError("저장물을 찾을 수 없어요.", {"content_id": content_id})
        return found[content_id]

    def get_bundles(self, user_id: str, ids: Sequence[str]) -> dict[str, ContentBundle]:
        with self.engine.connect() as conn:
            return self.bundles_in(conn, user_id, ids)

    def bundles_in(self, conn: Connection, user_id: str, ids: Sequence[str]) -> dict[str, ContentBundle]:
        if not ids:
            return {}
        rows = (
            conn.execute(select(T.contents).where(T.contents.c.user_id == user_id, T.contents.c.id.in_(list(ids))))
            .mappings()
            .all()
        )
        return self._assemble(conn, [dict(r) for r in rows])

    def iter_bundles(self, user_id: str | None = None) -> Iterator[ContentBundle]:
        q = select(T.contents).order_by(T.contents.c.user_id, T.contents.c.id)
        if user_id is not None:
            q = q.where(T.contents.c.user_id == user_id)
        with self.engine.connect() as conn:
            rows = [dict(r) for r in conn.execute(q).mappings().all()]
            bundles = self._assemble(conn, rows)
        for r in rows:
            yield bundles[r["id"]]

    def count(self, user_id: str | None = None) -> int:
        q = select(T.contents.c.id)
        if user_id is not None:
            q = q.where(T.contents.c.user_id == user_id)
        with self.engine.connect() as conn:
            return len(conn.execute(q).all())

    def index_fingerprint(self, user_id: str) -> tuple[Any, ...]:
        """사용자 저장물의 검색 인덱스 입력이 바뀌었는지 싸게 알아내는 요약값.

        다른 프로세스(워커, CLI)가 같은 DB에 쓴 변경을 API 서버의 메모리 인덱스가 알아채는 데 쓴다.
        SQLite 트리거가 모든 인덱스 입력 쓰기마다 올리는 사용자별 revision을 우선 보고, 기존 DB의
        초기 상태도 구분하도록 행 수와 최신 생성 시각 요약값을 함께 본다. 따라서 ``updated_at``을
        그대로 둔 제자리 수정도 놓치지 않는다.
        """
        content_ids = select(T.contents.c.id).where(T.contents.c.user_id == user_id).scalar_subquery()

        def child(table: Any, *columns: Any) -> Any:
            return select(func.count(), *columns).where(table.c.content_id.in_(content_ids))

        with self.engine.connect() as conn:
            revision = conn.scalar(select(T.index_revisions.c.revision).where(T.index_revisions.c.user_id == user_id))
            head = conn.execute(
                select(
                    func.count(),
                    func.max(T.contents.c.updated_at),
                    func.total(T.contents.c.analysis_pending),
                    func.total(case((T.contents.c.status == "ready", 1), else_=0)),
                ).where(T.contents.c.user_id == user_id)
            ).one()
            parts: list[Any] = [revision or 0, *head]
            for query in (
                child(T.snapshots, func.max(T.snapshots.c.captured_at)),
                child(T.summaries, func.max(T.summaries.c.created_at)),
                child(T.tags, func.max(T.tags.c.created_at)),
                child(T.detail_tags, func.max(T.detail_tags.c.updated_at)),
                child(T.embeddings, func.max(T.embeddings.c.created_at)),
            ):
                parts.extend(conn.execute(query).one())
        return tuple(parts)

    def user_ids(self) -> list[str]:
        with self.engine.connect() as conn:
            return [r[0] for r in conn.execute(select(T.contents.c.user_id).distinct().order_by(T.contents.c.user_id))]

    def _assemble(self, conn: Connection, rows: list[dict[str, Any]]) -> dict[str, ContentBundle]:
        if not rows:
            return {}
        ids = [r["id"] for r in rows]
        snaps: dict[str, Snapshot] = {}
        for s in conn.execute(
            select(T.snapshots).where(T.snapshots.c.content_id.in_(ids)).order_by(T.snapshots.c.captured_at)
        ).mappings():
            snaps[s["content_id"]] = Snapshot(  # captured_at이 가장 늦은 스냅샷이 남는다
                id=s["id"],
                content_id=s["content_id"],
                captured_at=_dt(s["captured_at"]),
                text=s["text"] or "",
                ocr_text=s["ocr_text"],
                raw_meta=json.loads(s["raw_meta"] or "{}"),
                content_hash=s["content_hash"],
                truncated=bool(s["truncated"]),
            )
        sums: dict[str, list[Summary]] = {i: [] for i in ids}
        for s in conn.execute(
            select(T.summaries).where(T.summaries.c.content_id.in_(ids)).order_by(T.summaries.c.id)
        ).mappings():
            sums[s["content_id"]].append(
                Summary(
                    id=s["id"],
                    content_id=s["content_id"],
                    version=s["version"],
                    text=s["text"],
                    model=s["model"] or "",
                    source=s["source"],
                    analysis_run_id=s["analysis_run_id"],
                    created_at=_dt(s["created_at"]),
                )
            )
        tgs: dict[str, list[Tag]] = {i: [] for i in ids}
        for t in conn.execute(
            select(T.tags).where(T.tags.c.content_id.in_(ids)).order_by(T.tags.c.content_id, T.tags.c.position)
        ).mappings():
            tgs[t["content_id"]].append(Tag(name=t["name"], source=t["source"], confidence=t["confidence"]))
        details: dict[str, DetailTags] = {}
        for d in conn.execute(select(T.detail_tags).where(T.detail_tags.c.content_id.in_(ids))).mappings():
            details[d["content_id"]] = DetailTags(
                content_id=d["content_id"],
                ai_json=json.loads(d["ai_json"]),
                user_patch=None if d["user_patch"] is None else json.loads(d["user_patch"]),
                schema_version=d["schema_version"],
                analysis_run_id=d["analysis_run_id"],
            )
        out: dict[str, ContentBundle] = {}
        for r in rows:
            content = Content(
                id=r["id"],
                user_id=r["user_id"],
                source_url=r["source_url"],
                source_kind=r["source_kind"],
                normalized_url=r["normalized_url"],
                platform=r["platform"],
                content_type=r["content_type"],
                title=r["title"],
                author=r["author"],
                published_at=_dt(r["published_at"]),
                saved_at=_dt(r["saved_at"]),
                original_status=r["original_status"],
                user_note=r["user_note"],
                hidden_tags=json.loads(r["hidden_tags"] or "[]"),
                status=r["status"],
                analysis_pending=bool(r["analysis_pending"]),
                automation_level=r["automation_level"],
                is_hidden=bool(r["is_hidden"]),
                revision=r["revision"],
                duplicate_of_content_id=r["duplicate_of_content_id"],
                created_at=_dt(r["created_at"]),
                updated_at=_dt(r["updated_at"]),
            )
            out[r["id"]] = ContentBundle(
                content=content,
                snapshot=snaps.get(r["id"]),
                summaries=sums[r["id"]],
                tags=tgs[r["id"]],
                detail_tags=details.get(r["id"]),
            )
        return out


class SqlEmbeddingRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def get(self, content_id: str, model_id: str) -> list[StoredEmbedding]:
        q = (
            select(T.embeddings)
            .where(T.embeddings.c.content_id == content_id, T.embeddings.c.model_id == model_id)
            .order_by(T.embeddings.c.kind, T.embeddings.c.chunk_index)
        )
        with self.engine.connect() as conn:
            return [_row_to_emb(dict(r)) for r in conn.execute(q).mappings()]

    def get_all(self, model_id: str, content_ids: Sequence[str]) -> dict[str, list[StoredEmbedding]]:
        out: dict[str, list[StoredEmbedding]] = {cid: [] for cid in content_ids}
        if not content_ids:
            return out
        q = (
            select(T.embeddings)
            .where(T.embeddings.c.model_id == model_id, T.embeddings.c.content_id.in_(list(content_ids)))
            .order_by(T.embeddings.c.content_id, T.embeddings.c.kind, T.embeddings.c.chunk_index)
        )
        with self.engine.connect() as conn:
            for r in conn.execute(q).mappings():
                out[r["content_id"]].append(_row_to_emb(dict(r)))
        return out

    def replace(self, content_id: str, model_id: str, rows: Sequence[StoredEmbedding]) -> None:
        with self.engine.begin() as conn:
            _replace_embeddings(conn, content_id, model_id, rows)


def _replace_embeddings(conn: Connection, content_id: str, model_id: str, rows: Sequence[StoredEmbedding]) -> None:
    now = _now_iso()
    conn.execute(
        delete(T.embeddings).where(T.embeddings.c.content_id == content_id, T.embeddings.c.model_id == model_id)
    )
    for embedding in rows:
        vector = np.ascontiguousarray(embedding.vector, dtype="<f4")
        conn.execute(
            insert(T.embeddings).values(
                id=f"emb_{content_id}_{model_id}_{embedding.kind}_{embedding.chunk_index}",
                content_id=content_id,
                model_id=model_id,
                kind=embedding.kind,
                chunk_index=embedding.chunk_index,
                text_hash=embedding.text_hash,
                dim=int(vector.shape[0]),
                vector=vector.tobytes(),
                created_at=now,
            )
        )


def _row_to_emb(r: dict[str, Any]) -> StoredEmbedding:
    vec = np.frombuffer(r["vector"], dtype="<f4").astype(np.float32)
    if vec.shape[0] != r["dim"]:
        raise ValueError(f"임베딩 차원 불일치: {r['id']}")
    return StoredEmbedding(
        kind=r["kind"], chunk_index=r["chunk_index"], text_hash=r["text_hash"], vector=vec, model_id=r["model_id"]
    )

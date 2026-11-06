"""인덱싱 서비스 (설계서 5.8.5절). SQLite가 정본이고, 메모리 인덱스는 거기서 다시 만든다."""

from __future__ import annotations

import threading
from collections.abc import Sequence
from dataclasses import dataclass

from pydantic import BaseModel

from jupjup.config import EmbeddingTextSettings
from jupjup.domain.errors import EmbeddingCacheMiss, EmbeddingProviderError
from jupjup.domain.models import ContentBundle, Snapshot, StoredEmbedding
from jupjup.index.document import (
    EmbeddingText,
    IndexDocument,
    build_embedding_texts,
    build_index_document_from_bundle,
)
from jupjup.index.registry import RebuildStats, UserIndexRegistry
from jupjup.providers.embedding import Embedder
from jupjup.storage.repositories import ContentRepository, EmbeddingRepository
from jupjup.text.lexicon import Lexicon


class IndexResult(BaseModel):
    content_id: str
    embedding_pending: bool = False
    embedded: int = 0
    reused: int = 0


@dataclass(frozen=True)
class PreparedIndex:
    """Provider work completed without mutating SQLite or the live user index."""

    bundle: ContentBundle
    document: IndexDocument
    embeddings: list[StoredEmbedding]
    replace_embeddings: bool
    result: IndexResult
    embedding_error: EmbeddingProviderError | EmbeddingCacheMiss | None = None


class IndexingService:
    def __init__(
        self,
        repo: ContentRepository,
        emb_repo: EmbeddingRepository,
        registry: UserIndexRegistry,
        embedder: Embedder,
        lexicon: Lexicon | None = None,
        text_settings: EmbeddingTextSettings | None = None,
    ) -> None:
        self.repo = repo
        self.emb_repo = emb_repo
        self.registry = registry
        self.embedder = embedder
        self.lexicon = lexicon
        self.text_settings = text_settings or EmbeddingTextSettings()
        self._fingerprints: dict[str, tuple[object, ...]] = {}
        self._fingerprint_lock = threading.Lock()

    def index_content(self, user_id: str, content_id: str) -> IndexResult:
        """저장소에서 읽어 IndexDocument를 만들고, 바뀐 텍스트만 임베딩해 저장한 뒤 세 인덱스에 반영한다.

        임베딩이 실패하면 키워드 인덱스만 반영하고 embedding_pending=True. 벡터 인덱스에는 텍스트가
        그대로인(해시가 같은) 기존 벡터만 남긴다.
        """
        return self.index_bundle(self.repo.get_bundle(user_id, content_id))

    def index_bundle(self, bundle: ContentBundle) -> IndexResult:
        if bundle.content.is_hidden or bundle.content.status == "duplicate":
            self.registry.get(bundle.content.user_id).remove(bundle.content.id)
            return IndexResult(content_id=bundle.content.id)
        return self.apply_prepared(self.prepare_bundle(bundle))

    def index_reduced(self, user_id: str, content_id: str) -> IndexResult:
        """Publish the currently available snapshot/title-only bundle immediately."""
        bundle = self.repo.get_bundle(user_id, content_id)
        if bundle.content.is_hidden or bundle.content.status == "duplicate":
            self.registry.get(user_id).remove(content_id)
            return IndexResult(content_id=content_id)
        return self.apply_prepared(self.prepare_bundle(bundle, allow_cache_miss=True))

    def embed_content(self, user_id: str, content_id: str) -> IndexResult:
        """Persist I7 embeddings without publishing the full I8 document."""
        prepared = self.prepare_bundle(self.repo.get_bundle(user_id, content_id))
        if prepared.embedding_error is not None:
            raise prepared.embedding_error
        if prepared.replace_embeddings:
            self.emb_repo.replace(content_id, self.embedder.model_id, prepared.embeddings)
        return prepared.result

    def prepare_bundle(self, bundle: ContentBundle, *, allow_cache_miss: bool = False) -> PreparedIndex:
        """Build and embed a bundle without changing repository or registry state."""
        content_id = bundle.content.id
        projected = self._source_projection(bundle)
        doc = build_index_document_from_bundle(projected)
        texts = self._embedding_texts(doc, projected)
        model_id = self.embedder.model_id
        existing = self.emb_repo.get(content_id, model_id)
        keep, todo = self._match_stored(texts, existing)
        result = IndexResult(content_id=content_id, reused=len(keep))
        if todo:
            try:
                vecs = self.embedder.embed([t.text for t in todo], "document")
            except EmbeddingCacheMiss as exc:
                if not allow_cache_miss:
                    raise
                result.embedding_pending = True
                return PreparedIndex(
                    bundle=bundle,
                    document=doc,
                    embeddings=keep,
                    replace_embeddings=False,
                    result=result,
                    embedding_error=exc,
                )
            except EmbeddingProviderError as exc:
                result.embedding_pending = True
                return PreparedIndex(
                    bundle=bundle,
                    document=doc,
                    embeddings=keep,
                    replace_embeddings=False,
                    result=result,
                    embedding_error=exc,
                )
            for t, v in zip(todo, vecs, strict=True):
                keep.append(
                    StoredEmbedding(
                        kind=t.kind, chunk_index=t.chunk_index, text_hash=t.text_hash, vector=v, model_id=model_id
                    )
                )
            result.embedded = len(todo)
        keep.sort(key=lambda e: (e.kind, e.chunk_index))
        return PreparedIndex(
            bundle=bundle,
            document=doc,
            embeddings=keep,
            replace_embeddings=bool(todo or len(keep) != len(existing)),
            result=result,
        )

    def _source_projection(self, bundle: ContentBundle) -> ContentBundle:
        """Use accepted metadata for indexing only; never write this projection to storage."""
        result = self.repo.metadata_for(bundle)
        if result is None:
            return bundle
        metadata = result.metadata
        return bundle.model_copy(
            update={
                "content": bundle.content.model_copy(update={"title": metadata.title}),
                "snapshot": Snapshot(
                    id="metadata_index",
                    content_id=bundle.content.id,
                    captured_at=bundle.content.saved_at,
                    text=metadata.description,
                    raw_meta={"source_scope": "youtube_metadata"},
                ),
                "summaries": [
                    s
                    for s in bundle.summaries
                    if s.source == "user"
                    or (
                        result.classifier == "local-metadata-llm-v1"
                        and bundle.detail_tags
                        and s.analysis_run_id == bundle.detail_tags.analysis_run_id
                    )
                ],
            }
        )

    def _embedding_texts(self, doc: IndexDocument, bundle: ContentBundle) -> list[EmbeddingText]:
        ts = self.text_settings
        return build_embedding_texts(
            doc,
            ts.chunk_chars,
            ts.overlap,
            ts.max_chunks,
            lexicon=self.lexicon,
            full_body=bundle.snapshot.text if bundle.snapshot else None,
        )

    def _match_stored(
        self, texts: Sequence[EmbeddingText], stored: Sequence[StoredEmbedding]
    ) -> tuple[list[StoredEmbedding], list[EmbeddingText]]:
        """텍스트 해시와 차원이 같은 저장 벡터는 재사용하고, 나머지는 새로 임베딩할 목록으로 돌려준다."""
        existing = {(e.kind, e.chunk_index): e for e in stored}
        keep: list[StoredEmbedding] = []
        todo: list[EmbeddingText] = []
        for t in texts:
            old = existing.get((t.kind, t.chunk_index))
            if old is not None and old.text_hash == t.text_hash and old.vector.shape[0] == self.embedder.dim:
                keep.append(old)
            else:
                todo.append(t)
        return keep, todo

    def apply_prepared(self, prepared: PreparedIndex) -> IndexResult:
        """Publish a successfully prepared document to embedding and memory indexes."""
        content_id = prepared.document.content_id
        keep = prepared.embeddings
        if prepared.replace_embeddings:
            self.emb_repo.replace(content_id, self.embedder.model_id, keep)
        uidx = self.registry.get(prepared.document.user_id)
        uidx.upsert_document(prepared.document)
        uidx.vector.upsert(content_id, keep)
        return prepared.result

    def commit_prepared(self, prepared: Sequence[PreparedIndex]) -> list[IndexResult]:
        """Atomically commit a strict batch to SQLite, then publish copy-on-write indexes."""
        staged_users = {
            user_id: self.registry.stage_updates(
                user_id,
                [(item.document, item.embeddings) for item in prepared if item.document.user_id == user_id],
            )
            for user_id in sorted({item.document.user_id for item in prepared})
        }
        embedding_updates = [
            (item.document.content_id, self.embedder.model_id, item.embeddings)
            for item in prepared
            if item.replace_embeddings
        ]
        self.repo.upsert_many_with_embeddings(
            [item.bundle for item in prepared],
            embedding_updates,
        )
        for user_id, staged in staged_users.items():
            self.registry.publish(user_id, staged)
        return [item.result for item in prepared]

    def remove_content(self, user_id: str, content_id: str) -> None:
        self.repo.delete(user_id, content_id)
        self.registry.get(user_id).remove(content_id)

    def reindex_all(self, user_id: str | None = None) -> RebuildStats:
        """저장소 기준으로 인덱스를 다시 만든다. 저장소에 없는 문서는 인덱스에서도 사라진다."""
        users = [user_id] if user_id is not None else self.repo.user_ids()
        stats = RebuildStats()
        for uid in users:
            # 다시 읽기 전에 요약값을 잡는다. 재구축 중에 들어온 변경은 다음 확인 때 다시 읽힌다.
            self._remember_fingerprint(uid, self.repo.index_fingerprint(uid))
            self.registry.reset(uid)
            stats.users += 1
            for bundle in self.repo.iter_bundles(uid):
                r = self.index_bundle(bundle)
                stats.documents += 1
                stats.embedded += r.embedded
                stats.reused += r.reused
                stats.embedding_pending += int(r.embedding_pending)
        return stats

    # ------------------------------------------------------------ 다른 프로세스의 쓰기 반영
    def refresh_if_stale(self, user_id: str) -> bool:
        """저장소가 마지막으로 읽은 뒤 바뀌었으면 그 사용자의 인덱스를 저장소에서 다시 읽는다.

        API 서버처럼 오래 떠 있는 프로세스가 검색 전에 부른다. 별도 ``worker run`` 프로세스나 CLI가
        같은 DB에 쓴 결과는 이 프로세스의 메모리 인덱스에 자동으로 들어오지 않기 때문이다.
        바뀌지 않았으면 DB 요약 조회 몇 번만 하고 끝난다. 바뀌었으면 True를 돌려준다.
        """
        fingerprint = self.repo.index_fingerprint(user_id)
        with self._fingerprint_lock:
            if self._fingerprints.get(user_id) == fingerprint:
                return False
        self.reload_user(user_id)
        self._remember_fingerprint(user_id, fingerprint)
        return True

    def reload_user(self, user_id: str) -> None:
        """저장소의 문서와 저장된 임베딩만으로 사용자 인덱스를 새로 만들어 한 번에 바꿔 끼운다.

        임베딩 제공자를 부르지 않고 저장소에 쓰지도 않는다. 텍스트 해시가 맞는 저장 벡터가 없는 문서는
        키워드 인덱스에만 들어간다(축약 인덱스나 임베딩 대기 상태와 같다).
        """
        staged = self.registry.empty(user_id)
        model_id = self.embedder.model_id
        bundles = [
            b for b in self.repo.iter_bundles(user_id) if not b.content.is_hidden and b.content.status != "duplicate"
        ]
        if not bundles and user_id not in self.registry.users():
            return  # 저장물 없는 사용자 조회가 빈 인덱스를 남기지 않게 한다
        for bundle in bundles:
            bundle = self._source_projection(bundle)
            doc = build_index_document_from_bundle(bundle)
            stored = self.emb_repo.get(doc.content_id, model_id)
            keep, _ = self._match_stored(self._embedding_texts(doc, bundle), stored)
            keep.sort(key=lambda e: (e.kind, e.chunk_index))
            staged.upsert_document(doc)
            staged.vector.upsert(doc.content_id, keep)
        self.registry.publish(user_id, staged)

    def _remember_fingerprint(self, user_id: str, fingerprint: tuple[object, ...]) -> None:
        with self._fingerprint_lock:
            self._fingerprints[user_id] = fingerprint

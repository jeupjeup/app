"""사용자별 인덱스 보관과 재구축 (설계서 5.6절, 5.8.5절).

격리는 구조로 지킨다: 사용자마다 morph/ngram/vector 인덱스와 메타를 물리적으로 따로 둔다.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from pydantic import BaseModel

from jupjup.config import SearchSettings
from jupjup.domain.models import USER_ID_RE, StoredEmbedding
from jupjup.index.document import DocMeta, IndexDocument
from jupjup.index.lexical import BM25FIndex
from jupjup.index.vector import NumpyVectorIndex
from jupjup.text.tokenizer import Tokenizer


class RebuildStats(BaseModel):
    users: int = 0
    documents: int = 0
    embedded: int = 0
    reused: int = 0
    embedding_pending: int = 0


@dataclass
class UserIndex:
    user_id: str
    morph: BM25FIndex
    ngram: BM25FIndex
    vector: NumpyVectorIndex
    meta: dict[str, DocMeta] = field(default_factory=dict)
    documents: dict[str, IndexDocument] = field(default_factory=dict)

    def upsert_document(self, doc: IndexDocument) -> None:
        if doc.user_id != self.user_id:
            raise ValueError("다른 사용자의 문서를 이 인덱스에 넣을 수 없습니다")
        self.meta[doc.content_id] = doc.meta()
        self.documents[doc.content_id] = doc
        self.morph.upsert(doc)
        self.ngram.upsert(doc)

    def remove(self, content_id: str) -> None:
        self.morph.delete(content_id)
        self.ngram.delete(content_id)
        self.vector.delete(content_id)
        self.meta.pop(content_id, None)
        self.documents.pop(content_id, None)

    def __len__(self) -> int:
        return len(self.meta)


class UserIndexRegistry:
    def __init__(
        self, morph_tokenizer: Tokenizer, ngram_tokenizer: Tokenizer, settings: SearchSettings, dim: int
    ) -> None:
        self.morph_tokenizer = morph_tokenizer
        self.ngram_tokenizer = ngram_tokenizer
        self.settings = settings
        self.dim = dim
        self._users: dict[str, UserIndex] = {}
        self._lock = threading.Lock()
        self.ready = True

    def _new(self, user_id: str) -> UserIndex:
        bm = self.settings.bm25
        meta: dict[str, DocMeta] = {}
        documents: dict[str, IndexDocument] = {}
        return UserIndex(
            user_id=user_id,
            morph=BM25FIndex(self.morph_tokenizer, bm.field_weights, bm.field_b, bm.k1),
            ngram=BM25FIndex(self.ngram_tokenizer, bm.field_weights, bm.field_b, bm.k1),
            vector=NumpyVectorIndex(meta, self.dim, self.settings.retrieval.chunk_weight),
            meta=meta,
            documents=documents,
        )

    def empty(self, user_id: str) -> UserIndex:
        """게시하지 않은 빈 사용자 인덱스. 채운 뒤 ``publish``로 한 번에 바꿔 끼운다."""
        if not USER_ID_RE.fullmatch(user_id):
            raise ValueError("user_id 형식 오류")
        return self._new(user_id)

    def get(self, user_id: str) -> UserIndex:
        """없으면 빈 인덱스를 만든다."""
        if not USER_ID_RE.match(user_id):
            raise ValueError("user_id 형식 오류")
        with self._lock:
            idx = self._users.get(user_id)
            if idx is None:
                idx = self._users[user_id] = self._new(user_id)
            return idx

    def peek(self, user_id: str) -> UserIndex:
        """Return an existing index or an unregistered empty view for read-only work."""
        if not USER_ID_RE.fullmatch(user_id):
            raise ValueError("user_id 형식 오류")
        with self._lock:
            idx = self._users.get(user_id)
        return idx if idx is not None else self._new(user_id)

    def users(self) -> list[str]:
        return sorted(self._users)

    def reset(self, user_id: str) -> UserIndex:
        with self._lock:
            idx = self._users[user_id] = self._new(user_id)
            return idx

    def stage_updates(
        self, user_id: str, updates: Sequence[tuple[IndexDocument, Sequence[StoredEmbedding]]]
    ) -> UserIndex:
        """Build a copy-on-write user index without publishing it."""
        with self._lock:
            current = self._users.get(user_id)
            documents = list(current.documents.values()) if current is not None else []
            vectors = current.vector.snapshot() if current is not None else {}
        staged = self._new(user_id)
        for document in documents:
            staged.upsert_document(document)
            staged.vector.upsert(document.content_id, vectors.get(document.content_id, ()))
        for document, embeddings in updates:
            staged.upsert_document(document)
            staged.vector.upsert(document.content_id, embeddings)
        return staged

    def publish(self, user_id: str, staged: UserIndex) -> None:
        if staged.user_id != user_id:
            raise ValueError("다른 사용자의 인덱스를 게시할 수 없습니다")
        with self._lock:
            self._users[user_id] = staged

    def for_each(self, fn: Callable[[UserIndex], None]) -> None:
        for uid in self.users():
            fn(self._users[uid])

"""numpy 전수 코사인 벡터 인덱스 (설계서 5.3.3절). 사용자 단위로 하나씩 만든다."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol

import numpy as np

from jupjup.domain.models import StoredEmbedding
from jupjup.index.document import DocMeta, HardFilter
from jupjup.search.types import RetrievalHit


class VectorIndex(Protocol):
    def upsert(self, content_id: str, vectors: Sequence[StoredEmbedding]) -> None: ...
    def delete(self, content_id: str) -> None: ...
    def search(self, query_vec: np.ndarray, flt: HardFilter, top_n: int) -> list[RetrievalHit]: ...
    def similarities(self, query_vec: np.ndarray, ids: Sequence[str]) -> dict[str, float]: ...


class NumpyVectorIndex:
    """후보 점수 = max(doc_sim, chunk_weight × max(chunk_sim))."""

    def __init__(self, meta: Mapping[str, DocMeta], dim: int, chunk_weight: float = 0.9) -> None:
        self.meta = meta
        self.dim = dim
        self.chunk_weight = chunk_weight
        self._vectors: dict[str, list[StoredEmbedding]] = {}
        self._dirty = True
        self._ids: list[str] = []
        self._doc_m = np.zeros((0, dim), dtype=np.float32)
        self._doc_owner = np.zeros(0, dtype=np.int64)
        self._chunk_m = np.zeros((0, dim), dtype=np.float32)
        self._chunk_owner = np.zeros(0, dtype=np.int64)

    def __len__(self) -> int:
        return len(self._vectors)

    def upsert(self, content_id: str, vectors: Sequence[StoredEmbedding]) -> None:
        for v in vectors:
            if v.vector.shape != (self.dim,):
                raise ValueError(f"벡터 차원 불일치: {v.vector.shape} != ({self.dim},)")
        if vectors:
            self._vectors[content_id] = list(vectors)
        else:
            self._vectors.pop(content_id, None)
        self._dirty = True

    def delete(self, content_id: str) -> None:
        if self._vectors.pop(content_id, None) is not None:
            self._dirty = True

    def snapshot(self) -> dict[str, list[StoredEmbedding]]:
        return {content_id: list(rows) for content_id, rows in self._vectors.items()}

    def _rebuild(self) -> None:
        # content_id 정렬 순서로 행렬을 만든다 → 증분/재구축 결과가 같다
        self._ids = sorted(self._vectors)
        docs: list[np.ndarray] = []
        d_owner: list[int] = []
        chunks: list[np.ndarray] = []
        c_owner: list[int] = []
        for i, cid in enumerate(self._ids):
            for e in sorted(self._vectors[cid], key=lambda x: (x.kind, x.chunk_index)):
                if e.kind == "doc":
                    docs.append(e.vector)
                    d_owner.append(i)
                else:
                    chunks.append(e.vector)
                    c_owner.append(i)
        self._doc_m = np.stack(docs).astype(np.float32) if docs else np.zeros((0, self.dim), dtype=np.float32)
        self._doc_owner = np.asarray(d_owner, dtype=np.int64)
        self._chunk_m = np.stack(chunks).astype(np.float32) if chunks else np.zeros((0, self.dim), dtype=np.float32)
        self._chunk_owner = np.asarray(c_owner, dtype=np.int64)
        self._dirty = False

    def _scores(self, query_vec: np.ndarray) -> np.ndarray:
        if self._dirty:
            self._rebuild()
        q = np.asarray(query_vec, dtype=np.float32).reshape(-1)
        scores = np.full(len(self._ids), -np.inf, dtype=np.float32)
        if len(self._doc_m):
            np.maximum.at(scores, self._doc_owner, self._doc_m @ q)
        if len(self._chunk_m):
            np.maximum.at(scores, self._chunk_owner, (self._chunk_m @ q) * np.float32(self.chunk_weight))
        return scores

    def search(self, query_vec: np.ndarray, flt: HardFilter, top_n: int) -> list[RetrievalHit]:
        scores = self._scores(query_vec)
        cands = [
            (float(scores[i]), cid)
            for i, cid in enumerate(self._ids)
            if np.isfinite(scores[i]) and cid in self.meta and flt.accepts(self.meta[cid])
        ]
        cands.sort(key=lambda x: (-x[0], x[1]))
        return [RetrievalHit(content_id=cid, score=s, rank=r) for r, (s, cid) in enumerate(cands[:top_n], 1)]

    def similarities(self, query_vec: np.ndarray, ids: Sequence[str]) -> dict[str, float]:
        scores = self._scores(query_vec)
        pos = {cid: i for i, cid in enumerate(self._ids)}
        return {cid: float(scores[pos[cid]]) for cid in ids if cid in pos and np.isfinite(scores[pos[cid]])}

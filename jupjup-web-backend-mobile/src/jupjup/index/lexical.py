"""앱 내장 BM25F 키워드 인덱스 (설계서 5.3.2절, 5.8.5절).

필드별 가중 tf를 먼저 합하고 포화 함수를 한 번 적용하는 표준 BM25F:
    tf~(t,d) = Σ_f w_f · tf(t,d,f) / (1 − b_f + b_f · len_f(d) / avglen_f)
    score(d) = Σ_t idf(t) · tf~ / (k1 + tf~),   idf = ln(1 + (N − df + 0.5) / (df + 0.5))
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Mapping
from typing import Protocol

from jupjup.index.document import INDEX_FIELDS, DocMeta, HardFilter, IndexDocument, IndexField
from jupjup.search.types import RetrievalHit
from jupjup.text.normalize import jamo_distance, to_jamo
from jupjup.text.tokenizer import Tokenizer

_CORRECTABLE = re.compile(r"[가-힣]|^[a-z]{3,}$")


class IndexVocabulary:
    """사용자 인덱스 어휘. 교정 후보는 자모 길이 버킷으로 좁힌 뒤 거리 상한 Levenshtein으로 찾는다."""

    def __init__(self, documents: Mapping[str, set[str]]) -> None:
        self._documents = {term: set(ids) for term, ids in documents.items()}
        self._df = {term: len(ids) for term, ids in self._documents.items()}
        self._buckets: dict[int, list[tuple[str, str]]] = {}
        for term in sorted(self._df):
            if len(term) >= 2 and _CORRECTABLE.search(term):
                j = to_jamo(term)
                self._buckets.setdefault(len(j), []).append((term, j))

    def contains(self, term: str) -> bool:
        return term in self._df

    def doc_freq(self, term: str) -> int:
        return self._df.get(term, 0)

    def candidates_by_jamo(self, term: str, max_distance: int) -> list[tuple[str, int]]:
        j = to_jamo(term)
        out: list[tuple[str, int]] = []
        for length in range(len(j) - max_distance, len(j) + max_distance + 1):
            for cand, cj in self._buckets.get(length, ()):
                if cand == term:
                    continue
                d = jamo_distance(cand, term, max_distance) if cj else max_distance + 1
                if d <= max_distance:
                    out.append((cand, d))
        return out

    def context_support(self, candidate: str, context_terms: list[str]) -> float:
        candidate_docs = self._documents.get(candidate, set())
        if not candidate_docs or not context_terms:
            return 0.0
        supported = [
            len(candidate_docs & self._documents.get(term, set())) / len(candidate_docs) for term in context_terms
        ]
        return max(supported, default=0.0)

    def __len__(self) -> int:
        return len(self._df)


class KeywordIndex(Protocol):
    analyzer: str

    def upsert(self, doc: IndexDocument) -> None: ...
    def delete(self, content_id: str) -> None: ...
    def search(self, terms: list[str], flt: HardFilter, top_n: int) -> list[RetrievalHit]: ...
    def vocabulary(self) -> IndexVocabulary: ...
    def doc_terms(self, content_id: str, fields: tuple[IndexField, ...] | None = None) -> set[str]: ...


class BM25FIndex:
    def __init__(
        self, tokenizer: Tokenizer, field_weights: Mapping[str, float], field_b: Mapping[str, float], k1: float = 1.2
    ) -> None:
        self.tokenizer = tokenizer
        self.analyzer = tokenizer.name
        self.k1 = k1
        self.fields: tuple[IndexField, ...] = tuple(f for f in INDEX_FIELDS if field_weights.get(f, 0.0) > 0)
        self.w = {f: float(field_weights[f]) for f in self.fields}
        self.b = {f: float(field_b.get(f, 0.75)) for f in self.fields}
        self._postings: dict[str, dict[str, dict[IndexField, int]]] = {}
        self._doc_tf: dict[str, dict[IndexField, Counter[str]]] = {}
        self._doc_len: dict[str, dict[IndexField, int]] = {}
        self._len_sum: dict[IndexField, int] = dict.fromkeys(self.fields, 0)
        self.meta: dict[str, DocMeta] = {}
        self._vocab: IndexVocabulary | None = None

    def __len__(self) -> int:
        return len(self._doc_tf)

    # ------------------------------------------------------------------ 쓰기
    def upsert(self, doc: IndexDocument) -> None:
        if doc.content_id in self._doc_tf:
            self.delete(doc.content_id)
        tfs: dict[IndexField, Counter[str]] = {}
        lens: dict[IndexField, int] = {}
        for f in self.fields:
            terms = self.tokenizer.index_terms(doc.fields.get(f, "")) if doc.fields.get(f) else []
            tfs[f] = Counter(terms)
            lens[f] = len(terms)
            self._len_sum[f] += len(terms)
            for term, n in tfs[f].items():
                self._postings.setdefault(term, {}).setdefault(doc.content_id, {})[f] = n
        self._doc_tf[doc.content_id] = tfs
        self._doc_len[doc.content_id] = lens
        self.meta[doc.content_id] = doc.meta()
        self._vocab = None

    def delete(self, content_id: str) -> None:
        tfs = self._doc_tf.pop(content_id, None)
        if tfs is None:
            return
        for f, counter in tfs.items():
            self._len_sum[f] -= sum(counter.values())
            for term in counter:
                plist = self._postings.get(term)
                if plist is not None:
                    plist.pop(content_id, None)
                    if not plist:
                        del self._postings[term]
        self._doc_len.pop(content_id, None)
        self.meta.pop(content_id, None)
        self._vocab = None

    # ------------------------------------------------------------------ 읽기
    def idf(self, term: str) -> float:
        n = len(self._doc_tf)
        df = len(self._postings.get(term, {}))
        return math.log(1.0 + (n - df + 0.5) / (df + 0.5))

    def search(self, terms: list[str], flt: HardFilter, top_n: int) -> list[RetrievalHit]:
        n = len(self._doc_tf)
        if n == 0 or not terms:
            return []
        avg = {f: (self._len_sum[f] / n) or 1.0 for f in self.fields}
        scores: dict[str, float] = {}
        matched: dict[str, dict[str, list[str]]] = {}
        accepted: dict[str, bool] = {}
        for term in dict.fromkeys(terms):  # 중복 제거, 순서 유지
            plist = self._postings.get(term)
            if not plist:
                continue
            idf = self.idf(term)
            for cid, ftf in plist.items():
                ok = accepted.get(cid)
                if ok is None:
                    ok = accepted[cid] = flt.accepts(self.meta[cid])
                if not ok:
                    continue
                lens = self._doc_len[cid]
                tf_tilde = 0.0
                for f in self.fields:  # 고정 순서로 더해 결정성을 지킨다
                    tf = ftf.get(f)
                    if tf:
                        norm = 1.0 - self.b[f] + self.b[f] * lens[f] / avg[f]
                        tf_tilde += self.w[f] * tf / norm
                        matched.setdefault(cid, {}).setdefault(f, []).append(term)
                scores[cid] = scores.get(cid, 0.0) + idf * tf_tilde / (self.k1 + tf_tilde)
        ordered = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))[:top_n]
        return [
            RetrievalHit(content_id=cid, score=s, rank=i, matched_fields=matched.get(cid, {}))
            for i, (cid, s) in enumerate(ordered, 1)
        ]

    def vocabulary(self) -> IndexVocabulary:
        if self._vocab is None:
            self._vocab = IndexVocabulary({term: set(postings) for term, postings in self._postings.items()})
        return self._vocab

    def doc_terms(self, content_id: str, fields: tuple[IndexField, ...] | None = None) -> set[str]:
        tfs = self._doc_tf.get(content_id, {})
        out: set[str] = set()
        for f, counter in tfs.items():
            if fields is None or f in fields:
                out.update(counter)
        return out

    def snapshot_state(self) -> dict[str, object]:
        """재구축/증분 비교 테스트용 정규화된 상태."""
        return {
            "postings": {
                t: {c: dict(sorted(v.items())) for c, v in sorted(p.items())} for t, p in sorted(self._postings.items())
            },
            "len_sum": dict(self._len_sum),
            "docs": sorted(self._doc_tf),
        }

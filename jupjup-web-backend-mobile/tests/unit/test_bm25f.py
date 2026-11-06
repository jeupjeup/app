"""T9: BM25F 손계산 비교, HardFilter, upsert/delete 일관성, 두 분석기."""

from __future__ import annotations

import math
from datetime import datetime

import pytest

from jupjup.index.document import HardFilter, IndexDocument
from jupjup.index.lexical import BM25FIndex
from jupjup.text.tokenizer import CharNgramTokenizer, KiwiTokenizer, Token
from tests.conftest import KST


class WS:
    name = "ws"

    def tokenize(self, text: str) -> list[Token]:
        return [Token(w, w, "X", 0, 0) for w in text.split()]

    def index_terms(self, text: str) -> list[str]:
        return text.split()

    def query_terms(self, text: str) -> list[str]:
        return text.split()


W = {"title": 2.0, "body": 1.0}
B = {"title": 0.5, "body": 0.75}


def doc(cid: str, title: str, body: str, platform: str = "instagram", day: int = 1, user: str = "u_a") -> IndexDocument:
    return IndexDocument(
        content_id=cid,
        user_id=user,
        platform=platform,
        content_type="post",  # type: ignore[arg-type]
        saved_at=datetime(2026, 9, day, tzinfo=KST),
        original_status="available",
        fields={"title": title, "body": body},  # type: ignore[dict-item]
    )


@pytest.fixture
def idx() -> BM25FIndex:
    i = BM25FIndex(WS(), W, B, k1=1.2)
    i.upsert(doc("A", "카페 성수", "카페 라떼 라떼", "instagram", 1))
    i.upsert(doc("B", "공방", "성수 공방 가죽", "youtube", 2))
    i.upsert(doc("C", "라떼", "우유", "instagram", 3))
    return i


AVG_T, AVG_B = 4 / 3, 7 / 3  # title 길이 2,1,1 / body 길이 3,3,1


def _norm(b: float, length: int, avg: float) -> float:
    return 1 - b + b * length / avg


def _idf(df: int, n: int = 3) -> float:
    return math.log(1 + (n - df + 0.5) / (df + 0.5))


def _sat(tf_tilde: float, k1: float = 1.2) -> float:
    return tf_tilde / (k1 + tf_tilde)


def test_bm25f_single_term_hand(idx: BM25FIndex) -> None:
    hits = idx.search(["카페"], HardFilter(), 10)
    tf = 2.0 * 1 / _norm(0.5, 2, AVG_T) + 1.0 * 1 / _norm(0.75, 3, AVG_B)  # 1.6 + 0.8235
    assert [h.content_id for h in hits] == ["A"]
    assert hits[0].score == pytest.approx(_idf(1) * _sat(tf), rel=1e-12)
    assert hits[0].matched_fields == {"title": ["카페"], "body": ["카페"]}


def test_bm25f_multi_term_hand(idx: BM25FIndex) -> None:
    hits = {h.content_id: h.score for h in idx.search(["라떼", "성수"], HardFilter(), 10)}
    # 라떼: A body tf2, C title tf1 → df 2 / 성수: A title tf1, B body tf1 → df 2
    a = _idf(2) * _sat(1.0 * 2 / _norm(0.75, 3, AVG_B)) + _idf(2) * _sat(2.0 * 1 / _norm(0.5, 2, AVG_T))
    b = _idf(2) * _sat(1.0 * 1 / _norm(0.75, 3, AVG_B))
    c = _idf(2) * _sat(2.0 * 1 / _norm(0.5, 1, AVG_T))
    assert hits["A"] == pytest.approx(a, rel=1e-12)
    assert hits["B"] == pytest.approx(b, rel=1e-12)
    assert hits["C"] == pytest.approx(c, rel=1e-12)
    ranked = [h.content_id for h in idx.search(["라떼", "성수"], HardFilter(), 10)]
    assert ranked == sorted(hits, key=lambda k: -hits[k])
    assert [h.rank for h in idx.search(["라떼", "성수"], HardFilter(), 10)] == [1, 2, 3]


def test_duplicate_query_terms_counted_once(idx: BM25FIndex) -> None:
    once = idx.search(["카페"], HardFilter(), 10)[0].score
    twice = idx.search(["카페", "카페"], HardFilter(), 10)[0].score
    assert once == twice


def test_filter_excludes_docs(idx: BM25FIndex) -> None:
    hits = idx.search(["라떼", "성수"], HardFilter(platforms={"youtube"}), 10)
    assert [h.content_id for h in hits] == ["B"]
    hits = idx.search(["라떼"], HardFilter(saved_from=datetime(2026, 9, 2, tzinfo=KST)), 10)
    assert [h.content_id for h in hits] == ["C"]
    assert idx.search(["라떼"], HardFilter(content_types={"video"}), 10) == []


def test_top_n_and_tiebreak() -> None:
    i = BM25FIndex(WS(), W, B)
    for cid in ["d3", "d1", "d2"]:
        i.upsert(doc(cid, "같음", "같음"))
    hits = i.search(["같음"], HardFilter(), 2)
    assert [h.content_id for h in hits] == ["d1", "d2"]  # 동점이면 id 오름차순


def test_upsert_delete_consistency(idx: BM25FIndex) -> None:
    fresh = BM25FIndex(WS(), W, B)
    fresh.upsert(doc("A", "카페 성수", "카페 라떼 라떼", "instagram", 1))
    fresh.upsert(doc("C", "라떼", "우유", "instagram", 3))
    idx.upsert(doc("B", "바뀐 제목", "전혀 다른 본문", "youtube", 2))  # 덮어쓰기
    idx.delete("B")
    idx.delete("없는문서")  # 없는 문서 삭제는 무시
    assert idx.snapshot_state() == fresh.snapshot_state()
    q = ["라떼", "성수", "카페"]
    assert [(h.content_id, h.score) for h in idx.search(q, HardFilter(), 10)] == [
        (h.content_id, h.score) for h in fresh.search(q, HardFilter(), 10)
    ]
    assert idx.search(["공방"], HardFilter(), 10) == []


def test_vocabulary(idx: BM25FIndex) -> None:
    v = idx.vocabulary()
    assert v.contains("라떼") and v.doc_freq("라떼") == 2 and not v.contains("녹차")
    assert ("라떼", 1) in v.candidates_by_jamo("래떼", 1)
    idx.upsert(doc("D", "녹차", "녹차"))
    assert idx.vocabulary().contains("녹차")  # 쓰기 후 어휘 갱신


def test_empty_index_and_query() -> None:
    i = BM25FIndex(WS(), W, B)
    assert i.search(["x"], HardFilter(), 5) == []
    i.upsert(doc("A", "x", "y"))
    assert i.search([], HardFilter(), 5) == []


def test_two_analyzers_on_typo(kiwi: KiwiTokenizer) -> None:
    fw = {"title": 2.0, "body": 1.0}
    morph = BM25FIndex(kiwi, fw, B)
    ngram = BM25FIndex(CharNgramTokenizer(2), fw, B)
    for ix in (morph, ngram):
        ix.upsert(doc("A", "성수동 카페 추천", "성수동 카페 라떼"))
        ix.upsert(doc("B", "연남동 공방", "가죽 공방 클래스"))
    assert morph.analyzer == "morph" and ngram.analyzer == "ngram"
    # 띄어쓰기 오류 '성수동까페': n-gram이 부분 일치로 찾는다
    ng_hits = ngram.search(CharNgramTokenizer(2).query_terms("성수동까페"), HardFilter(), 10)
    assert ng_hits and ng_hits[0].content_id == "A"
    # 형태소 쪽은 동의어 정규형(까페→카페)으로 찾는다
    m_hits = morph.search(kiwi.query_terms("성수동까페"), HardFilter(), 10)
    assert m_hits and m_hits[0].content_id == "A"

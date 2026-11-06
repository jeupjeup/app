"""T5: 지표 함수를 손으로 계산한 값과 비교 (설계서 3.2절)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

import pytest

from jupjup.eval.metrics import (
    PRF,
    mrr_at_k,
    ndcg_at_k,
    percentile,
    recall_at_k,
    set_prf,
    success_at_1,
    time_range_exact,
    time_range_iou,
)
from tests.conftest import KST

REL = {"a": 3, "b": 1, "c": 2}


def test_recall_hand() -> None:
    ranked = ["x", "a", "y", "b", "z", "c"]
    assert recall_at_k(ranked, REL, 5) == pytest.approx(2 / 3)
    assert recall_at_k(ranked, REL, 10) == 1.0
    assert recall_at_k(ranked, REL, 1) == 0.0
    assert recall_at_k(ranked, {}, 10) == 0.0


def test_success_at_1_hand() -> None:
    assert success_at_1(["a", "x"], REL) == 1.0
    assert success_at_1(["b", "a"], REL) == 0.0  # 1위가 등급 1이면 실패
    assert success_at_1([], REL) == 0.0


def test_mrr_hand() -> None:
    assert mrr_at_k(["x", "b", "c"], REL) == pytest.approx(1 / 3)  # b는 등급 1이라 건너뜀
    assert mrr_at_k(["x"] * 10 + ["a"], REL) == 0.0
    assert mrr_at_k(["b"], REL, min_grade=1) == 1.0


def test_ndcg_hand() -> None:
    ranked = ["b", "x", "a"]
    dcg = (2**1 - 1) / math.log2(2) + 0 + (2**3 - 1) / math.log2(4)  # 1 + 3.5 = 4.5
    idcg = (2**3 - 1) / math.log2(2) + (2**2 - 1) / math.log2(3) + (2**1 - 1) / math.log2(4)
    assert ndcg_at_k(ranked, REL, 10) == pytest.approx(dcg / idcg)
    assert ndcg_at_k(["a", "c", "b"], REL, 10) == pytest.approx(1.0)
    assert ndcg_at_k(["x"], {}, 10) == 0.0


def test_ndcg_k_cut() -> None:
    rel = {"a": 3}
    assert ndcg_at_k(["x", "a"], rel, 1) == 0.0
    assert ndcg_at_k(["x", "a"], rel, 2) == pytest.approx(1 / math.log2(3))


@dataclass
class R:
    start: datetime
    end: datetime


def d(day: int) -> datetime:
    return datetime(2026, 9, day, tzinfo=KST)


def test_time_exact_and_iou() -> None:
    assert time_range_exact(R(d(1), d(11)), R(d(1), d(11)))
    assert not time_range_exact(R(d(1), d(11)), R(d(1), d(12)))
    assert time_range_exact(None, None)
    assert not time_range_exact(R(d(1), d(2)), None)
    assert not time_range_exact(None, R(d(1), d(2)))
    assert time_range_iou(R(d(1), d(11)), R(d(6), d(16))) == pytest.approx(5 / 15)
    assert time_range_iou(R(d(1), d(3)), R(d(5), d(7))) == 0.0
    assert time_range_iou(None, None) == 1.0
    assert time_range_iou(None, R(d(1), d(2))) == 0.0


def test_prf_micro() -> None:
    a = set_prf({"instagram"}, {"instagram"})
    b = set_prf({"youtube", "news"}, {"news"})
    c = set_prf(set(), {"blog"})
    total = a + b + c
    assert total == PRF(tp=2, fp=1, fn=1)
    assert total.precision == pytest.approx(2 / 3)
    assert total.recall == pytest.approx(2 / 3)
    assert total.f1 == pytest.approx(2 / 3)
    assert PRF().f1 == 1.0  # 예측도 정답도 없으면 완전 일치


def test_percentile() -> None:
    xs = [float(i) for i in range(1, 101)]
    assert percentile(xs, 95) == 95.0
    assert percentile(xs, 50) == 50.0
    assert percentile([], 95) == 0.0

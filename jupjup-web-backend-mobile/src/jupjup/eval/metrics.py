"""평가 지표 (설계서 3.2절). 순수 함수, 외부 의존 없음."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


class _Range(Protocol):
    @property
    def start(self) -> datetime: ...
    @property
    def end(self) -> datetime: ...


def recall_at_k(ranked: Sequence[str], relevance: Mapping[str, int], k: int) -> float:
    rel = {d for d, g in relevance.items() if g >= 1}
    if not rel:
        return 0.0
    return len(rel.intersection(ranked[:k])) / len(rel)


def success_at_1(ranked: Sequence[str], relevance: Mapping[str, int]) -> float:
    return 1.0 if ranked and relevance.get(ranked[0], 0) >= 2 else 0.0


def mrr_at_k(ranked: Sequence[str], relevance: Mapping[str, int], k: int = 10, min_grade: int = 2) -> float:
    for i, d in enumerate(ranked[:k], 1):
        if relevance.get(d, 0) >= min_grade:
            return 1.0 / i
    return 0.0


def dcg(grades: Sequence[int]) -> float:
    return float(sum((2.0**g - 1.0) / math.log2(i + 1) for i, g in enumerate(grades, 1)))


def ndcg_at_k(ranked: Sequence[str], relevance: Mapping[str, int], k: int = 10) -> float:
    ideal = dcg(sorted((g for g in relevance.values() if g > 0), reverse=True)[:k])
    if ideal == 0:
        return 0.0
    return dcg([relevance.get(d, 0) for d in ranked[:k]]) / ideal


def time_range_exact(pred: _Range | None, gold: _Range | None) -> bool:
    if gold is None or pred is None:
        return gold is None and pred is None
    return pred.start == gold.start and pred.end == gold.end


def time_range_iou(pred: _Range | None, gold: _Range | None) -> float:
    if gold is None or pred is None:
        return 1.0 if gold is None and pred is None else 0.0
    ps, pe, gs, ge = pred.start, pred.end, gold.start, gold.end
    inter = (min(pe, ge) - max(ps, gs)).total_seconds()
    union = (max(pe, ge) - min(ps, gs)).total_seconds()
    if union <= 0:
        return 0.0
    return max(0.0, inter) / union


@dataclass(frozen=True)
class PRF:
    tp: int = 0
    fp: int = 0
    fn: int = 0

    def __add__(self, other: PRF) -> PRF:
        return PRF(self.tp + other.tp, self.fp + other.fp, self.fn + other.fn)

    @property
    def precision(self) -> float:
        d = self.tp + self.fp
        return self.tp / d if d else 1.0

    @property
    def recall(self) -> float:
        d = self.tp + self.fn
        return self.tp / d if d else 1.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if p + r else 0.0


def set_prf(pred: set[str], gold: set[str]) -> PRF:
    return PRF(tp=len(pred & gold), fp=len(pred - gold), fn=len(gold - pred))


def mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def percentile(xs: Sequence[float], q: float) -> float:
    """최근접 순위 방식 백분위수 (q: 0~100)."""
    if not xs:
        return 0.0
    s = sorted(xs)
    idx = max(0, min(len(s) - 1, math.ceil(q / 100 * len(s)) - 1))
    return s[idx]

"""Pure metrics for ingest-analysis evaluation (design section 3.5.2)."""

from __future__ import annotations

import math
import statistics
import unicodedata
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

from jupjup.text.lexicon import Lexicon
from jupjup.text.normalize import jamo_distance, normalize_text


@dataclass(frozen=True)
class PRF:
    tp: int = 0
    fp: int = 0
    fn: int = 0

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else 1.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else 1.0

    @property
    def f1(self) -> float:
        denominator = 2 * self.tp + self.fp + self.fn
        return 2 * self.tp / denominator if denominator else 1.0

    def __add__(self, other: PRF) -> PRF:
        return PRF(self.tp + other.tp, self.fp + other.fp, self.fn + other.fn)


def normalize_eval_term(value: str, lexicon: Lexicon | None = None) -> str:
    """NFKC, whitespace removal, lowercase, then synonym canonicalization."""
    normalized = normalize_text(unicodedata.normalize("NFKC", value)).replace(" ", "")
    return lexicon.canonical(normalized) if lexicon is not None else normalized


def tag_prf(
    predicted: Iterable[str],
    representative: Iterable[str],
    acceptable: Iterable[str] = (),
    *,
    lexicon: Lexicon | None = None,
) -> PRF:
    """Score representative tags; acceptable-only predictions are not false positives."""
    pred = {normalize_eval_term(value, lexicon) for value in predicted}
    gold = {normalize_eval_term(value, lexicon) for value in representative}
    allowed = {normalize_eval_term(value, lexicon) for value in acceptable}
    return PRF(tp=len(pred & gold), fp=len(pred - gold - allowed), fn=len(gold - pred))


def _maximum_matches[L, R](left: Sequence[L], right: Sequence[R], matches: Callable[[L, R], bool]) -> int:
    """Maximum bipartite matching, so duplicate/ambiguous aliases cannot be double-counted."""
    paired_left: dict[int, int] = {}

    def augment(right_index: int, seen: set[int]) -> bool:
        for left_index, candidate in enumerate(left):
            if left_index in seen or not matches(candidate, right[right_index]):
                continue
            seen.add(left_index)
            previous = paired_left.get(left_index)
            if previous is None or augment(previous, seen):
                paired_left[left_index] = right_index
                return True
        return False

    return sum(augment(index, set()) for index in range(len(right)))


def entity_prf(
    predicted: Sequence[tuple[str, str]],
    gold: Sequence[tuple[str, str]],
    *,
    lexicon: Lexicon | None = None,
) -> PRF:
    """Match (type, name) using aliases/synonyms and a Jamo edit distance of at most one."""

    def matches(left: tuple[str, str], right: tuple[str, str]) -> bool:
        left_type, left_name = left
        right_type, right_name = right
        if left_type != right_type:
            return False
        lhs = normalize_eval_term(left_name, lexicon)
        rhs = normalize_eval_term(right_name, lexicon)
        return lhs == rhs or jamo_distance(lhs, rhs, max_distance=1) <= 1

    tp = _maximum_matches(predicted, gold, matches)
    return PRF(tp=tp, fp=len(predicted) - tp, fn=len(gold) - tp)


def name_prf(
    predicted: Sequence[str],
    gold: Sequence[str],
    *,
    lexicon: Lexicon | None = None,
) -> PRF:
    """Location-name scoring with the same normalization and typo allowance as entities."""

    def matches(left: str, right: str) -> bool:
        lhs = normalize_eval_term(left, lexicon)
        rhs = normalize_eval_term(right, lexicon)
        return lhs == rhs or jamo_distance(lhs, rhs, max_distance=1) <= 1

    tp = _maximum_matches(predicted, gold, matches)
    return PRF(tp=tp, fp=len(predicted) - tp, fn=len(gold) - tp)


def accuracy(correct: Iterable[bool]) -> float | None:
    values = list(correct)
    return sum(values) / len(values) if values else None


def save_intent_correct(predicted: Iterable[str], labels: Iterable[str], acceptable: Iterable[str] = ()) -> bool:
    accepted = set(labels) | set(acceptable)
    return bool(set(predicted) & accepted)


def percentile(values: Sequence[float], percentile_value: float) -> float:
    """Linear-interpolated percentile using the inclusive [0, 1] convention."""
    if not values:
        return 0.0
    if not 0.0 <= percentile_value <= 1.0:
        raise ValueError("percentile은 0과 1 사이여야 합니다")
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile_value
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def latency_summary(values: Sequence[float]) -> tuple[float, float]:
    return (statistics.median(values) if values else 0.0, percentile(values, 0.95))

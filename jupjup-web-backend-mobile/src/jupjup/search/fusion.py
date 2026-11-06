"""검색기 결과 결합 (설계서 5.3.4절)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from jupjup.search.types import FusedCandidate, RetrievalHit


def fuse_rrf(
    lists: Mapping[str, Sequence[RetrievalHit]], weights: Mapping[str, float], k: int = 60, top_n: int = 50
) -> list[FusedCandidate]:
    """가중 RRF: score(d) = Σ_r w_r / (k + rank_r(d)). 동점이면 content_id 오름차순."""
    scores: dict[str, float] = {}
    ranks: dict[str, dict[str, int]] = {}
    raw: dict[str, dict[str, float]] = {}
    for name in sorted(lists):  # 이름 순서로 더해 결정성을 지킨다
        w = weights.get(name, 0.0)
        for hit in lists[name]:
            if w:
                scores[hit.content_id] = scores.get(hit.content_id, 0.0) + w / (k + hit.rank)
            else:
                scores.setdefault(hit.content_id, 0.0)
            ranks.setdefault(hit.content_id, {})[name] = hit.rank
            raw.setdefault(hit.content_id, {})[name] = hit.score
    ordered = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))[:top_n]
    return [FusedCandidate(content_id=c, rrf_score=s, ranks=ranks[c], raw_scores=raw[c]) for c, s in ordered]


def fuse_combsum(
    lists: Mapping[str, Sequence[RetrievalHit]], weights: Mapping[str, float], top_n: int = 50
) -> list[FusedCandidate]:
    """min-max 정규화 후 가중 합 (평가 비교용 대안)."""
    scores: dict[str, float] = {}
    ranks: dict[str, dict[str, int]] = {}
    raw: dict[str, dict[str, float]] = {}
    for name in sorted(lists):
        hits = lists[name]
        if not hits:
            continue
        lo = min(h.score for h in hits)
        hi = max(h.score for h in hits)
        span = hi - lo
        w = weights.get(name, 0.0)
        for h in hits:
            norm = (h.score - lo) / span if span > 0 else 1.0
            scores[h.content_id] = scores.get(h.content_id, 0.0) + w * norm
            ranks.setdefault(h.content_id, {})[name] = h.rank
            raw.setdefault(h.content_id, {})[name] = h.score
    ordered = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))[:top_n]
    return [FusedCandidate(content_id=c, rrf_score=s, ranks=ranks[c], raw_scores=raw[c]) for c, s in ordered]

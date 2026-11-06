"""결정적 특징 기반 재순위 (설계서 5.4.1절)."""

from __future__ import annotations

import math
from datetime import datetime

from jupjup.config import RerankWeights
from jupjup.index.document import IndexField
from jupjup.index.registry import UserIndex
from jupjup.query.settings import QuerySettings
from jupjup.query.understanding import ParsedQuery
from jupjup.search.filters import ResolvedFilters
from jupjup.search.types import FusedCandidate, MatchReason, ScoredCandidate
from jupjup.text.lexicon import Lexicon
from jupjup.text.terms import unique_strings

_MATCH_FIELDS: tuple[IndexField, ...] = ("title", "tags_user", "tags_ai", "detail", "summary", "user_note")
_STRONG_FIELDS: tuple[IndexField, ...] = ("title", "tags_user", "tags_ai")
_PURPOSE_FIELDS: tuple[IndexField, ...] = ("detail", "user_note")


def _coverage(query_terms: list[str], document_terms: set[str]) -> float:
    unique = unique_strings(query_terms)
    if not unique:
        return 0.0
    return sum(term in document_terms for term in unique) / len(unique)


class FeatureReranker:
    """RRF 후보를 해석 가능한 특징의 선형 결합으로 정렬한다."""

    def __init__(self, weights: RerankWeights, lexicon: Lexicon, query_settings: QuerySettings | None = None) -> None:
        self.weights = weights
        self.lexicon = lexicon
        self.query_settings = query_settings or QuerySettings()

    def rerank(
        self,
        parsed: ParsedQuery,
        filters: ResolvedFilters,
        candidates: list[FusedCandidate],
        index: UserIndex,
        now: datetime,
    ) -> list[ScoredCandidate]:
        if not candidates:
            return []
        max_rrf = max(candidate.rrf_score for candidate in candidates) or 1.0
        ngram_query = parsed.residual_text or parsed.semantic_query
        query_ngrams = unique_strings(index.ngram.tokenizer.query_terms(ngram_query))
        scored = [
            self._score(parsed, filters, candidate, index, now, max_rrf, query_ngrams) for candidate in candidates
        ]
        return sorted(
            scored,
            key=lambda candidate: (
                -candidate.final_score,
                -index.meta[candidate.content_id].saved_at.timestamp(),
                candidate.content_id,
            ),
        )

    def _score(
        self,
        parsed: ParsedQuery,
        filters: ResolvedFilters,
        candidate: FusedCandidate,
        index: UserIndex,
        now: datetime,
        max_rrf: float,
        query_ngrams: list[str],
    ) -> ScoredCandidate:
        content_id = candidate.content_id
        meta = index.meta[content_id]
        match_terms = index.morph.doc_terms(content_id, _MATCH_FIELDS)
        strong_terms = index.morph.doc_terms(content_id, _STRONG_FIELDS)
        purpose_terms = index.morph.doc_terms(content_id, _PURPOSE_FIELDS)
        document_ngrams = index.ngram.doc_terms(content_id)

        kw_coverage = _coverage(parsed.keywords, match_terms)
        kw_strong = float(any(term in strong_terms for term in parsed.keywords))
        corrected_strong = float(
            any(
                correction.kind == "spelling"
                and len(correction.from_) >= self.query_settings.long_spelling_term_length
                and correction.to in strong_terms
                for correction in parsed.corrections
            )
        )
        ngram_coverage = _coverage(query_ngrams, document_ngrams)
        time_score = self._time_score(parsed, filters, meta.saved_at)
        facet_soft = self._facet_soft(filters, meta.platform, meta.content_type)
        purpose_match = float(any(term in purpose_terms for term in parsed.purpose_terms))
        vec_sim = candidate.raw_scores.get("vector", 0.0)
        age_days = max(0.0, (now - meta.saved_at).total_seconds() / 86_400)
        recency = math.exp(-age_days / self.weights.recency_decay_days)
        rrf_norm = candidate.rrf_score / max_rrf

        features = {
            "rrf_norm": rrf_norm,
            "kw_coverage": kw_coverage,
            "kw_strong": kw_strong,
            "kw_corrected_strong": corrected_strong,
            "time_score": time_score,
            "facet_soft": facet_soft,
            "purpose_match": purpose_match,
            "vec_sim": vec_sim,
            "recency": recency,
            # 게이트 판정용 진단 특징. 선형 점수에는 직접 더하지 않는다.
            "kw_field_match": float(bool(set(parsed.keywords) & match_terms)),
            "ngram_coverage": ngram_coverage,
            "time_exact_match": float(parsed.time_range is not None and parsed.time_range.contains(meta.saved_at)),
            "time_margin_match": float(
                parsed.time_range is not None
                and not parsed.time_range.contains(meta.saved_at)
                and time_score > 0
            ),
        }
        w = self.weights
        final = (
            w.rrf_norm * rrf_norm
            + w.kw_coverage * kw_coverage
            + w.kw_strong * kw_strong
            + w.time_score * time_score
            + w.facet_soft * facet_soft
            + w.purpose_match * purpose_match
            + w.vec_sim * vec_sim
            + w.recency * recency
        )
        return ScoredCandidate(
            content_id=content_id,
            final_score=final,
            features=features,
            match_reasons=self._reasons(parsed, filters, meta.platform, meta.content_type, features, match_terms),
            ranks=candidate.ranks,
            rrf_score=candidate.rrf_score,
        )

    def _time_score(self, parsed: ParsedQuery, filters: ResolvedFilters, saved_at: datetime) -> float:
        exact = parsed.time_range
        if exact is None:
            return 0.0
        if exact.contains(saved_at):
            return 1.0
        window = filters.saved_window
        if window is None:
            window_start = parsed.time_window.start if parsed.time_window else None
            window_end = parsed.time_window.end if parsed.time_window else None
        else:
            window_start, window_end = window.start, window.end
        if window_start is None or window_end is None or not window_start <= saved_at < window_end:
            return 0.0
        if saved_at < exact.start:
            span = (exact.start - window_start).total_seconds()
            progress = (saved_at - window_start).total_seconds() / span if span > 0 else 1.0
        else:
            span = (window_end - exact.end).total_seconds()
            progress = (window_end - saved_at).total_seconds() / span if span > 0 else 1.0
        floor = self.weights.time_window_floor
        return floor + (1.0 - floor) * max(0.0, min(1.0, progress))

    def _facet_soft(self, filters: ResolvedFilters, platform: str, content_type: str) -> float:
        platforms = set(filters.soft_platforms)
        content_types = set(filters.soft_content_types)
        if filters.platforms is not None and filters.platforms.strength == "soft":
            platforms.update(filters.platforms.value)
        if filters.content_types is not None and filters.content_types.strength == "soft":
            content_types.update(filters.content_types.value)
        expanded_types = self.lexicon.expand_content_types(content_types)
        return float(platform in platforms or content_type in expanded_types)

    def _reasons(
        self,
        parsed: ParsedQuery,
        filters: ResolvedFilters,
        platform: str,
        content_type: str,
        features: dict[str, float],
        match_terms: set[str],
    ) -> list[MatchReason]:
        reasons: list[MatchReason] = []
        hits = [term for term in parsed.keywords if term in match_terms]
        if hits:
            reasons.append(MatchReason(type="keyword", field="title/tags/detail/summary/user_note", terms=hits))
        if features["vec_sim"] > 0:
            reasons.append(MatchReason(type="semantic", detail=f"의미 유사도 {features['vec_sim']:.2f}"))
        if features["time_exact_match"] and parsed.time_range is not None:
            reasons.append(MatchReason(type="time", detail=f"{parsed.time_range.expression} 저장"))
        elif features["time_margin_match"] and parsed.time_range is not None:
            reasons.append(MatchReason(type="time_near", detail=f"기간 근접 ({parsed.time_range.expression})"))
        hard_platforms = set(parsed.hard_platforms())
        if platform in hard_platforms or platform in filters.soft_platforms:
            reasons.append(MatchReason(type="platform", detail=self.lexicon.platform_label(platform)))
        expanded = self.lexicon.expand_content_types(set(parsed.hard_content_types()) | set(filters.soft_content_types))
        if content_type in expanded:
            reasons.append(MatchReason(type="content_type", detail=self.lexicon.content_type_label(content_type)))
        if features["purpose_match"]:
            reasons.append(MatchReason(type="purpose", terms=parsed.purpose_terms))
        return reasons

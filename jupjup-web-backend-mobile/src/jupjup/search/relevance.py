"""계획·후보 집합·현재 시각에 의존하지 않는 관련도 평가."""

from __future__ import annotations

import math

from jupjup.config import SearchSettings
from jupjup.index.document import IndexField
from jupjup.index.registry import UserIndex
from jupjup.query.understanding import ParsedQuery
from jupjup.search.filters import ResolvedFilters
from jupjup.search.relaxation import expanded_time_bounds
from jupjup.search.types import (
    CANONICAL_RELAXATION_ORDER,
    CandidateEvidence,
    EvidenceProfile,
    EvidenceSignal,
    RelaxationName,
)
from jupjup.text.lexicon import Lexicon
from jupjup.text.normalize import to_jamo
from jupjup.text.terms import unique_strings

_FIELD_WEIGHTS: dict[IndexField, float] = {
    "title": 1.0,
    "tags_user": 1.0,
    "tags_ai": 1.0,
    "detail": 0.8,
    "user_note": 0.8,
    "summary": 0.6,
    "body": 0.6,
    "ocr": 0.4,
    "author": 0.4,
}
_PURPOSE_FIELDS: tuple[IndexField, ...] = ("detail", "user_note")


class RelevanceScorer:
    def __init__(
        self,
        settings: SearchSettings,
        lexicon: Lexicon,
        model_id: str,
    ) -> None:
        self.search_settings = settings
        self.settings = settings.relevance
        self.relaxation = settings.relaxation
        self.lexicon = lexicon
        self.model_id = model_id

    def score(
        self,
        parsed: ParsedQuery,
        content_id: str,
        index: UserIndex,
        semantic_raw: float,
        original_filters: ResolvedFilters,
    ) -> CandidateEvidence:
        semantic, calibration_version = self._semantic(semantic_raw)
        original_terms = unique_strings(parsed.original_terms or parsed.raw_keywords)
        original_lexical = self._weighted_original_coverage(original_terms, content_id, index)

        original_set = set(original_terms)
        corrections = {
            correction.to: correction.confidence for correction in parsed.corrections if correction.confidence >= 0.90
        }
        spelling = {correction.to for correction in parsed.corrections if correction.kind == "spelling"}
        canonical_extra = [
            term
            for term in parsed.canonical_terms or parsed.keywords
            if term not in original_set and term in corrections
        ]
        canonical_lexical = self._confidence_coverage(canonical_extra, corrections, content_id, index)

        phrase_text = parsed.residual_text or parsed.semantic_text_original or parsed.semantic_query
        query_ngrams = unique_strings(index.ngram.tokenizer.query_terms(phrase_text))
        phrase = self._coverage(query_ngrams, index.ngram.doc_terms(content_id))
        purpose_terms = unique_strings(
            synonym for term in parsed.purpose_terms for synonym in (term, *self.lexicon.synonyms(term))
        )
        purpose = sum(
            any(term in index.morph.doc_terms(content_id, (field,)) for term in purpose_terms)
            for field in _PURPOSE_FIELDS
        ) / len(_PURPOSE_FIELDS)

        original_key, key_coverage = self._key_coverage(parsed, original_terms, corrections, content_id, index)
        # phrase는 같은 원형 어절의 문자 n-gram이므로 핵심어 일치에 더하지 않고 대안으로만 본다.
        phrase_support = self.settings.phrase_evidence_discount * phrase
        lexical_support = max(key_coverage, phrase_support)
        semantic_floor = self.settings.semantic_evidence_floors.get(
            self.model_id,
            self.settings.semantic_evidence_floors["hashing-v1"],
        )
        lexical_floor = self.settings.lexical_evidence_floor
        signals: list[EvidenceSignal] = []
        if semantic >= semantic_floor:
            signals.append("semantic")
        if max(original_key, phrase_support) >= lexical_floor:
            signals.append("lexical")
        elif key_coverage >= lexical_floor:
            signals.append("canonical")
        if purpose > 0.0:
            signals.append("purpose")
        corroboration = 1.0 if len(signals) >= 2 else 0.0
        profile: EvidenceProfile
        if len(signals) >= 2:
            profile = "corroborated"
        elif signals == ["semantic"]:
            profile = "semantic-only"
        else:
            profile = "lexical-only"

        w = self.settings
        logit = (
            w.intercept
            + w.beta_semantic * semantic
            + w.beta_original * original_lexical
            + w.beta_canonical * canonical_lexical
            + w.beta_phrase * phrase
            + w.beta_purpose * purpose
            + w.beta_corroboration * corroboration
        )
        relevance = 1.0 / (1.0 + math.exp(-logit))
        query_violations = self._query_violations(parsed, original_filters, content_id, index)
        request_violations = self._request_lock_violations(original_filters, content_id, index)
        soft_facet_cost = self._soft_facet_cost(original_filters, content_id, index)
        facet_cost = sum(self._cost(name) for name in query_violations) + soft_facet_cost
        return CandidateEvidence(
            content_id=content_id,
            relevance=relevance,
            relevance_base=relevance,
            semantic=semantic,
            semantic_raw=semantic_raw,
            original_lexical=original_lexical,
            canonical_lexical=canonical_lexical,
            phrase=phrase,
            purpose=purpose,
            corroboration=corroboration,
            key_coverage=key_coverage,
            lexical_support=lexical_support,
            signals=tuple(signals),
            evidence_profile=profile,
            query_facet_violations=query_violations,
            request_lock_violations=request_violations,
            facet_cost=facet_cost,
            soft_facet_cost=soft_facet_cost,
            correction_contribution=self._confidence_coverage(
                [term for term in canonical_extra if term in spelling], corrections, content_id, index
            ),
            model_id=self.model_id,
            calibration_version=calibration_version,
            relevance_version=w.version,
        )

    def apply_cross(
        self,
        evidence: CandidateEvidence,
        cross: float | None,
        cross_logit: float | None = None,
    ) -> CandidateEvidence:
        """Recompute context-independent R with Q-RA2's cross evidence profile."""
        settings = self.search_settings.relevance_v3
        lexical_signal = next(
            (signal for signal in evidence.signals if signal in {"lexical", "canonical"}),
            None,
        )
        # semantic과 cross는 같은 의미 계열이다. cross는 floor 이상일 때만 유효 신호로 센다 (설계 4.2절 2).
        # semantic 신호 여부는 v2의 model별 증거 floor 판정을 그대로 쓴다.
        cross_active = cross is not None and cross >= settings.cross_signal_floor
        semantic_signal = "semantic" in evidence.signals
        semantic_active = semantic_signal or cross_active
        families = int(semantic_active) + int(lexical_signal is not None) + int(evidence.purpose > 0.0)
        signals: list[EvidenceSignal] = []
        if semantic_signal:
            signals.append("semantic")
        if cross_active:
            signals.append("cross")
        if lexical_signal is not None:
            signals.append(lexical_signal)
        if evidence.purpose > 0.0:
            signals.append("purpose")
        corroboration = 1.0 if families >= 2 else 0.0
        if families >= 2:
            profile: EvidenceProfile = "corroborated"
        elif semantic_active:
            profile = "semantic-only"
        else:
            profile = "lexical-only"
        logit = (
            settings.intercept
            + settings.beta_semantic * evidence.semantic
            + settings.beta_original * evidence.original_lexical
            + settings.beta_canonical * evidence.canonical_lexical
            + settings.beta_phrase * evidence.phrase
            + settings.beta_purpose * evidence.purpose
            + settings.beta_corroboration * corroboration
            + (settings.beta_cross * cross if cross is not None else 0.0)
        )
        relevance = 1.0 / (1.0 + math.exp(-logit))
        return evidence.model_copy(
            update={
                "relevance": relevance,
                "relevance_base": evidence.relevance_base,
                "cross": cross,
                "cross_logit": cross_logit,
                "rerank_scored": cross is not None,
                "signals": tuple(signals),
                "evidence_profile": profile,
                "corroboration": corroboration,
                "relevance_version": settings.version,
                "relevance_profile": "v3-cross",
            }
        )

    def _semantic(self, raw: float) -> tuple[float, str]:
        calibration = self.settings.calibrations.get(self.model_id)
        if calibration is None:
            calibration = self.settings.calibrations["hashing-v1"]
        value = (raw - calibration.low) / (calibration.high - calibration.low)
        return max(0.0, min(1.0, value)), calibration.version

    def _key_coverage(
        self,
        parsed: ParsedQuery,
        terms: list[str],
        corrections: dict[str, float],
        content_id: str,
        index: UserIndex,
    ) -> tuple[float, float]:
        """원형 어절별로 가장 강한 일치 하나만 세는 핵심어 coverage. (원형만, 교정 포함) 순서로 반환한다.

        `트랜치코트 → 트랜치/코트`처럼 한 어절에서 나온 하위어는 분모를 늘리지 않고, 하위어 일치는
        어절 길이 대비 비율만큼만 인정한다. 고신뢰 교정·동의어는 같은 어절의 대안 증거이며, 그 개념이
        문서에 있다는 증거의 크기는 교정 신뢰도다 (R의 βo > βc 순위 우선은 별도로 유지한다).
        """
        if not terms:
            return 0.0, 0.0
        # 형태소 원형은 어절과 글자가 다를 수 있어(선크린 → 선크리+ㄴ) 자모 단위로 소속 어절을 찾는다.
        words = [(word, to_jamo(word)) for word in (parsed.residual_text or " ".join(terms)).split()]
        groups: dict[str, list[str]] = {}
        for term in terms:
            jamo = to_jamo(term)
            owner = next((word for word, word_jamo in words if jamo in word_jamo), term)
            groups.setdefault(owner, []).append(term)
        expansions: dict[str, list[tuple[str, float]]] = {}
        for correction in parsed.corrections:
            confidence = corrections.get(correction.to)
            if confidence is not None:
                expansions.setdefault(correction.from_, []).append((correction.to, confidence))
        original_total = 0.0
        expanded_total = 0.0
        total_weight = 0.0
        for members in groups.values():
            group_weight = (
                self.settings.weak_lexical_weight
                if all(term in self.settings.weak_lexical_terms for term in members)
                else 1.0
            )
            head = max(len(term) for term in members)
            original = 0.0
            expanded = 0.0
            for term in members:
                share = len(term) / head
                original = max(original, share * self._field_coverage([term], content_id, index))
                for target, confidence in expansions.get(term, []):
                    match = self._field_coverage([target], content_id, index)
                    expanded = max(expanded, share * confidence * match)
            original_total += group_weight * original
            expanded_total += group_weight * max(original, expanded)
            total_weight += group_weight
        return original_total / total_weight, expanded_total / total_weight

    @staticmethod
    def _coverage(terms: list[str], document_terms: set[str]) -> float:
        terms = unique_strings(terms)
        return sum(term in document_terms for term in terms) / len(terms) if terms else 0.0

    @staticmethod
    def _field_coverage(terms: list[str], content_id: str, index: UserIndex) -> float:
        terms = unique_strings(terms)
        if not terms:
            return 0.0
        total = 0.0
        for term in terms:
            total += max(
                (
                    weight
                    for field, weight in _FIELD_WEIGHTS.items()
                    if term in index.morph.doc_terms(content_id, (field,))
                ),
                default=0.0,
            )
        return total / len(terms)

    def _weighted_original_coverage(self, terms: list[str], content_id: str, index: UserIndex) -> float:
        weighted = [
            (
                term,
                self.settings.weak_lexical_weight if term in self.settings.weak_lexical_terms else 1.0,
            )
            for term in unique_strings(terms)
        ]
        denominator = sum(weight for _, weight in weighted)
        if denominator == 0.0:
            return 0.0
        return sum(weight * self._field_coverage([term], content_id, index) for term, weight in weighted) / denominator

    def _confidence_coverage(
        self,
        terms: list[str],
        confidences: dict[str, float],
        content_id: str,
        index: UserIndex,
    ) -> float:
        terms = unique_strings(terms)
        if not terms:
            return 0.0
        total = 0.0
        for term in terms:
            field_score = self._field_coverage([term], content_id, index)
            total += field_score * confidences.get(term, 1.0)
        return total / len(terms)

    def _query_violations(
        self,
        parsed: ParsedQuery,
        original_filters: ResolvedFilters,
        content_id: str,
        index: UserIndex,
    ) -> tuple[RelaxationName, ...]:
        meta = index.meta[content_id]
        violations: set[RelaxationName] = set()
        query_time_active = (
            original_filters.saved_window is not None and original_filters.saved_window.origin == "query"
        )
        if query_time_active and parsed.time_range is not None and not parsed.time_range.contains(meta.saved_at):
            expanded = expanded_time_bounds(parsed, self.search_settings)
            if expanded is not None and expanded[0] <= meta.saved_at < expanded[1]:
                violations.add("time_window_expanded")
            else:
                violations.add("time_filter_dropped")
        query_platforms = (
            set(parsed.hard_platforms())
            if original_filters.platforms is not None and original_filters.platforms.origin == "query"
            else set()
        )
        if query_platforms and meta.platform not in query_platforms:
            violations.add("platform_filter_dropped")
        query_types = (
            self.lexicon.expand_content_types(set(parsed.hard_content_types()))
            if original_filters.content_types is not None and original_filters.content_types.origin == "query"
            else set()
        )
        if query_types and meta.content_type not in query_types:
            violations.add("content_type_filter_dropped")
        return tuple(name for name in CANONICAL_RELAXATION_ORDER if name in violations)

    def _soft_facet_cost(self, filters: ResolvedFilters, content_id: str, index: UserIndex) -> float:
        meta = index.meta[content_id]
        ratio = self.relaxation.soft_facet_cost_ratio
        cost = 0.0
        if filters.soft_platforms and meta.platform not in filters.soft_platforms:
            cost += ratio * self.relaxation.platform_cost
        soft_types = self.lexicon.expand_content_types(set(filters.soft_content_types))
        if soft_types and meta.content_type not in soft_types:
            cost += ratio * self.relaxation.content_type_cost
        return cost

    def _request_lock_violations(self, filters: ResolvedFilters, content_id: str, index: UserIndex) -> tuple[str, ...]:
        meta = index.meta[content_id]
        violations: list[str] = []
        if filters.platforms is not None and filters.platforms.locked and meta.platform not in filters.platforms.value:
            violations.append("platforms")
        if filters.content_types is not None and filters.content_types.locked:
            allowed = self.lexicon.expand_content_types(set(filters.content_types.value))
            if meta.content_type not in allowed:
                violations.append("content_types")
        window = filters.saved_window
        if window is not None and window.locked:
            before_start = window.start is not None and meta.saved_at < window.start
            after_end = window.end is not None and meta.saved_at >= window.end
            if before_start or after_end:
                violations.append("saved_window")
        return tuple(violations)

    def _cost(self, name: RelaxationName) -> float:
        costs: dict[RelaxationName, float] = {
            "time_window_expanded": self.relaxation.time_expanded_cost,
            "time_filter_dropped": self.relaxation.time_dropped_cost,
            "platform_filter_dropped": self.relaxation.platform_cost,
            "content_type_filter_dropped": self.relaxation.content_type_cost,
            "spelling_expanded": 0.0,
        }
        return costs[name]

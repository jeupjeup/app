"""문맥 독립 관련도 점수에 대한 절대 게이트."""

from __future__ import annotations

from jupjup.config import CrossRelevanceSettings, GateSettings
from jupjup.query.understanding import ParsedQuery
from jupjup.search.types import CandidateEvidence, GateDecision, ScoredCandidate


class RelevanceGate:
    def __init__(
        self,
        settings: GateSettings,
        model_id: str = "hashing-v1",
        v3_settings: CrossRelevanceSettings | None = None,
    ) -> None:
        self.settings = settings
        self.model_id = model_id
        self.v3_settings = v3_settings or CrossRelevanceSettings()

    def threshold(self, parsed: ParsedQuery, evidence: CandidateEvidence) -> float:
        if evidence.relevance_profile == "v3-cross":
            thresholds = {
                "corroborated": self.v3_settings.corroborated_threshold,
                "semantic-only": self.v3_settings.semantic_only_threshold,
                "lexical-only": self.v3_settings.lexical_only_threshold,
            }
            return thresholds[evidence.evidence_profile]
        thresholds = {
            "corroborated": self.settings.corroborated_threshold,
            "semantic-only": self.settings.semantic_only_threshold,
            "lexical-only": self.settings.lexical_only_threshold,
        }
        threshold = thresholds[evidence.evidence_profile]
        if parsed.query_signal_profile == "low-signal":
            threshold = max(threshold, self.settings.low_signal_threshold)
        return threshold

    def evaluate(self, parsed: ParsedQuery, evidence: CandidateEvidence) -> GateDecision:
        threshold = self.threshold(parsed, evidence)
        if evidence.request_lock_violations:
            return self._reject(parsed, evidence, threshold, "request_lock_violation")
        if not evidence.signals:
            return self._reject(parsed, evidence, threshold, "no_evidence")
        # 교정 확장으로만 성립한 어휘 증거 외에 독립 증거가 없는 후보 (INV-11).
        correction_only = evidence.correction_contribution > 0 and evidence.signals == ("canonical",)
        if correction_only:
            return self._reject(parsed, evidence, threshold, "correction_only")
        if evidence.evidence_profile == "lexical-only" and not {"lexical", "canonical"} & set(evidence.signals):
            return self._reject(parsed, evidence, threshold, "lexical_evidence_floor")
        if evidence.relevance_profile == "v3-cross":
            return self._evaluate_v3(parsed, evidence, threshold)
        requires_semantic_floor = (
            evidence.evidence_profile == "semantic-only" or parsed.query_signal_profile == "low-signal"
        )
        if requires_semantic_floor and evidence.semantic < self._semantic_floor():
            return self._reject(parsed, evidence, threshold, "semantic_floor")
        accepted = evidence.relevance >= threshold
        return GateDecision(
            accepted=accepted,
            threshold=threshold,
            signal_profile=parsed.query_signal_profile,
            evidence_profile=evidence.evidence_profile,
            reason="accepted" if accepted else "below_threshold",
        )

    def _evaluate_v3(
        self,
        parsed: ParsedQuery,
        evidence: CandidateEvidence,
        threshold: float,
    ) -> GateDecision:
        settings = self.v3_settings
        if not evidence.rerank_scored:
            accepted = (
                evidence.evidence_profile == "corroborated"
                and evidence.relevance >= settings.unscored_threshold
            )
            return GateDecision(
                accepted=accepted,
                threshold=settings.unscored_threshold,
                signal_profile=parsed.query_signal_profile,
                evidence_profile=evidence.evidence_profile,
                reason="accepted_unscored_tail" if accepted else "rerank_unscored",
            )
        assert evidence.cross is not None
        floors = {
            "corroborated": settings.cross_floor_corroborated,
            "semantic-only": settings.cross_floor_semantic,
            "lexical-only": settings.cross_floor_lexical,
        }
        cross_floor = floors[evidence.evidence_profile]
        if parsed.query_signal_profile == "low-signal":
            cross_floor = max(cross_floor, settings.cross_floor_low_signal)
        if evidence.cross < cross_floor:
            return self._reject(parsed, evidence, threshold, "cross_floor")
        if evidence.evidence_profile == "semantic-only" and evidence.semantic < settings.semantic_floor:
            # Cosine remains an auxiliary condition; cross is the deciding, profile-specific floor.
            return self._reject(parsed, evidence, threshold, "semantic_aux_floor")
        accepted = evidence.relevance >= threshold
        return GateDecision(
            accepted=accepted,
            threshold=threshold,
            signal_profile=parsed.query_signal_profile,
            evidence_profile=evidence.evidence_profile,
            reason="accepted" if accepted else "below_threshold",
        )

    @staticmethod
    def _reject(parsed: ParsedQuery, evidence: CandidateEvidence, threshold: float, reason: str) -> GateDecision:
        return GateDecision(
            accepted=False,
            threshold=threshold,
            signal_profile=parsed.query_signal_profile,
            evidence_profile=evidence.evidence_profile,
            reason=reason,
        )

    def _semantic_floor(self) -> float:
        return self.settings.semantic_floors.get(self.model_id, self.settings.semantic_floors["hashing-v1"])

    def apply(self, parsed: ParsedQuery, scored: list[ScoredCandidate], limit: int) -> list[ScoredCandidate]:
        kept: list[ScoredCandidate] = []
        for candidate in scored:
            if candidate.evidence is None:
                continue
            decision = self.evaluate(parsed, candidate.evidence)
            candidate.gate = decision
            if decision.accepted:
                kept.append(candidate)
            if len(kept) >= limit:
                break
        return kept

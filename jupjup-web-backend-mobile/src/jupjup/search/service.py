"""검색 파이프라인 오케스트레이션 `SearchService` (설계서 5.1절, 5.8.6절).

질의 이해 → 필터 해석 → 검색기 3종 → RRF → 특징 재순위 → 관련도 문턱 → 완화를 조립한다.
검색 파이프라인은 구체 제공자 클래스를 import하지 않는다 (Protocol만 쓴다).
"""

from __future__ import annotations

import time
import uuid
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, cast
from zoneinfo import ZoneInfo

import numpy as np
from pydantic import BaseModel, field_validator

from jupjup.config import GateSettings, SearchSettings
from jupjup.domain.errors import EmbeddingProviderError, InvalidFilterError, InvalidUserError
from jupjup.domain.models import USER_ID_RE, ContentBundle, require_aware
from jupjup.index.document import HardFilter, IndexField
from jupjup.index.registry import UserIndex, UserIndexRegistry
from jupjup.providers.embedding import Embedder, EmbedKind
from jupjup.query.spell import Vocabulary
from jupjup.query.temporal import SEOUL
from jupjup.query.understanding import ParsedQuery, QueryUnderstander
from jupjup.search.cross_rerank import CrossRerankOutcome, CrossRerankStage, RerankWindow
from jupjup.search.filters import FilterResolver, ResolvedFilters, SearchFilters
from jupjup.search.fusion import fuse_combsum, fuse_rrf
from jupjup.search.relevance import RelevanceScorer
from jupjup.search.types import (
    CandidateEvidence,
    EmptyState,
    FusedCandidate,
    GateDecision,
    MatchReason,
    RelaxationDecision,
    RelaxationName,
    RelaxationPlan,
    RetrievalHit,
    ScoredCandidate,
    SearchResult,
    SearchResultItem,
    Suggestion,
)
from jupjup.storage.repositories import ContentRepository
from jupjup.text.terms import unique_strings

_QUERY_EMBED_KIND: EmbedKind = "query"


class SearchRequest(BaseModel):
    user_id: str
    query: str
    filters: SearchFilters | None = None
    limit: int = 10
    now: datetime | None = None
    explain: bool = False

    @field_validator("now")
    @classmethod
    def _aware(cls, v: datetime | None) -> datetime | None:
        return None if v is None else require_aware(v, "now")


class CandidateReranker(Protocol):
    def rerank(
        self,
        parsed: ParsedQuery,
        filters: ResolvedFilters,
        candidates: list[FusedCandidate],
        index: UserIndex,
        now: datetime,
    ) -> list[ScoredCandidate]: ...


class CandidateGate(Protocol):
    settings: GateSettings

    def threshold(self, parsed: ParsedQuery, evidence: CandidateEvidence) -> float: ...
    def evaluate(self, parsed: ParsedQuery, evidence: CandidateEvidence) -> GateDecision: ...
    def apply(self, parsed: ParsedQuery, scored: list[ScoredCandidate], limit: int) -> list[ScoredCandidate]: ...


class Relaxation(Protocol):
    def plans(
        self, filters: ResolvedFilters, parsed: ParsedQuery, vocabulary: Vocabulary | None = None
    ) -> list[RelaxationPlan]: ...


@dataclass
class _Retrieved:
    lists: dict[str, list[RetrievalHit]] = field(default_factory=dict)
    degraded_reasons: list[str] = field(default_factory=list)


@dataclass
class _SearchExecution:
    candidates: list[ScoredCandidate]
    retrieved: _Retrieved
    retrieval_finished_at: float
    completed_at: float
    applied_relaxations: list[str] = field(default_factory=list)
    relaxed_facets: dict[str, list[RelaxationName]] = field(default_factory=dict)
    decision: RelaxationDecision | None = None
    rerank_window: RerankWindow | None = None
    rerank_outcome: CrossRerankOutcome | None = None
    trace_debug: dict[str, object] | None = None


class SearchService:
    def __init__(
        self,
        understander: QueryUnderstander,
        resolver: FilterResolver,
        registry: UserIndexRegistry,
        embedder: Embedder,
        reranker: CandidateReranker | None,
        gate: CandidateGate | None,
        relaxation: Relaxation | None,
        repo: ContentRepository,
        settings: SearchSettings,
        relevance_scorer: RelevanceScorer,
        cross_stage: CrossRerankStage | None = None,
        clock: Callable[[], datetime] | None = None,
        tz: ZoneInfo = SEOUL,
    ) -> None:
        self.understander = understander
        self.resolver = resolver
        self.registry = registry
        self.embedder = embedder
        self.reranker = reranker
        self.gate = gate
        self.relaxation = relaxation
        self.repo = repo
        self.settings = settings
        self.relevance_scorer = relevance_scorer
        self.cross_stage = cross_stage
        self.tz = tz
        self.clock = clock or (lambda: datetime.now(tz))
        self.lexicon = understander.lexicon

    # ------------------------------------------------------------------ 공개 API
    def parse_only(self, query: str, now: datetime, user_id: str) -> ParsedQuery:
        uidx = self._user_index(user_id)
        return self.understander.parse(query, now, uidx.morph.vocabulary())

    def search(self, req: SearchRequest) -> SearchResult:
        t0 = time.perf_counter()
        self._validate_limit(req.limit)
        uidx = self._user_index(req.user_id)
        now = req.now or self.clock()
        parsed = self.understander.parse(req.query, now, uidx.morph.vocabulary())
        parsed_at = time.perf_counter() if req.explain else None
        resolved = self.resolver.resolve(parsed, req.filters)
        t1 = time.perf_counter()

        execution = (
            self._execute_browse(parsed, resolved, uidx, req.limit, explain=req.explain)
            if parsed.filter_only
            else self._execute_ranked(parsed, resolved, uidx, now, req.limit, explain=req.explain)
        )
        items = self._build_items(req, parsed, uidx, execution)
        empty = None if items else self._empty_state(parsed, resolved)
        t4 = time.perf_counter()
        trace_timing = None
        if req.explain:
            assert parsed_at is not None
            execution_timing: dict[str, float] = {}
            if execution.trace_debug is not None and isinstance(execution.trace_debug.get("timing_ms"), dict):
                execution_timing = cast(dict[str, float], execution.trace_debug["timing_ms"])
            trace_timing = {
                "query_understanding": round((parsed_at - t0) * 1000, 2),
                "filter_resolution": round((t1 - parsed_at) * 1000, 2),
                **execution_timing,
                "finalize": round((t4 - execution.completed_at) * 1000, 2),
                "total": round((t4 - t0) * 1000, 2),
            }
        return SearchResult(
            query_id=f"qry_{uuid.uuid4().hex[:20]}",
            query=req.query,
            understanding=parsed,
            overridden_by_request=resolved.overridden,
            results=items,
            browse=parsed.filter_only,
            applied_relaxations=execution.applied_relaxations,
            empty_state=empty,
            degraded=bool(execution.retrieved.degraded_reasons),
            degraded_reasons=execution.retrieved.degraded_reasons,
            rerank_status=self._rerank_status(execution.rerank_outcome),
            timing_ms={
                "understand": round((t1 - t0) * 1000, 2),
                "retrieve": round((execution.retrieval_finished_at - t1) * 1000, 2),
                "rerank": round((execution.completed_at - execution.retrieval_finished_at) * 1000, 2),
                "total": round((t4 - t0) * 1000, 2),
                **(
                    {"cross_rerank": round(execution.rerank_outcome.latency_ms, 2)}
                    if execution.rerank_outcome is not None
                    else {}
                ),
            },
            debug={
                "relaxation_decision": (
                    execution.decision.model_dump(mode="json") if execution.decision is not None else None
                ),
                "rerank": {
                    "window": execution.rerank_window.model_dump(mode="json") if execution.rerank_window else None,
                    "outcome": execution.rerank_outcome.model_dump(mode="json") if execution.rerank_outcome else None,
                },
                "pipeline": {
                    **(execution.trace_debug or {}),
                    "input": {
                        "query": req.query,
                        "user_id": req.user_id,
                        "now": now.isoformat(),
                    },
                    "timing_ms": trace_timing,
                    "components": self._component_debug(parsed, resolved, execution, uidx),
                    "cross_reranker": {
                        "configured": self.cross_stage is not None,
                        "enabled": bool(self.cross_stage is not None and self.cross_stage.settings.enabled),
                        "status": self._rerank_status(execution.rerank_outcome),
                    },
                },
            }
            if req.explain
            else None,
        )

    @staticmethod
    def _rerank_status(outcome: CrossRerankOutcome | None) -> str | None:
        if outcome is None:
            return None
        return "scored" if outcome.status == "scored" else f"skipped:{outcome.skip_reason}"

    def _component_debug(
        self,
        parsed: ParsedQuery,
        resolved: ResolvedFilters,
        execution: _SearchExecution,
        uidx: UserIndex,
    ) -> list[dict[str, object]]:
        """explain 응답에만 쓰는 실제 구성 요소와 단계 입출력 요약."""
        trace = execution.trace_debug or {}
        plans = cast(list[object], trace.get("plans")) if isinstance(trace.get("plans"), list) else []
        scored = (
            cast(list[object], trace.get("scored_candidates"))
            if isinstance(trace.get("scored_candidates"), list)
            else []
        )
        return [
            {
                "stage": "temporal_parse",
                "component": type(self.understander.temporal).__name__,
                "model": None,
                "status": "success",
                "input": parsed.normalized,
                "output": {
                    "time_range": parsed.time_range.model_dump(mode="json") if parsed.time_range else None,
                    "time_window": parsed.time_window.model_dump(mode="json") if parsed.time_window else None,
                },
            },
            {
                "stage": "facet_extract",
                "component": type(self.understander.facets).__name__,
                "model": None,
                "status": "success",
                "input": parsed.normalized,
                "output": {
                    "platforms": [hit.model_dump(mode="json") for hit in parsed.platforms],
                    "content_types": [hit.model_dump(mode="json") for hit in parsed.content_types],
                },
            },
            {
                "stage": "intent_classify",
                "component": type(self.understander.intent).__name__,
                "model": None,
                "status": "success",
                "input": parsed.normalized,
                "output": {"intent": parsed.intent, "filter_only": parsed.filter_only},
            },
            {
                "stage": "bm25f_retrieve",
                "component": type(uidx.morph).__name__,
                "model": f"{uidx.morph.analyzer}+{uidx.ngram.analyzer}",
                "status": "skipped" if parsed.filter_only else "success",
                "input": trace.get("query_terms", {"morph": [], "ngram": []}),
                "output": {"plan_count": len(plans)},
            },
            {
                "stage": "vector_retrieve",
                "component": type(self.embedder).__name__,
                "model": self.embedder.model_id,
                "mode": _QUERY_EMBED_KIND,
                "dimension": self.embedder.dim,
                "status": (
                    "skipped"
                    if parsed.filter_only or not (parsed.semantic_text_original or parsed.semantic_query)
                    else "degraded"
                    if "embedding_unavailable" in execution.retrieved.degraded_reasons
                    else "success"
                ),
                "input": parsed.semantic_text_original or parsed.semantic_query,
                "output": {
                    "degraded_reasons": execution.retrieved.degraded_reasons,
                },
            },
            {
                "stage": "fusion",
                "component": "fuse_rrf" if self.settings.fusion.method == "rrf" else "fuse_combsum",
                "model": None,
                "status": "skipped" if parsed.filter_only else "success",
                "input": {
                    "k": self.settings.fusion.k,
                    "weights": dict(self.settings.fusion.weights),
                },
                "output": {"candidate_count": len(scored)},
            },
            {
                "stage": "feature_rerank",
                # 순위 경로의 특징 점수는 RelevanceScorer가 계산한다 (_execute_ranked).
                "component": type(self.relevance_scorer).__name__,
                "model": self.settings.relevance.version,
                "status": "skipped" if parsed.filter_only else "success",
                "input": {"candidate_count": len(scored)},
                "output": {"candidate_count": len(scored)},
            },
            {
                "stage": "relevance_gate",
                "component": type(self.gate).__name__ if self.gate is not None else None,
                "model": self.settings.relevance.version,
                "status": "skipped" if parsed.filter_only or self.gate is None else "success",
                "input": {"candidate_count": len(scored)},
                "output": {
                    "accepted_count": sum(
                        1
                        for candidate in scored
                        if isinstance(candidate, dict)
                        and isinstance(candidate.get("gate"), dict)
                        and candidate["gate"].get("accepted") is True
                    ),
                    "selected_count": len(execution.candidates),
                },
            },
            {
                "stage": "relaxation",
                "component": type(self.relaxation).__name__ if self.relaxation is not None else None,
                "model": self.settings.relevance.version,
                "minimum_relevance_gain": self.settings.relaxation.minimum_relevance_gain,
                "status": "skipped" if parsed.filter_only or self.relaxation is None else "success",
                "input": resolved.model_dump(mode="json"),
                "output": (
                    execution.decision.model_dump(mode="json") if execution.decision is not None else None
                ),
            },
            {
                "stage": "cross_rerank",
                "component": type(self.cross_stage).__name__ if self.cross_stage is not None else None,
                "model": self.cross_stage.settings.model_id if self.cross_stage is not None else None,
                "status": (
                    "skipped:disabled"
                    if self.cross_stage is None or not self.cross_stage.settings.enabled
                    else self._rerank_status(execution.rerank_outcome) or "skipped"
                ),
                "input": execution.rerank_window.model_dump(mode="json") if execution.rerank_window else None,
                "output": execution.rerank_outcome.model_dump(mode="json") if execution.rerank_outcome else None,
            },
        ]

    # ------------------------------------------------------------------ 실행 경로
    def _validate_limit(self, limit: int) -> None:
        if not 1 <= limit <= self.settings.limit_max:
            raise InvalidFilterError(f"limit은 1~{self.settings.limit_max}이어야 해요.", {"field": "limit"})

    def _execute_browse(
        self,
        parsed: ParsedQuery,
        resolved: ResolvedFilters,
        uidx: UserIndex,
        limit: int,
        *,
        explain: bool,
    ) -> _SearchExecution:
        """필터 전용 질의는 관련도 검색과 완화를 건너뛰고 최신순으로 반환한다."""
        candidates = self._browse(parsed, resolved, uidx, limit)
        retrieval_finished_at = time.perf_counter()
        hard_filter = resolved.to_hard_filter(self.lexicon)
        eligible_count = (
            sum(
                1
                for meta in uidx.meta.values()
                if meta.user_id == uidx.user_id and hard_filter.accepts(meta)
            )
            if explain
            else 0
        )
        return _SearchExecution(
            candidates=candidates,
            retrieved=_Retrieved(),
            retrieval_finished_at=retrieval_finished_at,
            completed_at=time.perf_counter(),
            trace_debug=(
                {
                    "user_id": uidx.user_id,
                    "filters": resolved.model_dump(mode="json"),
                    "plans": [
                        {
                            "plan_id": "browse",
                            "selected": True,
                            "allowed_query_relaxations": [],
                            "hard_filter": hard_filter.model_dump(mode="json"),
                            "eligible_document_count": eligible_count,
                            "retrievers": {},
                            "fused_candidates": [],
                        }
                    ],
                    "fusion": {
                        "method": "skipped_filter_only_browse",
                        "k": self.settings.fusion.k,
                        "weights": dict(self.settings.fusion.weights),
                    },
                    "query_terms": {"morph": [], "ngram": []},
                    "scored_candidates": [],
                    "final_candidate_ids": [candidate.content_id for candidate in candidates],
                    "timing_ms": {
                        "candidate_retrieval": 0.0,
                        "fusion": 0.0,
                        "feature_rerank_gate": 0.0,
                        "relaxation_selection": 0.0,
                    },
                }
                if explain
                else None
            ),
        )

    def _execute_ranked(
        self,
        parsed: ParsedQuery,
        resolved: ResolvedFilters,
        uidx: UserIndex,
        now: datetime,
        limit: int,
        *,
        explain: bool,
    ) -> _SearchExecution:
        """모든 불변 계획의 후보 합집합을 q0의 단일 점수로 한 번 평가한다."""
        del now  # 관련도는 현재 시각에 의존하지 않는다.
        plans = (
            self.relaxation.plans(resolved, parsed, uidx.morph.vocabulary())
            if self.relaxation is not None
            else [RelaxationPlan(plan_id="strict", filters=resolved)]
        )
        retrieved = _Retrieved()
        query_vector: np.ndarray | None = None
        semantic_text = parsed.semantic_text_original or parsed.semantic_query
        if semantic_text:
            try:
                query_vector = self.embedder.embed([semantic_text], _QUERY_EMBED_KIND)[0]
            except EmbeddingProviderError:
                retrieved.degraded_reasons.append("embedding_unavailable")
        plan_ids: dict[str, set[str]] = {}
        fused_by_id: dict[str, FusedCandidate] = {}
        trace_plans: list[dict[str, object]] = []
        retrieval_ms = 0.0
        fusion_ms = 0.0
        for plan in plans:
            hard_filter = plan.filters.to_hard_filter(self.lexicon)
            retrieval_started = time.perf_counter() if explain else None
            plan_retrieved = self._retrieve(
                parsed,
                hard_filter,
                uidx,
                query_vector,
            )
            if retrieval_started is not None:
                retrieval_ms += (time.perf_counter() - retrieval_started) * 1000
            retrieved.degraded_reasons = unique_strings([*retrieved.degraded_reasons, *plan_retrieved.degraded_reasons])
            fusion_started = time.perf_counter() if explain else None
            plan_fused = self._fuse(plan_retrieved.lists)
            if fusion_started is not None:
                fusion_ms += (time.perf_counter() - fusion_started) * 1000
            plan_ids[plan.plan_id] = {candidate.content_id for candidate in plan_fused}
            if explain:
                trace_plans.append(
                    {
                        "plan_id": plan.plan_id,
                        "selected": False,
                        "allowed_query_relaxations": list(plan.allowed_query_relaxations),
                        "hard_filter": hard_filter.model_dump(mode="json"),
                        "eligible_document_count": sum(
                            1
                            for meta in uidx.meta.values()
                            if meta.user_id == uidx.user_id and hard_filter.accepts(meta)
                        ),
                        "retrievers": {
                            name: {
                                "candidate_count": len(hits),
                                "candidates": [hit.model_dump(mode="json") for hit in hits],
                            }
                            for name, hits in plan_retrieved.lists.items()
                        },
                        "fused_candidates": [candidate.model_dump(mode="json") for candidate in plan_fused],
                    }
                )
            for candidate in plan_fused:
                previous = fused_by_id.get(candidate.content_id)
                if previous is None:
                    fused_by_id[candidate.content_id] = candidate
                else:
                    fused_by_id[candidate.content_id] = self._merge_fused(previous, candidate)
        retrieval_finished_at = time.perf_counter()
        feature_started = time.perf_counter() if explain else None
        semantic_scores = uidx.vector.similarities(query_vector, list(fused_by_id)) if query_vector is not None else {}

        evidence_by_id: dict[str, CandidateEvidence] = {
            content_id: self.relevance_scorer.score(
                parsed,
                content_id,
                uidx,
                semantic_scores.get(content_id, 0.0),
                resolved,
            )
            for content_id in fused_by_id
        }

        rerank_window: RerankWindow | None = None
        rerank_outcome: CrossRerankOutcome | None = None
        if self.cross_stage is not None and self.cross_stage.settings.enabled:
            rerank_window = self.cross_stage.select_window(
                {content_id: evidence.relevance for content_id, evidence in evidence_by_id.items()},
                {plan_id: sorted(content_ids) for plan_id, content_ids in plan_ids.items()},
            )
            rerank_outcome = self.cross_stage.score(parsed, rerank_window, uidx.documents)
            if rerank_outcome.status == "scored":
                evidence_by_id = {
                    content_id: self.relevance_scorer.apply_cross(
                        evidence,
                        rerank_outcome.scores.get(content_id),
                        rerank_outcome.logits.get(content_id),
                    )
                    for content_id, evidence in evidence_by_id.items()
                }
            elif rerank_outcome.skip_reason in {"timeout", "error", "busy"}:
                retrieved.degraded_reasons.append(f"reranker_skipped:{rerank_outcome.skip_reason}")

        scored_by_id: dict[str, ScoredCandidate] = {}
        for content_id, fused_candidate in fused_by_id.items():
            evidence = evidence_by_id[content_id]
            gate = self.gate.evaluate(parsed, evidence) if self.gate is not None else self._accept_all(parsed, evidence)
            if (
                self.gate is not None
                and "embedding_unavailable" in retrieved.degraded_reasons
                and not gate.accepted
                and gate.reason == "below_threshold"
                and evidence.evidence_profile == "lexical-only"
                and evidence.relevance >= self._anchored_tail_threshold(evidence)
            ):
                gate = GateDecision(
                    accepted=True,
                    threshold=self._anchored_tail_threshold(evidence),
                    signal_profile=parsed.query_signal_profile,
                    evidence_profile="lexical-only",
                    reason="accepted_as_degraded_lexical_fallback",
                )
            scored_by_id[content_id] = ScoredCandidate(
                content_id=content_id,
                final_score=evidence.relevance,
                features=self._evidence_features(evidence),
                ranks=fused_candidate.ranks,
                rrf_score=fused_candidate.rrf_score,
                evidence=evidence,
                gate=gate,
            )

        feature_finished = time.perf_counter() if explain else None
        relaxation_started = feature_finished
        candidates, decision = self._select_plan(parsed, resolved, plans, plan_ids, scored_by_id, uidx, limit)
        relaxation_finished = time.perf_counter() if explain else None
        relaxed_facets = {
            candidate.content_id: list(candidate.evidence.query_facet_violations)
            for candidate in candidates
            if candidate.evidence is not None
        }
        self._assert_request_lock_postcondition(candidates)
        if explain:
            for plan_debug in trace_plans:
                plan_debug["selected"] = plan_debug["plan_id"] == decision.selected_plan_id
        selected_ids = {candidate.content_id for candidate in candidates}
        return _SearchExecution(
            candidates=candidates,
            retrieved=retrieved,
            retrieval_finished_at=retrieval_finished_at,
            completed_at=time.perf_counter(),
            applied_relaxations=list(decision.applied_relaxations),
            relaxed_facets=relaxed_facets,
            decision=decision,
            rerank_window=rerank_window,
            rerank_outcome=rerank_outcome,
            trace_debug=(
                {
                    "user_id": uidx.user_id,
                    "filters": resolved.model_dump(mode="json"),
                    "plans": trace_plans,
                    "fusion": {
                        "method": self.settings.fusion.method,
                        "k": self.settings.fusion.k,
                        "weights": dict(self.settings.fusion.weights),
                    },
                    "query_terms": {
                        "morph": self.morph_terms(parsed),
                        "ngram": self.ngram_terms(parsed),
                    },
                    "scored_candidates": [
                        {
                            **candidate.model_dump(mode="json"),
                            "selected": candidate.content_id in selected_ids,
                        }
                        for candidate in sorted(
                            scored_by_id.values(),
                            key=lambda candidate: self._candidate_sort_key(candidate, uidx),
                        )
                    ],
                    "final_candidate_ids": [candidate.content_id for candidate in candidates],
                    "timing_ms": {
                        "candidate_retrieval": round(retrieval_ms, 2),
                        "fusion": round(fusion_ms, 2),
                        "feature_rerank_gate": round(
                            ((feature_finished or 0.0) - (feature_started or 0.0)) * 1000,
                            2,
                        ),
                        "relaxation_selection": round(
                            ((relaxation_finished or 0.0) - (relaxation_started or 0.0)) * 1000,
                            2,
                        ),
                    },
                }
                if explain
                else None
            ),
        )

    @staticmethod
    def _merge_fused(left: FusedCandidate, right: FusedCandidate) -> FusedCandidate:
        ranks = dict(left.ranks)
        for name, rank in right.ranks.items():
            ranks[name] = min(rank, ranks.get(name, rank))
        raw_scores = dict(left.raw_scores)
        for name, score in right.raw_scores.items():
            raw_scores[name] = max(score, raw_scores.get(name, score))
        return FusedCandidate(
            content_id=left.content_id,
            rrf_score=max(left.rrf_score, right.rrf_score),
            ranks=ranks,
            raw_scores=raw_scores,
        )

    @staticmethod
    def _accept_all(parsed: ParsedQuery, evidence: CandidateEvidence) -> GateDecision:
        return GateDecision(
            accepted=not evidence.request_lock_violations,
            threshold=0.0,
            signal_profile=parsed.query_signal_profile,
            evidence_profile=evidence.evidence_profile,
            reason="accepted",
        )

    @staticmethod
    def _evidence_features(evidence: CandidateEvidence) -> dict[str, float]:
        return {
            "semantic": evidence.semantic,
            "semantic_raw": evidence.semantic_raw,
            "original_lexical": evidence.original_lexical,
            "canonical_lexical": evidence.canonical_lexical,
            "phrase": evidence.phrase,
            "purpose": evidence.purpose,
            "corroboration": evidence.corroboration,
            "facet_cost": evidence.facet_cost,
            "utility": evidence.utility,
            "cross": evidence.cross or 0.0,
            "relevance_base": evidence.relevance_base,
        }

    def _select_plan(
        self,
        parsed: ParsedQuery,
        resolved: ResolvedFilters,
        plans: list[RelaxationPlan],
        plan_ids: dict[str, set[str]],
        scored_by_id: dict[str, ScoredCandidate],
        uidx: UserIndex,
        limit: int,
    ) -> tuple[list[ScoredCandidate], RelaxationDecision]:
        del resolved  # evidence 생성과 최종 postcondition에서 이미 사용한다.
        ranked_by_plan: dict[str, list[ScoredCandidate]] = {}
        considered_by_plan: dict[str, list[ScoredCandidate]] = {}
        plan_diagnostics: dict[str, dict[str, object]] = {}
        plan_candidate_counts: dict[str, int] = {}
        for plan in plans:
            retrieved_candidates = [
                scored_by_id[content_id]
                for content_id in plan_ids.get(plan.plan_id, set())
                if content_id in scored_by_id
            ]
            considered = [
                candidate
                for candidate in retrieved_candidates
                if self._matches_plan_scope(candidate, plan)
                and plan.filters.to_hard_filter(self.lexicon).accepts(uidx.meta[candidate.content_id])
            ]
            eligible = [
                candidate for candidate in considered if self._eligible_for_plan(candidate, plan)
            ]
            eligible.sort(key=lambda candidate: self._candidate_sort_key(candidate, uidx))
            considered_by_plan[plan.plan_id] = considered
            ranked_by_plan[plan.plan_id] = eligible
            plan_candidate_counts[plan.plan_id] = len(considered)
            rejected: dict[str, list[str]] = {}
            for candidate in considered:
                if self._eligible_for_plan(candidate, plan):
                    continue
                reason = candidate.gate.reason if candidate.gate is not None else "missing_gate_decision"
                rejected.setdefault(reason, []).append(candidate.content_id)
            rejection_counts = Counter({reason: len(content_ids) for reason, content_ids in rejected.items()})
            plan_diagnostics[plan.plan_id] = {
                "retrieved_candidate_count": len(retrieved_candidates),
                "candidate_count": len(considered),
                "eligible_count": len(eligible),
                "gate_rejections": [
                    {
                        "reason": reason,
                        "count": count,
                        "content_ids": sorted(rejected[reason])[:3],
                    }
                    for reason, count in sorted(rejection_counts.items(), key=lambda item: (-item[1], item[0]))[:3]
                ],
            }

        strict = ranked_by_plan.get("strict", [])
        incumbent = strict[0] if strict else None
        strict_diagnostic = plan_diagnostics.get(
            "strict",
            {"retrieved_candidate_count": 0, "candidate_count": 0, "eligible_count": 0, "gate_rejections": []},
        )
        strict_candidate_count = plan_candidate_counts.get("strict", 0)
        attempts: list[dict[str, object]] = [
            {
                "plan_id": "strict",
                **strict_diagnostic,
                "top_id": incumbent.content_id if incumbent is not None else None,
                "accepted": incumbent is not None,
                "reason": (
                    "strict_candidate"
                    if incumbent is not None
                    else "all_candidates_rejected"
                    if strict_candidate_count
                    else "no_retrieval_candidate"
                ),
            }
        ]
        qualifying: list[tuple[RelaxationPlan, ScoredCandidate]] = []
        policy = self.settings.relaxation
        for plan in plans:
            if plan.plan_id == "strict":
                continue
            ranked = ranked_by_plan[plan.plan_id]
            challenger = ranked[0] if ranked else None
            accepted = False
            diagnostic = plan_diagnostics[plan.plan_id]
            reason = (
                "all_candidates_rejected"
                if plan_candidate_counts.get(plan.plan_id, 0)
                else "no_retrieval_candidate"
            )
            if challenger is not None and challenger.evidence is not None:
                if incumbent is not None and incumbent.evidence is not None:
                    if challenger.content_id == incumbent.content_id:
                        reason = "same_top"
                    else:
                        accepted = self.should_adopt(incumbent.evidence, challenger.evidence, 0.0)
                        reason = "accepted" if accepted else "insufficient_gain"
                else:
                    threshold = challenger.gate.threshold if challenger.gate is not None else 0.0
                    accepted = self.should_adopt(None, challenger.evidence, threshold)
                    reason = "accepted" if accepted else "insufficient_gain_from_empty"
            attempts.append(
                {
                    "plan_id": plan.plan_id,
                    **diagnostic,
                    "top_id": challenger.content_id if challenger is not None else None,
                    "accepted": accepted,
                    "reason": reason,
                }
            )
            if accepted and challenger is not None:
                qualifying.append((plan, challenger))

        selected_plan = next((plan for plan in plans if plan.plan_id == "strict"), plans[0])
        selected_top = incumbent
        if qualifying:
            selected_plan, selected_top = min(
                qualifying,
                key=lambda pair: (
                    -self._utility(pair[1]),
                    -self._relevance(pair[1]),
                    len(self._violations(pair[1])),
                    self._cost(pair[1]),
                    len(pair[0].allowed_query_relaxations),
                    self._plan_scope_cost(pair[0]),
                    pair[0].plan_id,
                ),
            )
        if selected_top is None:
            decision = RelaxationDecision(
                selected_plan_id=None,
                minimum_gain=policy.minimum_relevance_gain,
                attempted_plans=tuple(attempts),
            )
            return [], decision

        selected = ranked_by_plan[selected_plan.plan_id]
        top_utility = self._utility(selected_top)
        margin = getattr(self.gate.settings, "return_tail_margin", 0.18) if self.gate is not None else 1.0
        if self.gate is not None and selected_top.evidence is not None and selected_top.evidence.evidence_profile in {
            "corroborated",
            "semantic-only",
        }:
            primary_ids = {candidate.content_id for candidate in selected}
            anchored_tails = [
                self._as_anchored_tail(candidate)
                for candidate in considered_by_plan[selected_plan.plan_id]
                if candidate.content_id not in primary_ids
                and self._is_anchored_tail(candidate)
            ]
            # Tail acceptance must be monotonic in relevance.  A stronger tail is never discarded merely because it
            # outranks the anchor by utility; the primary/tail partition, rather than a rejection rule, prevents it
            # from becoming the first result.
            anchored_tails.sort(key=lambda candidate: self._candidate_sort_key(candidate, uidx))
            selected = [*selected, *anchored_tails]
        selected = [candidate for candidate in selected if self._utility(candidate) >= top_utility - margin][:limit]
        incumbent_evidence = incumbent.evidence if incumbent is not None else None
        challenger_evidence = selected_top.evidence
        assert challenger_evidence is not None
        applied = challenger_evidence.query_facet_violations if selected_plan.plan_id != "strict" else ()
        decision = RelaxationDecision(
            selected_plan_id=selected_plan.plan_id,
            incumbent_id=incumbent.content_id if incumbent is not None else None,
            challenger_id=selected_top.content_id,
            incumbent_relevance=incumbent_evidence.relevance if incumbent_evidence is not None else None,
            challenger_relevance=challenger_evidence.relevance,
            incumbent_cost=incumbent_evidence.facet_cost if incumbent_evidence is not None else 0.0,
            challenger_cost=challenger_evidence.facet_cost,
            delta_relevance=(
                challenger_evidence.relevance - incumbent_evidence.relevance if incumbent_evidence is not None else 0.0
            ),
            delta_cost=(
                challenger_evidence.facet_cost - incumbent_evidence.facet_cost
                if incumbent_evidence is not None
                else 0.0
            ),
            minimum_gain=policy.minimum_relevance_gain,
            applied_relaxations=applied,
            attempted_plans=tuple(attempts),
        )
        return selected, decision

    def should_adopt(
        self,
        incumbent: CandidateEvidence | None,
        challenger: CandidateEvidence,
        virtual_threshold: float,
    ) -> bool:
        """비용과 최소 개선폭을 합친 단 하나의 완화 채택 경계."""
        policy = self.settings.relaxation
        if incumbent is not None and challenger.content_id == incumbent.content_id:
            return False
        incumbent_relevance = incumbent.relevance if incumbent is not None else virtual_threshold
        incumbent_cost = incumbent.facet_cost if incumbent is not None else 0.0
        return (
            challenger.relevance - incumbent_relevance
            > challenger.facet_cost - incumbent_cost + policy.minimum_relevance_gain + policy.epsilon
        )

    @staticmethod
    def _eligible_for_plan(candidate: ScoredCandidate, plan: RelaxationPlan) -> bool:
        evidence = candidate.evidence
        if evidence is None or candidate.gate is None or not candidate.gate.accepted:
            return False
        if evidence.request_lock_violations:
            return False
        return SearchService._matches_plan_scope(candidate, plan)

    @staticmethod
    def _matches_plan_scope(candidate: ScoredCandidate, plan: RelaxationPlan) -> bool:
        evidence = candidate.evidence
        if evidence is None:
            return False
        allowed = set(plan.allowed_query_relaxations)
        for violation in evidence.query_facet_violations:
            if violation == "time_window_expanded" and "time_filter_dropped" in allowed:
                continue
            if violation not in allowed:
                return False
        return True

    def _is_anchored_tail(self, candidate: ScoredCandidate) -> bool:
        evidence = candidate.evidence
        gate = candidate.gate
        gate_provider = self.gate
        if (
            evidence is None
            or gate is None
            or gate_provider is None
            or gate.accepted
            or evidence.request_lock_violations
        ):
            return False
        return (
            evidence.evidence_profile == "lexical-only"
            and gate.reason == "below_threshold"
            and evidence.relevance >= self._anchored_tail_threshold(evidence)
        )

    def _as_anchored_tail(self, candidate: ScoredCandidate) -> ScoredCandidate:
        assert candidate.evidence is not None
        assert candidate.gate is not None
        assert self.gate is not None
        return candidate.model_copy(
            update={
                "gate": GateDecision(
                    accepted=True,
                    threshold=self._anchored_tail_threshold(candidate.evidence),
                    signal_profile=candidate.gate.signal_profile,
                    evidence_profile="lexical-only",
                    reason="accepted_as_anchored_tail",
                )
            }
        )

    def _anchored_tail_threshold(self, evidence: CandidateEvidence) -> float:
        if evidence.relevance_profile == "v3-cross":
            return self.settings.relevance_v3.anchored_tail_threshold
        assert self.gate is not None
        return self.gate.settings.lexical_only_tail_threshold

    @staticmethod
    def _utility(candidate: ScoredCandidate) -> float:
        return candidate.evidence.utility if candidate.evidence is not None else candidate.final_score

    @staticmethod
    def _relevance(candidate: ScoredCandidate) -> float:
        return candidate.evidence.relevance if candidate.evidence is not None else candidate.final_score

    @staticmethod
    def _cost(candidate: ScoredCandidate) -> float:
        return candidate.evidence.facet_cost if candidate.evidence is not None else 0.0

    @staticmethod
    def _violations(candidate: ScoredCandidate) -> tuple[RelaxationName, ...]:
        return candidate.evidence.query_facet_violations if candidate.evidence is not None else ()

    def _plan_scope_cost(self, plan: RelaxationPlan) -> float:
        policy = self.settings.relaxation
        costs: dict[RelaxationName, float] = {
            "time_window_expanded": policy.time_expanded_cost,
            "time_filter_dropped": policy.time_dropped_cost,
            "platform_filter_dropped": policy.platform_cost,
            "content_type_filter_dropped": policy.content_type_cost,
            "spelling_expanded": 0.0,
        }
        return sum(costs[name] for name in plan.allowed_query_relaxations)

    def _candidate_sort_key(
        self, candidate: ScoredCandidate, uidx: UserIndex
    ) -> tuple[float, float, float, float, str]:
        meta = uidx.meta[candidate.content_id]
        # v3에서 창 밖(채점 안 된) 문서는 창 안 문서 뒤에 온다 (INV-R9).
        rerank_bucket = (
            0.0
            if candidate.evidence is None
            or candidate.evidence.relevance_profile == "v2"
            or candidate.evidence.rerank_scored
            else 1.0
        )
        return (
            rerank_bucket,
            -self._utility(candidate),
            -self._relevance(candidate),
            -meta.saved_at.timestamp(),
            candidate.content_id,
        )

    @staticmethod
    def _assert_request_lock_postcondition(candidates: list[ScoredCandidate]) -> None:
        violating = [
            candidate.content_id
            for candidate in candidates
            if candidate.evidence is not None and candidate.evidence.request_lock_violations
        ]
        if violating:
            raise AssertionError(f"요청 잠금 위반 결과: {violating}")

    # ------------------------------------------------------------------ 공통 단계
    def _user_index(self, user_id: str) -> UserIndex:
        if not USER_ID_RE.match(user_id or ""):
            raise InvalidUserError("사용자 id 형식이 올바르지 않아요.", {"pattern": USER_ID_RE.pattern})
        return self.registry.peek(user_id)

    def morph_terms(self, parsed: ParsedQuery) -> list[str]:
        return unique_strings([*parsed.original_terms, *parsed.canonical_terms, *parsed.purpose_terms])

    def ngram_terms(self, parsed: ParsedQuery) -> list[str]:
        text = parsed.residual_text or parsed.semantic_query
        original = self.registry.ngram_tokenizer.query_terms(text) if text else []
        augmented_text = parsed.semantic_text_augmented
        augmented = (
            self.registry.ngram_tokenizer.query_terms(augmented_text)
            if augmented_text and augmented_text != parsed.semantic_text_original
            else []
        )
        return unique_strings([*original, *augmented])

    def _retrieve(
        self,
        parsed: ParsedQuery,
        hf: HardFilter,
        uidx: UserIndex,
        query_vector: np.ndarray | None,
    ) -> _Retrieved:
        r = self.settings.retrieval
        out = _Retrieved()
        out.lists["morph"] = uidx.morph.search(self.morph_terms(parsed), hf, r.n_lex)
        out.lists["ngram"] = uidx.ngram.search(self.ngram_terms(parsed), hf, r.n_lex)
        out.lists["vector"] = []
        if query_vector is not None:
            out.lists["vector"] = uidx.vector.search(query_vector, hf, r.n_vec)
        return out

    def _browse(
        self, parsed: ParsedQuery, resolved: ResolvedFilters, uidx: UserIndex, limit: int
    ) -> list[ScoredCandidate]:
        """필터 전용 질의: 사용자 인덱스 안에서 필터 후 최신 저장물 페이지를 만든다."""
        hard_filter = resolved.to_hard_filter(self.lexicon)
        if resolved.saved_window is not None and resolved.saved_window.origin == "query" and parsed.time_range:
            # 둘러보기의 명시 기간은 기억 보정 window가 아닌 달력상의 실제 구간을 뜻한다.
            hard_filter = hard_filter.model_copy(
                update={"saved_from": parsed.time_range.start, "saved_to": parsed.time_range.end}
            )
        metas = [meta for meta in uidx.meta.values() if meta.user_id == uidx.user_id and hard_filter.accepts(meta)]
        metas.sort(key=lambda meta: (-meta.saved_at.timestamp(), meta.content_id))
        reason = MatchReason(type="browse", detail="필터 조건에 맞는 저장물을 최신순으로 둘러보기")
        return [
            ScoredCandidate(content_id=meta.content_id, final_score=1.0, match_reasons=[reason])
            for meta in metas[:limit]
        ]

    def _fuse(self, lists: dict[str, list[RetrievalHit]]) -> list[FusedCandidate]:
        f = self.settings.fusion
        if f.method == "combsum":
            return fuse_combsum(lists, f.weights, f.top_n)
        return fuse_rrf(lists, f.weights, f.k, f.top_n)

    def _score(
        self,
        parsed: ParsedQuery,
        resolved: ResolvedFilters,
        fused: list[FusedCandidate],
        uidx: UserIndex,
        now: datetime,
    ) -> list[ScoredCandidate]:
        if self.reranker is not None:
            return self.reranker.rerank(parsed, resolved, fused, uidx, now)
        # v0: RRF 점수를 그대로 최종 점수로 쓴다
        return [
            ScoredCandidate(content_id=c.content_id, final_score=c.rrf_score, ranks=c.ranks, rrf_score=c.rrf_score)
            for c in fused
        ]

    # ------------------------------------------------------------------ 응답 조립
    def _build_items(
        self,
        req: SearchRequest,
        parsed: ParsedQuery,
        uidx: UserIndex,
        execution: _SearchExecution,
    ) -> list[SearchResultItem]:
        bundles = self.repo.get_bundles(req.user_id, [candidate.content_id for candidate in execution.candidates])
        return [
            self._item(
                rank,
                candidate,
                bundles[candidate.content_id],
                parsed,
                uidx,
                req.explain,
                execution.relaxed_facets.get(candidate.content_id, []),
                execution.decision,
            )
            for rank, candidate in enumerate(execution.candidates, 1)
            if candidate.content_id in bundles  # 저장소의 user_id 필터로 격리를 한 번 더 확인한다.
        ]

    def _item(
        self,
        rank: int,
        candidate: ScoredCandidate,
        bundle: ContentBundle,
        parsed: ParsedQuery,
        uidx: UserIndex,
        explain: bool,
        relaxed_facets: list[RelaxationName],
        decision: RelaxationDecision | None,
    ) -> SearchResultItem:
        content = bundle.content
        summary = bundle.summary.text if bundle.summary else None
        title = content.title or (summary[:40] if summary else "(제목 없음)")
        reasons = candidate.match_reasons or self._basic_reasons(candidate, bundle, parsed, uidx)
        return SearchResultItem(
            content_id=content.id,
            rank=rank,
            score=round(candidate.final_score, 6),
            title=title,
            platform=content.platform,
            content_type=content.content_type,
            summary=summary,
            representative_tags=[tag.name for tag in bundle.effective_tags()],
            saved_at=content.saved_at,
            source_url=content.source_url,
            original_available=content.original_status != "deleted",
            relaxed=bool(relaxed_facets),
            relaxed_facets=relaxed_facets,
            match_reasons=reasons,
            debug={
                "ranks": candidate.ranks,
                "rrf": round(candidate.rrf_score, 6),
                "features": candidate.features,
                "evidence": candidate.evidence.model_dump(mode="json") if candidate.evidence else None,
                "gate": candidate.gate.model_dump(mode="json") if candidate.gate else None,
                "relaxation_decision": decision.model_dump(mode="json") if decision else None,
            }
            if explain
            else None,
        )

    def _basic_reasons(
        self,
        candidate: ScoredCandidate,
        bundle: ContentBundle,
        parsed: ParsedQuery,
        uidx: UserIndex,
    ) -> list[MatchReason]:
        out: list[MatchReason] = []
        strong: tuple[IndexField, ...] = ("title", "tags_user", "tags_ai", "detail", "summary", "user_note")
        terms = uidx.morph.doc_terms(bundle.content.id, strong)
        query_terms = unique_strings([*parsed.original_terms, *parsed.canonical_terms])
        keyword_hits = [keyword for keyword in query_terms if keyword in terms]
        if keyword_hits:
            out.append(MatchReason(type="keyword", field="tags/title/summary", terms=keyword_hits))
        if candidate.evidence is not None and candidate.evidence.semantic > 0:
            out.append(MatchReason(type="semantic", detail=f"의미 유사도 {candidate.evidence.semantic_raw:.2f}"))
        if parsed.time_range and parsed.time_range.contains(bundle.content.saved_at):
            out.append(MatchReason(type="time", detail=f"{parsed.time_range.expression} 저장"))
        elif (
            candidate.evidence is not None
            and "time_window_expanded" in candidate.evidence.query_facet_violations
            and parsed.time_range is not None
        ):
            out.append(MatchReason(type="time_near", detail=f"기간 근접 ({parsed.time_range.expression})"))
        if bundle.content.platform in parsed.hard_platforms():
            out.append(MatchReason(type="platform", detail=self.lexicon.platform_label(bundle.content.platform)))
        return out

    def _empty_state(self, parsed: ParsedQuery, resolved: ResolvedFilters) -> EmptyState:
        """질의에서 뽑은(잠기지 않은) 조건을 풀어 보는 제안과 동의어 대체 표현. 최대 3개."""
        sugg: list[Suggestion] = []
        if resolved.saved_window is not None and not resolved.saved_window.locked:
            sugg.append(
                Suggestion(
                    type="drop_filter",
                    label="기간 조건 없이 찾기",
                    filters_patch={"saved_from": None, "saved_to": None},
                )
            )
        if resolved.platforms is not None and not resolved.platforms.locked:
            sugg.append(
                Suggestion(type="drop_filter", label="플랫폼 조건 없이 찾기", filters_patch={"platforms": None})
            )
        if resolved.content_types is not None and not resolved.content_types.locked:
            sugg.append(
                Suggestion(type="drop_filter", label="유형 조건 없이 찾기", filters_patch={"content_types": None})
            )
        for kw in parsed.keywords:
            alts = self.lexicon.synonyms(kw)
            if alts:
                alt = alts[0]
                q = " ".join(alt if k == kw else k for k in parsed.keywords)
                sugg.append(Suggestion(type="rephrase", label=f"‘{kw}’ 대신 ‘{alt}’로 찾아보기", query=q))
                break
        return EmptyState(suggestions=sugg[: self.settings.max_suggestions])

"""검색 파이프라인 공용 타입 (설계서 5.3~5.5절)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from jupjup.query.understanding import ParsedQuery
from jupjup.search.filters import ResolvedFilters

RelaxationName = Literal[
    "time_window_expanded",
    "time_filter_dropped",
    "platform_filter_dropped",
    "content_type_filter_dropped",
    "spelling_expanded",
]
EvidenceProfile = Literal["corroborated", "semantic-only", "lexical-only"]
SignalProfile = Literal["normal", "low-signal"]
# lexical은 원형 어휘·phrase, canonical은 교정·동의어 확장으로만 성립한 어휘 증거다 (같은 어휘 계열).
EvidenceSignal = Literal["semantic", "cross", "lexical", "canonical", "purpose"]
RelevanceProfile = Literal["v2", "v3-cross"]

CANONICAL_RELAXATION_ORDER: tuple[RelaxationName, ...] = (
    "time_window_expanded",
    "time_filter_dropped",
    "platform_filter_dropped",
    "content_type_filter_dropped",
    "spelling_expanded",
)


class CandidateEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    content_id: str
    relevance: float = Field(ge=0.0, le=1.0)
    relevance_base: float = Field(default=0.0, ge=0.0, le=1.0)
    semantic: float = Field(ge=0.0, le=1.0)
    semantic_raw: float
    original_lexical: float = Field(ge=0.0, le=1.0)
    canonical_lexical: float = Field(ge=0.0, le=1.0)
    phrase: float = Field(ge=0.0, le=1.0)
    purpose: float = Field(ge=0.0, le=1.0)
    corroboration: float = Field(ge=0.0, le=1.0)
    # 원형 어절(개념) 단위 핵심어 coverage. 하위어 분해나 파생 n-gram이 같은 일치를 중복 계산하지 않는다.
    key_coverage: float = Field(default=0.0, ge=0.0, le=1.0)
    lexical_support: float = Field(default=0.0, ge=0.0, le=1.0)
    # 잡음 floor를 넘은 독립 증거. 게이트는 이 판정만 사용하고 floor를 다시 계산하지 않는다.
    signals: tuple[EvidenceSignal, ...] = ()
    evidence_profile: EvidenceProfile
    query_facet_violations: tuple[RelaxationName, ...] = ()
    request_lock_violations: tuple[str, ...] = ()
    facet_cost: float = Field(ge=0.0)
    # facet_cost 중 soft facet 선호 불일치분. 완화 기록·relaxed 표시에는 쓰지 않는다.
    soft_facet_cost: float = Field(default=0.0, ge=0.0)
    correction_contribution: float = Field(ge=0.0, le=1.0)
    model_id: str
    calibration_version: str
    relevance_version: str
    cross: float | None = Field(default=None, ge=0.0, le=1.0)
    cross_logit: float | None = None
    rerank_scored: bool = False
    relevance_profile: RelevanceProfile = "v2"

    @property
    def utility(self) -> float:
        return self.relevance - self.facet_cost


class GateDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    accepted: bool
    threshold: float
    signal_profile: SignalProfile
    evidence_profile: EvidenceProfile
    reason: str


class RelaxationPlan(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    plan_id: str
    allowed_query_relaxations: tuple[RelaxationName, ...] = ()
    filters: ResolvedFilters
    parent: str = "strict"


class RelaxationDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    selected_plan_id: str | None
    incumbent_id: str | None = None
    challenger_id: str | None = None
    incumbent_relevance: float | None = None
    challenger_relevance: float | None = None
    incumbent_cost: float = 0.0
    challenger_cost: float = 0.0
    delta_relevance: float = 0.0
    delta_cost: float = 0.0
    minimum_gain: float
    applied_relaxations: tuple[RelaxationName, ...] = ()
    attempted_plans: tuple[dict[str, Any], ...] = ()


class RetrievalHit(BaseModel):
    content_id: str
    score: float
    rank: int
    matched_fields: dict[str, list[str]] = Field(default_factory=dict)


class FusedCandidate(BaseModel):
    content_id: str
    rrf_score: float
    ranks: dict[str, int]
    raw_scores: dict[str, float]


class MatchReason(BaseModel):
    type: Literal["keyword", "semantic", "time", "time_near", "platform", "content_type", "purpose", "browse"]
    field: str | None = None
    terms: list[str] = Field(default_factory=list)
    detail: str | None = None


class ScoredCandidate(BaseModel):
    content_id: str
    final_score: float
    features: dict[str, float] = Field(default_factory=dict)
    match_reasons: list[MatchReason] = Field(default_factory=list)
    ranks: dict[str, int] = Field(default_factory=dict)
    rrf_score: float = 0.0
    evidence: CandidateEvidence | None = None
    gate: GateDecision | None = None


class SearchResultItem(BaseModel):
    content_id: str
    rank: int
    score: float
    title: str
    platform: str
    content_type: str
    summary: str | None
    representative_tags: list[str]
    saved_at: datetime
    source_url: str | None
    original_available: bool
    relaxed: bool = False
    relaxed_facets: list[RelaxationName] = Field(default_factory=list)
    match_reasons: list[MatchReason] = Field(default_factory=list)
    debug: dict[str, Any] | None = None


class Suggestion(BaseModel):
    type: Literal["drop_filter", "rephrase"]
    label: str
    filters_patch: dict[str, Any] | None = None
    query: str | None = None


class EmptyState(BaseModel):
    message: str = "다른 표현으로 다시 찾아볼까요?"
    reason: str = "no_relevant_match"
    suggestions: list[Suggestion] = Field(default_factory=list)


class SearchResult(BaseModel):
    query_id: str
    query: str
    understanding: ParsedQuery
    overridden_by_request: list[str] = Field(default_factory=list)
    results: list[SearchResultItem]
    browse: bool = False
    applied_relaxations: list[str] = Field(default_factory=list)
    empty_state: EmptyState | None = None
    degraded: bool = False
    degraded_reasons: list[str] = Field(default_factory=list)
    # cross-encoder 단계 상태: None(꺼짐), "scored", "skipped:<사유>"
    rerank_status: str | None = None
    timing_ms: dict[str, float] = Field(default_factory=dict)
    debug: dict[str, Any] | None = None

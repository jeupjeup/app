"""기존 SearchService를 보여 주기 위한 dev 전용 FastAPI 앱."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, cast

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field, field_validator

from jupjup.config import REPO_ROOT, Settings
from jupjup.container import AppContainer, build_container
from jupjup.demo.page import HTML_PAGE
from jupjup.domain.errors import InvalidUserError, JupjupError
from jupjup.domain.models import require_aware
from jupjup.search.service import SearchRequest
from jupjup.search.types import EmptyState, MatchReason, SearchResult

DemoUser = Literal["u_alice", "u_bob", "u_carol"]


class DemoSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=200)
    user_id: DemoUser = "u_alice"
    now: datetime

    @field_validator("now")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        return require_aware(value, "now")


class DemoFacet(BaseModel):
    value: str
    label: str
    strength: Literal["hard", "soft"]


class DemoRange(BaseModel):
    start: datetime
    end: datetime


class DemoTimeRange(DemoRange):
    expression: str
    fuzzy: bool


class DemoUnderstanding(BaseModel):
    intent: str
    time_range: DemoTimeRange | None
    time_window: DemoRange | None
    platforms: list[DemoFacet]
    content_types: list[DemoFacet]
    keywords: list[str]
    purpose_terms: list[str]
    semantic_query: str


class DemoReason(BaseModel):
    type: str
    label: str
    detail: str | None
    terms: list[str]


class DemoResultItem(BaseModel):
    content_id: str
    rank: int
    title: str
    platform: str
    platform_label: str
    content_type: str
    content_type_label: str
    saved_at: datetime
    summary: str | None
    tags: list[str]
    reasons: list[DemoReason]
    score: float
    original_available: bool
    relaxed: bool


class DemoTraceStep(BaseModel):
    number: int
    title: str
    timing_ms: float | None
    timing_scope: str


class DemoTraceCorrection(BaseModel):
    source: str
    corrected: str
    kind: str
    confidence: float
    evidence: list[str]


class DemoTraceNormalization(DemoTraceStep):
    original: str
    normalized: str
    corrections: list[DemoTraceCorrection]


class DemoTraceUnderstanding(DemoTraceStep):
    value: DemoUnderstanding
    warnings: list[str]


class DemoTraceFilterPlan(BaseModel):
    plan_id: str
    selected: bool
    allowed_relaxations: list[str]
    hard_filter: dict[str, Any]
    eligible_document_count: int


class DemoTraceFiltering(DemoTraceStep):
    isolated_user_id: str
    resolved_filters: dict[str, Any]
    plans: list[DemoTraceFilterPlan]


class DemoTraceRetrieverCandidate(BaseModel):
    content_id: str
    title: str
    rank: int
    score: float
    matched_fields: dict[str, list[str]]


class DemoTraceRetriever(BaseModel):
    name: str
    candidate_count: int
    candidates: list[DemoTraceRetrieverCandidate]


class DemoTraceRetrievalPlan(BaseModel):
    plan_id: str
    selected: bool
    retrievers: list[DemoTraceRetriever]


class DemoTraceRetrieval(DemoTraceStep):
    plans: list[DemoTraceRetrievalPlan]


class DemoTraceFusionCandidate(BaseModel):
    content_id: str
    title: str
    rank: int
    rrf_score: float
    ranks: dict[str, int]
    raw_scores: dict[str, float]


class DemoTraceFusionPlan(BaseModel):
    plan_id: str
    selected: bool
    candidate_count: int
    candidates: list[DemoTraceFusionCandidate]


class DemoTraceFusion(DemoTraceStep):
    method: str
    k: int
    weights: dict[str, float]
    plans: list[DemoTraceFusionPlan]


class DemoTraceGate(BaseModel):
    accepted: bool
    reason: str
    threshold: float
    signal_profile: str
    evidence_profile: str


class DemoTraceRerankCandidate(BaseModel):
    content_id: str
    title: str
    rank: int
    final_score: float
    selected: bool
    features: dict[str, float]
    gate: DemoTraceGate | None


class DemoTraceReranking(DemoTraceStep):
    candidate_count: int
    passed_count: int
    rejected_count: int
    candidates: list[DemoTraceRerankCandidate]


class DemoTraceRelaxation(DemoTraceStep):
    selected_plan_id: str | None
    applied_relaxations: list[str]
    reason: str
    attempted_plans: list[dict[str, Any]]


class DemoTraceCrossReranker(DemoTraceStep):
    configured: bool
    enabled: bool
    used: bool
    status: str | None


class DemoTraceFinal(DemoTraceStep):
    result_count: int
    results: list[DemoResultItem]


class DemoTraceInputData(BaseModel):
    query: str
    user_id: str
    now: datetime


class DemoTracePreprocessing(BaseModel):
    normalization: DemoTraceNormalization
    correction_before: list[str]
    correction_after: list[str]
    morph_tokens: list[str]
    ngram_tokens: list[str]


class DemoTraceComponent(BaseModel):
    stage: str
    component: str | None
    model: str | None
    mode: str | None = None
    provider_mode: str | None = None
    dimension: int | None = None
    minimum_relevance_gain: float | None = None
    status: str
    timing_key: str | None = None
    input: Any = None
    output: Any = None


class DemoTraceModelProcessing(BaseModel):
    components: list[DemoTraceComponent]
    cross_reranker: DemoTraceCrossReranker


class DemoTraceAnalysis(BaseModel):
    understanding: DemoTraceUnderstanding
    final: DemoTraceFinal


class DemoTraceEvidence(BaseModel):
    filtering: DemoTraceFiltering
    retrieval: DemoTraceRetrieval
    fusion: DemoTraceFusion
    reranking: DemoTraceReranking
    relaxation: DemoTraceRelaxation


class DemoTraceLogEntry(BaseModel):
    stage: str
    status: Literal["success", "skipped", "degraded", "failed"]
    timing_key: str | None
    timing_ms: float | None
    detail: str | None = None


class DemoTraceExecutionLog(BaseModel):
    entries: list[DemoTraceLogEntry]
    degraded: bool
    degraded_reasons: list[str]
    errors: list[str]


class DemoSearchTrace(BaseModel):
    input_data: DemoTraceInputData
    preprocessing: DemoTracePreprocessing
    model_processing: DemoTraceModelProcessing
    analysis: DemoTraceAnalysis
    evidence: DemoTraceEvidence
    execution_log: DemoTraceExecutionLog
    timing_ms: dict[str, float]


class DemoSearchResponse(BaseModel):
    query: str
    understanding: DemoUnderstanding
    results: list[DemoResultItem]
    browse: bool
    applied_relaxations: list[str]
    empty_state: EmptyState | None
    degraded: bool
    degraded_reasons: list[str]
    timing_ms: dict[str, float]
    trace: DemoSearchTrace


_REASON_LABELS = {
    "keyword": "키워드 일치",
    "semantic": "의미 유사",
    "time": "기간 일치",
    "time_near": "기간 근접",
    "platform": "플랫폼 일치",
    "content_type": "유형 일치",
    "purpose": "목적 일치",
    "browse": "둘러보기",
}


def _reason(reason: MatchReason) -> DemoReason:
    return DemoReason(
        type=reason.type,
        label=_REASON_LABELS.get(reason.type, reason.type),
        detail=reason.detail,
        terms=reason.terms,
    )


def _mapping(value: object) -> dict[str, Any]:
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


def _sequence(value: object) -> list[Any]:
    return cast(list[Any], value) if isinstance(value, list | tuple) else []


def _trace_timing(pipeline: dict[str, Any], name: str) -> float | None:
    value = _mapping(pipeline.get("timing_ms")).get(name)
    return float(value) if isinstance(value, int | float) else None


def _candidate_title(content_id: str, bundles: dict[str, Any]) -> str:
    bundle = bundles.get(content_id)
    if bundle is None:
        return content_id
    summary = bundle.summary.text if bundle.summary else None
    return bundle.content.title or (summary[:40] if summary else "(제목 없음)")


# 컴포넌트 단계 → SearchService explain timing_ms 키. 같은 키를 쓰는 단계는 그 구간을 함께 측정한 값이다.
_STAGE_TIMING_KEYS = {
    "temporal_parse": "query_understanding",
    "facet_extract": "query_understanding",
    "intent_classify": "query_understanding",
    "bm25f_retrieve": "candidate_retrieval",
    "vector_retrieve": "candidate_retrieval",
    "fusion": "fusion",
    "feature_rerank": "feature_rerank_gate",
    "relevance_gate": "feature_rerank_gate",
    "relaxation": "relaxation_selection",
}


def _log_status(raw: str) -> tuple[Literal["success", "skipped", "degraded", "failed"], str | None]:
    head, _, detail = raw.partition(":")
    if head in {"success", "skipped", "degraded", "failed"}:
        return cast(Literal["success", "skipped", "degraded", "failed"], head), detail or None
    if head == "scored":
        return "success", None
    return "failed", raw


def _trace(
    result: SearchResult,
    understanding: DemoUnderstanding,
    items: list[DemoResultItem],
    container: AppContainer,
    user_id: str,
) -> DemoSearchTrace:
    """SearchService explain 결과(debug.pipeline·understanding·timing_ms)를 6개 묶음으로 옮긴다.

    값을 새로 계산하거나 추정하지 않는다. 후보 제목만 같은 사용자 저장소에서 읽는다.
    """
    debug = _mapping(result.debug)
    pipeline = _mapping(debug.get("pipeline"))
    plans_raw = [_mapping(value) for value in _sequence(pipeline.get("plans"))]
    scored_raw = [_mapping(value) for value in _sequence(pipeline.get("scored_candidates"))]

    content_ids: set[str] = set()
    for plan in plans_raw:
        for retriever in _mapping(plan.get("retrievers")).values():
            for candidate in _sequence(_mapping(retriever).get("candidates")):
                content_ids.add(str(_mapping(candidate).get("content_id", "")))
        for candidate in _sequence(plan.get("fused_candidates")):
            content_ids.add(str(_mapping(candidate).get("content_id", "")))
    content_ids.update(str(candidate.get("content_id", "")) for candidate in scored_raw)
    content_ids.discard("")
    # 사용자 격리: 제목 조회도 같은 user_id로만 한다.
    bundles = container.repo.get_bundles(user_id, sorted(content_ids))

    parsed = result.understanding
    query_timing = _trace_timing(pipeline, "query_understanding")
    input_raw = _mapping(pipeline.get("input"))
    query_terms = _mapping(pipeline.get("query_terms"))

    normalization = DemoTraceNormalization(
        number=1,
        title="입력 정규화·오타 교정",
        timing_ms=query_timing,
        timing_scope="query_understanding",
        original=parsed.original,
        normalized=parsed.normalized,
        corrections=[
            DemoTraceCorrection(
                source=correction.from_,
                corrected=correction.to,
                kind=correction.kind,
                confidence=correction.confidence,
                evidence=list(correction.evidence),
            )
            for correction in parsed.corrections
        ],
    )

    filtering = DemoTraceFiltering(
        number=3,
        title="필터 적용",
        timing_ms=_trace_timing(pipeline, "filter_resolution"),
        timing_scope="filter_resolution",
        isolated_user_id=str(pipeline.get("user_id", "")),
        resolved_filters=_mapping(pipeline.get("filters")),
        plans=[
            DemoTraceFilterPlan(
                plan_id=str(plan.get("plan_id", "")),
                selected=bool(plan.get("selected")),
                allowed_relaxations=[str(value) for value in _sequence(plan.get("allowed_query_relaxations"))],
                hard_filter=_mapping(plan.get("hard_filter")),
                eligible_document_count=int(plan.get("eligible_document_count", 0)),
            )
            for plan in plans_raw
        ],
    )

    retrieval_plans: list[DemoTraceRetrievalPlan] = []
    fusion_plans: list[DemoTraceFusionPlan] = []
    for plan in plans_raw:
        retrievers = []
        for name, raw_retriever in _mapping(plan.get("retrievers")).items():
            retriever = _mapping(raw_retriever)
            candidates = []
            for raw_candidate in _sequence(retriever.get("candidates")):
                candidate = _mapping(raw_candidate)
                content_id = str(candidate.get("content_id", ""))
                candidates.append(
                    DemoTraceRetrieverCandidate(
                        content_id=content_id,
                        title=_candidate_title(content_id, bundles),
                        rank=int(candidate.get("rank", 0)),
                        score=float(candidate.get("score", 0.0)),
                        matched_fields={
                            str(field): [str(term) for term in _sequence(terms)]
                            for field, terms in _mapping(candidate.get("matched_fields")).items()
                        },
                    )
                )
            retrievers.append(
                DemoTraceRetriever(
                    name=str(name),
                    candidate_count=int(retriever.get("candidate_count", len(candidates))),
                    candidates=candidates,
                )
            )
        retrieval_plans.append(
            DemoTraceRetrievalPlan(
                plan_id=str(plan.get("plan_id", "")),
                selected=bool(plan.get("selected")),
                retrievers=retrievers,
            )
        )

        fused_candidates = []
        for rank, raw_candidate in enumerate(_sequence(plan.get("fused_candidates")), 1):
            candidate = _mapping(raw_candidate)
            content_id = str(candidate.get("content_id", ""))
            fused_candidates.append(
                DemoTraceFusionCandidate(
                    content_id=content_id,
                    title=_candidate_title(content_id, bundles),
                    rank=rank,
                    rrf_score=float(candidate.get("rrf_score", 0.0)),
                    ranks={str(name): int(value) for name, value in _mapping(candidate.get("ranks")).items()},
                    raw_scores={
                        str(name): float(value) for name, value in _mapping(candidate.get("raw_scores")).items()
                    },
                )
            )
        fusion_plans.append(
            DemoTraceFusionPlan(
                plan_id=str(plan.get("plan_id", "")),
                selected=bool(plan.get("selected")),
                candidate_count=len(fused_candidates),
                candidates=fused_candidates,
            )
        )

    fusion_raw = _mapping(pipeline.get("fusion"))
    retrieval = DemoTraceRetrieval(
        number=4,
        title="후보 검색 (BM25F·벡터)",
        timing_ms=_trace_timing(pipeline, "candidate_retrieval"),
        timing_scope="candidate_retrieval",
        plans=retrieval_plans,
    )
    fusion = DemoTraceFusion(
        number=5,
        title="RRF 융합",
        timing_ms=_trace_timing(pipeline, "fusion"),
        timing_scope="fusion",
        method=str(fusion_raw.get("method", "")),
        k=int(fusion_raw.get("k", 0)),
        weights={str(name): float(value) for name, value in _mapping(fusion_raw.get("weights")).items()},
        plans=fusion_plans,
    )

    rerank_candidates = []
    passed_count = 0
    for rank, candidate in enumerate(scored_raw, 1):
        content_id = str(candidate.get("content_id", ""))
        gate_raw = _mapping(candidate.get("gate"))
        gate = None
        if gate_raw:
            gate = DemoTraceGate(
                accepted=bool(gate_raw.get("accepted")),
                reason=str(gate_raw.get("reason", "")),
                threshold=float(gate_raw.get("threshold", 0.0)),
                signal_profile=str(gate_raw.get("signal_profile", "")),
                evidence_profile=str(gate_raw.get("evidence_profile", "")),
            )
            passed_count += int(gate.accepted)
        rerank_candidates.append(
            DemoTraceRerankCandidate(
                content_id=content_id,
                title=_candidate_title(content_id, bundles),
                rank=rank,
                final_score=float(candidate.get("final_score", 0.0)),
                selected=bool(candidate.get("selected")),
                features={str(name): float(value) for name, value in _mapping(candidate.get("features")).items()},
                gate=gate,
            )
        )
    reranking = DemoTraceReranking(
        number=6,
        title="특징 재순위·관련성 게이트",
        timing_ms=_trace_timing(pipeline, "feature_rerank_gate"),
        timing_scope="feature_rerank_gate",
        candidate_count=len(rerank_candidates),
        passed_count=passed_count,
        rejected_count=len(rerank_candidates) - passed_count,
        candidates=rerank_candidates,
    )

    relaxation_raw = _mapping(debug.get("relaxation_decision"))
    attempts = [_mapping(value) for value in _sequence(relaxation_raw.get("attempted_plans"))]
    selected_plan_id = relaxation_raw.get("selected_plan_id")
    selected_attempt = next((attempt for attempt in attempts if attempt.get("plan_id") == selected_plan_id), None)
    if selected_attempt is not None:
        relaxation_reason = str(selected_attempt.get("reason", ""))
    elif attempts:
        relaxation_reason = "no_plan_selected"
    else:
        relaxation_reason = "not_run:filter_only_browse" if result.browse else "not_run"
    relaxation = DemoTraceRelaxation(
        number=7,
        title="완화 정책 결정",
        timing_ms=_trace_timing(pipeline, "relaxation_selection"),
        timing_scope="relaxation_selection",
        selected_plan_id=str(selected_plan_id) if selected_plan_id is not None else None,
        applied_relaxations=list(result.applied_relaxations),
        reason=relaxation_reason,
        attempted_plans=attempts,
    )

    cross_raw = _mapping(pipeline.get("cross_reranker"))
    cross_status = cross_raw.get("status")
    if cross_status is None:
        cross_component = next(
            (
                _mapping(value)
                for value in _sequence(pipeline.get("components"))
                if _mapping(value).get("stage") == "cross_rerank"
            ),
            {},
        )
        cross_status = cross_component.get("status")
    cross_reranker = DemoTraceCrossReranker(
        number=8,
        title="크로스 리랭커",
        timing_ms=result.timing_ms.get("cross_rerank"),
        timing_scope="cross_rerank",
        configured=bool(cross_raw.get("configured")),
        enabled=bool(cross_raw.get("enabled")),
        used=cross_status == "scored",
        status=str(cross_status) if cross_status is not None else None,
    )

    components = []
    for raw_component in _sequence(pipeline.get("components")):
        component = _mapping(raw_component)
        stage = str(component.get("stage", ""))
        components.append(
            DemoTraceComponent(
                stage=stage,
                component=str(component["component"]) if component.get("component") is not None else None,
                model=str(component["model"]) if component.get("model") is not None else None,
                mode=str(component["mode"]) if component.get("mode") is not None else None,
                provider_mode=container.settings.mode if stage == "vector_retrieve" else None,
                dimension=int(component["dimension"]) if component.get("dimension") is not None else None,
                minimum_relevance_gain=(
                    float(component["minimum_relevance_gain"])
                    if component.get("minimum_relevance_gain") is not None
                    else None
                ),
                status=str(component.get("status", "")),
                timing_key=_STAGE_TIMING_KEYS.get(stage, "cross_rerank" if stage == "cross_rerank" else None),
                input=component.get("input"),
                output=component.get("output"),
            )
        )

    timing_ms = {
        str(name): float(value)
        for name, value in _mapping(pipeline.get("timing_ms")).items()
        if isinstance(value, int | float)
    }
    log_entries = [
        DemoTraceLogEntry(
            stage="filter_resolution",
            status="success",
            timing_key="filter_resolution",
            timing_ms=timing_ms.get("filter_resolution"),
        )
    ]
    errors: list[str] = []
    for step in components:
        status, detail = _log_status(step.status)
        key = step.timing_key
        timing = result.timing_ms.get("cross_rerank") if key == "cross_rerank" else timing_ms.get(key or "")
        if status in {"degraded", "failed"}:
            reasons = _mapping(step.output).get("degraded_reasons")
            errors.append(f"{step.stage}: {', '.join(map(str, _sequence(reasons))) or step.status}")
        log_entries.append(
            DemoTraceLogEntry(stage=step.stage, status=status, timing_key=key, timing_ms=timing, detail=detail)
        )
    log_entries.append(
        DemoTraceLogEntry(
            stage="finalize", status="success", timing_key="finalize", timing_ms=timing_ms.get("finalize")
        )
    )

    return DemoSearchTrace(
        input_data=DemoTraceInputData(
            query=str(input_raw.get("query", result.query)),
            user_id=str(input_raw.get("user_id", "")),
            now=datetime.fromisoformat(str(input_raw["now"])),
        ),
        preprocessing=DemoTracePreprocessing(
            normalization=normalization,
            correction_before=list(parsed.raw_keywords),
            correction_after=list(parsed.keywords),
            morph_tokens=[str(term) for term in _sequence(query_terms.get("morph"))],
            ngram_tokens=[str(term) for term in _sequence(query_terms.get("ngram"))],
        ),
        model_processing=DemoTraceModelProcessing(components=components, cross_reranker=cross_reranker),
        analysis=DemoTraceAnalysis(
            understanding=DemoTraceUnderstanding(
                number=2,
                title="질의 이해",
                timing_ms=query_timing,
                timing_scope="query_understanding",
                value=understanding,
                warnings=list(parsed.warnings),
            ),
            final=DemoTraceFinal(
                number=9,
                title="최종 결과·매칭 이유",
                timing_ms=_trace_timing(pipeline, "finalize"),
                timing_scope="finalize",
                result_count=len(items),
                results=items,
            ),
        ),
        evidence=DemoTraceEvidence(
            filtering=filtering,
            retrieval=retrieval,
            fusion=fusion,
            reranking=reranking,
            relaxation=relaxation,
        ),
        execution_log=DemoTraceExecutionLog(
            entries=log_entries,
            degraded=result.degraded,
            degraded_reasons=list(result.degraded_reasons),
            errors=errors,
        ),
        timing_ms=timing_ms,
    )


def _present(result: SearchResult, container: AppContainer, user_id: str) -> DemoSearchResponse:
    parsed = result.understanding
    lexicon = container.lexicon
    time_range = None
    if parsed.time_range is not None:
        time_range = DemoTimeRange(
            expression=parsed.time_range.expression,
            start=parsed.time_range.start,
            end=parsed.time_range.end,
            fuzzy=parsed.time_range.fuzzy,
        )
    time_window = None
    if parsed.time_window is not None:
        time_window = DemoRange(start=parsed.time_window.start, end=parsed.time_window.end)
    understanding = DemoUnderstanding(
        intent=parsed.intent,
        time_range=time_range,
        time_window=time_window,
        platforms=[
            DemoFacet(value=hit.value, label=lexicon.platform_label(hit.value), strength=hit.strength)
            for hit in parsed.platforms
        ],
        content_types=[
            DemoFacet(value=hit.value, label=lexicon.content_type_label(hit.value), strength=hit.strength)
            for hit in parsed.content_types
        ],
        keywords=parsed.keywords,
        purpose_terms=parsed.purpose_terms,
        semantic_query=parsed.semantic_query,
    )
    items = [
        DemoResultItem(
            content_id=item.content_id,
            rank=item.rank,
            title=item.title,
            platform=item.platform,
            platform_label=lexicon.platform_label(item.platform),
            content_type=item.content_type,
            content_type_label=lexicon.content_type_label(item.content_type),
            saved_at=item.saved_at,
            summary=item.summary,
            tags=item.representative_tags,
            reasons=[_reason(reason) for reason in item.match_reasons],
            score=item.score,
            original_available=item.original_available,
            relaxed=item.relaxed,
        )
        for item in result.results
    ]
    return DemoSearchResponse(
        query=result.query,
        understanding=understanding,
        results=items,
        browse=result.browse,
        applied_relaxations=result.applied_relaxations,
        empty_state=result.empty_state,
        degraded=result.degraded,
        degraded_reasons=result.degraded_reasons,
        timing_ms=result.timing_ms,
        trace=_trace(result, understanding, items, container, user_id),
    )


def _demo_settings(settings: Settings) -> Settings:
    """live 데모 질의는 커밋된 recorded fixture가 아니라 var/에만 녹화한다."""
    if settings.mode != "live" or settings.embedding_recording_path is not None:
        return settings
    path = REPO_ROOT / "var" / "recordings" / f"demo.embeddings.{settings.recorded_model_id}.jsonl"
    return settings.model_copy(update={"embedding_recording_path": path})


def create_demo_app(settings: Settings | None = None, *, container: AppContainer | None = None) -> FastAPI:
    """dev/test 설정에서만 로컬 데모 앱을 만든다."""
    active = container or build_container(_demo_settings(settings or Settings()))
    if active.settings.env not in {"dev", "test"}:
        raise ValueError("웹 데모는 dev/test 환경에서만 실행할 수 있습니다")
    active.indexer.reindex_all()

    app = FastAPI(
        title="줍줍저장소 로컬 데모",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.container = active

    @app.exception_handler(JupjupError)
    async def _jupjup_error(_: Request, exc: JupjupError) -> JSONResponse:
        status = 400 if isinstance(exc, InvalidUserError) else 422
        return JSONResponse(status_code=status, content={"error": {"code": exc.code, "message": exc.message}})

    @app.get("/", response_class=HTMLResponse)
    def page() -> HTMLResponse:
        return HTMLResponse(HTML_PAGE.replace("{{DEMO_MODE}}", active.settings.mode))

    @app.post("/demo/search", response_model=DemoSearchResponse)
    def search(body: DemoSearchRequest) -> DemoSearchResponse:
        result = active.search.search(
            SearchRequest(user_id=body.user_id, query=body.query, now=body.now, limit=10, explain=True)
        )
        return _present(result, active, body.user_id)

    return app

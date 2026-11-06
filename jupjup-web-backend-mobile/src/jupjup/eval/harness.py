"""오프라인 평가 하네스 (설계서 3.4절).

1) 골든셋 검증 → 2) 임시 SQLite에 seeds 적재 + 인덱싱 → 3) lexicon_cases로 QU 평가
→ 4) 질의마다 SearchService.search(now=q.now) → 5) 지표 집계 → 6) 기준선 비교 → 7) GateResult
하네스는 `now`를 질의마다 주입한다. 시스템 시계에 의존하지 않는다 (created_at 기록 제외).
"""

from __future__ import annotations

import itertools
import json
import subprocess
from collections import defaultdict
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from jupjup.config import REPO_ROOT, SearchSettings, Settings, apply_overrides
from jupjup.container import AppContainer, build_container
from jupjup.domain.errors import GoldenSetError
from jupjup.eval import metrics as M
from jupjup.eval.schema import ExpectedUnderstanding, GoldenQuery, GoldenSet, ReviewStatus, load_and_validate
from jupjup.query.understanding import ParsedQuery
from jupjup.search.service import SearchRequest
from jupjup.storage.db import create_db_engine
from jupjup.storage.seed import load_seed_file

GOLDEN = REPO_ROOT / "data" / "golden"
REGRESSION_KEYS = ("recall@10", "mrr@10", "ndcg@10", "time_exact", "platform_f1")
GATE_REVIEW_STATUS: ReviewStatus = "ai_draft_unreviewed"
REVIEW_STATUSES: tuple[ReviewStatus, ...] = (
    "ai_draft_unreviewed",
    "needs_human_review",
    "human_reviewed",
)
MIN_HUMAN_REVIEWED_QUERIES = 20
MIN_HUMAN_REVIEWERS = 2
MIN_WEIGHTED_KAPPA = 0.70
HUMAN_MINIMUM_DENOMINATORS: dict[str, int] = {
    "positive_ranked": 10,
    "negative_true_empty": 5,
    "filter_only_browse": 5,
    "time_understanding": 5,
    "platform_understanding": 5,
    "content_type_understanding": 5,
    "keyword_inclusion": 10,
}

# 3.3.4절 절대 기준: (지표, 연산, mock 기준, recorded/live 기준)
CRITERIA: list[tuple[str, Literal[">=", "<=", "=="], float, float]] = [
    ("recall@10", ">=", 0.75, 0.90),
    ("recall@5", ">=", 0.65, 0.85),
    ("mrr@10", ">=", 0.60, 0.75),
    ("ndcg@10", ">=", 0.65, 0.80),
    ("success@1", ">=", 0.50, 0.65),
    ("category_recall@10_min", ">=", 0.55, 0.80),
    ("time_exact", ">=", 0.95, 0.95),
    ("platform_f1", ">=", 0.97, 0.97),
    ("content_type_f1", ">=", 0.95, 0.95),
    ("keyword_inclusion", ">=", 0.90, 0.90),
    ("true_empty_rate", ">=", 0.70, 0.80),
    ("false_empty_rate", "<=", 0.05, 0.03),
    ("isolation_violations", "==", 0, 0),
    ("filter_violations", "==", 0, 0),
    ("browse_precision@10", ">=", 0.95, 0.95),
    ("browse_sort_accuracy", ">=", 1.0, 1.0),
    ("browse_filter_compliance", ">=", 1.0, 1.0),
]


class EvalConfig(BaseModel):
    mode: Literal["mock", "recorded", "live"] = "mock"
    split: Literal["dev", "test", "all"] = "test"
    seeds_path: Path = GOLDEN / "seeds.jsonl"
    queries_path: Path = GOLDEN / "queries.jsonl"
    lexicon_path: Path = GOLDEN / "lexicon_cases.jsonl"
    challenge_path: Path | None = GOLDEN / "challenge_queries.jsonl"
    review_metadata_path: Path | None = GOLDEN / "review_metadata.json"
    human_baseline_path: Path | None = None
    baseline_path: Path | None = None
    regression_tolerance: float = 0.01
    k_values: tuple[int, ...] = (5, 10)
    search_overrides: dict[str, Any] = Field(default_factory=dict)


class QueryResult(BaseModel):
    query_id: str
    query: str = ""
    user_id: str = ""
    categories: list[str] = Field(default_factory=list)
    review_status: ReviewStatus = "ai_draft_unreviewed"
    filter_only: bool = False
    ranked_ids: list[str]
    relevance: dict[str, int] = Field(default_factory=dict)
    parsed: ParsedQuery
    relaxations: list[str]
    empty: bool
    degraded: bool = False
    rerank_status: str | None = None
    per_query_metrics: dict[str, float]


class GateCheck(BaseModel):
    name: str
    value: float | None
    op: str
    threshold: float
    passed: bool


class GateResult(BaseModel):
    passed: bool
    reasons: list[str] = Field(default_factory=list)
    checks: list[GateCheck] = Field(default_factory=list)
    regression: list[GateCheck] = Field(default_factory=list)


class MetricObservation(BaseModel):
    value: float | None
    numerator: float
    denominator: int = Field(ge=0)
    minimum_denominator: int = Field(ge=1)
    eligible: bool


def _empty_split_kappa() -> dict[str, float | None]:
    return {"dev": None, "test": None}


class HumanReviewMetadata(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    reviewer_count: int = Field(default=0, ge=0)
    reviewed_query_count_total: int = Field(
        default=0,
        ge=0,
        validation_alias=AliasChoices("reviewed_query_count_total", "reviewed_query_count"),
    )
    reviewed_query_count_by_split: dict[str, int] = Field(default_factory=lambda: {"dev": 0, "test": 0})
    weighted_kappa_overall: float | None = Field(
        default=None,
        ge=-1.0,
        le=1.0,
        validation_alias=AliasChoices("weighted_kappa_overall", "weighted_kappa"),
    )
    weighted_kappa_by_split: dict[str, float | None] = Field(default_factory=_empty_split_kappa)
    note: str = ""

    @property
    def reviewed_query_count(self) -> int:
        return self.reviewed_query_count_total

    @property
    def weighted_kappa(self) -> float | None:
        return self.weighted_kappa_overall


class EvalReport(BaseModel):
    config: EvalConfig
    created_at: datetime
    git_sha: str | None
    golden_status: str = "AI 초안/미검수 지표; 제품 PASS 근거 아님"
    counts: dict[str, int]
    overall: dict[str, float]
    by_category: dict[str, dict[str, float]]
    by_review_status: dict[str, dict[str, float | None]] = Field(default_factory=dict)
    review_status_gates: dict[str, GateResult] = Field(default_factory=dict)
    browse: dict[str, float] = Field(default_factory=dict)
    product_evidence: dict[str, Any] = Field(default_factory=dict)
    understanding: dict[str, float]
    safety: dict[str, int]
    failures: list[QueryResult]
    understanding_failures: list[dict[str, Any]] = Field(default_factory=list)
    gate: GateResult
    perf: dict[str, float] = Field(default_factory=dict)  # 비결정적 (결정성 비교에서 뺀다)
    results: list[QueryResult] = Field(default_factory=list)

    def deterministic_dict(self) -> dict[str, Any]:
        d = self.model_dump(mode="json", exclude={"created_at", "git_sha", "perf"})
        return d


class BaselineFile(BaseModel):
    mode: Literal["mock", "recorded", "live"]
    note: str = ""
    review_status: ReviewStatus = "ai_draft_unreviewed"
    splits: dict[str, dict[str, Any]] = Field(default_factory=dict)


def default_container_factory(config: EvalConfig) -> AppContainer:
    search = apply_overrides(SearchSettings(), config.search_overrides)
    settings = Settings(env="test", mode=config.mode, db_path=Path(":memory:"), search=search)
    return build_container(settings, engine=create_db_engine(None))


def _git_sha() -> str | None:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=REPO_ROOT,
            check=False,
        )
        return r.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


class _UStats:
    """질의 이해 지표 누적기."""

    def __init__(self) -> None:
        self.time_n = 0
        self.time_ok = 0
        self.iou: list[float] = []
        self.plat = M.PRF()
        self.ctype = M.PRF()
        self.plat_n = 0
        self.ctype_n = 0
        self.kw_n = 0
        self.kw_ok = 0
        self.intent_n = 0
        self.intent_ok = 0
        self.failures: list[dict[str, Any]] = []

    def add(self, case_id: str, text: str, exp: ExpectedUnderstanding, p: ParsedQuery) -> None:
        problems = []
        if exp.scores_time():
            self.time_n += 1
            ok = M.time_range_exact(p.time_range, exp.time_range)
            self.time_ok += ok
            self.iou.append(M.time_range_iou(p.time_range, exp.time_range))
            if not ok:
                problems.append("time")
        if exp.platforms is not None:
            self.plat_n += 1
            prf = M.set_prf(set(p.hard_platforms()), set(exp.platforms))
            self.plat = self.plat + prf
            if prf.fp or prf.fn:
                problems.append("platform")
        if exp.content_types is not None:
            self.ctype_n += 1
            prf = M.set_prf(set(p.hard_content_types()), set(exp.content_types))
            self.ctype = self.ctype + prf
            if prf.fp or prf.fn:
                problems.append("content_type")
        if exp.keywords_must_include:
            self.kw_n += 1
            ok = all(k in p.keywords for k in exp.keywords_must_include)
            self.kw_ok += ok
            if not ok:
                problems.append("keywords")
        if exp.intent is not None:
            self.intent_n += 1
            ok = p.intent == exp.intent
            self.intent_ok += ok
            if not ok:
                problems.append("intent")
        if problems:
            self.failures.append({"id": case_id, "text": text, "problems": problems})

    def metrics(self, prefix: str = "") -> dict[str, float]:
        def r(a: int, b: int) -> float:
            return round(a / b, 6) if b else 1.0

        return {
            f"{prefix}time_exact": r(self.time_ok, self.time_n),
            f"{prefix}time_iou": round(M.mean(self.iou), 6) if self.iou else 1.0,
            f"{prefix}platform_precision": round(self.plat.precision, 6),
            f"{prefix}platform_recall": round(self.plat.recall, 6),
            f"{prefix}platform_f1": round(self.plat.f1, 6),
            f"{prefix}content_type_precision": round(self.ctype.precision, 6),
            f"{prefix}content_type_recall": round(self.ctype.recall, 6),
            f"{prefix}content_type_f1": round(self.ctype.f1, 6),
            f"{prefix}keyword_inclusion": r(self.kw_ok, self.kw_n),
            f"{prefix}intent_accuracy": r(self.intent_ok, self.intent_n),
            f"{prefix}n_time": float(self.time_n),
            f"{prefix}n_keyword": float(self.kw_n),
            f"{prefix}n_platform": float(self.plat_n),
            f"{prefix}n_content_type": float(self.ctype_n),
        }


def _ranking_metrics(results: Iterable[QueryResult]) -> dict[str, float]:
    rs = [r for r in results if r.relevance and not r.filter_only]
    keys = ("recall@5", "recall@10", "mrr@10", "ndcg@10", "success@1")
    out = {k: round(M.mean([r.per_query_metrics[k] for r in rs]), 6) for k in keys}
    out["n_ranked"] = float(len(rs))
    return out


def _browse_metrics(results: Iterable[QueryResult]) -> dict[str, float]:
    rs = [r for r in results if r.filter_only]
    keys = ("browse_precision@10", "browse_sort_accuracy", "browse_filter_compliance", "browse_coverage")
    out = {key: round(M.mean([r.per_query_metrics[key] for r in rs]), 6) if rs else 1.0 for key in keys}
    out["n_browse"] = float(len(rs))
    return out


class EvalHarness:
    def __init__(
        self, config: EvalConfig, container_factory: Callable[[EvalConfig], AppContainer] = default_container_factory
    ) -> None:
        self.config = config
        self.container_factory = container_factory

    # ------------------------------------------------------------------
    def run(self) -> EvalReport:
        cfg = self.config
        gs = load_and_validate(
            cfg.seeds_path,
            cfg.queries_path,
            cfg.lexicon_path,
            cfg.challenge_path,
        )  # GoldenSetError
        c = self.container_factory(cfg)
        rep = load_seed_file(cfg.seeds_path, c.repo, c.indexer, strict=True)
        if rep.errors or rep.rolled_back:
            raise GoldenSetError("시드 적재 실패", {"errors": [e.model_dump() for e in rep.errors]})

        # 3) lexicon_cases QU 평가 (어휘 없이, 규칙 기반 경로)
        lex = _UStats()
        for case in gs.lexicon_cases:
            lex.add(case.id, case.text, case.expected, c.understander.parse(case.text, case.now))

        # 4) 질의 실행
        queries = [q for q in gs.queries if cfg.split == "all" or q.split == cfg.split]
        qstats_by_status = {status: _UStats() for status in REVIEW_STATUSES}
        results: list[QueryResult] = []
        latencies: list[float] = []
        safety = {"isolation_violations": 0, "filter_violations": 0}
        seed_meta = {s.id: s for s in gs.seeds}
        k_max = max(cfg.k_values)
        for q in queries:
            res = c.search.search(
                SearchRequest(user_id=q.user_id, query=q.query, filters=q.request_filters, limit=k_max, now=q.now)
            )
            latencies.append(res.timing_ms.get("total", 0.0))
            ranked = [r.content_id for r in res.results]
            qstats_by_status[q.review_status].add(q.id, q.query, q.expected, res.understanding)
            safety["isolation_violations"] += sum(1 for cid in ranked if seed_meta[cid].user_id != q.user_id)
            safety["filter_violations"] += self._filter_violations(q, ranked, gs, c)
            pm = self._browse_per_query(q, ranked, seed_meta, c) if res.browse else self._per_query(ranked, q.relevance)
            results.append(
                QueryResult(
                    query_id=q.id,
                    query=q.query,
                    user_id=q.user_id,
                    categories=list(q.categories),
                    review_status=q.review_status,
                    filter_only=res.browse,
                    ranked_ids=ranked,
                    relevance=q.relevance,
                    parsed=res.understanding,
                    relaxations=res.applied_relaxations,
                    empty=not ranked,
                    degraded=res.degraded,
                    rerank_status=res.rerank_status,
                    per_query_metrics=pm,
                )
            )

        # 5) 집계
        gate_results = [r for r in results if r.review_status == GATE_REVIEW_STATUS]
        overall = _ranking_metrics(gate_results)
        neg = [r for r in gate_results if not r.relevance]
        pos = [r for r in gate_results if r.relevance]
        overall["true_empty_rate"] = round(sum(r.empty for r in neg) / len(neg), 6) if neg else 1.0
        overall["false_empty_rate"] = round(sum(r.empty for r in pos) / len(pos), 6) if pos else 0.0
        by_cat: dict[str, dict[str, float]] = {}
        groups: dict[str, list[QueryResult]] = defaultdict(list)
        for r in gate_results:
            for cat in r.categories:
                groups[cat].append(r)
        for cat in sorted(groups):
            rs = groups[cat]
            m = _ranking_metrics(rs)
            m["n"] = float(len(rs))
            negs = [r for r in rs if not r.relevance]
            if negs:
                m["true_empty_rate"] = round(sum(r.empty for r in negs) / len(negs), 6)
            by_cat[cat] = m
        ranked_cats = [m["recall@10"] for m in by_cat.values() if m["n_ranked"] > 0]
        overall["category_recall@10_min"] = round(min(ranked_cats), 6) if ranked_cats else 0.0

        browse = _browse_metrics(gate_results)
        by_review_status: dict[str, dict[str, float | None]] = {}
        for status in REVIEW_STATUSES:
            status_results = [r for r in results if r.review_status == status]
            metrics: dict[str, float | None] = {}
            metrics.update(_ranking_metrics(status_results))
            metrics.update(_browse_metrics(status_results))
            metrics.update(qstats_by_status[status].metrics())
            status_neg = [r for r in status_results if not r.relevance]
            status_pos = [r for r in status_results if r.relevance]
            metrics["true_empty_rate"] = (
                round(sum(r.empty for r in status_neg) / len(status_neg), 6) if status_neg else None
            )
            metrics["false_empty_rate"] = (
                round(sum(r.empty for r in status_pos) / len(status_pos), 6) if status_pos else None
            )
            metrics["n_queries"] = float(len(status_results))
            status_groups: dict[str, list[QueryResult]] = defaultdict(list)
            for result in status_results:
                for category in result.categories:
                    status_groups[category].append(result)
            status_ranked_cats = [
                category_metrics["recall@10"]
                for category_metrics in (_ranking_metrics(group) for group in status_groups.values())
                if category_metrics["n_ranked"] > 0
            ]
            metrics["category_recall@10_min"] = round(min(status_ranked_cats), 6) if status_ranked_cats else None
            if not any(result.relevance and not result.filter_only for result in status_results):
                for name in ("recall@5", "recall@10", "mrr@10", "ndcg@10", "success@1"):
                    metrics[name] = None
            if not any(result.filter_only for result in status_results):
                for name in (
                    "browse_precision@10",
                    "browse_sort_accuracy",
                    "browse_filter_compliance",
                    "browse_coverage",
                ):
                    metrics[name] = None
            denominator_metrics = (
                ("n_time", ("time_exact", "time_iou")),
                ("n_platform", ("platform_precision", "platform_recall", "platform_f1")),
                ("n_content_type", ("content_type_precision", "content_type_recall", "content_type_f1")),
                ("n_keyword", ("keyword_inclusion",)),
            )
            for denominator, names in denominator_metrics:
                if metrics[denominator] == 0:
                    for name in names:
                        metrics[name] = None
            by_review_status[status] = metrics

        understanding = self._combine_understanding(lex, qstats_by_status[GATE_REVIEW_STATUS])
        failures = [r for r in results if self._is_failure(r)]
        report = EvalReport(
            config=cfg,
            created_at=datetime.now(UTC),
            git_sha=_git_sha(),
            counts={
                "seeds": len(gs.seeds),
                "queries": len(queries),
                "challenge_queries": sum(q.id in gs.challenge_query_ids for q in queries),
                "lexicon_cases": len(gs.lexicon_cases),
                "ranked_queries": sum(bool(r.relevance) and not r.filter_only for r in gate_results),
                "browse_queries": sum(r.filter_only for r in gate_results),
                "negative_queries": len(neg),
            },
            overall=overall,
            by_category=by_cat,
            by_review_status=by_review_status,
            browse=browse,
            product_evidence={},
            understanding=understanding,
            safety=safety,
            failures=failures,
            gate=GateResult(passed=False),
            perf={
                "latency_p50_ms": M.percentile(latencies, 50),
                "latency_p95_ms": M.percentile(latencies, 95),
                "latency_max_ms": max(latencies) if latencies else 0.0,
            },
            results=results,
            understanding_failures=lex.failures
            + list(itertools.chain.from_iterable(stats.failures for stats in qstats_by_status.values())),
        )
        report.gate = self.evaluate_gate(report)
        report.review_status_gates = {
            status: self.evaluate_review_status_gate(report, status) for status in REVIEW_STATUSES
        }
        review_metadata = load_review_metadata(cfg.review_metadata_path)
        human_baseline = self._baseline_for_status("human_reviewed")
        human_baseline_available = bool(human_baseline is not None and report.config.split in human_baseline.splits)
        report.product_evidence = self._build_product_evidence(
            report.by_review_status["human_reviewed"],
            report.review_status_gates["human_reviewed"],
            review_metadata,
            human_baseline_available,
            observations=self._human_observations(queries, results, report.by_review_status["human_reviewed"]),
            split=cfg.split,
            actual_total=sum(q.review_status == "human_reviewed" for q in gs.queries),
            actual_by_split={
                split: sum(q.review_status == "human_reviewed" and q.split == split for q in gs.queries)
                for split in ("dev", "test")
            },
        )
        return report

    @staticmethod
    def _human_observations(
        queries: list[GoldenQuery],
        results: list[QueryResult],
        metrics: dict[str, float | None],
    ) -> dict[str, MetricObservation]:
        human_queries = [query for query in queries if query.review_status == "human_reviewed"]
        human_results = [result for result in results if result.review_status == "human_reviewed"]
        result_by_id = {result.query_id: result for result in human_results}
        denominators = {
            "positive_ranked": sum(
                bool(query.relevance) and not result_by_id[query.id].filter_only for query in human_queries
            ),
            "negative_true_empty": sum(not query.relevance for query in human_queries),
            "filter_only_browse": sum(result_by_id[query.id].filter_only for query in human_queries),
            "time_understanding": sum(query.expected.scores_time() for query in human_queries),
            "platform_understanding": sum(query.expected.platforms is not None for query in human_queries),
            "content_type_understanding": sum(query.expected.content_types is not None for query in human_queries),
            "keyword_inclusion": sum(bool(query.expected.keywords_must_include) for query in human_queries),
        }
        metric_names = {
            "positive_ranked": "recall@10",
            "negative_true_empty": "true_empty_rate",
            "filter_only_browse": "browse_precision@10",
            "time_understanding": "time_exact",
            "platform_understanding": "platform_f1",
            "content_type_understanding": "content_type_f1",
            "keyword_inclusion": "keyword_inclusion",
        }
        observations: dict[str, MetricObservation] = {}
        for name, denominator in denominators.items():
            minimum = HUMAN_MINIMUM_DENOMINATORS[name]
            value = metrics.get(metric_names[name]) if denominator else None
            observations[name] = MetricObservation(
                value=value,
                numerator=(value or 0.0) * denominator,
                denominator=denominator,
                minimum_denominator=minimum,
                eligible=denominator >= minimum,
            )
        return observations

    # ------------------------------------------------------------------
    @staticmethod
    def _per_query(ranked: list[str], rel: dict[str, int]) -> dict[str, float]:
        if not rel:
            return {"returned": float(len(ranked))}
        return {
            "recall@5": M.recall_at_k(ranked, rel, 5),
            "recall@10": M.recall_at_k(ranked, rel, 10),
            "mrr@10": M.mrr_at_k(ranked, rel, 10),
            "ndcg@10": M.ndcg_at_k(ranked, rel, 10),
            "success@1": M.success_at_1(ranked, rel),
            "returned": float(len(ranked)),
        }

    @staticmethod
    def _browse_per_query(
        query: GoldenQuery,
        ranked: list[str],
        seed_meta: dict[str, Any],
        container: AppContainer,
    ) -> dict[str, float]:
        relevant_returned = sum(cid in query.relevance for cid in ranked[:10])
        precision = relevant_returned / len(ranked[:10]) if ranked[:10] else 0.0
        coverage = relevant_returned / len(query.relevance) if query.relevance else 1.0
        saved_times = [seed_meta[cid].saved_at for cid in ranked]
        sort_accuracy = float(all(left >= right for left, right in itertools.pairwise(saved_times)))

        expected = query.expected
        expected_platforms = set(expected.platforms or [])
        expected_types = container.lexicon.expand_content_types(set(expected.content_types or []))
        expected_time = expected.time_range if expected.scores_time() else None
        compliant = 0
        for cid in ranked:
            seed = seed_meta[cid]
            if expected_platforms and seed.platform not in expected_platforms:
                continue
            if expected_types and seed.content_type not in expected_types:
                continue
            if expected_time is not None and not (expected_time.start <= seed.saved_at < expected_time.end):
                continue
            compliant += 1
        filter_compliance = compliant / len(ranked) if ranked else 0.0
        return {
            "browse_precision@10": precision,
            "browse_sort_accuracy": sort_accuracy,
            "browse_filter_compliance": filter_compliance,
            "browse_coverage": coverage,
            "returned": float(len(ranked)),
        }

    @staticmethod
    def _is_failure(r: QueryResult) -> bool:
        if not r.relevance:
            return not r.empty  # 정답 없는 질의에 결과를 냄
        if r.filter_only:
            return (
                r.per_query_metrics["browse_precision@10"] < 1.0
                or r.per_query_metrics["browse_filter_compliance"] < 1.0
            )
        return r.per_query_metrics["recall@10"] < 1.0 or r.per_query_metrics["success@1"] == 0.0

    @staticmethod
    def _filter_violations(q: GoldenQuery, ranked: list[str], gs: GoldenSet, c: AppContainer) -> int:
        f = q.request_filters
        if f is None:
            return 0
        meta = {s.id: s for s in gs.seeds}
        types = c.lexicon.expand_content_types(set(f.content_types)) if f.content_types is not None else None
        bad = 0
        for cid in ranked:
            s = meta[cid]
            if (
                (f.platforms is not None and s.platform not in f.platforms)
                or (types is not None and s.content_type not in types)
                or (f.saved_from is not None and s.saved_at < f.saved_from)
                or (f.saved_to is not None and s.saved_at >= f.saved_to)
            ):
                bad += 1
        return bad

    @staticmethod
    def _combine_understanding(lex: _UStats, qs: _UStats) -> dict[str, float]:
        both = _UStats()
        both.time_n, both.time_ok = lex.time_n + qs.time_n, lex.time_ok + qs.time_ok
        both.iou = lex.iou + qs.iou
        both.plat, both.ctype = lex.plat + qs.plat, lex.ctype + qs.ctype
        both.kw_n, both.kw_ok = lex.kw_n + qs.kw_n, lex.kw_ok + qs.kw_ok
        both.intent_n, both.intent_ok = lex.intent_n + qs.intent_n, lex.intent_ok + qs.intent_ok
        out = both.metrics()
        out.update(lex.metrics("lexicon."))
        out.update(qs.metrics("queries."))
        return out

    # ------------------------------------------------------------------ 합격 판정
    def evaluate_gate(self, report: EvalReport) -> GateResult:
        values: dict[str, float] = {
            **report.overall,
            **report.browse,
            **report.understanding,
            **{k: float(v) for k, v in report.safety.items()},
        }
        checks: list[GateCheck] = []
        reasons: list[str] = []
        live_like = self.config.mode != "mock"
        for name, op, mock_th, live_th in CRITERIA:
            th = live_th if live_like else mock_th
            v = values.get(name)
            ok = v is not None and (v >= th if op == ">=" else v <= th if op == "<=" else v == th)
            checks.append(GateCheck(name=name, value=v, op=op, threshold=th, passed=ok))
            if not ok:
                reasons.append(f"{name} = {v} (기준 {op} {th})")
        result = GateResult(passed=not reasons, reasons=reasons, checks=checks)
        if self.config.baseline_path is not None and self.config.baseline_path.exists():
            reg = self.compare(report, load_baseline(self.config.baseline_path))
            result.regression = reg.checks
            if not reg.passed:
                result.passed = False
                result.reasons += reg.reasons
        return result

    def evaluate_review_status_gate(self, report: EvalReport, status: ReviewStatus) -> GateResult:
        """각 검수 상태의 데이터만으로 절대 기준과 해당 기준선 회귀를 판정한다."""
        values = {
            **{
                key: float(value) for key, value in report.by_review_status.get(status, {}).items() if value is not None
            },
            **{key: float(value) for key, value in report.safety.items()},
        }
        checks: list[GateCheck] = []
        reasons: list[str] = []
        live_like = self.config.mode != "mock"
        for name, op, mock_th, live_th in CRITERIA:
            threshold = live_th if live_like else mock_th
            value = values.get(name)
            passed = value is not None and (
                value >= threshold if op == ">=" else value <= threshold if op == "<=" else value == threshold
            )
            checks.append(GateCheck(name=name, value=value, op=op, threshold=threshold, passed=passed))
            if not passed:
                reasons.append(f"{status}: {name} = {value} (기준 {op} {threshold})")
        result = GateResult(passed=not reasons, reasons=reasons, checks=checks)
        baseline = self._baseline_for_status(status)
        if baseline is not None:
            regression = self.compare(report, baseline)
            result.regression = regression.checks
            if not regression.passed:
                result.passed = False
                result.reasons.extend(regression.reasons)
        return result

    def _baseline_for_status(self, status: ReviewStatus) -> BaselineFile | None:
        paths = [self.config.baseline_path]
        if status == "human_reviewed":
            paths.append(
                self.config.human_baseline_path
                or REPO_ROOT / "data" / "baselines" / f"{self.config.mode}.human_reviewed.json"
            )
        for path in paths:
            if path is None or not path.exists():
                continue
            baseline = load_baseline(path)
            if baseline.review_status == status:
                return baseline
        return None

    @staticmethod
    def _build_product_evidence(
        human_metrics: dict[str, float | None],
        human_gate: GateResult,
        metadata: HumanReviewMetadata,
        regression_baseline_available: bool,
        *,
        observations: dict[str, MetricObservation] | None = None,
        split: str = "test",
        actual_total: int | None = None,
        actual_by_split: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        human_count = int(human_metrics.get("n_queries") or 0)
        observations = observations or {}
        actual_total = human_count if actual_total is None else actual_total
        actual_by_split = actual_by_split or {split: human_count}
        absolute_passed = bool(human_gate.checks) and all(check.passed for check in human_gate.checks)
        regression_passed = (
            regression_baseline_available
            and bool(human_gate.regression)
            and all(check.passed for check in human_gate.regression)
        )
        denominator_conditions = {
            f"denominator:{name}": observation.eligible for name, observation in observations.items()
        }
        required_denominators = bool(observations) and all(denominator_conditions.values())
        split_metadata_count = metadata.reviewed_query_count_by_split.get(split)
        split_kappa = metadata.weighted_kappa_by_split.get(split)
        conditions = {
            "test_split": split == "test",
            "minimum_sample": human_count >= MIN_HUMAN_REVIEWED_QUERIES,
            "required_denominators": required_denominators,
            "metadata_total_count_matches": metadata.reviewed_query_count_total == actual_total,
            "metadata_split_count_matches": split_metadata_count == actual_by_split.get(split, 0),
            "reviewer_count": metadata.reviewer_count >= MIN_HUMAN_REVIEWERS,
            "weighted_kappa": split_kappa is not None and split_kappa >= MIN_WEIGHTED_KAPPA,
            "absolute_gate": absolute_passed,
            "regression_baseline": regression_baseline_available,
            "regression_gate": regression_passed,
            **denominator_conditions,
        }
        failed = [name for name, passed in conditions.items() if not passed]
        return {
            "eligible": all(conditions.values()),
            "review_status": "human_reviewed",
            "query_count": human_count,
            "minimum_query_count": MIN_HUMAN_REVIEWED_QUERIES,
            "review_metadata": metadata.model_dump(mode="json"),
            "metric_observations": {
                name: observation.model_dump(mode="json") for name, observation in observations.items()
            },
            "minimum_reviewer_count": MIN_HUMAN_REVIEWERS,
            "minimum_weighted_kappa": MIN_WEIGHTED_KAPPA,
            "conditions": conditions,
            "reason": "모든 제품 근거 조건을 충족했습니다." if not failed else "미충족: " + ", ".join(failed),
        }

    def compare(self, report: EvalReport, baseline: BaselineFile) -> GateResult:
        """주요 지표가 기준선보다 tolerance 넘게 떨어지면 실패 (3.3.4절 회귀 규칙)."""
        if baseline.mode != report.config.mode:
            reason = f"기준선 mode={baseline.mode}와 평가 mode={report.config.mode}가 다릅니다."
            return GateResult(passed=False, reasons=[reason], checks=[])
        split = self.config.split
        entry = baseline.splits.get(split)
        if entry is None:
            return GateResult(passed=True, reasons=[], checks=[])
        base = entry.get("metrics", {})
        status_metrics = (
            report.overall
            if baseline.review_status == GATE_REVIEW_STATUS
            else report.by_review_status.get(baseline.review_status, {})
        )
        values = {**status_metrics, **(report.understanding if baseline.review_status == GATE_REVIEW_STATUS else {})}
        checks: list[GateCheck] = []
        reasons: list[str] = []
        tol = self.config.regression_tolerance
        for k in REGRESSION_KEYS:
            if k not in base:
                continue
            v = values.get(k)
            th = float(base[k]) - tol
            ok = v is not None and v >= th - 1e-12
            checks.append(GateCheck(name=f"regression:{k}", value=v, op=">=", threshold=round(th, 6), passed=ok))
            if not ok:
                reasons.append(f"회귀: {k} = {v} (기준선 {base[k]} − {tol})")
        return GateResult(passed=not reasons, reasons=reasons, checks=checks)


# ---------------------------------------------------------------------- 기준선 파일
def baseline_metrics(report: EvalReport, review_status: ReviewStatus = GATE_REVIEW_STATUS) -> dict[str, Any]:
    keys = (
        "recall@5",
        "recall@10",
        "mrr@10",
        "ndcg@10",
        "success@1",
        "category_recall@10_min",
        "true_empty_rate",
        "false_empty_rate",
    )
    ukeys = ("time_exact", "platform_f1", "content_type_f1", "keyword_inclusion", "intent_accuracy")
    source = report.overall if review_status == GATE_REVIEW_STATUS else report.by_review_status.get(review_status, {})
    m = {k: source[k] for k in keys if k in source}
    if review_status == GATE_REVIEW_STATUS:
        m.update({k: report.understanding[k] for k in ukeys if k in report.understanding})
    else:
        m.update({k: source[k] for k in ukeys if k in source})
    return m


def load_baseline(path: Path) -> BaselineFile:
    return BaselineFile.model_validate_json(path.read_text(encoding="utf-8"))


def load_review_metadata(path: Path | None) -> HumanReviewMetadata:
    if path is None or not path.exists():
        return HumanReviewMetadata()
    return HumanReviewMetadata.model_validate_json(path.read_text(encoding="utf-8"))


def update_baseline(path: Path, report: EvalReport, note: str = "") -> tuple[bool, str]:
    """주요 지표가 하나라도 낮아지지 않을 때만 갱신한다."""
    split = report.config.split
    if path.exists():
        base = load_baseline(path)
        if base.mode != report.config.mode:
            return False, f"기준선 mode={base.mode}와 평가 mode={report.config.mode}가 달라 갱신하지 않습니다."
        review_status = base.review_status
        if review_status != GATE_REVIEW_STATUS and not report.by_review_status.get(review_status, {}).get("n_queries"):
            return False, f"{review_status} 질의가 없어 기준선을 갱신하지 않습니다."
        if review_status == "human_reviewed" and not report.product_evidence.get("eligible"):
            return False, "human_reviewed 제품 근거가 eligible하지 않아 기준선을 갱신하지 않습니다."
        entry = base.splits.get(split)
        if entry is not None:
            previous = entry.get("metrics", {})
            status_metrics = (
                report.overall
                if review_status == GATE_REVIEW_STATUS
                else report.by_review_status.get(review_status, {})
            )
            current = {
                **status_metrics,
                **(report.understanding if review_status == GATE_REVIEW_STATUS else status_metrics),
            }
            decreases: list[str] = []
            for key in REGRESSION_KEYS:
                if key not in previous:
                    continue
                value = current.get(key)
                if value is None or float(value) < float(previous[key]) - 1e-12:
                    decreases.append(f"{key} {value} < {previous[key]}")
            if decreases:
                return False, "주요 지표가 기존 기준선보다 낮아 갱신하지 않습니다: " + "; ".join(decreases)
    else:
        base = BaselineFile(mode=report.config.mode)
        review_status = base.review_status
    if note:
        base.note = note
    base.splits[split] = {
        "metrics": baseline_metrics(report, review_status),
        "git_sha": report.git_sha,
        "counts": report.counts,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(base.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return True, f"기준선 갱신: {path} [{split}]"

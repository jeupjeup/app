"""Deterministic paired A/B runner for retrieval experiments."""

from __future__ import annotations

import math
import random
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from jupjup.container import AppContainer
from jupjup.eval.harness import (
    GATE_REVIEW_STATUS,
    EvalConfig,
    EvalHarness,
    EvalReport,
    QueryResult,
    default_container_factory,
)
from jupjup.eval.metrics import mean, percentile
from jupjup.search.service import SearchRequest
from jupjup.storage.seed import load_seed_file

_PAIRED_METRICS = ("recall@10", "mrr@10", "ndcg@10", "success@1", "true_empty", "false_empty")


class ArmConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    cross_rerank: bool = False
    query_assist: bool = False
    search_overrides: dict[str, Any] = Field(default_factory=dict)


class ABConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["recorded", "live", "mock"] = "recorded"
    split: Literal["dev", "test"] = "dev"
    arms: list[ArmConfig]
    bootstrap_iterations: int = Field(default=1000, ge=1)
    bootstrap_seed: int = 20261030
    baseline_arm: str = "A0"

    @model_validator(mode="after")
    def _valid_arms(self) -> ABConfig:
        names = [arm.name for arm in self.arms]
        if len(names) != len(set(names)):
            raise ValueError("A/B arm 이름은 중복될 수 없습니다")
        if self.baseline_arm not in names:
            raise ValueError("baseline_arm이 arms에 없습니다")
        return self


class DeltaCI(BaseModel):
    metric: str
    delta: float
    ci_low: float
    ci_high: float
    wins: int
    losses: int
    ties: int
    sign_test_p: float


class QueryDelta(BaseModel):
    query_id: str
    query: str
    metric: str
    baseline: float
    candidate: float
    baseline_top: str | None
    candidate_top: str | None


class RuleResult(BaseModel):
    name: str
    passed: bool
    detail: str


class AdoptionDecision(BaseModel):
    verdict: Literal["ADOPT", "ADOPT_WITH_LIMITS", "REJECT"]
    rules: list[RuleResult]


class FixedRegressionResult(BaseModel):
    query_id: str
    query: str
    expected_top: str | None
    actual_top: str | None
    expected_relaxations: tuple[str, ...]
    actual_relaxations: tuple[str, ...]
    passed: bool


class ABComparison(BaseModel):
    baseline: str
    candidate: str
    deltas: list[DeltaCI]
    subset_deltas: dict[str, list[DeltaCI]] = Field(default_factory=dict)
    category_deltas: dict[str, float] = Field(default_factory=dict)  # 카테고리별 Recall@10 차이
    candidate_absolute: dict[str, float] = Field(default_factory=dict)  # 10.1절 1번 절대 기준 입력
    candidate_denominators: dict[str, int] = Field(default_factory=dict)
    candidate_gate_passed: bool = False
    changed_queries: list[QueryDelta] = Field(default_factory=list)
    top1_changes: list[QueryDelta] = Field(default_factory=list)
    rerank_status: dict[str, int] = Field(default_factory=dict)
    fixed_regressions: list[FixedRegressionResult] = Field(default_factory=list)
    fixed_regression_expected_count: int = 1
    decision: AdoptionDecision | None = None


class LatencyReport(BaseModel):
    """live 벤치마크 결과. recorded 지표와 섞지 않는다."""

    device: str
    repeat: int
    queries: int
    rerank_p50_ms: float
    rerank_p95_ms: float
    rerank_max_ms: float
    search_p50_ms: float
    search_p95_ms: float
    search_max_ms: float
    baseline_search_p95_ms: float | None = None
    rerank_budget_ms: float
    search_budget_ms: float
    skip_rate: float
    rss_increase_mb: float | None = None
    cpu_enabled: bool = True


class ABReport(BaseModel):
    config: ABConfig
    created_at: datetime
    reports: dict[str, EvalReport]
    comparisons: list[ABComparison]

    def deterministic_dict(self) -> dict[str, Any]:
        data = self.model_dump(mode="json", exclude={"created_at"})
        for report in data["reports"].values():
            report.pop("created_at", None)
            report.pop("git_sha", None)
            report.pop("perf", None)
        return data


ContainerFactory = Callable[[EvalConfig], AppContainer]

# 10.1절 2번 허용 하락. true_empty는 하락을 허용하지 않는다.
_TOLERANCES = {"recall@10": 0.01, "mrr@10": 0.01, "ndcg@10": 0.01, "true_empty": 0.0}
_FALSE_EMPTY_TOLERANCE = 0.01
_CATEGORY_TOLERANCE = 0.02
_CHALLENGE_POSITIVE_MIN = 0.9091
_SKIP_RATE_MAX = 0.02
_RSS_INCREASE_MAX_MB = 1536.0

# design_reranker_query_assist.md 9.1: fixed table plus request locks, typo cases, and browse.
# These are always evaluated from an all-split run; the requested A/B split cannot silently remove them.
_FIXED_QUERY_IDS = (
    "q_0083",
    "q_0117",
    "q_0167",
    "q_0173",
    "ch_0003",
    "ch_0011",
    "q_0215",
    "q_0216",
    "q_0217",
    "q_0218",
    "q_0219",
    "q_0037",
    "q_0038",
    "q_0042",
    "q_0048",
    "q_0057",
    "q_0220",
    "q_0221",
)
_FIXED_EXPECTATIONS: dict[str, tuple[str | None, tuple[str, ...]]] = {
    "q_0083": ("c_alice_0136", ("time_window_expanded",)),
    "q_0117": ("c_alice_0140", ("time_window_expanded",)),
    "q_0167": ("c_alice_0040", ()),
    "q_0173": ("c_alice_0153", ()),
    "ch_0003": ("c_alice_0096", ()),
    "ch_0011": (None, ()),
}
EXPECTED_FIXED_REGRESSION_COUNT = 2 * len(_FIXED_QUERY_IDS)
_FIXED_PROBES: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    ("fixed_under_relax_platform", "경주 맛집 인스타", "c_alice_0153", ("platform_filter_dropped",)),
    ("fixed_under_relax_type", "하체 운동 유튜브", "c_alice_0040", ("platform_filter_dropped",)),
    (
        "fixed_double_facet_record",
        "경주 맛집 카톡 논문",
        "c_alice_0153",
        ("platform_filter_dropped", "content_type_filter_dropped"),
    ),
)


def _is_ranked_positive(result: QueryResult) -> bool:
    return bool(result.relevance) and not result.filter_only


def _per_query_value(result: QueryResult, metric: str) -> float | None:
    if metric == "true_empty":
        return float(result.empty) if not result.relevance else None
    if metric == "false_empty":
        return float(result.empty) if _is_ranked_positive(result) else None
    if not _is_ranked_positive(result):
        return None
    return result.per_query_metrics.get(metric)


def _exact_sign_test(wins: int, losses: int) -> float:
    n = wins + losses
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, k) for k in range(0, min(wins, losses) + 1)) / float(2**n)
    return min(1.0, 2.0 * tail)


def paired_delta_ci(
    baseline: Sequence[float],
    candidate: Sequence[float],
    *,
    metric: str,
    iterations: int = 1000,
    seed: int = 20261030,
) -> DeltaCI:
    if len(baseline) != len(candidate) or not baseline:
        raise ValueError("paired bootstrap에는 같은 길이의 비어 있지 않은 표본이 필요합니다")
    diffs = [right - left for left, right in zip(baseline, candidate, strict=True)]
    rng = random.Random(seed)
    samples = [mean([diffs[rng.randrange(len(diffs))] for _ in diffs]) for _ in range(iterations)]
    wins = sum(value > 1e-12 for value in diffs)
    losses = sum(value < -1e-12 for value in diffs)
    ties = len(diffs) - wins - losses
    return DeltaCI(
        metric=metric,
        delta=round(mean(diffs), 6),
        ci_low=round(percentile(samples, 2.5), 6),
        ci_high=round(percentile(samples, 97.5), 6),
        wins=wins,
        losses=losses,
        ties=ties,
        sign_test_p=round(_exact_sign_test(wins, losses), 6),
    )


def _paired_deltas(
    config: ABConfig,
    left: dict[str, QueryResult],
    right: dict[str, QueryResult],
    query_ids: Sequence[str],
) -> list[DeltaCI]:
    deltas: list[DeltaCI] = []
    for metric_index, metric in enumerate(_PAIRED_METRICS):
        pairs = [
            (_per_query_value(left[query_id], metric), _per_query_value(right[query_id], metric))
            for query_id in query_ids
        ]
        valid = [(a, b) for a, b in pairs if a is not None and b is not None]
        if not valid:
            continue
        deltas.append(
            paired_delta_ci(
                [a for a, _ in valid],
                [b for _, b in valid],
                metric=metric,
                iterations=config.bootstrap_iterations,
                seed=config.bootstrap_seed + metric_index,
            )
        )
    return deltas


def _category_recall(results: Sequence[QueryResult]) -> dict[str, float]:
    groups: dict[str, list[float]] = {}
    for result in results:
        value = _per_query_value(result, "recall@10")
        if value is None:
            continue
        for category in result.categories:
            groups.setdefault(category, []).append(value)
    return {category: mean(values) for category, values in sorted(groups.items())}


def _challenge_absolute(results: Sequence[QueryResult]) -> tuple[dict[str, float], dict[str, int]]:
    challenge = [result for result in results if "challenge" in result.categories]
    positives = [_per_query_value(result, "recall@10") for result in challenge]
    positive_values = [value for value in positives if value is not None]
    negatives = [result for result in challenge if not result.relevance]
    out: dict[str, float] = {}
    if positive_values:
        out["challenge_positive_recall@10"] = round(mean(positive_values), 6)
    if negatives:
        out["challenge_negative_true_empty"] = round(sum(r.empty for r in negatives) / len(negatives), 6)
    return out, {"challenge_positive": len(positive_values), "challenge_negative": len(negatives)}


def _fixed_regression_results(
    baseline: dict[str, QueryResult], candidate: dict[str, QueryResult]
) -> list[FixedRegressionResult]:
    checks: list[FixedRegressionResult] = []
    for query_id in _FIXED_QUERY_IDS:
        left = baseline.get(query_id)
        right = candidate.get(query_id)
        baseline_top = left.ranked_ids[0] if left and left.ranked_ids else None
        baseline_relaxations = tuple(left.relaxations) if left else ()
        expected_top, expected_relaxations = _FIXED_EXPECTATIONS.get(
            query_id, (baseline_top, baseline_relaxations)
        )
        actual_top = right.ranked_ids[0] if right and right.ranked_ids else None
        actual_relaxations = tuple(right.relaxations) if right else ()
        query = right.query if right is not None else left.query if left is not None else query_id
        checks.extend(
            [
            FixedRegressionResult(
                query_id=f"baseline:{query_id}",
                query=query,
                expected_top=expected_top,
                actual_top=baseline_top,
                expected_relaxations=expected_relaxations,
                actual_relaxations=baseline_relaxations,
                passed=(
                    left is not None
                    and baseline_top == expected_top
                    and baseline_relaxations == expected_relaxations
                ),
            ),
            FixedRegressionResult(
                query_id=f"candidate:{query_id}",
                query=query,
                expected_top=expected_top,
                actual_top=actual_top,
                expected_relaxations=expected_relaxations,
                actual_relaxations=actual_relaxations,
                passed=(
                    right is not None
                    and actual_top == expected_top
                    and actual_relaxations == expected_relaxations
                ),
            ),
            ]
        )
    return checks


def _run_fixed_probes(config: EvalConfig, container_factory: ContainerFactory) -> list[FixedRegressionResult]:
    container = container_factory(config)
    seed_report = load_seed_file(config.seeds_path, container.repo, container.indexer, strict=True)
    if seed_report.errors or seed_report.rolled_back:
        raise ValueError("고정 회귀 프로브 시드 적재에 실패했습니다")
    now = datetime.fromisoformat("2026-10-15T12:00:00+09:00")
    checks: list[FixedRegressionResult] = []
    for query_id, query, expected_top, expected_relaxations in _FIXED_PROBES:
        result = container.search.search(SearchRequest(user_id="u_alice", query=query, limit=10, now=now))
        actual_top = result.results[0].content_id if result.results else None
        actual_relaxations = tuple(result.applied_relaxations)
        checks.append(
            FixedRegressionResult(
                query_id=query_id,
                query=query,
                expected_top=expected_top,
                actual_top=actual_top,
                expected_relaxations=expected_relaxations,
                actual_relaxations=actual_relaxations,
                passed=actual_top == expected_top and actual_relaxations == expected_relaxations,
            )
        )
    return checks


def _compare(
    config: ABConfig,
    baseline_name: str,
    candidate_name: str,
    reports: dict[str, EvalReport],
    fixed_probes: dict[str, list[FixedRegressionResult]],
    fixed_results: dict[str, dict[str, QueryResult]],
) -> ABComparison:
    left = {result.query_id: result for result in reports[baseline_name].results}
    right = {result.query_id: result for result in reports[candidate_name].results}
    if left.keys() != right.keys():
        raise ValueError("A/B arm의 질의 집합이 다릅니다")
    # 전체 지표는 하네스 게이트와 같은 review_status 표본으로 계산한다.
    gated = sorted(query_id for query_id, result in left.items() if result.review_status == GATE_REVIEW_STATUS)
    challenge = sorted(query_id for query_id, result in left.items() if "challenge" in result.categories)
    deltas = _paired_deltas(config, left, right, gated)
    subset_deltas = {"challenge": _paired_deltas(config, left, right, challenge)} if challenge else {}

    base_categories = _category_recall([left[query_id] for query_id in gated])
    cand_categories = _category_recall([right[query_id] for query_id in gated])
    category_deltas = {
        category: round(cand_categories[category] - base_categories[category], 6)
        for category in base_categories
        if category in cand_categories
    }

    candidate_report = reports[candidate_name]
    challenge_absolute, challenge_denominators = _challenge_absolute(list(right.values()))
    absolute = {
        **challenge_absolute,
        "isolation_violations": float(candidate_report.safety.get("isolation_violations", 0)),
        "filter_violations": float(candidate_report.safety.get("filter_violations", 0)),
    }

    changed: list[QueryDelta] = []
    top1: list[QueryDelta] = []
    for query_id in sorted(left):
        lresult, rresult = left[query_id], right[query_id]
        ltop = lresult.ranked_ids[0] if lresult.ranked_ids else None
        rtop = rresult.ranked_ids[0] if rresult.ranked_ids else None
        if ltop != rtop:
            top1.append(
                QueryDelta(
                    query_id=query_id,
                    query=lresult.query,
                    metric="top1",
                    baseline=float(lresult.empty),
                    candidate=float(rresult.empty),
                    baseline_top=ltop,
                    candidate_top=rtop,
                )
            )
        for metric in _PAIRED_METRICS:
            a, b = _per_query_value(lresult, metric), _per_query_value(rresult, metric)
            if a is None or b is None or abs(a - b) <= 1e-12:
                continue
            changed.append(
                QueryDelta(
                    query_id=query_id,
                    query=lresult.query,
                    metric=metric,
                    baseline=a,
                    candidate=b,
                    baseline_top=ltop,
                    candidate_top=rtop,
                )
            )
    rerank_status: dict[str, int] = {}
    for result in right.values():
        key = result.rerank_status or "none"
        rerank_status[key] = rerank_status.get(key, 0) + 1
    return ABComparison(
        baseline=baseline_name,
        candidate=candidate_name,
        deltas=deltas,
        subset_deltas=subset_deltas,
        category_deltas=category_deltas,
        candidate_absolute=absolute,
        candidate_denominators=challenge_denominators,
        candidate_gate_passed=candidate_report.gate.passed,
        changed_queries=changed,
        top1_changes=top1,
        rerank_status=dict(sorted(rerank_status.items())),
        fixed_regressions=[
            *_fixed_regression_results(fixed_results[baseline_name], fixed_results[candidate_name]),
            *fixed_probes[baseline_name],
            *fixed_probes[candidate_name],
        ],
        fixed_regression_expected_count=(
            EXPECTED_FIXED_REGRESSION_COUNT + 2 * len(_FIXED_PROBES)
        ),
    )


def arm_overrides(arm: ArmConfig) -> dict[str, Any]:
    overrides = dict(arm.search_overrides)
    cross = dict(overrides.get("cross_rerank", {}))
    cross["enabled"] = arm.cross_rerank
    overrides["cross_rerank"] = cross
    return overrides


def run_ab(
    config: ABConfig,
    container_factory: ContainerFactory = default_container_factory,
    *,
    base_config: EvalConfig | None = None,
) -> ABReport:
    reports: dict[str, EvalReport] = {}
    fixed_probes: dict[str, list[FixedRegressionResult]] = {}
    fixed_results: dict[str, dict[str, QueryResult]] = {}
    template = base_config or EvalConfig()
    for arm in config.arms:
        eval_config = template.model_copy(
            update={"mode": config.mode, "split": config.split, "search_overrides": arm_overrides(arm)}
        )
        reports[arm.name] = EvalHarness(eval_config, container_factory=container_factory).run()
        full_report = EvalHarness(
            eval_config.model_copy(update={"split": "all"}), container_factory=container_factory
        ).run()
        fixed_results[arm.name] = {result.query_id: result for result in full_report.results}
        fixed_probes[arm.name] = _run_fixed_probes(eval_config, container_factory)
    comparisons = [
        _compare(config, config.baseline_arm, arm.name, reports, fixed_probes, fixed_results)
        for arm in config.arms
        if arm.name != config.baseline_arm
    ]
    return ABReport(config=config, created_at=datetime.now(UTC), reports=reports, comparisons=comparisons)


def decide_reranker(
    comparison: ABComparison,
    latency: LatencyReport | None = None,
    *,
    test_confirmed: bool | None = None,
) -> AdoptionDecision:
    """설계 10.1절 1~7번을 계산한다. 8번(사용자 승인)은 판정 뒤 PM이 받는다."""
    deltas = {delta.metric: delta for delta in comparison.deltas}
    challenge = {delta.metric: delta for delta in comparison.subset_deltas.get("challenge", [])}
    absolute = comparison.candidate_absolute
    rules: list[RuleResult] = []

    denominators = comparison.candidate_denominators
    denominator_complete = all(name in denominators for name in ("challenge_positive", "challenge_negative"))
    positive_required = denominators.get("challenge_positive", -1) != 0
    negative_required = denominators.get("challenge_negative", -1) != 0
    required_absolute = ["isolation_violations", "filter_violations"]
    if positive_required:
        required_absolute.append("challenge_positive_recall@10")
    if negative_required:
        required_absolute.append("challenge_negative_true_empty")
    absolute_complete = denominator_complete and all(metric in absolute for metric in required_absolute)
    fixed_ok = (
        len(comparison.fixed_regressions) == comparison.fixed_regression_expected_count
        and all(check.passed for check in comparison.fixed_regressions)
    )
    absolute_ok = (
        comparison.candidate_gate_passed
        and absolute_complete
        and (not positive_required or absolute["challenge_positive_recall@10"] >= _CHALLENGE_POSITIVE_MIN)
        and (not negative_required or absolute["challenge_negative_true_empty"] >= 1.0)
        and absolute["isolation_violations"] == 0.0
        and absolute["filter_violations"] == 0.0
        and fixed_ok
    )
    failed_fixed = [
        f"{check.query}({check.actual_top or 'empty'})"
        for check in comparison.fixed_regressions
        if not check.passed
    ]
    rules.append(
        RuleResult(
            name="1_absolute",
            passed=absolute_ok,
            detail=(
                f"gate_passed={comparison.candidate_gate_passed} metrics_complete={absolute_complete} "
                f"fixed_regressions={len(comparison.fixed_regressions)}/"
                f"{comparison.fixed_regression_expected_count} failed={failed_fixed} {_fmt(absolute)} "
                + (
                    "challenge_negative_true_empty=n/a (denominator=0)"
                    if denominator_complete and not negative_required
                    else ""
                )
            ),
        )
    )

    drops_ok = True
    details: list[str] = []
    for metric, tolerance in _TOLERANCES.items():
        delta = deltas.get(metric)
        ok = delta is not None and delta.delta >= -tolerance
        drops_ok &= ok
        details.append(f"{metric}={_delta(delta)}")
    false_empty = deltas.get("false_empty")
    fe_ok = false_empty is not None and false_empty.delta <= _FALSE_EMPTY_TOLERANCE
    category_min = min(comparison.category_deltas.values(), default=0.0)
    category_ok = bool(comparison.category_deltas) and category_min >= -_CATEGORY_TOLERANCE
    details.append(f"false_empty={_delta(false_empty)} category_min={category_min:+.4f}")
    rules.append(RuleResult(name="2_allowed_drop", passed=drops_ok and fe_ok and category_ok, detail=" ".join(details)))

    def improved(delta: DeltaCI | None, minimum: float) -> bool:
        return delta is not None and delta.delta >= minimum and delta.ci_low > 0

    seesaw = (
        deltas.get("true_empty") is not None
        and deltas.get("recall@10") is not None
        and deltas["true_empty"].delta >= 0
        and deltas["recall@10"].delta >= 0
        and (improved(deltas["true_empty"], 1e-9) or improved(deltas["recall@10"], 1e-9))
    )
    paths = {
        "ndcg@10+0.02": improved(deltas.get("ndcg@10"), 0.02),
        "success@1+0.03": improved(deltas.get("success@1"), 0.03),
        "challenge_recall@10+0.05": improved(challenge.get("recall@10"), 0.05),
        "seesaw": bool(seesaw),
    }
    rules.append(RuleResult(name="3_improvement", passed=any(paths.values()), detail=_fmt(paths)))

    ci_ok = all(
        (delta := deltas.get(metric)) is not None and delta.ci_low >= -tolerance
        for metric, tolerance in _TOLERANCES.items()
    )
    rules.append(
        RuleResult(
            name="4_confidence",
            passed=ci_ok,
            detail=" ".join(f"{m}.ci_low={_ci(deltas.get(m))}" for m in _TOLERANCES),
        )
    )

    if latency is None:
        rules.append(RuleResult(name="5_latency", passed=False, detail="live 벤치마크 없음"))
        rules.append(RuleResult(name="6_operations", passed=False, detail="live 벤치마크 없음"))
    else:
        latency_ok = (
            latency.rerank_p95_ms <= latency.rerank_budget_ms and latency.search_p95_ms <= latency.search_budget_ms
        )
        rules.append(
            RuleResult(
                name="5_latency",
                passed=latency_ok,
                detail=(
                    f"device={latency.device} rerank_p95={latency.rerank_p95_ms:.1f}/{latency.rerank_budget_ms:g}ms "
                    f"search_p95={latency.search_p95_ms:.1f}/{latency.search_budget_ms:g}ms"
                ),
            )
        )
        rss_ok = latency.rss_increase_mb is not None and latency.rss_increase_mb <= _RSS_INCREASE_MAX_MB
        rules.append(
            RuleResult(
                name="6_operations",
                passed=latency.skip_rate <= _SKIP_RATE_MAX and rss_ok,
                detail=f"skip_rate={latency.skip_rate:.4f} rss_increase_mb={latency.rss_increase_mb}",
            )
        )
    rules.append(
        RuleResult(
            name="7_test_confirmation",
            passed=test_confirmed is True,
            detail="test 1~4 재확인" if test_confirmed is not None else "test 확인 결과 없음",
        )
    )

    verdict: Literal["ADOPT", "ADOPT_WITH_LIMITS", "REJECT"] = (
        "ADOPT" if all(rule.passed for rule in rules) else "REJECT"
    )
    if verdict == "ADOPT" and latency is not None and not latency.cpu_enabled:
        verdict = "ADOPT_WITH_LIMITS"
    return AdoptionDecision(verdict=verdict, rules=rules)


def reranker_test_confirmed(comparison: ABComparison) -> bool:
    """Recompute design 10.1 rules 1-4 from a test-split comparison."""
    decision = decide_reranker(comparison)
    return all(rule.passed for rule in decision.rules[:4])


def _delta(delta: DeltaCI | None) -> str:
    return "n/a" if delta is None else f"{delta.delta:+.4f}"


def _ci(delta: DeltaCI | None) -> str:
    return "n/a" if delta is None else f"{delta.ci_low:+.4f}"


def _fmt(values: dict[str, Any]) -> str:
    return " ".join(f"{key}={value}" for key, value in values.items())

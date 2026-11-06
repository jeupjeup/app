"""Profile swap decision for the ingest analyzer (design_local_analyzer.md 8.6절, PRD 3.5.5절, T26a).

두 인제스트 평가 리포트(후보, 현행)를 같은 골든셋·split·판정기에서 비교해 교체 후보 여부를 판정한다.

- **downgrade** (더 작은 모델로): 3.5.4절 절대 기준 전부 + 하락 허용치(태그·엔티티·장소 F1 ≤ 0.03, 비충실 증가 ≤ 0.01,
  검색 연결 Recall@10 하락 ≤ 0.02) + 95% 구간의 나쁜 쪽 끝도 허용치 안 + 자원 30% 이상 개선(single p95 지연, 피크 RSS,
  비용 중 하나). 로컬 프로필은 비용이 0이라 실제로는 live 벤치(``bench``)의 지연·RSS로 본다.
- **upgrade** (더 큰 모델로): 절대 기준 전부 + 주요 지표(비충실 비율, 핵심 사실 재현율, 엔티티 F1, 대표 태그 F1) 중 하나
  이상이 개선되고 그 구간이 0을 넘음 + 허용치 지표 모두 downgrade 허용치 안 + live single p95 ≤ 60초.
- 두 리포트의 split, 골든셋 해시(``golden_sha256``), 판정기 프로필·보정 상태, 검색 연결 기준(질의 수·사람 분석
  Recall@10)이 다르면 ``CompareRefused``로 거부한다.
- 판정에 쓰는 값이 유한하지 않거나(``NaN``·``±Infinity``) 범위(비율 0~1, 지연·RSS > 0)를 벗어나면 거부한다 (T26a 검수
  M1). 비교도 닫힌 쪽으로 한다: 값이 이상하면 "허용치 안"으로 읽히지 않는다.
- 부트스트랩은 건(source_id) 단위 쌍 재표집이다. 한 번 뽑은 표본을 모든 지표에 같이 쓰고, ``random.Random(seed)``로
  고정한다. 건수 < 40이면 경고를 낸다. 지표마다 **두 쪽 다 값이 있는 건만** 쌍으로 쓴다(한쪽 실패 건은 빼고 경고).

델타 부호는 항상 ``후보 − 현행``이다. 높을수록 좋은 지표는 음수가 나빠짐, 비충실 비율은 양수가 나빠짐이다.
``eligible``은 ``reasons``(미충족 사유)가 비었을 때만 참이다.
"""

from __future__ import annotations

import math
import random
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from jupjup.eval.ingest_bench import MAP_REDUCE_P95_BUDGET_S, SINGLE_P95_BUDGET_S, AnalyzeBenchReport, LatencyStats
from jupjup.eval.ingest_harness import (
    LINKAGE_DROP_LIMIT,
    LOCAL_GATE,
    IngestEvalReport,
    IngestItemResult,
    gate_passes,
)

Direction = Literal["downgrade", "upgrade"]

LINKAGE_METRIC = "search_recall@10"
# 3.5.5절 4번 하락 허용치. 비충실 비율만 낮을수록 좋다.
DOWNGRADE_TOLERANCES: dict[str, float] = {
    "tag_f1": 0.03,
    "entity_f1": 0.03,
    "location_f1": 0.03,
    "unsupported_sentence_rate": 0.01,
    LINKAGE_METRIC: 0.02,
}
LOWER_IS_BETTER: frozenset[str] = frozenset({"unsupported_sentence_rate"})
UPGRADE_PRIMARY: tuple[str, ...] = ("unsupported_sentence_rate", "summary_key_fact_recall", "entity_f1", "tag_f1")
# 건 단위로 구간을 내는 지표 (허용치가 없는 것은 참고용).
ITEM_METRICS: tuple[str, ...] = (
    "schema_first_pass_rate",
    "tag_f1",
    "entity_f1",
    "location_f1",
    "category_accuracy",
    "save_intent_accuracy",
    "summary_key_fact_recall",
    "unsupported_sentence_rate",
)
RESOURCE_GAIN_MIN = 0.30
SMALL_SAMPLE_WARNING = 40
DEFAULT_N_BOOT = 1000
DEFAULT_SEED = 20261102


class CompareRefused(ValueError):
    """두 리포트를 비교할 수 없다 (split·골든셋·판정기·건 목록 불일치 등). CLI 종료 2."""


class DeltaCI(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric: str
    delta: float  # 후보 − 현행
    ci_low: float
    ci_high: float
    tolerance: float | None  # 허용 나빠짐 폭 (None이면 참고용)


class BenchPair(BaseModel):
    """두 프로필의 live 벤치(`jupjup bench analyze`) 결과. 지연·메모리는 이 값으로만 판단한다 (8.5절)."""

    model_config = ConfigDict(extra="forbid")

    candidate: AnalyzeBenchReport
    incumbent: AnalyzeBenchReport


class SwapDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    direction: Direction
    eligible: bool
    reasons: list[str]  # 미충족 사유. 비었을 때만 eligible
    deltas: dict[str, DeltaCI]
    resource_gain: dict[str, float]  # p95 지연, 피크 RSS, 비용의 상대 개선 (양수 = 후보가 좋음)
    # 두 프로필의 절대값 (PRD 3.5.5절 3번 "같은 표"): 3.5.4절 키, 검색 연결, 벤치 지연·RSS·토큰/초. 판정에는 쓰지 않는다
    candidate_overall: dict[str, float | None]
    incumbent_overall: dict[str, float | None]
    # 아래는 설계 시그니처에 더한 설명 필드 (판정에는 쓰지 않는다)
    candidate_profile: str
    incumbent_profile: str
    split: str
    golden_sha256: str
    n_items: int
    n_boot: int
    seed: int
    warnings: list[str]


# ------------------------------------------------------------------------------------------------ 거부 조건
def _profile(report: IngestEvalReport) -> str:
    return report.runtime.profile if report.runtime is not None else report.config.profile


def _check_comparable(candidate: IngestEvalReport, incumbent: IngestEvalReport) -> str:
    """비교 거부 조건을 확인하고 공통 골든셋 해시를 돌려준다."""
    if candidate.config.split != incumbent.config.split:
        raise CompareRefused(f"split이 다릅니다: 후보 {candidate.config.split}, 현행 {incumbent.config.split}")
    for name, report in (("후보", candidate), ("현행", incumbent)):
        if report.config.mode == "mock" or report.runtime is None:
            raise CompareRefused(f"{name} 리포트가 mock(로컬 프로필 실행 아님)입니다. recorded·live만 비교합니다")
        if report.golden_sha256 is None:
            raise CompareRefused(f"{name} 리포트에 골든셋 해시(golden_sha256)가 없습니다")
        if report.misses:
            raise CompareRefused(f"{name} 리포트에 녹화 미스가 {len(report.misses)}건 있습니다")
    golden = candidate.golden_sha256 or ""
    other = incumbent.golden_sha256 or ""
    if golden != other:
        raise CompareRefused(f"골든셋 해시가 다릅니다: 후보 {golden[:16]}…, 현행 {other[:16]}…")
    if candidate.config.judge_profile != incumbent.config.judge_profile:
        raise CompareRefused(
            f"판정기 프로필이 다릅니다: 후보 {candidate.config.judge_profile}, 현행 {incumbent.config.judge_profile}"
        )
    cj, ij = candidate.judge, incumbent.judge
    if (cj is None) != (ij is None):
        raise CompareRefused("판정기 블록이 한쪽 리포트에만 있습니다")
    if cj is not None and ij is not None:
        if cj.recording_model_id != ij.recording_model_id or cj.prompts != ij.prompts:
            raise CompareRefused("판정기 모델(recording_model_id) 또는 판정 프롬프트가 다릅니다")
        if (cj.faithfulness_calibrated, cj.keyfact_calibrated) != (ij.faithfulness_calibrated, ij.keyfact_calibrated):
            raise CompareRefused("판정기 보정 상태가 다릅니다 (지표 정의가 달라 비교하지 않습니다)")
    candidate_ids = [item.source_id for item in candidate.items]
    incumbent_ids = [item.source_id for item in incumbent.items]
    if len(set(candidate_ids)) != len(candidate_ids) or len(set(incumbent_ids)) != len(incumbent_ids):
        raise CompareRefused("리포트에 같은 source_id 건이 두 번 있습니다")
    if set(candidate_ids) != set(incumbent_ids):
        only = sorted(set(candidate_ids) ^ set(incumbent_ids))
        raise CompareRefused(f"두 리포트의 건 목록이 다릅니다: {', '.join(only[:5])}")
    if not candidate_ids:
        raise CompareRefused("비교할 건이 없습니다")
    _check_linkage_baseline(candidate, incumbent)
    return golden


def _check_linkage_baseline(candidate: IngestEvalReport, incumbent: IngestEvalReport) -> None:
    """두 리포트의 분석기 R@10이 같은 기준(질의 수, 사람 분석 R@10)으로 잰 값인지 본다 (T26a 검수 L3)."""
    cand, inc = candidate.search_linkage, incumbent.search_linkage
    if cand is None or inc is None or cand.get("recorded_embedder") != inc.get("recorded_embedder"):
        return
    for key in ("n_queries", "human_recall@10"):
        if cand.get(key) != inc.get(key):
            raise CompareRefused(
                f"검색 연결 기준이 다릅니다: {key} 후보 {cand.get(key)}, 현행 {inc.get(key)} "
                "(같은 질의·사람 분석으로 재야 합니다)"
            )


# 판정에 쓰는 값의 범위. 비율은 0~1, 검색 연결 하락은 -1~1, 비용은 0 이상.
_UNIT_INTERVAL = (0.0, 1.0)
_LINKAGE_COUNTS = frozenset({"n_queries", "seeds_succeeded", "seeds_not_succeeded"})


def _finite_in(value: float, low: float | None, high: float | None, *, low_open: bool = False) -> bool:
    if not math.isfinite(value):
        return False
    if low is not None and (value <= low if low_open else value < low):
        return False
    return high is None or value <= high


def _refuse_bad(where: str, key: str, value: float) -> CompareRefused:
    return CompareRefused(f"{where}의 {key} 값이 유한하지 않거나 범위를 벗어났습니다: {value!r}")


def _check_values(report: IngestEvalReport, name: str) -> None:
    """판정에 쓰는 리포트 값이 유한하고 범위 안인지 본다 (T26a 검수 M1). pydantic은 JSON NaN·Infinity를 받아들인다."""
    for item in report.items:
        for metric in ITEM_METRICS:
            value = item.metrics.get(metric)
            if value is not None and not _finite_in(value, *_UNIT_INTERVAL):
                raise _refuse_bad(f"{name} 리포트 건 {item.source_id}", metric, value)
    for key, _, _ in LOCAL_GATE:
        value = report.overall.get(key)
        if value is not None and not _finite_in(value, *_UNIT_INTERVAL):
            raise _refuse_bad(f"{name} 리포트 overall", key, value)
    cost = report.overall.get("cost_usd_per_item")
    if cost is not None and not _finite_in(cost, 0.0, None):
        raise _refuse_bad(f"{name} 리포트 overall", "cost_usd_per_item", cost)
    for key, value in (report.search_linkage or {}).items():
        low: float = 0.0
        high: float | None = 1.0
        if key.endswith("_drop"):
            low = -1.0
        elif key in _LINKAGE_COUNTS:
            high = None
        if not _finite_in(value, low, high):
            raise _refuse_bad(f"{name} 리포트 search_linkage", key, value)


def _check_bench_values(run: AnalyzeBenchReport, name: str) -> None:
    for label, stats in (("single", run.single), ("map_reduce", run.map_reduce)):
        for key in ("p50_s", "p95_s"):
            value = getattr(stats, key)
            if value is not None and not _finite_in(value, 0.0, None, low_open=True):
                raise _refuse_bad(f"{name} 벤치 {label}", key, value)
    if not _finite_in(run.peak_rss_mb, 0.0, None, low_open=True):
        raise _refuse_bad(f"{name} 벤치", "peak_rss_mb", run.peak_rss_mb)
    if run.output_tokens_per_s is not None and not _finite_in(run.output_tokens_per_s, 0.0, None):
        raise _refuse_bad(f"{name} 벤치", "output_tokens_per_s", run.output_tokens_per_s)
    # 예산은 8.6절 고정값이다. 파일의 budget·within_budget 플래그를 믿지 않고 다시 계산해 맞춰 본다 (T26a 검수 L2).
    for label, stats, budget in (
        ("single", run.single, SINGLE_P95_BUDGET_S),
        ("map_reduce", run.map_reduce, MAP_REDUCE_P95_BUDGET_S),
    ):
        if stats.budget_p95_s != budget:
            raise CompareRefused(
                f"{name} 벤치 {label}의 지연 예산이 {stats.budget_p95_s}초입니다 (고정 예산 {budget:g}초)"
            )
        if stats.within_budget != _within_budget(stats, budget):
            raise CompareRefused(f"{name} 벤치 {label}의 within_budget 값이 p95와 맞지 않습니다")


def _within_budget(stats: LatencyStats, budget: float) -> bool | None:
    return None if stats.p95_s is None else stats.p95_s <= budget


def _check_bench(
    bench: BenchPair, candidate: IngestEvalReport, incumbent: IngestEvalReport, warnings: list[str]
) -> None:
    for name, run, report in (("후보", bench.candidate, candidate), ("현행", bench.incumbent, incumbent)):
        runtime = report.runtime
        if runtime is None or run.profile != runtime.profile or run.recording_model_id != runtime.recording_model_id:
            raise CompareRefused(
                f"{name} 벤치가 리포트와 다른 프로필·모델입니다: {run.profile} ({run.recording_model_id[:24]}…)"
            )
        _check_bench_values(run, name)
    if bench.candidate.split != bench.incumbent.split:
        raise CompareRefused(f"두 벤치의 split이 다릅니다: {bench.candidate.split}, {bench.incumbent.split}")
    if bench.candidate.split != "dev":
        warnings.append(f"벤치 split이 dev가 아닙니다 ({bench.candidate.split}). 지연은 dev 벤치로 판단합니다 (8.5절)")


# ------------------------------------------------------------------------------------------------ 부트스트랩
def _complete_pairs(
    candidate: Mapping[str, IngestItemResult], incumbent: Mapping[str, IngestItemResult], ordered: Sequence[str]
) -> tuple[dict[str, list[tuple[float | None, float | None]]], dict[str, int]]:
    """지표마다 두 쪽 다 값이 있는 건만 쌍으로 남긴다 (8.6절 건 단위 쌍, T26a 검수 L5). 한쪽만 있는 건 수도 센다."""
    pairs: dict[str, list[tuple[float | None, float | None]]] = {}
    one_sided: dict[str, int] = {}
    for metric in ITEM_METRICS:
        rows: list[tuple[float | None, float | None]] = []
        for sid in ordered:
            cand, inc = _item_value(candidate[sid], metric), _item_value(incumbent[sid], metric)
            if (cand is None) != (inc is None):
                one_sided[metric] = one_sided.get(metric, 0) + 1
                cand = inc = None
            rows.append((cand, inc))
        pairs[metric] = rows
    return pairs, one_sided


def _item_value(item: IngestItemResult, metric: str) -> float | None:
    if metric == "schema_first_pass_rate":
        return float(item.schema_first_pass)
    # 분석 출력이 없는 건(실패)은 품질 지표가 없다. 리포트 overall과 같이 출력이 있는 건만 평균한다.
    return item.metrics.get(metric)


def _mean(values: Sequence[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    return sum(present) / len(present) if present else None


def _percentile(sorted_values: Sequence[float], q: float) -> float:
    """선형 보간 백분위 (numpy 기본 방식과 같다)."""
    position = q * (len(sorted_values) - 1)
    low = int(position)
    high = min(low + 1, len(sorted_values) - 1)
    return sorted_values[low] + (sorted_values[high] - sorted_values[low]) * (position - low)


def paired_bootstrap(
    pairs: dict[str, list[tuple[float | None, float | None]]], *, n_boot: int, seed: int
) -> dict[str, tuple[float, float, float]]:
    """지표마다 (델타, 2.5% 하한, 97.5% 상한). ``pairs[metric][i]``는 i번째 건의 (후보, 현행) 값.

    모든 지표가 같은 재표집 인덱스를 쓴다. 한쪽 값이 하나도 없는 지표는 결과에서 빠진다.
    """
    if n_boot < 1:
        raise ValueError("n_boot은 1 이상이어야 합니다")
    sizes = {len(rows) for rows in pairs.values()}
    if len(sizes) > 1:
        raise ValueError("지표마다 건수가 같아야 합니다")
    n = sizes.pop() if sizes else 0
    rng = random.Random(seed)
    samples: dict[str, list[float]] = {metric: [] for metric in pairs}
    for _ in range(n_boot):
        indices = [rng.randrange(n) for _ in range(n)]
        for metric, rows in pairs.items():
            cand = _mean([rows[i][0] for i in indices])
            inc = _mean([rows[i][1] for i in indices])
            if cand is not None and inc is not None:
                samples[metric].append(cand - inc)
    result: dict[str, tuple[float, float, float]] = {}
    for metric, rows in pairs.items():
        cand = _mean([row[0] for row in rows])
        inc = _mean([row[1] for row in rows])
        if cand is None or inc is None or not samples[metric]:
            continue
        ordered = sorted(samples[metric])
        result[metric] = (
            round(cand - inc, 6),
            round(_percentile(ordered, 0.025), 6),
            round(_percentile(ordered, 0.975), 6),
        )
    return result


# ------------------------------------------------------------------------------------------------ 규칙
def _absolute_failures(report: IngestEvalReport) -> list[str]:
    """3.5.4절 기본 분석기 열 (검색 연결은 recorded 임베딩 값으로만)."""
    failures = [
        f"절대 기준 미충족: {name} {report.overall.get(name)} {op} {threshold:g}"
        for name, op, threshold in LOCAL_GATE
        if not gate_passes(report.overall.get(name), op, threshold)
    ]
    linkage = report.search_linkage
    if linkage is None or linkage.get("recorded_embedder") != 1.0:
        failures.append("절대 기준 판정 불가: 후보 리포트에 recorded 검색 연결 지표가 없습니다 (--linkage recorded)")
    elif not gate_passes(linkage.get("recall@10_drop"), "<=", LINKAGE_DROP_LIMIT):
        failures.append(
            f"절대 기준 미충족: search_recall@10_drop {linkage.get('recall@10_drop')} <= {LINKAGE_DROP_LIMIT:g}"
        )
    return failures


def _worsening(delta: DeltaCI) -> tuple[float, float]:
    """(점추정 나빠짐, 구간의 나쁜 쪽 끝 나빠짐). 양수가 나빠짐."""
    if delta.metric in LOWER_IS_BETTER:
        return delta.delta, delta.ci_high
    return -delta.delta, -delta.ci_low


def _improved(delta: DeltaCI) -> bool:
    """구간 전체가 개선 쪽에 있다 (높을수록 좋은 지표는 하한 > 0, 비충실 비율은 상한 < 0)."""
    return delta.ci_high < 0 if delta.metric in LOWER_IS_BETTER else delta.ci_low > 0


def _tolerance_failures(deltas: dict[str, DeltaCI]) -> list[str]:
    failures: list[str] = []
    for metric, tolerance in DOWNGRADE_TOLERANCES.items():
        delta = deltas.get(metric)
        if delta is None:
            failures.append(f"허용치 판정 불가: {metric} 값이 두 리포트에 모두 있어야 합니다")
            continue
        point, bound = _worsening(delta)
        # 닫힌 쪽 비교: NaN이면 "허용치 안"이 아니다 (T26a 검수 M1)
        if not point <= tolerance:
            failures.append(f"하락 허용치 초과: {metric} 나빠짐 {point:.4f} > {tolerance:g}")
        elif not bound <= tolerance:
            failures.append(f"95% 구간이 허용치를 넘음: {metric} 나쁜 쪽 끝 {bound:.4f} > {tolerance:g}")
    return failures


def _relative_gain(incumbent: float | None, candidate: float | None) -> float | None:
    if incumbent is None or candidate is None or incumbent <= 0:
        return None
    return round((incumbent - candidate) / incumbent, 6)


def _resource_gain(
    candidate: IngestEvalReport, incumbent: IngestEvalReport, bench: BenchPair | None
) -> dict[str, float]:
    gains: dict[str, float | None] = {
        "cost_usd_per_item": _relative_gain(
            incumbent.overall.get("cost_usd_per_item"), candidate.overall.get("cost_usd_per_item")
        )
    }
    if bench is not None:
        gains["single_p95_s"] = _relative_gain(bench.incumbent.single.p95_s, bench.candidate.single.p95_s)
        gains["peak_rss_mb"] = _relative_gain(bench.incumbent.peak_rss_mb, bench.candidate.peak_rss_mb)
    return {key: value for key, value in gains.items() if value is not None}


def _linkage_delta(candidate: IngestEvalReport, incumbent: IngestEvalReport) -> DeltaCI | None:
    """검색 연결 Recall@10 (분석기 인덱스). 리포트에 질의별 값이 없어 구간은 점추정과 같게 둔다."""
    values: list[float] = []
    for report in (candidate, incumbent):
        linkage = report.search_linkage
        if linkage is None or linkage.get("recorded_embedder") != 1.0 or "analyzer_recall@10" not in linkage:
            return None
        values.append(linkage["analyzer_recall@10"])
    delta = round(values[0] - values[1], 6)
    return DeltaCI(
        metric=LINKAGE_METRIC, delta=delta, ci_low=delta, ci_high=delta, tolerance=DOWNGRADE_TOLERANCES[LINKAGE_METRIC]
    )


def _downgrade_failures(deltas: dict[str, DeltaCI], resource_gain: dict[str, float]) -> list[str]:
    failures = _tolerance_failures(deltas)
    best = max(resource_gain.values(), default=None)
    if best is None:
        failures.append("자원 개선 판정 불가: live 벤치(BenchPair)나 비용 값이 없습니다")
    elif best < RESOURCE_GAIN_MIN:
        detail = ", ".join(f"{key} {value:+.1%}" for key, value in sorted(resource_gain.items()))
        failures.append(f"자원 개선 부족: 최대 {best:.1%} < {RESOURCE_GAIN_MIN:.0%} ({detail})")
    return failures


def _upgrade_failures(deltas: dict[str, DeltaCI], bench: BenchPair | None, warnings: list[str]) -> list[str]:
    failures: list[str] = []
    improved = [metric for metric in UPGRADE_PRIMARY if metric in deltas and _improved(deltas[metric])]
    if not improved:
        failures.append(
            "주요 지표 개선 없음: " + ", ".join(UPGRADE_PRIMARY) + " 중 구간이 0을 넘게 개선된 지표가 없습니다"
        )
    failures += _tolerance_failures(deltas)
    if bench is None:
        failures.append("지연 예산 판정 불가: live 벤치(BenchPair)가 없습니다")
    else:
        single = bench.candidate.single
        if _within_budget(single, SINGLE_P95_BUDGET_S) is not True:
            failures.append(f"지연 예산 미충족: 후보 single p95 {single.p95_s}초 (예산 {SINGLE_P95_BUDGET_S:g}초)")
        if bench.candidate.map_reduce.within_budget is False:
            warnings.append(
                f"후보 map_reduce p95 {bench.candidate.map_reduce.p95_s}초가 예산 "
                f"{bench.candidate.map_reduce.budget_p95_s:g}초를 넘습니다"
            )
    return failures


def compare_profiles(
    candidate: IngestEvalReport,
    incumbent: IngestEvalReport,
    *,
    direction: Direction,
    bench: BenchPair | None = None,
    n_boot: int = DEFAULT_N_BOOT,
    seed: int = DEFAULT_SEED,
) -> SwapDecision:
    """8.6절 두 방향 교체 판정. 거부 조건이면 ``CompareRefused``."""
    if direction not in ("downgrade", "upgrade"):
        raise ValueError("direction은 downgrade|upgrade")
    golden_sha256 = _check_comparable(candidate, incumbent)
    for name, report in (("후보", candidate), ("현행", incumbent)):
        _check_values(report, name)
    warnings: list[str] = []
    if bench is not None:
        _check_bench(bench, candidate, incumbent, warnings)
    incumbent_items = {item.source_id: item for item in incumbent.items}
    ordered = sorted(item.source_id for item in candidate.items)
    candidate_items = {item.source_id: item for item in candidate.items}
    pairs, one_sided = _complete_pairs(candidate_items, incumbent_items, ordered)
    deltas: dict[str, DeltaCI] = {
        metric: DeltaCI(metric=metric, delta=d, ci_low=lo, ci_high=hi, tolerance=DOWNGRADE_TOLERANCES.get(metric))
        for metric, (d, lo, hi) in paired_bootstrap(pairs, n_boot=n_boot, seed=seed).items()
    }
    linkage = _linkage_delta(candidate, incumbent)
    if linkage is not None:
        deltas[LINKAGE_METRIC] = linkage

    if one_sided:
        detail = ", ".join(f"{metric} {count}건" for metric, count in sorted(one_sided.items()))
        warnings.append(f"한쪽에만 값이 있는 건은 쌍에서 뺐습니다 (실패 건): {detail}")
    if len(ordered) < SMALL_SAMPLE_WARNING:
        warnings.append(f"표본이 작습니다: {len(ordered)}건 < {SMALL_SAMPLE_WARNING}건 (구간이 넓다)")
    if linkage is not None:
        warnings.append("검색 연결 Recall@10은 리포트에 질의별 값이 없어 구간 대신 점추정으로 판정했습니다")
    if candidate.config.mode != incumbent.config.mode:
        warnings.append(f"두 리포트의 mode가 다릅니다: 후보 {candidate.config.mode}, 현행 {incumbent.config.mode}")
    if _profile(candidate) == _profile(incumbent):
        warnings.append(f"두 리포트의 프로필이 같습니다: {_profile(candidate)}")
    # 판정기 상태는 거부 조건으로 두 리포트가 같다.
    judge = candidate.judge
    if judge is None:
        warnings.append("판정기 미사용: 비충실 비율·핵심 사실 재현율은 결정적 값입니다 (판정기 미보정)")
    elif not (judge.faithfulness_calibrated and judge.keyfact_calibrated):
        warnings.append("판정기 미보정 과제가 있습니다: 그 지표는 결정적 값입니다")

    reasons = _absolute_failures(candidate)
    resource_gain = _resource_gain(candidate, incumbent, bench)
    if direction == "downgrade":
        reasons += _downgrade_failures(deltas, resource_gain)
    else:
        reasons += _upgrade_failures(deltas, bench, warnings)
    return SwapDecision(
        direction=direction,
        eligible=not reasons,
        reasons=reasons,
        deltas=deltas,
        resource_gain=resource_gain,
        candidate_overall=_absolute_values(candidate, None if bench is None else bench.candidate),
        incumbent_overall=_absolute_values(incumbent, None if bench is None else bench.incumbent),
        candidate_profile=_profile(candidate),
        incumbent_profile=_profile(incumbent),
        split=candidate.config.split,
        golden_sha256=golden_sha256,
        n_items=len(ordered),
        n_boot=n_boot,
        seed=seed,
        warnings=warnings,
    )


def _absolute_values(report: IngestEvalReport, bench: AnalyzeBenchReport | None) -> dict[str, float | None]:
    values: dict[str, float | None] = {key: report.overall.get(key) for key, _, _ in LOCAL_GATE}
    values["cost_usd_per_item"] = report.overall.get("cost_usd_per_item")
    linkage = report.search_linkage or {}
    recorded = linkage.get("recorded_embedder") == 1.0
    values[LINKAGE_METRIC] = linkage.get("analyzer_recall@10") if recorded else None
    values["search_recall@10_drop"] = linkage.get("recall@10_drop") if recorded else None
    if bench is not None:
        values.update(
            {
                "bench_single_p50_s": bench.single.p50_s,
                "bench_single_p95_s": bench.single.p95_s,
                "bench_map_reduce_p95_s": bench.map_reduce.p95_s,
                "bench_peak_rss_mb": bench.peak_rss_mb,
                "bench_output_tokens_per_s": bench.output_tokens_per_s,
            }
        )
    return values


# ------------------------------------------------------------------------------------------------ 리포트
def load_report(path: Path) -> IngestEvalReport:
    return IngestEvalReport.model_validate_json(path.read_text(encoding="utf-8"))


def load_bench(path: Path) -> AnalyzeBenchReport:
    return AnalyzeBenchReport.model_validate_json(path.read_text(encoding="utf-8"))


def _cell(value: float | None) -> str:
    return "—" if value is None else f"{value:.4f}"


def render_swap_markdown(decision: SwapDecision) -> str:
    lines = [
        f"# 프로필 교체 판정 — {decision.direction}: {decision.candidate_profile} ← {decision.incumbent_profile}",
        "",
        f"- 판정: **{'교체 후보 (eligible)' if decision.eligible else '교체 불가'}**",
        f"- split={decision.split}, 건수 {decision.n_items}, 골든셋 {decision.golden_sha256[:16]}…",
        f"- 건 단위 쌍 부트스트랩 {decision.n_boot}회, seed {decision.seed}, 95% 구간. 델타 = 후보 − 현행",
        "",
        "| 지표 | 현행 | 후보 | 델타 | 95% 구간 | 허용 나빠짐 | 절대 기준 |",
        "|---|---:|---:|---:|---|---:|---|",
    ]
    absolute = {key: f"{op} {threshold:g}" for key, op, threshold in LOCAL_GATE}
    absolute["search_recall@10_drop"] = f"<= {LINKAGE_DROP_LIMIT:g}"
    names = list(dict.fromkeys([*decision.incumbent_overall, *decision.candidate_overall, *decision.deltas]))
    for metric in names:
        delta = decision.deltas.get(metric)
        tolerance = "—" if delta is None or delta.tolerance is None else f"{delta.tolerance:g}"
        delta_text = "—" if delta is None else f"{delta.delta:+.4f}"
        interval = "—" if delta is None else f"[{delta.ci_low:+.4f}, {delta.ci_high:+.4f}]"
        lines.append(
            f"| {metric} | {_cell(decision.incumbent_overall.get(metric))} | "
            f"{_cell(decision.candidate_overall.get(metric))} | {delta_text} | {interval} | {tolerance} | "
            f"{absolute.get(metric, '—')} |"
        )
    lines += ["", "## 자원 개선 (양수 = 후보가 좋음)", ""]
    if decision.resource_gain:
        lines += [f"- {key}: {value:+.1%}" for key, value in sorted(decision.resource_gain.items())]
    else:
        lines.append("- 값 없음 (live 벤치 미제공)")
    lines += ["", "## 미충족 사유", ""]
    lines += [f"- {reason}" for reason in decision.reasons] or ["- 없음"]
    if decision.warnings:
        lines += ["", "## 경고", ""]
        lines += [f"- {warning}" for warning in decision.warnings]
    return "\n".join(lines) + "\n"

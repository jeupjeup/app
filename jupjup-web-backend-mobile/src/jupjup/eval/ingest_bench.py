"""`jupjup bench analyze` live 지연 벤치 (설계 design_local_analyzer.md 8.5절, Q-LA4).

지연 판단은 recorded가 아니라 live 벤치로만 한다. 벤치는 녹화하지 않는다 (``record=False``). 건당 벽시계 시간을
single과 map_reduce로 나눠 p50/p95를 내고, 예산(single p95 ≤ 60초, map_reduce p95 ≤ 300초)과 비교한다.
"""

from __future__ import annotations

import resource
import sys

from pydantic import BaseModel, ConfigDict

from jupjup.eval.ingest_harness import IngestEvalReport
from jupjup.eval.ingest_metrics import latency_summary
from jupjup.eval.ingest_runtime import CapturingAnalyzer

SINGLE_P95_BUDGET_S = 60.0
MAP_REDUCE_P95_BUDGET_S = 300.0


class LatencyStats(BaseModel):
    model_config = ConfigDict(extra="forbid")

    n: int
    p50_s: float | None
    p95_s: float | None
    budget_p95_s: float
    within_budget: bool | None  # 표본이 없으면 None


class AnalyzeBenchReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile: str
    split: str
    recording_model_id: str
    llama_cpp_python: str | None
    gpu_offload: bool | None
    items: int
    succeeded: int
    single: LatencyStats
    map_reduce: LatencyStats
    output_tokens_per_s: float | None
    peak_rss_mb: float
    note: str = "벽시계 시간(분석기 호출 전체, 재요청 포함). live 출력은 녹화하지 않는다"

    @property
    def within_budget(self) -> bool:
        return all(stats.within_budget is not False for stats in (self.single, self.map_reduce))


def peak_rss_mb() -> float:
    """프로세스 최대 RSS. macOS는 바이트, Linux는 KiB 단위로 돌려준다."""
    value = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return round(value / (1024 * 1024) if sys.platform == "darwin" else value / 1024, 1)


def _stats(values_ms: list[float], budget_s: float) -> LatencyStats:
    if not values_ms:
        return LatencyStats(n=0, p50_s=None, p95_s=None, budget_p95_s=budget_s, within_budget=None)
    p50, p95 = latency_summary(values_ms)
    p95_s = round(p95 / 1000.0, 3)
    return LatencyStats(
        n=len(values_ms),
        p50_s=round(p50 / 1000.0, 3),
        p95_s=p95_s,
        budget_p95_s=budget_s,
        within_budget=p95_s <= budget_s,
    )


def bench_from_run(report: IngestEvalReport, capture: CapturingAnalyzer, *, rss_mb: float) -> AnalyzeBenchReport:
    if report.runtime is None:
        raise ValueError("bench analyze는 로컬 프로필 live 실행 결과에서만 만든다")
    single: list[float] = []
    mapped: list[float] = []
    for content_id, wall in sorted(capture.wall_ms.items()):
        (mapped if capture.modes.get(content_id) == "map_reduce" else single).append(wall)
    analyzed = list(capture.results.values())
    output_tokens = sum(meta.output_tokens for _, meta in analyzed)
    llm_seconds = sum(meta.latency_ms for _, meta in analyzed) / 1000.0
    return AnalyzeBenchReport(
        profile=report.runtime.profile,
        split=report.config.split,
        recording_model_id=report.runtime.recording_model_id,
        llama_cpp_python=report.runtime.llama_cpp_python,
        gpu_offload=report.runtime.gpu_offload,
        items=len(report.items),
        succeeded=sum(item.job_status == "succeeded" for item in report.items),
        single=_stats(single, SINGLE_P95_BUDGET_S),
        map_reduce=_stats(mapped, MAP_REDUCE_P95_BUDGET_S),
        output_tokens_per_s=round(output_tokens / llm_seconds, 2) if llm_seconds > 0 else None,
        peak_rss_mb=rss_mb,
    )

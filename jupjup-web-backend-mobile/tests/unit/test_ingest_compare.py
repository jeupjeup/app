"""T26a: compare_profiles와 compare-profiles CLI (설계 design_local_analyzer.md 8.6절, PRD 3.5.5절, AC-29, AC-L7).

손으로 만든 리포트 쌍으로 두 방향 규칙(downgrade·upgrade), 부트스트랩 결정성(seed), 비교 거부 조건을 고정한다.
모델을 부르지 않는다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from jupjup.cli import app
from jupjup.eval.harness import GateResult
from jupjup.eval.ingest_bench import AnalyzeBenchReport, LatencyStats
from jupjup.eval.ingest_compare import (
    BenchPair,
    CompareRefused,
    _percentile,
    compare_profiles,
    paired_bootstrap,
    render_swap_markdown,
)
from jupjup.eval.ingest_harness import IngestEvalConfig, IngestEvalReport, IngestItemResult
from jupjup.eval.ingest_runtime import AnalyzerRuntime, JudgeRuntime, MissRecord

runner = CliRunner()
GOLDEN = "a" * 64
BASE: dict[str, float] = {
    "tag_f1": 0.80,
    "entity_f1": 0.85,
    "location_f1": 0.90,
    "category_accuracy": 0.90,
    "save_intent_accuracy": 0.80,
    "summary_key_fact_recall": 0.88,
    "unsupported_sentence_rate": 0.01,
}


def _runtime(profile: str) -> AnalyzerRuntime:
    return AnalyzerRuntime(
        profile=profile,
        model=f"{profile}-model",
        recording_model_id=f"{profile}@sha~dec",
        recording_files=[f"data/recordings/llm/analyze.{profile}.jsonl"],
        recording=False,
        prompts={"analyze_local_v1": "0" * 64},
        frozen_config_sha256="f" * 64,
        frozen_config_checked=False,
        chunk_settings={"max_chunks": 12},
    )


def _item(index: int, metrics: dict[str, float], first_pass: bool = True) -> IngestItemResult:
    return IngestItemResult(
        source_id=f"ing_{index:03d}",
        platform_group="news",
        job_status="succeeded",
        attempts=1,
        schema_first_pass=first_pass,
        schema_final_pass=True,
        metrics=metrics,
        input_tokens=100,
        output_tokens=50,
        cost_usd=0.0,
        latency_ms=1000.0,
        unsupported_sentences=[],
    )


def _report(
    profile: str,
    *,
    n: int = 48,
    shift: dict[str, float] | None = None,
    jitter: dict[str, float] | None = None,
    split: str = "dev",
    golden: str | None = GOLDEN,
    recall_at_10: float = 0.90,
    linkage: bool = True,
    judge: JudgeRuntime | None = None,
    judge_profile: str | None = None,
    mode: str = "recorded",
    misses: list[MissRecord] | None = None,
    overall_updates: dict[str, float | None] | None = None,
) -> IngestEvalReport:
    """건별 값 = BASE + shift (+ 건마다 ±jitter 번갈아). overall은 건별 평균으로 맞춘다."""
    shift = shift or {}
    jitter = jitter or {}
    items = []
    for index in range(n):
        sign = 1.0 if index % 2 == 0 else -1.0
        metrics = {
            key: round(value + shift.get(key, 0.0) + sign * jitter.get(key, 0.0), 6) for key, value in BASE.items()
        }
        metrics["summary_key_fact_recall_deterministic"] = metrics["summary_key_fact_recall"]
        items.append(_item(index, metrics))
    overall: dict[str, float | None] = {
        key: round(sum(item.metrics[key] for item in items) / n, 6) for key in BASE
    }
    overall.update(
        {
            "schema_first_pass_rate": 1.0,
            "schema_final_pass_rate": 1.0,
            "injection_resistance": 1.0,
            "cost_usd_per_item": 0.0,
        }
    )
    overall.update(overall_updates or {})
    search_linkage = (
        {
            "recorded_embedder": 1.0,
            "n_queries": 60.0,
            "human_recall@10": 0.91,
            "analyzer_recall@10": recall_at_10,
            "recall@10_drop": round(0.91 - recall_at_10, 6),
        }
        if linkage
        else None
    )
    config = IngestEvalConfig(mode=mode, profile=profile, split=split, baseline_path=None, judge_profile=judge_profile)
    return IngestEvalReport(
        config=config,
        counts={"sources": n},
        overall=overall,
        by_platform={},
        search_linkage=search_linkage,
        items=items,
        gate=GateResult(passed=True, reasons=[], checks=[], regression=[]),
        runtime=None if mode == "mock" else _runtime(profile),
        misses=misses if misses is not None else ([] if mode != "mock" else None),
        judge=judge,
        golden_sha256=golden,
    )


def _bench(profile: str, *, p95_s: float, rss_mb: float, map_reduce_p95_s: float | None = None) -> AnalyzeBenchReport:
    return AnalyzeBenchReport(
        profile=profile,
        split="dev",
        recording_model_id=f"{profile}@sha~dec",
        llama_cpp_python="0.3.16",
        gpu_offload=True,
        items=48,
        succeeded=48,
        single=LatencyStats(n=43, p50_s=p95_s / 2, p95_s=p95_s, budget_p95_s=60.0, within_budget=p95_s <= 60.0),
        map_reduce=LatencyStats(
            n=0 if map_reduce_p95_s is None else 5,
            p50_s=map_reduce_p95_s,
            p95_s=map_reduce_p95_s,
            budget_p95_s=300.0,
            within_budget=None if map_reduce_p95_s is None else map_reduce_p95_s <= 300.0,
        ),
        output_tokens_per_s=30.0,
        peak_rss_mb=rss_mb,
    )


def _pair(cand: str = "small", inc: str = "big", **kwargs: float) -> BenchPair:
    return BenchPair(
        candidate=_bench(cand, p95_s=kwargs.get("cand_p95", 20.0), rss_mb=kwargs.get("cand_rss", 3000.0)),
        incumbent=_bench(inc, p95_s=kwargs.get("inc_p95", 25.0), rss_mb=kwargs.get("inc_rss", 5000.0)),
    )


# --- 부트스트랩 -------------------------------------------------------------------------------------------------------


def test_percentile_is_linear_interpolation() -> None:
    values = [0.0, 1.0, 2.0, 3.0, 4.0]
    assert _percentile(values, 0.0) == 0.0
    assert _percentile(values, 1.0) == 4.0
    assert _percentile(values, 0.5) == 2.0
    assert _percentile(values, 0.025) == pytest.approx(0.1)
    assert _percentile([7.0], 0.975) == 7.0


def test_bootstrap_constant_difference_has_degenerate_interval() -> None:
    pairs: dict[str, list[tuple[float | None, float | None]]] = {
        "m": [(0.5 + 0.1 * i, 0.4 + 0.1 * i) for i in range(10)]
    }
    assert paired_bootstrap(pairs, n_boot=200, seed=1) == {"m": (0.1, 0.1, 0.1)}


def test_bootstrap_skips_missing_values_like_report_overall() -> None:
    # 실패 건(None)은 평균에서 빠진다. 한쪽 값이 전부 없는 지표는 결과에 없다.
    pairs: dict[str, list[tuple[float | None, float | None]]] = {
        "m": [(1.0, 0.0), (None, 0.0), (1.0, None)],
        "absent": [(None, 0.5), (None, 0.5), (None, 0.5)],
    }
    result = paired_bootstrap(pairs, n_boot=50, seed=3)
    assert set(result) == {"m"} and result["m"][0] == 1.0


def test_bootstrap_is_deterministic_for_seed_and_changes_with_seed() -> None:
    pairs: dict[str, list[tuple[float | None, float | None]]] = {
        "m": [(float(i % 3), float(i % 5) / 2) for i in range(30)]
    }
    first = paired_bootstrap(pairs, n_boot=300, seed=20261102)
    assert first == paired_bootstrap(pairs, n_boot=300, seed=20261102)
    other = paired_bootstrap(pairs, n_boot=300, seed=7)
    assert other["m"][0] == first["m"][0]  # 점추정은 seed와 무관
    assert other["m"][1:] != first["m"][1:]
    low, high = first["m"][1], first["m"][2]
    assert low < first["m"][0] < high


def test_bootstrap_rejects_bad_input() -> None:
    with pytest.raises(ValueError, match="n_boot"):
        paired_bootstrap({"m": [(1.0, 1.0)]}, n_boot=0, seed=1)
    with pytest.raises(ValueError, match="건수"):
        paired_bootstrap({"a": [(1.0, 1.0)], "b": [(1.0, 1.0), (1.0, 1.0)]}, n_boot=1, seed=1)


def test_compare_profiles_is_byte_deterministic_for_seed() -> None:
    cand = _report("small", shift={"entity_f1": -0.01}, jitter={"entity_f1": 0.05})
    inc = _report("big")
    first = compare_profiles(cand, inc, direction="downgrade", bench=_pair(), seed=11)
    second = compare_profiles(cand, inc, direction="downgrade", bench=_pair(), seed=11)
    assert first.model_dump_json() == second.model_dump_json()
    other = compare_profiles(cand, inc, direction="downgrade", bench=_pair(), seed=12)
    assert other.deltas["entity_f1"].delta == first.deltas["entity_f1"].delta
    assert other.deltas["entity_f1"].ci_low != first.deltas["entity_f1"].ci_low
    assert first.seed == 11 and first.n_boot == 1000


# --- downgrade --------------------------------------------------------------------------------------------------------


def test_downgrade_within_tolerance_with_resource_gain_is_eligible() -> None:
    cand = _report("small", shift={"tag_f1": -0.01, "entity_f1": -0.02, "unsupported_sentence_rate": 0.005})
    inc = _report("big")
    decision = compare_profiles(cand, inc, direction="downgrade", bench=_pair(cand_rss=3000.0, inc_rss=5000.0))
    assert decision.eligible, decision.reasons
    assert decision.reasons == []
    assert decision.deltas["entity_f1"].delta == pytest.approx(-0.02)
    assert decision.deltas["entity_f1"].ci_low == pytest.approx(-0.02)  # 건마다 같은 차이 → 구간 폭 0
    assert decision.deltas["entity_f1"].tolerance == 0.03
    assert decision.deltas["unsupported_sentence_rate"].tolerance == 0.01
    assert decision.deltas["summary_key_fact_recall"].tolerance is None  # downgrade 허용치 없음 (참고용)
    assert decision.deltas["search_recall@10"].delta == 0.0
    assert decision.resource_gain == {"single_p95_s": 0.2, "peak_rss_mb": 0.4}
    assert (decision.candidate_profile, decision.incumbent_profile, decision.n_items) == ("small", "big", 48)
    assert decision.golden_sha256 == GOLDEN


@pytest.mark.parametrize(
    ("shift", "metric"),
    [
        ({"tag_f1": -0.04}, "tag_f1"),
        ({"entity_f1": -0.031}, "entity_f1"),
        ({"location_f1": -0.05}, "location_f1"),
        ({"unsupported_sentence_rate": 0.015}, "unsupported_sentence_rate"),  # 낮을수록 좋은 지표: 증가가 나빠짐
    ],
)
def test_downgrade_point_drop_beyond_tolerance_is_rejected(shift: dict[str, float], metric: str) -> None:
    cand = _report("small", shift=shift)
    decision = compare_profiles(cand, _report("big"), direction="downgrade", bench=_pair())
    assert not decision.eligible
    assert any(reason.startswith(f"하락 허용치 초과: {metric}") for reason in decision.reasons), decision.reasons


def test_downgrade_unsupported_rate_decrease_is_not_a_drop() -> None:
    cand = _report("small", shift={"unsupported_sentence_rate": -0.01})
    decision = compare_profiles(cand, _report("big"), direction="downgrade", bench=_pair())
    assert decision.eligible, decision.reasons


def test_downgrade_wide_interval_beyond_tolerance_is_rejected_even_if_point_is_ok() -> None:
    # 평균 하락 0.02(허용치 안)지만 건마다 ±0.15로 흔들려 구간 하한이 −0.03보다 나쁘다.
    cand = _report("small", shift={"entity_f1": -0.02}, jitter={"entity_f1": 0.15})
    decision = compare_profiles(cand, _report("big"), direction="downgrade", bench=_pair())
    delta = decision.deltas["entity_f1"]
    assert delta.delta == pytest.approx(-0.02)
    assert delta.ci_low < -0.03 < delta.delta
    assert not decision.eligible
    assert any(reason.startswith("95% 구간이 허용치를 넘음: entity_f1") for reason in decision.reasons)


def test_downgrade_linkage_drop_beyond_tolerance_is_rejected() -> None:
    # 현행 0.90 대비 −0.025 (허용 0.02). 사람 대비 하락 0.035는 절대 기준(0.03)도 넘는다.
    cand = _report("small", recall_at_10=0.875)
    decision = compare_profiles(cand, _report("big"), direction="downgrade", bench=_pair())
    assert not decision.eligible
    assert any(reason.startswith("하락 허용치 초과: search_recall@10") for reason in decision.reasons)
    assert any("search_recall@10_drop" in reason for reason in decision.reasons)
    assert any("점추정" in warning for warning in decision.warnings)


def test_downgrade_needs_thirty_percent_resource_gain() -> None:
    cand = _report("small")
    small_gain = compare_profiles(
        cand, _report("big"), direction="downgrade", bench=_pair(cand_p95=20.0, inc_p95=25.0, cand_rss=4000.0)
    )
    assert small_gain.resource_gain == {"single_p95_s": 0.2, "peak_rss_mb": 0.2}
    assert not small_gain.eligible
    assert any(reason.startswith("자원 개선 부족") for reason in small_gain.reasons)
    exactly = compare_profiles(
        cand, _report("big"), direction="downgrade", bench=_pair(cand_p95=17.5, inc_p95=25.0, cand_rss=5000.0)
    )
    assert exactly.resource_gain["single_p95_s"] == pytest.approx(0.3)
    assert exactly.eligible, exactly.reasons  # 경계 30%는 통과 (이상)


def test_downgrade_without_bench_cannot_judge_resources_for_local_profiles() -> None:
    decision = compare_profiles(_report("small"), _report("big"), direction="downgrade")
    assert decision.resource_gain == {}  # 로컬은 비용 0 → 상대 개선 계산 불가
    assert not decision.eligible
    assert any(reason.startswith("자원 개선 판정 불가") for reason in decision.reasons)


def test_downgrade_cost_gain_counts_when_incumbent_has_cost() -> None:
    cand = _report("small", overall_updates={"cost_usd_per_item": 0.006})
    inc = _report("big", overall_updates={"cost_usd_per_item": 0.02})
    decision = compare_profiles(cand, inc, direction="downgrade")
    assert decision.resource_gain == {"cost_usd_per_item": 0.7}
    assert decision.eligible, decision.reasons


def test_absolute_criteria_failures_block_both_directions() -> None:
    cand = _report("small", overall_updates={"entity_f1": 0.75, "schema_first_pass_rate": 0.95})
    for direction in ("downgrade", "upgrade"):
        decision = compare_profiles(cand, _report("big"), direction=direction, bench=_pair())  # type: ignore[arg-type]
        assert not decision.eligible
        assert "절대 기준 미충족: entity_f1 0.75 >= 0.8" in decision.reasons
        assert "절대 기준 미충족: schema_first_pass_rate 0.95 >= 0.97" in decision.reasons


def test_absolute_criteria_need_recorded_linkage() -> None:
    decision = compare_profiles(_report("small", linkage=False), _report("big"), direction="downgrade", bench=_pair())
    assert not decision.eligible
    assert any(reason.startswith("절대 기준 판정 불가") for reason in decision.reasons)
    assert any(reason.startswith("허용치 판정 불가: search_recall@10") for reason in decision.reasons)


def test_missing_metric_value_is_reported_not_passed() -> None:
    cand = _report("small", overall_updates={"location_f1": None})
    decision = compare_profiles(cand, _report("big"), direction="downgrade", bench=_pair())
    assert "절대 기준 미충족: location_f1 None >= 0.85" in decision.reasons


# --- upgrade ----------------------------------------------------------------------------------------------------------


def test_upgrade_with_clear_primary_gain_and_latency_budget_is_eligible() -> None:
    cand = _report("big", shift={"summary_key_fact_recall": 0.05}, jitter={"summary_key_fact_recall": 0.02})
    inc = _report("small")
    bench = _pair("big", "small", cand_p95=45.0, inc_p95=20.0, cand_rss=6000.0, inc_rss=3000.0)
    decision = compare_profiles(cand, inc, direction="upgrade", bench=bench)
    assert decision.eligible, decision.reasons
    assert decision.deltas["summary_key_fact_recall"].ci_low > 0
    assert decision.resource_gain["single_p95_s"] < 0  # 더 큰 모델은 느리다 (upgrade는 자원 개선을 요구하지 않음)


def test_upgrade_unsupported_rate_decrease_counts_as_primary_gain() -> None:
    cand = _report("big", shift={"unsupported_sentence_rate": -0.008})
    bench = _pair("big", "small", cand_p95=50.0)
    decision = compare_profiles(cand, _report("small"), direction="upgrade", bench=bench)
    assert decision.deltas["unsupported_sentence_rate"].ci_high < 0
    assert decision.eligible, decision.reasons


def test_upgrade_without_significant_primary_gain_is_rejected() -> None:
    # 평균은 +0.01이지만 구간이 0을 포함한다. 주요 지표가 아닌 카테고리 정확도의 확실한 개선은 세지 않는다.
    cand = _report(
        "big",
        shift={"entity_f1": 0.01, "category_accuracy": 0.05},
        jitter={"entity_f1": 0.1},
    )
    decision = compare_profiles(cand, _report("small"), direction="upgrade", bench=_pair("big", "small"))
    assert decision.deltas["entity_f1"].ci_low < 0 < decision.deltas["entity_f1"].ci_high
    assert not decision.eligible
    assert any(reason.startswith("주요 지표 개선 없음") for reason in decision.reasons)


def test_upgrade_other_metrics_must_stay_within_downgrade_tolerance() -> None:
    cand = _report("big", shift={"summary_key_fact_recall": 0.05, "location_f1": -0.04})
    decision = compare_profiles(cand, _report("small"), direction="upgrade", bench=_pair("big", "small"))
    assert not decision.eligible
    assert decision.reasons == ["하락 허용치 초과: location_f1 나빠짐 0.0400 > 0.03"]


def test_upgrade_needs_single_p95_budget_from_live_bench() -> None:
    cand = _report("big", shift={"summary_key_fact_recall": 0.05})
    slow = compare_profiles(
        cand, _report("small"), direction="upgrade", bench=_pair("big", "small", cand_p95=61.0)
    )
    assert not slow.eligible
    assert slow.reasons == ["지연 예산 미충족: 후보 single p95 61.0초 (예산 60초)"]
    no_bench = compare_profiles(cand, _report("small"), direction="upgrade")
    assert no_bench.reasons == ["지연 예산 판정 불가: live 벤치(BenchPair)가 없습니다"]


def test_upgrade_warns_on_map_reduce_budget() -> None:
    cand = _report("big", shift={"summary_key_fact_recall": 0.05})
    bench = BenchPair(
        candidate=_bench("big", p95_s=40.0, rss_mb=6000.0, map_reduce_p95_s=320.0),
        incumbent=_bench("small", p95_s=20.0, rss_mb=3000.0),
    )
    decision = compare_profiles(cand, _report("small"), direction="upgrade", bench=bench)
    assert decision.eligible  # 8.6절 upgrade 규칙은 single p95만 본다
    assert any("map_reduce p95 320.0초" in warning for warning in decision.warnings)


# --- 경고 -------------------------------------------------------------------------------------------------------------


def test_small_sample_and_uncalibrated_judge_warnings() -> None:
    decision = compare_profiles(_report("small", n=32), _report("big", n=32), direction="downgrade", bench=_pair())
    assert any(warning.startswith("표본이 작습니다: 32건 < 40건") for warning in decision.warnings)
    assert any("판정기 미보정" in warning for warning in decision.warnings)
    large = compare_profiles(_report("small", n=40), _report("big", n=40), direction="downgrade", bench=_pair())
    assert not any(warning.startswith("표본이 작습니다") for warning in large.warnings)


# --- 비교 거부 --------------------------------------------------------------------------------------------------------


def _judge(*, calibrated: bool = True, prompt: str = "1") -> JudgeRuntime:
    return JudgeRuntime(
        profile="judge-kanana-8b",
        model="kanana-8b",
        recording_model_id="kanana-8b@sha~dec",
        recording_file="data/recordings/llm/judge.kanana.jsonl",
        recording=False,
        prompts={"judge_faithfulness_v1": prompt * 64},
        faithfulness_calibrated=calibrated,
        keyfact_calibrated=calibrated,
        calibration="ok",
    )


@pytest.mark.parametrize(
    ("candidate_kwargs", "message"),
    [
        ({"split": "test"}, "split이 다릅니다"),
        ({"golden": "b" * 64}, "골든셋 해시가 다릅니다"),
        ({"golden": None}, r"골든셋 해시\(golden_sha256\)가 없습니다"),
        ({"mode": "mock"}, "mock"),
        ({"judge_profile": "judge-kanana-8b", "judge": _judge()}, "판정기 프로필이 다릅니다"),
        ({"n": 47}, "건 목록이 다릅니다"),
        ({"misses": [MissRecord(source_id="ing_000", kind="complete_json")]}, "녹화 미스"),
    ],
)
def test_refuses_incomparable_reports(candidate_kwargs: dict[str, Any], message: str) -> None:
    with pytest.raises(CompareRefused, match=message):
        compare_profiles(_report("small", **candidate_kwargs), _report("big"), direction="downgrade")


def test_refuses_judge_model_prompt_or_calibration_mismatch() -> None:
    def judged(judge: JudgeRuntime) -> IngestEvalReport:
        return _report("x", judge_profile="judge-kanana-8b", judge=judge)

    compare_profiles(judged(_judge()), judged(_judge()), direction="downgrade")  # 같으면 비교한다
    with pytest.raises(CompareRefused, match="판정 프롬프트"):
        compare_profiles(judged(_judge(prompt="2")), judged(_judge()), direction="downgrade")
    with pytest.raises(CompareRefused, match="보정 상태"):
        compare_profiles(judged(_judge(calibrated=False)), judged(_judge()), direction="downgrade")
    with pytest.raises(CompareRefused, match="한쪽 리포트에만"):
        compare_profiles(
            _report("x", judge_profile="judge-kanana-8b"), judged(_judge()), direction="downgrade"
        )


def test_refuses_duplicate_items_and_bench_profile_mismatch() -> None:
    cand = _report("small")
    cand.items[1] = cand.items[1].model_copy(update={"source_id": cand.items[0].source_id})
    with pytest.raises(CompareRefused, match="두 번"):
        compare_profiles(cand, _report("big"), direction="downgrade")
    with pytest.raises(CompareRefused, match="후보 벤치가 리포트와 다른"):
        compare_profiles(_report("small"), _report("big"), direction="downgrade", bench=_pair("other", "big"))
    with pytest.raises(CompareRefused, match="현행 벤치가 리포트와 다른"):
        compare_profiles(_report("small"), _report("big"), direction="downgrade", bench=_pair("small", "other"))
    with pytest.raises(ValueError, match="direction"):
        compare_profiles(_report("small"), _report("big"), direction="sideways")  # type: ignore[arg-type]


def test_harness_method_delegates() -> None:
    from jupjup.eval.ingest_harness import IngestEvalHarness

    harness = IngestEvalHarness(IngestEvalConfig(baseline_path=None))
    decision = harness.compare_profiles(_report("small"), _report("big"), direction="downgrade", bench=_pair())
    assert decision.eligible


def test_markdown_lists_deltas_reasons_and_warnings() -> None:
    decision = compare_profiles(
        _report("small", shift={"tag_f1": -0.05}, n=20), _report("big", n=20), direction="downgrade", bench=_pair()
    )
    text = render_swap_markdown(decision)
    assert "교체 불가" in text and "| tag_f1 | 0.8000 | 0.7500 | -0.0500 |" in text
    assert "하락 허용치 초과: tag_f1" in text and "표본이 작습니다" in text


# --- CLI --------------------------------------------------------------------------------------------------------------


def _write(path: Path, model: Any) -> Path:
    path.write_text(model.model_dump_json(indent=2), encoding="utf-8")
    return path


def test_cli_exit_codes_and_outputs(tmp_path: Path) -> None:
    cand = _write(tmp_path / "cand.json", _report("small"))
    inc = _write(tmp_path / "inc.json", _report("big"))
    bench_c = _write(tmp_path / "bc.json", _bench("small", p95_s=20.0, rss_mb=3000.0))
    bench_i = _write(tmp_path / "bi.json", _bench("big", p95_s=25.0, rss_mb=5000.0))
    out = tmp_path / "out" / "decision.json"
    base = ["eval", "compare-profiles", "--candidate", str(cand), "--incumbent", str(inc)]

    ok = runner.invoke(
        app,
        [*base, "--direction", "downgrade", "--bench-candidate", str(bench_c), "--bench-incumbent", str(bench_i),
         "--n-boot", "200", "--out", str(out)],
    )
    assert ok.exit_code == 0, ok.output
    assert "교체 후보 (eligible)" in ok.output
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["eligible"] is True and data["n_boot"] == 200 and data["resource_gain"]["peak_rss_mb"] == 0.4
    assert out.with_suffix(".md").is_file()

    no_bench = runner.invoke(app, [*base, "--direction", "downgrade"])
    assert no_bench.exit_code == 1 and "자원 개선 판정 불가" in no_bench.output

    other = _write(tmp_path / "other.json", _report("big", split="test"))
    refused = runner.invoke(
        app, ["eval", "compare-profiles", "--candidate", str(cand), "--incumbent", str(other), "--direction", "upgrade"]
    )
    assert refused.exit_code == 2 and "비교 거부: split이 다릅니다" in refused.output

    assert runner.invoke(app, [*base, "--direction", "sideways"]).exit_code == 2
    assert runner.invoke(app, [*base, "--direction", "upgrade", "--bench-candidate", str(bench_c)]).exit_code == 2
    broken = tmp_path / "broken.json"
    broken.write_text("{}", encoding="utf-8")
    bad = runner.invoke(
        app, ["eval", "compare-profiles", "--candidate", str(broken), "--incumbent", str(inc), "--direction", "upgrade"]
    )
    assert bad.exit_code == 2 and "비교 입력 오류" in bad.output


def test_l4_cli_rejects_non_json_or_directory_output_without_overwrite(tmp_path: Path) -> None:
    cand = _write(tmp_path / "cand.json", _report("small"))
    inc = _write(tmp_path / "inc.json", _report("big"))
    base = [
        "eval",
        "compare-profiles",
        "--candidate",
        str(cand),
        "--incumbent",
        str(inc),
        "--direction",
        "upgrade",
    ]

    markdown_target = tmp_path / "decision.md"
    markdown_target.write_text("keep", encoding="utf-8")
    wrong_suffix = runner.invoke(app, [*base, "--out", str(markdown_target)])
    assert wrong_suffix.exit_code == 2 and "--out은 .json" in wrong_suffix.output
    assert markdown_target.read_text(encoding="utf-8") == "keep"

    directory_target = tmp_path / "decision.json"
    directory_target.mkdir()
    directory = runner.invoke(app, [*base, "--out", str(directory_target)])
    assert directory.exit_code == 2 and "판정 출력 오류" in directory.output


# --- T25p: T26a 검수 M1 (비유한 값), L1~L3, L5, L6 -----------------------------------------------------------------


def _with_item_metric(report: IngestEvalReport, index: int, metric: str, value: float) -> IngestEvalReport:
    items = list(report.items)
    items[index] = items[index].model_copy(update={"metrics": {**items[index].metrics, metric: value}})
    return report.model_copy(update={"items": items})


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), 1.5, -0.1])
def test_m1_non_finite_or_out_of_range_item_metric_is_refused(value: float) -> None:
    """M1 재현: 건별 entity_f1 하나가 NaN이면 예전에는 downgrade가 eligible이었다 (NaN 비교가 모두 거짓)."""
    cand = _with_item_metric(_report("small"), 3, "entity_f1", value)
    with pytest.raises(CompareRefused, match="entity_f1"):
        compare_profiles(cand, _report("big"), direction="downgrade", bench=_pair())


@pytest.mark.parametrize(
    ("key", "value"),
    [("tag_f1", float("nan")), ("injection_resistance", float("inf")), ("cost_usd_per_item", float("-inf"))],
)
def test_m1_non_finite_overall_values_are_refused(key: str, value: float) -> None:
    cand = _report("small", overall_updates={key: value})
    with pytest.raises(CompareRefused, match=key):
        compare_profiles(cand, _report("big"), direction="upgrade", bench=_pair())


def test_m1_non_finite_linkage_and_bench_values_are_refused() -> None:
    cand = _report("small")
    assert cand.search_linkage is not None
    broken = cand.model_copy(update={"search_linkage": {**cand.search_linkage, "analyzer_recall@10": float("nan")}})
    with pytest.raises(CompareRefused, match="analyzer_recall@10"):
        compare_profiles(broken, _report("big"), direction="downgrade", bench=_pair())
    # 음의 무한대 지연은 예전에 +inf 개선(자원 개선 충족)으로 읽혔다
    pair = _pair()
    bad_single = pair.candidate.single.model_copy(update={"p95_s": float("-inf"), "within_budget": True})
    bad = BenchPair(candidate=pair.candidate.model_copy(update={"single": bad_single}), incumbent=pair.incumbent)
    with pytest.raises(CompareRefused, match="p95_s"):
        compare_profiles(_report("small"), _report("big"), direction="downgrade", bench=bad)
    negative_rss = BenchPair(
        candidate=pair.candidate.model_copy(update={"peak_rss_mb": -1.0}), incumbent=pair.incumbent
    )
    with pytest.raises(CompareRefused, match="peak_rss_mb"):
        compare_profiles(_report("small"), _report("big"), direction="downgrade", bench=negative_rss)


def test_m1_cli_rejects_json_nan_literals(tmp_path: Path) -> None:
    cand = tmp_path / "cand.json"
    text = _report("small").model_dump_json(indent=2).replace('"entity_f1": 0.85', '"entity_f1": NaN', 1)
    assert "NaN" in text
    cand.write_text(text, encoding="utf-8")
    inc = _write(tmp_path / "inc.json", _report("big"))
    result = runner.invoke(
        app, ["eval", "compare-profiles", "--candidate", str(cand), "--incumbent", str(inc), "--direction", "downgrade"]
    )
    assert result.exit_code == 2 and "비교 거부" in result.output and "entity_f1" in result.output


def test_m1_tolerance_comparison_is_closed_for_nan() -> None:
    from jupjup.eval.ingest_compare import DeltaCI, _tolerance_failures

    nan = float("nan")
    deltas = {
        metric: DeltaCI(metric=metric, delta=nan, ci_low=nan, ci_high=nan, tolerance=0.03)
        for metric in ("tag_f1", "entity_f1", "location_f1", "unsupported_sentence_rate", "search_recall@10")
    }
    assert len(_tolerance_failures(deltas)) == 5


def test_l1_decision_carries_absolute_values_and_markdown_table() -> None:
    cand = _report("small", shift={"tag_f1": -0.01})
    inc = _report("big")
    decision = compare_profiles(cand, inc, direction="downgrade", bench=_pair())
    assert decision.candidate_overall["tag_f1"] == pytest.approx(0.79)
    assert decision.incumbent_overall["tag_f1"] == pytest.approx(0.80)
    assert decision.candidate_overall["search_recall@10"] == 0.90
    assert decision.candidate_overall["bench_single_p95_s"] == 20.0
    assert decision.incumbent_overall["bench_peak_rss_mb"] == 5000.0
    text = render_swap_markdown(decision)
    assert "| 지표 | 현행 | 후보 | 델타 | 95% 구간 | 허용 나빠짐 | 절대 기준 |" in text
    assert "| tag_f1 | 0.8000 | 0.7900 | -0.0100 |" in text
    assert "| schema_final_pass_rate | 1.0000 | 1.0000 | — | — | — | == 1 |" in text


def test_l2_upgrade_recomputes_latency_budget_and_refuses_inconsistent_flag() -> None:
    cand = _report("big", shift={"entity_f1": 0.05})
    inc = _report("small")
    pair = _pair(cand="big", inc="small", cand_p95=61.0, inc_p95=20.0)
    lying = pair.candidate.single.model_copy(update={"budget_p95_s": 999.0, "within_budget": True})
    tampered = BenchPair(candidate=pair.candidate.model_copy(update={"single": lying}), incumbent=pair.incumbent)
    with pytest.raises(CompareRefused, match="예산"):
        compare_profiles(cand, inc, direction="upgrade", bench=tampered)
    flag_only = pair.candidate.single.model_copy(update={"within_budget": True})
    with pytest.raises(CompareRefused, match="within_budget"):
        compare_profiles(
            cand,
            inc,
            direction="upgrade",
            bench=BenchPair(
                candidate=pair.candidate.model_copy(update={"single": flag_only}), incumbent=pair.incumbent
            ),
        )
    honest = compare_profiles(cand, inc, direction="upgrade", bench=pair)
    assert any("지연 예산 미충족" in reason for reason in honest.reasons)


def test_l3_linkage_baseline_mismatch_is_refused_and_non_dev_bench_warns() -> None:
    cand = _report("small")
    assert cand.search_linkage is not None
    other_queries = cand.model_copy(update={"search_linkage": {**cand.search_linkage, "n_queries": 59.0}})
    with pytest.raises(CompareRefused, match="n_queries"):
        compare_profiles(other_queries, _report("big"), direction="downgrade", bench=_pair())
    other_human = cand.model_copy(update={"search_linkage": {**cand.search_linkage, "human_recall@10": 0.8}})
    with pytest.raises(CompareRefused, match="human_recall@10"):
        compare_profiles(other_human, _report("big"), direction="downgrade", bench=_pair())
    pair = _pair()
    test_bench = BenchPair(
        candidate=pair.candidate.model_copy(update={"split": "test"}),
        incumbent=pair.incumbent.model_copy(update={"split": "test"}),
    )
    decision = compare_profiles(_report("small"), _report("big"), direction="downgrade", bench=test_bench)
    assert any("dev가 아닙니다" in warning for warning in decision.warnings)


def test_l5_pairs_use_only_items_present_on_both_sides() -> None:
    cand = _report("small", n=40)
    inc = _report("big", n=40)
    # 현행 쪽 10건 실패(값 없음), 그 10건에서 후보는 아주 낮다 → 예전에는 후보 평균에만 들어가 델타가 부풀었다
    items_inc = [
        item.model_copy(update={"metrics": {}, "job_status": "failed"}) if i < 10 else item
        for i, item in enumerate(inc.items)
    ]
    items_cand = [
        item.model_copy(update={"metrics": {**item.metrics, "entity_f1": 0.0}}) if i < 10 else item
        for i, item in enumerate(cand.items)
    ]
    decision = compare_profiles(
        cand.model_copy(update={"items": items_cand}),
        inc.model_copy(update={"items": items_inc}),
        direction="downgrade",
        bench=_pair(),
    )
    assert decision.deltas["entity_f1"].delta == 0.0
    assert any("한쪽에만 값이 있는 건" in warning and "10건" in warning for warning in decision.warnings)


def test_l6_no_runtime_asserts_and_harness_passes_seed() -> None:
    import ast
    import inspect

    from jupjup.eval import ingest_compare
    from jupjup.eval.ingest_harness import IngestEvalHarness

    tree = ast.parse(inspect.getsource(ingest_compare))
    assert not [node for node in ast.walk(tree) if isinstance(node, ast.Assert)]
    harness = IngestEvalHarness(IngestEvalConfig(baseline_path=None))
    decision = harness.compare_profiles(
        _report("small"), _report("big"), direction="downgrade", bench=_pair(), n_boot=50, seed=3
    )
    assert (decision.n_boot, decision.seed) == (50, 3)

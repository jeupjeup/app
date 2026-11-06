"""T13~T14: 평가 하네스 결정성, 안전 지표, 기준선과 mock 절대 게이트."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jupjup.eval.harness import (
    BaselineFile,
    EvalConfig,
    EvalHarness,
    EvalReport,
    GateResult,
    HumanReviewMetadata,
    MetricObservation,
    baseline_metrics,
    update_baseline,
)
from jupjup.eval.report import render_markdown, write_report
from tests.conftest import ROOT

BASELINE = ROOT / "data" / "baselines" / "mock.json"
pytestmark = pytest.mark.eval


@pytest.fixture(scope="module")
def report_all() -> EvalReport:
    return EvalHarness(EvalConfig(mode="mock", split="all", baseline_path=BASELINE)).run()


def test_safety_zero(report_all: EvalReport) -> None:
    assert report_all.safety == {"isolation_violations": 0, "filter_violations": 0}


def test_no_regression_vs_baseline(report_all: EvalReport) -> None:
    assert BASELINE.exists(), "data/baselines/mock.json이 커밋되어 있어야 합니다"
    assert report_all.gate.regression, "기준선 비교가 실행되지 않았습니다"
    failed = [c for c in report_all.gate.regression if not c.passed]
    assert not failed, failed


def test_understanding_criteria(report_all: EvalReport) -> None:
    u = report_all.understanding
    assert u["time_exact"] >= 0.95
    assert u["platform_f1"] >= 0.97
    assert u["content_type_f1"] >= 0.95
    assert u["keyword_inclusion"] >= 0.90


def test_mock_absolute_gate(report_all: EvalReport) -> None:
    assert report_all.gate.passed, report_all.gate.reasons


def test_q0176_stronger_lexical_tail_is_rank_limited_not_discarded(report_all: EvalReport) -> None:
    result = next(result for result in report_all.results if result.query_id == "q_0176")
    assert "c_alice_0052" in result.ranked_ids
    assert result.per_query_metrics["recall@10"] == 1.0


def test_deterministic_twice() -> None:
    cfg = EvalConfig(mode="mock", split="dev")
    a = EvalHarness(cfg).run()
    b = EvalHarness(cfg).run()
    ja = json.dumps(a.deterministic_dict(), ensure_ascii=False, sort_keys=True)
    jb = json.dumps(b.deterministic_dict(), ensure_ascii=False, sort_keys=True)
    assert ja == jb  # 바이트 단위로 같음 (타임스탬프·지연 제외)


def test_report_files(tmp_path: Path, report_all: EvalReport) -> None:
    jp, mp = write_report(report_all, tmp_path)
    data = json.loads(jp.read_text(encoding="utf-8"))
    assert data["config"]["split"] == "all" and "by_category" in data and "failures" in data
    md = mp.read_text(encoding="utf-8")
    assert "## 카테고리별" in md and "## 실패 질의" in md and "review_status별 지표" in md
    assert "filter-only browse 지표" in md and "제품 품질 PASS 근거" in md
    assert render_markdown(report_all).count("| q_") <= 20 + len(report_all.understanding_failures)


def test_review_status_and_browse_metrics_are_separated(report_all: EvalReport) -> None:
    assert report_all.by_review_status["needs_human_review"]["n_queries"] == 24
    assert report_all.by_review_status["human_reviewed"]["n_queries"] == 0
    assert report_all.product_evidence["eligible"] is False
    assert report_all.browse["browse_precision@10"] == 1.0
    assert report_all.browse["browse_sort_accuracy"] == 1.0
    assert report_all.browse["browse_filter_compliance"] == 1.0
    assert report_all.browse["browse_coverage"] < 1.0
    assert report_all.by_category["filter_only"]["n_ranked"] == 0
    for status in ("ai_draft_unreviewed", "needs_human_review", "human_reviewed"):
        assert {"time_exact", "platform_f1", "content_type_f1", "keyword_inclusion"} <= set(
            report_all.by_review_status[status]
        )
        assert status in report_all.review_status_gates
    conditions = report_all.product_evidence["conditions"]
    assert not conditions["minimum_sample"]
    assert not conditions["reviewer_count"]
    assert not conditions["weighted_kappa"]


def test_regression_detected(report_all: EvalReport) -> None:
    h = EvalHarness(report_all.config)
    r10 = report_all.overall["recall@10"]
    worse_than_base = BaselineFile(mode="mock", splits={"all": {"metrics": {"recall@10": r10 + 0.02}}})
    g = h.compare(report_all, worse_than_base)
    assert not g.passed and any("recall@10" in x for x in g.reasons)
    within_tol = BaselineFile(mode="mock", splits={"all": {"metrics": {"recall@10": r10 + 0.005}}})
    assert h.compare(report_all, within_tol).passed
    other_split = BaselineFile(mode="mock", splits={"dev": {"metrics": {"recall@10": 2.0}}})
    assert h.compare(report_all, other_split).passed  # 같은 split 항목이 없으면 비교하지 않는다


def test_update_baseline_refuses_on_regression(tmp_path: Path, report_all: EvalReport) -> None:
    p = tmp_path / "b.json"
    ok, _ = update_baseline(p, report_all)
    assert (
        ok
        and json.loads(p.read_text(encoding="utf-8"))["splits"]["all"]["metrics"]["recall@10"]
        == report_all.overall["recall@10"]
    )
    worse = report_all.model_copy(deep=True)
    worse.overall["recall@10"] -= 0.2
    ok, msg = update_baseline(p, worse)
    assert not ok and "낮아" in msg


def test_update_baseline_refuses_even_small_decrease(tmp_path: Path, report_all: EvalReport) -> None:
    p = tmp_path / "b.json"
    ok, _ = update_baseline(p, report_all)
    assert ok
    slightly_worse = report_all.model_copy(deep=True)
    slightly_worse.overall["recall@10"] -= 0.005
    ok, msg = update_baseline(p, slightly_worse)
    assert not ok and "recall@10" in msg and "낮아" in msg


def test_human_reviewed_baseline_cannot_use_ai_metrics(tmp_path: Path, report_all: EvalReport) -> None:
    path = tmp_path / "human.json"
    path.write_text(
        BaselineFile(mode="mock", review_status="human_reviewed").model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    ok, message = update_baseline(path, report_all)
    assert not ok and "human_reviewed 질의가 없어" in message


def test_baseline_mode_mismatch_rejected_before_compare_or_write(tmp_path: Path, report_all: EvalReport) -> None:
    mismatched = BaselineFile(mode="recorded", splits={})
    comparison = EvalHarness(report_all.config).compare(report_all, mismatched)
    assert not comparison.passed and "mode=recorded" in comparison.reasons[0]

    path = tmp_path / "recorded.json"
    original = mismatched.model_dump_json(indent=2) + "\n"
    path.write_text(original, encoding="utf-8")
    ok, message = update_baseline(path, report_all)
    assert not ok and "mode=recorded" in message
    assert path.read_text(encoding="utf-8") == original


def test_human_baseline_includes_understanding_metrics(report_all: EvalReport) -> None:
    synthetic = report_all.model_copy(deep=True)
    synthetic.by_review_status["human_reviewed"] = {
        **synthetic.by_review_status["ai_draft_unreviewed"],
        "n_queries": 20.0,
    }
    metrics = baseline_metrics(synthetic, "human_reviewed")
    assert {"time_exact", "platform_f1", "content_type_f1", "keyword_inclusion"} <= set(metrics)


def test_product_evidence_requires_sample_reviewers_kappa_and_gates() -> None:
    metrics = {"n_queries": 20.0}
    gate = GateResult(passed=True, checks=[], regression=[])
    metadata = HumanReviewMetadata(reviewer_count=1, reviewed_query_count=20, weighted_kappa=0.69)
    observations = {
        name: MetricObservation(
            value=1.0,
            numerator=minimum,
            denominator=minimum,
            minimum_denominator=minimum,
            eligible=True,
        )
        for name, minimum in {
            "positive_ranked": 10,
            "negative_true_empty": 5,
            "filter_only_browse": 5,
            "time_understanding": 5,
            "platform_understanding": 5,
            "content_type_understanding": 5,
            "keyword_inclusion": 10,
        }.items()
    }
    evidence = EvalHarness._build_product_evidence(
        metrics,
        gate,
        metadata,
        regression_baseline_available=False,
        observations=observations,
        split="test",
        actual_total=20,
        actual_by_split={"test": 20},
    )
    assert evidence["eligible"] is False
    assert evidence["conditions"]["minimum_sample"] is True
    assert evidence["conditions"]["metadata_total_count_matches"] is True
    assert evidence["conditions"]["metadata_split_count_matches"] is False
    assert evidence["conditions"]["reviewer_count"] is False
    assert evidence["conditions"]["weighted_kappa"] is False


def test_inv17_zero_denominator_is_not_evaluated() -> None:
    observation = MetricObservation(
        value=None,
        numerator=0,
        denominator=0,
        minimum_denominator=5,
        eligible=False,
    )
    evidence = EvalHarness._build_product_evidence(
        {"n_queries": 20.0},
        GateResult(passed=True),
        HumanReviewMetadata(
            reviewer_count=2,
            reviewed_query_count_total=20,
            reviewed_query_count_by_split={"dev": 0, "test": 20},
            weighted_kappa_by_split={"dev": None, "test": 0.8},
        ),
        regression_baseline_available=True,
        observations={"negative_true_empty": observation},
        split="test",
        actual_total=20,
        actual_by_split={"test": 20},
    )
    assert evidence["metric_observations"]["negative_true_empty"]["value"] is None
    assert evidence["eligible"] is False


def test_review_status_gate_uses_null_for_missing_denominators(report_all: EvalReport) -> None:
    human = report_all.by_review_status["human_reviewed"]
    assert human["recall@10"] is None
    assert human["true_empty_rate"] is None
    assert human["browse_precision@10"] is None
    gate = report_all.review_status_gates["human_reviewed"]
    assert not gate.passed
    assert next(check for check in gate.checks if check.name == "true_empty_rate").value is None


def test_inv18_total_and_split_metadata_are_independent() -> None:
    metadata = HumanReviewMetadata(
        reviewer_count=2,
        reviewed_query_count_total=20,
        reviewed_query_count_by_split={"dev": 8, "test": 12},
        weighted_kappa_by_split={"dev": 0.8, "test": 0.8},
    )
    evidence = EvalHarness._build_product_evidence(
        {"n_queries": 12.0},
        GateResult(passed=True),
        metadata,
        regression_baseline_available=False,
        split="test",
        actual_total=20,
        actual_by_split={"dev": 8, "test": 12},
    )
    assert evidence["conditions"]["metadata_total_count_matches"] is True
    assert evidence["conditions"]["metadata_split_count_matches"] is True

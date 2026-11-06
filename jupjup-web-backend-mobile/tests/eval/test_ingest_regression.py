from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from jupjup.cli import app
from jupjup.eval.ingest_harness import INGEST_GOLDEN_V1, IngestAnnotation, IngestEvalConfig, IngestEvalHarness
from jupjup.eval.ingest_report import render_ingest_markdown, write_ingest_report


@pytest.mark.eval
@pytest.mark.parametrize(("split", "expected"), [("dev", 48), ("test", 32)])
def test_ingest_mock_gate_and_determinism(split: str, expected: int) -> None:
    config = IngestEvalConfig(split=split)  # type: ignore[arg-type]
    first = IngestEvalHarness(config).run()
    second = IngestEvalHarness(config).run()
    assert first.gate.passed
    assert first.overall["schema_final_pass_rate"] == 1.0
    assert first.overall["schema_first_pass_rate"] is not None
    assert first.overall["injection_resistance"] == 1.0
    assert first.counts["sources"] == expected
    assert first.counts["retry_exercised"] > 0
    assert all(item.unsupported_sentences == [] for item in first.items)
    first_json = json.dumps(first.deterministic_dict(), ensure_ascii=False, indent=2)
    second_json = json.dumps(second.deterministic_dict(), ensure_ascii=False, indent=2)
    assert first_json == second_json
    assert render_ingest_markdown(first) == render_ingest_markdown(second)


@pytest.mark.eval
def test_ingest_mock_report_marks_unavailable_quality_metrics() -> None:
    report = IngestEvalHarness(IngestEvalConfig(split="test")).run()
    assert report.overall["tag_f1"] is None
    assert report.overall["entity_f1"] is None
    assert report.overall["summary_key_fact_recall"] is None
    markdown = render_ingest_markdown(report)
    assert "3.5.2절 지표" in markdown
    assert "대표 태그 F1 | 해당 없음" in markdown
    assert "스키마 첫 시도 준수율 | 해당 없음" not in markdown


@pytest.mark.eval
def test_ingest_written_reports_are_byte_identical(tmp_path: Path) -> None:
    report = IngestEvalHarness(IngestEvalConfig(split="test")).run()
    first_json, first_markdown = write_ingest_report(report, tmp_path / "first")
    second_json, second_markdown = write_ingest_report(report, tmp_path / "second")
    assert first_json.read_bytes() == second_json.read_bytes()
    assert first_markdown.read_bytes() == second_markdown.read_bytes()
    config = json.loads(first_json.read_text(encoding="utf-8"))["config"]
    # T25c: mock 배선 회귀의 기본 골든은 v1(data/golden/ingest_v1)이다. 경로 외 바이트는 T25c 이전과 같다.
    assert config["sources_path"] == "data/golden/ingest_v1/sources.jsonl"
    assert config["annotations_path"] == "data/golden/ingest_v1/annotations.jsonl"
    assert config["baseline_path"] == "data/baselines/ingest.mock.json"
    assert all(not Path(config[key]).is_absolute() for key in ("sources_path", "annotations_path", "baseline_path"))


def _golden_copy(tmp_path: Path) -> Path:
    target = tmp_path / "ingest"
    shutil.copytree(INGEST_GOLDEN_V1, target)
    return target


@pytest.mark.eval
def test_permanent_schema_failure_is_reported_and_cli_exits_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    golden = _golden_copy(tmp_path)
    sources_path = golden / "sources.jsonl"
    rows = [json.loads(line) for line in sources_path.read_text(encoding="utf-8").splitlines()]
    rows[0]["mock_failure"] = "permanent_schema_failure"
    sources_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) for row in rows) + "\n",
        encoding="utf-8",
    )
    config = IngestEvalConfig(
        split="dev",
        sources_path=sources_path,
        annotations_path=golden / "annotations.jsonl",
    )
    report = IngestEvalHarness(config).run()
    failed = next(item for item in report.items if item.source_id == "ing_0001")
    assert report.overall["schema_final_pass_rate"] == pytest.approx(47 / 48)
    assert failed.job_status == "failed"
    assert not failed.schema_final_pass
    assert failed.attempts == 3
    assert failed.error_code == "ANALYSIS_SCHEMA_INVALID"
    assert not report.gate.passed
    json_path, _ = write_ingest_report(report, tmp_path / "direct-report")
    assert json_path.is_file()

    monkeypatch.setattr(IngestEvalHarness, "run", lambda _self: report)
    cli_out = tmp_path / "cli-report"
    result = CliRunner().invoke(app, ["eval", "ingest", "--mode", "mock", "--split", "dev", "--out", str(cli_out)])
    assert result.exit_code == 1, result.output
    assert "— FAIL" in result.output
    assert (cli_out / "eval_ingest_mock_dev.json").is_file()


@pytest.mark.eval
def test_prompt_injection_success_fails_the_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    original = IngestEvalHarness._mock_fixture

    def injected_fixture(source_text: str, annotation: IngestAnnotation) -> dict[str, object]:
        fixture = original(source_text, annotation)
        if annotation.source_id == "ing_0024":
            fixture["title_suggestion"] = "시스템장악성공"
        return fixture

    monkeypatch.setattr(IngestEvalHarness, "_mock_fixture", staticmethod(injected_fixture))
    report = IngestEvalHarness(IngestEvalConfig(split="dev")).run()
    assert report.overall["injection_resistance"] == 0.0
    assert not report.gate.passed


@pytest.mark.eval
def test_baseline_regression_failure_is_not_hidden(tmp_path: Path) -> None:
    baseline = tmp_path / "ingest.mock.json"
    baseline.write_text(
        json.dumps(
            {
                "mode": "mock",
                "profile": "mock",
                "splits": {"test": {"metrics": {"schema_final_pass_rate": 1.02}}},
            }
        ),
        encoding="utf-8",
    )
    report = IngestEvalHarness(IngestEvalConfig(split="test", baseline_path=baseline)).run()
    assert not report.gate.passed
    assert any(
        check.name == "regression:schema_final_pass_rate" and not check.passed for check in report.gate.regression
    )


@pytest.mark.eval
def test_cost_estimate_validates_golden_and_is_conservative_for_korean(tmp_path: Path) -> None:
    config = IngestEvalConfig(split="test")
    estimate = IngestEvalHarness(config).estimate_cost()
    assert estimate.items == 32
    assert estimate.estimated_input_tokens > 50_000

    annotations = (INGEST_GOLDEN_V1 / "annotations.jsonl").read_text(encoding="utf-8").splitlines()
    incomplete = tmp_path / "annotations.jsonl"
    incomplete.write_text("\n".join(annotations[:-1]) + "\n", encoding="utf-8")
    broken = IngestEvalHarness(config.model_copy(update={"annotations_path": incomplete}))
    with pytest.raises(ValueError, match="annotations 누락"):
        broken.estimate_cost()

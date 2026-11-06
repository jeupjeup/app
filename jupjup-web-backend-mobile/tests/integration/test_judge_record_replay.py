"""T25g: 판정기 녹화·재생, 하네스 결합, 보정 CLI, mock 결정적 매처 회귀 (설계 8.3·8.4절, 10.1절 T25g).

- v1·v2 mock all에서 결정적 핵심 사실 매처 = 기존 부분 문자열 결과 (건별)
- live(녹화) → recorded 재생이 같은 리포트, 판정기 녹화 파일에 프롬프트 원문 없음
- judge_failed가 비충실과 따로 세지고, 미보정이면 결정적 값 + "판정기 미보정" 표시, 보정 통과면 결합 규칙
- 판정기 녹화 미스 → 미스 목록, CLI 종료 2
- judge-sample → judge-calibrate (live 녹화 → recorded 재생 같은 κ)

실제 모델은 쓰지 않는다. llama_cpp 없이 기본 설치에서 돈다.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel
from typer.testing import CliRunner

from jupjup.cli import app
from jupjup.domain.errors import LLMProviderError, LLMTimeoutError
from jupjup.eval.ingest_harness import (
    INGEST_GOLDEN,
    INGEST_GOLDEN_V1,
    IngestEvalConfig,
    IngestEvalHarness,
    IngestEvalReport,
    load_ingest_golden,
)
from jupjup.eval.ingest_report import render_ingest_markdown, write_ingest_report
from jupjup.eval.ingest_runtime import DEFAULT_PROFILES_PATH
from jupjup.eval.judge import JudgeVerdicts, KeyFactVerdicts
from jupjup.eval.judge_calibration import JudgeCalibration, dump_label_rows, load_label_rows
from jupjup.eval.judge_tools import judge_calibrate, judge_sample
from jupjup.ingest.profiles import AnalyzerProfiles, DecodingParams, LocalModelSpec, recording_model_id
from jupjup.providers.llm import LLMRawResponse, MockLLM, prompt_hash
from jupjup.text.normalize import normalize_text
from tests.integration.test_ingest_record_replay import GoldenEchoLLM

runner = CliRunner()
PROFILE = "local-kanana-2b"
JUDGE = "judge-kanana-8b"
_NUMBERED = re.compile(r"^\[(\d+)\] (.*)$", re.M)


def _block(user: str, tag: str) -> str:
    match = re.search(rf"<{tag}>\n(.*?)\n</{tag}>", user, re.S)
    return "" if match is None else match.group(1)


class JudgeEchoLLM(MockLLM):
    """가짜 판정 모델. 문장 앞 12자가 원문에 있으면 supported, 아니면 unsupported.

    일부 요청은 첫 시도에 마지막 번호를 빼고(재요청 경로), 일부는 재요청에도 빼서 judge_failed를 만든다.
    """

    def __init__(self, model_id: str) -> None:
        super().__init__()
        self.model_id = model_id

    def complete_json(
        self,
        system: str,
        user: str,
        schema: type[BaseModel],
        timeout_s: float,
        max_tokens: int = 4000,
        effort: str | None = None,
    ) -> LLMRawResponse:
        key = prompt_hash(system, user)
        self.calls.append(key)
        retry = "이전 답에 문제가 있었다" in user
        if schema is JudgeVerdicts:
            source = normalize_text(_block(user, "source_document"))
            rows = _NUMBERED.findall(_block(user, "summary_sentences"))
            items = [
                {
                    "index": int(i),
                    "evidence": "",
                    "verdict": "supported" if normalize_text(text)[:12] in source else "unsupported",
                }
                for i, text in rows
            ]
        else:
            assert schema is KeyFactVerdicts
            summary = normalize_text(_block(user, "summary"))
            rows = _NUMBERED.findall(_block(user, "key_facts"))
            items = [
                {"index": int(i), "evidence": "", "verdict": "covered" if normalize_text(t) in summary else "missing"}
                for i, t in rows
            ]
        # 재요청 경로와 judge_failed 경로를 녹화에 남긴다 (프롬프트 해시로 결정적으로 고른다)
        bucket = int(prompt_hash(system, _block(user, "summary_sentences") + _block(user, "key_facts"))[:2], 16)
        if items and ((bucket % 3 == 0 and not retry) or bucket % 11 == 0):
            items = items[:-1]
        text = json.dumps({"judgments": items}, ensure_ascii=False)
        return LLMRawResponse(text=text, input_tokens=len(user), output_tokens=len(text), latency_ms=3.0)


class Factory:
    def __init__(self) -> None:
        self.models: list[str] = []

    def __call__(self, spec: LocalModelSpec, decoding: DecodingParams) -> MockLLM:
        self.models.append(spec.model_id)
        model_id = recording_model_id(spec, decoding)
        if spec.model_id == "kanana-1.5-8b-instruct-q4km":
            return JudgeEchoLLM(model_id)
        return GoldenEchoLLM(model_id)


def _judge_model_id() -> str:
    profiles = AnalyzerProfiles.load(DEFAULT_PROFILES_PATH)
    judge = profiles.judges[JUDGE]
    return recording_model_id(profiles.models[judge.model], judge.decoding)


def _stem(model_id: str) -> str:
    return model_id.replace("@", "_at_").replace("~", "_dec_")


def _config(root: Path, **updates: Any) -> IngestEvalConfig:
    values: dict[str, Any] = {
        "mode": "recorded",
        "profile": PROFILE,
        "split": "dev",
        "baseline_path": None,
        "recordings_dir": root / "llm",
        "judge_profile": JUDGE,
        "judge_calibration_path": root / "missing_calibration.json",
    }
    values.update(updates)
    return IngestEvalConfig(**values)


def _comparable(report: IngestEvalReport) -> str:
    data = report.deterministic_dict()
    data["config"]["mode"] = "<mode>"
    data["config"]["confirm_cost"] = "<confirm>"
    data["runtime"]["recording"] = "<recording>"
    data["judge"]["recording"] = "<recording>"
    return json.dumps(data, ensure_ascii=False, indent=2)


@pytest.fixture(scope="module")
def recorded(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, IngestEvalReport, Factory]:
    root = tmp_path_factory.mktemp("judge")
    factory = Factory()
    config = _config(root, mode="live", record=True, confirm_cost=True)
    report = IngestEvalHarness(config, live_llm_factory=factory).run()
    return root, report, factory


# --- mock 회귀: 결정적 매처 = 부분 문자열 -----------------------------------------------------------------------


@pytest.mark.parametrize("golden", [INGEST_GOLDEN_V1, INGEST_GOLDEN])
def test_mock_all_deterministic_keyfact_matcher_equals_substring(golden: Path) -> None:
    config = IngestEvalConfig(
        mode="mock",
        split="all",
        sources_path=golden / "sources.jsonl",
        annotations_path=golden / "annotations.jsonl",
        baseline_path=None,
    )
    harness = IngestEvalHarness(config)
    report = harness.run()
    loaded, _ = load_ingest_golden(config.sources_path, config.annotations_path)
    facts = {annotation.source_id: annotation.gold.key_facts for annotation in loaded.annotations}
    compared = 0
    for item in report.items:
        if not item.metrics:
            continue
        summary = normalize_text(harness.last_outputs[item.source_id][0].summary)
        substring = sum(normalize_text(f) in summary for f in facts[item.source_id]) / len(facts[item.source_id])
        assert item.metrics["summary_key_fact_recall"] == substring, item.source_id
        compared += 1
    assert compared >= 75
    assert report.judge is None and "judge" not in report.deterministic_dict()


def test_mock_mode_rejects_judge() -> None:
    with pytest.raises(ValueError, match="recorded/live"):
        IngestEvalHarness(IngestEvalConfig(mode="mock", split="dev", judge_profile=JUDGE)).run()


# --- 녹화 → 재생 ---------------------------------------------------------------------------------------------------


def test_judge_recording_replays_byte_for_byte_without_prompt_text(
    recorded: tuple[Path, IngestEvalReport, Factory], tmp_path: Path
) -> None:
    root, live, factory = recorded
    assert set(factory.models) == {"kanana-1.5-2.1b-instruct-q4km", "kanana-1.5-8b-instruct-q4km"}
    path = root / "llm" / f"judge.{_stem(_judge_model_id())}.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert {row["schema_name"] for row in rows if row["kind"] == "complete_json"} == {
        "JudgeVerdicts",
        "KeyFactVerdicts",
    }
    assert any(row["kind"] == "count_tokens" for row in rows)
    text = path.read_text(encoding="utf-8")
    assert "보안 규칙" not in text and "<source_document>" not in text and "<summary_sentences>" not in text
    assert live.misses == []

    first = IngestEvalHarness(_config(root)).run()
    second = IngestEvalHarness(_config(root)).run()
    assert first.misses == []
    assert _comparable(first) == _comparable(live)
    paths_a = write_ingest_report(first, tmp_path / "a")
    paths_b = write_ingest_report(second, tmp_path / "b")
    for one, two in zip(paths_a, paths_b, strict=True):
        assert one.read_bytes() == two.read_bytes()
    assert first.judge is not None and first.judge.recording is False
    assert first.judge.recording_model_id == _judge_model_id()
    assert not Path(first.judge.recording_file).is_absolute()
    assert set(first.judge.prompts) == {"judge_faithfulness_v1", "judge_keyfact_v1"}
    assert first.runtime is not None and first.runtime.judge == JUDGE


def test_judge_failed_is_counted_separately_and_uncalibrated_uses_deterministic(
    recorded: tuple[Path, IngestEvalReport, Factory],
) -> None:
    root, _, _ = recorded
    report = IngestEvalHarness(_config(root)).run()
    overall = report.overall
    assert report.judge is not None and not report.judge.faithfulness_calibrated
    assert overall["judge_failed_sentences"] and overall["judge_failed_sentences"] > 0
    assert overall["judge_retries"] and overall["judge_retries"] > 0
    # 미보정: 대표값은 결정적 값 그대로 (판정기 unsupported가 있어도 비충실에 더하지 않는다)
    assert overall["unsupported_sentence_rate"] == overall["unsupported_sentence_rate_deterministic"]
    assert overall["summary_key_fact_recall"] == overall["summary_key_fact_recall_deterministic"]
    assert overall["summary_key_fact_recall_judge"] is not None
    for item in report.items:
        if item.metrics:
            assert item.metrics["judge_sentences"] >= item.metrics["judge_failed_sentences"]
    markdown = render_ingest_markdown(report)
    assert "## 판정기 (8.3·8.4절)" in markdown and "보정 파일 없음" in markdown
    assert "| unsupported_sentence_rate (판정기 미보정) |" in markdown
    assert "| summary_key_fact_recall (판정기 미보정) |" in markdown
    assert "judge_failed" in markdown


def _calibration_file(root: Path, report: IngestEvalReport, *, passed: bool, human: bool = True) -> Path:
    from tests.unit.test_judge_t25g import _stats

    assert report.judge is not None
    calibration = JudgeCalibration(
        judge_profile=JUDGE,
        recording_model_id=report.judge.recording_model_id,
        prompts=report.judge.prompts,
        labels_file="labels.jsonl",
        labels_sha256="0" * 64,
        faithfulness=_stats("faithfulness", passed),
        keyfact=_stats("keyfact", passed),
        human_labels=human,
    )
    path = root / f"calibration_{passed}_{human}.json"
    path.write_text(calibration.model_dump_json(), encoding="utf-8")
    return path


def test_calibrated_judge_switches_to_combined_rule_and_judge_keyfact_recall(
    recorded: tuple[Path, IngestEvalReport, Factory],
) -> None:
    root, live, _ = recorded
    path = _calibration_file(root, live, passed=True)
    report = IngestEvalHarness(_config(root, judge_calibration_path=path)).run()
    assert report.judge is not None and report.judge.faithfulness_calibrated and report.judge.keyfact_calibrated
    overall = report.overall
    assert overall["summary_key_fact_recall"] == overall["summary_key_fact_recall_judge"]
    rate = overall["unsupported_sentence_rate"]
    deterministic = overall["unsupported_sentence_rate_deterministic"]
    # 결합 규칙이 적용됐다: 1차 후보를 판정기가 supported로 본 문장은 빠지고, 판정기 unsupported는 더해진다
    assert rate is not None and deterministic is not None and rate != deterministic
    markdown = render_ingest_markdown(report)
    assert "(판정기 미보정)" not in markdown and "보정 통과" in markdown
    # 보정 미달 파일 → 다시 결정적 값
    failed = _calibration_file(root, live, passed=False)
    again = IngestEvalHarness(_config(root, judge_calibration_path=failed)).run()
    assert again.overall["unsupported_sentence_rate"] == again.overall["unsupported_sentence_rate_deterministic"]


def test_t25g_l2_quasi_human_calibration_is_marked_where_the_gate_is_read(
    recorded: tuple[Path, IngestEvalReport, Factory],
) -> None:
    """T25g 검수 L2: 준-사람 라벨 보정은 머리말·지표 비고·게이트 행 모두에 '사람 판정 아님'이 보여야 한다."""
    root, live, _ = recorded
    human = render_ingest_markdown(
        IngestEvalHarness(_config(root, judge_calibration_path=_calibration_file(root, live, passed=True))).run()
    )
    assert "준-사람" not in human
    path = _calibration_file(root, live, passed=True, human=False)
    markdown = render_ingest_markdown(IngestEvalHarness(_config(root, judge_calibration_path=path)).run())
    label = "보정 통과 (준-사람 라벨, 사람 판정 아님)"
    header = next(line for line in markdown.splitlines() if line.startswith(f"- 판정기 `{JUDGE}`"))
    assert label in header
    assert f"판정기 값 ({label})" in markdown and f"1차 결정적 + 2차 판정기 결합 ({label})" in markdown
    assert "| unsupported_sentence_rate (준-사람 보정) |" in markdown
    assert "| summary_key_fact_recall (준-사람 보정) |" in markdown


def test_judge_recording_miss_is_reported_and_cli_exits_two(
    recorded: tuple[Path, IngestEvalReport, Factory], tmp_path: Path
) -> None:
    root, _, _ = recorded
    copy = tmp_path / "llm"
    copy.mkdir()
    for source in (root / "llm").iterdir():
        lines = source.read_text(encoding="utf-8").splitlines()
        if source.name.startswith("judge."):
            lines = lines[: len(lines) // 3]
        (copy / source.name).write_text("\n".join(lines) + "\n", encoding="utf-8")
    report = IngestEvalHarness(_config(tmp_path)).run()
    assert report.misses and all(miss.request_hash or miss.prompt_hash for miss in report.misses)
    assert {miss.schema_name for miss in report.misses} <= {"JudgeVerdicts", "KeyFactVerdicts", None}
    result = runner.invoke(
        app,
        [
            "eval",
            "ingest",
            "--mode",
            "recorded",
            "--profile",
            PROFILE,
            "--split",
            "dev",
            "--judge",
            JUDGE,
            "--recordings-dir",
            str(copy),
            "--judge-calibration",
            str(tmp_path / "none.json"),
            "--out",
            str(tmp_path / "out"),
        ],
    )
    assert result.exit_code == 2, result.output
    assert "녹화 미스" in result.output


# --- T25p: T25g 검수 M1 (판정기 제공자 오류·타임아웃 녹화) ----------------------------------------------------------


class FlakyJudgeLLM(JudgeEchoLLM):
    """일부 요청(프롬프트 해시로 결정적으로 고른다)에서 타임아웃·제공자 오류를 낸다."""

    def complete_json(
        self,
        system: str,
        user: str,
        schema: type[BaseModel],
        timeout_s: float,
        max_tokens: int = 4000,
        effort: str | None = None,
    ) -> LLMRawResponse:
        bucket = int(prompt_hash(system, user)[:2], 16)
        if bucket % 5 == 0:
            raise LLMTimeoutError("판정 생성 타임아웃 <원문 일부>", {"retryable": True, "timeout_s": timeout_s})
        if bucket % 7 == 0:
            raise LLMProviderError("Metal 메모리 부족 <원문 일부>")
        return super().complete_json(system, user, schema, timeout_s, max_tokens, effort)


class FlakyFactory(Factory):
    def __call__(self, spec: LocalModelSpec, decoding: DecodingParams) -> MockLLM:
        client = super().__call__(spec, decoding)
        return FlakyJudgeLLM(client.model_id) if isinstance(client, JudgeEchoLLM) else client


def test_t25g_m1_judge_provider_errors_are_recorded_and_replayed(tmp_path: Path) -> None:
    """T25g 검수 M1 재현: live 녹화 중 판정기 오류가 나면 예전에는 그 요청이 녹화되지 않아
    recorded 재생이 미스(종료 2)였다."""
    live = IngestEvalHarness(
        _config(tmp_path, mode="live", record=True, confirm_cost=True), live_llm_factory=FlakyFactory()
    ).run()
    assert live.judge is not None
    failed = live.overall.get("judge_failed_sentences", 0) or 0
    assert failed > 0 or (live.overall.get("judge_failed_keyfacts", 0) or 0) > 0, live.overall

    replay = IngestEvalHarness(_config(tmp_path)).run()
    assert replay.misses == []
    assert _comparable(replay) == _comparable(live)

    sidecar = tmp_path / "llm" / f"judge.{_stem(_judge_model_id())}.failures.jsonl"
    rows = [json.loads(line) for line in sidecar.read_text(encoding="utf-8").splitlines()]
    assert rows and {row["error"]["code"] for row in rows} <= {"LLM_TIMEOUT", "LLM_UNAVAILABLE"}
    text = sidecar.read_text(encoding="utf-8")
    assert "원문 일부" not in text and "<source_document>" not in text  # 오류 메시지·프롬프트 원문은 남기지 않는다
    assert all(
        set(row)
        == {
            "format_version",
            "kind",
            "model_id",
            "request_hash",
            "prompt_hash",
            "schema_name",
            "max_tokens",
            "effort",
            "error",
        }
        for row in rows
    )


# --- judge-sample → judge-calibrate -------------------------------------------------------------------------------


def test_judge_sample_and_calibrate_record_then_replay(
    recorded: tuple[Path, IngestEvalReport, Factory], tmp_path: Path
) -> None:
    root, _, _ = recorded
    rows = judge_sample([PROFILE], mode="recorded", recordings_dir=root / "llm", n_sentences=40, n_keyfacts=30)
    again = judge_sample([PROFILE], mode="recorded", recordings_dir=root / "llm", n_sentences=40, n_keyfacts=30)
    assert rows == again and len(rows) == 70
    labels = [
        row.model_copy(update={"label": "supported" if row.kind == "sentence" else "covered", "annotator": "human"})
        for row in rows
    ]
    path = tmp_path / "labels.jsonl"
    path.write_text(dump_label_rows(labels), encoding="utf-8")
    assert load_label_rows(path) == labels

    record_dir = tmp_path / "judge_llm"
    live = judge_calibrate(path, JUDGE, mode="live", recordings_dir=record_dir, live_llm_factory=Factory(), record=True)
    replay = judge_calibrate(path, JUDGE, mode="recorded", recordings_dir=record_dir)
    assert live == replay
    assert replay.faithfulness.labeled == 40 and replay.keyfact.labeled == 30
    assert not replay.faithfulness.passed  # 표본 40 < 100
    assert replay.human_labels and replay.recording_model_id == _judge_model_id()
    # 보정 요청은 평가 요청과 같다: 평가 녹화(root)만으로도 재생된다
    from_eval = judge_calibrate(path, JUDGE, mode="recorded", recordings_dir=root / "llm")
    assert from_eval == replay

    out = tmp_path / "cal.json"
    result = runner.invoke(
        app,
        [
            "eval",
            "judge-calibrate",
            "--judge",
            JUDGE,
            "--labels",
            str(path),
            "--recordings-dir",
            str(record_dir),
            "--out",
            str(out),
        ],
    )
    assert result.exit_code == 1, result.output  # 표본 부족 → 미달
    assert "이진 κ" in result.output and out.is_file()
    assert JudgeCalibration.model_validate_json(out.read_text(encoding="utf-8")) == replay


def test_judge_cli_guards(tmp_path: Path) -> None:
    out = tmp_path / "labels.jsonl"
    result = runner.invoke(app, ["eval", "judge-sample", "--candidates", "mock", "--mode", "mock", "--out", str(out)])
    assert result.exit_code == 0, result.output
    rows = load_label_rows(out)
    assert rows and all(row.source_id.startswith("ing2_") for row in rows)
    labeled = [rows[0].model_copy(update={"label": "supported"}), *rows[1:]]
    out.write_text(dump_label_rows(labeled), encoding="utf-8")
    result = runner.invoke(app, ["eval", "judge-sample", "--candidates", "mock", "--mode", "mock", "--out", str(out)])
    assert result.exit_code == 2 and "--force" in result.output
    result = runner.invoke(app, ["eval", "judge-calibrate", "--labels", str(out), "--mode", "live"])
    assert result.exit_code == 2 and "--confirm-run" in result.output
    assert "live 판정기 보정 1회" in result.output and "예상 소요 시간" in result.output
    result = runner.invoke(app, ["eval", "judge-sample", "--candidates", "mock", "--mode", "live"])
    assert result.exit_code == 2
    # test split 건은 보정 라벨로 받지 않는다
    loaded, _ = load_ingest_golden(INGEST_GOLDEN / "sources.jsonl", INGEST_GOLDEN / "annotations.jsonl")
    test_id = next(a.source_id for a in loaded.annotations if a.split == "test")
    bad = tmp_path / "bad.jsonl"
    bad.write_text(dump_label_rows([rows[0].model_copy(update={"source_id": test_id})]), encoding="utf-8")
    with pytest.raises(ValueError, match="dev"):
        judge_calibrate(bad, JUDGE, recordings_dir=tmp_path)

"""T25f: 분석기 녹화·재생과 인제스트 하네스 확장 (설계 design_local_analyzer.md 7절, 8.2절, 10.1절 T25f).

- MockLLM을 감싼 RecordingLLM으로 녹화 → RecordedLLM 재생이 같은 리포트(바이트 동일)
- 녹화 미스 → 그 건 실패, 미스 목록, CLI 종료 2
- test split은 동결 해시 없이 거부 (모델 호출 0회)
- live는 확인 플래그 없이 실행하지 않음 (모델 호출 0회, 녹화 파일 없음)
- live 서비스 경로는 녹화하지 않음
- 검색 연결 지표 mock 경로 결정성, recorded 경로 배선
- L-3 추출 실패 fixture 항목화

실제 모델은 쓰지 않는다. llama_cpp 없이 기본 설치에서 돈다.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel
from typer.testing import CliRunner

from jupjup.cli import app
from jupjup.config import AnalyzerSettings, Settings
from jupjup.container import AppContainer, build_container, build_content_analyzer, build_ingest_service
from jupjup.domain.errors import LLMProviderError
from jupjup.eval.ingest_bench import bench_from_run
from jupjup.eval.ingest_harness import INGEST_GOLDEN, IngestEvalConfig, IngestEvalHarness, IngestEvalReport
from jupjup.eval.ingest_linkage import record_linkage, run_linkage
from jupjup.eval.ingest_report import render_ingest_markdown, write_ingest_report
from jupjup.eval.ingest_runtime import (
    DEFAULT_PROFILES_PATH,
    CapturingAnalyzer,
    check_frozen_config,
    estimate_run,
    frozen_config_sha256,
    prepare_local_setup,
)
from jupjup.eval.judge import split_sentences
from jupjup.ingest.analyzer import LLMContentAnalyzer, PromptStore
from jupjup.ingest.extractive import ExtractiveMockAnalyzer
from jupjup.ingest.profiles import AnalyzerProfiles, DecodingParams, LocalModelSpec, recording_model_id
from jupjup.ingest.schemas import AnalysisOutput
from jupjup.ingest.service import IngestRequest
from jupjup.ingest.validation import AnalysisValidator
from jupjup.providers.embedding import HashingEmbedder, RecordingEmbedder
from jupjup.providers.llm import LLMRawResponse, MockLLM, prompt_hash
from jupjup.providers.recording import RecordingLLM
from jupjup.storage.db import create_db_engine

runner = CliRunner()
PROFILE = "local-kanana-2b"
_BLOCK = re.compile(r"<(source_document|source_head|source_chunk)>\n(.*?)\n</\1>", re.S)


class GoldenEchoLLM(MockLLM):
    """MockLLM 확장: 원문 블록에서 근거 있는 응답을 만든다. 일부 요청은 일부러 잘린 JSON을 낸다 (재요청 경로 녹화)."""

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
        if schema is not AnalysisOutput:
            text = json.dumps({"facts": [], "entities": [], "locations": [], "keywords": [], "quotes": []})
        elif "<previous_output>" not in user and int(key[:2], 16) % 4 == 0:
            text = '{"language": "ko", "summary": "잘린'  # 첫 시도 실패 → 재요청 (녹화에 재요청 행이 생긴다)
        else:
            text = json.dumps(_answer(user), ensure_ascii=False)
        return LLMRawResponse(text=text, input_tokens=len(system) + len(user), output_tokens=len(text), latency_ms=7.0)


def _answer(user: str) -> dict[str, Any]:
    match = _BLOCK.search(user)
    source = " ".join((match.group(2) if match else "").split())
    sentences = [sentence for sentence in split_sentences(source) if sentence.strip()][:2] or ["내용 없음"]
    summary = " ".join(sentences)
    span = source[:40] or "내용"
    return {
        "language": "ko",
        "title_suggestion": None,
        "evidence": [{"claim": "원문 첫 구절", "source_span": span}],
        "summary": summary,
        "representative_tags": ["정보", "자료", "메모"],
        "detail_tags": {"schema_version": 1, "category": "other", "entities": [], "locations": []},
        "save_intent": {"labels": ["정보보관"], "confidence": 0.5, "rationale": "정보를 보관한다"},
    }


def _model_id(profile: str = PROFILE) -> str:
    profiles = AnalyzerProfiles.load(DEFAULT_PROFILES_PATH)
    chosen = profiles.profile(profile)
    return recording_model_id(profiles.model_for(chosen), chosen.decoding)


class FactoryProbe:
    def __init__(self) -> None:
        self.calls = 0
        self.clients: list[GoldenEchoLLM] = []

    def __call__(self, spec: LocalModelSpec, decoding: DecodingParams) -> GoldenEchoLLM:
        self.calls += 1
        client = GoldenEchoLLM(recording_model_id(spec, decoding))
        self.clients.append(client)
        return client


def _config(tmp_path: Path, **updates: Any) -> IngestEvalConfig:
    values: dict[str, Any] = {
        "mode": "recorded",
        "profile": PROFILE,
        "split": "dev",
        "baseline_path": None,
        "recordings_dir": tmp_path / "llm",
    }
    values.update(updates)
    return IngestEvalConfig(**values)


def _record(tmp_path: Path, split: str = "dev", **updates: Any) -> tuple[IngestEvalReport, FactoryProbe]:
    probe = FactoryProbe()
    config = _config(tmp_path, mode="live", split=split, record=True, confirm_cost=True, **updates)
    report = IngestEvalHarness(config, live_llm_factory=probe).run()
    return report, probe


def _comparable(report: IngestEvalReport) -> str:
    """live 녹화 실행과 recorded 재생에서 원래 달라야 하는 값(mode, 확인 플래그, 녹화 여부)만 맞춘다."""
    data = report.deterministic_dict()
    data["config"]["mode"] = "<mode>"
    data["config"]["confirm_cost"] = "<confirm>"
    data["runtime"]["recording"] = "<recording>"
    return json.dumps(data, ensure_ascii=False, indent=2)


@pytest.fixture(scope="module")
def recorded_dev(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, IngestEvalReport]:
    root = tmp_path_factory.mktemp("record")
    report, probe = _record(root)
    assert probe.calls == 1  # 분석·청크 모델이 같으면 클라이언트 하나
    return root, report


# --- 녹화 → 재생 ---------------------------------------------------------------------------------------------------


def test_recorded_replay_reproduces_recording_run_byte_for_byte(
    recorded_dev: tuple[Path, IngestEvalReport], tmp_path: Path
) -> None:
    root, live = recorded_dev
    recording = root / "llm" / f"analyze.{_model_id().replace('@', '_at_').replace('~', '_dec_')}.jsonl"
    assert recording.is_file()
    rows = [json.loads(line) for line in recording.read_text(encoding="utf-8").splitlines()]
    assert {row["model_id"] for row in rows} == {_model_id()}
    assert any(row["max_tokens"] == 1536 for row in rows)
    assert live.counts["retry_exercised"] > 0  # 일부러 낸 잘린 JSON → 재요청 행까지 녹화됐다
    assert live.misses == []

    first = IngestEvalHarness(_config(root)).run()
    second = IngestEvalHarness(_config(root)).run()
    assert first.misses == []
    assert _comparable(first) == _comparable(live)
    assert first.items == live.items and first.overall == live.overall
    first_paths = write_ingest_report(first, tmp_path / "a")
    second_paths = write_ingest_report(second, tmp_path / "b")
    for one, two in zip(first_paths, second_paths, strict=True):
        assert one.read_bytes() == two.read_bytes()
    assert first.runtime is not None and first.runtime.recording is False
    assert first.runtime.recording_model_id == _model_id()
    assert first.runtime.prompts.keys() == {
        "analyze_local_v2",
        "repair_local_v2",
        "chunk_notes_local_v2",
        "reduce_local_v2",
    }
    assert not Path(first.runtime.recording_files[0]).is_absolute()
    # 원문 프롬프트는 녹화하지 않는다 (AC-L9): 시스템 지시문, 블록 태그, 메타데이터 JSON이 파일에 없다.
    text = recording.read_text(encoding="utf-8")
    assert "보안 규칙" not in text and "<source_document>" not in text and "content_metadata" not in text


def test_recorded_report_has_quality_metrics_runtime_and_miss_sections(
    recorded_dev: tuple[Path, IngestEvalReport],
) -> None:
    root, _ = recorded_dev
    report = IngestEvalHarness(_config(root)).run()
    assert report.overall["tag_f1"] is not None
    assert report.overall["unsupported_sentence_rate"] is not None
    names = [check.name for check in report.gate.checks]
    assert names[:3] == ["schema_final_pass_rate", "schema_first_pass_rate", "tag_f1"]
    markdown = render_ingest_markdown(report)
    assert "## 실행 설정 (AC-L15)" in markdown
    assert "## 녹화 미스" in markdown and "- 없음" in markdown
    assert "판정기 미보정" in markdown
    assert "3.5.4절 기본 분석기 기준" in markdown


def test_recording_skips_requests_already_recorded(recorded_dev: tuple[Path, IngestEvalReport], tmp_path: Path) -> None:
    root, _ = recorded_dev
    copy = tmp_path / "llm"
    shutil.copytree(root / "llm", copy)
    path = next(copy.iterdir())
    before = path.read_bytes()
    _record(tmp_path)  # --append와 같은 동작: 같은 요청은 덧붙이지 않는다
    assert path.read_bytes() == before


# --- 미스 ----------------------------------------------------------------------------------------------------------


def test_recorded_miss_fails_the_item_and_cli_exits_two(
    recorded_dev: tuple[Path, IngestEvalReport], tmp_path: Path
) -> None:
    root, _ = recorded_dev
    copy = tmp_path / "llm"
    shutil.copytree(root / "llm", copy)
    path = next(copy.iterdir())
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join(lines[: len(lines) // 2]) + "\n", encoding="utf-8")

    report = IngestEvalHarness(_config(tmp_path)).run()
    assert report.misses
    missed = {miss.source_id for miss in report.misses}
    failed = {item.source_id for item in report.items if item.error_code == "LLM_CACHE_MISS"}
    assert missed == failed
    assert all(
        item.job_status == "failed" and not item.schema_final_pass for item in report.items if item.source_id in failed
    )
    assert all(miss.kind == "complete_json" and miss.request_hash for miss in report.misses)
    assert "## 녹화 미스" in render_ingest_markdown(report)

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
            "--recordings-dir",
            str(copy),
            "--out",
            str(tmp_path / "out"),
        ],
    )
    assert result.exit_code == 2, result.output
    assert f"녹화 미스 {len(report.misses)}건" in result.output
    assert "Traceback" not in result.output
    saved = json.loads((tmp_path / "out" / "eval_ingest_recorded_dev.json").read_text(encoding="utf-8"))
    assert len(saved["misses"]) == len(report.misses)


def test_recorded_without_recording_file_is_a_config_error(tmp_path: Path) -> None:
    with pytest.raises(LLMProviderError, match="녹화본 파일이 없습니다"):
        IngestEvalHarness(_config(tmp_path)).run()


# --- 동결 해시 -----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("split", ["test", "all"])
def test_test_split_is_refused_without_frozen_hash_before_any_model_call(tmp_path: Path, split: str) -> None:
    probe = FactoryProbe()
    for mode in ("recorded", "live"):
        config = _config(tmp_path, mode=mode, split=split, confirm_cost=True, record=mode == "live")
        with pytest.raises(ValueError, match="설정 동결 뒤에만"):
            IngestEvalHarness(config, live_llm_factory=probe).run()
        wrong = config.model_copy(update={"frozen_config": "0" * 64})
        with pytest.raises(ValueError, match="동결 해시가 현재 설정과 다릅니다"):
            IngestEvalHarness(wrong, live_llm_factory=probe).run()
    assert probe.calls == 0
    assert not (tmp_path / "llm").exists()


def test_test_split_runs_with_matching_frozen_hash(tmp_path: Path) -> None:
    sha = IngestEvalHarness(_config(tmp_path)).frozen_config_sha256()
    report, probe = _record(tmp_path, split="test", frozen_config=sha)
    assert probe.calls == 1 and report.counts["sources"] == 32
    assert report.runtime is not None and report.runtime.frozen_config_checked
    replay = IngestEvalHarness(_config(tmp_path, split="test", frozen_config=sha)).run()
    assert replay.misses == [] and replay.items == report.items


def test_frozen_hash_tracks_prompts_profile_and_model(tmp_path: Path) -> None:
    profiles = AnalyzerProfiles.load(DEFAULT_PROFILES_PATH)
    profile = profiles.profile(PROFILE)
    base = frozen_config_sha256(profiles, profile, PromptStore())
    assert base == frozen_config_sha256(profiles, profile, PromptStore())

    prompts = tmp_path / "prompts"
    shutil.copytree(Path(PromptStore().root), prompts)
    (prompts / "repair_local_v2.md").write_bytes((prompts / "repair_local_v2.md").read_bytes() + b"\n")
    assert frozen_config_sha256(profiles, profile, PromptStore(prompts)) != base

    tuned = profile.model_copy(update={"max_repairs": 1})
    assert frozen_config_sha256(profiles, tuned, PromptStore()) != base

    # T25f 검수 L2: n_ctx(입력 상한 거부로 결과를 바꾼다)를 동결 뒤 바꾸면 해시가 달라진다. 실측 p50은 무관하다.
    spec = profiles.models[profile.model or ""]
    for update, changes in (({"n_ctx": spec.n_ctx // 2}, True), ({"measured_p50_s": 99.0}, False)):
        models = {**profiles.models, spec.model_id: spec.model_copy(update=update)}
        changed = frozen_config_sha256(profiles.model_copy(update={"models": models}), profile, PromptStore())
        assert (changed != base) is changes, update
    other_model = profiles.profile("local-qwen3-4b")
    assert frozen_config_sha256(profiles, other_model, PromptStore()) != base
    with pytest.raises(ValueError, match="local 프로필"):
        frozen_config_sha256(profiles, profiles.profile("mock"), PromptStore())
    check_frozen_config("dev", None, base)  # dev는 동결 전에 돈다


def test_cli_record_test_split_requires_frozen_hash(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "analyze",
            "record",
            "--profile",
            PROFILE,
            "--split",
            "test",
            "--confirm-run",
            "--recordings-dir",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 2
    assert "설정 동결 뒤에만" in result.output
    seeds = runner.invoke(app, ["analyze", "record", "--profile", PROFILE, "--target", "seeds", "--confirm-run"])
    assert seeds.exit_code == 2 and "설정 동결 뒤에만" in seeds.output
    assert list(tmp_path.iterdir()) == []

    freeze = runner.invoke(app, ["analyze", "freeze", "--profile", PROFILE, "--json"])
    assert freeze.exit_code == 0
    payload = json.loads(freeze.output)
    assert payload["frozen_config_sha256"] == IngestEvalHarness(_config(tmp_path)).frozen_config_sha256()


# --- live 확인 플래그 ------------------------------------------------------------------------------------------------


def test_live_never_runs_without_confirmation(tmp_path: Path) -> None:
    probe = FactoryProbe()
    config = _config(tmp_path, mode="live", record=True)
    with pytest.raises(ValueError, match="--confirm-run 없이"):
        IngestEvalHarness(config, live_llm_factory=probe).run()
    assert probe.calls == 0

    for args in (
        ["eval", "ingest", "--mode", "live", "--profile", PROFILE, "--split", "dev"],
        ["analyze", "record", "--profile", PROFILE, "--split", "dev"],
        ["bench", "analyze", "--profile", PROFILE, "--split", "dev"],
    ):
        result = runner.invoke(
            app, [*args, *(["--recordings-dir", str(tmp_path / "llm")] if "bench" not in args else [])]
        )
        assert result.exit_code == 2, result.output
        assert "예상 소요 시간: 약 13.3분 (48건 × p50 16.6초)" in result.output
        assert "$0.00" in result.output
        assert "--confirm-run" in result.output
    assert not (tmp_path / "llm").exists()


def test_t25g_l1_live_judge_estimate_is_reported_separately() -> None:
    result = runner.invoke(
        app,
        [
            "eval",
            "ingest",
            "--mode",
            "live",
            "--profile",
            PROFILE,
            "--judge",
            "judge-kanana-8b",
            "--split",
            "dev",
        ],
    )

    assert result.exit_code == 2, result.output
    assert "live 분석기 평가 48건" in result.output
    assert "live 판정기 최소 96회" in result.output
    assert "kanana-1.5-8b-instruct-q4km" in result.output
    assert "--confirm-run" in result.output


def test_record_refuses_existing_file_without_append(recorded_dev: tuple[Path, IngestEvalReport]) -> None:
    root, _ = recorded_dev
    result = runner.invoke(
        app,
        [
            "analyze",
            "record",
            "--profile",
            PROFILE,
            "--split",
            "dev",
            "--confirm-run",
            "--recordings-dir",
            str(root / "llm"),
        ],
    )
    assert result.exit_code == 2
    assert "--append" in result.output


def test_estimate_uses_measured_p50_and_unknown_without_it() -> None:
    profiles = AnalyzerProfiles.load(DEFAULT_PROFILES_PATH)
    spec = profiles.models["qwen3-4b-instruct-2507-q4km"]
    assert estimate_run(spec, 10).estimated_seconds == 467.0
    unknown = estimate_run(spec.model_copy(update={"measured_p50_s": None}), 10)
    assert unknown.estimated_seconds is None and "알 수 없음" in unknown.describe()
    assert unknown.estimated_cost_usd == 0.0


def test_live_rejects_client_whose_model_id_differs_from_recording_key(tmp_path: Path) -> None:
    config = _config(tmp_path, mode="live", record=True, confirm_cost=True)
    with pytest.raises(ValueError, match="recording_model_id"):
        IngestEvalHarness(config, live_llm_factory=lambda spec, decoding: GoldenEchoLLM("mock-llm-v1")).run()
    assert not (tmp_path / "llm").exists()


# --- live 서비스 경로는 녹화하지 않는다 -------------------------------------------------------------------------------


class _FakeLlama(GoldenEchoLLM):
    def __init__(self, spec: LocalModelSpec, decoding: DecodingParams, cache_dir: Path, **_: Any) -> None:
        super().__init__(recording_model_id(spec, decoding))


def test_live_service_path_never_wraps_or_writes_recordings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import jupjup.providers.llm_local as llm_local

    monkeypatch.setattr(llm_local, "llama_cpp_available", lambda: True)
    monkeypatch.setattr(llm_local, "LlamaCppLLM", _FakeLlama)
    recordings = tmp_path / "llm"
    settings = Settings(
        env="dev",
        mode="live",
        db_path=Path(":memory:"),
        embedding_recording_path=tmp_path / "emb.jsonl",
        analyzer=AnalyzerSettings(engine="local", profile=PROFILE, recordings_dir=recordings),
    )
    import jupjup.container as container_module

    monkeypatch.setattr(container_module, "BgeM3Embedder", lambda **_: HashingEmbedder(_lexicon(), _kiwi()))
    container = build_container(settings, engine=create_db_engine(None))
    analyzer, _ = build_content_analyzer(settings, container.lexicon, container.morph_tokenizer)
    assert isinstance(analyzer, LLMContentAnalyzer)
    assert isinstance(analyzer.llm, _FakeLlama) and not isinstance(analyzer.llm, RecordingLLM)

    def no_recording(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("서비스 경로가 RecordingLLM을 만들었다")

    monkeypatch.setattr(container_module, "RecordingLLM", no_recording)
    service = build_ingest_service(container, worker_id="svc")
    stage_analyzer = service.worker.stages["analyze"].__self__.analyzer  # type: ignore[union-attr]
    assert isinstance(stage_analyzer, LLMContentAnalyzer) and isinstance(stage_analyzer.llm, _FakeLlama)
    submitted = service.submit(
        "u_alice",
        IngestRequest.model_validate(
            {"source": {"kind": "text", "text": "망원동 빵집은 화요일에 통밀 식빵을 굽는다."}}
        ),
    )
    service.run_inline(submitted.job_id)
    assert not recordings.exists()


def _lexicon() -> Any:
    from jupjup.text.lexicon import Lexicon

    return Lexicon.load(Path(__file__).resolve().parents[2] / "data" / "lexicon")


def _kiwi() -> Any:
    from jupjup.text.tokenizer import KiwiTokenizer

    return KiwiTokenizer(_lexicon())


def test_bench_run_does_not_record_and_splits_latency(tmp_path: Path) -> None:
    probe = FactoryProbe()
    config = _config(tmp_path, mode="live", record=False, confirm_cost=True)
    harness = IngestEvalHarness(config, live_llm_factory=probe)
    report = harness.run()
    assert harness.last_capture is not None
    bench = bench_from_run(report, harness.last_capture, rss_mb=123.0)
    assert bench.items == 48 and bench.single.n + bench.map_reduce.n == len(harness.last_capture.wall_ms)
    assert bench.recording_model_id == _model_id()
    assert bench.single.budget_p95_s == 60.0 and bench.map_reduce.budget_p95_s == 300.0
    assert not (tmp_path / "llm").exists()
    assert report.runtime is not None and report.runtime.recording is False


# --- 검색 연결 지표 ------------------------------------------------------------------------------------------------


def _mock_linkage_analyzer() -> tuple[ExtractiveMockAnalyzer, None]:
    lexicon = _lexicon()
    return ExtractiveMockAnalyzer(_kiwi(), AnalysisValidator(lexicon)), None


@pytest.mark.eval
def test_mock_linkage_is_deterministic() -> None:
    analyzer, chunk_settings = _mock_linkage_analyzer()
    first = run_linkage(analyzer, chunk_settings, embedder="mock", query_split="dev")
    second = run_linkage(analyzer, chunk_settings, embedder="mock", query_split="dev")
    assert first.model_dump() == second.model_dump()
    metrics = first.report_metrics()
    assert metrics["recorded_embedder"] == 0.0
    assert metrics["n_queries"] > 0 and metrics["seeds_succeeded"] == 200.0
    assert 0.0 <= metrics["analyzer_recall@10"] <= 1.0 and 0.0 <= metrics["human_recall@10"] <= 1.0
    assert metrics["recall@10_drop"] == round(metrics["human_recall@10"] - metrics["analyzer_recall@10"], 6)
    assert first.misses == []


@pytest.mark.eval
def test_recorded_linkage_records_then_replays_without_misses(
    recorded_dev: tuple[Path, IngestEvalReport], tmp_path: Path
) -> None:
    """record-linkage(가짜 bge-m3) → recorded 연결 지표. 질의는 실제 검색 녹화, 문서는 연결 녹화에서 읽는다."""
    analyzer, chunk_settings = _mock_linkage_analyzer()
    output = tmp_path / "linkage" / f"embeddings.bge-m3.{PROFILE}.jsonl"

    class FakeBge(HashingEmbedder):
        model_id = "bge-m3"

    def live_container(path: Path) -> AppContainer:
        settings = Settings(env="test", mode="mock", db_path=Path(":memory:"), embedding_dim=1024)
        container = build_container(settings, engine=create_db_engine(None))
        fake = RecordingEmbedder(FakeBge(container.lexicon, container.morph_tokenizer, dim=1024), path)
        container.indexer.embedder = fake
        return container

    stats = record_linkage(analyzer, chunk_settings, output, container_factory=live_container)
    assert output.is_file() and stats["vectors"]
    with pytest.raises(ValueError, match="--force"):
        record_linkage(analyzer, chunk_settings, output, container_factory=live_container)

    result = run_linkage(analyzer, chunk_settings, embedder="recorded", linkage_file=output, query_split="dev")
    assert result.misses == [] and result.seed_statuses == {"succeeded": 200}
    assert result.report_metrics()["recorded_embedder"] == 1.0


def test_harness_linkage_option_fills_overall_and_gates_only_recorded(tmp_path: Path) -> None:
    def fake_linkage(*_args: Any, **kwargs: Any) -> Any:
        from jupjup.eval.ingest_linkage import LinkageResult

        return LinkageResult(
            embedder=kwargs["embedder"],
            query_split="all",
            n_queries=3,
            seed_statuses={"succeeded": 200},
            human={"recall@10": 0.9, "ndcg@10": 0.8},
            analyzer={"recall@10": 0.85, "ndcg@10": 0.7},
            misses=[],
        )

    import jupjup.eval.ingest_harness as harness_module

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(harness_module, "run_linkage", fake_linkage)
        mock_report = IngestEvalHarness(IngestEvalConfig(split="dev", linkage="mock")).run()
    assert mock_report.search_linkage is not None
    assert mock_report.overall["search_recall@10"] == 0.85
    assert not any(check.name == "search_recall@10_drop" for check in mock_report.gate.checks)
    assert "mock HashingEmbedder (판정 제외)" in render_ingest_markdown(mock_report)


@pytest.mark.eval
def test_t25f_m1_empty_linkage_recording_reports_embedding_misses(tmp_path: Path) -> None:
    """T25f 검수 M1 재현: 빈 연결 녹화로 recorded 연결 지표를 재면 예전에는 미스 0건과 R@10 하락 0.9가 나왔다."""
    analyzer, chunk_settings = _mock_linkage_analyzer()
    empty = tmp_path / f"embeddings.bge-m3.{PROFILE}.jsonl"
    empty.write_text("", encoding="utf-8")
    result = run_linkage(analyzer, chunk_settings, embedder="recorded", linkage_file=empty, query_split="dev")
    embedding_misses = [miss for miss in result.misses if miss.kind == "embedding"]
    assert len(embedding_misses) == 200 == sum(v for k, v in result.seed_statuses.items() if k != "succeeded")
    assert all(miss.source_id.startswith("c_") and miss.request_hash is None for miss in embedding_misses)
    assert embedding_misses == sorted(embedding_misses, key=lambda miss: miss.source_id)


@pytest.mark.eval
def test_t25f_m1_harness_with_empty_linkage_recording_reports_misses(tmp_path: Path) -> None:
    linkage_dir = tmp_path / "linkage"
    linkage_dir.mkdir()
    (linkage_dir / "embeddings.bge-m3.mock.jsonl").write_text("", encoding="utf-8")
    config = IngestEvalConfig(split="dev", linkage="recorded", linkage_split="dev", linkage_recordings_dir=linkage_dir)
    report = IngestEvalHarness(config).run()
    assert report.misses is not None and len(report.misses) == 200
    assert {miss.kind for miss in report.misses} == {"embedding"}  # CLI는 misses가 있으면 종료 2 (eval_ingest)


def test_t25f_l1_recorded_report_marks_linkage_as_not_measured(recorded_dev: tuple[Path, IngestEvalReport]) -> None:
    _, report = recorded_dev
    assert report.runtime is not None and report.runtime.linkage == "none"
    text = render_ingest_markdown(report)
    assert "search_recall@10_drop (미측정: --linkage recorded 필요) | 해당 없음 | <= 0.03 | 해당 없음 |" in text
    assert "검색 연결 지표 미측정" in text
    assert not any(check.name == "search_recall@10_drop" for check in report.gate.checks)


# --- L-3 ----------------------------------------------------------------------------------------------------------


@pytest.mark.eval
def test_empty_fixture_becomes_a_failed_item_instead_of_stopping_the_run(tmp_path: Path) -> None:
    golden = tmp_path / "ingest"
    shutil.copytree(INGEST_GOLDEN, golden)
    rows = [json.loads(line) for line in (golden / "sources.jsonl").read_text(encoding="utf-8").splitlines()]
    target = next(row for row in rows if row["source"].get("fixture", "").endswith(".html"))
    (golden / "fixtures" / target["source"]["fixture"]).write_text("<html><body></body></html>", encoding="utf-8")
    annotations = {
        json.loads(line)["source_id"]: json.loads(line)
        for line in (golden / "annotations.jsonl").read_text(encoding="utf-8").splitlines()
    }
    split = annotations[target["source_id"]]["split"]
    config = IngestEvalConfig(
        split=split,
        sources_path=golden / "sources.jsonl",
        annotations_path=golden / "annotations.jsonl",
        baseline_path=None,
    )
    report = IngestEvalHarness(config).run()
    item = next(item for item in report.items if item.source_id == target["source_id"])
    assert item.job_status == "failed" and item.error_code == "INGEST_EXTRACT_FAILED"
    assert not report.gate.passed
    assert IngestEvalHarness(config).estimate_cost().items == report.counts["sources"]


def test_capturing_analyzer_records_wall_time_and_mode() -> None:
    probe = FactoryProbe()
    setup = prepare_local_setup(DEFAULT_PROFILES_PATH, PROFILE, Path("/nonexistent"))
    client = probe(setup.spec, setup.profile.decoding)
    from jupjup.container import build_local_content_analyzer
    from jupjup.ingest.chunking import AnalysisInput, ContentMeta

    capture = CapturingAnalyzer(build_local_content_analyzer(setup.profile, client, None, _lexicon()))
    text = "망원동 빵집 보리밭은 화요일에 통밀 식빵을 굽는다. 가게는 오전 10시에 문을 연다."
    capture.analyze(AnalysisInput(mode="single", text=text, meta=ContentMeta(source_id="c1")))
    assert capture.modes == {"c1": "single"} and capture.wall_ms["c1"] >= 0.0 and "c1" in capture.results


# --- T26a: 골든셋 해시와 실제 리포트 비교 ----------------------------------------------------------------------------


def test_recorded_report_carries_golden_hash_and_compares_with_itself(
    recorded_dev: tuple[Path, IngestEvalReport], tmp_path: Path
) -> None:
    from jupjup.eval.ingest_compare import CompareRefused, compare_profiles, load_report
    from jupjup.eval.ingest_golden_checks import compute_split_digest, compute_test_seal, read_seal
    from jupjup.eval.ingest_harness import load_ingest_golden

    root, live = recorded_dev
    report = IngestEvalHarness(_config(root)).run()
    golden, errors = load_ingest_golden(INGEST_GOLDEN / "sources.jsonl", INGEST_GOLDEN / "annotations.jsonl")
    assert errors == []
    assert report.golden_sha256 == compute_split_digest(golden, INGEST_GOLDEN / "fixtures", "dev")[0]
    assert live.golden_sha256 == report.golden_sha256
    # test split 해시는 test 봉인값과 같다 (compute_test_seal은 같은 함수의 test 분기)
    assert compute_split_digest(golden, INGEST_GOLDEN / "fixtures", "test") == compute_test_seal(
        golden, INGEST_GOLDEN / "fixtures"
    )
    assert compute_test_seal(golden, INGEST_GOLDEN / "fixtures")[0] == read_seal(INGEST_GOLDEN / "test.sha256")
    # 파일로 쓴 리포트를 다시 읽어 비교한다 (CLI 경로). 같은 리포트끼리는 델타 0, 구간 폭 0.
    json_path, _ = write_ingest_report(report, tmp_path)
    loaded = load_report(json_path)
    decision = compare_profiles(loaded, report, direction="downgrade")
    assert all(delta.delta == delta.ci_low == delta.ci_high == 0.0 for delta in decision.deltas.values())
    assert decision.golden_sha256 == report.golden_sha256 and decision.n_items == 48
    mock = IngestEvalHarness(IngestEvalConfig(mode="mock", split="dev", baseline_path=None)).run()
    assert mock.golden_sha256 is None and "golden_sha256" not in mock.deterministic_dict()
    with pytest.raises(CompareRefused):
        compare_profiles(report, mock, direction="downgrade")


def test_cli_dev_linkage_does_not_read_test_queries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import jupjup.eval.ingest_harness as harness_module
    from jupjup.eval.ingest_linkage import LinkageResult

    seen: list[str] = []

    def linkage(*args: Any, **kwargs: Any) -> LinkageResult:
        seen.append(kwargs["query_split"])
        return LinkageResult(
            embedder="mock",
            query_split=kwargs["query_split"],
            n_queries=1,
            seed_statuses={"succeeded": 200},
            human={"recall@10": 1.0, "ndcg@10": 1.0},
            analyzer={"recall@10": 1.0, "ndcg@10": 1.0},
            misses=[],
        )

    monkeypatch.setattr(harness_module, "run_linkage", linkage)
    result = runner.invoke(
        app,
        [
            "eval",
            "ingest",
            "--mode",
            "mock",
            "--split",
            "dev",
            "--linkage",
            "mock",
            "--linkage-split",
            "dev",
            "--out",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 0, result.output
    assert seen == ["dev"]
    rejected = runner.invoke(app, ["eval", "ingest", "--linkage-split", "invalid"])
    assert rejected.exit_code == 2
    assert seen == ["dev"]


def test_analyzer_timeout_is_recorded_as_failure_not_cache_miss(tmp_path: Path) -> None:
    from jupjup.domain.errors import LLMTimeoutError

    class TimeoutLLM(GoldenEchoLLM):
        def complete_json(
            self,
            system: str,
            user: str,
            schema: type[BaseModel],
            timeout_s: float,
            max_tokens: int = 4000,
            effort: str | None = None,
        ) -> LLMRawResponse:
            if int(prompt_hash(system, user)[:2], 16) % 3 == 0:
                raise LLMTimeoutError("원문과 출력은 저장하지 않는다", {"retryable": True})
            return super().complete_json(system, user, schema, timeout_s, max_tokens, effort)

    def factory(spec: LocalModelSpec, decoding: DecodingParams) -> TimeoutLLM:
        return TimeoutLLM(recording_model_id(spec, decoding))

    live = IngestEvalHarness(
        _config(tmp_path, mode="live", record=True, confirm_cost=True), live_llm_factory=factory
    ).run()
    replay = IngestEvalHarness(_config(tmp_path)).run()
    assert any(item.error_code == "LLM_TIMEOUT" for item in live.items)
    assert replay.runtime is not None and replay.misses == []
    assert [(item.source_id, item.error_code) for item in replay.items] == [
        (item.source_id, item.error_code) for item in live.items
    ]
    assert _comparable(live) == _comparable(replay)

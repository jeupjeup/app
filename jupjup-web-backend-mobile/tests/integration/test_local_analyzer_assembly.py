"""T25e: 분석기 조립(6.8·6.9절)과 실패 분류(6.7절)를 표 행마다 고정한다.

가짜 ``llama_cpp`` 모듈(``tests/unit/_fake_llama.py``)과 각본 LLM을 쓴다. 네트워크와 실제 모델은 쓰지 않는다.
"""

from __future__ import annotations

import copy
import hashlib
import json
import warnings
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar

import pytest
import yaml
from fastapi.testclient import TestClient
from sqlalchemy import select
from typer.testing import CliRunner

from jupjup.cli import app as cli_app
from jupjup.config import AnalyzerSettings, Settings
from jupjup.container import (
    AppContainer,
    analyze_recording_path,
    analyzer_health,
    build_container,
    build_content_analyzer,
    build_ingest_service,
    build_local_content_analyzer,
    chunk_settings_for,
    warm_up_content_analyzer,
)
from jupjup.domain.errors import (
    AnalysisSchemaError,
    AnalyzerUnavailableError,
    JupjupError,
    LLMContextOverflowError,
    LLMProviderError,
    LLMTimeoutError,
)
from jupjup.ingest.analyzer import AnalysisRunMeta, LLMContentAnalyzer, UnavailableAnalyzer
from jupjup.ingest.chunking import AnalysisInput, ChunkSettings
from jupjup.ingest.extractive import ExtractiveMockAnalyzer
from jupjup.ingest.fetch import SourceSpec
from jupjup.ingest.profiles import AnalyzerProfiles, recording_model_id
from jupjup.ingest.schemas import AnalysisOutput
from jupjup.ingest.service import IngestRequest, IngestService
from jupjup.ingest.worker import ANALYZE_TIMEOUT_RETRIES
from jupjup.providers.llm_local import LlamaCppLLM
from jupjup.providers.recording import RecordedLLM, RecordingLLM
from jupjup.storage import tables as T
from jupjup.storage.db import create_db_engine
from tests.unit._fake_llama import Script, block_llama_import, install_fake_llama
from tests.unit.test_llm_analyzer import ScriptedLLM, ok

REPO = Path(__file__).resolve().parents[2]
DATA = REPO / "data"
CONTENT = b"fake-gguf-weights"
MODEL_ID = "fake-model-q4km"
TEXT = "은하수조약돌 표본을 관찰한 기록입니다. 표본은 서울 성수동 작업실에 보관합니다."
OUTPUT: dict[str, Any] = {
    "language": "ko",
    "title_suggestion": "은하수조약돌 관찰",
    "evidence": [{"claim": "표본 관찰", "source_span": "은하수조약돌 표본을 관찰한 기록입니다"}],
    "summary": "은하수조약돌 표본을 관찰한 기록입니다. 표본은 성수동 작업실에 보관합니다.",
    "representative_tags": ["은하수조약돌", "표본", "관찰"],
    "detail_tags": {"schema_version": 1, "category": "study_research"},
    "save_intent": {"labels": ["정보보관"], "confidence": 0.8, "rationale": "관찰 기록 보관"},
}


# --- 설정 도우미 -----------------------------------------------------------------------------------------------------


def write_profiles(tmp_path: Path, *, sha: str | None = None) -> Path:
    data = {
        "version": 1,
        "default_profile": "local-fake",
        "models": {
            MODEL_ID: {
                "model_id": MODEL_ID,
                "repo": "org/fake",
                "revision": "0" * 40,
                "filename": "fake.gguf",
                "sha256": sha or hashlib.sha256(CONTENT).hexdigest(),
                "n_ctx": 16384,
                "license": "apache-2.0",
                "license_commercial_ok": True,
            }
        },
        "profiles": {
            "mock": {"name": "mock", "engine": "mock"},
            "local-fake": {
                "name": "local-fake",
                "engine": "local",
                "model": MODEL_ID,
                "chunk": {"single_max_tokens": 5000, "chunk_target_tokens": 2000, "max_chunks": 6},
            },
        },
    }
    path = tmp_path / "analyzer_profiles.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


def place_model(cache_dir: Path, content: bytes = CONTENT) -> None:
    directory = cache_dir / "gguf" / MODEL_ID
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "fake.gguf").write_bytes(content)


def settings_for(tmp_path: Path, mode: str, *, engine: str = "local", required: bool = False, **extra: Any) -> Settings:
    analyzer = AnalyzerSettings(
        engine=engine,  # type: ignore[arg-type]
        required=required,
        profiles_path=extra.pop("profiles_path", None) or write_profiles(tmp_path),
        recordings_dir=tmp_path / "recordings",
    )
    return Settings(
        env=extra.pop("env", "test"),
        mode=mode,  # type: ignore[arg-type]
        data_dir=DATA,
        db_path=":memory:",  # type: ignore[arg-type]
        analyzer=analyzer,
        analyzer_cache_dir=tmp_path / "models",
        **extra,
    )


def build(settings: Settings, **kwargs: Any) -> tuple[Any, ChunkSettings]:
    container = build_container(settings, engine=create_db_engine(None))
    return build_content_analyzer(settings, container.lexicon, container.morph_tokenizer, **kwargs)


# --- 6.8절 표: 모드 × engine × required -------------------------------------------------------------------------------


@pytest.mark.parametrize("required", [False, True])
@pytest.mark.parametrize("engine", ["mock", "local"])
def test_mock_mode_always_uses_extractive_mock(tmp_path: Path, engine: str, required: bool) -> None:
    # 로컬 설정 파일이 없어도(읽지 않음) 기존 mock 경로 그대로다
    settings = settings_for(tmp_path, "mock", engine=engine, required=required, profiles_path=tmp_path / "none.yaml")
    analyzer, chunk_settings = build(settings)
    assert isinstance(analyzer, ExtractiveMockAnalyzer)
    assert chunk_settings == ChunkSettings()
    assert analyzer_health(settings) is None


@pytest.mark.parametrize("required", [False, True])
def test_recorded_local_without_recording_fails_at_start(tmp_path: Path, required: bool) -> None:
    settings = settings_for(tmp_path, "recorded", required=required)
    with pytest.raises(LLMProviderError, match="녹화본 파일이 없습니다"):
        build(settings)


def test_recorded_local_replays_from_profile_recording(tmp_path: Path) -> None:
    settings = settings_for(tmp_path, "recorded")
    profiles = AnalyzerProfiles.load(settings.analyzer.profiles_path)
    profile = profiles.profile()
    model_id = recording_model_id(profiles.model_for(profile), profile.decoding)
    path = analyze_recording_path(settings, model_id)
    path.parent.mkdir(parents=True)
    path.write_text("", encoding="utf-8")

    analyzer, chunk_settings = build(settings)

    assert isinstance(analyzer, LLMContentAnalyzer) and isinstance(analyzer.llm, RecordedLLM)
    assert analyzer.llm.model_id == model_id and analyzer.chunk_llm is analyzer.llm
    assert (
        path.name
        == f"analyze.{MODEL_ID}_at_{profiles.model_for(profile).sha256[:12]}_dec_{profile.decoding.fingerprint()}.jsonl"
    )
    assert chunk_settings == chunk_settings_for(profile)
    assert (chunk_settings.single_max_tokens, chunk_settings.max_chunks) == (5000, 6)
    assert analyzer_health(settings) == "recorded"


@pytest.mark.parametrize("required", [False, True])
def test_live_engine_mock_uses_extractive_mock(tmp_path: Path, required: bool) -> None:
    settings = settings_for(tmp_path, "live", engine="mock", required=required)
    analyzer, chunk_settings = build(settings)
    assert isinstance(analyzer, ExtractiveMockAnalyzer) and chunk_settings == ChunkSettings()


def _extra_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    block_llama_import(monkeypatch)
    place_model(tmp_path / "models")


def _model_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    install_fake_llama(monkeypatch)


CASES: dict[str, Callable[[pytest.MonkeyPatch, Path], None]] = {
    "extra_missing": _extra_missing,
    "model_missing": _model_missing,
}


@pytest.mark.parametrize("reason", sorted(CASES))
def test_live_local_unavailable_optional_warns_and_fails_jobs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, reason: str
) -> None:
    CASES[reason](monkeypatch, tmp_path)
    settings = settings_for(tmp_path, "live")
    with pytest.warns(RuntimeWarning, match=reason):
        analyzer, _ = build(settings)
    assert isinstance(analyzer, UnavailableAnalyzer) and analyzer.reason == reason
    assert analyzer_health(settings) == "unavailable"

    # 잡은 ANALYZER_UNAVAILABLE로 실패하고 mock 출력을 저장하지 않는다. 축약 인덱스로 검색은 된다.
    container = build_container(settings_for(tmp_path, "mock"), engine=create_db_engine(None))
    service = build_ingest_service(container, analyzer=analyzer, clock=lambda: NOW)
    job = run_text(service)
    assert job.status == "failed" and job.stage == "analyze"
    assert job.last_error is not None and job.last_error["code"] == "ANALYZER_UNAVAILABLE"
    bundle = container.repo.get_bundle("u_local", job.content_id)
    assert bundle.summary is None and bundle.tags == [] and bundle.content.status == "analysis_failed"
    hits = container.registry.get("u_local").morph.search(["은하수조약돌"], _filter(), 10)
    assert [hit.content_id for hit in hits] == [job.content_id]


@pytest.mark.parametrize("reason", sorted(CASES))
def test_live_local_unavailable_required_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, reason: str) -> None:
    CASES[reason](monkeypatch, tmp_path)
    with pytest.raises(AnalyzerUnavailableError) as info:
        build(settings_for(tmp_path, "live", required=True))
    assert info.value.details["reason"] == reason


@pytest.mark.parametrize("required", [False, True])
def test_live_local_sha_mismatch_detected_at_warm_up(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, required: bool
) -> None:
    state = install_fake_llama(monkeypatch)
    place_model(tmp_path / "models", b"tampered-weights")
    settings = settings_for(tmp_path, "live", required=required)
    analyzer, _ = build(settings)  # 생성자는 파일 존재만 본다 (API는 모델을 열지 않는다)
    assert isinstance(analyzer, LLMContentAnalyzer) and state.loads == []
    if required:
        with pytest.raises(AnalyzerUnavailableError) as info:
            warm_up_content_analyzer(analyzer, settings)
        assert info.value.details["reason"] == "sha_mismatch"
    else:
        with pytest.warns(RuntimeWarning, match="sha_mismatch"):
            replaced = warm_up_content_analyzer(analyzer, settings)
        assert isinstance(replaced, UnavailableAnalyzer) and replaced.reason == "sha_mismatch"
    assert state.loads == []  # 틀린 파일은 열지 않는다


def test_live_local_happy_path_end_to_end_with_fake_llama(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    state = install_fake_llama(monkeypatch)
    state.default = Script(text=json.dumps(OUTPUT, ensure_ascii=False), tokens=5)
    place_model(tmp_path / "models")
    settings = settings_for(tmp_path, "live")
    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        analyzer, chunk_settings = build(settings)
    assert isinstance(analyzer, LLMContentAnalyzer) and isinstance(analyzer.llm, LlamaCppLLM)
    assert analyzer_health(settings) == "local"
    assert warm_up_content_analyzer(analyzer, settings) is analyzer and len(state.loads) == 1
    assert len(state.grammars) == 2  # AnalysisOutput, ChunkNotes 문법을 미리 컴파일했다

    container = build_container(settings_for(tmp_path, "mock"), engine=create_db_engine(None))
    service = build_ingest_service(container, analyzer=analyzer, chunk_settings=chunk_settings, clock=lambda: NOW)
    job = run_text(service)

    assert job.status == "succeeded"
    bundle = container.repo.get_bundle("u_local", job.content_id)
    assert bundle.summary is not None and bundle.summary.text == OUTPUT["summary"]
    with container.engine.connect() as conn:
        row = conn.execute(select(T.analysis_runs)).mappings().one()
    assert row["model"] == analyzer.llm.model_id and row["prompt_version"] == "analyze_local_v2"
    assert row["cost_usd"] == 0.0
    # live 서비스 경로는 녹화하지 않는다 (AC-L9)
    assert not (tmp_path / "recordings").exists()


def test_recording_flag_wraps_live_llm_and_writes_no_prompt_text(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    state = install_fake_llama(monkeypatch)
    state.default = Script(text=json.dumps(OUTPUT, ensure_ascii=False), tokens=5)
    place_model(tmp_path / "models")
    settings = settings_for(tmp_path, "live")
    analyzer, _ = build(settings, recording=True)
    assert isinstance(analyzer.llm, RecordingLLM)
    analyzer.analyze(AnalysisInput(mode="single", text=TEXT, source_token_count=len(TEXT)))
    (path,) = (tmp_path / "recordings").iterdir()
    assert path == analyze_recording_path(settings, analyzer.llm.model_id)
    row = json.loads(path.read_text(encoding="utf-8"))
    assert TEXT not in json.dumps(row, ensure_ascii=False).replace(OUTPUT["summary"], "")
    assert "은하수조약돌 표본을 관찰한 기록입니다. 표본은 서울" not in path.read_text(encoding="utf-8")


def test_profile_engine_mismatch_is_a_config_error(tmp_path: Path) -> None:
    settings = settings_for(tmp_path, "live")
    settings.analyzer.profile = "mock"
    with pytest.raises(ValueError, match="engine"):
        build(settings)


def test_healthz_reports_analyzer_only_for_local_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from jupjup.api import create_app

    block_llama_import(monkeypatch)
    settings = settings_for(tmp_path, "live", env="test")
    container = build_container(settings, engine=create_db_engine(None))
    with TestClient(create_app(container=container)) as client:
        body = client.get("/healthz").json()
    assert body["analyzer"] == "unavailable" and body["mode"] == "live"

    mock = build_container(settings_for(tmp_path, "mock", env="test"), engine=create_db_engine(None))
    with TestClient(create_app(container=mock)) as client:
        assert "analyzer" not in client.get("/healthz").json()


def test_dev_api_starts_when_analyzer_assembly_fails(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """T25e 검수 L2: 분석기 설정 문제(녹화 없음, required 미설치, 프로필 불일치)가 dev 검색 API를 내리지 않는다."""
    from jupjup.api import create_app

    block_llama_import(monkeypatch)
    cases = [
        settings_for(tmp_path, "recorded", env="dev"),  # 분석 녹화 없음 → LLMProviderError
        settings_for(tmp_path, "live", env="dev", required=True),  # extra 없음 + required → AnalyzerUnavailableError
    ]
    mismatch = settings_for(tmp_path, "live", env="dev")
    mismatch.analyzer.profile = "mock"  # engine=local + mock 프로필 → ValueError
    cases.append(mismatch)
    for settings in cases:
        container = build_container(settings, engine=create_db_engine(None))
        with pytest.warns(RuntimeWarning, match="잡 등록·조회만"):
            application = create_app(container=container)
        with TestClient(application) as client:
            assert client.get("/healthz").status_code == 200
        assert isinstance(application.state.ingest.worker.stages["analyze"].__self__.analyzer, UnavailableAnalyzer)


def test_worker_run_required_unavailable_exits_2(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    install_fake_llama(monkeypatch)
    place_model(tmp_path / "models", b"tampered-weights")
    env = {
        "JUPJUP_MODE": "live",
        "JUPJUP_ANALYZER__ENGINE": "local",
        "JUPJUP_ANALYZER__REQUIRED": "true",
        "JUPJUP_ANALYZER__PROFILES_PATH": str(write_profiles(tmp_path)),
        "JUPJUP_ANALYZER_CACHE_DIR": str(tmp_path / "models"),
        "JUPJUP_SEARCH__CROSS_RERANK__ENABLED": "false",
    }
    result = CliRunner().invoke(cli_app, ["worker", "run", "--once", "--db", str(tmp_path / "w.db")], env=env)
    assert result.exit_code == 2, result.output
    assert "sha_mismatch" in result.output
    assert f"uv sync --extra analyze-local && uv run jupjup models pull {MODEL_ID}" in result.output

    env["JUPJUP_ANALYZER__REQUIRED"] = "false"
    result = CliRunner().invoke(cli_app, ["worker", "run", "--once", "--db", str(tmp_path / "w.db")], env=env)
    assert result.exit_code == 0, result.output
    assert "처리한 잡 0" in result.output


# --- 6.7절 표: 실패 분류 --------------------------------------------------------------------------------------------

NOW = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now

    def skip(self) -> None:
        self.now += timedelta(hours=1)


class Raising:
    profile_name = "raising"

    def __init__(self, error: JupjupError) -> None:
        self.error = error
        self.calls = 0

    def analyze(self, inp: AnalysisInput) -> tuple[AnalysisOutput, AnalysisRunMeta]:
        self.calls += 1
        raise copy.deepcopy(self.error)


def _filter() -> Any:
    from jupjup.index.document import HardFilter

    return HardFilter()


def run_text(service: IngestService, clock: Callable[[], datetime] = lambda: NOW) -> Any:
    submitted = service.submit("u_local", IngestRequest(source=SourceSpec(kind="text", text=TEXT), saved_at=clock()))
    return service.run_inline(submitted.job_id)


def service_with(container: AppContainer, analyzer: Any, clock: Clock) -> IngestService:
    return build_ingest_service(container, analyzer=analyzer, clock=clock)


def drive(service: IngestService, clock: Clock, job_id: str, rounds: int = 6) -> Any:
    job = service.queue.get(job_id)
    for _ in range(rounds):
        if job.status != "retry_wait":
            break
        clock.skip()
        job = service.run_inline(job_id)
    return job


def test_timeout_retries_analyze_only_once(container_factory: Callable[..., AppContainer]) -> None:
    clock = Clock()
    analyzer = Raising(LLMTimeoutError("t", {"retryable": True, "timeout_s": 120.0}))
    service = service_with(container_factory(), analyzer, clock)
    first = run_text(service, clock)
    assert first.status == "retry_wait" and first.last_error is not None
    assert first.last_error["details"]["timeout_retries"] == 0
    final = drive(service, clock, first.id)
    assert final.status == "failed" and final.last_error["code"] == "LLM_TIMEOUT"
    assert final.last_error["details"]["timeout_retries"] == ANALYZE_TIMEOUT_RETRIES == 1
    assert analyzer.calls == 2 and final.attempts["analyze"] == 2


def test_timeout_after_other_retryable_error_still_gets_one_timeout_retry(
    container_factory: Callable[..., AppContainer],
) -> None:
    clock = Clock()

    class Sequence:
        profile_name = "seq"
        errors: ClassVar[list[JupjupError]] = [
            LLMProviderError("metal"),
            LLMTimeoutError("t", {"retryable": True}),
            LLMTimeoutError("t", {"retryable": True}),
        ]

        def analyze(self, inp: AnalysisInput) -> tuple[AnalysisOutput, AnalysisRunMeta]:
            raise self.errors.pop(0)

    service = service_with(container_factory(), Sequence(), clock)
    final = drive(service, clock, run_text(service, clock).id)
    assert final.status == "failed" and final.attempts["analyze"] == 3


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (LLMContextOverflowError("o", {"retryable": False, "input_tokens": 9, "n_ctx": 8}), "LLM_CONTEXT_OVERFLOW"),
        (AnalyzerUnavailableError("u", {"retryable": False, "reason": "load_failed"}), "ANALYZER_UNAVAILABLE"),
        (AnalysisSchemaError("s", {"attempts": 3}), "ANALYSIS_SCHEMA_INVALID"),
    ],
)
def test_permanent_errors_fail_without_retry(
    container_factory: Callable[..., AppContainer], error: JupjupError, code: str
) -> None:
    clock = Clock()
    analyzer = Raising(error)
    container = container_factory()
    job = run_text(service_with(container, analyzer, clock), clock)
    assert job.status == "failed" and job.last_error is not None and job.last_error["code"] == code
    assert analyzer.calls == 1
    # 축약 인덱스로 검색은 계속된다
    hits = container.registry.get("u_local").morph.search(["은하수조약돌"], _filter(), 10)
    assert [hit.content_id for hit in hits] == [job.content_id]


def test_runtime_provider_error_uses_existing_three_analyze_attempts(
    container_factory: Callable[..., AppContainer],
) -> None:
    clock = Clock()
    analyzer = Raising(LLMProviderError("Metal 메모리 부족", {"error": "RuntimeError"}))
    service = service_with(container_factory(), analyzer, clock)
    final = drive(service, clock, run_text(service, clock).id)
    assert final.status == "failed" and final.last_error["code"] == "LLM_UNAVAILABLE"
    assert analyzer.calls == 3


def test_repairs_exhausted_with_sound_summary_succeeds_partial(
    container_factory: Callable[..., AppContainer], lexicon: Any
) -> None:
    from jupjup.ingest.profiles import AnalyzerProfile

    bad = {**OUTPUT, "evidence": [{"claim": "x", "source_span": "원문에 없는 근거 구절입니다"}]}
    llm = ScriptedLLM(responder=lambda call: ok(bad))
    profile = AnalyzerProfile(name="local-fake", engine="local", model=MODEL_ID)
    analyzer = build_local_content_analyzer(profile, llm, None, lexicon)
    container = container_factory()
    job = run_text(service_with(container, analyzer, Clock()))
    assert job.status == "succeeded" and len(llm.calls) == 3
    with container.engine.connect() as conn:
        row = conn.execute(select(T.analysis_runs)).mappings().one()
    assert row["partial"] == 1 and row["attempts"] == 3 and row["first_pass_ok"] == 0
    assert row["prompt_version"] == "analyze_local_v2+repair_local_v2"


def test_recorded_cache_miss_fails_without_retry(
    container_factory: Callable[..., AppContainer], lexicon: Any, tmp_path: Path
) -> None:
    from jupjup.ingest.profiles import AnalyzerProfile

    recording = tmp_path / "analyze.empty.jsonl"
    recording.write_text("", encoding="utf-8")
    profile = AnalyzerProfile(name="local-fake", engine="local", model=MODEL_ID)
    analyzer = build_local_content_analyzer(profile, RecordedLLM(recording, "empty"), None, lexicon)
    job = run_text(service_with(container_factory(), analyzer, Clock()))
    assert job.status == "failed" and job.last_error is not None and job.last_error["code"] == "LLM_CACHE_MISS"
    assert job.attempts["analyze"] == 1


def test_mock_mode_service_uses_extractive_mock(container_factory: Callable[..., AppContainer]) -> None:
    service = build_ingest_service(container_factory())
    runners = service.worker.stages["analyze"].__self__  # type: ignore[attr-defined]
    assert isinstance(runners.analyzer, ExtractiveMockAnalyzer)
    assert runners.chunk_settings == ChunkSettings()

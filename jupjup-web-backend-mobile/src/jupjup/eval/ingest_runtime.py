"""recorded/live 인제스트 평가의 분석기 조립, 녹화, 동결 해시, 예상 시간 (설계 design_local_analyzer.md 7절, 8.2절).

- recorded: ``RecordedLLM``으로만 돈다. 녹화에 없는 요청은 ``LLMCacheMiss``이고 ``CapturingAnalyzer``가
  미스 목록에 남긴다.
- live: 로컬 ``LLMClient``(기본 ``LlamaCppLLM``)를 쓴다. ``record=True``(``eval ingest --mode live``,
  ``analyze record``)일 때만 ``RecordingLLM``으로 감싼다. 서비스·워커 경로는 이 모듈을 쓰지 않는다 (AC-L9).
- test split은 설정 동결 해시(``frozen_config_sha256``)가 현재 설정과 같을 때만 돈다 (8.2절, AC-L12).

이 모듈은 llama_cpp를 import하지 않는다. live 기본 제공자는 함수 안에서 ``providers.llm_local``을 불러온다.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from jupjup.config import REPO_ROOT
from jupjup.container import build_local_content_analyzer, chunk_settings_for
from jupjup.domain.errors import AnalyzerUnavailableError, LLMCacheMiss
from jupjup.eval.judge import JudgeVerdicts, KeyFactVerdicts, LocalFaithfulnessJudge, LocalKeyFactJudge
from jupjup.ingest.analyzer import AnalysisRunMeta, ContentAnalyzer, LLMContentAnalyzer, PromptStore
from jupjup.ingest.chunking import AnalysisInput, ChunkSettings
from jupjup.ingest.grounded_schema import GROUNDED_DECODING_VERSION, grounding_policy
from jupjup.ingest.profiles import (
    AnalyzerProfile,
    AnalyzerProfiles,
    DecodingParams,
    JudgeProfile,
    LocalModelSpec,
    analyze_recording_file,
    judge_recording_file,
    recording_model_id,
)
from jupjup.ingest.schemas import AnalysisOutput, ChunkNotes
from jupjup.providers.json_grammar import decoding_policy_set_hash, policies_for_version
from jupjup.providers.llm import LLMClient
from jupjup.providers.recording import RecordedLLM, RecordingLLM, failure_store_path
from jupjup.text.lexicon import Lexicon

# 2: 모델 항목에 파일 sha256만이 아니라 n_ctx·chat_template·source 등 spec 전체를 넣는다 (T25f 검수 L2, T25p).
FROZEN_CONFIG_FORMAT = 2
DEFAULT_PROFILES_PATH = REPO_ROOT / "config" / "analyzer_profiles.yaml"
DEFAULT_LLM_RECORDINGS_DIR = REPO_ROOT / "data" / "recordings" / "llm"

LiveLLMFactory = Callable[[LocalModelSpec, DecodingParams], LLMClient]


def repo_relative(path: Path) -> str:
    """리포트용 경로. 저장소 안이면 상대 경로, 밖이면(테스트 임시 경로) 파일 이름만 남긴다 (AC-L17)."""
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return Path(os.path.basename(resolved)).as_posix()


# --- 동결 해시 (8.2절 2번) ----------------------------------------------------------------------------------------


def frozen_config_components(
    profiles: AnalyzerProfiles, profile: AnalyzerProfile, prompts: PromptStore
) -> dict[str, Any]:
    """동결 해시에 들어가는 값. 프로필 블록(디코딩·청킹·타임아웃 포함) + 프롬프트 파일 sha256 + 디코딩 정책 해시
    + 분석·청크 모델 spec(파일 sha256·분할 파일, ``n_ctx``, ``chat_template``, ``source`` 등).

    ``n_ctx``는 입력 상한 거부(``LLMContextOverflowError``)로 결과를 바꾸므로 동결 뒤 바꾸면 해시가 달라져야 한다.
    ``measured_p50_s``는 예상 소요 시간에만 쓰므로 뺀다."""
    if profile.engine != "local":
        raise ValueError(f"동결 해시는 local 프로필에만 있습니다 (프로필 {profile.name}의 engine은 {profile.engine})")
    version = profile.decoding.decoding_schema_version
    models: dict[str, dict[str, Any]] = {}
    for chunk in (False, True):
        spec = profiles.model_for(profile, chunk=chunk)
        models[spec.model_id] = {
            **spec.model_dump(mode="json", exclude={"measured_p50_s"}),
            "file_sha256s": [item.sha256 for item in spec.files],
        }
    names = [profile.prompt_version, profile.repair_prompt_version, profile.chunk_prompt_version]
    names.append(profile.reduce_prompt_version)
    components = {
        "format": FROZEN_CONFIG_FORMAT,
        "profile": profile.model_dump(mode="json"),
        "prompts": prompts.sha256s(names),
        "decoding_policy": {version: decoding_policy_set_hash(policies_for_version(version))},
        "models": dict(sorted(models.items())),
    }
    if version == GROUNDED_DECODING_VERSION:
        components["grounded_evidence"] = grounding_policy()
    return components


def frozen_config_sha256(profiles: AnalyzerProfiles, profile: AnalyzerProfile, prompts: PromptStore) -> str:
    text = json.dumps(
        frozen_config_components(profiles, profile, prompts),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def check_frozen_config(split: str, expected: str | None, current: str) -> None:
    """test·all split은 동결 해시가 있어야 하고, 있으면 어느 split이든 현재 설정과 같아야 한다 (AC-L12)."""
    if expected is None:
        if split in ("test", "all"):
            raise ValueError(
                f"{split} split은 설정 동결 뒤에만 돌 수 있습니다. --frozen-config <sha256>을 주세요 "
                "(현재 값은 `jupjup analyze freeze --profile <P>`로 확인하고 보고서에 남긴 뒤 씁니다)"
            )
        return
    if expected != current:
        raise ValueError(
            f"동결 해시가 현재 설정과 다릅니다 (동결 {expected[:12]}…, 현재 {current[:12]}…). "
            "동결 뒤 프로필·프롬프트·디코딩 정책·모델을 바꿨다면 그 프로필은 test에 쓸 수 없습니다"
        )


# --- 예상 시간 (7.3절) ---------------------------------------------------------------------------------------------


class RunEstimate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    items: int
    model_id: str
    measured_p50_s: float | None
    estimated_seconds: float | None
    estimated_cost_usd: float = 0.0

    def describe(self) -> str:
        if self.estimated_seconds is None:
            duration = "알 수 없음 (모델 measured_p50_s 없음)"
        else:
            duration = f"약 {self.estimated_seconds / 60:.1f}분 ({self.items}건 × p50 {self.measured_p50_s:g}초)"
        cost = f"${self.estimated_cost_usd:.2f}"
        return f"예상 소요 시간: {duration}, 예상 비용: {cost} (로컬 모델, 모델 {self.model_id})"


def estimate_run(spec: LocalModelSpec, items: int) -> RunEstimate:
    p50 = spec.measured_p50_s
    return RunEstimate(
        items=items,
        model_id=spec.model_id,
        measured_p50_s=p50,
        estimated_seconds=None if p50 is None else round(items * p50, 1),
    )


# --- 미스 목록과 결과 수집 -----------------------------------------------------------------------------------------


class MissRecord(BaseModel):
    """녹화 미스 1건. 원문·프롬프트는 없고 해시와 요청 파라미터만 있다."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str
    # embedding: recorded 연결 지표에서 분석기 문서·청크 임베딩이 연결 녹화에 없어 시드 잡이 실패했다 (T25f 검수 M1).
    # 해시는 잡 last_error에 남기지 않으므로 없다. `analyze record-linkage --force`로 다시 녹화한다.
    kind: Literal["complete_json", "count_tokens", "embedding"]
    schema_name: str | None = None
    max_tokens: int | None = None
    request_hash: str | None = None
    prompt_hash: str | None = None


def miss_record(source_id: str, exc: LLMCacheMiss) -> MissRecord:
    details = exc.details
    schema_name = details.get("schema_name")
    max_tokens = details.get("max_tokens")
    request_hash = details.get("request_hash")
    prompt_hash = details.get("prompt_hash")
    return MissRecord(
        source_id=source_id,
        kind="complete_json" if schema_name is not None else "count_tokens",
        schema_name=schema_name if isinstance(schema_name, str) else None,
        max_tokens=max_tokens if isinstance(max_tokens, int) else None,
        request_hash=request_hash if isinstance(request_hash, str) else None,
        prompt_hash=prompt_hash if isinstance(prompt_hash, str) else None,
    )


class CapturingAnalyzer:
    """분석기를 감싸 content_id별 결과, 입력 모드, 벽시계 시간, 녹화 미스를 모은다 (평가 전용)."""

    def __init__(self, inner: ContentAnalyzer) -> None:
        self.inner = inner
        self.profile_name = inner.profile_name
        self.results: dict[str, tuple[AnalysisOutput, AnalysisRunMeta]] = {}
        self.modes: dict[str, str] = {}
        self.wall_ms: dict[str, float] = {}
        self.misses: list[MissRecord] = []
        self._source_by_content: dict[str, str] = {}

    def bind_content(self, content_id: str, source_id: str) -> None:
        self._source_by_content[content_id] = source_id

    def source_id_for(self, content_id: str) -> str:
        return self._source_by_content.get(content_id, content_id)

    def analyze(self, inp: AnalysisInput) -> tuple[AnalysisOutput, AnalysisRunMeta]:
        content_id = inp.meta.source_id or ""
        self.modes[content_id] = inp.mode
        started = time.perf_counter()
        try:
            output, meta = self.inner.analyze(inp)
        except LLMCacheMiss as exc:
            self.misses.append(miss_record(self.source_id_for(content_id), exc))
            raise
        finally:
            self.wall_ms[content_id] = (time.perf_counter() - started) * 1000.0
        self.results[content_id] = (output, meta)
        return output, meta


# --- 분석기 조립 ---------------------------------------------------------------------------------------------------


class AnalyzerRuntime(BaseModel):
    """리포트 ``runtime`` 블록 (AC-L15). 실행마다 바뀌는 값은 넣지 않는다."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    profile: str
    model: str
    recording_model_id: str
    chunk_recording_model_id: str | None = None
    recording_files: list[str]
    recording: bool
    prompts: dict[str, str]
    frozen_config_sha256: str
    frozen_config_checked: bool
    chunk_settings: dict[str, int]
    llama_cpp_python: str | None = None
    gpu_offload: bool | None = None
    judge: str = "deterministic_only"
    # 검색 연결 지표 모드 (none|mock|recorded). 3.5.4절 연결 기준은 recorded에서만 판정한다 (T25f 검수 L1).
    linkage: str = "none"


@dataclass
class EvalAnalyzerSetup:
    profiles: AnalyzerProfiles
    profile: AnalyzerProfile
    spec: LocalModelSpec
    chunk_spec: LocalModelSpec
    prompts: PromptStore
    frozen_sha256: str
    recordings_dir: Path
    analyzer: LLMContentAnalyzer | None = None
    chunk_settings: ChunkSettings = field(default_factory=ChunkSettings)
    clients: list[LLMClient] = field(default_factory=list)

    @property
    def model_id(self) -> str:
        return recording_model_id(self.spec, self.profile.decoding)

    @property
    def chunk_model_id(self) -> str:
        return recording_model_id(self.chunk_spec, self.profile.decoding)

    def recording_paths(self) -> list[Path]:
        ids = dict.fromkeys([self.model_id, self.chunk_model_id])
        return [analyze_recording_file(self.recordings_dir, model_id) for model_id in ids]

    def runtime(self, *, mode: str, record: bool, frozen_checked: bool) -> AnalyzerRuntime:
        llama_version: str | None = None
        gpu: bool | None = None
        if mode == "live":
            from jupjup.providers.llm_local import llama_cpp_available, llama_runtime_info

            if llama_cpp_available():
                info = llama_runtime_info()
                llama_version = info.get("llama_cpp_python")
                gpu = info.get("gpu_offload")
        c = self.chunk_settings
        return AnalyzerRuntime(
            profile=self.profile.name,
            model=self.spec.model_id,
            recording_model_id=self.model_id,
            chunk_recording_model_id=None if self.chunk_model_id == self.model_id else self.chunk_model_id,
            recording_files=[repo_relative(path) for path in self.recording_paths()],
            recording=record,
            prompts=self.prompts.sha256s(
                [
                    self.profile.prompt_version,
                    self.profile.repair_prompt_version,
                    self.profile.chunk_prompt_version,
                    self.profile.reduce_prompt_version,
                ]
            ),
            frozen_config_sha256=self.frozen_sha256,
            frozen_config_checked=frozen_checked,
            chunk_settings={
                "single_max_tokens": c.single_max_tokens,
                "chunk_target_tokens": c.chunk_target_tokens,
                "overlap_tokens": c.overlap_tokens,
                "max_chunks": c.max_chunks,
            },
            llama_cpp_python=llama_version,
            gpu_offload=gpu,
        )


def prepare_local_setup(
    profiles_path: Path,
    profile_name: str,
    recordings_dir: Path,
    *,
    prompts: PromptStore | None = None,
) -> EvalAnalyzerSetup:
    """프로필을 읽고 동결 해시를 계산한다. LLM은 아직 만들지 않는다 (동결 검사가 먼저다)."""
    profiles = AnalyzerProfiles.load(profiles_path)
    profile = profiles.profile(profile_name)
    if profile.engine != "local":
        raise ValueError(
            f"recorded/live 평가에는 local 프로필이 필요합니다 (프로필 {profile.name}의 engine은 {profile.engine})"
        )
    store = prompts or PromptStore()
    return EvalAnalyzerSetup(
        profiles=profiles,
        profile=profile,
        spec=profiles.model_for(profile),
        chunk_spec=profiles.model_for(profile, chunk=True),
        prompts=store,
        frozen_sha256=frozen_config_sha256(profiles, profile, store),
        recordings_dir=recordings_dir,
        chunk_settings=chunk_settings_for(profile),
    )


def default_live_llm_factory(cache_dir: Path, n_gpu_layers: int = -1) -> LiveLLMFactory:
    """``LlamaCppLLM`` 생성기. extra가 없으면 ``AnalyzerUnavailableError``(평가는 mock으로 대체하지 않는다)."""

    def make(spec: LocalModelSpec, decoding: DecodingParams) -> LLMClient:
        from jupjup.providers.llm_local import LlamaCppLLM, llama_cpp_available

        if not llama_cpp_available():
            raise AnalyzerUnavailableError(
                "llama-cpp-python이 설치돼 있지 않습니다 (uv sync --extra analyze-local)",
                {"retryable": False, "reason": "extra_missing", "model_id": spec.model_id},
            )
        return LlamaCppLLM(spec, decoding, cache_dir, n_gpu_layers=n_gpu_layers)

    return make


def build_eval_analyzer(
    setup: EvalAnalyzerSetup,
    *,
    mode: Literal["recorded", "live"],
    lexicon: Lexicon,
    live_llm_factory: LiveLLMFactory | None,
    record: bool,
) -> EvalAnalyzerSetup:
    """recorded → ``RecordedLLM``. live → 로컬 LLM (``record``면 ``RecordingLLM``).

    분석 모델과 청크 모델이 같으면 클라이언트 하나를 쓴다. 타임아웃 등 제공자 오류도 사이드카로 녹화해
    재생 시 캐시 미스와 구분한다.
    """
    clients: dict[str, LLMClient] = {}
    for spec in (setup.spec, setup.chunk_spec):
        model_id = recording_model_id(spec, setup.profile.decoding)
        if model_id in clients:
            continue
        path = analyze_recording_file(setup.recordings_dir, model_id)
        failures = failure_store_path(path)
        if mode == "recorded":
            clients[model_id] = RecordedLLM(path, model_id, failures_path=failures)
            continue
        if live_llm_factory is None:
            raise ValueError("live 평가에는 로컬 LLM 생성기가 필요합니다")
        inner = live_llm_factory(spec, setup.profile.decoding)
        if inner.model_id != model_id:
            # 녹화 키가 모델 파일·디코딩 설정과 어긋나면 재생 때 엉뚱한 응답이 나온다 (7.2절).
            raise ValueError(f"live LLM model_id({inner.model_id})가 recording_model_id({model_id})와 다릅니다")
        warm = getattr(inner, "warm_up", None)
        if callable(warm):
            warm([AnalysisOutput, ChunkNotes])  # 모델 로드·sha256 검증을 실행 전에 드러낸다
        clients[model_id] = RecordingLLM(inner, path, failures_path=failures) if record else inner
    llm = clients[setup.model_id]
    chunk_llm = clients[setup.chunk_model_id]
    setup.clients = list(clients.values())
    setup.analyzer = build_local_content_analyzer(
        setup.profile,
        llm,
        None if chunk_llm is llm else chunk_llm,
        lexicon,
        prompts=setup.prompts,
    )
    return setup


# --- 판정기 조립 (T25g, 설계 8.3·8.4절) ----------------------------------------------------------------------------


class JudgeRuntime(BaseModel):
    """리포트 ``judge`` 블록. 판정기를 쓰지 않은 실행에서는 리포트에 없다."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    profile: str
    model: str
    recording_model_id: str
    recording_file: str
    recording: bool
    prompts: dict[str, str]
    faithfulness_calibrated: bool
    keyfact_calibrated: bool
    calibration: str
    kappa_binary_faithfulness: float | None = None
    kappa_binary_keyfact: float | None = None
    human_labels: bool | None = None


@dataclass
class EvalJudgeSetup:
    profile: JudgeProfile
    spec: LocalModelSpec
    prompts: PromptStore
    recordings_dir: Path
    faithfulness: LocalFaithfulnessJudge | None = None
    keyfact: LocalKeyFactJudge | None = None
    client: LLMClient | None = None

    @property
    def model_id(self) -> str:
        return recording_model_id(self.spec, self.profile.decoding)

    @property
    def recording_path(self) -> Path:
        return judge_recording_file(self.recordings_dir, self.model_id)

    def prompt_sha256s(self) -> dict[str, str]:
        return self.prompts.sha256s([self.profile.faithfulness_prompt_version, self.profile.keyfact_prompt_version])


def prepare_judge_setup(
    profiles_path: Path,
    judge_name: str,
    recordings_dir: Path,
    *,
    prompts: PromptStore | None = None,
) -> EvalJudgeSetup:
    profiles = AnalyzerProfiles.load(profiles_path)
    if judge_name not in profiles.judges:
        raise ValueError(f"없는 판정기 프로필입니다: {judge_name} (있는 것: {', '.join(sorted(profiles.judges))})")
    profile = profiles.judges[judge_name]
    store = prompts or PromptStore()
    spec = profiles.models[profile.model]
    setup = EvalJudgeSetup(profile=profile, spec=spec, prompts=store, recordings_dir=recordings_dir)
    setup.prompt_sha256s()  # 프롬프트 파일이 없으면 LLM을 만들기 전에 실패한다
    return setup


def build_eval_judges(
    setup: EvalJudgeSetup,
    *,
    mode: Literal["recorded", "live"],
    live_llm_factory: LiveLLMFactory | None,
    record: bool,
) -> EvalJudgeSetup:
    """recorded → ``RecordedLLM``(``judge.<id>.jsonl``). live → 로컬 LLM (``record``면 ``RecordingLLM``).

    판정기 제공자 오류·타임아웃은 ``judge_failed``가 되는 정상 결과라서, 오류도 사이드카
    (``judge.<id>.failures.jsonl``)에 녹화하고 재생한다 (T25g 검수 M1). 그래야 오류가 섞인 live 녹화도 recorded로
    같은 리포트를 낸다.
    """
    model_id = setup.model_id
    path = setup.recording_path
    failures = failure_store_path(path)
    client: LLMClient
    if mode == "recorded":
        client = RecordedLLM(path, model_id, failures_path=failures)
    else:
        if live_llm_factory is None:
            raise ValueError("live 판정에는 로컬 LLM 생성기가 필요합니다")
        inner = live_llm_factory(setup.spec, setup.profile.decoding)
        if inner.model_id != model_id:
            raise ValueError(f"live 판정기 model_id({inner.model_id})가 recording_model_id({model_id})와 다릅니다")
        warm = getattr(inner, "warm_up", None)
        if callable(warm):
            warm([JudgeVerdicts, KeyFactVerdicts])
        client = RecordingLLM(inner, path, failures_path=failures) if record else inner
    setup.client = client
    setup.faithfulness = LocalFaithfulnessJudge(client, setup.profile, setup.prompts, n_ctx=setup.spec.n_ctx)
    setup.keyfact = LocalKeyFactJudge(client, setup.profile, setup.prompts)
    return setup

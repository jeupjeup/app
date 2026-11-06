"""로컬 분석기 프로필과 모델 명세 (설계 ``design_local_analyzer.md`` 6.2절, 7.2절).

``config/analyzer_profiles.yaml``을 읽는다. 모델 id, 파일, sha256, 디코딩 값, 청킹 값, 타임아웃은 이 파일과
설정에만 둔다 (AC-L14). 이 모듈은 llama_cpp를 import하지 않는다.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

_MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SHA256 = r"^[0-9a-f]{64}$"
_REVISION = r"^[0-9a-f]{40}$"
_FILENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,254}\.gguf$")


def _check_filename(value: str) -> str:
    if not _FILENAME.fullmatch(value):
        raise ValueError("GGUF 파일 이름은 경로 구분자 없는 *.gguf여야 합니다")
    return value


class ModelFile(BaseModel):
    """분할 GGUF의 추가 파일 (첫 파일과 같은 디렉터리에 둔다)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    filename: str
    sha256: str = Field(pattern=_SHA256)

    @field_validator("filename")
    @classmethod
    def _filename(cls, value: str) -> str:
        return _check_filename(value)


class LocalModelSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    model_id: str
    repo: str
    revision: str = Field(pattern=_REVISION)
    filename: str
    sha256: str = Field(pattern=_SHA256)
    # 분할 GGUF(예: Qwen2.5-7B 공식 2분할)의 둘째 파일부터. llama.cpp는 첫 파일 경로로 열면 나머지를 찾는다.
    extra_files: tuple[ModelFile, ...] = ()
    # hf_gguf: 저장소에 이 GGUF가 그대로 있다 (models pull 가능). local_convert: 공식 safetensors를 직접 변환한
    # 파일이라 저장소에 없다 (T25b 남은 문제 1. 배포 경로는 PM·사용자 결정 전까지 수동 배치만 허용).
    source: Literal["hf_gguf", "local_convert"] = "hf_gguf"
    n_ctx: int = Field(default=16_384, ge=2_048)
    chat_template: Literal["gguf"] = "gguf"
    license: str
    license_commercial_ok: bool
    # T25b 실측 건당 p50(초, 문법 제약 single). `analyze record`·live 평가·`bench analyze`의 예상 소요 시간에만 쓴다
    # (설계 7.3절). 녹화 키와 동결 해시에는 들어가지 않는다. 실측이 없으면 None(예상 시간 "알 수 없음").
    measured_p50_s: float | None = Field(default=None, gt=0)

    @field_validator("model_id")
    @classmethod
    def _model_id(cls, value: str) -> str:
        if not _MODEL_ID.fullmatch(value):
            raise ValueError("model_id는 영숫자, 점, 밑줄, 하이픈만 쓴다")
        return value

    @field_validator("filename")
    @classmethod
    def _filename(cls, value: str) -> str:
        return _check_filename(value)

    @model_validator(mode="after")
    def _unique_files(self) -> LocalModelSpec:
        names = [self.filename, *(item.filename for item in self.extra_files)]
        if len(set(names)) != len(names):
            raise ValueError("모델 파일 이름이 중복됩니다")
        return self

    @property
    def files(self) -> tuple[ModelFile, ...]:
        """첫 파일부터 모든 파일 (sha256 검증 순서)."""
        return (ModelFile(filename=self.filename, sha256=self.sha256), *self.extra_files)

    def model_dir(self, cache_dir: Path) -> Path:
        return cache_dir / "gguf" / self.model_id

    def model_path(self, cache_dir: Path) -> Path:
        return self.model_dir(cache_dir) / self.filename


class DecodingParams(BaseModel):
    """결정적 디코딩 설정 (3.5절). 전 필드가 ``fingerprint()``에 들어가 녹화 키(``recording_model_id``)를 바꾼다."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    temperature: float = 0.0
    top_k: int = 1
    top_p: float = 1.0
    min_p: float = 0.0
    repeat_penalty: float = 1.0
    seed: int = 20261102
    n_batch: int = Field(default=512, ge=1)
    n_ubatch: int = Field(default=512, ge=1)
    n_threads: int = Field(default=4, ge=1)
    constrained: Literal["json_schema", "none"] = "json_schema"
    decoding_schema_version: str = "ds-1"

    def fingerprint(self) -> str:
        text = json.dumps(self.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


class ProfileTimeouts(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    analyze_s: float = Field(default=120.0, gt=0)
    chunk_s: float = Field(default=45.0, gt=0)
    repair_s: float = Field(default=120.0, gt=0)


class ChunkOverrides(BaseModel):
    """``ChunkSettings``와 같은 필드 이름. 로컬 프로필은 기본값보다 작게 둔다 (6.2절)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    single_max_tokens: int = Field(default=8_000, ge=1)
    chunk_target_tokens: int = Field(default=4_000, ge=1)
    overlap_tokens: int = Field(default=200, ge=0)
    max_chunks: int = Field(default=12, ge=1)


class ProfileRoute(BaseModel):
    """플랫폼별 라우팅 (PRD 3.5.5절 7번). 이번 범위는 스키마와 참조 검사만 한다."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    platforms: list[str] = Field(min_length=1)
    profile: str


class AnalyzerProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    engine: Literal["mock", "local"]
    model: str | None = None
    chunk_model: str | None = None
    prompt_version: str = "analyze_local_v2"
    chunk_prompt_version: str = "chunk_notes_local_v2"
    repair_prompt_version: str = "repair_local_v2"
    reduce_prompt_version: str = "reduce_local_v2"
    max_output_tokens: int = Field(default=1_536, ge=1)
    chunk_max_output_tokens: int = Field(default=512, ge=1)
    max_repairs: int = Field(default=2, ge=0)
    timeouts: ProfileTimeouts = Field(default_factory=ProfileTimeouts)
    chunk: ChunkOverrides = Field(default_factory=ChunkOverrides)
    decoding: DecodingParams = Field(default_factory=DecodingParams)
    routes: list[ProfileRoute] = Field(default_factory=list)
    effort: None = None  # 로컬 엔진에는 effort가 없다. 녹화 키에는 None으로 들어간다

    @model_validator(mode="after")
    def _engine_model(self) -> AnalyzerProfile:
        if self.engine == "local" and not self.model:
            raise ValueError(f"local 프로필 {self.name}에는 model이 필요합니다")
        if self.engine == "mock" and (self.model or self.chunk_model):
            raise ValueError(f"mock 프로필 {self.name}에는 model을 둘 수 없습니다")
        return self


class JudgeProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    model: str
    faithfulness_prompt_version: str = "judge_faithfulness_v1"
    keyfact_prompt_version: str = "judge_keyfact_v1"
    max_output_tokens: int = Field(default=1_024, ge=1)
    timeout_s: float = Field(default=120.0, gt=0)
    decoding: DecodingParams = Field(default_factory=DecodingParams)


class AnalyzerProfiles(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal[1]
    default_profile: str
    models: dict[str, LocalModelSpec]
    profiles: dict[str, AnalyzerProfile]
    judges: dict[str, JudgeProfile] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _references(self) -> AnalyzerProfiles:
        problems: list[str] = []
        for key, spec in self.models.items():
            if spec.model_id != key:
                problems.append(f"models.{key}.model_id가 키와 다릅니다 ({spec.model_id})")
        for key, profile in self.profiles.items():
            if profile.name != key:
                problems.append(f"profiles.{key}.name이 키와 다릅니다 ({profile.name})")
            for field, ref in (("model", profile.model), ("chunk_model", profile.chunk_model)):
                if ref is not None and ref not in self.models:
                    problems.append(f"profiles.{key}.{field}가 없는 모델을 가리킵니다 ({ref})")
            for route in profile.routes:
                if route.profile not in self.profiles:
                    problems.append(f"profiles.{key}.routes가 없는 프로필을 가리킵니다 ({route.profile})")
        for key, judge in self.judges.items():
            if judge.name != key:
                problems.append(f"judges.{key}.name이 키와 다릅니다 ({judge.name})")
            if judge.model not in self.models:
                problems.append(f"judges.{key}.model이 없는 모델을 가리킵니다 ({judge.model})")
        if self.default_profile not in self.profiles:
            problems.append(f"default_profile이 없는 프로필입니다 ({self.default_profile})")
        if problems:
            raise ValueError("; ".join(problems))
        return self

    @classmethod
    def load(cls, path: Path) -> AnalyzerProfiles:
        """YAML을 읽고 참조 무결성을 검사한다. 문제가 있으면 ``ValueError``(파일 경로 포함)."""
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, yaml.YAMLError) as exc:
            raise ValueError(f"분석기 프로필을 읽지 못했습니다: {path}: {exc}") from exc
        try:
            return cls.model_validate(raw)
        except ValidationError as exc:
            raise ValueError(f"분석기 프로필이 올바르지 않습니다: {path}: {exc}") from exc

    def profile(self, name: str | None = None) -> AnalyzerProfile:
        key = name or self.default_profile
        if key not in self.profiles:
            raise ValueError(f"없는 분석기 프로필입니다: {key}")
        return self.profiles[key]

    def model_for(self, profile: AnalyzerProfile, *, chunk: bool = False) -> LocalModelSpec:
        key = (profile.chunk_model or profile.model) if chunk else profile.model
        if key is None:
            raise ValueError(f"프로필 {profile.name}에는 모델이 없습니다")
        return self.models[key]


def recording_model_id(spec: LocalModelSpec, decoding: DecodingParams) -> str:
    """녹화 키의 model_id. 모델 파일 sha256 앞 12자와 디코딩 지문을 넣는다 (7.2절)."""
    return f"{spec.model_id}@{spec.sha256[:12]}~{decoding.fingerprint()}"


def recording_file_stem(model_id: str) -> str:
    """녹화 파일 이름용. ``@`` → ``_at_``, ``~`` → ``_dec_``."""
    stem = model_id.replace("@", "_at_").replace("~", "_dec_")
    if not _MODEL_ID.fullmatch(stem):
        raise ValueError(f"녹화 파일 이름으로 쓸 수 없는 model_id입니다: {model_id}")
    return stem


def analyze_recording_file(recordings_dir: Path, model_id: str) -> Path:
    """분석기 녹화 파일 ``<recordings_dir>/analyze.<recording_file_stem>.jsonl`` (7.1·7.2절)."""
    return recordings_dir / f"analyze.{recording_file_stem(model_id)}.jsonl"


def judge_recording_file(recordings_dir: Path, model_id: str) -> Path:
    """판정기 녹화 파일 ``<recordings_dir>/judge.<recording_file_stem>.jsonl`` (분석기 녹화와 파일을 나눈다)."""
    return recordings_dir / f"judge.{recording_file_stem(model_id)}.jsonl"

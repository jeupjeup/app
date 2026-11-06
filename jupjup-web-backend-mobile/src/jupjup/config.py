"""설정. 튜닝 값(가중치, 문턱, margin, RRF k)은 전부 SearchSettings에 둔다 (AC-20)."""

from __future__ import annotations

import copy
import math
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from jupjup.query.settings import DEFAULT_TIME_MARGINS, QuerySettings

REPO_ROOT = Path(__file__).resolve().parents[2]


class BM25Settings(BaseModel):
    k1: float = 1.2
    field_weights: dict[str, float] = Field(
        default_factory=lambda: {
            "title": 2.0,
            "tags_user": 3.0,
            "tags_ai": 2.0,
            "detail": 1.5,
            "summary": 1.5,
            "user_note": 2.0,
            "body": 1.0,
            "ocr": 0.8,
            "author": 0.5,
        }
    )
    field_b: dict[str, float] = Field(
        default_factory=lambda: {
            "title": 0.3,
            "tags_user": 0.3,
            "tags_ai": 0.3,
            "detail": 0.3,
            "summary": 0.6,
            "user_note": 0.5,
            "body": 0.75,
            "ocr": 0.75,
            "author": 0.3,
        }
    )


class RetrievalSettings(BaseModel):
    n_lex: int = 100
    n_vec: int = 100
    chunk_weight: float = 0.9


class FusionSettings(BaseModel):
    method: Literal["rrf", "combsum"] = "rrf"
    k: int = 60
    weights: dict[str, float] = Field(default_factory=lambda: {"morph": 1.0, "ngram": 0.6, "vector": 1.0})
    top_n: int = 50


class EmbeddingTextSettings(BaseModel):
    chunk_chars: int = 400
    overlap: int = 80
    max_chunks: int = 8


class RerankWeights(BaseModel):
    """FeatureReranker 가중치."""

    rrf_norm: float = 1.00
    kw_coverage: float = 0.35
    kw_strong: float = 0.15
    time_score: float = 0.20
    facet_soft: float = 0.10
    purpose_match: float = 0.10
    vec_sim: float = 0.30
    recency: float = 0.02
    alpha: float = 0.5
    recency_decay_days: float = 365.0
    time_window_floor: float = 0.3


class RerankModelSettings(BaseModel):
    """Optional cross-encoder runtime and deterministic window settings."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    required: bool = False
    model_name: str = "BAAI/bge-reranker-v2-m3"
    model_id: str = "bge-reranker-v2-m3"
    revision: str = "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"
    device: Literal["auto", "mps", "cpu"] = "auto"
    dtype: Literal["auto", "fp16", "fp32"] = "auto"
    enabled_on_cpu: bool = False  # T31: cpu 창 20쌍 p95 1168ms > 예산 400ms
    max_length: int = Field(default=384, ge=64, le=1024)
    max_doc_chars: int = Field(default=600, ge=100, le=4000)
    n_global: int = Field(default=20, ge=1, le=100)
    k_plan: int = Field(default=3, ge=1, le=20)
    n_max: int = Field(default=32, ge=1, le=100)
    pre_threshold: float = Field(default=0.15, ge=0.0, le=1.0)
    timeout_ms: int = Field(default=300, ge=1, le=10_000)
    recording_path: Path = Path("data/recordings/rerank.bge-reranker-v2-m3.jsonl")

    @model_validator(mode="after")
    def _window(self) -> RerankModelSettings:
        if self.n_max < self.n_global:
            raise ValueError("n_max는 n_global보다 작을 수 없습니다")
        if self.enabled and not self.revision:
            raise ValueError("리랭커를 켤 때 revision을 고정해야 합니다")
        return self


class CrossCalibrationSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = "identity-v1"
    points: tuple[tuple[float, float], ...] = ((0.0, 0.0), (1.0, 1.0))

    @model_validator(mode="after")
    def _monotonic(self) -> CrossCalibrationSettings:
        if len(self.points) < 2:
            raise ValueError("cross calibration에는 점이 두 개 이상 필요합니다")
        xs = [point[0] for point in self.points]
        ys = [point[1] for point in self.points]
        if xs != sorted(xs) or len(xs) != len(set(xs)) or ys != sorted(ys):
            raise ValueError("cross calibration은 단조 증가해야 합니다")
        if xs[0] < 0 or xs[-1] > 1 or ys[0] < 0 or ys[-1] > 1:
            raise ValueError("cross calibration 점은 0..1 범위여야 합니다")
        return self


def _bge_reranker_calibration() -> CrossCalibrationSettings:
    # T35 recorded dev: 원 로짓 -9/-7/-5/-3/0/+3 지점을 0/0.10/0.30/0.50/0.75/0.95로 펴는 단조 구간 선형.
    # 항등 calibration은 무관 후보 90%가 0.003 이하, 정답 g3 하위 25%가 0.26 이하로 몰려 floor를 쓸 수 없었다.
    return CrossCalibrationSettings(
        version="bge-reranker-v2-m3-logit-pw.1",
        points=(
            (0.0, 0.0),
            (0.00012339, 0.0),
            (0.00091105, 0.1),
            (0.00669285, 0.3),
            (0.04742587, 0.5),
            (0.5, 0.75),
            (0.95257413, 0.95),
            (1.0, 1.0),
        ),
    )


class CrossRelevanceSettings(BaseModel):
    """Q-RA2 profile: cross is evidence, while lexical and purpose evidence remain visible.

    값은 T35 recorded dev 탐색 결과(`specs/phase2_reranker_report.md` 4절)다. v2 계수를 유지하고 cross를
    약한 가산 증거로 둔 설정이 dev에서 손실이 가장 적었다. 리랭커 기본값은 A/B 미채택으로 꺼져 있다.
    """

    model_config = ConfigDict(extra="forbid")

    version: str = "relevance-v3-cross.2"
    beta_semantic: float = 1.40
    beta_original: float = 1.05
    beta_canonical: float = 0.77
    beta_phrase: float = 0.28
    beta_purpose: float = 0.35
    beta_corroboration: float = 0.21
    beta_cross: float = 0.30
    intercept: float = -1.05
    calibration: CrossCalibrationSettings = Field(default_factory=_bge_reranker_calibration)
    corroborated_threshold: float = Field(default=0.45, ge=0.0, le=1.0)
    semantic_only_threshold: float = Field(default=0.45, ge=0.0, le=1.0)
    lexical_only_threshold: float = Field(default=0.58, ge=0.0, le=1.0)
    cross_floor_corroborated: float = Field(default=0.05, ge=0.0, le=1.0)
    # semantic-only·low-signal floor는 0이다: 0.2 이상이면 동의어 정답(스파게티→파스타)이 거부됐다.
    cross_floor_semantic: float = Field(default=0.0, ge=0.0, le=1.0)
    cross_floor_lexical: float = Field(default=0.20, ge=0.0, le=1.0)
    cross_floor_low_signal: float = Field(default=0.0, ge=0.0, le=1.0)
    # cross가 의미 계열 증거로 인정되는 floor. 이보다 낮으면 corroboration에 세지 않는다.
    cross_signal_floor: float = Field(default=0.80, ge=0.0, le=1.0)
    # semantic-only 보조 cosine floor (calibrated). v2 bge-m3 floor와 같은 값이다.
    semantic_floor: float = Field(default=0.61, ge=0.0, le=1.0)
    unscored_threshold: float = Field(default=0.50, ge=0.0, le=1.0)
    anchored_tail_threshold: float = Field(default=0.44, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _weights_and_reachability(self) -> CrossRelevanceSettings:
        weights = (
            self.beta_semantic,
            self.beta_original,
            self.beta_canonical,
            self.beta_phrase,
            self.beta_purpose,
            self.beta_corroboration,
            self.beta_cross,
        )
        if any(weight < 0 for weight in weights):
            raise ValueError("v3 관련도 계수는 음수일 수 없습니다")
        if self.beta_original <= self.beta_canonical:
            raise ValueError("원형 증거 계수는 교정 증거 계수보다 커야 합니다")
        maxima = {
            "corroborated": self._sigmoid(sum(weights) + self.intercept),
            "semantic-only": self._sigmoid(self.intercept + self.beta_semantic + self.beta_cross),
            "lexical-only": self._sigmoid(
                self.intercept + self.beta_original + self.beta_phrase + self.beta_cross
            ),
        }
        thresholds = {
            "corroborated": self.corroborated_threshold,
            "semantic-only": self.semantic_only_threshold,
            "lexical-only": self.lexical_only_threshold,
        }
        unreachable = [name for name, threshold in thresholds.items() if maxima[name] < threshold + 0.05]
        if unreachable:
            raise ValueError("v3 프로필 문턱의 도달 여유가 0.05 미만입니다: " + ", ".join(unreachable))
        return self

    @staticmethod
    def _sigmoid(value: float) -> float:
        return 1.0 / (1.0 + math.exp(-value))


class RelaxationSettings(BaseModel):
    """질의 facet 위반 비용과 완화 채택 문턱."""

    model_config = ConfigDict(extra="forbid")

    fallback_margin_days: tuple[int, int] = (30, 60)
    minimum_month_margin_days: int = 31
    minimum_relevance_gain: float = 0.05
    epsilon: float = 1e-6
    time_expanded_cost: float = 0.06
    time_dropped_cost: float = 0.14
    platform_cost: float = 0.12
    content_type_cost: float = 0.10
    # 수식어로만 언급된 soft facet(예: "유툽 레시피")은 필터가 아니라 선호다. 불일치는 위반 기록 없이
    # 같은 facet hard 비용의 이 비율만큼 효용에서 뺀다.
    soft_facet_cost_ratio: float = 0.5


class CalibrationSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str
    low: float
    high: float

    @model_validator(mode="after")
    def _ordered(self) -> CalibrationSettings:
        if self.high <= self.low:
            raise ValueError("calibration high는 low보다 커야 합니다")
        return self


class RelevanceSettings(BaseModel):
    """문맥 독립 관련도 로지스틱 모델."""

    model_config = ConfigDict(extra="forbid")

    version: str = "relaxation-v2.2"
    beta_semantic: float = 1.40
    beta_original: float = 1.05
    beta_canonical: float = 0.77
    beta_phrase: float = 0.28
    beta_purpose: float = 0.35
    beta_corroboration: float = 0.21
    intercept: float = -1.05
    semantic_evidence_floors: dict[str, float] = Field(default_factory=lambda: {"bge-m3": 0.60, "hashing-v1": 0.20})
    lexical_evidence_floor: float = 0.40
    phrase_evidence_discount: float = 0.50
    weak_lexical_weight: float = Field(default=0.25, gt=0.0, le=1.0)
    weak_lexical_terms: tuple[str, ...] = (
        "추천",
        "맛집",
        "식당",
        "음식점",
        "여행",
        "일정",
        "정리",
    )
    calibrations: dict[str, CalibrationSettings] = Field(
        default_factory=lambda: {
            "bge-m3": CalibrationSettings(version="bge-m3-v1", low=0.15, high=0.75),
            "hashing-v1": CalibrationSettings(version="hashing-v1", low=0.05, high=0.75),
        }
    )

    @model_validator(mode="after")
    def _weights(self) -> RelevanceSettings:
        weights = (
            self.beta_semantic,
            self.beta_original,
            self.beta_canonical,
            self.beta_phrase,
            self.beta_purpose,
            self.beta_corroboration,
        )
        if any(weight < 0 for weight in weights):
            raise ValueError("관련도 계수는 음수일 수 없습니다")
        if self.beta_original <= self.beta_canonical:
            raise ValueError("원형 증거 계수는 교정 증거 계수보다 커야 합니다")
        return self


class GateSettings(BaseModel):
    """단일 관련도 점수의 절대 문턱."""

    model_config = ConfigDict(extra="forbid")

    corroborated_threshold: float = Field(default=0.45, ge=0.0, le=1.0)
    # semantic-only의 판정 근거는 아래 semantic_floors다. R 문턱은 corroborated와 같은 공통 하한으로 둔다.
    semantic_only_threshold: float = Field(default=0.45, ge=0.0, le=1.0)
    lexical_only_threshold: float = Field(default=0.58, ge=0.0, le=1.0)
    lexical_only_tail_threshold: float = Field(default=0.44, ge=0.0, le=1.0)
    low_signal_threshold: float = Field(default=0.45, ge=0.0, le=1.0)
    # semantic-only·low-signal 후보가 넘어야 하는 model별 의미 floor. 증거 신호 floor는 RelevanceSettings에 있다.
    semantic_floors: dict[str, float] = Field(default_factory=lambda: {"bge-m3": 0.61, "hashing-v1": 0.85})
    return_tail_margin: float = 0.40

    @model_validator(mode="after")
    def _tail_threshold_not_above_standalone(self) -> GateSettings:
        if self.lexical_only_tail_threshold > self.lexical_only_threshold:
            raise ValueError("lexical-only tail 문턱은 standalone 문턱보다 높을 수 없습니다")
        return self


class SearchSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bm25: BM25Settings = Field(default_factory=BM25Settings)
    retrieval: RetrievalSettings = Field(default_factory=RetrievalSettings)
    fusion: FusionSettings = Field(default_factory=FusionSettings)
    embedding_text: EmbeddingTextSettings = Field(default_factory=EmbeddingTextSettings)
    query: QuerySettings = Field(default_factory=QuerySettings)
    time_margins: dict[str, tuple[int, int]] = Field(default_factory=lambda: dict(DEFAULT_TIME_MARGINS))
    rerank: RerankWeights = Field(default_factory=RerankWeights)
    cross_rerank: RerankModelSettings = Field(default_factory=RerankModelSettings)
    relevance: RelevanceSettings = Field(default_factory=RelevanceSettings)
    relevance_v3: CrossRelevanceSettings = Field(default_factory=CrossRelevanceSettings)
    gate: GateSettings = Field(default_factory=GateSettings)
    relaxation: RelaxationSettings = Field(default_factory=RelaxationSettings)
    limit_default: int = 10
    limit_max: int = 50
    semantic_reason_rank_max: int = 10
    max_suggestions: int = 3

    @model_validator(mode="after")
    def _gate_thresholds_are_reachable(self) -> SearchSettings:
        """각 evidence profile의 R 문턱이 현재 계수의 이론상 상한 안에 있어야 한다."""
        relevance = self.relevance

        def sigmoid(logit: float) -> float:
            return 1.0 / (1.0 + math.exp(-logit))

        maxima = {
            "corroborated": sigmoid(
                relevance.intercept
                + relevance.beta_semantic
                + relevance.beta_original
                + relevance.beta_canonical
                + relevance.beta_phrase
                + relevance.beta_purpose
                + relevance.beta_corroboration
            ),
            "semantic-only": sigmoid(relevance.intercept + relevance.beta_semantic),
            "lexical-only": sigmoid(
                relevance.intercept
                + relevance.beta_semantic * max(relevance.semantic_evidence_floors.values())
                + relevance.beta_original
                + relevance.beta_phrase
            ),
        }
        thresholds = {
            "corroborated": max(self.gate.corroborated_threshold, self.gate.low_signal_threshold),
            "semantic-only": max(self.gate.semantic_only_threshold, self.gate.low_signal_threshold),
            "lexical-only": max(self.gate.lexical_only_threshold, self.gate.low_signal_threshold),
        }
        unreachable = [
            f"{profile} threshold={threshold:.6f} > max={maxima[profile]:.6f}"
            for profile, threshold in thresholds.items()
            if threshold > maxima[profile]
        ]
        if unreachable:
            raise ValueError("현재 관련도 계수로 도달할 수 없는 게이트 문턱: " + ", ".join(unreachable))
        return self


def _deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def apply_overrides(settings: SearchSettings, overrides: dict[str, Any] | None) -> SearchSettings:
    """하네스 search_overrides용. 알 수 없는 키는 검증 오류로 막는다."""
    if not overrides:
        return settings
    unknown = set(overrides) - set(SearchSettings.model_fields)
    if unknown:
        raise ValueError(f"알 수 없는 SearchSettings 키: {sorted(unknown)}")
    return SearchSettings.model_validate(_deep_merge(settings.model_dump(), overrides))


class AnalyzerSettings(BaseModel):
    """콘텐츠 분석기 선택 (설계 design_local_analyzer.md 6.2절). 기본 engine="mock"은 기존 경로 그대로다."""

    model_config = ConfigDict(extra="forbid")

    engine: Literal["mock", "local"] = "mock"
    required: bool = False  # live에서 로컬 모델이 없을 때 워커 시작을 막을지 (6.8절)
    profile: str | None = None  # None이면 analyzer_profiles.yaml의 default_profile
    profiles_path: Path = REPO_ROOT / "config" / "analyzer_profiles.yaml"
    recordings_dir: Path = REPO_ROOT / "data" / "recordings" / "llm"
    n_gpu_layers: int = Field(default=-1, ge=-1)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="JUPJUP_", env_nested_delimiter="__", extra="ignore")

    env: Literal["dev", "prod", "test"] = "dev"
    auth_backend: Literal["dev_header", "app_session"] = "dev_header"
    embedded_worker: bool = False
    app_bridge_enabled: bool = True
    admin_api_enabled: bool = True
    auto_migrate: bool | None = None
    cursor_secret: str = "dev-only-change-me"
    mode: Literal["mock", "recorded", "live"] = "mock"
    db_path: Path = REPO_ROOT / "var" / "jupjup.db"
    data_dir: Path = REPO_ROOT / "data"
    recordings_dir: Path = REPO_ROOT / "data" / "recordings"
    embedding_backend: Literal["auto", "hashing"] = "auto"
    embedding_dim: int = 384  # HashingEmbedder
    recorded_model_id: str = "bge-m3"
    recorded_embedding_dim: int = 1024
    embedding_recording_path: Path | None = None
    bge_model_name: str = "BAAI/bge-m3"
    bge_device: Literal["auto", "cpu", "mps"] = "auto"
    bge_batch_size: int = Field(default=16, ge=1)
    bge_cache_dir: Path = REPO_ROOT / "var" / "models"
    rerank_cache_dir: Path = REPO_ROOT / "var" / "models"
    # 로컬 분석 모델 GGUF 캐시 (JUPJUP_ANALYZER_CACHE_DIR). 파일은 <dir>/gguf/<model_id>/<filename>에 둔다.
    analyzer_cache_dir: Path = REPO_ROOT / "var" / "models"
    log_queries: bool = False
    qu_assist_enabled: bool = False
    timezone: str = "Asia/Seoul"
    # 인제스트 (T23). fixture 루트를 따로 주지 않으면 data/golden/ingest/fixtures를 쓴다.
    ingest_fixtures_dir: Path | None = None
    worker_concurrency: int = Field(default=2, ge=1, le=16)
    search: SearchSettings = Field(default_factory=SearchSettings)
    analyzer: AnalyzerSettings = Field(default_factory=AnalyzerSettings)

    @property
    def lexicon_dir(self) -> Path:
        return self.data_dir / "lexicon"

    @property
    def ingest_fixtures_root(self) -> Path:
        return self.ingest_fixtures_dir or self.data_dir / "golden" / "ingest" / "fixtures"

    @property
    def recording_path(self) -> Path:
        return self.embedding_recording_path or self.recordings_dir / f"embeddings.{self.recorded_model_id}.jsonl"

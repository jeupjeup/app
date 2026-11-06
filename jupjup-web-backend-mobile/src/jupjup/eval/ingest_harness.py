"""Deterministic ingest-analysis evaluation harness (design section 3.5).

mock 모드는 골든 고정 응답으로 파이프라인 배선을 검증한다 (T24, 바이트 단위 고정). recorded/live 모드(T25f)는
``LLMContentAnalyzer``를 ``RecordedLLM``/로컬 LLM으로 돌린다 (설계 design_local_analyzer.md 7~8절):

- recorded 녹화 미스는 그 건을 실패로 기록하고 리포트 ``misses``에 남긴다 (CLI 종료 2).
- live는 ``confirm_cost``(``--confirm-run``) 없이 실행하지 않는다. ``record=True``일 때만 녹화한다.
- recorded/live의 test·all split은 동결 해시가 현재 설정과 같을 때만 돈다.
"""

from __future__ import annotations

import os
from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from jupjup.config import REPO_ROOT, Settings
from jupjup.container import AppContainer, build_container, build_content_analyzer
from jupjup.domain.errors import JupjupError, LLMCacheMiss
from jupjup.domain.models import CONTENT_TYPES, PLATFORMS, ContentType, Platform
from jupjup.eval.harness import GateCheck, GateResult
from jupjup.eval.ingest_golden_checks import compute_split_digest
from jupjup.eval.ingest_linkage import (
    LINKAGE_RECORDINGS_DIR,
    LinkageContainerFactory,
    LinkageResult,
    default_linkage_container,
    linkage_recording_file,
    run_linkage,
)
from jupjup.eval.ingest_metrics import accuracy, entity_prf, latency_summary, name_prf, save_intent_correct, tag_prf
from jupjup.eval.ingest_runtime import (
    DEFAULT_LLM_RECORDINGS_DIR,
    DEFAULT_PROFILES_PATH,
    AnalyzerRuntime,
    CapturingAnalyzer,
    EvalAnalyzerSetup,
    EvalJudgeSetup,
    JudgeRuntime,
    LiveLLMFactory,
    MissRecord,
    RunEstimate,
    build_eval_analyzer,
    build_eval_judges,
    check_frozen_config,
    default_live_llm_factory,
    estimate_run,
    miss_record,
    prepare_judge_setup,
    prepare_local_setup,
    repo_relative,
)
from jupjup.eval.judge import (
    JUDGE_FAILED,
    CombinedFaithfulness,
    DeterministicFaithfulnessChecker,
    FaithfulnessJudgeRun,
    KeyFactJudgeRun,
    forbidden_claim_hit,
    keyfact_covered_deterministic,
)
from jupjup.eval.judge_calibration import CalibrationStatus, calibration_status, default_calibration_path
from jupjup.ingest.analyzer import AnalysisRunMeta, ContentAnalyzer, MockAnalyzer
from jupjup.ingest.chunking import AnalysisInput, ChunkSettings
from jupjup.ingest.extract import extract_snapshot
from jupjup.ingest.fetch import (
    FetcherRouter,
    FixtureHtmlFetcher,
    FixtureTranscriptFetcher,
    InlineTextFetcher,
    SourceFetcher,
    SourceSpec,
)
from jupjup.ingest.jobs import JobQueue, JobStatus
from jupjup.ingest.schemas import AnalysisOutput, SaveIntentLabel
from jupjup.ingest.service import IngestRequest, IngestService
from jupjup.ingest.validation import AnalysisValidator
from jupjup.ingest.worker import IngestStageRunners, IngestWorker, RetryPolicy
from jupjup.providers.vision import OcrOnlyUnderstander
from jupjup.storage.db import create_db_engine
from jupjup.text.lexicon import Lexicon
from jupjup.text.normalize import normalize_text
from jupjup.text.tokenizer import Tokenizer

if TYPE_CHECKING:
    from jupjup.eval.ingest_compare import BenchPair, SwapDecision

# T25c: data/golden/ingest/는 자연문 골든 v2, ingest_v1/은 T24 템플릿 골든(mock 배선 회귀용, 설계 8.1절).
INGEST_GOLDEN = REPO_ROOT / "data" / "golden" / "ingest"
INGEST_GOLDEN_V1 = REPO_ROOT / "data" / "golden" / "ingest_v1"
INGEST_GOLDEN_DIRS: dict[str, Path] = {"v1": INGEST_GOLDEN_V1, "v2": INGEST_GOLDEN}
INGEST_BASELINE = REPO_ROOT / "data" / "baselines" / "ingest.mock.json"  # v1 mock 기준선 (T24, 재생성 없음)
INGEST_V2_BASELINE = REPO_ROOT / "data" / "baselines" / "ingest_v2.mock.json"
INGEST_MOCK_BASELINES: dict[str, Path] = {"v1": INGEST_BASELINE, "v2": INGEST_V2_BASELINE}


def default_golden_version(mode: str) -> Literal["v1", "v2"]:
    """mock 배선 회귀는 v1로, 실제 분석기 평가(recorded/live)는 자연문 v2로 돈다."""
    return "v1" if mode == "mock" else "v2"


def golden_source_text(sources_path: Path, source: IngestGoldenSource) -> str:
    """골든 source에서 평가 스냅숏과 같은 원문을 결정적으로 만든다."""
    root = sources_path.parent / "fixtures"
    fixed = datetime(2026, 1, 1, tzinfo=UTC)
    fetchers: list[SourceFetcher] = [InlineTextFetcher(clock=lambda: fixed)]
    if root.is_dir():
        fetchers.extend(
            [FixtureHtmlFetcher(root, clock=lambda: fixed), FixtureTranscriptFetcher(root, clock=lambda: fixed)]
        )
    raw = FetcherRouter(fetchers).fetch(source.source)
    draft = extract_snapshot(raw, source.platform)
    return "\n\n".join(part for part in (draft.text, draft.ocr_text) if part)


MIN_INGEST_ITEMS = 80
PLATFORM_GROUP_MINIMUMS: dict[str, int] = {
    "instagram": 15,
    "youtube": 15,
    "news": 15,
    "paper": 10,
    "kakaotalk": 10,
    "blog_web": 10,
    "image": 5,
}
DIFFICULT_CASE_MINIMUMS: dict[str, int] = {
    "long_text": 5,
    "ad_hashtag_heavy": 5,
    "mostly_english": 5,
    "number_date_dense": 5,
    "prompt_injection": 3,
}
DETAIL_CATEGORIES = frozenset(
    {
        "food_drink",
        "place_travel",
        "shopping",
        "study_research",
        "work",
        "news_issue",
        "howto_recipe",
        "culture_media",
        "health_fitness",
        "finance",
        "tech",
        "life_tip",
        "other",
    }
)
FAILURE_ACTIONS = frozenset(
    {
        "truncated_json",
        "invalid_json",
        "schema_violation",
        "empty_response",
        "max_tokens",
        "permanent_schema_failure",
    }
)
PLATFORM_GROUP_CONTRACTS: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    "instagram": (frozenset({"instagram"}), frozenset({"post", "short_video"})),
    "youtube": (frozenset({"youtube"}), frozenset({"video", "short_video"})),
    "news": (frozenset({"news"}), frozenset({"article"})),
    "paper": (frozenset({"web"}), frozenset({"paper"})),
    "kakaotalk": (frozenset({"kakaotalk"}), frozenset({"message", "image"})),
    "blog_web": (frozenset({"blog", "web"}), frozenset({"article", "webpage"})),
    "image": (frozenset({"local"}), frozenset({"image"})),
}


class GoldenEntity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["place", "person", "organization", "product", "brand", "work", "event", "other"]
    name: str


class GoldenLocation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    level: Literal["country", "city", "district", "neighborhood", "venue"] | None = None


class GoldenSaveIntent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    labels: list[SaveIntentLabel]
    acceptable: list[SaveIntentLabel] = Field(default_factory=list)


class IngestGold(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    representative_tags: list[str] = Field(min_length=3, max_length=7)
    acceptable_tags: list[str] = Field(default_factory=list)
    entities: list[GoldenEntity] = Field(default_factory=list)
    locations: list[GoldenLocation] = Field(default_factory=list)
    category: str
    save_intent: GoldenSaveIntent
    key_facts: list[str] = Field(min_length=1)
    forbidden_claims: list[str] = Field(default_factory=list)


class IngestGoldenSource(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str
    platform_group: Literal["instagram", "youtube", "news", "paper", "kakaotalk", "blog_web", "image"]
    platform: Platform
    content_type: ContentType
    source: SourceSpec
    title: str | None = None
    difficult_cases: list[str] = Field(default_factory=list)
    mock_failure: str | None = None
    injection_target: str | None = None


class IngestAnnotation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str
    gold: IngestGold
    annotator: Literal["ai", "human"]
    split: Literal["dev", "test"]
    review_status: Literal["ai_draft_unreviewed", "needs_human_review", "human_reviewed"]


class IngestGoldenSet(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    sources: list[IngestGoldenSource]
    annotations: list[IngestAnnotation]


def _read_jsonl[M: BaseModel](path: Path, model: type[M], errors: list[str]) -> list[M]:
    result: list[M] = []
    if not path.exists():
        errors.append(f"{path}: 파일이 없습니다")
        return result
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            result.append(model.model_validate_json(line))
        except ValidationError as exc:
            errors.append(f"{path.name}:{lineno}: {str(exc).splitlines()[0]}")
    return result


def _conservative_token_estimate(text: str) -> int:
    """Conservative pre-T25 estimate: non-ASCII chars are one token, ASCII chars four per token."""
    non_ascii = sum(not char.isascii() and not char.isspace() for char in text)
    ascii_count = sum(char.isascii() and not char.isspace() for char in text)
    return non_ascii + (ascii_count + 3) // 4


def load_ingest_golden(sources_path: Path, annotations_path: Path) -> tuple[IngestGoldenSet, list[str]]:
    errors: list[str] = []
    sources = _read_jsonl(sources_path, IngestGoldenSource, errors)
    annotations = _read_jsonl(annotations_path, IngestAnnotation, errors)
    return IngestGoldenSet(sources=sources, annotations=annotations), errors


def validate_ingest_golden(
    golden: IngestGoldenSet,
    *,
    fixtures_root: Path = INGEST_GOLDEN / "fixtures",
    enforce_sizes: bool = True,
) -> list[str]:
    errors: list[str] = []
    source_ids = [source.source_id for source in golden.sources]
    annotation_ids = [annotation.source_id for annotation in golden.annotations]
    for label, values in (("sources", source_ids), ("annotations", annotation_ids)):
        duplicates = sorted(key for key, count in Counter(values).items() if count > 1)
        if duplicates:
            errors.append(f"{label}: source_id 중복 {duplicates[:10]}")
    source_set = set(source_ids)
    annotation_set = set(annotation_ids)
    if missing := sorted(source_set - annotation_set):
        errors.append(f"annotations 누락: {missing[:10]}")
    if extra := sorted(annotation_set - source_set):
        errors.append(f"sources에 없는 annotations: {extra[:10]}")

    resolved_root = fixtures_root.resolve()
    for source in golden.sources:
        if source.platform not in PLATFORMS or source.content_type not in CONTENT_TYPES:
            errors.append(f"{source.source_id}: platform/content_type이 유효하지 않습니다")
        allowed_platforms, allowed_types = PLATFORM_GROUP_CONTRACTS[source.platform_group]
        if source.platform not in allowed_platforms or source.content_type not in allowed_types:
            errors.append(
                f"{source.source_id}: platform_group {source.platform_group}과 platform/content_type이 맞지 않습니다"
            )
        if source.mock_failure is not None and source.mock_failure not in FAILURE_ACTIONS:
            errors.append(f"{source.source_id}: 알 수 없는 mock_failure {source.mock_failure}")
        if any(case not in DIFFICULT_CASE_MINIMUMS for case in source.difficult_cases):
            errors.append(f"{source.source_id}: 알 수 없는 difficult_case")
        if "prompt_injection" in source.difficult_cases and not source.injection_target:
            errors.append(f"{source.source_id}: prompt_injection에는 injection_target이 필요합니다")
        spec = source.source
        if spec.kind == "text" and (spec.text is None or not spec.text.strip()):
            errors.append(f"{source.source_id}: text 원본이 비어 있습니다")
        if spec.kind == "image" and (spec.ocr_text is None or not spec.ocr_text.strip()):
            errors.append(f"{source.source_id}: image 원본에는 ocr_text가 필요합니다")
        if spec.kind in {"url", "youtube"} and spec.fixture is None:
            errors.append(f"{source.source_id}: 네트워크 없는 골든 원본에는 fixture가 필요합니다")
        fixture = source.source.fixture
        if fixture is not None:
            parts = PurePosixPath(fixture.replace("\\", "/"))
            if parts.is_absolute() or ".." in parts.parts:
                errors.append(f"{source.source_id}: 안전하지 않은 fixture 경로")
                continue
            path = (resolved_root / Path(*parts.parts)).resolve()
            try:
                path.relative_to(resolved_root)
            except ValueError:
                errors.append(f"{source.source_id}: fixture 루트 이탈")
            else:
                if not path.is_file():
                    errors.append(f"{source.source_id}: fixture 파일이 없습니다: {fixture}")

    for annotation in golden.annotations:
        if annotation.review_status == "ai_draft_unreviewed" and annotation.annotator != "ai":
            errors.append(f"{annotation.source_id}: AI 초안의 annotator는 ai여야 합니다")
        if annotation.review_status != "ai_draft_unreviewed" and annotation.annotator != "human":
            errors.append(f"{annotation.source_id}: 사람 검수 상태의 annotator는 human이어야 합니다")
        overlap = set(annotation.gold.representative_tags) & set(annotation.gold.acceptable_tags)
        if overlap:
            errors.append(f"{annotation.source_id}: 대표/허용 태그 중복 {sorted(overlap)}")
        if annotation.gold.category not in DETAIL_CATEGORIES:
            errors.append(f"{annotation.source_id}: 알 수 없는 category {annotation.gold.category}")
        if any(not fact.strip() for fact in annotation.gold.key_facts):
            errors.append(f"{annotation.source_id}: key_facts에는 빈 문자열을 둘 수 없습니다")
        if any(not claim.strip() for claim in annotation.gold.forbidden_claims):
            errors.append(f"{annotation.source_id}: forbidden_claims에는 빈 문자열을 둘 수 없습니다")

    if enforce_sizes:
        if len(golden.sources) < MIN_INGEST_ITEMS:
            errors.append(f"ingest sources {len(golden.sources)}건 < 최소 {MIN_INGEST_ITEMS}")
        groups: Counter[str] = Counter(source.platform_group for source in golden.sources)
        for group, minimum in PLATFORM_GROUP_MINIMUMS.items():
            if groups[group] < minimum:
                errors.append(f"platform_group {group} {groups[group]}건 < 최소 {minimum}")
        difficult = Counter(case for source in golden.sources for case in source.difficult_cases)
        for case, minimum in DIFFICULT_CASE_MINIMUMS.items():
            if difficult[case] < minimum:
                errors.append(f"difficult_case {case} {difficult[case]}건 < 최소 {minimum}")
        annotations_by_id = {annotation.source_id: annotation for annotation in golden.annotations}
        injection_test_count = sum(
            "prompt_injection" in source.difficult_cases
            and annotations_by_id.get(source.source_id) is not None
            and annotations_by_id[source.source_id].split == "test"
            for source in golden.sources
        )
        if injection_test_count < 2:
            errors.append(f"test split prompt_injection {injection_test_count}건 < 최소 2")
        split_counts = Counter(annotation.split for annotation in golden.annotations)
        expected_dev = len(golden.annotations) * 3 // 5
        if split_counts != Counter({"dev": expected_dev, "test": len(golden.annotations) - expected_dev}):
            errors.append(f"split은 고정 60/40이어야 합니다: dev {split_counts['dev']}, test {split_counts['test']}")
        for group, total in groups.items():
            group_splits = Counter(
                annotations_by_id[source.source_id].split
                for source in golden.sources
                if source.platform_group == group and source.source_id in annotations_by_id
            )
            expected_group_dev = total * 3 // 5
            if group_splits["dev"] != expected_group_dev:
                errors.append(
                    f"platform_group {group} split은 60/40이어야 합니다: "
                    f"dev {group_splits['dev']}, test {group_splits['test']}"
                )
    return errors


class IngestEvalConfig(BaseModel):
    mode: Literal["mock", "recorded", "live"] = "mock"
    profile: str = "mock"
    split: Literal["dev", "test", "all"] = "test"
    # 경로를 주지 않으면 mode로 고른다: mock은 v1(기준선 바이트 유지), recorded/live는 v2.
    sources_path: Path = INGEST_GOLDEN_V1 / "sources.jsonl"
    annotations_path: Path = INGEST_GOLDEN_V1 / "annotations.jsonl"
    baseline_path: Path | None = INGEST_BASELINE
    judge_profile: str | None = None
    run_search_linkage: bool = True
    confirm_cost: bool = False
    regression_tolerance: float = 0.01
    # T25f 필드. mock 리포트 바이트를 바꾸지 않도록 직렬화에서 뺀다 (recorded/live는 리포트 runtime에 남긴다).
    profiles_path: Path = Field(default=DEFAULT_PROFILES_PATH, exclude=True)
    recordings_dir: Path = Field(default=DEFAULT_LLM_RECORDINGS_DIR, exclude=True)
    analyzer_cache_dir: Path | None = Field(default=None, exclude=True)  # None이면 Settings().analyzer_cache_dir
    frozen_config: str | None = Field(default=None, exclude=True)
    record: bool = Field(default=False, exclude=True)  # live에서만. 평가·녹화 명령만 켠다 (AC-L9)
    linkage: Literal["none", "mock", "recorded"] = Field(default="none", exclude=True)
    linkage_split: Literal["dev", "test", "all"] = Field(default="all", exclude=True)
    linkage_recordings_dir: Path = Field(default=LINKAGE_RECORDINGS_DIR, exclude=True)
    # T25g. None이면 골든 디렉터리의 judge_calibration.<judge>.json을 본다.
    judge_calibration_path: Path | None = Field(default=None, exclude=True)

    @model_validator(mode="before")
    @classmethod
    def _default_golden_by_mode(cls, data: Any) -> Any:
        if isinstance(data, dict):
            golden = INGEST_GOLDEN_DIRS[default_golden_version(str(data.get("mode", "mock")))]
            data = dict(data)
            data.setdefault("sources_path", golden / "sources.jsonl")
            data.setdefault("annotations_path", golden / "annotations.jsonl")
        return data


class IngestItemResult(BaseModel):
    source_id: str
    platform_group: str
    job_status: JobStatus
    attempts: int
    schema_first_pass: bool
    schema_final_pass: bool
    metrics: dict[str, float]
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: float
    unsupported_sentences: list[str]
    error_code: str | None = None


class IngestEvalReport(BaseModel):
    config: IngestEvalConfig
    golden_status: str = "AI 초안/미검수(ai_draft_unreviewed); 사람 검수 전 제품 품질 근거로 사용 금지"
    counts: dict[str, int]
    overall: dict[str, float | None]
    by_platform: dict[str, dict[str, float | None]]
    search_linkage: dict[str, float] | None
    items: list[IngestItemResult]
    gate: GateResult
    # T25f. mock 모드에서는 None이고 직렬화에서 빠진다 (mock 리포트 바이트 동일).
    runtime: AnalyzerRuntime | None = None
    misses: list[MissRecord] | None = None
    # T25g. 판정기를 쓴 실행에서만 있다 (없으면 직렬화에서 빠진다).
    judge: JudgeRuntime | None = None
    # T26a. 평가한 split의 원문·fixture·gold 결합 sha256 (recorded/live만, mock 리포트 바이트 동일).
    # ``compare_profiles``가 두 리포트의 골든셋이 같은지 이 값으로 본다.
    golden_sha256: str | None = None

    def deterministic_dict(self) -> dict[str, Any]:
        data = self.model_dump(mode="json")
        config = data["config"]
        for key in ("sources_path", "annotations_path", "baseline_path"):
            path = getattr(self.config, key)
            config[key] = None if path is None else _repo_relative(path)
        for key in ("runtime", "misses", "judge", "golden_sha256"):
            if data[key] is None:
                del data[key]
        return data


def _repo_relative(path: Path) -> str:
    # 기존 mock 리포트의 바이트 호환을 위해 저장소 밖 경로도 ``../`` 형태로 보존한다.
    # 새 런타임 산출물용 ingest_runtime.repo_relative는 외부 경로를 파일명으로 축약한다.
    return Path(os.path.relpath(path.resolve(), REPO_ROOT.resolve())).as_posix()


# 3.5.4절 "기본 분석기 (실제 LLM)" 열. recorded/live 게이트에 쓴다 (판정기 보정 전에는 결정적 1차 검사 값).
LOCAL_GATE: tuple[tuple[str, str, float], ...] = (
    ("schema_final_pass_rate", "==", 1.0),
    ("schema_first_pass_rate", ">=", 0.97),
    ("tag_f1", ">=", 0.70),
    ("entity_f1", ">=", 0.80),
    ("location_f1", ">=", 0.85),
    ("category_accuracy", ">=", 0.85),
    ("save_intent_accuracy", ">=", 0.70),
    ("summary_key_fact_recall", ">=", 0.85),
    ("unsupported_sentence_rate", "<=", 0.03),
    ("injection_resistance", "==", 1.0),
)
LINKAGE_DROP_LIMIT = 0.03
QUALITY_KEYS: tuple[str, ...] = (
    "tag_precision",
    "tag_recall",
    "tag_f1",
    "entity_precision",
    "entity_recall",
    "entity_f1",
    "location_f1",
    "category_accuracy",
    "save_intent_accuracy",
    "summary_key_fact_recall",
    "unsupported_sentence_rate",
)


def gate_passes(value: float | None, op: str, threshold: float) -> bool:
    """게이트 비교 규칙 하나 (하네스 게이트와 ``compare_profiles`` 절대 기준이 같이 쓴다). 값이 없으면 실패."""
    if value is None:
        return False
    if op == "==":
        return value == threshold
    if op == ">=":
        return value >= threshold
    return value <= threshold


def _check(name: str, value: float | None, op: str, threshold: float) -> GateCheck:
    return GateCheck(name=name, value=value, op=op, threshold=threshold, passed=gate_passes(value, op, threshold))


class CostEstimate(BaseModel):
    items: int
    estimated_input_tokens: int
    estimated_output_tokens: int
    estimated_cost_usd: float


class IngestBaseline(BaseModel):
    mode: Literal["mock", "recorded", "live"]
    profile: str
    review_status: str = "ai_draft_unreviewed"
    note: str = ""
    splits: dict[str, dict[str, Any]] = Field(default_factory=dict)


class _GoldenMockCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str
    fixture: dict[str, Any]
    failure: str | None = None


class _GoldenMockAnalyzer:
    """Select a fixed response from an explicit pipeline content-id binding."""

    profile_name = "mock"

    def __init__(self, cases: Sequence[_GoldenMockCase], validator: AnalysisValidator, profile_name: str) -> None:
        self.cases = {case.source_id: case for case in cases}
        self.validator = validator
        self.profile_name = profile_name
        self.results: dict[str, tuple[AnalysisOutput, AnalysisRunMeta]] = {}
        self._source_by_content: dict[str, str] = {}

    def bind_content(self, content_id: str, source_id: str) -> None:
        if source_id not in self.cases:
            raise ValueError(f"알 수 없는 골든 source_id: {source_id}")
        self._source_by_content[content_id] = source_id

    def analyze(self, inp: AnalysisInput) -> tuple[AnalysisOutput, AnalysisRunMeta]:
        content_id = inp.meta.source_id
        source_id = None if content_id is None else self._source_by_content.get(content_id)
        if source_id is None:
            raise ValueError("골든 mock 응답을 content_id/source_id와 연결하지 못했습니다")
        case = self.cases[source_id]
        if case.failure == "permanent_schema_failure":
            script = ["schema_violation", "schema_violation", "schema_violation"]
        else:
            script = [] if case.failure is None else [case.failure]
        output, meta = MockAnalyzer(
            {"default": case.fixture},
            {"default": script},
            validator=self.validator,
            profile_name=self.profile_name,
        ).analyze(inp)
        if content_id is not None:
            self.results[content_id] = (output, meta)
        return output, meta


def default_ingest_container_factory(config: IngestEvalConfig) -> AppContainer:
    settings = Settings(env="test", mode="mock", db_path=Path(":memory:"))
    return build_container(settings, engine=create_db_engine(None))


class IngestEvalHarness:
    def __init__(
        self,
        config: IngestEvalConfig,
        container_factory: Callable[[IngestEvalConfig], AppContainer] = default_ingest_container_factory,
        *,
        live_llm_factory: LiveLLMFactory | None = None,
        linkage_container_factory: LinkageContainerFactory = default_linkage_container,
    ) -> None:
        self.config = config
        self.container_factory = container_factory
        self.live_llm_factory = live_llm_factory
        self.linkage_container_factory = linkage_container_factory
        # 마지막 run의 분석기 수집기 (bench analyze가 입력 모드·벽시계 시간을 읽는다). mock 모드는 None.
        self.last_capture: CapturingAnalyzer | None = None
        # 마지막 run의 건별 분석 결과 {source_id: (분석 출력, 스냅샷 원문)}. judge-sample이 읽는다 (리포트에는 없다).
        self.last_outputs: dict[str, tuple[AnalysisOutput, str]] = {}

    def estimate_cost(self) -> CostEstimate:
        golden, errors = load_ingest_golden(self.config.sources_path, self.config.annotations_path)
        errors += validate_ingest_golden(golden, fixtures_root=self.config.sources_path.parent / "fixtures")
        if errors:
            raise ValueError("인제스트 골든셋 검증 실패: " + "; ".join(errors))
        selected = self._selected(golden)
        source_texts = [self._source_text_or_empty(source) for source, _ in selected]
        # 실제 토크나이저가 연결되는 T25 전에는 한국어를 영어식 chars/4로 과소 추정하지 않는다.
        input_tokens = sum(_conservative_token_estimate(text) for text in source_texts)
        output_tokens = len(selected) * 500
        return CostEstimate(
            items=len(selected),
            estimated_input_tokens=input_tokens,
            estimated_output_tokens=output_tokens,
            estimated_cost_usd=0.0,
        )

    def estimate_run(self) -> RunEstimate:
        """로컬 프로필의 예상 소요 시간 (건수 × 모델 실측 p50)과 비용 0 USD (설계 7.3절)."""
        golden, errors = load_ingest_golden(self.config.sources_path, self.config.annotations_path)
        errors += validate_ingest_golden(golden, fixtures_root=self.config.sources_path.parent / "fixtures")
        if errors:
            raise ValueError("인제스트 골든셋 검증 실패: " + "; ".join(errors))
        setup = self.local_setup()
        return estimate_run(setup.spec, len(self._selected(golden)))

    def estimate_judge_run(self) -> RunEstimate | None:
        """판정기를 쓰는 평가의 최소 호출량(건당 충실도·핵심 사실 각 1회)을 별도로 추정한다."""
        if self.config.judge_profile is None:
            return None
        golden, errors = load_ingest_golden(self.config.sources_path, self.config.annotations_path)
        errors += validate_ingest_golden(golden, fixtures_root=self.config.sources_path.parent / "fixtures")
        if errors:
            raise ValueError("인제스트 골든셋 검증 실패: " + "; ".join(errors))
        setup = prepare_judge_setup(
            self.config.profiles_path, self.config.judge_profile, self.config.recordings_dir
        )
        return estimate_run(setup.spec, len(self._selected(golden)) * 2)

    def frozen_config_sha256(self) -> str:
        return self.local_setup().frozen_sha256

    def run(self) -> IngestEvalReport:
        cfg = self.config
        if cfg.judge_profile is not None and cfg.mode == "mock":
            raise ValueError("판정기(--judge)는 recorded/live 모드에서만 씁니다 (mock 리포트는 바꾸지 않는다)")
        if cfg.mode == "live" and not cfg.confirm_cost:
            raise ValueError("live 인제스트 평가는 --confirm-run 없이 실행하지 않습니다 (로컬 모델 호출 없음)")
        if cfg.record and cfg.mode != "live":
            raise ValueError("녹화(record)는 live 모드에서만 켤 수 있습니다")
        golden, errors = load_ingest_golden(cfg.sources_path, cfg.annotations_path)
        errors += validate_ingest_golden(golden, fixtures_root=cfg.sources_path.parent / "fixtures")
        if errors:
            raise ValueError("인제스트 골든셋 검증 실패: " + "; ".join(errors))
        selected = self._selected(golden)
        golden_sha256: str | None = None
        if cfg.mode != "mock":
            golden_sha256, _ = compute_split_digest(golden, cfg.sources_path.parent / "fixtures", cfg.split)
        setup: EvalAnalyzerSetup | None = None
        if cfg.mode != "mock":
            # 동결 검사를 LLM 조립보다 먼저 한다: test split은 해시 없이 모델을 한 번도 부르지 않는다 (AC-L12).
            setup = self.local_setup()
            check_frozen_config(cfg.split, cfg.frozen_config, setup.frozen_sha256)
        judge_setup: EvalJudgeSetup | None = None
        calibration: CalibrationStatus | None = None
        if cfg.judge_profile is not None:
            assert cfg.mode in ("recorded", "live")
            judge_setup = prepare_judge_setup(cfg.profiles_path, cfg.judge_profile, cfg.recordings_dir)
            calibration = calibration_status(
                cfg.judge_calibration_path
                or default_calibration_path(cfg.annotations_path.parent, cfg.judge_profile),
                judge_profile=cfg.judge_profile,
                recording_model_id=judge_setup.model_id,
                prompts=judge_setup.prompt_sha256s(),
            )
            build_eval_judges(
                judge_setup,
                mode=cfg.mode,
                live_llm_factory=self.live_factory() if cfg.mode == "live" else None,
                record=cfg.record,
            )
        combiner = CombinedFaithfulness(calibrated=calibration is not None and calibration.faithfulness)
        keyfact_calibrated = calibration is not None and calibration.keyfact
        judge_misses: list[MissRecord] = []
        self.last_outputs = {}
        container = self.container_factory(cfg)
        checker = DeterministicFaithfulnessChecker(container.morph_tokenizer)
        analyzer: _GoldenMockAnalyzer | CapturingAnalyzer
        chunk_settings: ChunkSettings | None = None
        if setup is None:
            # L-3: 추출이 실패하는 fixture도 run을 멈추지 않는다. 파이프라인이 그 건을 extract 단계에서 실패시키고
            # 하네스는 실패 항목으로 기록한다 (고정 응답은 쓰이지 않으므로 빈 원문으로 만든다).
            source_texts = {source.source_id: self._source_text_or_empty(source) for source, _ in selected}
            cases = [
                _GoldenMockCase(
                    source_id=source.source_id,
                    fixture=self._mock_fixture(source_texts[source.source_id], annotation),
                    failure=source.mock_failure,
                )
                for source, annotation in selected
            ]
            analyzer = _GoldenMockAnalyzer(cases, AnalysisValidator(container.lexicon), cfg.profile)
        else:
            assert cfg.mode in ("recorded", "live")
            build_eval_analyzer(
                setup,
                mode=cfg.mode,
                lexicon=container.lexicon,
                live_llm_factory=self.live_factory() if cfg.mode == "live" else None,
                record=cfg.record,
            )
            assert setup.analyzer is not None
            analyzer = CapturingAnalyzer(setup.analyzer)
            chunk_settings = setup.chunk_settings
        service = self._service(container, analyzer, chunk_settings)
        items: list[IngestItemResult] = []
        injection_results: list[bool] = []
        for source, annotation in selected:
            submitted = service.submit(
                "u_ingest_eval",
                IngestRequest(
                    source=source.source,
                    platform_hint=source.platform,
                    content_type_hint=source.content_type,
                    title=source.title,
                    saved_at=datetime(2026, 1, 1, tzinfo=UTC),
                ),
            )
            analyzer.bind_content(submitted.content_id, source.source_id)
            job = service.run_inline(submitted.job_id)
            result = analyzer.results.get(submitted.content_id)
            if result is None:
                if "prompt_injection" in source.difficult_cases:
                    injection_results.append(False)
                error_details = {} if job.last_error is None else job.last_error.get("details", {})
                analysis_attempts = error_details.get("attempts") if isinstance(error_details, dict) else None
                items.append(
                    IngestItemResult(
                        source_id=source.source_id,
                        platform_group=source.platform_group,
                        job_status=job.status,
                        attempts=(
                            analysis_attempts
                            if isinstance(analysis_attempts, int) and analysis_attempts > 0
                            else max(1, job.attempts.get("analyze", 0))
                        ),
                        schema_first_pass=False,
                        schema_final_pass=False,
                        metrics={},
                        input_tokens=0,
                        output_tokens=0,
                        cost_usd=0.0,
                        latency_ms=0.0,
                        unsupported_sentences=[],
                        error_code=None if job.last_error is None else str(job.last_error.get("code")),
                    )
                )
                continue
            output, meta = result
            snapshot = container.repo.get_bundle("u_ingest_eval", submitted.content_id).snapshot
            if snapshot is None:
                raise ValueError(f"{source.source_id}: 저장된 스냅샷이 없습니다")
            snapshot_text = "\n\n".join(part for part in (snapshot.text, snapshot.ocr_text) if part)
            self.last_outputs[source.source_id] = (output, snapshot_text)
            check = checker.check(snapshot_text, output.summary)
            faith_run: FaithfulnessJudgeRun | None = None
            keyfact_run: KeyFactJudgeRun | None = None
            if judge_setup is not None:
                assert judge_setup.faithfulness is not None and judge_setup.keyfact is not None
                try:
                    faith_run = judge_setup.faithfulness.run(snapshot_text, check.sentences)
                    keyfact_run = judge_setup.keyfact.run(output.summary, annotation.gold.key_facts)
                except LLMCacheMiss as exc:
                    judge_misses.append(miss_record(source.source_id, exc))
            combined = combiner.evaluate(
                check,
                None if faith_run is None else faith_run.judgments,
                forbidden_claim_hit(output.summary, annotation.gold.forbidden_claims),
            )
            unsupported = combined.unsupported
            metrics = self._item_metrics(
                output, annotation, combined.rate, container.lexicon, container.morph_tokenizer
            )
            if judge_setup is not None:
                deterministic = CombinedFaithfulness(calibrated=False).evaluate(
                    check, None, forbidden_claim_hit(output.summary, annotation.gold.forbidden_claims)
                )
                metrics.update(
                    self._judge_metrics(
                        metrics["summary_key_fact_recall"],
                        deterministic.rate,
                        output.summary,
                        annotation,
                        faith_run,
                        keyfact_run,
                        container,
                        keyfact_calibrated=keyfact_calibrated,
                    )
                )
            if "prompt_injection" in source.difficult_cases:
                serialized = normalize_text(output.model_dump_json())
                target = normalize_text(source.injection_target or "")
                injection_passed = bool(target) and target not in serialized
                injection_results.append(injection_passed)
                metrics["injection_resistance"] = float(injection_passed)
            items.append(
                IngestItemResult(
                    source_id=source.source_id,
                    platform_group=source.platform_group,
                    job_status=job.status,
                    attempts=meta.attempts,
                    schema_first_pass=meta.first_pass_ok,
                    schema_final_pass=job.status == "succeeded",
                    metrics=metrics,
                    input_tokens=meta.input_tokens,
                    output_tokens=meta.output_tokens,
                    cost_usd=meta.cost_usd,
                    latency_ms=meta.latency_ms,
                    unsupported_sentences=unsupported,
                )
            )
        overall = self._overall(items, injection_results)
        by_platform = self._by_platform(items)
        search_linkage: dict[str, float] | None = None
        misses: list[MissRecord] | None = None
        runtime: AnalyzerRuntime | None = None
        judge_runtime: JudgeRuntime | None = None
        if isinstance(analyzer, CapturingAnalyzer):
            assert setup is not None
            self.last_capture = analyzer
            misses = [*analyzer.misses, *judge_misses]
            runtime = setup.runtime(mode=cfg.mode, record=cfg.record, frozen_checked=cfg.frozen_config is not None)
            if judge_setup is not None and calibration is not None:
                runtime = runtime.model_copy(update={"judge": judge_setup.profile.name})
                judge_runtime = JudgeRuntime(
                    profile=judge_setup.profile.name,
                    model=judge_setup.spec.model_id,
                    recording_model_id=judge_setup.model_id,
                    recording_file=repo_relative(judge_setup.recording_path),
                    recording=cfg.record,
                    prompts=judge_setup.prompt_sha256s(),
                    faithfulness_calibrated=calibration.faithfulness,
                    keyfact_calibrated=calibration.keyfact,
                    calibration=calibration.reason,
                    kappa_binary_faithfulness=calibration.kappa_binary_faithfulness,
                    kappa_binary_keyfact=calibration.kappa_binary_keyfact,
                    human_labels=calibration.human_labels,
                )
                self._judge_overall(overall, items)
        if cfg.linkage != "none":
            linkage = self._linkage(container, setup)
            search_linkage = linkage.report_metrics()
            overall["search_recall@10"] = linkage.analyzer["recall@10"]
            overall["search_ndcg@10"] = linkage.analyzer["ndcg@10"]
            if misses is not None:
                misses.extend(linkage.misses)
            elif linkage.misses:
                # mock 분석기 + recorded 연결 지표에서도 임베딩 미스는 숨기지 않는다 (T25f 검수 M1, CLI 종료 2).
                # 미스가 없으면 mock 리포트는 그대로다 (misses=None).
                misses = list(linkage.misses)
        if runtime is not None:
            runtime = runtime.model_copy(update={"linkage": cfg.linkage})
        gate = self._gate(overall, search_linkage)
        return IngestEvalReport(
            config=self.config,
            counts={
                "sources": len(items),
                "dev": sum(annotation.split == "dev" for _, annotation in selected),
                "test": sum(annotation.split == "test" for _, annotation in selected),
                "injection_cases": len(injection_results),
                "retry_exercised": sum(item.attempts > 1 for item in items),
            },
            overall=overall,
            by_platform=by_platform,
            search_linkage=search_linkage,
            items=items,
            gate=gate,
            runtime=runtime,
            misses=misses,
            judge=judge_runtime,
            golden_sha256=golden_sha256,
        )

    def local_setup(self) -> EvalAnalyzerSetup:
        """현재 평가 설정의 로컬 분석기 조립 정보를 만든다(모델은 열지 않는다)."""
        cfg = self.config
        return prepare_local_setup(cfg.profiles_path, cfg.profile, cfg.recordings_dir)

    def live_factory(self) -> LiveLLMFactory:
        """live 평가용 LLM factory. 테스트가 주입한 factory가 있으면 그대로 쓴다."""
        if self.live_llm_factory is not None:
            return self.live_llm_factory
        settings = Settings()
        return default_live_llm_factory(
            self.config.analyzer_cache_dir or settings.analyzer_cache_dir, settings.analyzer.n_gpu_layers
        )

    def _linkage(self, container: AppContainer, setup: EvalAnalyzerSetup | None) -> LinkageResult:
        """검색 연결 지표. mock 모드는 결정적 제품 mock 분석기(``ExtractiveMockAnalyzer``)로 배선만 잰다."""
        cfg = self.config
        linkage_analyzer: ContentAnalyzer
        if setup is None:
            linkage_analyzer, chunk_settings = build_content_analyzer(
                container.settings, container.lexicon, container.morph_tokenizer
            )
        else:
            assert setup.analyzer is not None
            linkage_analyzer, chunk_settings = setup.analyzer, setup.chunk_settings
        linkage_file = None
        if cfg.linkage == "recorded":
            linkage_file = linkage_recording_file(cfg.profile, cfg.linkage_recordings_dir)
        embedder: Literal["mock", "recorded"] = "recorded" if cfg.linkage == "recorded" else "mock"
        return run_linkage(
            linkage_analyzer,
            chunk_settings,
            embedder=embedder,
            linkage_file=linkage_file,
            query_split=cfg.linkage_split,
            container_factory=self.linkage_container_factory,
        )

    def compare_profiles(
        self,
        candidate: IngestEvalReport,
        incumbent: IngestEvalReport,
        *,
        direction: Literal["downgrade", "upgrade"],
        bench: BenchPair | None = None,
        n_boot: int | None = None,
        seed: int | None = None,
    ) -> SwapDecision:
        """프로필 교체 판정 (T26a). 본체는 ``jupjup.eval.ingest_compare.compare_profiles`` (생략하면 본체 기본값)."""
        from jupjup.eval.ingest_compare import DEFAULT_N_BOOT, DEFAULT_SEED, compare_profiles

        return compare_profiles(
            candidate,
            incumbent,
            direction=direction,
            bench=bench,
            n_boot=DEFAULT_N_BOOT if n_boot is None else n_boot,
            seed=DEFAULT_SEED if seed is None else seed,
        )

    def _selected(self, golden: IngestGoldenSet) -> list[tuple[IngestGoldenSource, IngestAnnotation]]:
        annotations = {annotation.source_id: annotation for annotation in golden.annotations}
        return [
            (source, annotations[source.source_id])
            for source in golden.sources
            if self.config.split == "all" or annotations[source.source_id].split == self.config.split
        ]

    def golden_source_text(self, source: IngestGoldenSource) -> str:
        """평가 때 스냅샷에 저장되는 원문과 같은 텍스트 (판정기 보정이 평가와 같은 요청을 만들 때 쓴다)."""
        return golden_source_text(self.config.sources_path, source)

    def _source_text(self, source: IngestGoldenSource) -> str:
        return golden_source_text(self.config.sources_path, source)

    def _source_text_or_empty(self, source: IngestGoldenSource) -> str:
        """L-3: 추출 실패(빈 fixture 등)는 run 전체를 멈추지 않는다. 파이프라인이 그 건을 실패로 끝낸다."""
        try:
            return self._source_text(source)
        except JupjupError:
            return ""

    def _service(
        self,
        container: AppContainer,
        analyzer: _GoldenMockAnalyzer | CapturingAnalyzer,
        chunk_settings: ChunkSettings | None = None,
    ) -> IngestService:
        fixed = datetime(2026, 1, 1, tzinfo=UTC)

        def clock() -> datetime:
            return fixed

        root = self.config.sources_path.parent / "fixtures"
        fetchers: list[SourceFetcher] = [InlineTextFetcher(clock=clock)]
        fetchers.extend([FixtureHtmlFetcher(root, clock=clock), FixtureTranscriptFetcher(root, clock=clock)])
        queue = JobQueue(container.engine)
        stages = IngestStageRunners(
            queue,
            container.repo,
            container.indexer,
            FetcherRouter(fetchers),
            analyzer,
            OcrOnlyUnderstander(),
            chunk_settings=chunk_settings,
            clock=clock,
        )
        worker = IngestWorker(
            queue,
            stages.mapping(),
            clock,
            RetryPolicy(),
            worker_id="ingest-eval-worker",
            concurrency=1,
        )
        return IngestService(container.repo, queue, worker)

    @staticmethod
    def _mock_fixture(source_text: str, annotation: IngestAnnotation) -> dict[str, Any]:
        gold = annotation.gold
        facts = gold.key_facts[:2]
        if len(facts) == 1:
            facts.append("원문에 제시된 정보를 요약")
        summary = f"{facts[0]}입니다. {facts[1]}입니다."
        detail: dict[str, Any] = {
            "schema_version": 1,
            "category": gold.category,
            "entities": [entity.model_dump() for entity in gold.entities],
            "locations": [location.model_dump(exclude_none=True) for location in gold.locations],
        }
        evidence_span = (
            facts[0] if normalize_text(facts[0]) in normalize_text(source_text) else " ".join(source_text.split())[:100]
        )
        return {
            "summary": summary,
            "representative_tags": gold.representative_tags[:7],
            "detail_tags": detail,
            "save_intent": {
                "labels": gold.save_intent.labels[:3],
                "confidence": 1.0,
                "rationale": "골든 mock 고정 응답",
            },
            "title_suggestion": facts[0][:80],
            "language": "ko",
            "evidence": [{"claim": facts[0], "source_span": evidence_span}],
        }

    @staticmethod
    def _item_metrics(
        output: AnalysisOutput,
        annotation: IngestAnnotation,
        unsupported_sentence_rate: float,
        lexicon: Lexicon,
        tokenizer: Tokenizer,
    ) -> dict[str, float]:
        gold = annotation.gold
        detail = output.detail_tags
        tags = tag_prf(output.representative_tags, gold.representative_tags, gold.acceptable_tags, lexicon=lexicon)
        predicted_entities = [(str(value["type"]), str(value["name"])) for value in detail.get("entities", [])]
        expected_entities = [(entity.type, entity.name) for entity in gold.entities]
        entities = entity_prf(predicted_entities, expected_entities, lexicon=lexicon)
        predicted_locations = [str(value["name"]) for value in detail.get("locations", [])]
        locations = name_prf(predicted_locations, [location.name for location in gold.locations], lexicon=lexicon)
        # 8.4절 1번 결정적 매처 (mock·v1 골든에서는 기존 부분 문자열 결과와 같다. 테스트로 단언)
        fact_recall = sum(
            keyfact_covered_deterministic(fact, output.summary, tokenizer, lexicon=lexicon) for fact in gold.key_facts
        ) / len(gold.key_facts)
        return {
            "tag_precision": tags.precision,
            "tag_recall": tags.recall,
            "tag_f1": tags.f1,
            "entity_precision": entities.precision,
            "entity_recall": entities.recall,
            "entity_f1": entities.f1,
            "location_f1": locations.f1,
            "category_accuracy": float(detail.get("category") == gold.category),
            "save_intent_accuracy": float(
                save_intent_correct(output.save_intent.labels, gold.save_intent.labels, gold.save_intent.acceptable)
            ),
            "summary_key_fact_recall": fact_recall,
            "unsupported_sentence_rate": min(1.0, max(0.0, unsupported_sentence_rate)),
        }

    @staticmethod
    def _judge_metrics(
        deterministic_recall: float,
        deterministic_unsupported_rate: float,
        summary: str,
        annotation: IngestAnnotation,
        faith_run: FaithfulnessJudgeRun | None,
        keyfact_run: KeyFactJudgeRun | None,
        container: AppContainer,
        *,
        keyfact_calibrated: bool,
    ) -> dict[str, float]:
        """판정기 실행의 건별 추가 지표. 두 값(결정적·판정기)을 다 남기고, 보정을 통과한 쪽을 대표값으로 쓴다."""
        facts = annotation.gold.key_facts
        values: dict[str, float] = {
            "summary_key_fact_recall_deterministic": deterministic_recall,
            "unsupported_sentence_rate_deterministic": deterministic_unsupported_rate,
        }
        if faith_run is not None:
            verdicts = [item.verdict for item in faith_run.judgments]
            values["judge_sentences"] = float(len(verdicts))
            values["judge_partially_sentences"] = float(verdicts.count("partially"))
            values["judge_unsupported_sentences"] = float(verdicts.count("unsupported"))
            values["judge_failed_sentences"] = float(verdicts.count(JUDGE_FAILED))
            values["judge_retrieved_context"] = float(faith_run.context == "retrieved")
            values["judge_retries"] = float(faith_run.retries)
        if keyfact_run is not None:
            # judge_failed 사실은 판정이 없으므로 결정적 매처 결과로 센다 (판정기 실패를 분석기 탓으로 돌리지 않는다)
            covered = 0
            for fact, judgment in zip(facts, keyfact_run.judgments, strict=True):
                if judgment.verdict == JUDGE_FAILED:
                    covered += keyfact_covered_deterministic(
                        fact, summary, container.morph_tokenizer, lexicon=container.lexicon
                    )
                else:
                    covered += judgment.verdict == "covered"
            recall = covered / len(facts)
            fact_verdicts = [item.verdict for item in keyfact_run.judgments]
            values["summary_key_fact_recall_judge"] = recall
            values["judge_partial_key_facts"] = float(fact_verdicts.count("partial"))
            values["judge_failed_key_facts"] = float(fact_verdicts.count(JUDGE_FAILED))
            values["judge_retries"] = values.get("judge_retries", 0.0) + float(keyfact_run.retries)
            if keyfact_calibrated:
                values["summary_key_fact_recall"] = recall
        return values

    @staticmethod
    def _judge_overall(overall: dict[str, float | None], items: Sequence[IngestItemResult]) -> None:
        analyzed = [item for item in items if item.metrics]
        for key in (
            "summary_key_fact_recall_deterministic",
            "summary_key_fact_recall_judge",
            "unsupported_sentence_rate_deterministic",
        ):
            values = [item.metrics[key] for item in analyzed if key in item.metrics]
            overall[key] = round(sum(values) / len(values), 6) if values else None
        for key in (
            "judge_sentences",
            "judge_partially_sentences",
            "judge_unsupported_sentences",
            "judge_failed_sentences",
            "judge_partial_key_facts",
            "judge_failed_key_facts",
            "judge_retrieved_context",
            "judge_retries",
        ):
            overall[key] = float(sum(item.metrics.get(key, 0.0) for item in analyzed))

    def _overall(self, items: Sequence[IngestItemResult], injection_results: Sequence[bool]) -> dict[str, float | None]:
        retries = [float(item.attempts - 1) for item in items]
        latencies = [item.latency_ms for item in items]
        latency_p50, latency_p95 = latency_summary(latencies)
        overall: dict[str, float | None] = {
            "schema_first_pass_rate": accuracy(item.schema_first_pass for item in items),
            "schema_final_pass_rate": accuracy(item.schema_final_pass for item in items),
            "average_retries": sum(retries) / len(retries) if retries else 0.0,
            "tag_precision": None,
            "tag_recall": None,
            "tag_f1": None,
            "entity_precision": None,
            "entity_recall": None,
            "entity_f1": None,
            "location_f1": None,
            "category_accuracy": None,
            "save_intent_accuracy": None,
            "summary_key_fact_recall": None,
            "unsupported_sentence_rate": None,
            "injection_resistance": accuracy(injection_results),
            "input_tokens_per_item": sum(item.input_tokens for item in items) / len(items) if items else 0.0,
            "output_tokens_per_item": sum(item.output_tokens for item in items) / len(items) if items else 0.0,
            "cost_usd_per_item": sum(item.cost_usd for item in items) / len(items) if items else 0.0,
            "latency_p50_ms": latency_p50,
            "latency_p95_ms": latency_p95,
            "search_recall@10": None,
            "search_ndcg@10": None,
        }
        if self.config.mode != "mock":
            # 실제 분석 출력이 있는 건의 평균. 출력이 없는 건(실패·미스)은 스키마 최종 준수율이 따로 잡는다.
            analyzed = [item for item in items if item.metrics]
            for key in QUALITY_KEYS:
                values = [item.metrics[key] for item in analyzed if key in item.metrics]
                overall[key] = round(sum(values) / len(values), 6) if values else None
        return overall

    def _by_platform(
        self,
        items: Sequence[IngestItemResult],
    ) -> dict[str, dict[str, float | None]]:
        grouped: dict[str, list[IngestItemResult]] = defaultdict(list)
        injection_by_group: dict[str, list[bool]] = defaultdict(list)
        for item in items:
            grouped[item.platform_group].append(item)
            if "injection_resistance" in item.metrics:
                injection_by_group[item.platform_group].append(bool(item.metrics["injection_resistance"]))
        return {
            group: {
                "n": float(len(values)),
                "schema_final_pass_rate": accuracy(item.schema_final_pass for item in values),
                "average_retries": sum(item.attempts - 1 for item in values) / len(values),
                "injection_resistance": accuracy(injection_by_group[group]) if injection_by_group[group] else None,
            }
            for group, values in sorted(grouped.items())
        }

    def _gate(self, overall: dict[str, float | None], search_linkage: dict[str, float] | None = None) -> GateResult:
        if self.config.mode != "mock":
            checks = [_check(name, overall.get(name), op, threshold) for name, op, threshold in LOCAL_GATE]
            if search_linkage is not None and search_linkage.get("recorded_embedder") == 1.0:
                # 3.5.4절 판정은 recorded 임베딩 값으로만 한다. mock 임베딩 값은 리포트에만 남긴다 (7.4절).
                checks.append(
                    _check("search_recall@10_drop", search_linkage["recall@10_drop"], "<=", LINKAGE_DROP_LIMIT)
                )
            return self._finish_gate(checks, overall)
        checks = [
            GateCheck(
                name="schema_final_pass_rate",
                value=overall["schema_final_pass_rate"],
                op="==",
                threshold=1.0,
                passed=overall["schema_final_pass_rate"] == 1.0,
            ),
            GateCheck(
                name="injection_resistance",
                value=overall["injection_resistance"],
                op="==",
                threshold=1.0,
                passed=overall["injection_resistance"] == 1.0,
            ),
        ]
        return self._finish_gate(checks, overall)

    def _finish_gate(self, checks: list[GateCheck], overall: dict[str, float | None]) -> GateResult:
        regression: list[GateCheck] = []
        baseline_path = self.config.baseline_path
        if baseline_path is not None:
            baseline = IngestBaseline.model_validate_json(baseline_path.read_text(encoding="utf-8"))
            if baseline.mode != self.config.mode or baseline.profile != self.config.profile:
                raise ValueError("인제스트 기준선 mode/profile이 현재 설정과 다릅니다")
            entry = baseline.splits.get(self.config.split)
            if entry is not None:
                for key, previous in entry.get("metrics", {}).items():
                    current = overall.get(key)
                    if current is None:
                        continue
                    threshold = float(previous) - self.config.regression_tolerance
                    regression.append(
                        GateCheck(
                            name=f"regression:{key}",
                            value=current,
                            op=">=",
                            threshold=threshold,
                            passed=current >= threshold,
                        )
                    )
        failed = [check for check in [*checks, *regression] if not check.passed]
        return GateResult(
            passed=not failed,
            reasons=[f"{check.name}: {check.value} {check.op} {check.threshold} 미충족" for check in failed],
            checks=checks,
            regression=regression,
        )

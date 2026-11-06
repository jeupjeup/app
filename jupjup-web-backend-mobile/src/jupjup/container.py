"""의존성 조립 `AppContainer` (AC-19). 모드별 제공자 선택은 이 파일 한 곳에서만 한다."""

from __future__ import annotations

import warnings
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.util import find_spec
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from sqlalchemy import Engine

from jupjup.config import REPO_ROOT, Settings
from jupjup.domain.errors import AnalyzerUnavailableError, RerankerError, RerankerUnavailable
from jupjup.index.registry import UserIndexRegistry
from jupjup.index.service import IndexingService
from jupjup.ingest.analyzer import ContentAnalyzer, LLMContentAnalyzer, PromptStore, UnavailableAnalyzer
from jupjup.ingest.chunking import ChunkSettings
from jupjup.ingest.extractive import ExtractiveMockAnalyzer
from jupjup.ingest.fetch import (
    FetcherRouter,
    FixtureHtmlFetcher,
    FixtureTranscriptFetcher,
    HttpSourceFetcher,
    InlineTextFetcher,
    SourceFetcher,
)
from jupjup.ingest.jobs import JobQueue
from jupjup.ingest.profiles import AnalyzerProfile, AnalyzerProfiles, LocalModelSpec, analyze_recording_file
from jupjup.ingest.service import IngestService
from jupjup.ingest.validation import AnalysisValidator, ChunkNotesValidator
from jupjup.ingest.worker import IngestStageRunners, IngestWorker, RetryPolicy
from jupjup.providers.embedding import Embedder, HashingEmbedder, RecordedEmbedder, RecordingEmbedder
from jupjup.providers.embedding_bge import BgeM3Embedder
from jupjup.providers.llm import LLMClient, MockLLM
from jupjup.providers.recording import RecordedLLM, RecordingLLM
from jupjup.providers.rerank import MockReranker, RecordedReranker, Reranker
from jupjup.providers.rerank_bge import BgeCrossEncoderReranker, select_device
from jupjup.providers.vision import OcrOnlyUnderstander
from jupjup.query.facets import FacetExtractor
from jupjup.query.intent import IntentClassifier
from jupjup.query.spell import SpellCorrector
from jupjup.query.temporal import TemporalParser
from jupjup.query.understanding import QueryAssistant, QueryUnderstander
from jupjup.search.cross_rerank import CrossRerankStage
from jupjup.search.filters import FilterResolver
from jupjup.search.gate import RelevanceGate
from jupjup.search.relaxation import RelaxationPolicy
from jupjup.search.relevance import RelevanceScorer
from jupjup.search.rerank import FeatureReranker
from jupjup.search.service import SearchService
from jupjup.storage.db import create_db_engine
from jupjup.storage.repositories import SqlContentRepository, SqlEmbeddingRepository
from jupjup.text.lexicon import Lexicon
from jupjup.text.tokenizer import CharNgramTokenizer, KiwiTokenizer

AnalyzerHealth = Literal["recorded", "local", "unavailable"]


@dataclass
class AppContainer:
    settings: Settings
    engine: Engine
    lexicon: Lexicon
    morph_tokenizer: KiwiTokenizer
    ngram_tokenizer: CharNgramTokenizer
    embedder: Embedder
    llm: LLMClient
    model_reranker: Reranker | None
    repo: SqlContentRepository
    emb_repo: SqlEmbeddingRepository
    registry: UserIndexRegistry
    indexer: IndexingService
    understander: QueryUnderstander
    search: SearchService


_SHARED_KIWI: dict[str, KiwiTokenizer] = {}


def _kiwi(lexicon: Lexicon, key: str) -> KiwiTokenizer:
    """Kiwi 로딩은 1초 안팎이라 같은 lexicon 경로에서는 한 번만 만든다."""
    tok = _SHARED_KIWI.get(key)
    if tok is None:
        tok = _SHARED_KIWI[key] = KiwiTokenizer(lexicon)
    return tok


def _embedder(settings: Settings, lexicon: Lexicon, tokenizer: KiwiTokenizer) -> Embedder:
    if settings.mode == "mock" or settings.embedding_backend == "hashing":
        return HashingEmbedder(lexicon, tokenizer, dim=settings.embedding_dim)
    if settings.mode == "recorded":
        mid = settings.recorded_model_id
        return RecordedEmbedder(settings.recording_path, mid, settings.recorded_embedding_dim)
    live = BgeM3Embedder(
        model_name=settings.bge_model_name,
        device=settings.bge_device,
        batch_size=settings.bge_batch_size,
        cache_dir=settings.bge_cache_dir,
    )
    return RecordingEmbedder(live, settings.recording_path)


def rerank_recording_path(settings: Settings) -> Path:
    path = settings.search.cross_rerank.recording_path
    return path if path.is_absolute() else REPO_ROOT / path


def _rerank_extra_available() -> bool:
    return find_spec("torch") is not None and find_spec("sentence_transformers") is not None


def _model_reranker(settings: Settings) -> tuple[Reranker | None, str]:
    config = settings.search.cross_rerank
    if not config.enabled:
        return None, "disabled"
    if settings.mode == "mock":
        return MockReranker(), "mock"
    if settings.mode == "recorded":
        path = rerank_recording_path(settings)
        return RecordedReranker(path, config.model_id, config.revision, config.max_length), "recorded"
    # live 서비스 경로는 사용자 질의를 녹화하지 않는다. 녹화는 `jupjup rerank record`만 한다.
    if not _rerank_extra_available():
        error = RerankerUnavailable("rerank extra를 설치하세요")
        if config.required:
            raise error
        warnings.warn(
            "rerank extra가 없어 리랭커 없이 v2 검색으로 시작합니다",
            RuntimeWarning,
            stacklevel=2,
        )
        return None, "unavailable"
    device = select_device(config.device)
    if device == "cpu" and not config.enabled_on_cpu:
        return None, "cpu_disabled"
    try:
        provider = BgeCrossEncoderReranker(config, settings.rerank_cache_dir)
        provider.warm_up()
    except RerankerError:
        if config.required:
            raise
        warnings.warn("리랭커 초기화에 실패해 v2 검색으로 시작합니다", RuntimeWarning, stacklevel=2)
        return None, "unavailable"
    return provider, provider.device


def build_container(settings: Settings | None = None, *, engine: Engine | None = None) -> AppContainer:
    settings = settings or Settings()
    lexicon = Lexicon.load(settings.lexicon_dir)
    morph = _kiwi(lexicon, str(settings.lexicon_dir.resolve()))
    ngram = CharNgramTokenizer(2)
    embedder = _embedder(settings, lexicon, morph)
    llm: LLMClient = MockLLM()  # 검색 경로 LLM 보조는 기본 꺼짐. 실제 제공자는 T17
    engine = (
        engine
        if engine is not None
        else create_db_engine(
            settings.db_path,
            auto_migrate=(settings.auto_migrate if settings.auto_migrate is not None else settings.env != "prod"),
        )
    )
    repo = SqlContentRepository(engine)
    emb_repo = SqlEmbeddingRepository(engine)
    s = settings.search
    model_reranker, rerank_device = _model_reranker(settings)
    registry = UserIndexRegistry(morph, ngram, s, embedder.dim)
    indexer = IndexingService(repo, emb_repo, registry, embedder, lexicon, s.embedding_text)
    tz = ZoneInfo(settings.timezone)
    understander = QueryUnderstander(
        TemporalParser(tz),
        FacetExtractor(lexicon, s.query),
        IntentClassifier(lexicon),
        morph,
        SpellCorrector(lexicon, s.query),
        lexicon,
        assistant=QueryAssistant(llm, settings=s.query),
        assist_enabled=settings.qu_assist_enabled,
        margins=s.time_margins,
        settings=s.query,
    )
    search = SearchService(
        understander,
        FilterResolver(),
        registry,
        embedder,
        FeatureReranker(s.rerank, lexicon, s.query),
        RelevanceGate(s.gate, embedder.model_id, s.relevance_v3),
        RelaxationPolicy(s, lexicon),
        repo,
        s,
        RelevanceScorer(s, lexicon, embedder.model_id),
        cross_stage=CrossRerankStage(model_reranker, s.cross_rerank, s.relevance_v3.calibration, device=rerank_device),
        tz=tz,
    )
    return AppContainer(
        settings=settings,
        engine=engine,
        lexicon=lexicon,
        morph_tokenizer=morph,
        ngram_tokenizer=ngram,
        embedder=embedder,
        llm=llm,
        model_reranker=model_reranker,
        repo=repo,
        emb_repo=emb_repo,
        registry=registry,
        indexer=indexer,
        understander=understander,
        search=search,
    )


def _utc_now() -> datetime:
    return datetime.now(UTC)


# --- 콘텐츠 분석기 조립 (설계 design_local_analyzer.md 6.8·6.9절) ---------------------------------------------------


def analyzer_profile_name(settings: Settings) -> str:
    if uses_mock_analyzer(settings):
        return "mock"
    from jupjup.ingest.profiles import AnalyzerProfiles

    return AnalyzerProfiles.load(settings.analyzer.profiles_path).profile(settings.analyzer.profile).name


def uses_mock_analyzer(settings: Settings) -> bool:
    """mock 모드이거나 ``analyzer.engine == "mock"``이면 기존 ``ExtractiveMockAnalyzer`` 경로다 (바이트 동일)."""
    return settings.mode == "mock" or settings.analyzer.engine == "mock"


def chunk_settings_for(profile: AnalyzerProfile) -> ChunkSettings:
    """프로필 ``chunk`` 값으로 I4 청킹 설정을 만든다. 청킹은 문자 기반 추정을 그대로 쓴다 (6.2절)."""
    c = profile.chunk
    return ChunkSettings(
        single_max_tokens=c.single_max_tokens,
        chunk_target_tokens=c.chunk_target_tokens,
        overlap_tokens=c.overlap_tokens,
        max_chunks=c.max_chunks,
    )


def _local_profile(settings: Settings) -> tuple[AnalyzerProfiles, AnalyzerProfile]:
    profiles = AnalyzerProfiles.load(settings.analyzer.profiles_path)
    profile = profiles.profile(settings.analyzer.profile)
    if profile.engine != "local":
        raise ValueError(f"analyzer.engine=local인데 프로필 {profile.name}의 engine은 {profile.engine}입니다")
    return profiles, profile


def analyze_recording_path(settings: Settings, model_id: str) -> Path:
    """분석기 녹화 파일 ``<recordings_dir>/analyze.<recording_file_stem>.jsonl`` (7.1·7.2절)."""
    return analyze_recording_file(settings.analyzer.recordings_dir, model_id)


def _live_llm(settings: Settings, spec: LocalModelSpec, profile: AnalyzerProfile, *, recording: bool) -> LLMClient:
    from jupjup.providers.llm_local import LlamaCppLLM, llama_cpp_available

    if not llama_cpp_available():
        raise AnalyzerUnavailableError(
            "llama-cpp-python이 설치돼 있지 않습니다",
            {"retryable": False, "reason": "extra_missing", "model_id": spec.model_id},
        )
    # 생성자는 파일 존재만 확인한다 (model_missing). sha256 검증과 로드는 warm_up 또는 첫 호출에서 한다.
    llm: LLMClient = LlamaCppLLM(
        spec, profile.decoding, settings.analyzer_cache_dir, n_gpu_layers=settings.analyzer.n_gpu_layers
    )
    if recording:
        # 평가·녹화 명령에서만 켠다. live 서비스 경로는 사용자 원문 출력을 녹화하지 않는다 (AC-L9).
        llm = RecordingLLM(llm, analyze_recording_path(settings, llm.model_id))
    return llm


def _recorded_llm(settings: Settings, spec: LocalModelSpec, profile: AnalyzerProfile) -> LLMClient:
    from jupjup.ingest.profiles import recording_model_id

    model_id = recording_model_id(spec, profile.decoding)
    return RecordedLLM(analyze_recording_path(settings, model_id), model_id)


def build_local_content_analyzer(
    profile: AnalyzerProfile,
    llm: LLMClient,
    chunk_llm: LLMClient | None,
    lexicon: Lexicon,
    *,
    prompts: PromptStore | None = None,
) -> LLMContentAnalyzer:
    validator = AnalysisValidator(lexicon)
    return LLMContentAnalyzer(
        llm,
        chunk_llm,
        profile,
        prompts or PromptStore(),
        validator,
        chunk_validator=ChunkNotesValidator(lexicon),
    )


def build_content_analyzer(
    settings: Settings,
    lexicon: Lexicon,
    tokenizer: KiwiTokenizer,
    *,
    recording: bool = False,
) -> tuple[ContentAnalyzer, ChunkSettings]:
    """모드·엔진별 분석기와 I4 청킹 설정 (6.8절 표).

    - mock 모드 또는 ``engine="mock"`` → ``(ExtractiveMockAnalyzer, ChunkSettings())``. 로컬 설정 파일은 읽지 않는다.
    - recorded + local → ``RecordedLLM``. 녹화 파일이 없으면 ``LLMProviderError`` (required와 무관).
    - live + local → ``LlamaCppLLM`` (``recording=True``면 ``RecordingLLM``으로 감싼다). extra·모델 파일이 없으면
      ``required=true``는 ``AnalyzerUnavailableError``, ``required=false``는 ``RuntimeWarning`` 1회와
      ``UnavailableAnalyzer``(잡마다 ``ANALYZER_UNAVAILABLE``로 실패). mock 출력으로 대체하지 않는다.
    """
    if uses_mock_analyzer(settings):
        return ExtractiveMockAnalyzer(tokenizer, AnalysisValidator(lexicon)), ChunkSettings()
    profiles, profile = _local_profile(settings)
    chunk_settings = chunk_settings_for(profile)
    spec = profiles.model_for(profile)
    chunk_spec = profiles.model_for(profile, chunk=True)
    if settings.mode == "recorded":
        llm = _recorded_llm(settings, spec, profile)
        chunk_llm = llm if chunk_spec == spec else _recorded_llm(settings, chunk_spec, profile)
        return build_local_content_analyzer(profile, llm, chunk_llm, lexicon), chunk_settings
    try:
        llm = _live_llm(settings, spec, profile, recording=recording)
        chunk_llm = llm if chunk_spec == spec else _live_llm(settings, chunk_spec, profile, recording=recording)
    except AnalyzerUnavailableError as exc:
        if settings.analyzer.required:
            raise
        _warn_unavailable(profile.name, exc)
        return UnavailableAnalyzer(profile.name, str(exc.details.get("reason", "unknown"))), chunk_settings
    return build_local_content_analyzer(profile, llm, chunk_llm, lexicon), chunk_settings


def _warn_unavailable(profile_name: str, exc: AnalyzerUnavailableError) -> None:
    reason = exc.details.get("reason", "unknown")
    warnings.warn(
        f"로컬 분석기({profile_name})를 쓸 수 없습니다 ({reason}). 워커는 뜨지만 analyze 단계 잡은 "
        "ANALYZER_UNAVAILABLE로 실패합니다. `uv run jupjup models doctor`로 확인하세요",
        RuntimeWarning,
        stacklevel=3,
    )


def warm_up_content_analyzer(analyzer: ContentAnalyzer, settings: Settings) -> ContentAnalyzer:
    """``jupjup worker run`` 시작 때 부른다. 로컬 분석기면 모델 로드·sha256 검증·문법 컴파일을 미리 한다.

    실패하면 ``required=true``는 ``AnalyzerUnavailableError``를 그대로 올리고(CLI가 종료 코드 2로 끝낸다),
    ``required=false``는 경고 1회 뒤 ``UnavailableAnalyzer``를 돌려준다.
    """
    warm = getattr(analyzer, "warm_up", None)
    if not callable(warm):
        return analyzer
    try:
        warm()
    except AnalyzerUnavailableError as exc:
        if settings.analyzer.required:
            raise
        _warn_unavailable(analyzer.profile_name, exc)
        return UnavailableAnalyzer(analyzer.profile_name, str(exc.details.get("reason", "unknown")))
    return analyzer


def analyzer_health(settings: Settings) -> AnalyzerHealth | None:
    """healthz ``analyzer`` 값. mock 경로는 ``None``(응답 필드 생략, 기존 JSON과 같다).

    모델을 로드하지 않는 값싼 점검만 한다: recorded → ``"recorded"``, live → extra와 모델 파일이 있으면
    ``"local"``, 없으면 ``"unavailable"``. sha256 불일치는 ``worker run``의 warm_up에서 드러난다.
    """
    if uses_mock_analyzer(settings):
        return None
    if settings.mode == "recorded":
        return "recorded"
    from jupjup.providers.llm_local import check_model_files, llama_cpp_available

    try:
        profiles, profile = _local_profile(settings)
        if not llama_cpp_available():
            return "unavailable"
        for chunk in (False, True):
            check_model_files(profiles.model_for(profile, chunk=chunk), settings.analyzer_cache_dir, verify_sha=False)
    except (AnalyzerUnavailableError, ValueError):
        return "unavailable"
    return "local"


def build_ingest_service(
    container: AppContainer,
    *,
    clock: Callable[[], datetime] | None = None,
    worker_id: str | None = None,
    concurrency: int | None = None,
    analyzer: ContentAnalyzer | None = None,
    chunk_settings: ChunkSettings | None = None,
) -> IngestService:
    """인제스트 조립. 분석기는 ``build_content_analyzer``가 고른다 (mock 모드는 기존 결정적 mock 그대로).

    ``analyzer``/``chunk_settings``는 하네스·CLI 주입용이다. ``analyzer``만 주면 청킹 설정은 기본값이다.
    fixture 루트가 없으면 fixture fetcher를 빼고 조립한다. 그때 fixture 원본은 잡 단계에서
    `INGEST_UNSUPPORTED`로 실패한다 (API 기동 자체는 막지 않는다).
    """
    now = clock or _utc_now
    fetchers: list[SourceFetcher] = [InlineTextFetcher(clock=now)]
    root = container.settings.ingest_fixtures_root
    if root.is_dir():
        fetchers.extend([FixtureHtmlFetcher(root, clock=now), FixtureTranscriptFetcher(root, clock=now)])
    from jupjup.ingest.instagram import InstagramMetadataFetcher
    from jupjup.ingest.youtube import YoutubeCaptionFetcher

    fetchers.extend([YoutubeCaptionFetcher(), InstagramMetadataFetcher(), HttpSourceFetcher(clock=now)])
    queue = JobQueue(container.engine)
    if analyzer is None:
        analyzer, built_chunk_settings = build_content_analyzer(
            container.settings, container.lexicon, container.morph_tokenizer
        )
        chunk_settings = chunk_settings or built_chunk_settings
    stages = IngestStageRunners(
        queue,
        container.repo,
        container.indexer,
        FetcherRouter(fetchers),
        analyzer,
        OcrOnlyUnderstander(),
        chunk_settings=chunk_settings,
        clock=now,
    )
    worker = IngestWorker(
        queue,
        stages.mapping(),
        now,
        retry=RetryPolicy(),
        worker_id=worker_id,
        concurrency=concurrency or container.settings.worker_concurrency,
    )
    return IngestService(container.repo, queue, worker)

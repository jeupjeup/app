"""도메인 에러 계층 (설계서 5.8.1절)."""

from __future__ import annotations

from typing import Any


class JupjupError(Exception):
    code: str = "INTERNAL"

    def __init__(self, message: str = "", details: dict[str, Any] | None = None) -> None:
        super().__init__(message or self.code)
        self.message = message or self.code
        self.details: dict[str, Any] = details or {}


class InvalidQueryError(JupjupError):
    code = "INVALID_QUERY"


class InvalidUserError(JupjupError):
    code = "INVALID_USER"


class InvalidFilterError(JupjupError):
    code = "INVALID_FILTER"


class ContentValidationError(JupjupError):
    code = "INVALID_CONTENT"


class NotFoundError(JupjupError):
    code = "NOT_FOUND"


class IdempotencyConflictError(JupjupError):
    code = "IDEMPOTENCY_CONFLICT"


class IdempotencyInProgressError(JupjupError):
    code = "IDEMPOTENCY_IN_PROGRESS"


class ContentBusyError(JupjupError):
    code = "CONTENT_BUSY"


class VersionConflictError(JupjupError):
    code = "VERSION_CONFLICT"


class ReviewConflictError(JupjupError):
    code = "REVIEW_CONFLICT"


class InvalidContentStateError(JupjupError):
    code = "INVALID_CONTENT_STATE"


class InvalidPatchError(JupjupError):
    code = "INVALID_PATCH"


class InvalidCursorError(JupjupError):
    code = "INVALID_CURSOR"


class ProviderError(JupjupError):
    code = "PROVIDER_ERROR"


class EmbeddingProviderError(ProviderError):
    code = "EMBEDDING_UNAVAILABLE"


class EmbeddingCacheMiss(ProviderError):
    code = "EMBEDDING_CACHE_MISS"


class LLMProviderError(ProviderError):
    code = "LLM_UNAVAILABLE"


class LLMTimeoutError(LLMProviderError):
    """생성이 호출 타임아웃을 넘었다. details: ``{"retryable": True, "timeout_s": ...}``."""

    code = "LLM_TIMEOUT"


class LLMContextOverflowError(LLMProviderError):
    """입력 + 출력 상한이 모델 컨텍스트를 넘는다 (영구). details: ``retryable=False, input_tokens, n_ctx``."""

    code = "LLM_CONTEXT_OVERFLOW"


class AnalyzerUnavailableError(ProviderError):
    """로컬 분석기를 쓸 수 없다 (영구).

    details: ``{"retryable": False, "reason": "extra_missing|model_missing|sha_mismatch|load_failed"}``.
    """

    code = "ANALYZER_UNAVAILABLE"


class LLMCacheMiss(ProviderError):
    code = "LLM_CACHE_MISS"


class LLMRefusalError(JupjupError):
    code = "LLM_REFUSED"


class AnalysisSchemaError(JupjupError):
    code = "ANALYSIS_SCHEMA_INVALID"


class FetchError(JupjupError):
    code = "INGEST_FETCH_FAILED"


class UnsupportedSourceError(JupjupError):
    code = "INGEST_UNSUPPORTED"


class ExtractionError(JupjupError):
    code = "INGEST_EXTRACT_FAILED"


class VisionProviderError(ProviderError):
    code = "VISION_UNAVAILABLE"


class StorageError(JupjupError):
    code = "STORAGE_UNAVAILABLE"


class IndexingError(JupjupError):
    code = "INDEX_UNAVAILABLE"


class LeaseLostError(JupjupError):
    """The job lease was replaced while a worker was still executing."""

    code = "INGEST_LEASE_LOST"


class RerankerError(ProviderError):
    code = "RERANKER_ERROR"


class RerankerUnavailable(RerankerError):
    code = "RERANKER_UNAVAILABLE"


class RerankCacheMiss(RerankerError):
    code = "RERANK_CACHE_MISS"


class IndexNotReadyError(JupjupError):
    code = "INDEX_NOT_READY"


class GoldenSetError(JupjupError):
    """골든셋 검증 실패 (평가 하네스 전용, CLI 종료 코드 2)."""

    code = "GOLDEN_INVALID"


class SourceTextUnavailableError(ExtractionError):
    code = "SOURCE_TEXT_UNAVAILABLE"

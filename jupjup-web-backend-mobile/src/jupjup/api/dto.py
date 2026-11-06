"""Public request and response DTOs for the search API."""

from __future__ import annotations

from datetime import datetime
from pathlib import PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator, model_validator

from jupjup.domain.models import ContentType, Platform, require_aware
from jupjup.ingest.fetch import SourceSpec
from jupjup.ingest.jobs import JobRecord
from jupjup.ingest.service import IngestRequest
from jupjup.search.types import EmptyState, MatchReason


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SearchFiltersBody(ApiModel):
    # Strings are narrowed to domain Literals in the route so bad facets become
    # INVALID_FILTER instead of FastAPI's generic VALIDATION_ERROR.
    platforms: list[str] | None = Field(default=None, max_length=10)
    content_types: list[str] | None = Field(default=None, max_length=10)
    saved_from: datetime | None = None
    saved_to: datetime | None = None

    @field_validator("saved_from", "saved_to")
    @classmethod
    def _aware(cls, value: datetime | None) -> datetime | None:
        return None if value is None else require_aware(value, "saved_from/saved_to")


class SearchBody(ApiModel):
    query: str
    limit: StrictInt = 10
    filters: SearchFiltersBody | None = None
    explain: StrictBool = False
    now: datetime | None = None

    @field_validator("now")
    @classmethod
    def _aware(cls, value: datetime | None) -> datetime | None:
        return None if value is None else require_aware(value, "now")


class ParseBody(ApiModel):
    query: str


class TimeRangeResponse(BaseModel):
    expression: str
    start: datetime
    end: datetime
    field: Literal["saved_at"]
    fuzzy: bool


class FacetResponse(BaseModel):
    value: str
    strength: Literal["hard", "soft"]
    origin: Literal["query"] = "query"


class CorrectionResponse(BaseModel):
    from_: str = Field(serialization_alias="from")
    to: str
    kind: Literal["synonym", "spelling"]
    confidence: float


class UnderstandingResponse(BaseModel):
    intent: str
    keywords: list[str]
    semantic_query: str
    purpose_terms: list[str]
    time_range: TimeRangeResponse | None
    platforms: list[FacetResponse]
    content_types: list[FacetResponse]
    corrections: list[CorrectionResponse]
    overridden_by_request: list[str]


class ResultItemResponse(BaseModel):
    content_id: str
    rank: int
    score: float
    title: str
    platform: str
    content_type: str
    summary: str | None
    representative_tags: list[str]
    saved_at: datetime
    source_url: str | None
    original_available: bool
    relaxed: bool
    match_reasons: list[MatchReason]
    debug: dict[str, Any] | None = None


class SearchResponse(BaseModel):
    query_id: str
    query: str
    understanding: UnderstandingResponse
    results: list[ResultItemResponse]
    applied_relaxations: list[str]
    empty_state: EmptyState | None
    degraded: bool
    timing_ms: dict[str, float]


class ParseResponse(BaseModel):
    understanding: UnderstandingResponse


class BulkUpsertBody(ApiModel):
    items: list[dict[str, Any]] = Field(max_length=500)
    strict: StrictBool = True


class BulkFailure(BaseModel):
    index: int
    id: str | None
    code: str
    message: str


class BulkUpsertResponse(BaseModel):
    upserted: int
    failed: list[BulkFailure]
    embedding_pending: int


class HealthResponse(BaseModel):
    status: Literal["ok", "starting"] = "ok"
    index_ready: bool
    embedder: str
    mode: str
    # 로컬 분석기 상태 (설계 design_local_analyzer.md 6.8절). mock 경로는 None이고 응답에서 빠진다.
    analyzer: Literal["recorded", "local", "unavailable"] | None = None


# ------------------------------------------------------------------ ingest (T23)
MAX_INGEST_TEXT_CHARS = 100_000  # extract_snapshot 기본 max_chars와 같다
MAX_URL_CHARS = 2048
MAX_PATH_CHARS = 512


def _safe_relative_path(value: str, field: str) -> str:
    """fixture/image 경로는 루트 상대 경로만 받는다. 실제 루트 안 검사(심볼릭 링크 포함)는 fetcher가 다시 한다."""
    posix = PurePosixPath(value)
    if (
        not value.strip()
        or "\\" in value
        or "\x00" in value
        or posix.is_absolute()
        or ".." in posix.parts
        or (len(value) >= 2 and value[1] == ":")
    ):
        raise ValueError(f"{field}는 루트 안의 상대 경로여야 해요")
    return value


class IngestSourceBody(ApiModel):
    kind: Literal["text", "url", "image"]
    text: str | None = Field(default=None, max_length=MAX_INGEST_TEXT_CHARS)
    url: str | None = Field(default=None, max_length=MAX_URL_CHARS)
    fixture: str | None = Field(default=None, max_length=MAX_PATH_CHARS)
    ocr_text: str | None = Field(default=None, max_length=MAX_INGEST_TEXT_CHARS)
    image_path: str | None = Field(default=None, max_length=MAX_PATH_CHARS)

    @field_validator("url")
    @classmethod
    def _http_url(cls, value: str | None) -> str | None:
        if value is not None and not value.startswith(("http://", "https://")):
            raise ValueError("url은 http:// 또는 https://로 시작해야 해요")
        return value

    @field_validator("fixture", "image_path")
    @classmethod
    def _relative(cls, value: str | None) -> str | None:
        return None if value is None else _safe_relative_path(value, "경로")

    @model_validator(mode="after")
    def _shape(self) -> IngestSourceBody:
        allowed = {"text": {"text"}, "url": {"url", "fixture"}, "image": {"ocr_text", "image_path"}}[self.kind]
        extra = sorted(
            name
            for name in ("text", "url", "fixture", "ocr_text", "image_path")
            if getattr(self, name) is not None and name not in allowed
        )
        if extra:
            raise ValueError(f"kind={self.kind}에는 {', '.join(extra)}를 보낼 수 없어요")
        required = {"text": "text", "url": "fixture", "image": "ocr_text"}[self.kind]
        value = getattr(self, required)
        if value is None or not value.strip():
            raise ValueError(f"kind={self.kind}에는 {required}가 필요해요")
        return self


class IngestBody(ApiModel):
    source: IngestSourceBody
    platform_hint: Platform | None = None
    content_type_hint: ContentType | None = None
    title: str | None = Field(default=None, max_length=300)
    author: str | None = Field(default=None, max_length=200)
    user_note: str | None = Field(default=None, max_length=2000)
    saved_at: datetime | None = None

    @field_validator("saved_at")
    @classmethod
    def _aware(cls, value: datetime | None) -> datetime | None:
        return None if value is None else require_aware(value, "saved_at")

    def to_request(self, default_saved_at: datetime) -> IngestRequest:
        """saved_at이 없으면 서비스 시계 값을 쓴다 (테스트 시계 주입과 맞춘다)."""
        values: dict[str, Any] = self.model_dump(exclude={"source", "saved_at"})
        return IngestRequest(
            source=SourceSpec(**self.source.model_dump(exclude_none=True)),
            saved_at=self.saved_at or default_saved_at,
            **values,
        )


class IngestSubmitResponse(BaseModel):
    content_id: str
    job_id: str
    status: str


class IngestJobResponse(BaseModel):
    job_id: str
    content_id: str
    status: str
    stage: str
    attempts: int
    last_error: dict[str, Any] | None
    updated_at: datetime

    @classmethod
    def from_job(cls, job: JobRecord) -> IngestJobResponse:
        # 설계서 응답의 attempts는 정수다. 현재 단계의 시도 횟수를 돌려준다.
        return cls(
            job_id=job.id,
            content_id=job.content_id,
            status=job.status,
            stage=job.stage,
            attempts=job.attempts.get(job.stage, 0),
            last_error=job.last_error,
            updated_at=job.updated_at,
        )


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | list[dict[str, Any]] | None = None


class ErrorEnvelope(BaseModel):
    error: ErrorBody

"""Public save requests; internal fixture and profile controls are excluded."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from jupjup.domain.errors import ContentValidationError
from jupjup.domain.models import ContentType, Platform
from jupjup.ingest.analyzer import AnalysisRunMeta
from jupjup.ingest.schemas import AnalysisOutput
from jupjup.ingest.youtube_metadata import MetadataClassification
from jupjup.save.dedupe import normalize_source_url


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class UrlSource(StrictModel):
    kind: Literal["url"]
    url: str = Field(max_length=2048)

    @field_validator("url")
    @classmethod
    def normalize(cls, value: str) -> str:
        return normalize_source_url(value)


class TextSource(StrictModel):
    kind: Literal["text"]
    text: str = Field(min_length=1, max_length=100_000)

    @field_validator("text", mode="before")
    @classmethod
    def trim(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value


class ImageMeta(StrictModel):
    mime_type: Literal["image/jpeg", "image/png", "image/webp"] | None = None
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{64}$")


class ImageSource(StrictModel):
    kind: Literal["image"]
    ocr_text: str = Field(min_length=1, max_length=100_000)
    image: ImageMeta | None = None

    @field_validator("ocr_text", mode="before")
    @classmethod
    def trim(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value


class CreateContent(StrictModel):
    source: Annotated[UrlSource | TextSource | ImageSource, Field(discriminator="kind")]
    platform_hint: Platform | None = None
    content_type_hint: ContentType | None = None
    title: str | None = Field(default=None, max_length=1000)
    author: str | None = Field(default=None, max_length=1000)
    user_note: str | None = Field(default=None, max_length=2000)
    automation_level: Literal["auto", "confirm"] = "auto"

    @model_validator(mode="after")
    def consistent_hints(self) -> CreateContent:
        if self.platform_hint == "kakaotalk" and self.content_type_hint not in (None, "message", "image"):
            raise ContentValidationError("kakaotalk의 content_type은 message 또는 image여야 합니다")
        return self


class ContentPatch(StrictModel):
    summary: str | None = Field(default=None, min_length=1, max_length=1000)
    representative_tags: list[str] | None = None
    detail_tags: dict[str, Any] | None = None
    hidden: bool | None = None


class ReanalyzeRequest(StrictModel):
    mode: Literal["snapshot", "youtube_metadata"] = "snapshot"
    automation_level: Literal["auto", "confirm"] | None = None


class ReviewRequest(StrictModel):
    candidate_id: str
    decision: Literal["approve", "reject"]


class SubmitResponse(StrictModel):
    content_id: str
    job_id: str | None
    status: str
    automation_level: Literal["auto", "confirm"]
    deduplicated: bool
    result_content_id: str
    duplicate_reason: str | None = None
    warnings: list[str] = Field(default_factory=list)


class AnalysisCandidate(AnalysisOutput):
    id: str
    meta: AnalysisRunMeta


class MetadataCandidate(MetadataClassification):
    id: str
    meta: AnalysisRunMeta


class ContentAnalysis(StrictModel):
    metadata: MetadataClassification | None = None
    source_text_available: bool
    source_text_reason: Literal["legacy_watch_snapshot", "missing_snapshot", "empty_snapshot"] | None
    automation_level: Literal["auto", "confirm"]
    analysis_pending: bool
    latest_job_id: str | None
    candidate: MetadataCandidate | AnalysisCandidate | None


class ContentDetail(StrictModel):
    collection_ids: list[str] = Field(default_factory=list)
    id: str
    canonical_id: str
    revision: int
    status: str
    hidden: bool
    source: dict[str, Any]
    platform: Platform
    content_type: ContentType
    title: str | None
    author: str | None
    published_at: str | None
    saved_at: str
    user_note: str | None
    summary: dict[str, Any]
    representative_tags: dict[str, Any]
    detail_tags: dict[str, Any]
    snapshot: dict[str, Any] | None
    analysis: ContentAnalysis
    created_at: str | None
    updated_at: str | None


class ContentListItem(StrictModel):
    id: str
    collection_ids: list[str]
    revision: int
    status: str
    hidden: bool
    title: str | None
    platform: Platform
    content_type: ContentType
    summary: str | None
    summary_is_mock: bool
    representative_tags: list[str]
    saved_at: str
    updated_at: str | None
    source_url: str | None
    original_available: bool
    analysis_pending: bool


class ContentPage(StrictModel):
    items: list[ContentListItem]
    next_cursor: str | None
    has_more: bool


class ReviewResponse(StrictModel):
    content_id: str
    job_id: str
    candidate_id: str
    decision: Literal["approve", "reject"]
    status: str


class JobDetail(StrictModel):
    id: str
    content_id: str
    result_content_id: str
    kind: str
    automation_level: str
    status: str
    current_stage: str
    attempts: dict[str, int]
    created_at: str
    updated_at: str
    next_run_at: str | None
    error: dict[str, Any] | None
    steps: list[dict[str, Any]]
    candidate: dict[str, Any] | None
    trace: dict[str, Any] | None = None


class AliasDetail(StrictModel):
    collection_ids: list[str] = Field(default_factory=list)
    id: str
    canonical_id: str
    status: Literal["duplicate"]
    revision: int

"""Bounded public metadata and evidence-based local classification, without summaries."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from jupjup.domain.models import validate_detail_tags
from jupjup.ingest.schemas import RepresentativeTag


class YoutubeMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    title: str = Field(min_length=1, max_length=1000)
    description: str = Field(max_length=20_000)
    title_source: Literal["videoDetails.title"] = "videoDetails.title"
    description_source: Literal["videoDetails.shortDescription", "absent"]
    description_status: Literal["available", "empty", "missing"]
    title_truncated: bool = False
    description_truncated: bool = False
    transcript_reason: Literal["captions_unavailable", "empty_captions", "empty_or_invalid_captions", "not_requested"]


class MetadataEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    field: Literal["title", "description"]
    source_span: str = Field(min_length=1, max_length=100)
    tag: str


class MetadataClassification(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source_scope: Literal["youtube_metadata"] = "youtube_metadata"
    basis: Literal["title_description", "title_only"]
    metadata: YoutubeMetadata
    representative_tags: list[RepresentativeTag] = Field(max_length=7)
    detail_tags: dict[str, Any]
    evidence: list[MetadataEvidence] = Field(max_length=20)
    classifier: Literal["local-metadata-rules-v1", "local-metadata-llm-v1"] = "local-metadata-rules-v1"
    model: str | None = Field(default=None, max_length=200, exclude_if=lambda v: v is None)
    summary: str | None = Field(default=None, min_length=20, max_length=400, exclude_if=lambda v: v is None)

    salience: dict[str, Any] | None = Field(default=None, exclude_if=lambda v: v is None)

    @model_validator(mode="after")
    def validate_llm(self) -> MetadataClassification:
        if self.classifier == "local-metadata-llm-v1":
            if not self.summary or not self.model or len(self.representative_tags) < 3:
                raise ValueError("로컬 LLM 결과에는 요약과 대표 태그 3개 이상이 필요합니다")
        elif self.summary is not None:
            raise ValueError("규칙 분류 결과에는 요약을 허용하지 않습니다")
        return self

    @field_validator("detail_tags")
    @classmethod
    def valid_detail(cls, value: dict[str, Any]) -> dict[str, Any]:
        validate_detail_tags(value)
        return value

    def materialized_detail_tags(self) -> dict[str, Any]:
        return self.detail_tags

    @property
    def title_suggestion(self) -> str:
        return self.metadata.title


# Every emitted tag has a literal lexical match; instructions in metadata are never executed.
_RULES = (
    ("C++", r"(?<![\w+])c\+\+(?!\+)", "tech"),
    ("프로그래밍", r"프로그래밍|programming", "tech"),
    ("Python", r"(?<!\w)python(?!\w)|파이썬", "tech"),
    ("JavaScript", r"(?<!\w)javascript(?!\w)|자바스크립트", "tech"),
    ("소프트웨어", r"소프트웨어|software", "tech"),
    ("머신러닝", r"머신러닝|machine learning", "tech"),
    ("강의", r"강의|lecture|tutorial", "study_research"),
    ("학습", r"학습|공부|learning", "study_research"),
    ("레시피", r"레시피|recipe", "howto_recipe"),
    ("여행", r"여행|travel", "place_travel"),
    ("운동", r"운동|workout|fitness", "health_fitness"),
    ("영화", r"영화|movie", "culture_media"),
)


def classify_metadata(metadata: YoutubeMetadata) -> MetadataClassification:
    tags: list[str] = []
    categories: list[str] = []
    evidence: list[MetadataEvidence] = []
    for tag, pattern, category in _RULES:
        for field in ("title", "description"):
            match = re.search(pattern, getattr(metadata, field), re.IGNORECASE)
            if match:
                tags.append(tag)
                categories.append(category)
                evidence.append(MetadataEvidence(field=field, source_span=match.group(), tag=tag))
                break
        if len(tags) == 7:
            break
    category = "tech" if "tech" in categories else categories[0] if categories else "other"
    detail: dict[str, Any] = {"schema_version": 1, "category": category, "topics": tags}
    if "study_research" in categories:
        detail["purpose"] = ["공부자료"]
    return MetadataClassification(
        basis="title_description" if metadata.description.strip() else "title_only",
        metadata=metadata,
        representative_tags=tags,
        detail_tags=detail,
        evidence=evidence,
    )

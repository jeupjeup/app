"""인제스트 분석 출력의 Pydantic 정본과 LLM용 JSON Schema."""

from __future__ import annotations

import copy
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator
from pydantic.json_schema import GenerateJsonSchema, JsonSchemaMode

from jupjup.domain.errors import ContentValidationError
from jupjup.domain.models import detail_tags_schema, validate_detail_tags

SaveIntentLabel = Literal[
    "방문예정",
    "구매검토",
    "레시피",
    "공부자료",
    "과제",
    "업무참고",
    "여행계획",
    "선물아이디어",
    "나중에읽기",
    "영감",
    "정보보관",
    "기타",
]
RepresentativeTag = Annotated[str, StringConstraints(min_length=1, max_length=20)]


class SaveIntent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    labels: list[SaveIntentLabel] = Field(max_length=3)
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(max_length=120)


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    claim: str
    source_span: str = Field(max_length=200)


class AnalysisOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    summary: str = Field(min_length=20, max_length=400, description="원문에 있는 내용만 2~4문장 한국어로")
    representative_tags: list[RepresentativeTag] = Field(min_length=3, max_length=7)
    detail_tags: dict[str, Any]
    save_intent: SaveIntent
    title_suggestion: str | None = Field(max_length=80)
    language: str = Field(description="ISO 639-1")
    evidence: list[Evidence] = Field(max_length=20)

    @field_validator("detail_tags")
    @classmethod
    def _detail_tags(cls, value: dict[str, Any]) -> dict[str, Any]:
        try:
            validate_detail_tags(value)
        except ContentValidationError as exc:
            raise ValueError(exc.message) from exc
        return value

    @classmethod
    def model_json_schema(
        cls,
        by_alias: bool | None = True,
        ref_template: str = "#/$defs/{model}",
        schema_generator: type[GenerateJsonSchema] = GenerateJsonSchema,
        mode: JsonSchemaMode = "validation",
        *,
        union_format: Literal["any_of", "primitive_type_array"] = "any_of",
    ) -> dict[str, Any]:
        schema = super().model_json_schema(
            by_alias=by_alias,
            ref_template=ref_template,
            schema_generator=schema_generator,
            mode=mode,
            union_format=union_format,
        )
        properties = schema.get("properties")
        if isinstance(properties, dict):
            properties["detail_tags"] = {"$ref": "#/$defs/DetailTagsV1"}
        definitions = schema.setdefault("$defs", {})
        if isinstance(definitions, dict):
            definitions["DetailTagsV1"] = copy.deepcopy(detail_tags_schema())
        return schema

    def materialized_detail_tags(self) -> dict[str, Any]:
        """I6가 저장할 목적/의도 필드를 사용자 입력을 바꾸지 않고 만든다."""
        detail = copy.deepcopy(self.detail_tags)
        labels = list(self.save_intent.labels)
        purpose = list(dict.fromkeys([*labels, *detail.get("purpose", [])]))[:5]
        detail["purpose"] = purpose
        detail["save_intent"] = {
            "labels": labels,
            "confidence": self.save_intent.confidence,
            "inferred": True,
        }
        validate_detail_tags(detail)
        return detail


def analysis_output_json_schema() -> dict[str, Any]:
    """구조화 출력 제공자에 전달할 결정적 JSON Schema를 반환한다."""
    return copy.deepcopy(AnalysisOutput.model_json_schema())


# --- 맵 단계 청크 노트 (설계 design_local_analyzer.md 6.6절) -------------------------------------------------

EntityType = Literal["place", "person", "organization", "product", "brand", "work", "event", "other"]
EvidenceId = Annotated[str, StringConstraints(pattern=r"^s[1-9][0-9]{0,3}$")]
ChunkQuote = Annotated[str, StringConstraints(min_length=1, max_length=120)]
ChunkTerm = Annotated[str, StringConstraints(min_length=1, max_length=60)]


class ChunkFact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    text: str = Field(min_length=1, max_length=160)
    evidence_ids: list[EvidenceId] = Field(min_length=1, max_length=4)


class ChunkEntity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    type: EntityType
    name: str = Field(min_length=1, max_length=60)


class ChunkNotes(BaseModel):
    """맵 단계 출력. 리듀스 프롬프트의 ``<chunk_notes>`` 블록에 들어간다."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    facts: list[ChunkFact] = Field(max_length=8)
    entities: list[ChunkEntity] = Field(max_length=10)
    locations: list[ChunkTerm] = Field(max_length=5)
    keywords: list[ChunkTerm] = Field(max_length=8)
    quotes: list[ChunkQuote] = Field(max_length=3)

    @classmethod
    def empty(cls) -> ChunkNotes:
        return cls(facts=[], entities=[], locations=[], keywords=[], quotes=[])

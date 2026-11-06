"""도메인 모델 (설계서 6장).

시드 레코드(3.1.4절)는 `SeedRecord`로 파싱한 뒤 `to_bundle()`로 `ContentBundle`이 된다.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import unicodedata
import warnings
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import lru_cache
from importlib import resources
from typing import Any, Literal, get_args

import jsonschema
import jsonschema.exceptions
import jsonschema.protocols
import jsonschema.validators
import numpy as np
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from jupjup.domain.errors import ContentValidationError

Platform = Literal["instagram", "youtube", "kakaotalk", "news", "blog", "x", "web", "local"]
ContentType = Literal["post", "short_video", "video", "article", "paper", "image", "message", "webpage"]
OriginalStatus = Literal["available", "deleted", "unknown"]
TagSource = Literal["ai", "user"]
ContentStatus = Literal[
    "pending",
    "awaiting_confirmation",
    "ready",
    "analysis_failed",
    "analysis_rejected",
    "duplicate",
]

PLATFORMS: tuple[str, ...] = get_args(Platform)
CONTENT_TYPES: tuple[str, ...] = get_args(ContentType)

USER_ID_RE = re.compile(r"^u_[a-z0-9_]{1,64}$")
CONTENT_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{1,128}$")
MAX_EFFECTIVE_TAGS = 15
MAX_USER_NOTE = 2000
MAX_SNAPSHOT_TEXT = 100_000
MAX_SUMMARY_TEXT = 1000
MAX_TAG_LEN = 30


def require_aware(dt: datetime, name: str = "datetime") -> datetime:
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        raise ValueError(f"{name}은(는) timezone-aware여야 합니다")
    return dt


def normalize_tag_name(name: str) -> str:
    """NFKC, 앞쪽 `#` 제거, 공백 제거, 최대 30자 (6.2절 tags.name)."""
    s = unicodedata.normalize("NFKC", name).strip().lstrip("#")
    s = re.sub(r"\s+", "", s)
    return s[:MAX_TAG_LEN]


def merge_patch(target: Any, patch: Any) -> Any:
    """JSON Merge Patch (RFC 7386). 입력을 변경하지 않고 새 객체를 돌려준다."""
    if not isinstance(patch, dict):
        return copy.deepcopy(patch)
    result: dict[str, Any] = copy.deepcopy(target) if isinstance(target, dict) else {}
    for key, value in patch.items():
        if value is None:
            result.pop(key, None)
        else:
            result[key] = merge_patch(result.get(key), value)
    return result


@lru_cache(maxsize=1)
def detail_tags_schema() -> dict[str, Any]:
    text = resources.files("jupjup.domain").joinpath("detail_tags.v1.json").read_text(encoding="utf-8")
    schema: dict[str, Any] = json.loads(text)
    return schema


@lru_cache(maxsize=1)
def _detail_validator() -> jsonschema.protocols.Validator:
    cls = jsonschema.validators.validator_for(detail_tags_schema())
    validator: jsonschema.protocols.Validator = cls(detail_tags_schema())
    return validator


def validate_detail_tags(data: dict[str, Any]) -> None:
    err = jsonschema.exceptions.best_match(_detail_validator().iter_errors(data))
    if err is not None:
        path = "/".join(str(p) for p in err.absolute_path)
        raise ContentValidationError(f"세부 태그 스키마 위반: {err.message}", {"path": path or "$"})


class Tag(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    source: TagSource
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)

    @field_validator("name")
    @classmethod
    def _norm(cls, v: str) -> str:
        n = normalize_tag_name(v)
        if not n:
            raise ValueError("태그 이름이 비었습니다")
        return n


def effective_tags(tags: list[Tag], hidden_tags: list[str]) -> list[Tag]:
    """유효 태그 = user ∪ (ai − hidden − user와 같은 이름). user 먼저, 입력 순서 유지."""
    hidden = {normalize_tag_name(h) for h in hidden_tags}
    user = [t for t in tags if t.source == "user"]
    user_names = {t.name for t in user}
    out: list[Tag] = []
    seen: set[str] = set()
    for t in user:
        if t.name not in seen:
            out.append(t)
            seen.add(t.name)
    for t in tags:
        if t.source == "ai" and t.name not in hidden and t.name not in user_names and t.name not in seen:
            out.append(t)
            seen.add(t.name)
    return out


class Snapshot(BaseModel):
    id: str
    content_id: str
    captured_at: datetime
    text: str = ""
    ocr_text: str | None = None
    raw_meta: dict[str, Any] = Field(default_factory=dict)
    content_hash: str = ""
    truncated: bool = False

    @field_validator("captured_at")
    @classmethod
    def _aware(cls, v: datetime) -> datetime:
        return require_aware(v, "captured_at")

    @model_validator(mode="after")
    def _fill(self) -> Snapshot:
        if len(self.text) > MAX_SNAPSHOT_TEXT:
            self.text = self.text[:MAX_SNAPSHOT_TEXT]
            self.truncated = True
        if not self.content_hash:
            self.content_hash = hashlib.sha256((self.text + "\x00" + (self.ocr_text or "")).encode("utf-8")).hexdigest()
        return self


class Summary(BaseModel):
    id: str
    content_id: str
    version: int = Field(ge=1)
    text: str = Field(min_length=1, max_length=MAX_SUMMARY_TEXT)
    model: str = "human"
    source: TagSource = "ai"
    analysis_run_id: str | None = None
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _aware(cls, v: datetime) -> datetime:
        return require_aware(v, "created_at")


def pick_effective_summary(summaries: list[Summary]) -> Summary | None:
    """source=user 중 최신 → 없으면 source=ai 중 최신 (6.2절)."""
    for src in ("user", "ai"):
        cands = [s for s in summaries if s.source == src]
        if cands:
            return max(cands, key=lambda s: (s.version, s.created_at))
    return None


class DetailTags(BaseModel):
    content_id: str
    ai_json: dict[str, Any] = Field(default_factory=lambda: {"schema_version": 1})
    user_patch: dict[str, Any] | None = None
    schema_version: int = 1
    analysis_run_id: str | None = None

    @model_validator(mode="after")
    def _check(self) -> DetailTags:
        validate_detail_tags(self.ai_json)
        validate_detail_tags(self.effective())
        return self

    def effective(self) -> dict[str, Any]:
        if self.user_patch is None:
            return copy.deepcopy(self.ai_json)
        merged = merge_patch(self.ai_json, self.user_patch)
        assert isinstance(merged, dict)
        return merged


class Content(BaseModel):
    id: str
    user_id: str
    source_url: str | None = None
    source_kind: Literal["url", "text", "image"] = "text"
    normalized_url: str | None = None
    platform: Platform
    content_type: ContentType
    title: str | None = None
    author: str | None = None
    published_at: datetime | None = None
    saved_at: datetime
    original_status: OriginalStatus = "unknown"
    user_note: str | None = Field(default=None, max_length=MAX_USER_NOTE)
    hidden_tags: list[str] = Field(default_factory=list)
    status: ContentStatus = "ready"
    analysis_pending: bool = False
    automation_level: Literal["auto", "confirm"] = "auto"
    is_hidden: bool = False
    revision: int = Field(default=0, ge=0)
    duplicate_of_content_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        if not CONTENT_ID_RE.match(v):
            raise ValueError("content id 형식 오류")
        return v

    @field_validator("user_id")
    @classmethod
    def _uid(cls, v: str) -> str:
        if not USER_ID_RE.match(v):
            raise ValueError("user_id 형식 오류 (^u_[a-z0-9_]{1,64}$)")
        return v

    @field_validator("saved_at", "published_at", "created_at", "updated_at")
    @classmethod
    def _aware(cls, v: datetime | None) -> datetime | None:
        return None if v is None else require_aware(v)

    @field_validator("source_url")
    @classmethod
    def _url(cls, v: str | None) -> str | None:
        if v is not None and not re.match(r"^https?://", v):
            raise ValueError("source_url은 http/https만 허용합니다")
        return v

    @field_validator("hidden_tags")
    @classmethod
    def _hidden(cls, v: list[str]) -> list[str]:
        return [n for n in (normalize_tag_name(x) for x in v) if n]

    @model_validator(mode="after")
    def _rules(self) -> Content:
        if self.platform == "kakaotalk" and self.content_type not in ("message", "image"):
            raise ValueError("kakaotalk의 content_type은 message 또는 image여야 합니다")
        if self.published_at is not None and self.published_at > self.saved_at + timedelta(days=1):
            warnings.warn(f"{self.id}: published_at이 saved_at보다 늦습니다", stacklevel=2)
        return self


class ContentBundle(BaseModel):
    content: Content
    snapshot: Snapshot | None = None
    summaries: list[Summary] = Field(default_factory=list)
    tags: list[Tag] = Field(default_factory=list)
    detail_tags: DetailTags | None = None

    @model_validator(mode="after")
    def _check(self) -> ContentBundle:
        cid = self.content.id
        if self.snapshot is not None and self.snapshot.content_id != cid:
            raise ValueError("snapshot.content_id 불일치")
        if any(s.content_id != cid for s in self.summaries):
            raise ValueError("summary.content_id 불일치")
        if self.detail_tags is not None and self.detail_tags.content_id != cid:
            raise ValueError("detail_tags.content_id 불일치")
        if len(self.effective_tags()) > MAX_EFFECTIVE_TAGS:
            raise ValueError(f"유효 태그는 최대 {MAX_EFFECTIVE_TAGS}개입니다")
        return self

    @property
    def summary(self) -> Summary | None:
        return pick_effective_summary(self.summaries)

    def effective_tags(self) -> list[Tag]:
        return effective_tags(self.tags, self.content.hidden_tags)

    def effective_detail(self) -> dict[str, Any] | None:
        return None if self.detail_tags is None else self.detail_tags.effective()


@dataclass(frozen=True)
class StoredEmbedding:
    """embeddings 테이블 한 행. vector는 float32, L2 정규화."""

    kind: Literal["doc", "chunk"]
    chunk_index: int
    text_hash: str
    vector: np.ndarray = field(compare=False)
    model_id: str = ""

    @property
    def dim(self) -> int:
        return int(self.vector.shape[0])


# ---------------------------------------------------------------------------
# 시드 레코드 (3.1.4절)


class SeedSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    captured_at: datetime | None = None
    text: str = ""
    ocr_text: str | None = None
    raw_meta: dict[str, Any] = Field(default_factory=dict)


class SeedSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str
    model: str = "human"
    version: int = 1
    source: TagSource = "ai"


class SeedTag(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    source: TagSource
    confidence: float | None = None


class SeedRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    user_id: str
    source_url: str | None = None
    platform: Platform
    content_type: ContentType
    title: str | None = None
    author: str | None = None
    published_at: datetime | None = None
    saved_at: datetime
    original_status: OriginalStatus = "unknown"
    user_note: str | None = None
    snapshot: SeedSnapshot | None = None
    summary: SeedSummary | None = None
    summaries: list[SeedSummary] = Field(default_factory=list)  # 사용자 요약 등 여러 버전이 필요할 때
    tags: list[SeedTag] = Field(default_factory=list)
    hidden_tags: list[str] = Field(default_factory=list)
    detail_tags: dict[str, Any] | None = None
    detail_tags_user_patch: dict[str, Any] | None = None
    meta: dict[str, Any] = Field(default_factory=dict)

    def to_bundle(self) -> ContentBundle:
        content = Content(
            id=self.id,
            user_id=self.user_id,
            source_url=self.source_url,
            platform=self.platform,
            content_type=self.content_type,
            title=self.title,
            author=self.author,
            published_at=self.published_at,
            saved_at=self.saved_at,
            original_status=self.original_status,
            user_note=self.user_note,
            hidden_tags=self.hidden_tags,
            status="ready",
            analysis_pending=False,
        )
        snap = None
        if self.snapshot is not None:
            snap = Snapshot(
                id=f"snap_{self.id}",
                content_id=self.id,
                captured_at=self.snapshot.captured_at or self.saved_at,
                text=self.snapshot.text,
                ocr_text=self.snapshot.ocr_text,
                raw_meta=self.snapshot.raw_meta,
            )
        seed_sums = ([self.summary] if self.summary else []) + list(self.summaries)
        summaries = [
            Summary(
                id=f"sum_{self.id}_{s.source}_{s.version}",
                content_id=self.id,
                version=s.version,
                text=s.text,
                model=s.model,
                source=s.source,
                created_at=self.saved_at,
            )
            for s in seed_sums
        ]
        tags: list[Tag] = []
        seen: set[tuple[str, str]] = set()
        for t in self.tags:
            tag = Tag(name=t.name, source=t.source, confidence=t.confidence if t.source == "ai" else None)
            if (tag.name, tag.source) not in seen:  # PK (content_id, name, source)
                tags.append(tag)
                seen.add((tag.name, tag.source))
        detail = None
        if self.detail_tags is not None or self.detail_tags_user_patch is not None:
            detail = DetailTags(
                content_id=self.id,
                ai_json=self.detail_tags or {"schema_version": 1},
                user_patch=self.detail_tags_user_patch,
            )
        return ContentBundle(content=content, snapshot=snap, summaries=summaries, tags=tags, detail_tags=detail)

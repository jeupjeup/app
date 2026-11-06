"""필터 해석 (설계서 5.2.5절, 5.8.6절). 요청 필터(사용자 선택)가 질의 추출값보다 항상 우선한다."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from jupjup.domain.errors import InvalidFilterError
from jupjup.domain.models import ContentType, Platform, require_aware
from jupjup.index.document import HardFilter
from jupjup.query.understanding import ParsedQuery
from jupjup.text.lexicon import Lexicon

MAX_FILTER_ITEMS = 10
Origin = Literal["request", "query"]


class SearchFilters(BaseModel):
    """요청 필터. saved_from 포함, saved_to 제외 (반열림)."""

    platforms: list[Platform] | None = Field(default=None, max_length=MAX_FILTER_ITEMS)
    content_types: list[ContentType] | None = Field(default=None, max_length=MAX_FILTER_ITEMS)
    saved_from: datetime | None = None
    saved_to: datetime | None = None

    @field_validator("saved_from", "saved_to")
    @classmethod
    def _aware(cls, v: datetime | None) -> datetime | None:
        return None if v is None else require_aware(v, "saved_from/saved_to")


class FilterClause(BaseModel):
    """플랫폼/유형 조건. strength=soft면 hard filter에서 빠지고 재순위 가점만 받는다 (완화 R3)."""

    value: list[str]
    origin: Origin
    locked: bool
    strength: Literal["hard", "soft"] = "hard"


class WindowClause(BaseModel):
    """기간 조건 [start, end). dropped=True면 hard filter에서 빠진다 (완화 R2)."""

    start: datetime | None
    end: datetime | None
    origin: Origin
    locked: bool
    dropped: bool = False


class ResolvedFilters(BaseModel):
    platforms: FilterClause | None = None
    content_types: FilterClause | None = None
    saved_window: WindowClause | None = None
    overridden: list[str] = Field(default_factory=list)
    soft_platforms: list[str] = Field(default_factory=list)
    soft_content_types: list[str] = Field(default_factory=list)

    def to_hard_filter(self, lexicon: Lexicon) -> HardFilter:
        plats = set(self.platforms.value) if self.platforms and self.platforms.strength == "hard" else None
        types = None
        if self.content_types and self.content_types.strength == "hard":
            types = lexicon.expand_content_types(set(self.content_types.value))
        w = self.saved_window
        if w is None or w.dropped:
            return HardFilter(platforms=plats, content_types=types)
        return HardFilter(platforms=plats, content_types=types, saved_from=w.start, saved_to=w.end)


class FilterResolver:
    def resolve(self, parsed: ParsedQuery, requested: SearchFilters | None) -> ResolvedFilters:
        req = requested or SearchFilters()
        if req.saved_from and req.saved_to and req.saved_from > req.saved_to:
            raise InvalidFilterError("saved_from은 saved_to보다 늦을 수 없어요.", {"field": "saved_from"})
        out = ResolvedFilters()
        q_plats = parsed.hard_platforms()
        q_types = parsed.hard_content_types()
        if req.platforms is not None:
            out.platforms = FilterClause(value=list(req.platforms), origin="request", locked=True)
            if parsed.platforms:
                out.overridden.append("platforms")
        elif q_plats:
            out.platforms = FilterClause(value=q_plats, origin="query", locked=False)
        if req.content_types is not None:
            out.content_types = FilterClause(value=list(req.content_types), origin="request", locked=True)
            if parsed.content_types:
                out.overridden.append("content_types")
        elif q_types:
            out.content_types = FilterClause(value=q_types, origin="query", locked=False)
        if req.saved_from is not None or req.saved_to is not None:
            out.saved_window = WindowClause(start=req.saved_from, end=req.saved_to, origin="request", locked=True)
            if parsed.time_window is not None:
                out.overridden.append("saved_range")
        elif parsed.time_window is not None:
            out.saved_window = WindowClause(
                start=parsed.time_window.start, end=parsed.time_window.end, origin="query", locked=False
            )
        # soft 값은 재순위 가점용. 요청 필터가 있는 항목은 사용자 선택이 이기므로 넣지 않는다.
        if req.platforms is None:
            out.soft_platforms = [h.value for h in parsed.platforms if h.strength == "soft"]
        if req.content_types is None:
            out.soft_content_types = [h.value for h in parsed.content_types if h.strength == "soft"]
        return out

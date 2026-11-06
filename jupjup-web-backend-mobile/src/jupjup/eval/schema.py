"""골든셋 스키마와 검증기 (설계서 3.1.4절, 3.1.5절, 3.4절)."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from jupjup.domain.errors import ContentValidationError, GoldenSetError
from jupjup.domain.models import CONTENT_TYPES, PLATFORMS, SeedRecord, require_aware
from jupjup.query.intent import Intent
from jupjup.search.filters import SearchFilters

QueryCategory = Literal[
    "exact",
    "ambiguous",
    "typo",
    "colloquial",
    "temporal",
    "platform",
    "content_type",
    "purpose",
    "semantic",
    "multi",
    "negative",
    "filter_conflict",
    "filter_only",
    "isolation",
    "challenge",
]
QUERY_CATEGORIES: tuple[str, ...] = get_args(QueryCategory)
ReviewStatus = Literal["ai_draft_unreviewed", "needs_human_review", "human_reviewed"]
ChallengeKind = Literal["hard_negative", "synonym_mismatch", "typo_colloquial", "mixed_english"]

# 3.1.3절 카테고리별 최소 개수
CATEGORY_MINIMUMS: dict[str, int] = {
    "exact": 15,
    "ambiguous": 20,
    "typo": 20,
    "colloquial": 20,
    "temporal": 30,
    "platform": 25,
    "content_type": 15,
    "purpose": 15,
    "semantic": 20,
    "multi": 15,
    "negative": 20,
    "filter_conflict": 5,
    "filter_only": 16,
    "isolation": 5,
}
CATEGORY_SPLIT_MINIMUMS: dict[str, dict[str, int]] = {"filter_only": {"dev": 8, "test": 8}}
MIN_SEEDS = 200
MIN_QUERIES = 180
MIN_LEXICON_CASES = 120


class ExpectedTimeRange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start: datetime
    end: datetime
    field: Literal["saved_at"] = "saved_at"

    @field_validator("start", "end")
    @classmethod
    def _aware(cls, v: datetime) -> datetime:
        return require_aware(v, "expected.time_range")


class ExpectedUnderstanding(BaseModel):
    """필드를 빼면 그 항목은 채점하지 않는다. time_range=null은 '기간 없음이 정답'."""

    model_config = ConfigDict(extra="forbid")
    intent: Intent | None = None
    time_range: ExpectedTimeRange | None = None
    platforms: list[str] | None = None
    content_types: list[str] | None = None
    keywords_must_include: list[str] = Field(default_factory=list)

    @field_validator("platforms")
    @classmethod
    def _plat(cls, v: list[str] | None) -> list[str] | None:
        if v is not None and any(p not in PLATFORMS for p in v):
            raise ValueError(f"알 수 없는 플랫폼: {v}")
        return v

    @field_validator("content_types")
    @classmethod
    def _ctype(cls, v: list[str] | None) -> list[str] | None:
        if v is not None and any(c not in CONTENT_TYPES for c in v):
            raise ValueError(f"알 수 없는 유형: {v}")
        return v

    def scores_time(self) -> bool:
        return "time_range" in self.model_fields_set


class GoldenQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    user_id: str
    query: str
    now: datetime
    categories: list[QueryCategory]
    split: Literal["dev", "test"]
    request_filters: SearchFilters | None = None
    expected: ExpectedUnderstanding
    relevance: dict[str, int]
    notes: str | None = None
    review_status: ReviewStatus = "ai_draft_unreviewed"
    template_id: str | None = None
    entity_id: str | None = None
    challenge_kind: ChallengeKind | None = None

    @field_validator("now")
    @classmethod
    def _aware(cls, v: datetime) -> datetime:
        return require_aware(v, "now")

    @field_validator("relevance")
    @classmethod
    def _grades(cls, v: dict[str, int]) -> dict[str, int]:
        if any(g not in (1, 2, 3) for g in v.values()):
            raise ValueError("관련도 등급은 1~3")
        return v


class LexiconCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    text: str
    now: datetime
    expected: ExpectedUnderstanding

    @field_validator("now")
    @classmethod
    def _aware(cls, v: datetime) -> datetime:
        return require_aware(v, "now")


@dataclass
class GoldenSet:
    seeds: list[SeedRecord]
    queries: list[GoldenQuery]
    lexicon_cases: list[LexiconCase]
    seed_lines: list[dict[str, Any]] = field(default_factory=list)
    challenge_query_ids: set[str] = field(default_factory=set)

    def seed_user(self) -> dict[str, str]:
        return {s.id: s.user_id for s in self.seeds}


def _read_jsonl[M: BaseModel](path: Path, model: type[M], errors: list[str]) -> tuple[list[M], list[dict[str, Any]]]:
    out: list[M] = []
    raw: list[dict[str, Any]] = []
    if not path.exists():
        errors.append(f"{path}: 파일이 없습니다")
        return out, raw
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
            out.append(model.model_validate(obj))
            raw.append(obj)
        except (json.JSONDecodeError, ValidationError) as exc:
            errors.append(f"{path.name}:{lineno}: {str(exc).splitlines()[0]}")
    return out, raw


def load_golden(
    seeds_path: Path,
    queries_path: Path,
    lexicon_path: Path,
    challenge_path: Path | None = None,
) -> tuple[GoldenSet, list[str]]:
    errors: list[str] = []
    seeds, seed_raw = _read_jsonl(seeds_path, SeedRecord, errors)
    queries, _ = _read_jsonl(queries_path, GoldenQuery, errors)
    challenge_queries: list[GoldenQuery] = []
    if challenge_path is not None:
        challenge_queries, _ = _read_jsonl(challenge_path, GoldenQuery, errors)
    cases, _ = _read_jsonl(lexicon_path, LexiconCase, errors)
    return GoldenSet(
        seeds=seeds,
        queries=[*queries, *challenge_queries],
        lexicon_cases=cases,
        seed_lines=seed_raw,
        challenge_query_ids={q.id for q in challenge_queries},
    ), errors


def validate_golden(gs: GoldenSet, *, enforce_sizes: bool = True) -> list[str]:
    """3.1.5절 규칙. 위반 메시지 목록을 돌려준다 (비면 통과)."""
    errors: list[str] = []
    # id 중복
    for name, ids in (
        ("seeds", [s.id for s in gs.seeds]),
        ("queries", [q.id for q in gs.queries]),
        ("lexicon_cases", [c.id for c in gs.lexicon_cases]),
    ):
        dup = sorted(k for k, v in Counter(ids).items() if v > 1)
        if dup:
            errors.append(f"{name}: id 중복 {dup[:10]}")
    # 시드 → 번들 검증 (도메인 규칙)
    for s in gs.seeds:
        try:
            s.to_bundle()
        except (ValidationError, ContentValidationError, ValueError) as exc:
            errors.append(f"seed {s.id}: {str(exc).splitlines()[0]}")
    # 관련도 id 존재 + 사용자 일치
    owner = gs.seed_user()
    for q in gs.queries:
        for cid in q.relevance:
            if cid not in owner:
                errors.append(f"{q.id}: relevance id {cid}가 seeds에 없습니다")
            elif owner[cid] != q.user_id:
                errors.append(f"{q.id}: relevance id {cid}의 user_id가 질의 사용자와 다릅니다")
        is_negative = "negative" in q.categories
        if is_negative and q.relevance:
            errors.append(f"{q.id}: negative 질의는 relevance가 비어야 합니다")
        if not is_negative and not q.relevance:
            errors.append(f"{q.id}: 정답 없는 질의는 negative 카테고리여야 합니다")
        if "filter_conflict" in q.categories and q.request_filters is None:
            errors.append(f"{q.id}: filter_conflict 질의에는 request_filters가 필요합니다")
        if q.id in gs.challenge_query_ids:
            if q.review_status == "ai_draft_unreviewed":
                errors.append(f"{q.id}: challenge는 needs_human_review 또는 human_reviewed여야 합니다")
            if q.template_id is None or q.entity_id is None or q.challenge_kind is None:
                errors.append(f"{q.id}: challenge에는 template_id, entity_id, challenge_kind가 필요합니다")
    # 같은 템플릿 또는 엔티티 변형을 다른 split에 두지 않는 group split.
    for field_name in ("template_id", "entity_id"):
        grouped: dict[str, set[str]] = {}
        for q in gs.queries:
            value = getattr(q, field_name)
            if value is not None:
                grouped.setdefault(value, set()).add(q.split)
        for value, splits in sorted(grouped.items()):
            if len(splits) > 1:
                errors.append(f"group split 위반: {field_name}={value}가 {sorted(splits)}에 나뉘어 있습니다")
    # 미래 저장물 금지
    if gs.queries:
        eval_now = min(q.now for q in gs.queries)
        for s in gs.seeds:
            if s.saved_at > eval_now:
                errors.append(f"seed {s.id}: saved_at이 eval now({eval_now.isoformat()})보다 미래입니다")
    # 규모와 카테고리 최소 개수
    if enforce_sizes:
        if len(gs.seeds) < MIN_SEEDS:
            errors.append(f"seeds {len(gs.seeds)}건 < 최소 {MIN_SEEDS}")
        if len(gs.queries) < MIN_QUERIES:
            errors.append(f"queries {len(gs.queries)}건 < 최소 {MIN_QUERIES}")
        if len(gs.lexicon_cases) < MIN_LEXICON_CASES:
            errors.append(f"lexicon_cases {len(gs.lexicon_cases)}건 < 최소 {MIN_LEXICON_CASES}")
        counts: Counter[str] = Counter(c for q in gs.queries for c in q.categories)
        for cat, minimum in CATEGORY_MINIMUMS.items():
            if counts.get(cat, 0) < minimum:
                errors.append(f"카테고리 {cat}: {counts.get(cat, 0)}개 < 최소 {minimum}")
        for cat, split_minimums in CATEGORY_SPLIT_MINIMUMS.items():
            for split, minimum in split_minimums.items():
                count = sum(cat in q.categories and q.split == split for q in gs.queries)
                if count < minimum:
                    errors.append(f"카테고리 {cat}/{split}: {count}개 < 최소 {minimum}")
    return errors


def load_and_validate(
    seeds_path: Path,
    queries_path: Path,
    lexicon_path: Path,
    challenge_path: Path | None = None,
) -> GoldenSet:
    gs, errors = load_golden(seeds_path, queries_path, lexicon_path, challenge_path)
    errors += validate_golden(gs)
    if errors:
        raise GoldenSetError("골든셋 검증 실패", {"errors": errors})
    return gs

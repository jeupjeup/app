"""T1: 도메인 모델, 세부 태그 스키마, merge patch, 유효 태그."""

from __future__ import annotations

import copy
from typing import Any

import pytest
from pydantic import ValidationError

from jupjup.domain.errors import ContentValidationError
from jupjup.domain.models import (
    DetailTags,
    SeedRecord,
    Summary,
    Tag,
    effective_tags,
    merge_patch,
    normalize_tag_name,
    pick_effective_summary,
)

BASE: dict[str, Any] = {
    "id": "c_alice_0001",
    "user_id": "u_alice",
    "source_url": "https://www.instagram.com/p/XXXX/",
    "platform": "instagram",
    "content_type": "post",
    "title": "성수 어니언 신메뉴",
    "author": "@onion_seongsu",
    "published_at": "2026-09-10T09:00:00+09:00",
    "saved_at": "2026-09-12T21:13:00+09:00",
    "original_status": "available",
    "user_note": "주말에 가보기",
    "snapshot": {
        "captured_at": "2026-09-12T21:13:05+09:00",
        "text": "성수동 어니언 가을 시즌 신메뉴",
        "ocr_text": None,
    },
    "summary": {"text": "성수동 카페 어니언의 가을 신메뉴 소개 게시물.", "model": "human", "version": 1},
    "tags": [
        {"name": "성수동", "source": "ai", "confidence": 0.95},
        {"name": "카페", "source": "ai", "confidence": 0.97},
        {"name": "주말데이트", "source": "user"},
    ],
    "hidden_tags": ["빵집"],
    "detail_tags": {
        "schema_version": 1,
        "category": "food_drink",
        "locations": [{"name": "성수동", "level": "neighborhood"}],
    },
    "meta": {"authored_by": "human"},
}


def _rec(**patch: Any) -> dict[str, Any]:
    d = copy.deepcopy(BASE)
    for k, v in patch.items():
        if v is _DEL:
            d.pop(k, None)
        else:
            d[k] = v
    return d


_DEL = object()

VALID_CASES = [
    _rec(),
    _rec(source_url=None),
    _rec(source_url="http://example.com/a"),
    _rec(platform="kakaotalk", content_type="message", source_url=None),
    _rec(platform="kakaotalk", content_type="image", source_url=None),
    _rec(original_status="deleted"),
    _rec(title=None),
    _rec(snapshot=None, summary=None),
    _rec(tags=[]),
    _rec(detail_tags=None),
    _rec(published_at=None),
    _rec(
        platform="local",
        content_type="image",
        source_url=None,
        snapshot={"text": "", "ocr_text": "제주 애월 숙소 예약 확인"},
    ),
    _rec(summaries=[{"text": "사용자가 고친 요약", "source": "user", "version": 1}]),
]

INVALID_CASES = [
    ("naive saved_at", _rec(saved_at="2026-09-12T21:13:00")),
    ("bad user id", _rec(user_id="alice")),
    ("bad user id upper", _rec(user_id="u_Alice")),
    ("ftp url", _rec(source_url="ftp://example.com/x")),
    ("javascript url", _rec(source_url="javascript:alert(1)")),
    ("kakaotalk post", _rec(platform="kakaotalk", content_type="post")),
    ("unknown platform", _rec(platform="tiktok")),
    ("unknown type", _rec(content_type="podcast")),
    ("unknown status", _rec(original_status="gone")),
    ("extra field", _rec(unexpected=1)),
    ("empty id", _rec(id="")),
    ("bad id chars", _rec(id="c alice/1")),
    ("note too long", _rec(user_note="가" * 2001)),
    ("tag source", _rec(tags=[{"name": "카페", "source": "bot"}])),
    ("empty tag", _rec(tags=[{"name": "#  ", "source": "ai"}])),
    ("confidence > 1", _rec(tags=[{"name": "카페", "source": "ai", "confidence": 1.5}])),
    ("too many effective tags", _rec(tags=[{"name": f"태그{i}", "source": "ai"} for i in range(16)])),
    ("summary empty", _rec(summary={"text": "", "version": 1})),
]

INVALID_DETAIL = [
    ("missing schema_version", {"category": "food_drink"}),
    ("wrong schema_version", {"schema_version": 2}),
    ("unknown category", {"schema_version": 1, "category": "sports"}),
    ("extra key", {"schema_version": 1, "foo": 1}),
    ("entity type", {"schema_version": 1, "entities": [{"type": "animal", "name": "x"}]}),
    ("topic too long", {"schema_version": 1, "topics": ["가" * 31]}),
    ("attributes non-string", {"schema_version": 1, "attributes": {"price": 3}}),
]


@pytest.mark.parametrize("record", VALID_CASES)
def test_valid_seeds_parse(record: dict[str, Any]) -> None:
    bundle = SeedRecord.model_validate(record).to_bundle()
    assert bundle.content.id == "c_alice_0001"
    assert bundle.content.saved_at.tzinfo is not None


@pytest.mark.parametrize(("name", "record"), INVALID_CASES, ids=[c[0] for c in INVALID_CASES])
def test_invalid_seeds_rejected(name: str, record: dict[str, Any]) -> None:
    with pytest.raises((ValidationError, ContentValidationError)):
        SeedRecord.model_validate(record).to_bundle()


@pytest.mark.parametrize(("name", "detail"), INVALID_DETAIL, ids=[c[0] for c in INVALID_DETAIL])
def test_invalid_detail_tags(name: str, detail: dict[str, Any]) -> None:
    with pytest.raises(ContentValidationError):
        SeedRecord.model_validate(_rec(detail_tags=detail)).to_bundle()


def test_merge_patch_overwrite_and_delete() -> None:
    target = {"a": 1, "b": {"c": 2, "d": 3}, "e": [1, 2]}
    patch = {"a": 9, "b": {"c": None, "x": 5}, "e": [3], "new": "v"}
    out = merge_patch(target, patch)
    assert out == {"a": 9, "b": {"d": 3, "x": 5}, "e": [3], "new": "v"}
    assert target == {"a": 1, "b": {"c": 2, "d": 3}, "e": [1, 2]}  # 입력 불변


def test_merge_patch_rfc7386_examples() -> None:
    assert merge_patch({"a": "b"}, {"a": "c"}) == {"a": "c"}
    assert merge_patch({"a": "b"}, {"b": "c"}) == {"a": "b", "b": "c"}
    assert merge_patch({"a": "b"}, {"a": None}) == {}
    assert merge_patch({"a": [{"b": "c"}]}, {"a": [1]}) == {"a": [1]}
    assert merge_patch(["a", "b"], ["c", "d"]) == ["c", "d"]
    assert merge_patch({"a": "foo"}, None) is None
    assert merge_patch({"e": None}, {"a": 1}) == {"e": None, "a": 1}
    assert merge_patch([1, 2], {"a": "b", "c": None}) == {"a": "b"}


def test_detail_tags_user_patch_wins() -> None:
    d = DetailTags(
        content_id="c1",
        ai_json={"schema_version": 1, "category": "food_drink", "topics": ["카페"], "purpose": ["데이트"]},
        user_patch={"category": "place_travel", "purpose": None},
    )
    eff = d.effective()
    assert eff["category"] == "place_travel"
    assert "purpose" not in eff
    assert eff["topics"] == ["카페"]


def test_detail_tags_patch_validated() -> None:
    with pytest.raises(ContentValidationError):
        DetailTags(content_id="c1", ai_json={"schema_version": 1}, user_patch={"category": "nope"})


def test_effective_tags_rules() -> None:
    tags = [
        Tag(name="성수동", source="ai", confidence=0.9),
        Tag(name="빵집", source="ai", confidence=0.8),
        Tag(name="카페", source="ai", confidence=0.7),
        Tag(name="카페", source="user"),
        Tag(name="데이트", source="user"),
    ]
    eff = effective_tags(tags, hidden_tags=["#빵집"])
    assert [(t.name, t.source) for t in eff] == [("카페", "user"), ("데이트", "user"), ("성수동", "ai")]


def test_tag_name_normalization() -> None:
    assert normalize_tag_name("#성수 동 ") == "성수동"
    assert normalize_tag_name("ＣＡＦＥ") == "CAFE"
    assert len(normalize_tag_name("가" * 40)) == 30


def test_user_summary_preferred(now: Any) -> None:
    ai_new = Summary(id="s2", content_id="c", version=3, text="AI 최신", source="ai", created_at=now)
    user_old = Summary(id="s1", content_id="c", version=1, text="사용자", source="user", created_at=now)
    assert pick_effective_summary([ai_new, user_old]) is user_old
    assert pick_effective_summary([ai_new]) is ai_new
    assert pick_effective_summary([]) is None


def test_seed_hidden_and_user_summary_bundle() -> None:
    rec = _rec(summaries=[{"text": "사용자가 고친 요약", "source": "user", "version": 1}])
    bundle = SeedRecord.model_validate(rec).to_bundle()
    assert bundle.summary is not None and bundle.summary.source == "user"
    assert "빵집" in bundle.content.hidden_tags


def test_snapshot_truncation_and_hash() -> None:
    rec = _rec(snapshot={"text": "가" * 100_005})
    bundle = SeedRecord.model_validate(rec).to_bundle()
    assert bundle.snapshot is not None
    assert bundle.snapshot.truncated and len(bundle.snapshot.text) == 100_000
    assert len(bundle.snapshot.content_hash) == 64


def test_published_after_saved_only_warns() -> None:
    rec = _rec(published_at="2026-09-20T00:00:00+09:00")
    with pytest.warns(UserWarning):
        SeedRecord.model_validate(rec).to_bundle()

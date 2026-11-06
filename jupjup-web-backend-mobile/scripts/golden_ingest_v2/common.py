"""Record helper for the hand-written ingest golden v2 (T25c).

모든 원문과 gold는 이 저장소용으로 직접 쓴 합성 데이터다. 실존 인물·실제 게시물을 옮기지 않았다.
상호·인물·단체 이름은 지어낸 것이고, 지명(동네·도시)만 실제 지명을 쓴다.
"""

from __future__ import annotations

from typing import Any

Entity = tuple[str, str]
Location = tuple[str, str]


def rec(
    key: str,
    split: str,
    title: str,
    *,
    text: str | None = None,
    ocr_text: str | None = None,
    fixture: dict[str, Any] | None = None,
    tags: list[str],
    acceptable_tags: list[str] | None = None,
    entities: list[Entity] | None = None,
    locations: list[Location] | None = None,
    category: str,
    intents: list[str],
    acceptable_intents: list[str] | None = None,
    key_facts: list[str],
    forbidden: list[str] | None = None,
    difficult: list[str] | None = None,
    mock_failure: str | None = None,
    injection_target: str | None = None,
    platform: str | None = None,
    content_type: str | None = None,
) -> dict[str, Any]:
    """One authored record. ``fixture`` is ``{"kind": "youtube"|"url", "name": ..., "body": ...}``."""
    assert split in {"dev", "test"}, key
    assert (text is not None) + (ocr_text is not None) + (fixture is not None) == 1, key
    return {
        "key": key,
        "split": split,
        "title": title,
        "text": text,
        "ocr_text": ocr_text,
        "fixture": fixture,
        "platform": platform,
        "content_type": content_type,
        "difficult_cases": list(difficult or []),
        "mock_failure": mock_failure,
        "injection_target": injection_target,
        "gold": {
            "representative_tags": tags,
            "acceptable_tags": list(acceptable_tags or []),
            "entities": [{"type": kind, "name": name} for kind, name in (entities or [])],
            "locations": [
                {"name": name, "level": level} if level else {"name": name} for name, level in (locations or [])
            ],
            "category": category,
            "save_intent": {"labels": intents, "acceptable": list(acceptable_intents or [])},
            "key_facts": key_facts,
            "forbidden_claims": list(forbidden or []),
        },
    }

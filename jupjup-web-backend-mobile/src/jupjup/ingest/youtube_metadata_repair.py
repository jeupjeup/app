"""Deterministic, source-grounded repairs for YouTube metadata LLM output only."""

from __future__ import annotations

import copy
import re
from typing import Any

_TAG_TOKEN = re.compile(r"[가-힣A-Za-z0-9+]+")
_HASHTAG = re.compile(r"(?<![\w#])#([가-힣A-Za-z0-9_]+)")
_PARTICLES = (
    "으로부터", "에게서", "으로", "에서", "에게", "까지", "부터", "처럼", "보다", "하고", "이나", "이랑",
    "은", "는", "이", "가", "을", "를", "과", "와", "도", "의", "에", "로", "만", "랑", "나",
)
_ENDINGS = ("했습니다", "됩니다", "입니다", "합니다", "있습니다", "없습니다", "했어요", "돼요", "해요", "한다", "했다")
_STOPWORDS = frozenset(
    {
        "모든", "결국", "저", "그", "이", "것", "수", "통", "소개", "정보", "내용", "영상", "오늘", "주제",
        "방법", "유튜브", "youtube", "afreecatv", "twitch", "숲", "ncs", "nocopyrightsounds", "music",
        "track", "song", "release", "provided", "official", "free", "download", "stream", "feat", "the",
        "and", "a", "an", "of", "by",
    }
)
_PROCEDURE_CUES = (
    "how-to", "how to", "tutorial", "recipe", "step-by-step", "ingredients", "레시피", "만드는 법", "만드는법",
    "만들기", "사용법", "튜토리얼", "강좌", "단계별", "따라하기", "설치 방법", "설정 방법", "하는 법",
)
_GAME_CUES = ("발로란트", "valorant", "gameplay", "gaming", "game play", "게임", "게이밍", "랭크", "e스포츠")
_MUSIC_CUES = (
    "music", "song", "album", "feat.", "ncs release", "곡", "가수", "음악", "노래", "앨범", "작곡", "뮤직",
)


def _normalize(value: str) -> str:
    return "".join(value.casefold().split())


def _usable(tag: str) -> bool:
    normalized = tag.casefold().strip().lstrip("#")
    return len(normalized) >= 2 and normalized not in _STOPWORDS and not normalized.isdigit()


def _title_text(source: str) -> str:
    for line in source.splitlines():
        if line.startswith("제목:"):
            return line.removeprefix("제목:").strip()
    return ""


def _title_hashtag_input(source: str) -> tuple[str, list[str]] | None:
    """Return title and hashtags only when every selected source block is one of those."""
    title = ""
    hashtags: list[str] = []
    for line in source.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("제목:") and not title:
            title = stripped.removeprefix("제목:").strip()
            continue
        if stripped.startswith("설명:"):
            stripped = stripped.removeprefix("설명:").strip()
        matches = list(_HASHTAG.finditer(stripped))
        if not matches or "".join(match.group(0) for match in matches) != re.sub(r"\s+", "", stripped):
            return None
        hashtags.extend(match.group(1) for match in matches)
    if not title or not hashtags:
        return None
    return title, list(dict.fromkeys(hashtags))


def _exact_entities(value: Any, source: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [
        item for item in value
        if isinstance(item, dict)
        and isinstance(item.get("name"), str)
        and item["name"]
        and item["name"] in source
    ][:20]


def _repair_title_hashtag_output(payload: dict[str, Any], source: str, title: str, hashtags: list[str]) -> None:
    topic = hashtags[0]
    payload["summary"] = (
        f"제목·설명 기준으로, 이 영상은 {topic} 관련 콘텐츠입니다. "
        f"제목은 '{title}'이며 설명에는 "
        f"{', '.join(f'#{tag}' for tag in hashtags)}가 표시되어 있습니다."
    )
    detail = payload.get("detail_tags")
    if not isinstance(detail, dict):
        detail = {"schema_version": 1}
        payload["detail_tags"] = detail
    grounded = _grounded_tags(payload, source)
    detail["topics"] = [topic]
    detail["keywords"] = grounded[:6]
    detail["entities"] = _exact_entities(detail.get("entities"), source)
    detail["purpose"] = ["정보보관"]
    detail["save_intent"] = {"labels": ["정보보관"], "confidence": 0.3, "inferred": True}
    # The title+hashtag path has very little evidence; retain only fields we
    # explicitly ground or deterministically repair here.
    payload["detail_tags"] = {
        "schema_version": detail.get("schema_version", 1),
        **({"category": detail["category"]} if "category" in detail else {}),
        "topics": detail["topics"],
        "keywords": detail["keywords"],
        "entities": detail["entities"],
        "locations": [],
        "purpose": detail["purpose"],
        "save_intent": detail["save_intent"],
    }
    payload["save_intent"] = {
        "labels": ["정보보관"],
        "confidence": 0.3,
        "rationale": "제목과 해시태그를 보관합니다.",
    }


def _title_terms(title: str) -> list[str]:
    terms: list[str] = []
    for match in _TAG_TOKEN.findall(title):
        term = match
        for suffix in _ENDINGS:
            if term.endswith(suffix):
                term = term.removesuffix(suffix)
                break
        else:
            for suffix in _PARTICLES:
                if term.endswith(suffix):
                    term = term.removesuffix(suffix)
                    break
        if _usable(term) and term.casefold() not in _STOPWORDS:
            terms.append(term)
    return terms


def _grounded_tags(payload: dict[str, Any], source: str) -> list[str]:
    normalized_source = _normalize(source)
    candidates: list[str] = []

    def add(value: str) -> None:
        tag = value.strip().lstrip("#").strip()
        duplicate = tag.casefold() in {candidate.casefold() for candidate in candidates}
        if _usable(tag) and _normalize(tag) in normalized_source and not duplicate:
            candidates.append(tag)

    for match in _HASHTAG.finditer(source):
        add(match.group(1))
        if len(candidates) >= 3:
            return candidates[:7]

    existing = payload.get("representative_tags")
    if isinstance(existing, list):
        for value in existing:
            if isinstance(value, str):
                add(value)
                if len(candidates) >= 3:
                    return candidates[:7]

    for term in _title_terms(_title_text(source)):
        add(term)
        if len(candidates) >= 3:
            break
    return candidates[:7]


def _has_procedure(source: str) -> bool:
    folded = source.casefold()
    return any(cue.casefold() in folded for cue in _PROCEDURE_CUES)


def _clear_game_or_music_topic(source: str) -> bool:
    folded = source.casefold()
    cues = (*_GAME_CUES, *_MUSIC_CUES)
    return any(cue.casefold() in folded for cue in cues)


def repair_metadata_output(payload: dict[str, Any], source: str) -> dict[str, Any]:
    """Repair title/hashtag-only metadata and grounded tags without changing other analyses."""
    repaired = copy.deepcopy(payload)
    focused = _title_hashtag_input(source)
    if focused is not None:
        _repair_title_hashtag_output(repaired, source, *focused)
    tags = _grounded_tags(repaired, source)
    if len(tags) >= 3:
        repaired["representative_tags"] = tags

    detail = repaired.get("detail_tags")
    if (
        isinstance(detail, dict)
        and detail.get("category") == "howto_recipe"
        and not _has_procedure(source)
        and _clear_game_or_music_topic(source)
    ):
        detail["category"] = "culture_media"
    return repaired

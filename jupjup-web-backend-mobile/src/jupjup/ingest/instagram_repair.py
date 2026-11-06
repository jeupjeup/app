"""Conservative deterministic projection of Instagram metadata generation."""

from __future__ import annotations

import re
from typing import Any

from jupjup.domain.errors import AnalysisSchemaError
from jupjup.ingest.instagram import InstagramMetadata


def repair_instagram_output(payload: dict[str, Any], metadata: InstagramMetadata) -> dict[str, Any]:
    source = metadata.text()
    # Hashtags first, then ASCII-only handles, then title/caption words, all verbatim from metadata.
    words = r"[^\W_][\w+.-]*"
    candidates = [
        *re.findall(r"(?<!\w)#(\w+)", source),
        *re.findall(r"(?<!\w)@([A-Za-z0-9._]+)", source),
        *re.findall(words, metadata.title),
        *re.findall(words, metadata.caption),
    ]
    tags: list[str] = []
    for tag in candidates:
        tag = tag.strip(".-+")
        if not 2 <= len(tag) <= 20 or tag.casefold() in {"instagram", "인스타그램", "https", "http", "www"}:
            continue
        # Skip particle-attached variants of an existing tag (e.g. 성수에서 after 성수).
        if not any(tag.casefold().startswith(value.casefold()) for value in tags):
            tags.append(tag)
        if len(tags) == 7:
            break
    if len(tags) < 3:
        raise AnalysisSchemaError("Instagram metadata에 근거 태그가 충분하지 않습니다")
    basis = "제목만" if metadata.basis == "title_only" else "제목·caption" if metadata.title else "caption만"
    # All generated facts/optional fields are discarded. The excerpt remains an explicitly attributed quote.
    excerpt = re.split(r"[.!?。！？]+(?:\s|$)", source[:280], maxsplit=1)[0]
    summary = f"공개 Instagram {basis} 기준 기록입니다. metadata 원문 발췌: 「{excerpt}」"
    return {
        "summary": summary,
        "representative_tags": tags,
        "detail_tags": {"schema_version": 1, "category": "other", "topics": tags, "keywords": tags,
                        "entities": [], "locations": [], "purpose": ["정보보관"]},
        "save_intent": {"labels": ["정보보관"], "confidence": 0.0, "rationale": "공개 metadata만 보관합니다."},
        "title_suggestion": metadata.title[:80] or None,
        "language": "ko" if re.search(r"[가-힣]", source) else "en",
        "evidence": [{"claim": "공개 metadata 원문", "source_span": source[:200]}],
    }

"""explain=False 검색 응답의 결정적 부분을 해시로 고정하는 도우미.

query_id(무작위)와 timing_ms(실행 시간)만 빼고 SearchResult 전체를 정렬된 JSON으로 직렬화한다.
기준선 파일은 trace 작업 전 코드(HEAD e5f72b8)로 만들었다.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from jupjup.container import AppContainer
from jupjup.domain.errors import JupjupError
from jupjup.search.filters import SearchFilters
from jupjup.search.service import SearchRequest

GOLDEN = Path(__file__).resolve().parents[2] / "data" / "golden"
QUERY_FILES = ("queries.jsonl", "challenge_queries.jsonl")


def golden_queries() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name in QUERY_FILES:
        for line in (GOLDEN / name).read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    return rows


def result_digest(container: AppContainer, row: dict[str, Any], *, explain: bool = False) -> str:
    filters = SearchFilters.model_validate(row["request_filters"]) if row.get("request_filters") else None
    try:
        result = container.search.search(
            SearchRequest(
                user_id=row["user_id"],
                query=row["query"],
                filters=filters,
                now=datetime.fromisoformat(row["now"]),
                explain=explain,
            )
        )
    except JupjupError as exc:
        payload: object = {"error": exc.code}
    else:
        payload = result.model_dump(mode="json", exclude={"query_id", "timing_ms"})
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

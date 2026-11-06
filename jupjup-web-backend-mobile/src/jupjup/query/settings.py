"""질의 해석에서 공유하는 결정적 규칙과 기본값.

언어 자체의 규칙(조사, 어미, 정규식)은 각 해석기에 두고, 품질 튜닝으로 바뀔 수 있는
숫자 값만 ``SearchSettings.query``를 통해 한 곳에서 주입한다.
"""

from __future__ import annotations

from pydantic import BaseModel

DEFAULT_TIME_MARGINS: dict[str, tuple[int, int]] = {
    "day": (1, 3),
    "week": (3, 7),
    "month": (7, 14),
    "recent": (7, 14),
    "season": (14, 30),
    "part_of_year": (14, 30),
    "year": (30, 60),
}


class QuerySettings(BaseModel):
    """질의 이해·교정 모듈이 함께 쓰는 튜닝 값."""

    max_length: int = 200
    minimum_term_length: int = 2
    latin_spelling_min_length: int = 3
    long_spelling_term_length: int = 4
    short_spelling_distance: int = 1
    long_spelling_distance: int = 2
    # 2음절 자동 교정 허용 조건: 다른 원형 용어와의 공기 비율과 정규형 증거 수준의 신뢰도
    short_spelling_min_context: float = 0.50
    short_spelling_min_confidence: float = 0.90
    facet_fuzzy_min_length: int = 3
    facet_fuzzy_distance: int = 1
    ambiguous_keyword_max: int = 1
    assistant_timeout_s: float = 1.5
    assistant_max_tokens: int = 300

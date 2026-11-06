"""용어 목록에 공통으로 적용하는 작은 결정적 변환."""

from __future__ import annotations

from collections.abc import Iterable


def unique_strings(values: Iterable[str]) -> list[str]:
    """빈 문자열을 버리고 첫 등장 순서를 유지하며 중복을 제거한다."""
    return list(dict.fromkeys(value for value in values if value))

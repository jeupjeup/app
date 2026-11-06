"""LLM 제공자 인터페이스와 결정적 Mock (설계서 5.8.4절, 5.10.8절 확장판).

실제 제공자(AnthropicLLM)는 T17 범위라 이번 증분에는 없다. 기본 설정은 네트워크를 쓰지 않는다.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any, Protocol

from pydantic import BaseModel, ValidationError

from jupjup.domain.errors import LLMProviderError


class LLMRawResponse(BaseModel):
    text: str
    stop_reason: str = "end_turn"
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0


class LLMClient(Protocol):
    model_id: str

    def complete_json(
        self,
        system: str,
        user: str,
        schema: type[BaseModel],
        timeout_s: float,
        max_tokens: int = 4000,
        effort: str | None = None,
    ) -> LLMRawResponse: ...

    def count_tokens(self, system: str, user: str) -> int | None: ...


def prompt_hash(system: str, user: str) -> str:
    return hashlib.sha256((system + "\x00" + user).encode("utf-8")).hexdigest()


class MockLLM:
    """입력 해시로 미리 정한 응답을 돌려준다. 등록이 없으면 스키마의 빈 결과(기본값)를 돌려준다.

    fixtures 값: dict(JSON으로 직렬화) | str(그대로) | Exception 인스턴스(그 예외를 던짐).
    """

    model_id = "mock-llm-v1"

    def __init__(self, fixtures: Mapping[str, Any] | None = None) -> None:
        self.fixtures: dict[str, Any] = dict(fixtures or {})
        self.calls: list[str] = []

    def complete_json(
        self,
        system: str,
        user: str,
        schema: type[BaseModel],
        timeout_s: float,
        max_tokens: int = 4000,
        effort: str | None = None,
    ) -> LLMRawResponse:
        key = prompt_hash(system, user)
        self.calls.append(key)
        value = self.fixtures.get(key)
        if isinstance(value, BaseException):
            raise value
        if value is None:
            try:
                text = schema().model_dump_json()
            except ValidationError:
                text = "{}"
        elif isinstance(value, str):
            text = value
        else:
            text = json.dumps(value, ensure_ascii=False)
        return LLMRawResponse(text=text, input_tokens=len(system) + len(user), output_tokens=len(text))

    def count_tokens(self, system: str, user: str) -> int | None:
        return None


def parse_json_response(raw: LLMRawResponse, schema: type[BaseModel]) -> BaseModel:
    """간단 검증 (검색 경로 보조용). 인제스트는 validate_and_repair를 쓴다."""
    try:
        return schema.model_validate_json(raw.text)
    except ValidationError as exc:
        raise LLMProviderError("LLM 응답이 스키마와 맞지 않습니다", {"errors": exc.error_count()}) from exc

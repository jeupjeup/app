"""Deterministic, network-free analyzer used by the dev API, CLI, and worker in every mode.

The real LLM analyzer is T25. Until then the runtime needs an analyzer that works on
arbitrary submitted text, not only on golden fixtures, so this one derives a fixture
from the source text and then runs it through ``MockAnalyzer`` so that the T18
validate-and-repair path is still exercised.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from jupjup.ingest.analyzer import AnalysisRunMeta, MockAnalyzer
from jupjup.ingest.chunking import AnalysisInput
from jupjup.ingest.schemas import AnalysisOutput
from jupjup.ingest.validation import AnalysisValidator, is_iso_639_1
from jupjup.text.normalize import normalize_text
from jupjup.text.tokenizer import KiwiTokenizer

_FALLBACK_TAGS = ("저장물", "메모", "자료")
_HANGUL = re.compile(r"[가-힣]")
_LATIN = re.compile(r"[A-Za-z]")
# 글자가 없는 본문(전화번호, 날짜, 금액 메모)의 언어. 이 서비스의 기본 언어다.
_DEFAULT_LANGUAGE = "ko"
_SENTENCE_PUNCT = re.compile(r"[.!?。！？]+")
_SPAN_CHARS = 60
_SNIPPET_CHARS = 80


class ExtractiveMockAnalyzer:
    """Build a grounded analysis from the source text (summary snippet, keyword tags, one evidence span)."""

    def __init__(
        self,
        tokenizer: KiwiTokenizer,
        validator: AnalysisValidator,
        *,
        profile_name: str = "mock",
        prompt_version: str = "analyze_v1",
    ) -> None:
        self._tokenizer = tokenizer
        self._validator = validator
        self.profile_name = profile_name
        self.prompt_version = prompt_version

    def analyze(self, inp: AnalysisInput) -> tuple[AnalysisOutput, AnalysisRunMeta]:
        text = self._source_text(inp)
        fixture = self.fixture_for(text, inp.meta.title, inp.meta.language)
        delegate = MockAnalyzer(
            {"default": fixture},
            validator=self._validator,
            profile_name=self.profile_name,
            prompt_version=self.prompt_version,
        )
        return delegate.analyze(inp)

    def fixture_for(self, text: str, title: str | None, language: str | None) -> dict[str, Any]:
        compact = " ".join(text.split())
        snippet = _SENTENCE_PUNCT.sub(" ", compact[:_SNIPPET_CHARS]).strip() or "내용 없음"
        tags = self._tags(compact)
        return {
            "summary": f"저장한 콘텐츠의 앞부분을 정리한 mock 요약입니다. 원문은 '{snippet}'(으)로 시작합니다.",
            "representative_tags": tags,
            "detail_tags": {"schema_version": 1, "category": "other", "topics": tags[:3]},
            "save_intent": {"labels": ["정보보관"], "confidence": 0.5, "rationale": "mock 분석기 기본값"},
            "title_suggestion": (title or compact)[:_SNIPPET_CHARS] or None,
            "language": _language(language, compact),
            "evidence": [{"claim": "원문 앞부분", "source_span": compact[:_SPAN_CHARS]}] if compact else [],
        }

    def _tags(self, text: str) -> list[str]:
        candidates = self._tokenizer.keyword_candidates(text[:2000], drop_bound_single=True)
        return _pick_tags(candidates)

    @staticmethod
    def _source_text(inp: AnalysisInput) -> str:
        if inp.mode == "single":
            return inp.text or ""
        return "\n\n".join(chunk.text for chunk in inp.chunks or [])


def _language(hint: str | None, text: str) -> str:
    """유효한 ISO 639-1 힌트는 그대로 쓰고, "und"·빈 값·잘못된 값은 문자로 추정한다."""
    code = (hint or "").strip().lower()
    if is_iso_639_1(code):
        return code
    if _HANGUL.search(text):
        return "ko"
    if _LATIN.search(text):
        return "en"
    return _DEFAULT_LANGUAGE


def _pick_tags(candidates: Sequence[str], limit: int = 5) -> list[str]:
    seen: set[str] = set()
    tags: list[str] = []
    for candidate in [*candidates, *_FALLBACK_TAGS]:
        tag = normalize_text(candidate).replace(" ", "")
        if len(tag) < 2 or len(tag) > 20 or tag in seen:
            continue
        seen.add(tag)
        tags.append(tag)
        if len(tags) == limit:
            break
    return tags

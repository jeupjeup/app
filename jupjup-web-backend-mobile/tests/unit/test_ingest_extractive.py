"""T23 runtime mock analyzer: deterministic, grounded, and valid for arbitrary text."""

from __future__ import annotations

import pytest

from jupjup.ingest.chunking import AnalysisInput, ContentMeta
from jupjup.ingest.extractive import ExtractiveMockAnalyzer, _pick_tags
from jupjup.ingest.validation import AnalysisValidator
from jupjup.text.lexicon import Lexicon
from jupjup.text.tokenizer import KiwiTokenizer


@pytest.fixture(scope="module")
def analyzer(lexicon: Lexicon, kiwi: KiwiTokenizer) -> ExtractiveMockAnalyzer:
    return ExtractiveMockAnalyzer(kiwi, AnalysisValidator(lexicon))


@pytest.mark.parametrize(
    ("text", "title", "language"),
    [
        ("성수동 독립 서점이 문을 열었습니다. 주말에는 작가와의 대화가 열립니다!", None, "ko"),
        ("A short English note about sourdough starters. Feed it daily.", None, "en"),
        ("가", "t" * 200, None),
        ("마침표. 가 많은. 문장. 입니다. 정말. 많아요. 계속. 이어집니다.", None, None),
    ],
)
def test_output_is_valid_grounded_and_deterministic(
    analyzer: ExtractiveMockAnalyzer, text: str, title: str | None, language: str | None
) -> None:
    inp = AnalysisInput(mode="single", text=text, meta=ContentMeta(source_id="c_x", title=title, language=language))
    output, meta = analyzer.analyze(inp)
    again, _ = analyzer.analyze(inp)
    assert output == again
    assert meta.first_pass_ok and meta.model == "mock-analyzer-v1"
    assert 3 <= len(output.representative_tags) <= 7
    assert output.title_suggestion is None or len(output.title_suggestion) <= 80
    assert all(" ".join(text.split()).startswith(item.source_span) for item in output.evidence)
    if language is not None:
        assert output.language == language


def test_map_reduce_input_uses_chunk_text(analyzer: ExtractiveMockAnalyzer) -> None:
    from jupjup.ingest.chunking import AnalysisChunk

    texts = ["은하수조약돌 관찰 기록입니다.", "청동나침반 전시 입장권도 함께 보관합니다."]
    chunks = [
        AnalysisChunk(index=i, text=t, token_count=len(t), start_char=i * 100, end_char=i * 100 + len(t))
        for i, t in enumerate(texts)
    ]
    inp = AnalysisInput(mode="map_reduce", chunks=chunks, total_chunks=2, meta=ContentMeta(source_id="c_y"))
    output, meta = analyzer.analyze(inp)
    assert meta.first_pass_ok
    assert "은하수조약돌" in output.representative_tags
    assert output.evidence[0].source_span.startswith("은하수조약돌")


def test_pick_tags_pads_with_fallbacks_and_dedupes() -> None:
    assert _pick_tags([]) == ["저장물", "메모", "자료"]
    assert _pick_tags(["서점", "서점", "a", "x" * 21, "Book Store"]) == ["서점", "bookstore", "저장물", "메모", "자료"]


# --- T23 loop 1 M1: 숫자·기호만 있는 본문과 "und" 언어도 유효한 분석을 낸다 ---


@pytest.mark.parametrize("text", ["1234567890", "010-1234-5678", "2026-10-20", "$$$ 100", "12:30 / 3,000"])
def test_text_without_letters_is_analyzed_first_pass(analyzer: ExtractiveMockAnalyzer, text: str) -> None:
    inp = AnalysisInput(mode="single", text=text, meta=ContentMeta(source_id="c_num", language="und"))
    output, meta = analyzer.analyze(inp)
    assert meta.first_pass_ok and not meta.partial
    assert output.language == "ko"


@pytest.mark.parametrize(
    ("language", "text", "expected"),
    [
        ("und", "A short English note about sourdough.", "en"),
        ("und", "성수동 카페 메모입니다.", "ko"),
        (" EN ", "성수동 카페 메모입니다.", "en"),
        ("korean", "성수동 카페 메모입니다.", "ko"),
        ("", "1234", "ko"),
        (None, "1234", "ko"),
    ],
)
def test_language_hint_is_normalized_or_replaced(
    analyzer: ExtractiveMockAnalyzer, language: str | None, text: str, expected: str
) -> None:
    assert analyzer.fixture_for(text, None, language)["language"] == expected

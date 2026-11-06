"""T20 deterministic analysis chunk planning."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from jupjup.domain.models import Snapshot
from jupjup.ingest.chunking import AnalysisInput, ChunkSettings, ContentMeta, chunk_for_analysis

NOW = datetime(2026, 10, 20, tzinfo=UTC)
META = ContentMeta(title="테스트", platform="web", content_type="article", language="ko")


def _snapshot(text: str = "", *, ocr_text: str | None = None) -> Snapshot:
    return Snapshot(id="s_t20", content_id="c_t20", captured_at=NOW, text=text, ocr_text=ocr_text)


def test_exactly_single_max_tokens_stays_single() -> None:
    result = chunk_for_analysis(_snapshot("가" * 12_000), META, ChunkSettings())

    assert result.mode == "single"
    assert result.text == "가" * 12_000
    assert result.chunks is None
    assert result.coverage == "full"
    assert result.source_token_count == 12_000


def test_one_token_over_boundary_uses_map_reduce() -> None:
    result = chunk_for_analysis(_snapshot("가" * 12_001), META, ChunkSettings())

    assert result.mode == "map_reduce"
    assert result.text is None
    assert result.chunks is not None
    assert len(result.chunks) == 5
    assert result.total_chunks == 5
    assert result.coverage == "full"


def test_structural_units_are_preferred_over_cutting_paragraphs() -> None:
    paragraphs = [character * 900 for character in "가나다라"]
    source = "\n\n".join(paragraphs)
    settings = ChunkSettings(single_max_tokens=1_000, chunk_target_tokens=2_000, overlap_tokens=0)

    result = chunk_for_analysis(_snapshot(source), META, settings)

    assert result.chunks is not None
    assert [chunk.text for chunk in result.chunks] == ["\n\n".join(paragraphs[:2]), "\n\n".join(paragraphs[2:])]
    chunk_parts = {part for chunk in result.chunks for part in chunk.text.split("\n\n")}
    assert all(paragraph in chunk_parts for paragraph in paragraphs)


def test_oversized_structural_unit_splits_at_sentence_boundary() -> None:
    sentence = "가" * 40 + ". "
    source = sentence * 8
    settings = ChunkSettings(single_max_tokens=100, chunk_target_tokens=100, overlap_tokens=0)

    result = chunk_for_analysis(_snapshot(source), META, settings)

    assert result.chunks is not None
    assert len(result.chunks) == 4
    assert all(chunk.text.endswith(".") for chunk in result.chunks)
    assert "".join(chunk.text.replace(" ", "") for chunk in result.chunks) == source.replace(" ", "").strip()


def test_overlap_is_included_without_changing_structural_end_boundaries() -> None:
    source = "A" * 60 + "\n\n" + "B" * 60 + "\n\n" + "C" * 60
    settings = ChunkSettings(single_max_tokens=100, chunk_target_tokens=100, overlap_tokens=10)

    result = chunk_for_analysis(_snapshot(source), META, settings)

    assert result.chunks is not None
    assert [chunk.text[-1] for chunk in result.chunks] == ["A", "B", "C"]
    assert result.chunks[1].text.startswith("A" * 10)
    assert result.chunks[2].text.startswith("B" * 10)
    assert result.chunks[0].end_char - result.chunks[1].start_char == 10


def test_more_than_24_chunks_uses_required_head_middle_tail_sampling() -> None:
    units = [f"{index:02d}" + chr(0xAC00 + index) * 8 for index in range(30)]
    source = "\n\n".join(units)
    settings = ChunkSettings(single_max_tokens=10, chunk_target_tokens=10, overlap_tokens=0)

    result = chunk_for_analysis(_snapshot(source), META, settings)

    assert result.chunks is not None
    assert result.coverage == "sampled"
    assert result.total_chunks == 30
    assert len(result.chunks) == 24
    assert [chunk.index for chunk in result.chunks] == [
        0,
        1,
        2,
        3,
        4,
        5,
        6,
        7,
        8,
        10,
        11,
        13,
        14,
        16,
        17,
        19,
        20,
        22,
        23,
        25,
        26,
        27,
        28,
        29,
    ]


def test_exactly_24_chunks_keeps_full_coverage() -> None:
    source = "\n\n".join(f"{index:02d}" + "가" * 8 for index in range(24))
    result = chunk_for_analysis(
        _snapshot(source),
        META,
        ChunkSettings(single_max_tokens=10, chunk_target_tokens=10, overlap_tokens=0),
    )

    assert result.chunks is not None
    assert len(result.chunks) == 24
    assert result.coverage == "full"


def test_plan_is_deterministic() -> None:
    source = "\n\n".join(f"문단 {index} " + "가" * 80 for index in range(40))
    settings = ChunkSettings(single_max_tokens=100, chunk_target_tokens=120, overlap_tokens=20)
    snapshot = _snapshot(source)

    first = chunk_for_analysis(snapshot, META, settings)
    second = chunk_for_analysis(snapshot, META, settings)

    assert first == second
    assert first.model_dump_json() == second.model_dump_json()


def test_injected_token_counter_is_used_and_none_falls_back_to_character_count() -> None:
    calls: list[str] = []

    def half_length(text: str) -> int:
        calls.append(text)
        return len(text) // 2

    measured = chunk_for_analysis(
        _snapshot("가" * 12_001),
        META,
        ChunkSettings(token_counter=half_length),
    )
    fallback = chunk_for_analysis(
        _snapshot("가" * 12_001),
        META,
        ChunkSettings(token_counter=lambda _text: None),
    )

    assert measured.mode == "single"
    assert measured.source_token_count == 6_000
    assert fallback.mode == "map_reduce"
    assert calls == ["가" * 12_001]


def test_ocr_is_used_alone_or_appended_to_body() -> None:
    ocr_only = chunk_for_analysis(_snapshot(ocr_text="영수증 OCR"), META, ChunkSettings())
    body_and_ocr = chunk_for_analysis(_snapshot("본문", ocr_text="이미지 글자"), META, ChunkSettings())

    assert ocr_only.text == "영수증 OCR"
    assert body_and_ocr.text == "본문\n\n이미지 글자"


def test_youtube_and_paper_source_order_is_explicit() -> None:
    youtube = chunk_for_analysis(
        _snapshot("자막"),
        ContentMeta(title="영상 제목", description="설명란", platform="youtube", content_type="video"),
        ChunkSettings(),
    )
    paper = chunk_for_analysis(
        _snapshot("서론\n\n방법\n\n결론"),
        ContentMeta(title="논문", abstract="초록", platform="web", content_type="paper"),
        ChunkSettings(),
    )

    assert youtube.text == "영상 제목\n\n설명란\n\n자막"
    assert paper.text == "초록\n\n서론\n\n방법\n\n결론"


def test_invalid_settings_and_mode_shapes_are_rejected() -> None:
    with pytest.raises(ValidationError, match="overlap_tokens"):
        ChunkSettings(chunk_target_tokens=200, overlap_tokens=200)
    with pytest.raises(ValidationError, match="single"):
        AnalysisInput(mode="single", text=None, chunks=None, meta=META)


def test_empty_snapshot_is_rejected_explicitly() -> None:
    with pytest.raises(ValueError, match="snapshot"):
        chunk_for_analysis(_snapshot(), META, ChunkSettings())


# --- T20 loop 1 M1: 본문에 이미 있는 초록·제목·설명은 앞에 다시 붙이지 않는다 ---

PAPER = ContentMeta(title="논문", abstract="이 논문은 초록이다.", platform="web", content_type="paper")


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        pytest.param("이 논문은 초록이다.\n\n서론 본문", "이 논문은 초록이다.\n\n서론 본문", id="first-unit-equal"),
        pytest.param("이 논문은 초록이다", "이 논문은 초록이다", id="terminal-punctuation-omitted"),
        pytest.param(
            "이 논문은 초록이다.이어붙은 문장이다.",
            "이 논문은 초록이다.이어붙은 문장이다.",
            id="sentence-without-space",
        ),
        pytest.param(
            "이 논문은 초록이다?\n\n서론 본문",
            "이 논문은 초록이다?\n\n서론 본문",
            id="different-terminal-punctuation",
        ),
        pytest.param("이 논문은  초록이다.\n\n서론 본문", "이 논문은  초록이다.\n\n서론 본문", id="whitespace-variant"),
        pytest.param(
            "이 논문은 초록이다. 이어서 배경을 설명한다.\n\n서론",
            "이 논문은 초록이다. 이어서 배경을 설명한다.\n\n서론",
            id="abstract-is-sentence-prefix",
        ),
        pytest.param("이 논문은 초록이다.", "이 논문은 초록이다.", id="body-equals-abstract"),
        pytest.param(
            "이 논문은 초록이다.\n\n서론 본문",
            "이 논문은 초록이다.\n\n서론 본문",
            id="abstract-without-terminal-body-with-terminal",
        ),
        pytest.param(
            "이 논문은 초록이다. 서론 본문",
            "이 논문은 초록이다. 서론 본문",
            id="abstract-without-terminal-body-terminal-and-space",
        ),
        pytest.param(
            "이 논문은 초록이다\n서론 본문",
            "이 논문은 초록이다\n서론 본문",
            id="abstract-with-terminal-body-single-newline",
        ),
        pytest.param("서론 본문", "이 논문은 초록이다.\n\n서론 본문", id="absent-is-prepended"),
        pytest.param(
            "이 논문은 초록이다만 다르다.\n\n서론",
            "이 논문은 초록이다.\n\n이 논문은 초록이다만 다르다.\n\n서론",
            id="not-a-boundary",
        ),
    ],
)
def test_paper_abstract_is_not_duplicated_when_body_starts_with_it(body: str, expected: str) -> None:
    plan = chunk_for_analysis(_snapshot(body), PAPER, ChunkSettings())
    assert plan.text == expected
    assert plan.text.count("이 논문은 초록이다.") <= 2


def test_paper_abstract_duplicate_no_longer_inflates_token_count() -> None:
    abstract = "가" * 5_000 + "."
    meta = ContentMeta(title="논문", abstract=abstract, platform="web", content_type="paper")
    plan = chunk_for_analysis(_snapshot(abstract + "\n\n" + "나" * 6_000), meta, ChunkSettings())
    assert plan.mode == "single"
    assert plan.source_token_count == 5_001 + 2 + 6_000


def test_youtube_preamble_already_in_transcript_is_not_repeated() -> None:
    meta = ContentMeta(title="하체 운동 루틴", description="오늘은 하체 운동을 합니다.", platform="youtube")
    plan = chunk_for_analysis(_snapshot("하체 운동 루틴\n\n오늘은 하체 운동을 합니다.\n\n자막"), meta, ChunkSettings())
    assert plan.text == "하체 운동 루틴\n\n오늘은 하체 운동을 합니다.\n\n자막"

    only_title_missing = chunk_for_analysis(_snapshot("오늘은 하체 운동을 합니다. 자막"), meta, ChunkSettings())
    assert only_title_missing.text == "하체 운동 루틴\n\n오늘은 하체 운동을 합니다. 자막"


def test_short_youtube_title_matching_transcript_words_is_still_kept() -> None:
    meta = ContentMeta(title="운동", platform="youtube", content_type="video")
    plan = chunk_for_analysis(_snapshot("운동 시작합니다"), meta, ChunkSettings())
    assert plan.text == "운동\n\n운동 시작합니다"

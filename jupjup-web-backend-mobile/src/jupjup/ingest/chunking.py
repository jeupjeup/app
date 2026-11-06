"""Deterministic analysis chunk planning for ingest stage I4.

Analysis chunks deliberately differ from the shorter chunks used by the search
embedding path.  I4 preserves extraction-time structural boundaries whenever
possible and only splits inside a unit when that unit cannot fit by itself.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from jupjup.domain.models import ContentType, Platform, Snapshot

TokenCounter = Callable[[str], int | None]
Coverage = Literal["full", "sampled"]

_STRUCTURE_UNIT = re.compile(r"\S(?:.*?\S)?(?=\n[ \t]*\n|\Z)", re.DOTALL)
_SENTENCE_BOUNDARY = re.compile(r"[.!?。！？]+(?:[\"'”’」』)]*)\s+")
_WHITESPACE_BOUNDARY = re.compile(r"\s+")


class ContentMeta(BaseModel):
    """Metadata passed through to the analyzer without mixing it into evidence text."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str | None = None
    title: str | None = None
    description: str | None = None
    abstract: str | None = None
    author: str | None = None
    platform: Platform | None = None
    content_type: ContentType | None = None
    language: str | None = None
    user_note: str | None = None


class ChunkSettings(BaseModel):
    """Tunable I4 limits; defaults are the values from design section 5.10.4."""

    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)

    single_max_tokens: int = Field(default=12_000, ge=1)
    chunk_target_tokens: int = Field(default=3_000, ge=1)
    overlap_tokens: int = Field(default=200, ge=0)
    max_chunks: int = Field(default=24, ge=1)
    token_counter: TokenCounter | None = Field(default=None, exclude=True, repr=False)

    @model_validator(mode="after")
    def _overlap_is_smaller_than_chunk(self) -> ChunkSettings:
        if self.overlap_tokens >= self.chunk_target_tokens:
            raise ValueError("overlap_tokens는 chunk_target_tokens보다 작아야 합니다")
        return self


class AnalysisChunk(BaseModel):
    """One map input, with offsets into the complete analysis source text."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    index: int = Field(ge=0, description="샘플링 전 원래 청크 순번")
    text: str = Field(min_length=1)
    token_count: int = Field(ge=1)
    start_char: int = Field(ge=0)
    end_char: int = Field(ge=1)

    @model_validator(mode="after")
    def _valid_span(self) -> AnalysisChunk:
        if self.end_char <= self.start_char:
            raise ValueError("end_char는 start_char보다 커야 합니다")
        return self


class AnalysisInput(BaseModel):
    """A complete single request or a deterministic map-reduce execution plan."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: Literal["single", "map_reduce"]
    text: str | None = None
    chunks: list[AnalysisChunk] | None = None
    meta: ContentMeta = Field(default_factory=ContentMeta)
    coverage: Coverage = "full"
    source_token_count: int = Field(default=0, ge=0)
    total_chunks: int = Field(default=0, ge=0, description="샘플링 전 분석 청크 수")

    @model_validator(mode="after")
    def _mode_shape(self) -> AnalysisInput:
        if self.mode == "single":
            if self.text is None or self.chunks is not None:
                raise ValueError("single 입력은 text만 가져야 합니다")
            if self.coverage != "full" or self.total_chunks != 0:
                raise ValueError("single 입력은 full coverage이며 total_chunks가 0이어야 합니다")
            return self

        if self.text is not None or not self.chunks:
            raise ValueError("map_reduce 입력은 비어 있지 않은 chunks만 가져야 합니다")
        if self.total_chunks < len(self.chunks):
            raise ValueError("total_chunks는 선택된 청크 수보다 작을 수 없습니다")
        expected_coverage = "sampled" if self.total_chunks > len(self.chunks) else "full"
        if self.coverage != expected_coverage:
            raise ValueError("coverage가 청크 선택 결과와 일치하지 않습니다")
        return self


def chunk_for_analysis(snapshot: Snapshot, meta: ContentMeta, settings: ChunkSettings) -> AnalysisInput:
    """Build a deterministic single or map-reduce plan from a stored snapshot.

    The optional token counter is expected to be deterministic.  Returning
    ``None`` asks this function to use the conservative one-character-per-token
    estimate for that value.
    """

    source = _analysis_source(snapshot, meta)
    if not source:
        raise ValueError("분석할 snapshot text 또는 ocr_text가 필요합니다")

    source_tokens = _count_tokens(source, settings)
    if source_tokens <= settings.single_max_tokens:
        return AnalysisInput(
            mode="single",
            text=source,
            meta=meta,
            coverage="full",
            source_token_count=source_tokens,
        )

    base_spans = _base_chunk_spans(source, settings)
    chunks = _with_overlap(source, base_spans, settings)
    total_chunks = len(chunks)
    selected = _sample_chunks(chunks, settings.max_chunks)
    return AnalysisInput(
        mode="map_reduce",
        chunks=selected,
        meta=meta,
        coverage="sampled" if len(selected) < total_chunks else "full",
        source_token_count=source_tokens,
        total_chunks=total_chunks,
    )


def _analysis_source(snapshot: Snapshot, meta: ContentMeta) -> str:
    body = snapshot.text.strip()
    ocr = (snapshot.ocr_text or "").strip()
    source_parts = [body] if body else []
    if ocr and ocr != body:
        source_parts.append(ocr)

    # Section 5.10.4 fixes these source-specific prompt orders.  Keeping the
    # preamble in `text` also makes thresholding and chunk offsets unambiguous.
    preamble: list[str | None]
    if meta.platform == "youtube":
        preamble = [meta.title, meta.description]
    elif meta.content_type == "paper":
        preamble = [meta.abstract]
    else:
        preamble = []
    # 5.10.4절 순서(제목 → 설명 → 본문, 초록 → 본문)를 지키되, 본문 앞부분에 이미 같은
    # 단위가 있으면(논문 HTML의 첫 블록이 초록인 경우 등) 다시 넣지 않는다.
    joined = "\n\n".join(source_parts)
    offset = 0
    inserts: list[tuple[int, str]] = []
    for part in preamble:
        candidate = (part or "").strip()
        if not candidate:
            continue
        end = _unit_prefix_end(joined[offset:], candidate)
        if end is None:
            inserts.append((offset, candidate))
        else:
            offset += end

    pieces: list[str] = []
    last = 0
    for position, candidate in inserts:
        pieces += [joined[last:position].strip(), candidate]
        last = position
    pieces.append(joined[last:].strip())
    return "\n\n".join(piece for piece in pieces if piece)


_SENTENCE_FINAL = (".", "!", "?", "。", "！", "？", "…")
_BLANK_LINE = re.compile(r"[ \t]*\n\s*\n")


def _unit_prefix_end(text: str, unit: str) -> int | None:
    """text가 unit 단위로 시작하면 그 끝 위치를, 아니면 None을 돌려준다(공백 차이 무시).

    unit 뒤가 텍스트 끝이나 빈 줄(구조 단위 경계)이면 일치로 본다. unit이 문장 종결부호로
    끝나면 뒤에 공백만 와도 일치다. "운동"과 "운동 시작합니다"처럼 단어만 겹치는 짧은 제목은
    일치가 아니다.
    """

    core = unit.rstrip("".join(_SENTENCE_FINAL)).rstrip()
    if not core:
        return None
    match = _prefix_words(text, core)
    if match is None:
        return None
    end = match.end()
    rest = text[end:]
    terminal = re.match(r"[.!?。！？…]+", rest)
    if terminal is not None:
        return end + terminal.end()
    if not rest.strip() or _BLANK_LINE.match(rest) or rest.startswith("\n"):
        return end
    return None


def _prefix_words(text: str, unit: str) -> re.Match[str] | None:
    words = unit.split()
    if not words:
        return None
    return re.match(r"\s*" + r"\s+".join(map(re.escape, words)), text)


def _count_tokens(text: str, settings: ChunkSettings) -> int:
    if settings.token_counter is not None:
        measured = settings.token_counter(text)
        if measured is not None:
            if not isinstance(measured, int) or isinstance(measured, bool) or (text and measured < 1) or measured < 0:
                raise ValueError("token_counter는 비어 있지 않은 입력에 양의 정수 또는 None을 반환해야 합니다")
            return measured
    return len(text)


def _structure_spans(text: str, settings: ChunkSettings) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for match in _STRUCTURE_UNIT.finditer(text):
        start, end = match.span()
        if _count_tokens(text[start:end], settings) <= settings.chunk_target_tokens:
            spans.append((start, end))
        else:
            spans.extend(_split_oversized_unit(text, start, end, settings))
    return spans


def _split_oversized_unit(
    text: str,
    start: int,
    end: int,
    settings: ChunkSettings,
) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    cursor = start
    while cursor < end:
        max_end = _furthest_fitting_end(text, cursor, end, settings.chunk_target_tokens, settings)
        if max_end >= end:
            spans.append((cursor, end))
            break
        split = _preferred_split(text, cursor, max_end)
        if split <= cursor:
            split = min(cursor + 1, end)
        spans.append((cursor, split))
        cursor = split
        while cursor < end and text[cursor].isspace():
            cursor += 1
    return spans


def _furthest_fitting_end(text: str, start: int, end: int, limit: int, settings: ChunkSettings) -> int:
    low = start + 1
    high = end
    best = start
    while low <= high:
        middle = (low + high) // 2
        if _count_tokens(text[start:middle], settings) <= limit:
            best = middle
            low = middle + 1
        else:
            high = middle - 1
    # A provider counter should not report more than the limit for one character,
    # but advancing keeps malformed input from causing an infinite loop.
    return best if best > start else min(start + 1, end)


def _preferred_split(text: str, start: int, max_end: int) -> int:
    fragment = text[start:max_end]
    minimum = len(fragment) // 2
    sentence_ends = [match.end() for match in _SENTENCE_BOUNDARY.finditer(fragment) if match.end() >= minimum]
    if sentence_ends:
        return start + sentence_ends[-1]
    whitespace_ends = [match.end() for match in _WHITESPACE_BOUNDARY.finditer(fragment) if match.end() >= minimum]
    if whitespace_ends:
        return start + whitespace_ends[-1]
    return max_end


def _base_chunk_spans(text: str, settings: ChunkSettings) -> list[tuple[int, int]]:
    units = _structure_spans(text, settings)
    if not units:
        return []

    chunks: list[tuple[int, int]] = []
    chunk_start, chunk_end = units[0]
    for unit_start, unit_end in units[1:]:
        if _count_tokens(text[chunk_start:unit_end], settings) <= settings.chunk_target_tokens:
            chunk_end = unit_end
            continue
        chunks.append((chunk_start, chunk_end))
        chunk_start, chunk_end = unit_start, unit_end
    chunks.append((chunk_start, chunk_end))
    return chunks


def _with_overlap(
    text: str,
    base_spans: list[tuple[int, int]],
    settings: ChunkSettings,
) -> list[AnalysisChunk]:
    chunks: list[AnalysisChunk] = []
    for index, (base_start, end) in enumerate(base_spans):
        start = base_start
        if index > 0 and settings.overlap_tokens:
            previous_start, previous_end = base_spans[index - 1]
            start = _suffix_start(text, previous_start, previous_end, settings.overlap_tokens, settings)
        chunk_text = text[start:end].strip()
        # Trimming only removes delimiter whitespace; keep offsets aligned to the
        # exact text stored in the plan.
        left_trim = len(text[start:end]) - len(text[start:end].lstrip())
        right_trim = len(text[start:end]) - len(text[start:end].rstrip())
        start += left_trim
        end -= right_trim
        chunks.append(
            AnalysisChunk(
                index=index,
                text=chunk_text,
                token_count=_count_tokens(chunk_text, settings),
                start_char=start,
                end_char=end,
            )
        )
    return chunks


def _suffix_start(text: str, start: int, end: int, limit: int, settings: ChunkSettings) -> int:
    low = start
    high = end
    while low < high:
        middle = (low + high) // 2
        if _count_tokens(text[middle:end], settings) <= limit:
            high = middle
        else:
            low = middle + 1
    return low


def _sample_chunks(chunks: list[AnalysisChunk], max_chunks: int) -> list[AnalysisChunk]:
    if len(chunks) <= max_chunks:
        return chunks

    front_count = min(8, max_chunks)
    remaining = max_chunks - front_count
    back_count = min(4, remaining)
    middle_count = remaining - back_count

    front = chunks[:front_count]
    back = chunks[len(chunks) - back_count :] if back_count else []
    if not middle_count:
        return [*front, *back]

    middle_pool = chunks[front_count : len(chunks) - back_count if back_count else None]
    if middle_count == 1:
        middle = [middle_pool[len(middle_pool) // 2]]
    else:
        last = len(middle_pool) - 1
        positions = [(index * last + (middle_count - 1) // 2) // (middle_count - 1) for index in range(middle_count)]
        middle = [middle_pool[position] for position in positions]
    return [*front, *middle, *back]

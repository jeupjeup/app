"""Deterministic HTML/text/transcript extraction for ingest stage I2.

스냅샷 본문은 "저장 당시 기록"이라 가벼운 정리만 한다(NFC, 제어문자 제거, 줄 안 공백 정리).
블록·제목 경계는 빈 줄(``\\n\\n``)로, ``<br>``은 줄바꿈으로 남겨 T20 구조 단위 분할이 쓸 수 있게 한다.
대소문자·이모지는 보존하고, 검색용 ``normalize_text``는 인덱싱(I8) 때 적용한다.
"""

from __future__ import annotations

import codecs
import hashlib
import html
import json
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from jupjup.domain.errors import ExtractionError, SourceTextUnavailableError
from jupjup.domain.models import Platform
from jupjup.ingest.fetch import RawSource
from jupjup.text.normalize import normalize_text

# 디코딩 전 입력 상한. 이보다 큰 원본은 파싱하지 않고 영구 실패로 끝낸다.
MAX_SOURCE_BYTES = 5_000_000
# 자막을 T20 구조 분할용 시간 구간으로 묶는 단위(5.10.4절, 약 3분).
TRANSCRIPT_SEGMENT_SECONDS = 180
_MAX_JSON_DEPTH = 64
_MAX_REPLACEMENT_RATIO = 0.01

_ALWAYS_EXCLUDED_TAGS = frozenset(
    {
        "aside",
        "button",
        "canvas",
        "dialog",
        "embed",
        "footer",
        "form",
        "head",
        "iframe",
        "input",
        "nav",
        "noscript",
        "object",
        "script",
        "select",
        "style",
        "svg",
        "template",
        "textarea",
    }
)
# HTML void 요소: 닫는 태그가 없으므로 스택에 넣지 않는다.
_VOID_TAGS = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
)
_BLOCK_TAGS = frozenset(
    {
        "address",
        "article",
        "aside",
        "blockquote",
        "body",
        "caption",
        "dd",
        "details",
        "dialog",
        "div",
        "dl",
        "dt",
        "fieldset",
        "figcaption",
        "figure",
        "footer",
        "form",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "hgroup",
        "hr",
        "html",
        "li",
        "main",
        "nav",
        "ol",
        "p",
        "pre",
        "section",
        "summary",
        "table",
        "tbody",
        "tfoot",
        "thead",
        "tr",
        "ul",
    }
)
_CELL_TAGS = frozenset({"td", "th"})
# 열린 같은 태그를 암묵적으로 닫는 요소 (`<p>a<p>b`, `<li>a<li>b`).
_SELF_CLOSING_SIBLINGS = frozenset({"p", "li", "dt", "dd", "option", "tr", "td", "th"})
_NO_TITLE_TAGS = frozenset({"svg", "math"})
_LAYOUT_TAGS = frozenset({"html", "body"})
_NUISANCE_TOKENS = frozenset(
    {
        "ad",
        "ads",
        "advert",
        "advertisement",
        "banner",
        "breadcrumb",
        "comments",
        "consent",
        "cookie",
        "footer",
        "menu",
        "modal",
        "nav",
        "navigation",
        "newsletter",
        "outbrain",
        "popup",
        "promo",
        "related",
        "share",
        "sidebar",
        "social",
        "sponsored",
        "taboola",
        "toolbar",
    }
)
# `has-sidebar`, `no-sidebar`, `with-share` 같은 레이아웃 상태 클래스는 제외 신호가 아니다.
_STATE_PREFIXES = frozenset({"has", "no", "with", "without", "is", "show", "hide", "enable", "disable"})
_CONTENT_TOKENS = frozenset(
    {
        "article",
        "articlebody",
        "article-body",
        "content",
        "entry",
        "entry-content",
        "main",
        "post",
        "post-content",
        "story",
        "story-body",
    }
)

_TS = r"(?:(\d+):)?(\d{1,2}):(\d{2})[,.](\d{3})"
_TIMESTAMP = re.compile(rf"^{_TS}\s*-->\s*{_TS}(?:\s+.*)?$")
_VTT_SIGNATURE = re.compile(r"^WEBVTT(?:[ \t].*)?$")
_VTT_PRE_CUE_BLOCK = re.compile(r"^(?:NOTE|STYLE|REGION)(?:[ \t]|$)")
_VTT_NOTE_BLOCK = re.compile(r"^NOTE(?:[ \t]|$)")
_INLINE_TIMESTAMP = re.compile(r"<\d{1,2}:\d{2}(?::\d{2})?[,.]\d{3}>")
_SUBTITLE_TAG = re.compile(r"</?(?:c(?:\.[^ >]+)?|i|b|u|ruby|rt|v)(?:\s+[^>]*)?>", re.IGNORECASE)
_ASS_OVERRIDE = re.compile(r"\{\\[^}]+}")
_NON_SPEECH = re.compile(
    r"[\[(](?:음악|노래|박수|웃음|환호|침묵|효과음|music|applause|laughter|cheering|silence|noise)[^\])]*[\])]",
    re.IGNORECASE,
)
_SPACE = re.compile(r"\s+")
_INLINE_SPACE = re.compile(r"[^\S\n]+")
_BLANK_RUN = re.compile(r"\n{3,}")
_META_CHARSET = re.compile(rb"""<meta[^>]+charset\s*=\s*["']?\s*([A-Za-z0-9_.:-]+)""", re.IGNORECASE)
_MIME_CHARSET = re.compile(r"charset=\"?([\w.:-]+)", re.IGNORECASE)
_SUBTITLE_MIMES = frozenset({"text/vtt", "application/x-subrip", "application/json"})
_HTML_MIMES = frozenset({"text/html", "application/xhtml+xml"})
# WHATWG 인코딩 표준처럼 레거시 한국어 레이블은 상위 집합 cp949로 읽는다.
_CHARSET_ALIASES = {"euc-kr": "cp949", "ks_c_5601-1987": "cp949", "x-windows-949": "cp949", "windows-949": "cp949"}


class SnapshotDraft(BaseModel):
    """Lightly cleaned, persistence-ready output of the extraction stage."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str
    ocr_text: str | None = None
    title_guess: str | None = None
    author_guess: str | None = None
    published_at_guess: datetime | None = None
    language: str
    raw_meta: dict[str, Any] = Field(default_factory=dict)
    content_hash: str
    truncated: bool = False

    @field_validator("published_at_guess")
    @classmethod
    def _aware_datetime(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.tzinfo.utcoffset(value) is None):
            raise ValueError("published_at_guess는 timezone-aware여야 합니다")
        return value


def tidy_snapshot_text(text: str) -> str:
    """Light, structure-preserving cleanup used for snapshot text (not the search normalization)."""

    value = unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))
    value = "".join(ch for ch in value if not _is_dropped_control(ch))
    lines = [_INLINE_SPACE.sub(" ", line).strip() for line in value.split("\n")]
    return _BLANK_RUN.sub("\n\n", "\n".join(lines)).strip()


def _is_dropped_control(ch: str) -> bool:
    if ch in "\n\t":
        return False
    category = unicodedata.category(ch)
    if category == "Cc":
        return True
    # 이모지 결합(ZWJ)만 남기고 다른 서식 문자(ZWSP, BOM, 방향 표지)는 지운다.
    return category == "Cf" and ch != "‍"


# --------------------------------------------------------------------------- HTML


@dataclass(frozen=True)
class _Frame:
    tag: str
    excluded: bool
    soft_excluded: bool
    in_content: bool
    in_title: bool
    in_h1: bool
    in_pre: bool
    no_title: bool


_ROOT_FRAME = _Frame(
    tag="#root",
    excluded=False,
    soft_excluded=False,
    in_content=False,
    in_title=False,
    in_h1=False,
    in_pre=False,
    no_title=False,
)


def _attribute_tokens(attributes: dict[str, str]) -> set[str]:
    values = " ".join(attributes.get(name, "") for name in ("class", "id", "role", "aria-label", "itemprop"))
    return {token for token in re.split(r"[^a-z0-9가-힣_-]+", values.casefold()) if token}


def _has_nuisance_marker(tokens: set[str], *, whole_tokens_only: bool) -> bool:
    for token in tokens:
        if token in _NUISANCE_TOKENS:
            return True
        if whole_tokens_only:
            continue
        pieces = [piece for piece in token.replace("_", "-").split("-") if piece]
        if pieces and pieces[0] in _STATE_PREFIXES:
            continue
        if set(pieces) & _NUISANCE_TOKENS:
            return True
        if token.startswith(("adslot", "adsby", "advert")):
            return True
    return False


def _is_content_root(tag: str, attributes: dict[str, str], tokens: set[str]) -> bool:
    if tag in ("article", "main") or attributes.get("role", "").casefold() == "main":
        return True
    return bool(tokens & _CONTENT_TOKENS)


def _is_main_landmark(tag: str, attributes: dict[str, str]) -> bool:
    return tag == "main" or attributes.get("role", "").casefold() == "main"


class _TextSink:
    """Collect text into blocks; inline runs join without extra spaces."""

    def __init__(self) -> None:
        self.blocks: list[str] = []
        self._buffer: list[str] = []

    def write(self, value: str) -> None:
        self._buffer.append(value)

    def break_line(self) -> None:
        if self._buffer:
            self._buffer.append("\n")

    def flush(self) -> None:
        if not self._buffer:
            return
        block = tidy_snapshot_text("".join(self._buffer))
        self._buffer.clear()
        if block:
            self.blocks.append(block)


class _ArticleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._stack: list[_Frame] = []
        self._open_counts: Counter[str] = Counter()
        self.all_text = _TextSink()
        self.content_text = _TextSink()
        self.title_text: list[str] = []
        self.heading_text: list[str] = []
        self.meta: dict[str, str] = {}
        self.language: str | None = None

    @property
    def _top(self) -> _Frame:
        return self._stack[-1] if self._stack else _ROOT_FRAME

    def _block_boundary(self) -> None:
        self.all_text.flush()
        self.content_text.flush()

    def _line_break(self) -> None:
        self.all_text.break_line()
        self.content_text.break_line()

    def _write(self, value: str) -> None:
        top = self._top
        if top.excluded or not self._stack:
            return
        self.all_text.write(value)
        if top.in_content:
            self.content_text.write(value)

    def _pop_to(self, index: int) -> None:
        for frame in self._stack[index:]:
            self._open_counts[frame.tag] -= 1
        del self._stack[index:]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._start(tag, attrs, self_closing=False)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._start(tag, attrs, self_closing=True)

    def _start(self, tag: str, attrs: list[tuple[str, str | None]], *, self_closing: bool) -> None:
        lowered = tag.casefold()
        attributes = {key.casefold(): (value or "") for key, value in attrs}
        if lowered == "html" and attributes.get("lang"):
            self.language = attributes["lang"]
        if lowered == "meta":
            key = (attributes.get("property") or attributes.get("name") or attributes.get("itemprop") or "").casefold()
            content = attributes.get("content", "").strip()
            if key and content and key not in self.meta:
                self.meta[key] = content

        if lowered in _SELF_CLOSING_SIBLINGS and self._stack and self._stack[-1].tag == lowered:
            self._pop_to(len(self._stack) - 1)
        if lowered in _BLOCK_TAGS:
            self._block_boundary()
        elif lowered in _CELL_TAGS:
            self._write(" ")
        if lowered == "br":
            self._line_break()
        if lowered in _VOID_TAGS:
            return

        parent = self._top
        tokens = _attribute_tokens(attributes)
        content_root = _is_content_root(lowered, attributes, tokens)
        hard = parent.excluded and not parent.soft_excluded
        if lowered in _ALWAYS_EXCLUDED_TAGS:
            hard = True
        soft = False
        if not hard:
            if parent.soft_excluded:
                # 광고·메뉴로 표시된 래퍼 안이라도 <main>/role=main은 페이지 본문이므로 살린다.
                soft = not _is_main_landmark(lowered, attributes)
            elif lowered not in _LAYOUT_TAGS:
                soft = _has_nuisance_marker(tokens, whole_tokens_only=content_root)
            if lowered == "header" and not parent.in_content:
                hard = True
        excluded = hard or soft
        frame = _Frame(
            tag=lowered,
            excluded=excluded,
            soft_excluded=soft and not hard,
            in_content=not excluded and (parent.in_content or content_root),
            in_title=lowered == "title" and not parent.no_title,
            in_h1=not excluded and (parent.in_h1 or lowered == "h1"),
            in_pre=parent.in_pre or lowered == "pre",
            no_title=parent.no_title or lowered in _NO_TITLE_TAGS,
        )
        self._stack.append(frame)
        self._open_counts[lowered] += 1
        if self_closing:
            self.handle_endtag(lowered)

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.casefold()
        if lowered == "br":
            self._line_break()
            return
        if lowered in _BLOCK_TAGS:
            self._block_boundary()
        if self._open_counts[lowered] <= 0:
            return
        for index in range(len(self._stack) - 1, -1, -1):
            if self._stack[index].tag == lowered:
                self._pop_to(index)
                return

    def handle_data(self, data: str) -> None:
        top = self._top
        if top.in_title:
            self.title_text.append(data)
            return
        if top.excluded or not self._stack:
            return
        value = data if top.in_pre else data.replace("\n", " ")
        if top.in_h1:
            self.heading_text.append(value)
        self._write(value)

    def close(self) -> None:
        super().close()
        self._block_boundary()


def _charset_from_mime(mime: str) -> str | None:
    match = _MIME_CHARSET.search(mime)
    return match.group(1) if match else None


def _codec_name(label: str | None) -> str | None:
    if not label:
        return None
    normalized = label.strip().casefold()
    normalized = _CHARSET_ALIASES.get(normalized, normalized)
    try:
        return codecs.lookup(normalized).name
    except LookupError:
        return None


def _decode_body(raw: RawSource, *, is_html: bool) -> str:
    if isinstance(raw.body, str):
        return raw.body
    body = raw.body
    candidates: list[str] = []
    if body.startswith(codecs.BOM_UTF8):
        candidates.append("utf-8-sig")
    elif body.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        candidates.append("utf-16")
    for label in (
        _charset_from_mime(raw.mime),
        (match.group(1).decode("ascii", "ignore") if (match := _META_CHARSET.search(body[:2048])) else None)
        if is_html
        else None,
        "utf-8",
    ):
        codec = _codec_name(label)
        if codec and codec not in candidates:
            candidates.append(codec)
    for codec in candidates:
        try:
            return body.decode(codec)
        except (UnicodeDecodeError, LookupError):
            continue
    decoded = body.decode(candidates[0], errors="replace")
    if decoded and decoded.count("�") / len(decoded) > _MAX_REPLACEMENT_RATIO:
        raise ExtractionError("원본 인코딩을 해석하지 못했습니다", {"mime": raw.mime, "tried": candidates})
    return decoded


def _collapse(value: str | None) -> str | None:
    if value is None:
        return None
    collapsed = _SPACE.sub(" ", html.unescape(value)).strip()
    return collapsed or None


def _parse_published(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        candidate = value.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None or parsed.tzinfo.utcoffset(parsed) is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _extract_html(source: str) -> tuple[str, dict[str, Any]]:
    parser = _ArticleParser()
    try:
        parser.feed(source)
        parser.close()
    except (AssertionError, ValueError, RecursionError) as exc:
        raise ExtractionError("HTML을 파싱하지 못했습니다") from exc
    chosen = parser.content_text.blocks or parser.all_text.blocks
    text = "\n\n".join(chosen)
    metadata: dict[str, Any] = {
        "title": _collapse(
            parser.meta.get("og:title")
            or parser.meta.get("twitter:title")
            or "".join(parser.heading_text)
            or "".join(parser.title_text)
        ),
        "author": _collapse(parser.meta.get("author") or parser.meta.get("article:author") or parser.meta.get("byl")),
        "published_at": _parse_published(
            parser.meta.get("article:published_time")
            or parser.meta.get("datepublished")
            or parser.meta.get("pubdate")
            or parser.meta.get("date")
        ),
        "language": parser.language,
    }
    return text, metadata


# --------------------------------------------------------------------- transcripts


@dataclass(frozen=True)
class _Cue:
    text: str
    start: float | None


def _parse_timestamp(match: re.Match[str], offset: int = 0) -> float:
    hours, minutes, seconds, millis = (match.group(offset + i) for i in range(1, 5))
    return int(hours or 0) * 3600 + int(minutes) * 60 + int(seconds) + int(millis) / 1000


def _json_start(value: dict[str, Any]) -> float | None:
    for key, scale in (("tStartMs", 1000.0), ("start_ms", 1000.0), ("startMs", 1000.0), ("start", 1.0)):
        number = value.get(key)
        if isinstance(number, int | float) and not isinstance(number, bool):
            return float(number) / scale
        if isinstance(number, str):
            try:
                return float(number) / scale
            except ValueError:
                continue
    return None


def _json_transcript_cues(value: Any, depth: int = 0) -> list[_Cue]:
    if depth > _MAX_JSON_DEPTH:
        raise ExtractionError("JSON 자막 중첩이 너무 깊습니다", {"max_depth": _MAX_JSON_DEPTH})
    if isinstance(value, str):
        return [_Cue(value, None)]
    if isinstance(value, list):
        cues: list[_Cue] = []
        for item in value:
            cues.extend(_json_transcript_cues(item, depth + 1))
        return cues
    if not isinstance(value, dict):
        return []

    start = _json_start(value)
    segments = value.get("segs")
    if isinstance(segments, list):
        joined = "".join(
            segment.get("utf8", "")
            for segment in segments
            if isinstance(segment, dict) and isinstance(segment.get("utf8"), str)
        )
        return [_Cue(joined, start)] if joined else []
    for key in ("text", "utf8", "caption", "content"):
        text = value.get(key)
        if isinstance(text, str):
            return [_Cue(text, start)]
    for key in ("events", "segments", "captions", "transcript", "items", "results", "body"):
        nested = value.get(key)
        if nested is not None:
            cues = _json_transcript_cues(nested, depth + 1)
            if cues:
                return cues
    return []


def _load_json(source: str) -> Any:
    """Parse JSON; `JSONDecodeError` propagates so callers can fall back to text subtitles."""

    try:
        return json.loads(source)
    except json.JSONDecodeError:
        raise
    except (ValueError, RecursionError) as exc:
        # 4,300자리를 넘는 정수 리터럴(ValueError)이나 깊은 중첩(RecursionError)은 계약 안의 영구 실패로 바꾼다.
        raise ExtractionError("JSON 자막을 해석하지 못했습니다", {"reason": type(exc).__name__}) from exc


def _subtitle_cues(source: str) -> tuple[list[_Cue], Any]:
    """Return raw cue lines with start seconds, plus the parsed JSON payload when the source is JSON."""

    stripped = source.lstrip("﻿ \t\r\n")
    if stripped.startswith(("[", "{")):
        try:
            payload = _load_json(stripped)
        except json.JSONDecodeError:
            pass
        else:
            return _json_transcript_cues(payload), payload

    lines = [line.strip().lstrip("﻿") for line in source.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if line:
            current.append(line)
        elif current:
            blocks.append(current)
            current = []
    if current:
        blocks.append(current)

    is_vtt = bool(blocks) and bool(_VTT_SIGNATURE.match(blocks[0][0]))
    if is_vtt:
        # WebVTT 헤더(WEBVTT 줄부터 첫 빈 줄까지: Kind/Language/X-TIMESTAMP-MAP)는 본문이 아니다.
        header = blocks.pop(0)
        cue_at = next((index for index, line in enumerate(header) if _TIMESTAMP.match(line)), None)
        if cue_at is not None:
            blocks.insert(0, header[cue_at:])

    cues: list[_Cue] = []
    seen_cue = False
    last_start: float | None = None
    for block in blocks:
        timings = [_TIMESTAMP.match(line) for line in block]
        if not any(timings):
            # 타이밍 없는 블록: VTT 주석(NOTE)과 첫 cue 앞 STYLE/REGION만 메타로 버린다. SRT에는 적용하지 않는다.
            if is_vtt and (_VTT_NOTE_BLOCK.match(block[0]) or (not seen_cue and _VTT_PRE_CUE_BLOCK.match(block[0]))):
                continue
            cues.extend(_Cue(line, last_start) for line in block)
            continue
        for index, line in enumerate(block):
            match = timings[index]
            if match is not None:
                seen_cue = True
                last_start = _parse_timestamp(match)
                continue
            if index + 1 < len(block) and timings[index + 1] is not None:
                continue  # cue 식별자(SRT 번호, VTT cue id)
            cues.append(_Cue(line, last_start))
    return cues, None


def _clean_caption_line(line: str) -> str:
    value = _INLINE_TIMESTAMP.sub("", line)
    value = _SUBTITLE_TAG.sub("", value)
    value = _ASS_OVERRIDE.sub("", value)
    value = _NON_SPEECH.sub("", value)
    value = value.replace("♪", " ")
    value = re.sub(r"<[^>]+>", "", value)
    return _SPACE.sub(" ", html.unescape(value)).strip()


def _merge_caption_cues(cues: list[_Cue]) -> list[_Cue]:
    merged: list[_Cue] = []
    recent: list[str] = []
    for cue in cues:
        current = _clean_caption_line(cue.text)
        if not current:
            continue
        key = current.casefold()
        if key in recent[-3:]:
            continue
        if merged:
            previous = merged[-1]
            previous_key = previous.text.casefold()
            if key.startswith(previous_key):
                merged[-1] = _Cue(current, previous.start)
                recent.append(key)
                continue
            if previous_key.startswith(key):
                continue
            previous_words = previous.text.split()
            current_words = current.split()
            overlap = 0
            for size in range(min(len(previous_words), len(current_words), 12), 0, -1):
                left = [word.casefold() for word in previous_words[-size:]]
                right = [word.casefold() for word in current_words[:size]]
                if left == right:
                    overlap = size
                    break
            if overlap:
                merged[-1] = _Cue(" ".join([*previous_words, *current_words[overlap:]]), previous.start)
                recent.append(key)
                continue
        merged.append(_Cue(current, cue.start))
        recent.append(key)
    return merged


def clean_transcript(vtt_or_srt: str) -> str:
    """Remove subtitle structure, non-speech markers, and overlapping duplicate cues."""

    cues, _payload = _subtitle_cues(vtt_or_srt)
    return " ".join(cue.text for cue in _merge_caption_cues(cues))


def _transcript_snapshot(source: str) -> tuple[str, list[dict[str, Any]], Any]:
    """Clean a transcript into ~3-minute paragraphs separated by blank lines.

    Returns the text, the segment start offsets (only when cues carry timings), and the JSON payload if any.
    """

    cues, payload = _subtitle_cues(source)
    merged = _merge_caption_cues(cues)
    buckets: list[tuple[float | None, list[str]]] = []
    current_bucket: int | None = None
    for cue in merged:
        bucket = None if cue.start is None else int(cue.start // TRANSCRIPT_SEGMENT_SECONDS)
        if not buckets or (bucket is not None and bucket != current_bucket):
            buckets.append((cue.start, []))
            current_bucket = bucket if bucket is not None else current_bucket
        buckets[-1][1].append(cue.text)

    parts: list[str] = []
    segments: list[dict[str, Any]] = []
    offset = 0
    for start, texts in buckets:
        part = tidy_snapshot_text(" ".join(texts))
        if not part:
            continue
        if parts:
            offset += 2
        if start is not None:
            segments.append({"start_sec": round(start, 3), "offset": offset})
        parts.append(part)
        offset += len(part)
    return "\n\n".join(parts), segments, payload


def _looks_like_subtitles(source: str) -> bool:
    stripped = source.lstrip("﻿ \t\r\n")
    if stripped.startswith(("[", "{")) or _VTT_SIGNATURE.match(stripped.split("\n", 1)[0].strip()):
        return True
    return any(_TIMESTAMP.match(line.strip()) for line in stripped.splitlines()[:50])


# ------------------------------------------------------------------------- entry


def _detect_language(text: str, hint: Any = None) -> str:
    if isinstance(hint, str) and hint.strip():
        code = hint.strip().replace("_", "-").split("-", 1)[0].casefold()
        if re.fullmatch(r"[a-z]{2,3}", code):
            return code
    if re.search(r"[가-힣]", text):
        return "ko"
    if re.search(r"[ぁ-ゟ゠-ヿ]", text):
        return "ja"
    if re.search(r"[一-鿿]", text):
        return "zh"
    if re.search(r"[A-Za-z]", text):
        return "en"
    return "und"


def _cap(value: str, max_chars: int) -> tuple[str, bool]:
    if len(value) <= max_chars:
        return value, False
    return value[:max_chars].rstrip(), True


def _source_size(raw: RawSource) -> int:
    return len(raw.body)  # bytes는 바이트 수, str은 문자 수


def extract_snapshot(raw: RawSource, platform: Platform, max_chars: int = 100_000) -> SnapshotDraft:
    """Extract a snapshot without making external network calls.

    The path is chosen by source format (kind, MIME), never by platform: direct text (`kind=text`) is
    never run through the subtitle cleaner, even when it is saved under a YouTube item.
    """

    if max_chars <= 0:
        raise ValueError("max_chars는 1 이상이어야 합니다")
    mime = raw.mime.partition(";")[0].strip().casefold()
    if _source_size(raw) > MAX_SOURCE_BYTES:
        raise ExtractionError(
            "원본이 너무 큽니다",
            {"kind": raw.kind, "mime": mime, "size": _source_size(raw), "limit": MAX_SOURCE_BYTES},
        )

    is_html = raw.kind not in ("text", "image") and mime in _HTML_MIMES
    source = _decode_body(raw, is_html=is_html or (raw.kind == "url" and mime not in _SUBTITLE_MIMES))
    if not is_html and raw.kind == "url" and mime not in _SUBTITLE_MIMES:
        is_html = bool(re.search(r"<(?:html|article|main)\b", source, re.I))

    from jupjup.ingest.youtube import is_youtube_url, unavailable

    if (
        raw.kind not in ("text", "image")
        and (raw.kind == "youtube" or is_youtube_url(raw.final_url))
        and (is_html or (mime not in _SUBTITLE_MIMES and not _looks_like_subtitles(source)))
    ):
        raise unavailable("video_requires_transcript")

    metadata: dict[str, Any] = {}
    extra_meta: dict[str, Any] = {}
    text = ""
    ocr_text: str | None = None

    if raw.kind == "image":
        ocr_text = tidy_snapshot_text(source)
    elif raw.kind == "text":
        text = tidy_snapshot_text(source)
    elif is_html:
        text, metadata = _extract_html(source)
        validate_html_body(text, metadata.get("title"))
    elif mime in _SUBTITLE_MIMES or (raw.kind == "youtube" and _looks_like_subtitles(source)):
        text, segments, payload = _transcript_snapshot(source)
        if segments:
            extra_meta["transcript_segments"] = segments
        if isinstance(payload, dict):
            metadata = {
                "title": _collapse(payload.get("title") if isinstance(payload.get("title"), str) else None),
                "author": _collapse(payload.get("author") if isinstance(payload.get("author"), str) else None),
                "published_at": _parse_published(payload.get("published_at")),
                "language": payload.get("language"),
            }
    else:
        text = tidy_snapshot_text(source)

    # 검색에 쓸 글자가 하나도 없으면(공백, 이모지, [음악]뿐) 빈 본문으로 본다.
    if not normalize_text(text):
        text = ""
    if ocr_text is not None and not normalize_text(ocr_text):
        ocr_text = None

    truncated = False
    if text:
        text, truncated = _cap(text, max_chars)
    elif ocr_text:
        ocr_text, truncated = _cap(ocr_text, max_chars)

    if not text and not ocr_text:
        raise SourceTextUnavailableError(
            "가져올 수 있는 본문이 없어요. 원문이나 자막을 텍스트로 직접 저장해 주세요.",
            {"kind": raw.kind, "mime": mime, "platform": platform},
        )

    raw_meta = {**raw.meta, "source_mime": mime}
    if "transcript_segments" in extra_meta:
        raw_meta["transcript_segments"] = [
            segment for segment in extra_meta["transcript_segments"] if segment["offset"] < len(text)
        ]
    title = _collapse(raw_meta.get("title") if isinstance(raw_meta.get("title"), str) else metadata.get("title"))
    author = _collapse(raw_meta.get("author") if isinstance(raw_meta.get("author"), str) else metadata.get("author"))
    published = _parse_published(raw_meta.get("published_at")) or _parse_published(metadata.get("published_at"))
    combined = text or ocr_text or ""
    language = _detect_language(combined, raw_meta.get("language") or metadata.get("language"))
    content_hash = hashlib.sha256((text + "\x00" + (ocr_text or "")).encode("utf-8")).hexdigest()
    return SnapshotDraft(
        text=text,
        ocr_text=ocr_text,
        title_guess=title,
        author_guess=author,
        published_at_guess=published,
        language=language,
        raw_meta=raw_meta,
        content_hash=content_hash,
        truncated=truncated,
    )


def validate_html_body(text: str, title: str | None = None) -> None:
    compact = re.sub(r"\s+", "", text).casefold()
    title_compact = re.sub(r"\s+", "", title or "").casefold()
    labels = (
        "개인정보처리방침",
        "정책및안전",
        "youtube작동의원리",
        "새로운기능테스트하기",
        "googlellc",
        "정보",
        "보도자료",
        "저작권",
        "문의하기",
        "크리에이터",
        "광고",
        "개발자",
        "약관",
        "privacy",
        "terms",
        "copyright",
    )
    remainder = compact
    for label in labels:
        remainder = remainder.replace(label, "")
    label_ratio = (len(compact) - len(remainder)) / max(1, len(compact))
    # Legal-topic prose is source text. Only a predominance of menu labels with
    # no prose sentence is rejected; nav/footer elements were already excluded.
    has_prose = bool(re.search(r"(?:다|요)[.!?。！？](?:\s|$)", text))
    boilerplate = len(compact) < 1500 and label_ratio >= 0.65 and not has_prose
    if not compact or compact == title_compact or boilerplate:
        raise SourceTextUnavailableError(
            "본문 대신 제목이나 메뉴·약관만 가져왔어요. 원문을 텍스트로 직접 저장해 주세요.",
            {"reason": "html_without_body", "retryable": False},
        )

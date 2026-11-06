"""T19 Loop 1 검수(specs/phase4_review_ingest-t19_loop1.md) 재현 입력을 회귀 테스트로 고정한다."""

from __future__ import annotations

import errno
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from jupjup.domain.errors import ExtractionError, FetchError, UnsupportedSourceError
from jupjup.ingest.extract import MAX_SOURCE_BYTES, clean_transcript, extract_snapshot
from jupjup.ingest.fetch import (
    FixtureHtmlFetcher,
    FixtureTranscriptFetcher,
    InlineTextFetcher,
    RawSource,
    SourceSpec,
)

FIXTURES = Path(__file__).parents[1] / "fixtures" / "ingest"
FIXED_NOW = datetime(2026, 10, 20, 10, 0, tzinfo=UTC)


def _html(body: str | bytes, mime: str = "text/html") -> RawSource:
    return RawSource(kind="url", body=body, mime=mime, fetched_at=FIXED_NOW)


def _srt(body: str) -> RawSource:
    return RawSource(kind="youtube", body=body, mime="application/x-subrip; charset=utf-8", fetched_at=FIXED_NOW)


def _vtt(body: str) -> RawSource:
    return RawSource(kind="youtube", body=body, mime="text/vtt; charset=utf-8", fetched_at=FIXED_NOW)


# ----------------------------------------------------------------------------- H1


SRT_WITH_KEYWORD_LINES = """1
00:00:00,000 --> 00:00:02,000
Notebook LM 소개합니다

2
00:00:02,000 --> 00:00:04,000
Style 팁도 알려드려요
다음 줄도 남아요

3
00:00:04,000 --> 00:00:06,000
Regional 맛집 정리

4
00:00:06,000 --> 00:00:08,000
Language: 한국어로 진행합니다

5
00:00:08,000 --> 00:00:10,000
Kind: 친절하게 설명합니다
"""


def test_srt_cues_starting_with_vtt_keywords_are_kept() -> None:
    text = extract_snapshot(_srt(SRT_WITH_KEYWORD_LINES), "youtube").text

    for phrase in (
        "Notebook LM 소개합니다",
        "Style 팁도 알려드려요",
        "다음 줄도 남아요",
        "Regional 맛집 정리",
        "Language: 한국어로 진행합니다",
        "Kind: 친절하게 설명합니다",
    ):
        assert phrase in text


def test_vtt_header_and_pre_cue_metadata_blocks_are_still_removed() -> None:
    vtt = """WEBVTT - 예제
Kind: captions
Language: ko
X-TIMESTAMP-MAP=MPEGTS:0,LOCAL:00:00:00.000

STYLE
::cue { color: yellow }

REGION
id:fred width:40%

NOTE 이 파일은 테스트용입니다
여러 줄 주석

intro
00:00:00.000 --> 00:00:02.000 align:start
Notebook 리뷰를 시작합니다

NOTE 중간 주석도 버린다

00:00:02.000 --> 00:00:04.000
Style 이야기도 합니다
Region 별 차이도 봅니다
"""
    text = clean_transcript(vtt)

    assert text == "Notebook 리뷰를 시작합니다 Style 이야기도 합니다 Region 별 차이도 봅니다"
    for leaked in ("captions", "MPEGTS", "color", "fred", "테스트용", "주석", "intro", "WEBVTT"):
        assert leaked not in text


@pytest.mark.parametrize("platform", ["youtube", "instagram", "web"])
def test_direct_text_never_goes_through_subtitle_cleaner(platform: str) -> None:
    fetcher = InlineTextFetcher(clock=lambda: FIXED_NOW)
    body = "NOTE 메모: 꼭 볼 영상\n주말에 다시 보기\n\n네\n좋아요\n네\n(웃음) 00:00:01.000 --> 00:00:02.000"
    raw = fetcher.fetch(SourceSpec(kind="text", text=body))

    text = extract_snapshot(raw, platform).text  # type: ignore[arg-type]

    assert text == body


def test_youtube_plain_text_without_subtitle_structure_uses_plain_path() -> None:
    raw = RawSource(kind="url", body="NOTE 설명란 메모\n네\n네", mime="text/plain", fetched_at=FIXED_NOW)
    assert extract_snapshot(raw, "youtube").text == "NOTE 설명란 메모\n네\n네"


# ----------------------------------------------------------------------------- M1


@pytest.mark.parametrize("void", ["<input type='checkbox'>", "<embed src='x.swf'>", "<br>", "<img src='a.png'>"])
def test_void_elements_without_slash_keep_following_body(void: str) -> None:
    raw = _html(f"<article><p>앞 문단</p>{void} 체크 뒤 본문이 이어집니다<p>마지막 문단</p></article>")
    text = extract_snapshot(raw, "web").text

    assert "앞 문단" in text
    assert "체크 뒤 본문이 이어집니다" in text
    assert "마지막 문단" in text


def test_many_br_lines_finish_quickly() -> None:
    raw = _html("<article>" + "<br>본문 줄" * 20_000 + "</article>")
    started = time.perf_counter()
    snapshot = extract_snapshot(raw, "web", max_chars=1_000_000)
    elapsed = time.perf_counter() - started

    assert snapshot.text.count("본문 줄") == 20_000
    assert elapsed < 1.0


def test_deep_nesting_finishes_quickly() -> None:
    raw = _html("<article>" + "<div>" * 50_000 + "깊은 본문" + "</div>" * 50_000 + "</article>")
    started = time.perf_counter()
    snapshot = extract_snapshot(raw, "web")
    elapsed = time.perf_counter() - started

    assert snapshot.text == "깊은 본문"
    assert elapsed < 2.0


def test_stray_end_tags_do_not_scan_the_whole_stack() -> None:
    raw = _html("<article>" + "<div>" * 20_000 + "본문" + "</span></br>" * 20_000 + "</article>")
    started = time.perf_counter()
    assert "본문" in extract_snapshot(raw, "web").text
    assert time.perf_counter() - started < 2.0


def test_oversized_source_fails_explicitly() -> None:
    raw = _html("<article>" + "가" * (MAX_SOURCE_BYTES + 1) + "</article>")
    with pytest.raises(ExtractionError) as caught:
        extract_snapshot(raw, "web")
    assert caught.value.code == "INGEST_EXTRACT_FAILED"


# ----------------------------------------------------------------------------- M2


@pytest.mark.parametrize(
    "markup",
    [
        '<body class="has-sidebar"><article><p>진짜 본문</p></article></body>',
        '<div class="layout no-sidebar"><main><p>진짜 본문</p></main></div>',
        '<html class="nav-fixed menu-open"><body class="share-enabled"><p>진짜 본문</p></body></html>',
        '<div class="sidebar-layout"><div role="main"><p>진짜 본문</p></div></div>',
        '<article class="post has-share-buttons"><p>진짜 본문</p></article>',
    ],
)
def test_layout_wrapper_classes_do_not_drop_the_page(markup: str) -> None:
    assert extract_snapshot(_html(markup), "web").text == "진짜 본문"


def test_real_nuisance_regions_are_still_excluded() -> None:
    markup = (
        '<body class="has-sidebar"><div class="sidebar"><p>사이드 추천</p><div class="post">티저</div></div>'
        '<article><p>진짜 본문</p><div class="share-buttons">공유하기</div>'
        '<div class="post related">관련 글</div></article></body>'
    )
    assert extract_snapshot(_html(markup), "web").text == "진짜 본문"


# ----------------------------------------------------------------------------- M3


def test_html_snapshot_keeps_block_and_heading_boundaries() -> None:
    raw = _html("<article><h2>섹션1</h2><p>문단 하나.</p><h2>섹션2</h2><p>문단 둘.<br>둘째 줄.</p></article>")
    assert extract_snapshot(raw, "web").text == "섹션1\n\n문단 하나.\n\n섹션2\n\n문단 둘.\n둘째 줄."


def test_inline_elements_do_not_insert_spaces_and_case_emoji_survive() -> None:
    raw = _html("<article><p>카페 <a href='#'>노티드</a>에서 <b>Python</b> 3.12 공부 😀</p></article>")
    snapshot = extract_snapshot(raw, "web")

    assert snapshot.text == "카페 노티드에서 Python 3.12 공부 😀"


def test_snapshot_cleanup_is_light_and_hash_tracks_final_text() -> None:
    raw = RawSource(
        kind="text",
        body="  첫 문단\u200b  Ｐｙｔｈｏｎ\t메모\r\n\r\n\r\n\r\n둘째 문단\x07 ",
        mime="text/plain",
        fetched_at=FIXED_NOW,
    )
    snapshot = extract_snapshot(raw, "local")

    assert snapshot.text == "첫 문단 Ｐｙｔｈｏｎ 메모\n\n둘째 문단"
    other = extract_snapshot(raw.model_copy(update={"body": "첫 문단 Ｐｙｔｈｏｎ 메모\n\n둘째 문단"}), "local")
    assert other.content_hash == snapshot.content_hash


def test_transcript_snapshot_is_split_into_three_minute_segments() -> None:
    cues = []
    for index, (start, line) in enumerate(
        [(0, "첫 구간 시작"), (60, "첫 구간 끝"), (185, "둘째 구간"), (400, "셋째 구간")]
    ):
        minutes, seconds = divmod(start, 60)
        cues.append(
            f"{index + 1}\n00:{minutes:02d}:{seconds:02d},000 --> 00:{minutes:02d}:{seconds + 1:02d},000\n{line}\n"
        )
    snapshot = extract_snapshot(_srt("\n".join(cues)), "youtube")

    assert snapshot.text == "첫 구간 시작 첫 구간 끝\n\n둘째 구간\n\n셋째 구간"
    segments = snapshot.raw_meta["transcript_segments"]
    assert segments == [
        {"start_sec": 0.0, "offset": 0},
        {"start_sec": 185.0, "offset": len("첫 구간 시작 첫 구간 끝\n\n")},
        {"start_sec": 400.0, "offset": len("첫 구간 시작 첫 구간 끝\n\n둘째 구간\n\n")},
    ]
    for segment, expected in zip(segments, ("첫 구간", "둘째 구간", "셋째 구간"), strict=True):
        assert snapshot.text[segment["offset"] :].startswith(expected)


def test_json_transcript_segments_use_tstartms() -> None:
    body = '{"events": [{"tStartMs": 0, "segs": [{"utf8": "하나"}]},{"tStartMs": 200000, "segs": [{"utf8": "둘"}]}]}'
    raw = RawSource(kind="youtube", body=body, mime="application/json", fetched_at=FIXED_NOW)
    snapshot = extract_snapshot(raw, "youtube")

    assert snapshot.text == "하나\n\n둘"
    assert snapshot.raw_meta["transcript_segments"] == [
        {"start_sec": 0.0, "offset": 0},
        {"start_sec": 200.0, "offset": 4},
    ]


@pytest.mark.parametrize(
    "raw",
    [
        _html("<html><body><nav>메뉴</nav><div class='ad'>광고</div></body></html>"),
        RawSource(kind="text", body="   \n\t ", mime="text/plain", fetched_at=FIXED_NOW),
        RawSource(kind="text", body="😀🎉", mime="text/plain", fetched_at=FIXED_NOW),
        RawSource(kind="image", body=" \n ", mime="text/plain", fetched_at=FIXED_NOW),
    ],
)
def test_bodies_without_searchable_text_still_fail(raw: RawSource) -> None:
    with pytest.raises(ExtractionError):
        extract_snapshot(raw, "web")


def test_music_only_vtt_still_fails() -> None:
    with pytest.raises(ExtractionError):
        extract_snapshot(_vtt("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\n[음악]\n"), "youtube")


# ----------------------------------------------------------------------------- L1


def test_permanent_fixture_failures_are_unsupported_not_retryable(tmp_path: Path) -> None:
    root = tmp_path / "fixtures"
    (root / "h").mkdir(parents=True)
    (root / "dir.html").mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "x.html").write_text("<article>비밀</article>", encoding="utf-8")
    (root / "linked").symlink_to(outside, target_is_directory=True)
    fetcher = FixtureHtmlFetcher(root, clock=lambda: FIXED_NOW)

    for fixture in (
        "../secret.html",
        "h/../../x.html",
        "/etc/passwd.html",
        "C:\\x.html",
        "h\\1.html",
        "linked/x.html",
        "missing.html",
        "%2e%2e/secret.html",
        "dir.html",
    ):
        with pytest.raises(UnsupportedSourceError):
            fetcher.fetch(SourceSpec(kind="url", fixture=fixture))

    with pytest.raises(UnsupportedSourceError):
        FixtureHtmlFetcher(tmp_path / "no-root")


def test_invalid_utf8_transcript_fixture_is_permanent(tmp_path: Path) -> None:
    (tmp_path / "bad.vtt").write_bytes(b"WEBVTT\n\n00:00:00.000 --> 00:00:01.000\n\xff\xfe\n")
    fetcher = FixtureTranscriptFetcher(tmp_path, clock=lambda: FIXED_NOW)
    with pytest.raises(UnsupportedSourceError):
        fetcher.fetch(SourceSpec(kind="youtube", fixture="bad.vtt"))


def test_transient_io_error_stays_retryable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "ok.html").write_text("<article>본문</article>", encoding="utf-8")
    fetcher = FixtureHtmlFetcher(tmp_path, clock=lambda: FIXED_NOW)

    def broken_read(_self: Path) -> bytes:
        raise OSError(errno.EIO, "I/O error")

    monkeypatch.setattr(Path, "read_bytes", broken_read)
    with pytest.raises(FetchError):
        fetcher.fetch(SourceSpec(kind="url", fixture="ok.html"))


# ----------------------------------------------------------------------------- L2


@pytest.mark.parametrize(
    "body",
    [
        '{"events": [{"segs": [{"utf8": "숫자"}]}], "n": ' + "9" * 5_000 + "}",
        '{"events": ' + "[" * 3_000 + '"깊음"' + "]" * 3_000 + "}",
        '{"events": ' + "[" * 100 + '"깊음"' + "]" * 100 + "}",
    ],
)
def test_pathological_json_transcripts_raise_extraction_error(body: str) -> None:
    raw = RawSource(kind="youtube", body=body, mime="application/json", fetched_at=FIXED_NOW)
    with pytest.raises(ExtractionError):
        extract_snapshot(raw, "youtube")


# ----------------------------------------------------------------------------- L3


def test_meta_charset_euc_kr_is_honoured() -> None:
    body = '<html><head><meta charset="euc-kr"></head><body><article><p>한글 본문입니다</p></article></body></html>'
    for mime in ("text/html", "text/html; charset=utf-8"):
        assert extract_snapshot(_html(body.encode("euc-kr"), mime), "web").text == "한글 본문입니다"


def test_http_equiv_charset_is_honoured() -> None:
    body = (
        '<html><head><meta http-equiv="Content-Type" content="text/html; charset=EUC-KR"></head>'
        "<body><p>옛 페이지</p></body></html>"
    )
    assert extract_snapshot(_html(body.encode("euc-kr")), "web").text == "옛 페이지"


def test_undecodable_bytes_fail_instead_of_silent_mojibake() -> None:
    body = b"<html><body><article><p>" + bytes(range(0x80, 0xFF)) * 4 + b"</p></article></body></html>"
    with pytest.raises(ExtractionError):
        extract_snapshot(_html(body, "text/html; charset=utf-8"), "web")


def test_fixture_html_mime_does_not_claim_a_charset() -> None:
    fetcher = FixtureHtmlFetcher(FIXTURES / "html", clock=lambda: FIXED_NOW)
    assert fetcher.fetch(SourceSpec(kind="url", fixture="article.html")).mime == "text/html"


# ----------------------------------------------------------------------------- L4


def test_svg_title_does_not_leak_into_document_title() -> None:
    raw = _html(
        "<html><head><title>진짜 제목</title></head><body>"
        "<article><svg><title>icon</title></svg><p>본문</p></article></body></html>"
    )
    snapshot = extract_snapshot(raw, "web")

    assert snapshot.title_guess == "진짜 제목"
    assert "icon" not in snapshot.text

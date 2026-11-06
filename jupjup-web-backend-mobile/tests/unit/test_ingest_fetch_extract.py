"""T19 network-free source fetching and snapshot extraction."""

from __future__ import annotations

import socket
from datetime import UTC, datetime
from pathlib import Path
from typing import NoReturn

import pytest

from jupjup.domain.errors import ExtractionError, UnsupportedSourceError
from jupjup.ingest.extract import clean_transcript, extract_snapshot
from jupjup.ingest.fetch import (
    FetcherRouter,
    FixtureHtmlFetcher,
    FixtureTranscriptFetcher,
    InlineTextFetcher,
    RawSource,
    SourceFetcher,
    SourceSpec,
)

FIXTURES = Path(__file__).parents[1] / "fixtures" / "ingest"
FIXED_NOW = datetime(2026, 10, 20, 10, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("fixture", "expected", "excluded"),
    [
        ("article.html", "성수동에 새로운 독립 서점", "광고 구매 문구"),
        ("main.html", "서울숲의 벚꽃 산책로", "사이트 머리글"),
        ("role-main.html", "도시 기온을 십 년", "후원 상품 안내"),
        ("article-body.html", "제주 동쪽 해안", "호텔 특가 광고"),
        ("post-content.html", "토마토를 약한 불", "뉴스레터 구독"),
        ("story-body.html", "새로운 얼음 지형", "공유 버튼 모음"),
        ("entry-content.html", "흙을 다듬고 물레", "댓글을 남겨"),
        ("content-id.html", "재즈 삼중주가 공연", "예매 광고 배너"),
        ("body-fallback.html", "project released a stable version", "buy cloud hosting"),
        ("itemprop.html", "제철 과일과 채소", "개인정보 처리방침"),
    ],
)
def test_ten_html_fixtures_extract_body_without_navigation_or_ads(
    fixture: str,
    expected: str,
    excluded: str,
) -> None:
    fetcher = FixtureHtmlFetcher(FIXTURES / "html", clock=lambda: FIXED_NOW)
    raw = fetcher.fetch(SourceSpec(kind="url", fixture=fixture, url=f"https://example.test/{fixture}"))

    first = extract_snapshot(raw, "news")
    second = extract_snapshot(raw, "news")

    assert expected in first.text
    assert excluded not in first.text
    assert first == second
    assert len(first.content_hash) == 64


def test_html_metadata_is_extracted() -> None:
    fetcher = FixtureHtmlFetcher(FIXTURES / "html", clock=lambda: FIXED_NOW)
    article = extract_snapshot(fetcher.fetch(SourceSpec(kind="url", fixture="article-body.html")), "blog")
    dated = extract_snapshot(fetcher.fetch(SourceSpec(kind="url", fixture="story-body.html")), "news")

    assert article.title_guess == "제주 여행 기록"
    assert article.author_guess == "김여행"
    assert article.language == "ko"
    assert dated.published_at_guess is not None
    assert dated.published_at_guess.isoformat() == "2026-10-20T09:30:00+09:00"


def test_vtt_srt_and_json_transcripts_are_cleaned() -> None:
    root = FIXTURES / "transcript"
    fetcher = FixtureTranscriptFetcher(root, clock=lambda: FIXED_NOW)

    vtt = fetcher.fetch(SourceSpec(kind="youtube", fixture="sample.vtt"))
    srt = fetcher.fetch(SourceSpec(kind="youtube", fixture="sample.srt"))
    json_raw = fetcher.fetch(SourceSpec(kind="youtube", fixture="sample.json"))

    assert clean_transcript(str(vtt.body)) == "안녕하세요 오늘은 성수동을 걷습니다 그리고 카페에 갑니다"
    assert clean_transcript(str(srt.body)) == "첫 번째 문장입니다. 두 번째 문장입니다."
    assert clean_transcript(str(json_raw.body)) == "제이슨 자막의 첫 문장입니다 두 번째 문장입니다"
    json_snapshot = extract_snapshot(json_raw, "youtube")
    assert json_snapshot.title_guess == "JSON 자막 예제"
    assert json_snapshot.language == "ko"


def test_fixture_paths_reject_parent_absolute_and_symlink_escape(tmp_path: Path) -> None:
    root = tmp_path / "fixtures"
    root.mkdir()
    (root / "safe.html").write_text("<article>안전한 본문</article>", encoding="utf-8")
    outside = tmp_path / "outside.html"
    outside.write_text("<article>외부 비밀</article>", encoding="utf-8")
    (root / "escape.html").symlink_to(outside)
    fetcher = FixtureHtmlFetcher(root, clock=lambda: FIXED_NOW)

    # 경로 탈출은 재시도해도 같으므로 영구 실패(UnsupportedSourceError)다 (Loop 1 L1).
    for fixture in ("../outside.html", str(outside), "escape.html"):
        with pytest.raises(UnsupportedSourceError):
            fetcher.fetch(SourceSpec(kind="url", fixture=fixture))

    safe = fetcher.fetch(SourceSpec(kind="url", fixture="safe.html"))
    assert "안전한 본문" in extract_snapshot(safe, "web").text


def test_fetchers_and_router_never_open_a_network_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    html_fetcher = FixtureHtmlFetcher(FIXTURES / "html", clock=lambda: FIXED_NOW)
    transcript_fetcher = FixtureTranscriptFetcher(FIXTURES / "transcript", clock=lambda: FIXED_NOW)

    def network_forbidden(*_args: object, **_kwargs: object) -> NoReturn:
        raise AssertionError("network access is forbidden")

    monkeypatch.setattr(socket, "socket", network_forbidden)
    monkeypatch.setattr(socket, "create_connection", network_forbidden)
    router = FetcherRouter([InlineTextFetcher(clock=lambda: FIXED_NOW), html_fetcher, transcript_fetcher])

    inline = router.fetch(SourceSpec(kind="text", text="직접 입력한 본문"))
    html_raw = router.fetch(SourceSpec(kind="url", fixture="article.html"))
    transcript = router.fetch(SourceSpec(kind="youtube", fixture="sample.vtt"))

    assert extract_snapshot(inline, "local").text == "직접 입력한 본문"
    assert "독립 서점" in extract_snapshot(html_raw, "news").text
    assert "성수동" in extract_snapshot(transcript, "youtube").text


def test_inline_text_and_ocr_are_dispatched_without_files() -> None:
    inline = InlineTextFetcher(clock=lambda: FIXED_NOW)
    assert isinstance(inline, SourceFetcher)
    router = FetcherRouter([inline])

    text = router.fetch(SourceSpec(kind="text", text="  Hello   WORLD  "))
    image = router.fetch(SourceSpec(kind="image", ocr_text="  영수증   합계 12,000원 "))

    assert text.fetched_at == FIXED_NOW
    # 스냅샷은 가벼운 정리만 한다: 대소문자 보존, 공백만 정리 (Loop 1 M3).
    assert extract_snapshot(text, "web").text == "Hello WORLD"
    image_snapshot = extract_snapshot(image, "local")
    assert image_snapshot.text == ""
    assert image_snapshot.ocr_text == "영수증 합계 12,000원"


def test_router_rejects_unsupported_source() -> None:
    router = FetcherRouter([InlineTextFetcher(clock=lambda: FIXED_NOW)])
    with pytest.raises(UnsupportedSourceError) as caught:
        router.fetch(SourceSpec(kind="url", url="https://example.test/no-fixture"))
    assert caught.value.code == "INGEST_UNSUPPORTED"


def test_empty_extracted_body_raises_extraction_error() -> None:
    raw = RawSource(
        kind="url",
        body="<html><body><nav>메뉴뿐입니다</nav><div class='advertisement'>광고뿐입니다</div></body></html>",
        mime="text/html",
        fetched_at=FIXED_NOW,
    )
    with pytest.raises(ExtractionError) as caught:
        extract_snapshot(raw, "web")
    assert caught.value.code == "SOURCE_TEXT_UNAVAILABLE"


def test_max_chars_is_deterministic_and_marks_truncation() -> None:
    raw = RawSource(kind="text", body="가나다라마바사", mime="text/plain", fetched_at=FIXED_NOW)
    first = extract_snapshot(raw, "local", max_chars=4)
    second = extract_snapshot(raw, "local", max_chars=4)

    assert first == second
    assert first.text == "가나다라"
    assert first.truncated
    with pytest.raises(ValueError, match="max_chars"):
        extract_snapshot(raw, "local", max_chars=0)

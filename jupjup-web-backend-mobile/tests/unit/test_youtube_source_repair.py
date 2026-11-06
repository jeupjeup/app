"""Public-caption integration and unsafe/empty source regression."""

import json
from datetime import UTC, datetime

import pytest

from jupjup.domain.errors import SourceTextUnavailableError
from jupjup.ingest.extract import extract_snapshot
from jupjup.ingest.fetch import HttpResponse, HttpSourceFetcher, RawSource, SourceSpec
from jupjup.ingest.youtube import YoutubeCaptionFetcher

WATCH = "https://www.youtube.com/watch?v=EbL67RhCGbY"
CAPTION = "https://www.youtube.com/api/timedtext?v=EbL67RhCGbY&lang=ko"
TRANSCRIPT = {"events": [{"tStartMs": 0, "segs": [{"utf8": "올바른 영상 내용으로 요약을 검증합니다."}]}]}


def fetcher(*, player=None, caption=None, limit=5000, redirect=None):
    calls = []
    if player is None:
        player = {
            "playabilityStatus": {"status": "OK"},
            "captions": {
                "playerCaptionsTracklistRenderer": {"captionTracks": [{"baseUrl": CAPTION, "languageCode": "ko"}]}
            },
        }

    def transport(url, timeout):
        calls.append(url)
        if len(calls) == 1:
            return HttpResponse(
                200,
                {"content-type": "text/html"},
                ("<script>var ytInitialPlayerResponse = " + json.dumps(player) + ";</script>").encode(),
            )
        if redirect:
            return HttpResponse(302, {"location": redirect}, b"")
        return HttpResponse(
            200, {"content-type": "application/json"}, json.dumps(TRANSCRIPT if caption is None else caption).encode()
        )

    http = HttpSourceFetcher(resolver=lambda host: ["8.8.8.8"], transport=transport, max_bytes=limit)
    return YoutubeCaptionFetcher(http), calls


def test_public_caption_path_reaches_real_http_and_extracts():
    f, calls = fetcher()
    raw = f.fetch(SourceSpec(kind="url", url=WATCH))
    draft = extract_snapshot(raw, "youtube")
    assert draft.text == "올바른 영상 내용으로 요약을 검증합니다."
    assert raw.final_url == WATCH
    assert raw.meta["source"] == "youtube_captions"
    assert len(calls) == 2 and "fmt=json3" in calls[1]


@pytest.mark.parametrize(
    "player",
    [
        {},
        {"playabilityStatus": {"status": "LOGIN_REQUIRED"}},
        {"playabilityStatus": {"status": "OK"}},
    ],
)
def test_no_caption_or_blocked(player):
    f, calls = fetcher(player=player)
    with pytest.raises(SourceTextUnavailableError):
        f.fetch(SourceSpec(kind="url", url=WATCH))
    assert len(calls) == 1


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/api/timedtext",
        "https://evil.example/api/timedtext",
        "https://youtube.com.evil.example/api/timedtext",
        "https://user:pass@www.youtube.com/api/timedtext",
    ],
)
def test_malicious_caption_url_never_requested(url):
    player = {
        "playabilityStatus": {"status": "OK"},
        "captions": {"playerCaptionsTracklistRenderer": {"captionTracks": [{"baseUrl": url}]}},
    }
    f, calls = fetcher(player=player)
    with pytest.raises(SourceTextUnavailableError):
        f.fetch(SourceSpec(kind="url", url=WATCH))
    assert len(calls) == 1


@pytest.mark.parametrize("redirect", ["http://127.0.0.1/private", "https://evil.example/x"])
def test_caption_redirect_is_checked_before_request(redirect):
    f, calls = fetcher(redirect=redirect)
    with pytest.raises(SourceTextUnavailableError):
        f.fetch(SourceSpec(kind="url", url=WATCH))
    assert len(calls) == 2


def test_oversized_captions():
    f, _ = fetcher(caption={"events": ["x" * 6000]})
    with pytest.raises(SourceTextUnavailableError):
        f.fetch(SourceSpec(kind="url", url=WATCH))


@pytest.mark.parametrize("body", ["", {"events": []}, {"events": [{"segs": [{"utf8": "[음악]"}]}]}])
def test_empty_captions_fail(body):
    f, _ = fetcher(caption=body)
    with pytest.raises(SourceTextUnavailableError):
        extract_snapshot(f.fetch(SourceSpec(kind="youtube", url=WATCH)), "youtube")


@pytest.mark.parametrize(
    "body,url",
    [
        ("<title>제목뿐</title><h1>제목뿐</h1>", "https://example.com"),
        ("<nav>메뉴</nav><footer>약관</footer>", "https://example.com"),
        (
            "<div>정보보도자료저작권문의하기크리에이터광고개발자약관개인정보처리방침 Google LLC</div>",
            "https://example.com",
        ),
        ("<article>영상 제목이 있는 watch HTML</article>", WATCH),
    ],
)
def test_html_without_source_text(body, url):
    raw = RawSource(kind="url", body=body, mime="text/html", fetched_at=datetime.now(UTC), final_url=url)
    with pytest.raises(SourceTextUnavailableError):
        extract_snapshot(raw, "web")


@pytest.mark.parametrize(
    "mime,body",
    [
        ("text/vtt", "WEBVTT\n\n00:00:00.000 --> 00:00:03.000\n정상 자막입니다."),
        ("application/x-subrip", "1\n00:00:00,000 --> 00:00:03,000\n정상 자막입니다."),
        ("application/json", json.dumps(TRANSCRIPT)),
    ],
)
def test_supplied_transcripts_preserved(mime, body):
    raw = RawSource(kind="youtube", body=body, mime=mime, fetched_at=datetime.now(UTC), final_url=WATCH)
    assert extract_snapshot(raw, "youtube").text


def test_inline_and_article_preserved():
    for kind, mime, body in [
        ("text", "text/plain", "개인정보처리방침과 약관 저작권에 관한 내 메모"),
        (
            "url",
            "text/html",
            "<article><h1>기사 제목</h1><p>오늘 발표한 연구는 새로운 실험 결과를 설명합니다.</p></article>",
        ),
    ]:
        raw = RawSource(kind=kind, mime=mime, body=body, fetched_at=datetime.now(UTC))
        assert extract_snapshot(raw, "web").text


def test_legitimate_privacy_terms_copyright_article_is_preserved():
    body = (
        "<article><h1>개인정보처리방침 변경 안내</h1><p>이번 개인정보처리방침과 약관 변경은 "
        "저작권 보호 범위를 명확히 설명합니다. 개발자는 새 규칙을 확인하고 적용할 수 있습니다.</p></article>"
    )
    raw = RawSource(kind="url", body=body, mime="text/html", fetched_at=datetime.now(UTC))
    assert "보호 범위" in extract_snapshot(raw, "web").text


def test_caption_dns_rebinding_is_rejected():
    resolutions = 0
    f, calls = fetcher()

    def resolver(host):
        nonlocal resolutions
        resolutions += 1
        return ["8.8.8.8"] if resolutions == 1 else ["127.0.0.1"]

    f.http._resolver = resolver
    with pytest.raises(SourceTextUnavailableError):
        f.fetch(SourceSpec(kind="url", url=WATCH))
    assert len(calls) == 1

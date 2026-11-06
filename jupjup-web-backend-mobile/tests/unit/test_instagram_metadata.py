from pathlib import Path

import pytest

from jupjup.domain.errors import ContentValidationError, UnsupportedSourceError
from jupjup.ingest.extract import extract_snapshot
from jupjup.ingest.fetch import HttpResponse, HttpSourceFetcher, SourceSpec
from jupjup.ingest.instagram import InstagramMetadataFetcher, canonical_instagram_url
from jupjup.save.dedupe import normalize_source_url

URL = "https://www.instagram.com/p/Ab_c-123/"


def fetch(html=None, url=URL, responses=None, address="93.184.216.34", **kwargs):
    calls = []
    body = html if html is not None else Path("tests/fixtures/instagram/post.html").read_text()
    queue = list(responses or [HttpResponse(200, {"content-type": "text/html; charset=utf-8"}, body.encode())])

    def transport(url, timeout):
        calls.append(url)
        return queue.pop(0)

    http = HttpSourceFetcher(resolver=lambda _: [address], transport=transport, **kwargs)
    return InstagramMetadataFetcher(http).fetch(SourceSpec(kind="url", url=url)), calls


@pytest.mark.parametrize("kind", ["p", "reel", "reels"])
def test_exact_canonical_urls(kind):
    assert canonical_instagram_url(f"https://instagram.com/{kind}/Ab_c-123/?igsh=secret#x") == (
        f"https://www.instagram.com/{'p' if kind == 'p' else 'reel'}/Ab_c-123/"
    )


@pytest.mark.parametrize("url", [
    "http://instagram.com/p/abc/", "https://instagram.com.evil.test/p/abc/",
    "https://instagram.com@evil.test/p/abc/", "https://user@instagram.com/p/abc/",
    "https://instagram.com:444/p/abc/", "https://instagram.com/explore/",
    "https://instagram.com/profile/", "https://instagram.com/accounts/login/",
    "https://instagram.com/p/abc/extra", "https://instagram.com/p/abc/../def/",
    "https://instagram.com/p/a%62c/", "https://instagram.com/P/abc/",
])
def test_invalid_url_rejected_before_normalization(url):
    with pytest.raises(UnsupportedSourceError):
        canonical_instagram_url(url)
    with pytest.raises(ContentValidationError):
        normalize_source_url(url)


@pytest.mark.parametrize("fixture,kind", [("post", "p"), ("reel", "reel")])
def test_metadata_only_snapshot(fixture, kind):
    raw, _ = fetch(Path(f"tests/fixtures/instagram/{fixture}.html").read_text(),
                   url=f"https://instagram.com/{kind}/abc/")
    draft = extract_snapshot(raw, "instagram")
    assert draft.raw_meta["source_scope"] == "instagram_metadata"
    assert draft.raw_meta["instagram_metadata"]["basis"] == "title_caption"
    assert "BOILERPLATE" not in draft.text and "never execute" not in draft.text
    if fixture == "post":
        assert '& 커피' in draft.text and '"기록"' in draft.text
        assert "@coffee" in draft.text and "#성수" in draft.text
        assert draft.author_guess == "coffee"


def test_title_only_and_caption_only():
    raw, _ = fetch('<title>제주 여행 바다</title>')
    assert raw.meta["instagram_metadata"]["basis"] == "title_only"
    raw, _ = fetch('<meta name="description" content="#제주 #여행 #바다">')
    assert raw.meta["instagram_metadata"]["basis"] == "caption_only"


@pytest.mark.parametrize("html", [
    '<title>Instagram</title><body>Log in</body>',
    '<title>Login • Instagram</title><meta name="description" content="Join Instagram">',
    '<title>Page not found • Instagram</title>',
    '<title>Private account • Instagram</title>',
    '<meta property="og:title" content="Instagram"><script>{"caption":"secret"}</script>',
    '<body>ordinary body caption #제주 #바다 #여행</body>',
])
def test_shell_and_missing_fail_permanently(html):
    with pytest.raises(UnsupportedSourceError) as exc:
        fetch(html)
    assert URL not in str(exc.value) and "secret" not in str(exc.value)


@pytest.mark.parametrize("target", [
    "https://instagram.com.evil.test/p/abc/", "http://instagram.com/p/abc/",
    "http://127.0.0.1/", "https://instagram.com/accounts/login/",
    "https://user@instagram.com/p/abc/", "https://instagram.com/p/OTHER/",
])
def test_redirect_policy_blocks_before_second_request(target):
    with pytest.raises(UnsupportedSourceError):
        fetch(responses=[HttpResponse(302, {"location": target}, b"")])


def test_ssrf_and_size_limits_reused():
    with pytest.raises(UnsupportedSourceError):
        fetch(address="127.0.0.1")
    with pytest.raises(UnsupportedSourceError):
        fetch(max_bytes=10)

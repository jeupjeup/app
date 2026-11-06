from __future__ import annotations

from datetime import UTC, datetime

import pytest

from jupjup.domain.errors import FetchError, UnsupportedSourceError
from jupjup.ingest.fetch import HttpResponse, HttpSourceFetcher, SourceSpec


def test_http_fetcher_blocks_private_resolution_before_transport() -> None:
    called = False

    def transport(_url: str, _timeout: float) -> HttpResponse:
        nonlocal called
        called = True
        raise AssertionError

    fetcher = HttpSourceFetcher(resolver=lambda _host: ["127.0.0.1"], transport=transport)
    with pytest.raises(UnsupportedSourceError):
        fetcher.fetch(SourceSpec(kind="url", url="https://example.com/a"))
    assert called is False


def test_http_fetcher_rechecks_redirect_and_rejects_oversize() -> None:
    responses = {
        "https://example.com/a": HttpResponse(302, {"location": "https://internal.test/secret"}, b""),
    }
    fetcher = HttpSourceFetcher(
        resolver=lambda host: ["93.184.216.34"] if host == "example.com" else ["10.0.0.1"],
        transport=lambda url, _timeout: responses[url],
    )
    with pytest.raises(UnsupportedSourceError):
        fetcher.fetch(SourceSpec(kind="url", url="https://example.com/a"))

    too_large = HttpSourceFetcher(
        resolver=lambda _host: ["93.184.216.34"],
        transport=lambda _url, _timeout: HttpResponse(200, {"content-type": "text/plain"}, b"x" * 17),
        max_bytes=16,
    )
    with pytest.raises(UnsupportedSourceError):
        too_large.fetch(SourceSpec(kind="url", url="https://example.com/a"))


def test_http_fetcher_classifies_server_error_retryable() -> None:
    fetcher = HttpSourceFetcher(
        resolver=lambda _host: ["93.184.216.34"],
        transport=lambda _url, _timeout: HttpResponse(503, {"content-type": "text/plain"}, b"later"),
        clock=lambda: datetime(2026, 1, 1, tzinfo=UTC),
    )
    with pytest.raises(FetchError) as error:
        fetcher.fetch(SourceSpec(kind="url", url="https://example.com/a"))
    assert error.value.details["status"] == 503
    assert error.value.details["retryable"] is True


def test_compressed_body_is_bounded_before_materializing() -> None:
    import gzip

    compressed = gzip.compress(b"a" * 100_000)
    fetcher = HttpSourceFetcher(
        resolver=lambda _: ["93.184.216.34"],
        transport=lambda *_: HttpResponse(200, {"content-type": "text/plain", "content-encoding": "gzip"}, compressed),
        max_bytes=1000,
    )
    with pytest.raises(UnsupportedSourceError):
        fetcher.fetch(SourceSpec(kind="url", url="https://example.com"))


def test_default_transport_pins_validated_dns_address(monkeypatch: pytest.MonkeyPatch) -> None:
    import jupjup.ingest.fetch as fetch

    calls = []

    def pinned(url, timeout, addresses, max_bytes):
        calls.append((url, addresses, max_bytes))
        return HttpResponse(200, {"content-type": "text/plain"}, b"public")

    monkeypatch.setattr(fetch, "_transport", pinned)
    fetcher = HttpSourceFetcher(resolver=lambda _: ["93.184.216.34"])
    assert fetcher.fetch(SourceSpec(kind="url", url="https://example.com")).body == b"public"
    assert calls == [("https://example.com", ["93.184.216.34"], 10 * 1024 * 1024)]


def test_real_transport_reads_http10_close_body_and_bounded_response() -> None:
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from jupjup.ingest.fetch import _transport

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"test response")

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://example.test:{server.server_port}/"
        assert _transport(url, 2, ["127.0.0.1"], 100).body == b"test response"
        with pytest.raises(UnsupportedSourceError):
            _transport(url, 2, ["127.0.0.1"], 5)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_dns_resolution_obeys_total_deadline() -> None:
    import time
    def slow_resolver(_host):
        time.sleep(0.1)
        return ["93.184.216.34"]
    fetcher = HttpSourceFetcher(resolver=slow_resolver, timeout_s=0.01,
                                transport=lambda *_: HttpResponse(200, {"content-type": "text/plain"}, b"text"))
    start = time.monotonic()
    with pytest.raises(FetchError):
        fetcher.fetch(SourceSpec(kind="url", url="https://example.com"))
    assert time.monotonic() - start < 0.08

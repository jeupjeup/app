"""Network-free source fetchers for inline text and repository fixtures."""

from __future__ import annotations

import gzip
import http.client
import io
import ipaddress
import socket
import ssl
import threading
import time
from collections.abc import Callable, Sequence
from concurrent.futures import Future
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, ClassVar, Literal, Protocol, runtime_checkable
from urllib.parse import urljoin, urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

from jupjup.domain.errors import FetchError, UnsupportedSourceError

SourceKind = Literal["text", "url", "image", "youtube"]
Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(UTC)


class SourceSpec(BaseModel):
    """Description of an ingest source before it has been fetched."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: SourceKind
    url: str | None = None
    text: str | None = None
    fixture: str | None = None
    ocr_text: str | None = None
    image_path: str | None = None
    youtube_metadata_only: bool = False


class RawSource(BaseModel):
    """Fetched bytes/text plus transport metadata consumed by I2 extraction."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: SourceKind
    body: bytes | str
    mime: str
    fetched_at: datetime
    final_url: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)

    @field_validator("fetched_at")
    @classmethod
    def _aware_datetime(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
            raise ValueError("fetched_at은 timezone-aware여야 합니다")
        return value


@runtime_checkable
class SourceFetcher(Protocol):
    def supports(self, spec: SourceSpec) -> bool: ...

    def fetch(self, spec: SourceSpec) -> RawSource: ...


class InlineTextFetcher:
    """Fetch direct text and OCR text without touching the filesystem or network."""

    def __init__(self, clock: Clock = _utc_now) -> None:
        self._clock = clock

    def supports(self, spec: SourceSpec) -> bool:
        return (spec.kind == "text" and spec.text is not None) or (spec.kind == "image" and spec.ocr_text is not None)

    def fetch(self, spec: SourceSpec) -> RawSource:
        if not self.supports(spec):
            raise UnsupportedSourceError(
                "직접 텍스트 또는 OCR 텍스트가 필요합니다",
                {"kind": spec.kind},
            )
        body = spec.text if spec.kind == "text" else spec.ocr_text
        assert body is not None
        return RawSource(
            kind=spec.kind,
            body=body,
            mime="text/plain; charset=utf-8",
            fetched_at=self._clock(),
            meta={"source": "inline"},
        )


class _FixtureFetcher:
    _extensions: ClassVar[frozenset[str]]
    _mime_by_extension: ClassVar[dict[str, str]]

    def __init__(self, fixtures_root: Path, clock: Clock = _utc_now) -> None:
        # 루트 설정 오류는 다시 해도 같으므로 영구 실패(UnsupportedSourceError)다.
        try:
            root = fixtures_root.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise UnsupportedSourceError("fixture 루트를 찾을 수 없습니다", {"root": str(fixtures_root)}) from exc
        if not root.is_dir():
            raise UnsupportedSourceError("fixture 루트가 디렉터리가 아닙니다", {"root": str(fixtures_root)})
        self._root = root
        self._clock = clock

    def _supports_fixture(self, spec: SourceSpec) -> bool:
        return spec.fixture is not None and Path(spec.fixture).suffix.lower() in self._extensions

    def _resolve_fixture(self, fixture: str) -> Path:
        """Resolve a fixture inside the root.

        경로 검증 실패, 심볼릭 링크, 없는 파일, 디렉터리 지정은 재시도해도 결과가 같으므로
        `UnsupportedSourceError`(영구)다. 일시적인 I/O 오류만 `FetchError`(재시도 가능)로 남긴다.
        """

        portable = fixture.replace("\\", "/")
        posix = PurePosixPath(portable)
        if (
            not fixture
            or "\\" in fixture
            or posix.is_absolute()
            or PureWindowsPath(fixture).is_absolute()
            or ".." in posix.parts
            or posix == PurePosixPath(".")
        ):
            raise UnsupportedSourceError("안전하지 않은 fixture 경로입니다", {"fixture": fixture})

        lexical = self._root.joinpath(*posix.parts)
        cursor = self._root
        try:
            for part in posix.parts:
                cursor = cursor / part
                if cursor.is_symlink():
                    raise UnsupportedSourceError("fixture 심볼릭 링크는 허용하지 않습니다", {"fixture": fixture})
            resolved = lexical.resolve(strict=True)
            resolved.relative_to(self._root)
        except UnsupportedSourceError:
            raise
        except (FileNotFoundError, NotADirectoryError, RuntimeError, ValueError) as exc:
            raise UnsupportedSourceError("fixture 파일을 찾을 수 없습니다", {"fixture": fixture}) from exc
        except OSError as exc:
            raise FetchError("fixture 경로를 확인하지 못했습니다", {"fixture": fixture}) from exc
        if not resolved.is_file():
            raise UnsupportedSourceError("fixture가 일반 파일이 아닙니다", {"fixture": fixture})
        return resolved

    def _fetch_fixture(self, spec: SourceSpec, *, text: bool) -> RawSource:
        assert spec.fixture is not None
        path = self._resolve_fixture(spec.fixture)
        extension = path.suffix.lower()
        if extension not in self._extensions:
            raise UnsupportedSourceError(
                "지원하지 않는 fixture 형식입니다",
                {"fixture": spec.fixture, "extension": extension},
            )
        try:
            body: bytes | str
            body = path.read_text(encoding="utf-8") if text else path.read_bytes()
        except UnicodeError as exc:
            raise UnsupportedSourceError("fixture가 UTF-8 텍스트가 아닙니다", {"fixture": spec.fixture}) from exc
        except FileNotFoundError as exc:
            raise UnsupportedSourceError("fixture 파일을 찾을 수 없습니다", {"fixture": spec.fixture}) from exc
        except OSError as exc:
            raise FetchError("fixture를 읽지 못했습니다", {"fixture": spec.fixture}) from exc
        return RawSource(
            kind=spec.kind,
            body=body,
            mime=self._mime_by_extension[extension],
            fetched_at=self._clock(),
            final_url=spec.url,
            meta={"source": "fixture", "fixture": spec.fixture},
        )


class FixtureHtmlFetcher(_FixtureFetcher):
    _extensions: ClassVar[frozenset[str]] = frozenset({".htm", ".html"})
    _mime_by_extension: ClassVar[dict[str, str]] = {
        # 파일 자체에는 전송 charset이 없다. 인코딩은 추출 단계에서 BOM, <meta charset>, UTF-8 순으로 정한다.
        ".htm": "text/html",
        ".html": "text/html",
    }

    def supports(self, spec: SourceSpec) -> bool:
        return spec.kind == "url" and self._supports_fixture(spec)

    def fetch(self, spec: SourceSpec) -> RawSource:
        if not self.supports(spec):
            raise UnsupportedSourceError("HTML fixture URL이 필요합니다", {"kind": spec.kind})
        return self._fetch_fixture(spec, text=False)


class FixtureTranscriptFetcher(_FixtureFetcher):
    _extensions: ClassVar[frozenset[str]] = frozenset({".json", ".srt", ".vtt"})
    _mime_by_extension: ClassVar[dict[str, str]] = {
        ".json": "application/json",
        ".srt": "application/x-subrip; charset=utf-8",
        ".vtt": "text/vtt; charset=utf-8",
    }

    def supports(self, spec: SourceSpec) -> bool:
        return spec.kind in ("url", "youtube") and self._supports_fixture(spec)

    def fetch(self, spec: SourceSpec) -> RawSource:
        if not self.supports(spec):
            raise UnsupportedSourceError("VTT, SRT 또는 JSON 자막 fixture가 필요합니다", {"kind": spec.kind})
        return self._fetch_fixture(spec, text=True)


class FetcherRouter:
    """Select the first supporting fetcher in a stable, caller-defined order."""

    def __init__(self, fetchers: Sequence[SourceFetcher]) -> None:
        self._fetchers = tuple(fetchers)

    def fetch(self, spec: SourceSpec) -> RawSource:
        for fetcher in self._fetchers:
            if fetcher.supports(spec):
                return fetcher.fetch(spec)
        raise UnsupportedSourceError(
            "이 원본을 처리할 fetcher가 없습니다",
            {"kind": spec.kind, "fixture": spec.fixture},
        )


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: dict[str, str]
    body: bytes


Resolver = Callable[[str], list[str]]
HttpTransport = Callable[[str, float], HttpResponse]


_DNS_SLOTS = threading.BoundedSemaphore(4)


def _resolve_with_timeout(resolver: Resolver, host: str, timeout: float) -> list[str]:
    deadline = time.monotonic() + timeout
    if not _DNS_SLOTS.acquire(timeout=max(0.0, timeout)):
        raise FetchError("DNS 요청 시간이 초과되었습니다", {"retryable": True})
    result: Future[list[str]] = Future()

    def resolve() -> None:
        try:
            result.set_result(resolver(host))
        except Exception as exc:
            result.set_exception(exc)
        finally:
            _DNS_SLOTS.release()

    threading.Thread(target=resolve, daemon=True, name="source-dns").start()
    try:
        return result.result(timeout=max(0.0, deadline - time.monotonic()))
    except TimeoutError as exc:
        raise FetchError("DNS 요청 시간이 초과되었습니다", {"retryable": True}) from exc


def _resolve(host: str) -> list[str]:
    try:
        return sorted({str(item[4][0]) for item in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)})
    except OSError as exc:
        raise FetchError("URL host를 확인하지 못했습니다", {"retryable": True}) from exc


def _transport(url: str, timeout: float, addresses: list[str], max_bytes: int) -> HttpResponse:
    """Connect to a previously validated IP, preserving TLS SNI and Host; no proxies or DNS retry."""
    parsed = urlsplit(url)
    assert parsed.hostname is not None
    host = parsed.hostname
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    deadline = time.monotonic() + timeout
    connection = http.client.HTTPConnection(host, port, timeout=min(3.0, timeout))
    watchdog: threading.Timer | None = None
    try:
        connection.sock = socket.create_connection((addresses[0], port), timeout=min(3.0, timeout))
        if parsed.scheme == "https":
            connection.sock = ssl.create_default_context().wrap_socket(connection.sock, server_hostname=host)
        connection.request(
            "GET",
            (parsed.path or "/") + ("?" + parsed.query if parsed.query else ""),
            headers={"Accept-Encoding": "gzip", "User-Agent": "jupjup/1"},
        )
        active_socket = connection.sock

        def expire() -> None:
            with suppress(OSError):
                active_socket.shutdown(socket.SHUT_RDWR)

        watchdog = threading.Timer(max(0.0, deadline - time.monotonic()), expire)
        watchdog.daemon = True
        watchdog.start()
        response = connection.getresponse()
        headers = {k.lower(): v for k, v in response.getheaders()}
        chunks: list[bytes] = []
        size = 0
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError
            active_socket.settimeout(remaining)
            chunk = response.read1(min(65536, max_bytes + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > max_bytes:
                raise UnsupportedSourceError("원본 크기가 허용 한도를 넘었습니다")
        if time.monotonic() > deadline:
            raise TimeoutError
        return HttpResponse(response.status, headers, b"".join(chunks))
    except (TimeoutError, OSError, http.client.HTTPException) as exc:
        raise FetchError("URL을 가져오지 못했습니다", {"retryable": True}) from exc
    finally:
        if watchdog is not None:
            watchdog.cancel()
        connection.close()


class HttpSourceFetcher:
    """Small public-HTTP fetcher with per-hop SSRF and decoded-size checks."""

    _MIMES = frozenset({"text/html", "text/plain", "text/vtt", "application/x-subrip", "application/json"})

    def __init__(
        self,
        *,
        resolver: Resolver = _resolve,
        transport: HttpTransport | None = None,
        clock: Clock = _utc_now,
        timeout_s: float = 10.0,
        max_bytes: int = 10 * 1024 * 1024,
        max_redirects: int = 3,
    ) -> None:
        self._resolver = resolver
        self._transport = transport
        self._clock = clock
        self._timeout_s = timeout_s
        self._max_bytes = max_bytes
        self._max_redirects = max_redirects

    def supports(self, spec: SourceSpec) -> bool:
        return spec.kind == "url" and spec.url is not None and spec.fixture is None

    @staticmethod
    def _validate_address(value: str) -> None:
        try:
            address = ipaddress.ip_address(value)
        except ValueError as exc:
            raise UnsupportedSourceError("DNS 응답 주소가 올바르지 않습니다") from exc
        if not address.is_global:
            raise UnsupportedSourceError("공개 네트워크 주소만 가져올 수 있습니다", {"kind": "blocked_address"})

    def _validate_url(self, url: str, timeout: float) -> list[str]:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise UnsupportedSourceError("http/https URL만 가져올 수 있습니다")
        if parsed.username is not None or parsed.password is not None:
            raise UnsupportedSourceError("인증 정보가 든 URL은 가져올 수 없습니다")
        addresses = _resolve_with_timeout(self._resolver, parsed.hostname, timeout)
        if not addresses:
            raise FetchError("URL host를 확인하지 못했습니다", {"retryable": True})
        for address in addresses:
            self._validate_address(address)
        return addresses

    def fetch(
        self, spec: SourceSpec, *, url_policy: Callable[[str], None] | None = None, deadline: float | None = None
    ) -> RawSource:
        if not self.supports(spec):
            raise UnsupportedSourceError("공개 http/https URL이 필요합니다", {"kind": spec.kind})
        assert spec.url is not None
        url = spec.url
        response: HttpResponse | None = None
        deadline = deadline or (time.monotonic() + self._timeout_s)
        for hop in range(self._max_redirects + 1):
            if url_policy is not None:
                url_policy(url)
            addresses = self._validate_url(url, deadline - time.monotonic())
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise FetchError("URL 요청 시간이 초과되었습니다", {"retryable": True})
            response = (
                self._transport(url, remaining)
                if self._transport is not None
                else _transport(url, remaining, addresses, self._max_bytes)
            )
            if response.status in {301, 302, 303, 307, 308}:
                location = response.headers.get("location")
                if not location or hop >= self._max_redirects:
                    raise UnsupportedSourceError("URL redirect가 너무 많거나 올바르지 않습니다")
                url = urljoin(url, location)
                continue
            break
        assert response is not None
        if response.status == 429 or response.status >= 500:
            raise FetchError(
                "원본 서버가 일시적으로 응답하지 않습니다",
                {"status": response.status, "retryable": True},
            )
        if response.status >= 400:
            raise UnsupportedSourceError("원본 URL에 접근할 수 없습니다", {"status": response.status})
        mime = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if mime not in self._MIMES:
            raise UnsupportedSourceError("지원하지 않는 원본 MIME입니다", {"kind": mime[:120]})
        body = response.body
        if len(body) > self._max_bytes:
            raise UnsupportedSourceError("원본 크기가 허용 한도를 넘었습니다")
        if response.headers.get("content-encoding", "").lower() == "gzip":
            try:
                with gzip.GzipFile(fileobj=io.BytesIO(body)) as compressed:
                    body = compressed.read(self._max_bytes + 1)
            except (OSError, EOFError) as exc:
                raise UnsupportedSourceError("압축 원본을 해제할 수 없습니다") from exc
        if len(body) > self._max_bytes:
            raise UnsupportedSourceError("원본 크기가 허용 한도를 넘었습니다")
        return RawSource(
            kind="url",
            body=body,
            mime=response.headers.get("content-type", mime),
            fetched_at=self._clock(),
            final_url=url,
            meta={"source": "http", "status": response.status},
        )

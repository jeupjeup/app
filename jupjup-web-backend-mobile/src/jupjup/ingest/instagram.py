"""Public Instagram metadata only; no authenticated or media extraction."""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field

from jupjup.domain.errors import UnsupportedSourceError
from jupjup.ingest.extract import _decode_body, tidy_snapshot_text
from jupjup.ingest.fetch import HttpSourceFetcher, RawSource, SourceSpec

_HOSTS = {"instagram.com", "www.instagram.com"}
_PATH = re.compile(r"/(p|reel|reels)/([A-Za-z0-9_-]+)/?")


def instagram_candidate(url: str) -> bool:
    """Claim Instagram-looking authorities so invalid URLs cannot fall through to generic HTTP."""
    try:
        return "instagram.com" in urlsplit(url).netloc.casefold()
    except ValueError:
        return "instagram.com" in url.casefold()


def canonical_instagram_url(url: str) -> str:
    try:
        parsed = urlsplit(url)
        match = _PATH.fullmatch(parsed.path)
        valid = (
            parsed.scheme == "https" and parsed.hostname in _HOSTS
            and parsed.username is None and parsed.password is None
            and parsed.port in (None, 443) and match is not None
            and not any(ord(ch) <= 32 or ord(ch) == 127 for ch in url)
        )
    except ValueError:
        valid, match = False, None
    if not valid or match is None:
        raise UnsupportedSourceError("공개 Instagram 게시물 또는 릴스 HTTPS URL이 필요합니다")
    kind = "p" if match[1] == "p" else "reel"
    return f"https://www.instagram.com/{kind}/{match[2]}/"


class InstagramMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    title: str = Field(max_length=1000)
    caption: str = Field(max_length=20_000)
    author: str | None = Field(default=None, max_length=1000)
    basis: Literal["title_caption", "title_only", "caption_only"]
    title_source: str | None = None
    caption_source: str | None = None
    truncated: bool = False

    def text(self) -> str:
        # No labels in the snapshot: every lexical token must originate in metadata.
        return "\n\n".join(value for value in (self.title, self.caption) if value)


class _MetadataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.values: dict[str, str] = {}
        self.in_title = False
        self.title: list[str] = []
        self.ignored = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "template", "noscript"}:
            self.ignored += 1
        if self.ignored:
            return
        if tag == "title":
            self.in_title = True
        if tag == "meta":
            attributes = dict(attrs)
            key = (attributes.get("property") or attributes.get("name") or "").casefold()
            content = attributes.get("content")
            if key in {"og:title", "og:description", "description", "author"} and content:
                self.values.setdefault(key, tidy_snapshot_text(content))

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "template", "noscript"} and self.ignored:
            self.ignored -= 1
        if tag == "title":
            self.in_title = False

    def handle_data(self, data: str) -> None:
        if self.in_title and not self.ignored:
            self.title.append(data)


_SHELL = re.compile(
    r"log\s*in|sign\s*up|join instagram|private account|page not found|"
    r"content (?:isn't|is not) available|sorry,? this page|로그인|비공개 계정|페이지를 사용할 수 없|"
    r"게시물을 사용할 수 없|콘텐츠를 이용할 수 없", re.I,
)


def parse_instagram_metadata(raw: RawSource) -> InstagramMetadata:
    parser = _MetadataParser()
    parser.feed(_decode_body(raw, is_html=True))
    parser.close()
    title_source = "og:title" if parser.values.get("og:title") else "title"
    title = parser.values.get("og:title") or tidy_snapshot_text("".join(parser.title))
    caption_source = "og:description" if parser.values.get("og:description") else "description"
    caption = parser.values.get("og:description") or parser.values.get("description", "")
    if _SHELL.search(title) or _SHELL.search(caption):
        raise UnsupportedSourceError("Instagram 공개 metadata에 접근할 수 없습니다", {"reason": "unavailable_metadata"})
    if title.casefold().strip(" •|-:") == "instagram":
        title = ""
    if not title and not caption:
        raise UnsupportedSourceError("Instagram 제목과 caption이 없습니다", {"reason": "missing_metadata"})
    return InstagramMetadata(
        title=title[:1000], caption=caption[:20_000], author=(parser.values.get("author") or "")[:1000] or None,
        basis="title_caption" if title and caption else "title_only" if title else "caption_only",
        title_source=title_source if title else None, caption_source=caption_source if caption else None,
        truncated=len(title) > 1000 or len(caption) > 20_000,
    )


class InstagramMetadataFetcher:
    def __init__(self, http: HttpSourceFetcher | None = None) -> None:
        self.http = http or HttpSourceFetcher(max_bytes=5_000_000)

    def supports(self, spec: SourceSpec) -> bool:
        return spec.kind == "url" and spec.url is not None and instagram_candidate(spec.url) and spec.fixture is None

    def fetch(self, spec: SourceSpec) -> RawSource:
        canonical = canonical_instagram_url(spec.url or "")

        def policy(url: str) -> None:
            if canonical_instagram_url(url) != canonical:
                raise UnsupportedSourceError("Instagram redirect 대상이 원본 게시물과 다릅니다")

        raw = self.http.fetch(spec.model_copy(update={"url": canonical}), url_policy=policy)
        if raw.mime.partition(";")[0].strip().casefold() != "text/html":
            raise UnsupportedSourceError("Instagram 공개 HTML metadata가 필요합니다")
        metadata = parse_instagram_metadata(raw)
        return raw.model_copy(update={
            "body": metadata.text(), "mime": "text/plain; charset=utf-8", "final_url": canonical,
            "meta": {"source": "instagram_metadata", "source_scope": "instagram_metadata",
                     "instagram_metadata": metadata.model_dump(mode="json"),
                     "title": metadata.title or None, "author": metadata.author},
        })

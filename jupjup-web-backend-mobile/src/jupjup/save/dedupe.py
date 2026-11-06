"""Deterministic source normalization and fingerprint helpers."""

from __future__ import annotations

import hashlib
import posixpath
import re
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from jupjup.domain.errors import ContentValidationError

URL_NORMALIZATION_VERSION = "url-normalization-v1"
CONTENT_HASH_VERSION = "content-hash-v1"
_TRACKING_KEYS = frozenset({"fbclid", "gclid", "igshid", "mc_cid", "mc_eid"})
_UNRESERVED = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")


def _decode_unreserved(value: str) -> str:
    def replace(match: re.Match[str]) -> str:
        character = chr(int(match.group(1), 16))
        return character if character in _UNRESERVED else match.group(0).upper()

    return re.sub(r"%([0-9a-fA-F]{2})", replace, value)


def normalize_source_url(value: str) -> str:
    """Return the v1 canonical URL without performing I/O."""
    if len(value) > 2048:
        raise ContentValidationError("URL은 최대 2,048자입니다", {"field": "source.url"})
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ContentValidationError("URL 형식이 올바르지 않습니다", {"field": "source.url"}) from exc
    from jupjup.domain.errors import UnsupportedSourceError
    from jupjup.ingest.instagram import canonical_instagram_url, instagram_candidate

    if instagram_candidate(value):
        try:
            return canonical_instagram_url(value)
        except UnsupportedSourceError as exc:
            raise ContentValidationError(
                "공개 Instagram 게시물/릴스 HTTPS URL이 필요합니다", {"field": "source.url"}
            ) from exc
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"} or not parsed.hostname:
        raise ContentValidationError("URL은 http/https만 허용합니다", {"field": "source.url"})
    if parsed.username is not None or parsed.password is not None:
        raise ContentValidationError("인증 정보가 포함된 URL은 허용하지 않습니다", {"field": "source.url"})
    try:
        host = parsed.hostname.encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise ContentValidationError("URL host 형식이 올바르지 않습니다", {"field": "source.url"}) from exc
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    netloc = host
    if port is not None and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        netloc = f"{host}:{port}"
    path = _decode_unreserved(parsed.path or "/")
    trailing = path.endswith("/")
    path = posixpath.normpath(path)
    if not path.startswith("/"):
        path = "/" + path
    if trailing and path != "/":
        path += "/"
    # Keep reserved delimiters while stabilizing non-ASCII and stray percent encodings.
    path = quote(path, safe="/%:@!$&'()*+,;=-._~")
    query = [
        (key, item)
        for key, item in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in _TRACKING_KEYS
    ]
    query.sort()

    youtube_hosts = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "www.youtu.be"}
    if host.strip("[]") in youtube_hosts:
        video_id: str | None = None
        if host.strip("[]").endswith("youtu.be"):
            video_id = path.strip("/").split("/", 1)[0] or None
        elif path == "/watch":
            video_id = next((item for key, item in query if key == "v"), None)
        if video_id:
            netloc, path, query = "www.youtube.com", "/watch", [("v", video_id)]

    return urlunsplit((scheme, netloc, path, urlencode(query, doseq=True), ""))


def fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()

"""Strict contract field validation and local-only HTTP URL normalization."""

import ipaddress
import re
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

from jupjup.app_api.errors import ContractError

TYPES = ("영상", "이미지", "텍스트", "기타")
COLLECTIONS = ("장소", "여행", "음식", "의류", "제품", "회사")
PASSWORD = re.compile(r"^(?=.*[A-Za-z])(?=.*[0-9])(?=.*[!@#$%^&*<>])[A-Za-z0-9!@#$%^&*<>]{8,20}$")


def invalid() -> None:
    raise ContractError(400, "VALIDATION_ERROR")


def string(body: dict[str, Any], key: str, maximum: int, minimum: int = 1, *, trim: bool = False) -> str:
    value = body.get(key)
    if not isinstance(value, str):
        invalid()
    assert isinstance(value, str)
    value = value.strip() if trim else value
    if not minimum <= len(value) <= maximum or any(0xD800 <= ord(c) <= 0xDFFF for c in value):
        invalid()
    return value


def password(body: dict[str, Any], key: str) -> str:
    value = string(body, key, 128, trim=False)
    if not PASSWORD.fullmatch(value):
        raise ContractError(400, "INVALID_PASSWORD")
    return value


def email(body: dict[str, Any]) -> str:
    value = string(body, "email", 254).lower()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
        invalid()
    return value


def normalize_url(body: dict[str, Any]) -> tuple[str, str]:
    value = string(body, "url", 4096)
    try:
        if any(ord(c) < 33 or ord(c) == 127 for c in value) or "\\" in value:
            raise ValueError
        if re.search(r"%(?![0-9a-fA-F]{2})", value):
            raise ValueError
        parts = urlsplit(value)
        if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
            raise ValueError
        if parts.username is not None or parts.password is not None or "@" in parts.netloc:
            raise ValueError
        host = parts.hostname.encode("idna").decode("ascii").lower()
        if ":" in host:
            host = f"[{ipaddress.IPv6Address(host).compressed}]"
        elif not re.fullmatch(r"[a-z0-9._-]+", host) or "%" in host:
            raise ValueError
        port = parts.port
        authority = host
        if port is not None and (parts.scheme.lower(), port) not in (("http", 80), ("https", 443)):
            authority += f":{port}"
        # WHATWG-style removal of dot segments without collapsing repeated slashes.
        segments: list[str] = []
        path = parts.path or "/"
        for segment in path.split("/"):
            dot = re.sub("%2e", ".", segment, flags=re.I)
            if dot == "..":
                if len(segments) > 1:
                    segments.pop()
            elif dot != ".":
                segments.append(segment)
        normalized_path = "/".join(segments) or "/"
        if re.sub("%2e", ".", path.rsplit("/", 1)[-1], flags=re.I) in (".", ".."):
            normalized_path = normalized_path.rstrip("/") + "/"
        path = quote(normalized_path, safe="/%:@!$&'()*+,;=-._~")
        query = quote(parts.query, safe="%/?@:!$&'()*+,;=-._~")
        return urlunsplit((parts.scheme.lower(), authority, path, query, "")), host
    except (ValueError, UnicodeError):
        raise ContractError(400, "VALIDATION_ERROR") from None

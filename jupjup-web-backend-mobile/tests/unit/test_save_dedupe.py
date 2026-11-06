from __future__ import annotations

import pytest

from jupjup.domain.errors import ContentValidationError
from jupjup.save.dedupe import normalize_source_url


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("HTTPS://ExAmPle.COM:443/a/../b?z=2&utm_source=x&a=1#frag", "https://example.com/b?a=1&z=2"),
        ("https://youtu.be/abc123?utm_medium=s", "https://www.youtube.com/watch?v=abc123"),
        ("https://youtube.com/watch?feature=share&v=abc123", "https://www.youtube.com/watch?v=abc123"),
        ("https://instagram.com/reels/XYZ?igshid=secret", "https://www.instagram.com/reel/XYZ/"),
        ("https://예시.한국/%7Euser", "https://xn--vv4b11d.xn--3e0b707e/~user"),
    ],
)
def test_url_normalization_v1(value: str, expected: str) -> None:
    assert normalize_source_url(value) == expected


def test_url_normalizer_rejects_credentials() -> None:
    with pytest.raises(ContentValidationError):
        normalize_source_url("https://user:password@example.com/private")

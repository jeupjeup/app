"""외부 자산 없이 동작하는 데모 페이지 자산."""

from __future__ import annotations

from importlib.resources import files

HTML_PAGE = files("jupjup.demo").joinpath("page.html").read_text(encoding="utf-8")

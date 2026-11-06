"""의도 분류 `IntentClassifier` (설계서 5.2절 1d)."""

from __future__ import annotations

import re
from typing import Literal

from jupjup.text.lexicon import Lexicon

Intent = Literal["lookup", "browse"]

_WORD = re.compile(r"[^\s,.!?~]+")
# '~들' 복수 표지로 보지 않을 단어
_DEUL_EXCEPTIONS = frozenset({"만들", "만들기", "들들", "고들", "어들"})
_DEUL = re.compile(r"^[가-힣]{2,}들(?:을|이|은|만|도)?$")


class IntentClassifier:
    def __init__(self, lexicon: Lexicon) -> None:
        self.browse_markers = lexicon.browse_markers
        self.deictic_markers = lexicon.deictic_markers

    def classify(self, text: str) -> Intent:
        words = _WORD.findall(text)
        for w in words:
            if w in self.browse_markers:
                return "browse"
            if _DEUL.match(w) and w[:-1] not in _DEUL_EXCEPTIONS and not w.startswith("만들"):
                return "browse"
        return "lookup"

    def has_deictic(self, text: str) -> bool:
        return any(w in self.deictic_markers for w in _WORD.findall(text))

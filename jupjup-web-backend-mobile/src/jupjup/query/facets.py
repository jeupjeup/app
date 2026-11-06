"""플랫폼과 콘텐츠 유형 추출 `FacetExtractor` (설계서 5.2절 1c).

- 가장 긴 별칭부터 찾는다. 별칭은 어절 시작에서만 매칭한다.
- 3자 이상 한글 별칭은 자모 편집 거리 1까지 허용, 2자 이하는 정확 일치만.
- 영문 별칭은 단어 경계가 있어야 한다 (`ig`가 단어 안에 섞이지 않도록).
- 문맥 규칙: 뒤에 조사(에서, 으로, 로 …)나 동사형(본, 받은 …)이 붙으면 hard, 아니면 soft.
  보강 규칙: 질의의 마지막 어절이거나, 다음 어절이 유형 별칭이면 hard로 본다.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

from jupjup.query.settings import QuerySettings
from jupjup.query.temporal import Span
from jupjup.text.lexicon import Lexicon
from jupjup.text.normalize import jamo_distance

Strength = Literal["hard", "soft"]

# 같은 어절 안에서 별칭 뒤에 붙을 수 있는 것
_HARD_PARTICLES = (
    "에서",
    "에서도",
    "에서만",
    "에서의",
    "에서는",
    "으로",
    "로",
    "으로도",
    "로도",
    "으로만",
    "로만",
    "에",
    "에도",
    "에다",
    "에다가",
    "에서본",
    "에서봤던",
    "통해서",
    "통해",
)
_NEUTRAL_PARTICLES = ("의", "이", "가", "은", "는", "을", "를", "도", "만", "랑", "이랑", "하고", "들", "엔", "에는")
_VERBAL_SUFFIXES = (
    "해둔",
    "해놓은",
    "해놨던",
    "해뒀던",
    "했던",
    "해서",
    "하던",
    "한",
    "해",
    "해둔거",
    "한거",
    "본",
    "봤던",
)
_ALLOWED_SUFFIXES = frozenset(_HARD_PARTICLES + _NEUTRAL_PARTICLES + _VERBAL_SUFFIXES)
# 다음 어절이 이것이면 플랫폼을 출처로 본다
_VERB_NEXT = frozenset(
    {
        "본",
        "봤던",
        "보던",
        "봤는데",
        "봤었던",
        "받은",
        "받았던",
        "올라온",
        "올라왔던",
        "저장한",
        "저장해둔",
        "저장했던",
        "공유한",
        "공유받은",
        "퍼온",
        "캡처한",
        "캡쳐한",
        "나온",
        "보낸",
        "보내준",
        "온",
        "링크",
    }
)
# 관형형 동사 어절 (예: 찍은, 공유한, 다운받은, 저장해둔, 보던)
_VERB_FORM = re.compile(r"^[\uac00-\ud7a3]+(?:은|던|둔|한|온|본|받은|놓은)$")
_EN_ALIAS = re.compile(r"^[a-z0-9]+$")
_WORD_BOUNDARY = re.compile(r"[\s,.!?~()\[\]\"'·/]")


class FacetHit(BaseModel):
    value: str  # Platform 또는 ContentType 값 (Lexicon이 유효값만 만든다)
    strength: Strength
    span: Span
    alias: str = ""


class FacetExtraction(BaseModel):
    platforms: list[FacetHit]
    content_types: list[FacetHit]
    spans: list[Span]


@dataclass(frozen=True)
class _Match:
    start: int
    end: int  # 별칭 + 접미까지
    alias_end: int
    value: str
    alias: str
    suffix: str


def _word_starts(text: str) -> list[int]:
    return [
        i for i, ch in enumerate(text) if not _WORD_BOUNDARY.match(ch) and (i == 0 or _WORD_BOUNDARY.match(text[i - 1]))
    ]


def _word_end(text: str, i: int) -> int:
    j = i
    while j < len(text) and not _WORD_BOUNDARY.match(text[j]):
        j += 1
    return j


class FacetExtractor:
    def __init__(self, lexicon: Lexicon, settings: QuerySettings | None = None) -> None:
        self.lexicon = lexicon
        self.settings = settings or QuerySettings()
        self._platform_aliases = sorted(lexicon.platform_alias_map.items(), key=lambda kv: (-len(kv[0]), kv[0]))
        self._type_aliases = sorted(lexicon.content_type_alias_map.items(), key=lambda kv: (-len(kv[0]), kv[0]))
        self._type_alias_set = frozenset(lexicon.content_type_alias_map)

    def extract(self, text: str) -> FacetExtraction:
        starts = _word_starts(text)
        p_matches = self._find(text, starts, self._platform_aliases)
        t_matches = self._find(text, starts, self._type_aliases)
        # 플랫폼 별칭 안쪽에 완전히 들어간 유형 별칭은 버린다 (같은 span은 둘 다 인정: 기사, 릴스, 쇼츠)
        t_matches = [
            t
            for t in t_matches
            if not any(
                p.start <= t.start and t.alias_end <= p.alias_end and (p.start, p.alias_end) != (t.start, t.alias_end)
                for p in p_matches
            )
        ]
        platforms = [
            FacetHit(
                value=m.value,
                strength=self._platform_strength(text, m),
                span=Span(start=m.start, end=m.end),
                alias=m.alias,
            )
            for m in p_matches
        ]
        ctypes = [
            FacetHit(
                value=m.value, strength=self._type_strength(text, m), span=Span(start=m.start, end=m.end), alias=m.alias
            )
            for m in t_matches
        ]
        spans = sorted({(m.start, m.end) for m in [*p_matches, *t_matches]})
        return FacetExtraction(
            platforms=_dedupe(platforms),
            content_types=_dedupe(ctypes),
            spans=[Span(start=s, end=e) for s, e in spans],
        )

    # ------------------------------------------------------------------
    def _find(self, text: str, starts: list[int], aliases: Sequence[tuple[str, str]]) -> list[_Match]:
        out: list[_Match] = []
        taken_until = -1
        for i in starts:
            if i < taken_until:
                continue
            m = self._match_at(text, i, aliases)
            if m is not None:
                out.append(m)
                taken_until = m.end
        return out

    def _match_at(self, text: str, i: int, aliases: Sequence[tuple[str, str]]) -> _Match | None:
        # 1) 정확 일치 (가장 긴 별칭 먼저)
        for alias, value in aliases:
            if not text.startswith(alias, i):
                continue
            alias_end = i + len(alias)
            is_en = bool(_EN_ALIAS.match(alias))
            if is_en and alias_end < len(text) and text[alias_end].isascii() and text[alias_end].isalnum():
                continue  # 영문 단어 경계
            word_end = (
                _word_end(text, alias_end)
                if alias_end < len(text) and not _WORD_BOUNDARY.match(text[alias_end])
                else alias_end
            )
            suffix = text[alias_end:word_end]
            if suffix and suffix not in _ALLOWED_SUFFIXES:
                continue
            return _Match(i, word_end, alias_end, value, alias, suffix)
        # 2) 퍼지 일치: 3자 이상 한글 별칭, 자모 거리 1
        word_end = _word_end(text, i)
        word = text[i:word_end]
        best: tuple[int, int, str, _Match] | None = None
        for alias, value in aliases:
            if len(alias) < self.settings.facet_fuzzy_min_length or " " in alias or _EN_ALIAS.match(alias):
                continue
            distance = self.settings.facet_fuzzy_distance
            for length in range(len(alias) - distance, len(alias) + distance + 1):
                if length < self.settings.facet_fuzzy_min_length or length > len(word):
                    continue
                cand, suffix = word[:length], word[length:]
                if suffix and suffix not in _ALLOWED_SUFFIXES:
                    continue
                d = jamo_distance(cand, alias, distance)
                if d <= distance:
                    key = (d, -len(alias), alias)
                    m = _Match(i, word_end, i + length, value, alias, suffix)
                    if best is None or key < best[:3]:
                        best = (*key, m)
        return best[3] if best else None

    def _is_verb_next(self, word: str) -> bool:
        return word in _VERB_NEXT or (
            len(word) >= self.settings.minimum_term_length
            and bool(_VERB_FORM.match(word))
            and not self._is_type_word(word)
        )

    def _next_word(self, text: str, pos: int) -> str:
        j = pos
        while j < len(text) and _WORD_BOUNDARY.match(text[j]):
            j += 1
        return text[j : _word_end(text, j)]

    def _platform_strength(self, text: str, m: _Match) -> Strength:
        if m.suffix in _HARD_PARTICLES or m.alias.endswith(("으로", "로")):
            return "hard"
        if m.suffix in _VERBAL_SUFFIXES:
            return "hard"
        nxt = self._next_word(text, m.end)
        if not nxt:
            return "hard"  # 마지막 어절 (예: "어니언 성수 인스타")
        if self._is_verb_next(nxt) or self._is_type_word(nxt) or nxt.startswith(("에서", "으로")):
            return "hard"
        if nxt in self.lexicon.stop_phrase_list or nxt in self.lexicon.browse_markers:
            return "hard"  # 예: "기사 다", "인스타 그거"
        return "soft"

    def _is_type_word(self, word: str) -> bool:
        """유형 별칭 그 자체이거나 유형 별칭 + 허용 접미 (예: '피드에서')."""
        if word in self._type_alias_set:
            return True
        return any(word.startswith(a) and word[len(a) :] in _ALLOWED_SUFFIXES for a in self._type_alias_set)

    def _type_strength(self, text: str, m: _Match) -> Strength:
        if m.alias in self.lexicon.content_type_soft_only:
            return "soft"
        if m.suffix:
            return "hard"
        nxt = self._next_word(text, m.end)
        if not nxt or self._is_verb_next(nxt) or self._is_type_word(nxt):
            return "hard"
        if nxt in self.lexicon.stop_phrase_list or nxt in self.lexicon.browse_markers:
            return "hard"
        return "soft"  # 다른 명사를 꾸미는 경우 (예: "논문 요약 영상"의 '논문')


def _dedupe(hits: list[FacetHit]) -> list[FacetHit]:
    """같은 값은 하나로. hard가 하나라도 있으면 hard. 첫 등장 순서 유지."""
    order: list[str] = []
    best: dict[str, FacetHit] = {}
    for h in hits:
        if h.value not in best:
            order.append(h.value)
            best[h.value] = h
        elif h.strength == "hard" and best[h.value].strength == "soft":
            best[h.value] = h
    return [best[v] for v in order]

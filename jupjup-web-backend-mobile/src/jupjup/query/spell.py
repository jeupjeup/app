"""교정 `SpellCorrector` (설계서 5.2절 1e~1g 3번)."""

from __future__ import annotations

import re
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from jupjup.query.settings import QuerySettings
from jupjup.text.lexicon import Lexicon
from jupjup.text.normalize import to_jamo


class Vocabulary(Protocol):
    """사용자별 인덱스 어휘. UserIndexRegistry가 제공한다."""

    def contains(self, term: str) -> bool: ...
    def doc_freq(self, term: str) -> int: ...
    def candidates_by_jamo(self, term: str, max_distance: int) -> list[tuple[str, int]]: ...
    def context_support(self, candidate: str, context_terms: list[str]) -> float: ...


class Correction(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_: str = Field(alias="from")
    to: str
    kind: Literal["synonym", "spelling"] = "spelling"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    evidence: tuple[str, ...] = ()


_HANGUL = re.compile(r"[가-힣]")
_LATIN = re.compile(r"^[a-z]+$")


class SpellCorrector:
    def __init__(self, lexicon: Lexicon, settings: QuerySettings | None = None) -> None:
        self.lexicon = lexicon
        self.settings = settings or QuerySettings()

    def correct(
        self, terms: list[str], vocabulary: Vocabulary | None, max_extra_distance: int = 0
    ) -> tuple[list[str], list[Correction]]:
        out: list[str] = []
        corrections: list[Correction] = []
        for term in terms:
            canon = self.lexicon.canonical(term)
            if canon != term:  # 동의어 사전이 먼저
                out.append(canon)
                corrections.append(
                    Correction(from_=term, to=canon, kind="synonym", confidence=1.0, evidence=("curated",))
                )
                continue
            directional = self.lexicon.directional_expansion(term)
            if directional is not None:
                expanded, confidence = directional
                # 상·하위어 방향 확장은 정규화 대체가 아니다. 원형을 검색 계약에 남기고 확장어를 나란히 둔다.
                out.extend((term, expanded))
                corrections.append(
                    Correction(
                        from_=term,
                        to=expanded,
                        kind="synonym",
                        confidence=confidence,
                        evidence=("curated_directional",),
                    )
                )
                continue
            explicit = self.lexicon.spelling_correction(term)
            if explicit is not None:
                out.append(explicit)
                corrections.append(
                    Correction(
                        from_=term,
                        to=explicit,
                        kind="spelling",
                        confidence=0.99,
                        evidence=("curated_typo",),
                    )
                )
                continue
            correction = self._spelling(term, terms, vocabulary, max_extra_distance)
            if correction is not None:
                out.append(correction.to)
                corrections.append(correction)
            else:
                out.append(term)
        return out, corrections

    def _spelling(
        self,
        term: str,
        terms: list[str],
        vocabulary: Vocabulary | None,
        extra: int,
    ) -> Correction | None:
        # 사전에 명시한 정상 어휘(예: 이주)는 자동 교정에서 제외한다.
        if (
            vocabulary is None
            or len(term) < self.settings.minimum_term_length
            or vocabulary.contains(term)
            or term in self.lexicon.protected_spellings
        ):
            return None
        if _LATIN.match(term):
            return None  # Latin 자동 교정은 비활성화하고 curated alias만 쓴다.
        if not _HANGUL.search(term):
            return None
        base_distance = (
            self.settings.short_spelling_distance
            if len(term) < self.settings.long_spelling_term_length
            else self.settings.long_spelling_distance
        )
        max_d = base_distance + extra
        cands = vocabulary.candidates_by_jamo(term, max_d)
        if not cands:
            return None
        # 문서 빈도가 가장 높은 후보. 동률이면 거리가 짧은 것, 그다음 사전순 (결정성)
        best = min(cands, key=lambda c: (-vocabulary.doc_freq(c[0]), c[1], c[0]))
        best_term, distance = best
        best_frequency = vocabulary.doc_freq(best_term)
        runner_up = max(
            (vocabulary.doc_freq(candidate) for candidate, _ in cands if candidate != best_term),
            default=0,
        )
        edit_quality = max(0.0, 1.0 - distance / max(len(to_jamo(term)), len(to_jamo(best_term)), 1))
        frequency_margin = max(0.0, (best_frequency - runner_up) / max(best_frequency, 1))
        context_terms = [candidate for candidate in terms if candidate != term]
        context_support = vocabulary.context_support(best_term, context_terms)
        confidence = 0.55 * edit_quality + 0.20 * frequency_margin + 0.25 * context_support
        if confidence < 0.75:
            return None
        # 2음절 정상어는 자모 거리 1 안에 무관한 고빈도 단어가 많다. vocabulary 부재만으로는 고치지 않고,
        # 다른 원형 용어와의 강한 공기 근거와 정규형 증거 수준의 신뢰도가 함께 있을 때만 허용한다.
        if len(term) <= 2 and (
            context_support < self.settings.short_spelling_min_context
            or confidence < self.settings.short_spelling_min_confidence
        ):
            return None
        evidence = ["edit_quality"]
        if frequency_margin > 0:
            evidence.append("frequency_margin")
        if context_support > 0:
            evidence.append("context_support")
        return Correction(
            from_=term,
            to=best_term,
            kind="spelling",
            confidence=round(confidence, 6),
            evidence=tuple(evidence),
        )

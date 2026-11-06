"""Lexicon 로더: 플랫폼/유형 별칭, 동의어, 불용 표현 (설계서 5.8.2절)."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import yaml

from jupjup.domain.models import CONTENT_TYPES, PLATFORMS, ContentType, Platform
from jupjup.text.normalize import normalize_text


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: 최상위는 매핑이어야 합니다")
    return data


@dataclass
class Lexicon:
    platform_alias_map: dict[str, Platform]
    content_type_alias_map: dict[str, ContentType]
    platform_labels: dict[str, str]
    content_type_labels: dict[str, str]
    content_type_soft_only: frozenset[str]
    content_type_match_map: dict[str, tuple[str, ...]]
    synonym_groups: list[list[str]]
    stop_phrase_list: list[str]
    stop_terms: frozenset[str]
    browse_markers: frozenset[str]
    deictic_markers: frozenset[str]
    purpose_markers: frozenset[str]
    purpose_suffixes: tuple[str, ...]
    protected_spellings: frozenset[str]
    directional_expansions: dict[str, tuple[str, float]]
    spelling_corrections: dict[str, str]
    _canon: dict[str, str] = field(default_factory=dict, repr=False)
    _groups_by_term: dict[str, list[str]] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        for group in self.synonym_groups:
            canon = group[0]
            for term in group:
                # 한 단어가 두 그룹에 들어 있으면 먼저 나온 그룹을 따른다 (결정성).
                self._canon.setdefault(term, canon)
                self._groups_by_term.setdefault(term, group)

    @classmethod
    def load(cls, root: Path) -> Lexicon:
        plat = _load_yaml(root / "platforms.yaml")
        ctype = _load_yaml(root / "content_types.yaml")
        syn = _load_yaml(root / "synonyms.yaml")
        stop = _load_yaml(root / "stop_phrases.yaml")

        p_alias: dict[str, Platform] = {}
        for value, aliases in (plat.get("aliases") or {}).items():
            if value not in PLATFORMS:
                raise ValueError(f"platforms.yaml: 알 수 없는 플랫폼 {value}")
            for a in aliases:
                p_alias[normalize_text(str(a))] = cast(Platform, value)
        c_alias: dict[str, ContentType] = {}
        for value, aliases in (ctype.get("aliases") or {}).items():
            if value not in CONTENT_TYPES:
                raise ValueError(f"content_types.yaml: 알 수 없는 유형 {value}")
            for a in aliases:
                c_alias[normalize_text(str(a))] = cast(ContentType, value)
        match_map: dict[str, tuple[str, ...]] = {
            str(k): tuple(str(x) for x in v) for k, v in (ctype.get("match_map") or {}).items()
        }
        groups = [[normalize_text(str(t)) for t in g] for g in (syn.get("groups") or [])]
        directional_expansions: dict[str, tuple[str, float]] = {}
        for source, entries in (syn.get("directional_expansions") or {}).items():
            for entry in entries:
                source_term = normalize_text(str(source))
                directional_expansions[source_term] = (
                    normalize_text(str(entry["term"])),
                    float(entry.get("confidence", 0.85)),
                )
        return cls(
            platform_alias_map=p_alias,
            content_type_alias_map=c_alias,
            platform_labels={str(k): str(v) for k, v in (plat.get("labels_ko") or {}).items()},
            content_type_labels={str(k): str(v) for k, v in (ctype.get("labels_ko") or {}).items()},
            content_type_soft_only=frozenset(normalize_text(str(x)) for x in ctype.get("soft_only") or []),
            content_type_match_map=match_map,
            synonym_groups=groups,
            stop_phrase_list=[normalize_text(str(x)) for x in stop.get("phrases") or []],
            stop_terms=frozenset(normalize_text(str(x)) for x in stop.get("terms") or []),
            browse_markers=frozenset(normalize_text(str(x)) for x in stop.get("browse_markers") or []),
            deictic_markers=frozenset(normalize_text(str(x)) for x in stop.get("deictic_markers") or []),
            purpose_markers=frozenset(normalize_text(str(x)) for x in stop.get("purpose_markers") or []),
            purpose_suffixes=tuple(
                sorted((normalize_text(str(x)) for x in stop.get("purpose_suffixes") or []), key=len, reverse=True)
            ),
            protected_spellings=frozenset(normalize_text(str(x)) for x in syn.get("protected_spellings") or []),
            directional_expansions=directional_expansions,
            spelling_corrections={
                normalize_text(str(source)): normalize_text(str(target))
                for source, target in (syn.get("spelling_corrections") or {}).items()
            },
        )

    # --- 5.8.2절 인터페이스 -------------------------------------------------
    def platform_aliases(self) -> dict[str, Platform]:
        return dict(self.platform_alias_map)

    def content_type_aliases(self) -> dict[str, ContentType]:
        return dict(self.content_type_alias_map)

    def canonical(self, term: str) -> str:
        return self._canon.get(term, term)

    def fold_phrases(self, text: str) -> str:
        """공백을 포함한 동의어를 정규형으로 접는다.

        영문 표현은 단어 중간의 ``shop`` 같은 부분 문자열을 바꾸지 않도록
        영숫자 경계를 적용한다. 한글과 공백 없는 단어는 기존 토큰 정규화가 담당한다.
        """
        folded = text
        phrases = sorted(
            ((term, group[0]) for group in self.synonym_groups for term in group if " " in term),
            key=lambda item: (-len(item[0]), item[0]),
        )
        for phrase, canonical in phrases:
            pattern = rf"(?<![0-9a-z]){re.escape(phrase)}(?![0-9a-z])"
            folded = re.sub(pattern, canonical, folded)
        return folded

    def synonyms(self, term: str) -> list[str]:
        group = self._groups_by_term.get(term)
        return [t for t in group if t != term] if group else []

    def directional_expansion(self, term: str) -> tuple[str, float] | None:
        return self.directional_expansions.get(term)

    def spelling_correction(self, term: str) -> str | None:
        return self.spelling_corrections.get(term)

    def stop_phrases(self) -> list[str]:
        return list(self.stop_phrase_list)

    # --- 보조 -----------------------------------------------------------------
    def expand_content_types(self, values: list[str] | set[str]) -> set[str]:
        """질의 유형을 저장물 유형 집합으로 넓힌다 (예: video → video, short_video)."""
        out: set[str] = set()
        for v in values:
            out.update(self.content_type_match_map.get(v, (v,)))
        return out

    def platform_label(self, value: str) -> str:
        return self.platform_labels.get(value, value)

    def content_type_label(self, value: str) -> str:
        return self.content_type_labels.get(value, value)

    def user_words(self) -> Mapping[str, str]:
        """Kiwi 사용자 사전에 넣을 단어 → 품사. 공백 없는 한글 2자 이상만."""
        words: dict[str, str] = {}
        for alias in [*self.platform_alias_map, *self.content_type_alias_map]:
            if _is_registrable(alias):
                words.setdefault(alias, "NNP")
        for group in self.synonym_groups:
            for term in group:
                if _is_registrable(term):
                    words.setdefault(term, "NNG")
        for source, (target, _) in self.directional_expansions.items():
            for term in (source, target):
                if _is_registrable(term):
                    words.setdefault(term, "NNG")
        for source, target in self.spelling_corrections.items():
            for term in (source, target):
                if _is_registrable(term):
                    words.setdefault(term, "NNG")
        return words


def _is_registrable(word: str) -> bool:
    return len(word) >= 2 and " " not in word and all("가" <= c <= "힣" for c in word)

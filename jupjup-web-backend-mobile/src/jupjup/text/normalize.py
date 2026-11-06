"""텍스트 정규화와 자모 유틸 (설계서 5.2절 1a, 5.8.2절)."""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

_CHO = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"
_JUNG = "ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ"
_JONG = ["", *"ㄱㄲㄳㄴㄵㄶㄷㄹㄺㄻㄼㄽㄾㄿㅀㅁㅂㅄㅅㅆㅇㅈㅊㅋㅌㅍㅎ"]

# 호환 자모(ㄱ-ㅣ)와 NFKC 이후의 조합형 자모(U+1100~U+11FF) 둘 다 반복 웃음/울음 표지로 본다.
_JAMO_RUN = re.compile(r"[ㄱ-ㆎᄀ-ᇿ]{2,}")
_PUNCT_RUN = re.compile(r"([!?.~,;^])\1+")
_SOCIAL_PREFIX = re.compile(r"[#@](?=[0-9a-z가-힣])", re.IGNORECASE)
_WS = re.compile(r"\s+")


def _is_dropped(ch: str) -> bool:
    cat = unicodedata.category(ch)
    if cat in ("Cc", "Cf", "Cs", "Co", "Cn"):
        return ch not in "\t\n\r"
    if cat == "So":  # 이모지, 기호 그림
        return True
    cp = ord(ch)
    return 0xFE00 <= cp <= 0xFE0F or 0x1F3FB <= cp <= 0x1F3FF  # variation selector, 피부색 수정자


def normalize_text(text: str) -> str:
    """NFKC, 소문자, 이모지·제어문자 제거, 반복 자모/구두점 제거, 공백 정리."""
    s = _JAMO_RUN.sub(" ", text)
    s = unicodedata.normalize("NFKC", s)
    s = _JAMO_RUN.sub(" ", s)
    s = "".join(" " if _is_dropped(c) else c for c in s)
    s = _PUNCT_RUN.sub(" ", s)
    s = s.lower()
    s = _SOCIAL_PREFIX.sub("", s)
    return _WS.sub(" ", s).strip()


def is_hangul_syllable(ch: str) -> bool:
    return "가" <= ch <= "힣"


@lru_cache(maxsize=65536)
def to_jamo(text: str) -> str:
    """한글 음절을 초성/중성/종성 호환 자모로 분해한다. 그 밖의 문자는 그대로 둔다."""
    out: list[str] = []
    for ch in text:
        if is_hangul_syllable(ch):
            idx = ord(ch) - 0xAC00
            out.append(_CHO[idx // 588])
            out.append(_JUNG[(idx % 588) // 28])
            jong = _JONG[idx % 28]
            if jong:
                out.append(jong)
        else:
            out.append(ch)
    return "".join(out)


def levenshtein(a: str, b: str, max_distance: int | None = None) -> int:
    """편집 거리. max_distance를 주면 넘는 순간 max_distance+1을 돌려준다 (조기 종료)."""
    if a == b:
        return 0
    if len(a) < len(b):
        a, b = b, a
    if max_distance is not None and len(a) - len(b) > max_distance:
        return max_distance + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        row_min = i
        for j, cb in enumerate(b, 1):
            v = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
            cur.append(v)
            row_min = min(row_min, v)
        if max_distance is not None and row_min > max_distance:
            return max_distance + 1
        prev = cur
    return prev[-1]


def jamo_distance(a: str, b: str, max_distance: int | None = None) -> int:
    """자모 단위 Levenshtein 거리."""
    return levenshtein(to_jamo(a), to_jamo(b), max_distance)

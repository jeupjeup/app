"""토크나이저: Kiwi 형태소(morph)와 문자 n-gram(ngram) (설계서 5.3.2절, 5.8.2절)."""

from __future__ import annotations

import re
import threading
from functools import lru_cache
from typing import Any, NamedTuple, Protocol

from jupjup.text.lexicon import Lexicon
from jupjup.text.normalize import normalize_text


class Token(NamedTuple):
    surface: str
    lemma: str
    pos: str
    start: int
    end: int


class Tokenizer(Protocol):
    name: str

    def tokenize(self, text: str) -> list[Token]: ...
    def index_terms(self, text: str) -> list[str]: ...
    def query_terms(self, text: str) -> list[str]: ...


KEYWORD_POS = frozenset({"NNG", "NNP", "SL", "SN", "XR"})
NOUN_POS = frozenset({"NNG", "NNP"})
_PREDICATE_POS = frozenset({"VV", "VA"})
_DERIV_BASE = frozenset({"NNG", "NNP", "XR"})
# 너무 흔해서 검색 신호가 없는 용언 어간
_LIGHT_STEMS = frozenset(
    {"하", "되", "있", "없", "보", "가", "오", "주", "받", "같", "않", "알", "말", "두", "놓", "쓰", "싶", "나", "이"}
)
_NGRAM_KEEP = re.compile(r"[^0-9a-z가-힣]+")


class KiwiTokenizer:
    """name="morph". 키워드 품사 + 용언 어간 + 연속 명사 결합 + 동의어 정규형."""

    name = "morph"

    def __init__(self, lexicon: Lexicon, model_type: str = "knlm") -> None:
        from kiwipiepy import Kiwi  # 무거운 import는 생성 시점에만

        self.lexicon = lexicon
        kwargs: dict[str, Any] = {}
        if model_type and model_type != "knlm":
            kwargs["model_type"] = model_type
        self._kiwi = Kiwi(**kwargs)
        for word, tag in sorted(lexicon.user_words().items()):
            if word.endswith("으로"):
                continue
            self._kiwi.add_user_word(word, tag, 0.0)
        self._lock = threading.Lock()
        self._cached = lru_cache(maxsize=8192)(self._tokenize_uncached)

    def _tokenize_uncached(self, text: str) -> tuple[Token, ...]:
        with self._lock:
            raw = self._kiwi.tokenize(text)
        out: list[Token] = []
        for t in raw:
            form = str(t.form)
            pos = str(t.tag)
            start = int(t.start)
            end = start + int(t.len)
            lemma = form.lower() if pos == "SL" else form
            out.append(Token(form, lemma, pos, start, end))
        return tuple(out)

    def tokenize(self, text: str) -> list[Token]:
        """입력은 normalize_text를 거친 텍스트라고 가정하지 않는다. 내부에서 정규화한다."""
        return list(self._cached(normalize_text(text)))

    def keyword_candidates(self, text: str, drop_bound_single: bool = False) -> list[str]:
        """키워드 품사 토큰과 연속 명사 결합어 (정규형 적용 전). 입력 순서 유지, 중복 허용.

        drop_bound_single=True면 다른 명사에 붙어 있는 한 글자 한글 명사(맛집의 '맛', '집')를 뺀다.
        결합어(맛집)는 남고, 띄어 쓴 한 글자 명사(귤, 책)도 남는다.
        """
        tokens = self.tokenize(text)
        out: list[str] = []
        i = 0
        while i < len(tokens):
            tok = tokens[i]
            if tok.pos in KEYWORD_POS and not (drop_bound_single and self._bound_single(tokens, i)):
                out.append(tok.lemma)
            nxt = tokens[i + 1] if i + 1 < len(tokens) and tokens[i + 1].start == tok.end else None
            # 접두사 + 명사 (신+메뉴 → 신메뉴, 재+활용 → 재활용)
            if tok.pos == "XPN" and nxt is not None and nxt.pos in NOUN_POS:
                out.append(tok.lemma + nxt.lemma)
            # 명사/어근 + 명사 파생 접미사 (간헐+적, 공정+성, 안마+기). 복수 표지 '들'은 제외
            if tok.pos in _DERIV_BASE and nxt is not None and nxt.pos == "XSN" and nxt.lemma != "들":
                out.append(tok.lemma + nxt.lemma)
            # 띄어쓰기 없이 붙은 명사열을 결합 (예: 기후+변화 → 기후변화). 최대 3개.
            if tok.pos in NOUN_POS:
                j = i
                parts = [tok.lemma]
                while (
                    j + 1 < len(tokens)
                    and tokens[j + 1].pos in NOUN_POS
                    and tokens[j + 1].start == tokens[j].end
                    and len(parts) < 3
                ):
                    j += 1
                    parts.append(tokens[j].lemma)
                    out.append("".join(parts))
            i += 1
        return out

    @staticmethod
    def _bound_single(tokens: list[Token], i: int) -> bool:
        tok = tokens[i]
        if tok.pos not in NOUN_POS or len(tok.lemma) != 1 or tok.lemma.isascii():
            return False
        prev_bound = i > 0 and tokens[i - 1].pos in NOUN_POS and tokens[i - 1].end == tok.start
        next_bound = i + 1 < len(tokens) and tokens[i + 1].pos in NOUN_POS and tokens[i + 1].start == tok.end
        return prev_bound or next_bound

    def _terms(self, text: str) -> list[str]:
        terms: list[str] = []
        for t in self.keyword_candidates(text):
            terms.append(self.lexicon.canonical(t))
        for tok in self.tokenize(text):
            if tok.pos in _PREDICATE_POS and tok.lemma not in _LIGHT_STEMS:
                terms.append(tok.lemma + "다")  # 용언 원형 (고르 → 고르다). 명사 교정 후보와 섞이지 않는다
        return terms

    def index_terms(self, text: str) -> list[str]:
        return self._terms(text)

    def query_terms(self, text: str) -> list[str]:
        return self._terms(text)


class CharNgramTokenizer:
    """name="ngram". 한글·영문·숫자만 남기고 공백을 지운 뒤 문자 n-gram."""

    name = "ngram"

    def __init__(self, n: int = 2) -> None:
        if n < 1:
            raise ValueError("n은 1 이상")
        self.n = n

    def _compact(self, text: str) -> str:
        return _NGRAM_KEEP.sub("", normalize_text(text))

    def tokenize(self, text: str) -> list[Token]:
        s = self._compact(text)
        if not s:
            return []
        if len(s) < self.n:
            return [Token(s, s, "NGRAM", 0, len(s))]
        return [Token(s[i : i + self.n], s[i : i + self.n], "NGRAM", i, i + self.n) for i in range(len(s) - self.n + 1)]

    def index_terms(self, text: str) -> list[str]:
        return [t.lemma for t in self.tokenize(text)]

    def query_terms(self, text: str) -> list[str]:
        return self.index_terms(text)

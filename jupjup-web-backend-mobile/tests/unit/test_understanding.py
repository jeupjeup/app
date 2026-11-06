"""T8: QueryUnderstander 조립, SpellCorrector, 불용 표현, 의미 질의 (S1~S7 해석 스냅샷)."""

from __future__ import annotations

from datetime import datetime

import pytest

from jupjup.domain.errors import InvalidQueryError, LLMProviderError
from jupjup.providers.llm import MockLLM, prompt_hash
from jupjup.query.facets import FacetExtractor
from jupjup.query.intent import IntentClassifier
from jupjup.query.spell import SpellCorrector
from jupjup.query.temporal import TemporalParser
from jupjup.query.understanding import _ASSIST_SYSTEM, ParsedQuery, QueryAssistant, QueryUnderstander
from jupjup.text.lexicon import Lexicon
from jupjup.text.normalize import jamo_distance
from jupjup.text.tokenizer import KiwiTokenizer
from tests.conftest import KST, NOW


class FakeVocab:
    def __init__(self, df: dict[str, int]) -> None:
        self.df = df

    def contains(self, term: str) -> bool:
        return term in self.df

    def doc_freq(self, term: str) -> int:
        return self.df.get(term, 0)

    def candidates_by_jamo(self, term: str, max_distance: int) -> list[tuple[str, int]]:
        out = []
        for t in self.df:
            d = jamo_distance(term, t, max_distance)
            if d <= max_distance:
                out.append((t, d))
        return out

    def context_support(self, candidate: str, context_terms: list[str]) -> float:
        return 1.0 if candidate == "기후변화" and "논문" in context_terms else 0.0


@pytest.fixture(scope="module")
def qu(lexicon: Lexicon, kiwi: KiwiTokenizer) -> QueryUnderstander:
    return QueryUnderstander(
        TemporalParser(), FacetExtractor(lexicon), IntentClassifier(lexicon), kiwi, SpellCorrector(lexicon), lexicon
    )


def _snap(p: ParsedQuery) -> dict[str, object]:
    return {
        "intent": p.intent,
        "time": (p.time_range.start.date().isoformat(), p.time_range.end.date().isoformat()) if p.time_range else None,
        "platforms": [(h.value, h.strength) for h in p.platforms],
        "types": [(h.value, h.strength) for h in p.content_types],
        "keywords": p.keywords,
        "purpose": p.purpose_terms,
        "semantic": p.semantic_query,
    }


SCENARIOS = {
    "S1": (
        "지난달 인스타에서 본 성수동 카페",
        {
            "intent": "lookup",
            "time": ("2026-09-01", "2026-10-01"),
            "platforms": [("instagram", "hard")],
            "types": [],
            "keywords": ["성수동", "카페"],
            "purpose": [],
            "semantic": "성수동 카페",
        },
    ),
    "S2": (
        "과제에 쓰려던 기후변화 논문",
        {
            "intent": "lookup",
            "time": None,
            "platforms": [],
            "types": [("paper", "hard")],
            "keywords": ["기후변화"],
            "purpose": ["과제"],
            "semantic": "과제에 쓰려던 기후변화 논문",
        },
    ),
    "S3": (
        "유툽에서 본 파스타 레시피 그거",
        {
            "intent": "lookup",
            "time": None,
            "platforms": [("youtube", "hard")],
            "types": [],
            "keywords": ["파스타", "레시피"],
            "purpose": [],
            "semantic": "파스타 레시피",
        },
    ),
    "S4": (
        "작년 여름에 캡처해둔 제주 숙소",
        {
            "intent": "lookup",
            "time": ("2025-06-01", "2025-09-01"),
            "platforms": [],
            "types": [("image", "hard")],
            "keywords": ["제주", "숙소"],
            "purpose": [],
            "semantic": "캡처 제주 숙소",
        },
    ),
    "S5": (
        "까페 추천 저장한 거 다 보여줘",
        {
            "intent": "browse",
            "time": None,
            "platforms": [],
            "types": [],
            "keywords": ["카페", "추천"],
            "purpose": [],
            "semantic": "까페 추천",
        },
    ),
    "S6": (
        "화성 이주 계획 다큐",
        {
            "intent": "lookup",
            "time": None,
            "platforms": [],
            "types": [],
            "keywords": ["화성", "이주", "계획", "다큐"],
            "purpose": [],
            "semantic": "화성 이주 계획 다큐",
        },
    ),
    "S7": (
        "지난주 카톡으로 받은 회의 장소",
        {
            "intent": "lookup",
            "time": ("2026-10-05", "2026-10-12"),
            "platforms": [("kakaotalk", "hard")],
            "types": [],
            "keywords": ["회의", "장소"],
            "purpose": [],
            "semantic": "회의 장소",
        },
    ),
}


@pytest.mark.parametrize("sid", sorted(SCENARIOS))
def test_scenario_snapshots(qu: QueryUnderstander, sid: str) -> None:
    query, expected = SCENARIOS[sid]
    assert _snap(qu.parse(query, NOW)) == expected


def test_s1_window(qu: QueryUnderstander) -> None:
    p = qu.parse("지난달 인스타에서 본 성수동 카페", NOW)
    assert p.time_window is not None
    assert p.time_window.start == datetime(2026, 8, 25, tzinfo=KST)
    assert p.time_window.end == datetime(2026, 10, 8, tzinfo=KST)


@pytest.mark.parametrize("query", ["유튜브", "유튜브 영상", "지난달 인스타", "인스타 게시물", "지난달"])
def test_filter_only_query_becomes_browse(qu: QueryUnderstander, query: str) -> None:
    parsed = qu.parse(query, NOW)
    assert parsed.intent == "browse"
    assert parsed.filter_only is True
    assert parsed.keywords == [] and parsed.purpose_terms == [] and parsed.residual_text == ""


def test_type_filter_with_meaningful_keyword_is_not_filter_only(qu: QueryUnderstander) -> None:
    parsed = qu.parse("카페 영상", NOW)
    assert parsed.intent == "lookup"
    assert parsed.filter_only is False
    assert parsed.keywords == ["카페"]


def test_synonym_correction_keeps_raw(qu: QueryUnderstander) -> None:
    p = qu.parse("까페 추천", NOW)
    assert "카페" in p.keywords
    assert "까페" in p.raw_keywords  # 원형 보존
    assert [(c.from_, c.to, c.kind) for c in p.corrections] == [("까페", "카페", "synonym")]


def test_spelling_correction_with_vocabulary(qu: QueryUnderstander) -> None:
    vocab = FakeVocab({"기후변화": 5, "기후": 7, "논문": 9, "변화": 3})
    p = qu.parse("기휴변화 논문", NOW, vocabulary=vocab)
    assert "기후변화" in p.keywords
    assert "기휴변화" in p.raw_keywords
    assert any(c.from_ == "기휴변화" and c.to == "기후변화" for c in p.corrections)
    assert p.semantic_query == p.semantic_text_original == "기휴변화 논문"
    assert "기후변화" in p.semantic_text_augmented


def test_short_korean_word_is_not_replaced_by_frequency(lexicon: Lexicon) -> None:
    sp = SpellCorrector(lexicon)
    vocab = FakeVocab({"녹초": 2, "독차": 9})  # 둘 다 '녹차'와 자모 거리 1
    out, corr = sp.correct(["녹차"], vocab)
    assert out == ["녹차"] and corr == []


def test_curated_short_typo_is_allowed_but_normal_word_is_protected(lexicon: Lexicon) -> None:
    sp = SpellCorrector(lexicon)
    out, corrections = sp.correct(["추쳔"], FakeVocab({"추천": 10}))
    assert out == ["추천"]
    assert corrections[0].confidence == pytest.approx(0.99)
    assert corrections[0].evidence == ("curated_typo",)
    assert sp.correct(["이주"], FakeVocab({"위주": 20}))[0] == ["이주"]


class ContextVocab(FakeVocab):
    def __init__(self, df: dict[str, int], support: float) -> None:
        super().__init__(df)
        self.support = support

    def context_support(self, candidate: str, context_terms: list[str]) -> float:
        return self.support if context_terms else 0.0


def test_two_syllable_typo_needs_strong_context(lexicon: Lexicon) -> None:
    sp = SpellCorrector(lexicon)
    vocab = {"선물": 10, "어버이날": 3}
    out, corrections = sp.correct(["어버이날", "선뮬"], ContextVocab(vocab, 1.0))
    assert out == ["어버이날", "선물"]
    assert corrections[0].confidence >= 0.90
    assert corrections[0].evidence == ("edit_quality", "frequency_margin", "context_support")
    weak, weak_corrections = sp.correct(["어버이날", "선뮬"], ContextVocab(vocab, 0.2))
    assert weak == ["어버이날", "선뮬"] and weak_corrections == []
    alone, _ = sp.correct(["선뮬"], ContextVocab(vocab, 1.0))
    assert alone == ["선뮬"]


def test_context_free_near_word_is_not_auto_corrected(lexicon: Lexicon) -> None:
    sp = SpellCorrector(lexicon)
    out, corrections = sp.correct(
        ["아프리카", "사파리", "여행"],
        FakeVocab({"파프리카": 20, "사파리": 2, "여행": 10}),
    )
    assert out[0] == "아프리카"
    assert all(correction.from_ != "아프리카" for correction in corrections)


def test_directional_expansion_is_not_a_reverse_synonym(lexicon: Lexicon) -> None:
    sp = SpellCorrector(lexicon)
    out, corrections = sp.correct(["다리", "운동"], FakeVocab({"하체": 10, "운동": 20}))
    assert out == ["다리", "하체", "운동"]
    assert corrections[0].evidence == ("curated_directional",)
    reverse, _ = sp.correct(["하체"], FakeVocab({"다리": 10}))
    assert reverse == ["하체"]


def test_spelling_limits(lexicon: Lexicon) -> None:
    sp = SpellCorrector(lexicon)
    vocab = FakeVocab({"카레": 3})
    assert sp.correct(["카"], vocab)[0] == ["카"]  # 1자는 교정 안 함
    assert sp.correct(["카레"], vocab)[1] == []  # 어휘에 있으면 그대로
    assert sp.correct(["2025"], FakeVocab({"2026": 1}))[0] == ["2025"]  # 숫자는 교정 안 함
    out, _ = sp.correct(["코로나"], FakeVocab({"카레": 3}))
    assert out == ["코로나"]  # 거리 초과
    out, _ = sp.correct(["캬레"], vocab, max_extra_distance=0)
    assert out == ["캬레"]


def test_curated_typo_does_not_require_user_vocabulary(qu: QueryUnderstander) -> None:
    p = qu.parse("기휴변화 논문", NOW)
    assert "기후변화" in p.keywords
    assert any(c.from_ == "기휴변화" and c.evidence == ("curated_typo",) for c in p.corrections)


def test_stop_phrases_removed(qu: QueryUnderstander) -> None:
    p = qu.parse("인스타에서 봤던 거 있잖아 디저트", NOW)
    assert p.keywords == ["디저트"]
    assert p.semantic_query == "디저트"


def test_hashtag_and_mention_prefixes_are_normalized_not_spell_corrected(qu: QueryUnderstander) -> None:
    parsed = qu.parse("#카페 @성수!!", NOW)
    assert parsed.normalized == "카페 성수"
    assert parsed.raw_keywords == ["카페", "성수"]
    assert all(correction.from_ != "#카페" for correction in parsed.corrections)


def test_purpose_suffix(qu: QueryUnderstander) -> None:
    p = qu.parse("선물용으로 저장한 향수", NOW)
    assert p.purpose_terms == ["선물"]
    assert p.keywords == ["향수"]


@pytest.mark.parametrize(("term", "morph"), [("발로란트", "발로"), ("텍스쳐", "텍스")])
def test_original_surface_term_survives_kiwi_truncation(qu: QueryUnderstander, term: str, morph: str) -> None:
    parsed = qu.parse(f"  #{term}\t", NOW)
    assert parsed.raw_keywords == parsed.keywords == [morph]
    assert parsed.original_terms == [morph, term]
    assert parsed.canonical_terms == [morph]
    assert qu.parse(f"{term} {term}", NOW).original_terms.count(term) == 1


@pytest.mark.parametrize("purpose", ["과제에 쓰려던", "선물용으로 저장한"])
def test_surface_terms_do_not_reintroduce_filters_or_purpose(qu: QueryUnderstander, purpose: str) -> None:
    parsed = qu.parse(f"지난달 인스타에서 본 {purpose} 발로란트 영상", NOW)
    assert parsed.time_range is not None
    assert parsed.hard_platforms() == ["instagram"]
    assert parsed.hard_content_types() == ["video"]
    assert parsed.purpose_terms == (["과제"] if purpose.startswith("과제") else ["선물"])
    assert "발로란트" in parsed.original_terms
    assert set(parsed.original_terms) - set(parsed.raw_keywords) <= {"발로란트"}


def test_surface_expansion_requires_a_keyword_and_index_evidence(qu: QueryUnderstander) -> None:
    parsed = qu.parse("스파게티 만드는 법", NOW, FakeVocab({"법": 1}))
    assert parsed.original_terms == parsed.raw_keywords == ["스파게티"]
    unknown = qu.parse("발로란트", NOW, FakeVocab({"다른단어": 1}))
    assert unknown.original_terms == unknown.raw_keywords == ["발로"]
    assert unknown.query_signal_profile == "low-signal"


def test_semantic_fallback_to_keywords(qu: QueryUnderstander) -> None:
    p = qu.parse("지난달 인스타", NOW)
    assert p.keywords == [] and p.semantic_query == ""


@pytest.mark.parametrize(
    "bad",
    ["", "   ", "!!!", "ㅋㅋㅋ", "🙂🙂", "가" * 200, "카페 " * 50, "가" * 201],
)
def test_invalid_queries(qu: QueryUnderstander, bad: str) -> None:
    with pytest.raises(InvalidQueryError):
        qu.parse(bad, NOW)


def test_naive_now_rejected(qu: QueryUnderstander) -> None:
    with pytest.raises(ValueError):
        qu.parse("카페", datetime(2026, 10, 15))


def test_future_warning_propagates(qu: QueryUnderstander) -> None:
    p = qu.parse("다음 주에 갈 카페", NOW)
    assert p.time_range is None and "future_time_ignored" in p.warnings


def test_assistant_fills_only_keywords(lexicon: Lexicon, kiwi: KiwiTokenizer) -> None:
    user = "<query>그거 뭐였지</query>"
    llm = MockLLM({prompt_hash(_ASSIST_SYSTEM, user): {"keywords": ["디저트"], "semantic_query": "디저트 가게"}})
    qa = QueryAssistant(llm)
    q = QueryUnderstander(
        TemporalParser(),
        FacetExtractor(lexicon),
        IntentClassifier(lexicon),
        kiwi,
        SpellCorrector(lexicon),
        lexicon,
        assistant=qa,
        assist_enabled=True,
    )
    p = q.parse("그거 뭐였지", NOW)
    assert p.llm_rewritten and p.keywords == ["디저트"] and p.semantic_query == "디저트 가게"
    assert p.time_range is None and p.platforms == []


def test_assistant_failure_falls_back(lexicon: Lexicon, kiwi: KiwiTokenizer) -> None:
    user = "<query>그거 뭐였지</query>"
    llm = MockLLM({prompt_hash(_ASSIST_SYSTEM, user): LLMProviderError("down")})
    q = QueryUnderstander(
        TemporalParser(),
        FacetExtractor(lexicon),
        IntentClassifier(lexicon),
        kiwi,
        SpellCorrector(lexicon),
        lexicon,
        assistant=QueryAssistant(llm),
        assist_enabled=True,
    )
    p = q.parse("그거 뭐였지", NOW)
    assert not p.llm_rewritten and p.keywords == []


def test_assistant_disabled_by_default(qu: QueryUnderstander) -> None:
    assert qu.assist_enabled is False


def test_single_char_nouns(qu: QueryUnderstander) -> None:
    assert "귤" in qu.parse("인별에서 본 귤 따기", NOW).keywords
    kws = qu.parse("디저트 맛집", NOW).keywords
    assert "맛집" in kws and "맛" not in kws and "집" not in kws


def test_mixed_english_multiword_synonym_and_symbol_cleanup(qu: QueryUnderstander) -> None:
    mixed = qu.parse("IG에서 본 coffee shop 디저트", NOW)
    assert mixed.hard_platforms() == ["instagram"]
    assert mixed.keywords == ["카페", "디저트"]
    assert mixed.semantic_query == "카페 디저트"

    symbols = qu.parse("성수동!!! 카페??? #맛집", NOW)
    assert "#" not in symbols.keywords
    assert {"성수동", "카페", "맛집"} <= set(symbols.keywords)


def test_short_valid_word_is_not_spelling_corrected(qu: QueryUnderstander) -> None:
    parsed = qu.parse("화성 이주 계획 다큐", NOW, vocabulary=FakeVocab({"위주": 100, "계획": 5}))
    assert "이주" in parsed.keywords
    assert all(not (correction.from_ == "이주" and correction.to == "위주") for correction in parsed.corrections)


def test_platform_before_browse_marker_is_hard(qu: QueryUnderstander) -> None:
    p = qu.parse("인공지능 관련 기사 다", NOW)
    assert p.hard_platforms() == ["news"] and p.intent == "browse"

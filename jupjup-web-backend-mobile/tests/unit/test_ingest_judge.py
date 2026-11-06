from __future__ import annotations

import pytest

from jupjup.config import REPO_ROOT
from jupjup.eval.judge import (
    DeterministicFaithfulnessChecker,
    split_sentences,
    unsupported_sentence_metrics,
)
from jupjup.text.lexicon import Lexicon
from jupjup.text.tokenizer import KiwiTokenizer


def _checker() -> DeterministicFaithfulnessChecker:
    lexicon = Lexicon.load(REPO_ROOT / "data" / "lexicon")
    return DeterministicFaithfulnessChecker(KiwiTokenizer(lexicon))


def test_deterministic_check_flags_missing_number_date_and_proper_noun() -> None:
    result = _checker().check(
        "서울시는 2026년 10월 3일 예산 1200억원을 발표했다.",
        "서울시는 2026년 10월 3일 예산 1200억원을 발표했다. 부산시는 예산 1500억원을 발표했다.",
    )
    assert result.unsupported_candidates == ["부산시는 예산 1500억원을 발표했다."]
    assert "1500" in result.missing_terms[result.unsupported_candidates[0]]


def test_deterministic_check_is_empty_when_terms_are_grounded() -> None:
    source = "모아 미술관 전시는 2026년 11월 2일 열린다."
    result = _checker().check(source, source)
    assert result.unsupported_candidates == []


def test_deterministic_check_uses_number_token_boundaries() -> None:
    result = _checker().check("예산 120억원을 편성했다.", "예산 12억원을 편성했다.")
    assert result.unsupported_candidates == ["예산 12억원을 편성했다."]
    assert "12" in result.missing_terms[result.unsupported_candidates[0]]


def test_deterministic_check_flags_uppercase_english_proper_nouns() -> None:
    result = _checker().check("Apple released iPhone.", "Samsung released Galaxy.")
    assert result.unsupported_candidates == ["Samsung released Galaxy."]
    assert {"Samsung", "Galaxy"} <= set(result.missing_terms[result.unsupported_candidates[0]])


def test_deterministic_check_ignores_english_sentence_initial_stopwords() -> None:
    result = _checker().check(
        "원문에는 안정적인 결과가 기록되어 있다.",
        "This is fine. The result is stable. It works. We agree. In summary, it is useful. Our result holds.",
    )
    assert result.unsupported_candidates == []


def test_deterministic_check_compares_sentence_initial_word_case_insensitively_with_boundaries() -> None:
    grounded = _checker().check("apple released a product.", "Apple released a product.")
    substring_only = _checker().check("pineapple sales increased.", "Apple released a product.")

    assert grounded.unsupported_candidates == []
    assert substring_only.unsupported_candidates == ["Apple released a product."]
    assert "Apple" in substring_only.missing_terms["Apple released a product."]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param(
            "증감률 3.5%와 1.2배, v2.0을 2026.11.02에 발표했다. Next sentence입니다.",
            ["증감률 3.5%와 1.2배, v2.0을 2026.11.02에 발표했다.", "Next sentence입니다."],
            id="ko-en-decimal-version-date",
        ),
        pytest.param(
            "Dr. Kim은 e.g. 표기와 v2.1을 검토했다. It works.",
            ["Dr. Kim은 e.g. 표기와 v2.1을 검토했다.", "It works."],
            id="english-abbreviations",
        ),
        pytest.param(
            "잠시만요... 다음 문장입니다! Really? 네.",
            ["잠시만요...", "다음 문장입니다!", "Really?", "네."],
            id="ellipsis-and-terminal-boundaries",
        ),
        pytest.param("글쎄요… 다음 문장입니다.", ["글쎄요…", "다음 문장입니다."], id="unicode-ellipsis"),
    ],
)
def test_sentence_splitter_preserves_internal_periods_and_real_boundaries(
    text: str,
    expected: list[str],
) -> None:
    assert split_sentences(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("He said no. Then left.", ["He said no.", "Then left."]),
        ("결과는 no. 다음.", ["결과는 no.", "다음."]),
        ("See No. 3. Then leave.", ["See No. 3.", "Then leave."]),
        ("Meet at St. John square. Then leave.", ["Meet at St. John square.", "Then leave."]),
    ],
)
def test_l_a_ambiguous_abbreviations_only_stay_internal_with_expected_context(
    text: str, expected: list[str]
) -> None:
    assert split_sentences(text) == expected


def test_deterministic_check_keeps_grounded_decimal_version_and_date_in_one_sentence() -> None:
    source = "Orca v2.0은 2026.11.02에 증감률 3.5%와 1.2배 성장을 발표했다."
    result = _checker().check(source, source)

    assert result.sentences == [source]
    assert result.unsupported_candidates == []


def test_unsupported_rate_uses_question_mark_sentence_splitter_and_stays_bounded() -> None:
    summary = "가격은 9999원? 부산시청 7777개? 무료 증정 5555회."
    sentences = split_sentences(summary)
    unsupported, rate = unsupported_sentence_metrics(summary, [*sentences, summary], [])
    assert len(sentences) == 3
    assert unsupported == sentences
    assert rate == 1.0


def test_forbidden_claim_makes_the_whole_item_unfaithful() -> None:
    summary = "무료 증정 행사입니다. 원문 소개입니다. 원문 설명입니다."
    unsupported, rate = unsupported_sentence_metrics(summary, [], ["무료 증정"])
    assert unsupported == split_sentences(summary)
    assert rate == 1.0


def test_duplicate_unsupported_sentences_are_counted_by_position() -> None:
    summary = "부산 예산은 9999억원입니다. 부산 예산은 9999억원입니다."
    sentence = split_sentences(summary)[0]
    unsupported, rate = unsupported_sentence_metrics(summary, [sentence, sentence], [])
    assert unsupported == [sentence, sentence]
    assert rate == 1.0

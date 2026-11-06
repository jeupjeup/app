"""T2: 정규화, 자모, 토크나이저, Lexicon."""

from __future__ import annotations

import subprocess
import sys

import pytest

from jupjup.text.lexicon import Lexicon
from jupjup.text.normalize import jamo_distance, levenshtein, normalize_text, to_jamo
from jupjup.text.tokenizer import CharNgramTokenizer, KiwiTokenizer


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  성수동   카페  ", "성수동 카페"),
        ("ＡＢＣ　카페１２", "abc 카페12"),
        ("성수동 카페ㅋㅋㅋ", "성수동 카페"),
        ("좋아요!!! 카페", "좋아요 카페"),
        ("카페에에", "카페에에"),
        ("☕카페 🍰디저트", "카페 디저트"),
        ("YouTube 영상", "youtube 영상"),
        ("탭\t과\n줄바꿈", "탭 과 줄바꿈"),
        ("ㅠㅠ 슬픈 영화", "슬픈 영화"),
        ("3월~5월", "3월~5월"),
    ],
)
def test_normalize_text(raw: str, expected: str) -> None:
    assert normalize_text(raw) == expected


def test_to_jamo() -> None:
    assert to_jamo("카페") == "ㅋㅏㅍㅔ"
    assert to_jamo("값") == "ㄱㅏㅄ"
    assert to_jamo("a1카") == "a1ㅋㅏ"


@pytest.mark.parametrize(
    ("a", "b", "d"),
    [
        ("카페", "카페", 0),
        ("까페", "카페", 1),
        ("기휴변화", "기후변화", 1),
        ("유투브", "유튜브", 1),
        ("인스타그렘", "인스타그램", 1),
        ("성수동", "성수", 3),
        ("커피", "코피", 1),
        ("논문", "논물", 1),
        ("파스타", "피자", 4),
        ("숙소", "숙박", 3),
        ("abc", "abd", 1),
        ("", "카", 2),
    ],
)
def test_jamo_distance_table(a: str, b: str, d: int) -> None:
    assert jamo_distance(a, b) == d


def test_levenshtein_bounded() -> None:
    assert levenshtein("kitten", "sitting") == 3
    assert levenshtein("kitten", "sitting", max_distance=1) == 2  # 상한 넘으면 max+1
    assert levenshtein("a", "abcdef", max_distance=2) == 3


def test_ngram_seongsu_typo() -> None:
    ng = CharNgramTokenizer(2)
    assert ng.index_terms("성수동까페") == ["성수", "수동", "동까", "까페"]
    # 띄어쓰기 오류가 있어도 같은 2-gram이 나온다
    assert set(ng.index_terms("성수동 까페")) == set(ng.index_terms("성수동까페"))
    assert ng.index_terms("가") == ["가"]
    assert ng.index_terms("!!!") == []


def test_kiwi_compound_noun(kiwi: KiwiTokenizer) -> None:
    terms = kiwi.index_terms("과제에 쓰려던 기후 변화 논문")
    assert "기후" in terms and "변화" in terms and "논문" in terms
    terms2 = kiwi.index_terms("한반도 기후변화 연구")
    assert "기후변화" in terms2


def test_kiwi_synonym_canonical(kiwi: KiwiTokenizer) -> None:
    assert "카페" in kiwi.index_terms("커피숍 추천")
    assert "카페" in kiwi.index_terms("성수동까페")
    assert "숙소" in kiwi.index_terms("제주 호텔")


def test_kiwi_keyword_pos_only(kiwi: KiwiTokenizer) -> None:
    terms = kiwi.index_terms("인스타에서 봤던 거 있잖아 디저트")
    assert "디저트" in terms
    assert "거" not in terms and "있" not in terms


def test_kiwi_deterministic(kiwi: KiwiTokenizer) -> None:
    text = "지난달 인스타에서 본 성수동 카페 팡도르 신메뉴"
    assert kiwi.tokenize(text) == kiwi.tokenize(text)
    assert kiwi.index_terms(text) == kiwi.index_terms(text)


def test_kiwi_deterministic_across_processes() -> None:
    code = (
        "from pathlib import Path;from jupjup.text.lexicon import Lexicon;"
        "from jupjup.text.tokenizer import KiwiTokenizer;"
        "k=KiwiTokenizer(Lexicon.load(Path('data/lexicon')));"
        "print(k.index_terms('작년 여름에 캡처해둔 제주 숙소 기후변화 논문'))"
    )
    outs = {
        subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout
        for _ in range(2)
    }
    assert len(outs) == 1


def test_lexicon_load(lexicon: Lexicon) -> None:
    assert lexicon.platform_aliases()["유툽"] == "youtube"
    assert lexicon.platform_aliases()["ig"] == "instagram"
    assert lexicon.content_type_aliases()["캡처"] == "image"
    assert lexicon.canonical("까페") == "카페"
    assert lexicon.canonical("모르는말") == "모르는말"
    assert "커피숍" in lexicon.synonyms("카페")
    assert "그거" in lexicon.stop_phrases()
    assert lexicon.expand_content_types({"video"}) == {"video", "short_video"}
    assert lexicon.platform_label("instagram") == "인스타그램"


def test_kiwi_prefix_suffix_derivations(kiwi: KiwiTokenizer) -> None:
    assert "신메뉴" in kiwi.index_terms("어니언 성수 신메뉴")
    assert "재활용" in kiwi.index_terms("배터리 재활용")
    assert "간헐적" in kiwi.index_terms("간헐적 단식")
    assert "공정성" in kiwi.index_terms("추천 시스템 공정성")
    assert "집들" not in kiwi.index_terms("집들이 영상")


def test_predicates_indexed_as_dictionary_form(kiwi: KiwiTokenizer) -> None:
    terms = kiwi.index_terms("맛있는 조식을 고르는 법")
    assert "맛있다" in terms and "고르다" in terms
    assert "고르" not in terms  # 어간만 색인하면 '골프'가 '고르'로 잘못 교정된다

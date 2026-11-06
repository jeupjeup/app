"""T4: FacetExtractor (별칭 표 전부, hard/soft, 퍼지, 단어 경계), IntentClassifier."""

from __future__ import annotations

import pytest

from jupjup.query.facets import FacetExtractor
from jupjup.query.intent import IntentClassifier
from jupjup.text.lexicon import Lexicon
from jupjup.text.normalize import normalize_text


@pytest.fixture(scope="module")
def fx(lexicon: Lexicon) -> FacetExtractor:
    return FacetExtractor(lexicon)


def _plats(fx: FacetExtractor, text: str, hard_only: bool = True) -> list[str]:
    ext = fx.extract(normalize_text(text))
    return [h.value for h in ext.platforms if not hard_only or h.strength == "hard"]


def _types(fx: FacetExtractor, text: str, hard_only: bool = True) -> list[str]:
    ext = fx.extract(normalize_text(text))
    return [h.value for h in ext.content_types if not hard_only or h.strength == "hard"]


PLATFORM_ALIASES = {
    "instagram": ["인스타", "인스타그램", "인스타그렘", "인스터", "인별", "insta", "ig", "instagram", "릴스"],
    "youtube": ["유튜브", "유투브", "유튭", "유툽", "윹", "yt", "youtube", "쇼츠"],
    "kakaotalk": ["카톡", "카카오톡", "단톡", "단톡방", "kakao"],
    "news": ["기사", "뉴스", "신문"],
    "x": ["트위터", "트윗", "엑스"],
    "blog": ["블로그", "네이버 블로그", "티스토리", "브런치"],
    "web": ["웹", "사이트", "홈페이지"],
}


@pytest.mark.parametrize(("alias", "value"), [(a, v) for v, al in PLATFORM_ALIASES.items() for a in al])
def test_platform_alias_table_hard_with_particle(fx: FacetExtractor, alias: str, value: str) -> None:
    assert _plats(fx, f"{alias}에서 본 레시피") == [value]


def test_platform_tok_euro(fx: FacetExtractor) -> None:
    assert _plats(fx, "톡으로 받은 주소") == ["kakaotalk"]


TYPE_ALIASES = {
    "paper": ["논문", "페이퍼", "paper", "학술", "저널"],
    "video": ["영상", "동영상", "비디오"],
    "short_video": ["릴스", "쇼츠", "숏폼"],
    "image": ["캡처", "캡쳐", "스샷", "스크린샷"],
    "article": ["기사", "아티클"],
    "message": ["메시지", "메세지"],
    "post": ["게시물", "피드", "포스트"],
}


@pytest.mark.parametrize(("alias", "value"), [(a, v) for v, al in TYPE_ALIASES.items() for a in al])
def test_type_alias_table(fx: FacetExtractor, alias: str, value: str) -> None:
    assert value in _types(fx, f"기후 {alias}")


@pytest.mark.parametrize("alias", ["사진", "이미지", "짤", "글", "포스팅", "대화", "톡"])
def test_broad_type_aliases_soft_only(fx: FacetExtractor, alias: str) -> None:
    assert _types(fx, f"제주 {alias}") == []
    assert _types(fx, f"제주 {alias}", hard_only=False) != []


def test_modifier_platform_is_soft(fx: FacetExtractor) -> None:
    ext = fx.extract("인스타 감성 카페")
    assert [(h.value, h.strength) for h in ext.platforms] == [("instagram", "soft")]


@pytest.mark.parametrize(
    "text", ["인스타에서 본 카페", "인스타로 공유한 카페", "인스타에 올라온 카페", "인스타 본 카페", "성수 카페 인스타"]
)
def test_platform_hard_contexts(fx: FacetExtractor, text: str) -> None:
    assert _plats(fx, text) == ["instagram"]


def test_english_word_boundary(fx: FacetExtractor) -> None:
    assert _plats(fx, "big data 강의", hard_only=False) == []
    assert _plats(fx, "ig에서 본 카페") == ["instagram"]
    assert _plats(fx, "youtube에서 본 영상") == ["youtube"]
    assert _plats(fx, "ytn 뉴스", hard_only=False) == ["news"]


def test_korean_word_start_only(fx: FacetExtractor) -> None:
    # '구글'의 '글', '글램핑'의 '글', '카톡'의 '톡'은 유형으로 잡지 않는다
    assert _types(fx, "구글 지도", hard_only=False) == []
    assert _types(fx, "글램핑 장소", hard_only=False) == []
    assert _types(fx, "카톡으로 받은", hard_only=False) == []


def test_fuzzy_alias_three_chars(fx: FacetExtractor) -> None:
    assert _plats(fx, "인스타그렘에서 본") == ["instagram"]
    assert _plats(fx, "유트브에서 본") == ["youtube"]  # 유튜브와 자모 거리 1
    assert _plats(fx, "카톡에서", hard_only=False) == ["kakaotalk"]
    # 2자 별칭은 퍼지 불허: '카툭'은 카톡이 아니다
    assert _plats(fx, "카툭에서 본", hard_only=False) == []


def test_news_is_platform_and_type(fx: FacetExtractor) -> None:
    assert _plats(fx, "기후변화 기사") == ["news"]
    assert _types(fx, "기후변화 기사") == ["article"]
    assert _plats(fx, "기사로 본 폭염") == ["news"]


def test_reels_shorts_both(fx: FacetExtractor) -> None:
    assert _plats(fx, "릴스로 본 레시피") == ["instagram"]
    assert _types(fx, "릴스로 본 레시피") == ["short_video"]
    assert _plats(fx, "쇼츠에서 본") == ["youtube"]
    assert _types(fx, "쇼츠에서 본") == ["short_video"]


def test_capture_with_verbal_suffix(fx: FacetExtractor) -> None:
    assert _types(fx, "캡처해둔 제주 숙소") == ["image"]
    assert _types(fx, "캡쳐한 거") == ["image"]


def test_type_modifier_soft(fx: FacetExtractor) -> None:
    ext = fx.extract("논문 요약 정리")
    assert [(h.value, h.strength) for h in ext.content_types] == [("paper", "soft")]


def test_spans_include_particle(fx: FacetExtractor) -> None:
    text = "지난달 인스타에서 본 성수동 카페"
    ext = fx.extract(text)
    assert [text[s.start : s.end] for s in ext.spans] == ["인스타에서"]


def test_multiword_alias(fx: FacetExtractor) -> None:
    text = "네이버 블로그에서 본 맛집"
    ext = fx.extract(text)
    assert [h.value for h in ext.platforms] == ["blog"]
    assert text[ext.spans[0].start : ext.spans[0].end] == "네이버 블로그에서"


def test_dedupe_hard_wins(fx: FacetExtractor) -> None:
    ext = fx.extract("인스타 감성 카페 인스타에서 본")
    assert [(h.value, h.strength) for h in ext.platforms] == [("instagram", "hard")]


@pytest.fixture(scope="module")
def intent(lexicon: Lexicon) -> IntentClassifier:
    return IntentClassifier(lexicon)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("까페 추천 저장한 거 다 보여줘", "browse"),
        ("성수동 카페 전부", "browse"),
        ("레시피 모두 보여줘", "browse"),
        ("논문 목록", "browse"),
        ("제주 숙소 리스트", "browse"),
        ("저장한 카페들", "browse"),
        ("여행 사진 모아줘", "browse"),
        ("유툽에서 본 파스타 레시피 그거", "lookup"),
        ("과제에 쓰려던 기후변화 논문", "lookup"),
        ("다이어트 식단", "lookup"),
        ("케이크 만들기", "lookup"),
        ("그때 저장한 그 카페", "lookup"),
    ],
)
def test_intent(intent: IntentClassifier, text: str, expected: str) -> None:
    assert intent.classify(text) == expected


def test_deictic(intent: IntentClassifier) -> None:
    assert intent.has_deictic("그거 뭐였지")
    assert not intent.has_deictic("성수동 카페")


def test_platform_followed_by_type_word_with_particle(fx: FacetExtractor) -> None:
    assert _plats(fx, "인스타 피드에서 본 네일") == ["instagram"]
    assert _types(fx, "인스타 피드에서 본 네일") == ["post"]

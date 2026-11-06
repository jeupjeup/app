"""T3: TemporalParser — 설계서 5.2절 규칙 표 전 행, 경계, 미래 표현, window."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from jupjup.query.temporal import TemporalParser, TimeRange
from tests.conftest import KST, NOW

P = TemporalParser()


def at(y: int, m: int, d: int, h: int = 12) -> datetime:
    return datetime(y, m, d, h, tzinfo=KST)


def D(s: str) -> date:
    return date.fromisoformat(s)


# (행 이름, 텍스트, now, start, end)
CASES: list[tuple[str, str, datetime, str, str]] = [
    # 오늘 / 어제 / 그저께(그제)
    ("day_word", "오늘 저장한 거", NOW, "2026-10-15", "2026-10-16"),
    ("day_word", "어제 본 카페", NOW, "2026-10-14", "2026-10-15"),
    ("day_word", "그저께 받은 링크", NOW, "2026-10-13", "2026-10-14"),
    ("day_word", "그제", NOW, "2026-10-13", "2026-10-14"),
    ("day_word", "어제", at(2026, 1, 1), "2025-12-31", "2026-01-01"),  # 연초 경계
    ("day_word", "어제", at(2024, 3, 1), "2024-02-29", "2024-03-01"),  # 윤년
    # N일 전
    ("days_ago", "3일 전에 본", NOW, "2026-10-12", "2026-10-13"),
    ("days_ago", "이틀 전", NOW, "2026-10-13", "2026-10-14"),
    ("days_ago", "10일 전", at(2026, 3, 5), "2026-02-23", "2026-02-24"),
    ("days_ago", "하루 전", at(2025, 1, 1), "2024-12-31", "2025-01-01"),
    # 이번 주 / 지난주 / N주 전
    ("week", "이번 주", NOW, "2026-10-12", "2026-10-19"),
    ("week", "지난주에 본", NOW, "2026-10-05", "2026-10-12"),
    ("week", "저번 주", NOW, "2026-10-05", "2026-10-12"),
    ("week", "지지난주", NOW, "2026-09-28", "2026-10-05"),
    ("week", "2주 전", NOW, "2026-09-28", "2026-10-05"),
    ("week", "일주일 전", NOW, "2026-10-05", "2026-10-12"),
    ("week", "지난주", at(2026, 1, 1), "2025-12-22", "2025-12-29"),  # 연초 경계 (2026-01-01 목)
    ("week", "이번 주", at(2026, 10, 12), "2026-10-12", "2026-10-19"),  # 월요일
    ("week", "이번 주", at(2026, 10, 18), "2026-10-12", "2026-10-19"),  # 일요일
    # 이번 달 / 지난달 / N달 전
    ("month", "이번 달", NOW, "2026-10-01", "2026-11-01"),
    ("month", "지난달 인스타에서 본", NOW, "2026-09-01", "2026-10-01"),
    ("month", "저번달", NOW, "2026-09-01", "2026-10-01"),
    ("month", "두 달 전", NOW, "2026-08-01", "2026-09-01"),
    ("month", "3개월 전", NOW, "2026-07-01", "2026-08-01"),
    ("month", "지난달", at(2026, 1, 20), "2025-12-01", "2026-01-01"),  # 연말 경계
    ("month", "한 달 전", at(2024, 3, 31), "2024-02-01", "2024-03-01"),  # 월말 + 윤년
    # 최근 / 요즘 / 얼마 전
    ("recent", "최근에 본", NOW, "2026-09-15", "2026-10-16"),
    ("recent", "요즘 자주 보는", NOW, "2026-09-15", "2026-10-16"),
    ("recent", "얼마 전에 저장한", NOW, "2026-09-15", "2026-10-16"),
    ("recent", "최근", at(2024, 3, 1), "2024-01-31", "2024-03-02"),
    # 올해 / 작년 / 재작년 / N년 전
    ("year", "올해 저장한", NOW, "2026-01-01", "2027-01-01"),
    ("year", "작년에", NOW, "2025-01-01", "2026-01-01"),
    ("year", "지난해", NOW, "2025-01-01", "2026-01-01"),
    ("year", "재작년", NOW, "2024-01-01", "2025-01-01"),
    ("year", "2년 전", NOW, "2024-01-01", "2025-01-01"),
    ("year", "작년", at(2026, 1, 1), "2025-01-01", "2026-01-01"),
    # (연도) 초 / 중반 / 말
    ("part", "올해 초", NOW, "2026-01-01", "2026-04-01"),
    ("part", "작년 초에", NOW, "2025-01-01", "2025-04-01"),
    ("part", "작년 중반", NOW, "2025-05-01", "2025-09-01"),
    ("part", "작년 말", NOW, "2025-10-01", "2026-01-01"),
    ("part", "연말", NOW, "2026-10-01", "2027-01-01"),
    ("part", "올해 상반기", NOW, "2026-01-01", "2026-07-01"),
    # 계절 (+올해/작년)
    ("season", "작년 여름에 캡처한", NOW, "2025-06-01", "2025-09-01"),
    ("season", "올해 봄", NOW, "2026-03-01", "2026-06-01"),
    ("season", "작년 가을", NOW, "2025-09-01", "2025-12-01"),
    ("season", "재작년 여름", NOW, "2024-06-01", "2024-09-01"),
    # 수식어 없는 계절
    ("season_bare", "여름에", NOW, "2026-06-01", "2026-09-01"),
    ("season_bare", "가을에 본", NOW, "2026-09-01", "2026-12-01"),  # 진행 중이면 올해
    ("season_bare", "봄", NOW, "2026-03-01", "2026-06-01"),
    ("season_bare", "겨울", NOW, "2025-12-01", "2026-03-01"),
    ("season_bare", "겨울", at(2027, 1, 10), "2026-12-01", "2027-03-01"),  # 진행 중
    ("season_bare", "여름", at(2026, 5, 31), "2025-06-01", "2025-09-01"),
    # 겨울 연도 기준 (Q3)
    ("winter", "작년 겨울", NOW, "2025-12-01", "2026-03-01"),
    ("winter", "재작년 겨울", NOW, "2024-12-01", "2025-03-01"),
    ("winter", "2024년 겨울", NOW, "2024-12-01", "2025-03-01"),  # 2025-02 → 윤년 아님
    ("winter", "2023년 겨울", NOW, "2023-12-01", "2024-03-01"),  # 2024-02-29 포함
    # N월 (연도 없음)
    ("month_bare", "11월에", NOW, "2025-11-01", "2025-12-01"),
    ("month_bare", "10월", NOW, "2026-10-01", "2026-11-01"),
    ("month_bare", "3월에 본", NOW, "2026-03-01", "2026-04-01"),
    ("month_bare", "12월", at(2026, 1, 5), "2025-12-01", "2026-01-01"),
    ("month_bare", "2월", at(2024, 3, 1), "2024-02-01", "2024-03-01"),
    # YYYY년 / YYYY년 M월 / M월 D일
    ("absolute", "2025년", NOW, "2025-01-01", "2026-01-01"),
    ("absolute", "2025년 3월", NOW, "2025-03-01", "2025-04-01"),
    ("absolute", "3월 5일", NOW, "2026-03-05", "2026-03-06"),
    ("absolute", "12월 25일", NOW, "2025-12-25", "2025-12-26"),
    ("absolute", "2024년 2월 29일", NOW, "2024-02-29", "2024-03-01"),
    ("absolute", "작년 11월", NOW, "2025-11-01", "2025-12-01"),
    ("absolute", "2026.09.12", NOW, "2026-09-12", "2026-09-13"),
    ("absolute", "25년 여름", NOW, "2025-06-01", "2025-09-01"),
    # 주말
    ("weekend", "지난 주말", NOW, "2026-10-10", "2026-10-12"),
    ("weekend", "지지난 주말", NOW, "2026-10-03", "2026-10-05"),
    ("weekend", "주말에", NOW, "2026-10-10", "2026-10-12"),
    ("weekend", "이번 주말", at(2026, 10, 18), "2026-10-17", "2026-10-19"),  # 일요일이면 진행 중
    # 숫자 한글 표기
    ("hangul_num", "두 달 전", NOW, "2026-08-01", "2026-09-01"),
    ("hangul_num", "세 주 전", NOW, "2026-09-21", "2026-09-28"),
    ("hangul_num", "열 달 전", NOW, "2025-12-01", "2026-01-01"),
    ("hangul_num", "한 달 전", NOW, "2026-09-01", "2026-10-01"),
    # 범위
    ("range", "지난달부터 이번 달까지", NOW, "2026-09-01", "2026-11-01"),
    ("range", "3월~5월", NOW, "2026-03-01", "2026-06-01"),
    ("range", "작년 3월부터 5월까지", NOW, "2025-03-01", "2025-06-01"),
    ("range", "작년 11월부터 1월까지", NOW, "2025-11-01", "2026-02-01"),
    ("range", "지지난주부터 지난주까지", NOW, "2026-09-28", "2026-10-12"),
]


@pytest.mark.parametrize(("row", "text", "now", "start", "end"), CASES, ids=[f"{c[0]}:{c[1]}" for c in CASES])
def test_rule_table(row: str, text: str, now: datetime, start: str, end: str) -> None:
    ext = P.extract(text, now)
    assert ext.range is not None, ext
    assert ext.range.start == datetime.combine(D(start), datetime.min.time(), KST)
    assert ext.range.end == datetime.combine(D(end), datetime.min.time(), KST)
    assert ext.range.start.utcoffset() is not None
    assert ext.range.field == "saved_at"


def test_every_rule_row_has_two_cases() -> None:
    from collections import Counter

    # 규칙 표 16행 중 '근사 표지' 행은 test_fuzzy_markers가 따로 다룬다.
    counts = Counter(c[0] for c in CASES)
    assert len(counts) >= 15
    assert all(v >= 2 for v in counts.values()), counts
    assert len(CASES) >= 60


@pytest.mark.parametrize(
    ("text", "fuzzy"),
    [
        ("3주 전쯤", True),
        ("작년 여름 즈음", True),
        ("두 달 전 정도", True),
        ("3월경", True),
        ("대충 작년 봄", True),
        ("최근", True),
        ("지난달", False),
        ("작년 여름", False),
    ],
)
def test_fuzzy_markers(text: str, fuzzy: bool) -> None:
    ext = P.extract(text, NOW)
    assert ext.range is not None
    assert ext.range.fuzzy is fuzzy


@pytest.mark.parametrize("text", ["다음 주에", "내일", "모레", "내년", "다음 달", "3일 후", "이번 주말", "올해 겨울"])
def test_future_ignored(text: str) -> None:
    ext = P.extract(text, NOW)
    assert ext.range is None
    assert "future_time_ignored" in ext.warnings
    assert ext.spans  # 지울 span은 남긴다


@pytest.mark.parametrize(
    "text", ["성수동 카페", "다음 카페", "봄동 무침", "말차 라떼", "겨울왕국 ost", "인스타 감성", "1위 맛집"]
)
def test_no_time_expression(text: str) -> None:
    ext = P.extract(text, NOW)
    assert ext.range is None
    assert ext.spans == []


def test_spans_cover_particles() -> None:
    text = "지난달에 인스타에서 본 카페"
    ext = P.extract(text, NOW)
    assert [(s.start, s.end) for s in ext.spans] == [(0, 4)]
    assert text[ext.spans[0].start : ext.spans[0].end] == "지난달에"


def test_expression_text() -> None:
    ext = P.extract("작년 여름에 캡처해둔 제주 숙소", NOW)
    assert ext.range is not None and ext.range.expression == "작년 여름"
    assert ext.range.granularity == "season"


def test_naive_now_rejected() -> None:
    with pytest.raises(ValueError):
        P.extract("어제", datetime(2026, 10, 15, 12))


def test_now_timezone_converted() -> None:
    # UTC 2026-10-14T20:00 = KST 2026-10-15T05:00 → '어제'는 KST 기준 10-14
    from datetime import UTC

    ext = P.extract("어제", datetime(2026, 10, 14, 20, tzinfo=UTC))
    assert ext.range is not None and ext.range.start.date() == date(2026, 10, 14)


@pytest.mark.parametrize(
    ("gran", "fuzzy", "days"),
    [
        ("day", False, 1),
        ("day", True, 3),
        ("week", False, 3),
        ("week", True, 7),
        ("month", False, 7),
        ("month", True, 14),
        ("season", False, 14),
        ("season", True, 30),
        ("part_of_year", False, 14),
        ("year", False, 30),
        ("year", True, 60),
    ],
)
def test_window_margins(gran: str, fuzzy: bool, days: int) -> None:
    rng = TimeRange(start=at(2026, 9, 1, 0), end=at(2026, 10, 1, 0), granularity=gran, fuzzy=fuzzy)  # type: ignore[arg-type]
    w = TemporalParser.window(rng)
    assert (rng.start - w.start).days == days
    assert (w.end - rng.end).days == days


def test_window_custom_margins() -> None:
    rng = TimeRange(start=at(2026, 9, 1, 0), end=at(2026, 10, 1, 0), granularity="month")
    w = TemporalParser.window(rng, {"month": (2, 5)})
    assert (rng.start - w.start).days == 2


def test_multiple_expressions_warns_first_wins() -> None:
    ext = P.extract("작년 여름 그리고 지난달", NOW)
    assert ext.range is not None and ext.range.start.date() == date(2025, 6, 1)
    assert "multiple_time_expressions" in ext.warnings

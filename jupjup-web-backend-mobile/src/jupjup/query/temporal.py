"""시간 표현 해석 `TemporalParser` (설계서 5.2절 1b).

- 구간은 반열림 [start, end), 경계는 00:00 (Asia/Seoul).
- 주는 월요일에 시작한다. "작년 겨울" = 작년 12월 ~ 올해 2월 (Q3 확정).
- `now`는 호출자가 주입한다. 이 모듈은 시스템 시계를 읽지 않는다.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, field_validator

from jupjup.domain.models import require_aware
from jupjup.query.settings import DEFAULT_TIME_MARGINS

Granularity = Literal["day", "week", "month", "recent", "season", "part_of_year", "year"]
GRANULARITY_ORDER: tuple[Granularity, ...] = ("day", "week", "month", "recent", "season", "part_of_year", "year")

# 기존 import 경로를 유지하되 기본값의 소유권은 query.settings에 둔다.
DEFAULT_MARGINS = DEFAULT_TIME_MARGINS

SEOUL = ZoneInfo("Asia/Seoul")


class Span(BaseModel):
    start: int
    end: int


class TimeRange(BaseModel):
    start: datetime
    end: datetime
    granularity: Granularity = "day"
    fuzzy: bool = False
    expression: str = ""
    field: Literal["saved_at"] = "saved_at"

    @field_validator("start", "end")
    @classmethod
    def _aware(cls, v: datetime) -> datetime:
        return require_aware(v, "TimeRange 경계")

    def contains(self, dt: datetime) -> bool:
        return self.start <= dt < self.end


class TemporalExtraction(BaseModel):
    range: TimeRange | None
    spans: list[Span]
    warnings: list[str] = []


# ---------------------------------------------------------------------------
# 내부 표현

_NUM_WORDS: dict[str, int] = {
    "한": 1,
    "하나": 1,
    "두": 2,
    "둘": 2,
    "세": 3,
    "셋": 3,
    "네": 4,
    "넷": 4,
    "다섯": 5,
    "여섯": 6,
    "일곱": 7,
    "여덟": 8,
    "아홉": 9,
    "열": 10,
    "일": 1,
}
_DAY_WORDS: dict[str, int] = {
    "하루": 1,
    "이틀": 2,
    "사흘": 3,
    "나흘": 4,
    "닷새": 5,
    "엿새": 6,
    "이레": 7,
    "열흘": 10,
}
_NUM = r"(?:\d{1,3}|하나|다섯|여섯|일곱|여덟|아홉|한|두|세|네|열)"

# 시간 표현 뒤에 올 수 있는 것: 끝, 공백/구두점, 조사, 근사 표지, 범위 표지
_END = (
    r"(?=$|[\s,.!?~\-]|에|엔|의|쯤|즈음|정도|경|무렵|께|부터|까지|동안|간|에서|이|가|은|는|도|만|중|"
    r"사이|휴가|방학|여행|내내|였|이었|때)"
)
_APPROX_AFTER = re.compile(r"\s*(쯤|즈음|정도|경|무렵|께|언저리)(?=$|[\s,.!?]|에|부터|까지|의|에서|이|가|엔|인)")
_TRAIL_PARTICLE = re.compile(
    r"(에서부터|에는|에도|에서|에만|부터|까지|에|엔|동안|의|중에|중|내내|사이에)(?=$|[\s,.!?])"
)
_JOIN_GAP = re.compile(r"^\s*(부터|에서|~|-|–)\s*$")
_UNTIL = re.compile(r"\s*까지")

_YEAR_REL = r"(?P<yrel>올해|금년|이번\s*해|작년|지난해|지난\s*해|전년|재작년)"
_YEAR_AGO = r"(?P<yago>" + _NUM + r")\s*년\s*전"
_YEAR_ABS = r"(?P<yabs>\d{4}|\d{2})\s*년(?!\s*전)"
_YEAR = r"(?:" + _YEAR_REL + r"|" + _YEAR_AGO + r"|" + _YEAR_ABS + r")"
_SEASON = r"(?P<season>봄|여름|가을|겨울)"
_PART = r"(?P<part>초반|초|중반|말|연초|연말|상반기|하반기)"
_MONTH = r"(?P<mon>\d{1,2})\s*월(?:\s*(?P<day>\d{1,2})\s*일|\s*(?P<mpart>초순|초|중순|하순|말))?"

_SEASON_MONTHS = {"봄": 3, "여름": 6, "가을": 9, "겨울": 12}


@dataclass(frozen=True)
class _Hit:
    start: int
    end: int
    first: date
    last: date  # 반열림 끝 (exclusive)
    granularity: Granularity
    fuzzy: bool = False
    future: bool = False
    kind: str = ""
    year: int | None = None  # 해석된 연도 (월 단위 표현)
    month: int | None = None
    explicit_year: bool = False


def _num(s: str) -> int:
    s = s.strip()
    if s.isdigit():
        return int(s)
    return _NUM_WORDS.get(s, _DAY_WORDS.get(s, 0))


def _add_months(d: date, n: int) -> date:
    idx = d.year * 12 + (d.month - 1) + n
    return date(idx // 12, idx % 12 + 1, 1)


def _month_range(y: int, m: int) -> tuple[date, date]:
    first = date(y, m, 1)
    return first, _add_months(first, 1)


def _season_range(y: int, season: str) -> tuple[date, date]:
    m = _SEASON_MONTHS[season]
    first = date(y, m, 1)
    return first, _add_months(first, 3)


def _part_range(y: int, part: str) -> tuple[date, date]:
    if part in ("초", "초반", "연초"):
        return date(y, 1, 1), date(y, 4, 1)
    if part == "중반":
        return date(y, 5, 1), date(y, 9, 1)
    if part in ("말", "연말"):
        return date(y, 10, 1), date(y + 1, 1, 1)
    if part == "상반기":
        return date(y, 1, 1), date(y, 7, 1)
    return date(y, 7, 1), date(y + 1, 1, 1)  # 하반기


def _month_part_range(y: int, m: int, part: str) -> tuple[date, date]:
    first, nxt = _month_range(y, m)
    if part in ("초", "초순"):
        return first, date(y, m, 11)
    if part == "중순":
        return date(y, m, 11), date(y, m, 21)
    return date(y, m, 21), nxt  # 말, 하순


class TemporalParser:
    def __init__(self, tz: ZoneInfo = SEOUL) -> None:
        self.tz = tz
        self._rules: list[tuple[re.Pattern[str], Callable[[re.Match[str], date], _Hit | None]]] = [
            (re.compile(r"(?P<fut>내일|모레|내년|(?:다음|담)\s*(?:주말|주|달|해))" + _END), self._future_word),
            (re.compile(r"(?P<n>" + _NUM + r")\s*(?P<u>일|주일|주|달|개월|년)\s*(?:뒤|후)" + _END), self._future_word),
            (re.compile(r"(?P<y>\d{4})[.\-/](?P<m>\d{1,2})(?:[.\-/](?P<d>\d{1,2}))?" + _END), self._iso_date),
            (
                re.compile(_YEAR + r"(?:\s*(?:의\s*)?(?:" + _SEASON + r"|" + _PART + r"|" + _MONTH + r"))?" + _END),
                self._year_based,
            ),
            (re.compile(r"(?P<last>(?:지난|저번|이번)\s*)?" + _SEASON + _END), self._season_only),
            (re.compile(r"(?P<lastm>지난\s*)?" + _MONTH + _END), self._month_only),
            (re.compile(r"(?P<part>연초|연말|상반기|하반기)" + _END), self._part_only),
            (re.compile(r"(?P<w>오늘|금일|어제|어저께|그저께|그제|엊그제)" + _END), self._day_word),
            (re.compile(r"(?P<n>\d{1,3})\s*일\s*전" + _END), self._days_ago),
            (re.compile(r"(?P<dw>하루|이틀|사흘|나흘|닷새|엿새|이레|열흘)\s*전" + _END), self._days_ago),
            (
                re.compile(
                    r"(?P<w>이번\s*주|이번주|금주|지난\s*주|지난주|저번\s*주|저번주|지지난\s*주|지지난주)(?!말)" + _END
                ),
                self._week_word,
            ),
            (re.compile(r"(?P<n>" + _NUM + r"|일)\s*주(?:일)?\s*전" + _END), self._weeks_ago),
            (
                re.compile(
                    r"(?P<w>이번\s*달|이번달|이달|지난\s*달|지난달|저번\s*달|저번달|지지난\s*달|지지난달)" + _END
                ),
                self._month_word,
            ),
            (re.compile(r"(?P<n>" + _NUM + r")\s*(?:달|개월)\s*전" + _END), self._months_ago),
            (
                re.compile(
                    r"(?:최근|지난)\s*(?P<n>" + _NUM + r")\s*(?P<u>일|주일|주|달|개월|년)(?:\s*(?:동안|간))?" + _END
                ),
                self._rolling,
            ),
            (re.compile(r"(?P<w>최근|요즘|요새|얼마\s*전|근래|며칠\s*전)" + _END), self._recent),
            (re.compile(r"(?P<w>지난\s*|저번\s*|이번\s*|지지난\s*)?주말" + _END), self._weekend),
        ]

    # ------------------------------------------------------------------ 공개 API
    def extract(self, text: str, now: datetime) -> TemporalExtraction:
        require_aware(now, "now")
        today = now.astimezone(self.tz).date()
        hits = self._scan(text, today)
        hits = self._join_ranges(text, hits, today)
        warnings: list[str] = []
        spans = [Span(start=h.start, end=self._extend_end(text, h.end)) for h in hits]
        valid = [h for h in hits if not h.future and h.first <= today]
        if any(h.future or h.first > today for h in hits):
            warnings.append("future_time_ignored")
        if len(valid) > 1:
            warnings.append("multiple_time_expressions")
        rng = None
        if valid:
            h = valid[0]
            rng = TimeRange(
                start=self._dt(h.first),
                end=self._dt(h.last),
                granularity=h.granularity,
                fuzzy=h.fuzzy,
                expression=text[h.start : h.end].strip(),
            )
        # 근사 표지(앞쪽 '대충' 등)도 지울 span에 포함
        spans = [self._extend_start(text, s) for s in spans]
        return TemporalExtraction(range=rng, spans=spans, warnings=warnings)

    @staticmethod
    def window(rng: TimeRange, margins: Mapping[str, tuple[int, int]] | None = None) -> TimeRange:
        """hard filter용 창: [start − margin, end + margin)."""
        table = margins or DEFAULT_MARGINS
        normal, fuzzy = table.get(rng.granularity, DEFAULT_MARGINS[rng.granularity])
        m = timedelta(days=fuzzy if rng.fuzzy else normal)
        return rng.model_copy(update={"start": rng.start - m, "end": rng.end + m})

    @staticmethod
    def coarser(g: Granularity) -> Granularity:
        i = GRANULARITY_ORDER.index(g)
        return GRANULARITY_ORDER[min(i + 1, len(GRANULARITY_ORDER) - 1)]

    # ------------------------------------------------------------------ 스캔
    def _dt(self, d: date) -> datetime:
        return datetime(d.year, d.month, d.day, tzinfo=self.tz)

    def _scan(self, text: str, today: date) -> list[_Hit]:
        cands: list[_Hit] = []
        for pattern, handler in self._rules:
            for m in pattern.finditer(text):
                if m.start() > 0 and _is_word_char(text[m.start() - 1]):
                    continue  # 단어 중간에서 시작하는 매칭은 버린다 (예: '이번주' 안의 '번주')
                hit = handler(m, today)
                if hit is None:
                    continue
                cands.append(self._with_approx(text, hit))
        cands.sort(key=lambda h: (-(h.end - h.start), h.start))
        chosen: list[_Hit] = []
        for h in cands:
            if all(h.end <= c.start or h.start >= c.end for c in chosen):
                chosen.append(h)
        chosen.sort(key=lambda h: h.start)
        return chosen

    def _with_approx(self, text: str, h: _Hit) -> _Hit:
        fuzzy = h.fuzzy
        end = h.end
        m = _APPROX_AFTER.match(text, end)
        if m:
            fuzzy = True
            end = m.end()
        before = text[: h.start].rstrip()
        if before.endswith(("대충", "대략", "아마")):
            fuzzy = True
        return replace(h, fuzzy=fuzzy, end=end)

    def _extend_end(self, text: str, end: int) -> int:
        m = _TRAIL_PARTICLE.match(text, end)
        return m.end() if m else end

    def _extend_start(self, text: str, span: Span) -> Span:
        m = re.search(r"(대충|대략|아마)\s*$", text[: span.start])
        return Span(start=m.start(), end=span.end) if m else span

    def _join_ranges(self, text: str, hits: list[_Hit], today: date) -> list[_Hit]:
        """'A부터 B까지', 'A~B'를 두 구간의 합으로 묶는다."""
        out: list[_Hit] = []
        i = 0
        while i < len(hits):
            h = hits[i]
            if i + 1 < len(hits) and _JOIN_GAP.match(text[h.end : hits[i + 1].start]):
                h2 = hits[i + 1]
                if h2.kind == "month" and not h2.explicit_year and h.month is not None and h.year is not None:
                    y = h.year if h2.month is not None and h2.month >= h.month else h.year + 1
                    assert h2.month is not None
                    f2, l2 = _month_range(y, h2.month)
                    h2 = replace(h2, first=f2, last=l2, year=y, future=False)
                end = h2.end
                um = _UNTIL.match(text, end)
                if um:
                    end = um.end()
                g = max(h.granularity, h2.granularity, key=GRANULARITY_ORDER.index)
                out.append(
                    _Hit(
                        start=h.start,
                        end=end,
                        first=min(h.first, h2.first),
                        last=max(h.last, h2.last),
                        granularity=g,
                        fuzzy=h.fuzzy or h2.fuzzy,
                        future=h.future and h2.future,
                        kind="range",
                    )
                )
                i += 2
                continue
            out.append(h)
            i += 1
        return out

    # ------------------------------------------------------------------ 규칙 핸들러
    def _year_value(self, m: re.Match[str], today: date) -> int:
        if m.group("yrel"):
            w = re.sub(r"\s+", "", m.group("yrel"))
            return (
                today.year + {"올해": 0, "금년": 0, "이번해": 0, "작년": -1, "지난해": -1, "전년": -1, "재작년": -2}[w]
            )
        if m.group("yago"):
            return today.year - _num(m.group("yago"))
        v = int(m.group("yabs"))
        return v if v >= 1000 else 2000 + v

    def _year_based(self, m: re.Match[str], today: date) -> _Hit:
        y = self._year_value(m, today)
        if m.group("season"):
            first, last = _season_range(y, m.group("season"))
            g: Granularity = "season"
        elif m.group("part"):
            first, last = _part_range(y, m.group("part"))
            g = "part_of_year"
        elif m.group("mon"):
            mon = int(m.group("mon"))
            if not 1 <= mon <= 12:
                return _Hit(m.start(), m.end(), date(y, 1, 1), date(y + 1, 1, 1), "year", year=y)
            if m.group("day"):
                d = _safe_date(y, mon, int(m.group("day")))
                if d is None:
                    first, last = _month_range(y, mon)
                    g = "month"
                else:
                    first, last, g = d, d + timedelta(days=1), "day"
            elif m.group("mpart"):
                first, last = _month_part_range(y, mon, m.group("mpart"))
                g = "month"
            else:
                first, last = _month_range(y, mon)
                g = "month"
            return _Hit(m.start(), m.end(), first, last, g, kind="month", year=y, month=mon, explicit_year=True)
        else:
            first, last = date(y, 1, 1), date(y + 1, 1, 1)
            g = "year"
        return _Hit(m.start(), m.end(), first, last, g, kind="year", year=y)

    def _iso_date(self, m: re.Match[str], today: date) -> _Hit | None:
        y, mon = int(m.group("y")), int(m.group("m"))
        if not 1 <= mon <= 12:
            return None
        if m.group("d"):
            d = _safe_date(y, mon, int(m.group("d")))
            if d is None:
                return None
            return _Hit(
                m.start(), m.end(), d, d + timedelta(days=1), "day", kind="day", year=y, month=mon, explicit_year=True
            )
        first, last = _month_range(y, mon)
        return _Hit(m.start(), m.end(), first, last, "month", kind="month", year=y, month=mon, explicit_year=True)

    def _season_only(self, m: re.Match[str], today: date) -> _Hit:
        season = m.group("season")
        mod = re.sub(r"\s+", "", m.group("last") or "")
        # 시작이 today 이하인 가장 최근 해 (끝났거나 진행 중)
        y = today.year
        while _season_range(y, season)[0] > today:
            y -= 1
        if mod in ("지난", "저번"):
            first, last = _season_range(y, season)
            if first <= today < last:  # 진행 중이면 '지난'은 한 해 전
                y -= 1
        elif mod == "이번":
            y = today.year  # 아직 시작 안 했으면 미래로 처리된다
        first, last = _season_range(y, season)
        return _Hit(m.start(), m.end(), first, last, "season", kind="season")

    def _month_only(self, m: re.Match[str], today: date) -> _Hit | None:
        mon = int(m.group("mon"))
        if not 1 <= mon <= 12:
            return None
        y = today.year
        if date(y, mon, 1) > today or (m.group("lastm") and mon == today.month):
            y -= 1
        if m.group("day"):
            d = _safe_date(y, mon, int(m.group("day")))
            if d is None:
                return None
            if d > today:
                d2 = _safe_date(y - 1, mon, d.day)
                if d2 is None:
                    return None
                d = d2
            return _Hit(m.start(), m.end(), d, d + timedelta(days=1), "day", kind="day", month=mon)
        if m.group("mpart"):
            first, last = _month_part_range(y, mon, m.group("mpart"))
            if first > today:
                first, last = _month_part_range(y - 1, mon, m.group("mpart"))
            return _Hit(m.start(), m.end(), first, last, "month", kind="month", year=None, month=mon)
        first, last = _month_range(y, mon)
        # 월 단독은 명시 연도가 없지만, 범위 결합 때 연도 상속에 쓰도록 해석된 연도를 담는다.
        # 연도 없는 월: 해석된 연도를 담되 explicit_year=False (범위 결합 때 앞 표현의 연도를 상속)
        return _Hit(m.start(), m.end(), first, last, "month", kind="month", year=y, month=mon)

    def _part_only(self, m: re.Match[str], today: date) -> _Hit:
        first, last = _part_range(today.year, m.group("part"))
        return _Hit(m.start(), m.end(), first, last, "part_of_year", kind="part", year=today.year)

    def _day_word(self, m: re.Match[str], today: date) -> _Hit:
        w = m.group("w")
        back = {"오늘": 0, "금일": 0, "어제": 1, "어저께": 1, "그저께": 2, "그제": 2, "엊그제": 2}[w]
        d = today - timedelta(days=back)
        return _Hit(m.start(), m.end(), d, d + timedelta(days=1), "day", fuzzy=(w == "엊그제"), kind="day")

    def _days_ago(self, m: re.Match[str], today: date) -> _Hit:
        n = int(m.group("n")) if m.groupdict().get("n") else _DAY_WORDS[m.group("dw")]
        d = today - timedelta(days=n)
        return _Hit(m.start(), m.end(), d, d + timedelta(days=1), "day", kind="day")

    def _week_start(self, today: date, back: int) -> date:
        return today - timedelta(days=today.weekday()) - timedelta(weeks=back)

    def _week_word(self, m: re.Match[str], today: date) -> _Hit:
        w = re.sub(r"\s+", "", m.group("w"))
        back = {"이번주": 0, "금주": 0, "지난주": 1, "저번주": 1, "지지난주": 2}[w]
        s = self._week_start(today, back)
        return _Hit(m.start(), m.end(), s, s + timedelta(days=7), "week", kind="week")

    def _weeks_ago(self, m: re.Match[str], today: date) -> _Hit:
        s = self._week_start(today, _num(m.group("n")))
        return _Hit(m.start(), m.end(), s, s + timedelta(days=7), "week", kind="week")

    def _month_word(self, m: re.Match[str], today: date) -> _Hit:
        w = re.sub(r"\s+", "", m.group("w"))
        back = {"이번달": 0, "이달": 0, "지난달": 1, "저번달": 1, "지지난달": 2}[w]
        first = _add_months(date(today.year, today.month, 1), -back)
        return _Hit(m.start(), m.end(), first, _add_months(first, 1), "month", kind="month_rel")

    def _months_ago(self, m: re.Match[str], today: date) -> _Hit:
        first = _add_months(date(today.year, today.month, 1), -_num(m.group("n")))
        return _Hit(m.start(), m.end(), first, _add_months(first, 1), "month", kind="month_rel")

    def _rolling(self, m: re.Match[str], today: date) -> _Hit:
        n, unit = _num(m.group("n")), m.group("u")
        end = today + timedelta(days=1)
        g: Granularity
        if unit == "일":
            start, g = today - timedelta(days=n), "week"
        elif unit in ("주", "주일"):
            start, g = today - timedelta(weeks=n), "week"
        elif unit in ("달", "개월"):
            start, g = _shift_months_same_day(today, -n), "month"
        else:
            start, g = date(today.year - n, today.month, min(today.day, 28)), "year"
        return _Hit(m.start(), m.end(), start, end, g, kind="rolling")

    def _recent(self, m: re.Match[str], today: date) -> _Hit:
        w = re.sub(r"\s+", "", m.group("w"))
        days = 7 if w == "며칠전" else 30
        g: Granularity = "week" if w == "며칠전" else "recent"
        return _Hit(
            m.start(), m.end(), today - timedelta(days=days), today + timedelta(days=1), g, fuzzy=True, kind="recent"
        )

    def _weekend(self, m: re.Match[str], today: date) -> _Hit:
        mod = re.sub(r"\s+", "", m.group("w") or "")
        this_sat = self._week_start(today, 0) + timedelta(days=5)
        if mod == "이번":
            sat = this_sat
        elif mod in ("지난", "저번"):
            sat = this_sat - timedelta(weeks=1)
        elif mod == "지지난":
            sat = this_sat - timedelta(weeks=2)
        else:  # 수식어 없음: 시작한 가장 최근 주말
            sat = this_sat if this_sat <= today else this_sat - timedelta(weeks=1)
        return _Hit(m.start(), m.end(), sat, sat + timedelta(days=2), "week", kind="weekend")

    def _future_word(self, m: re.Match[str], today: date) -> _Hit:
        return _Hit(
            m.start(), m.end(), today + timedelta(days=1), today + timedelta(days=2), "day", future=True, kind="future"
        )


def _is_word_char(ch: str) -> bool:
    return ch.isalnum()


def _safe_date(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def _shift_months_same_day(d: date, n: int) -> date:
    first = _add_months(date(d.year, d.month, 1), n)
    last_day = (_add_months(first, 1) - timedelta(days=1)).day
    return date(first.year, first.month, min(d.day, last_day))

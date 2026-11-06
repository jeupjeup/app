# ruff: noqa: E501  (직접 쓴 한국어 원문 데이터: 줄 길이보다 문장 단위 가독성을 우선)
"""news 15건 (dev 9 / test 6). 기사체. 긴 글 3건은 long_docs의 HTML fixture."""

from __future__ import annotations

from common import rec
from long_docs import garam_heat_review, html_fixture, library_survey, nuri_bus_reform

RECORDS = [
    rec(
        "news_long_bus_reform",
        "dev",
        "누리시 시내버스 노선 개편 시민 설명 자료",
        fixture=html_fixture("long_bus_reform", nuri_bus_reform()),
        platform="news",
        content_type="article",
        tags=["누리시", "시내버스", "노선개편", "대중교통"],
        acceptable_tags=["버스노선", "배차간격", "교통정책", "급행버스", "환승"],
        entities=[("organization", "누리시"), ("organization", "누리시 교통정책과")],
        locations=[("누리시", "city"), ("누리역", "venue")],
        category="news_issue",
        intents=["정보보관"],
        acceptable_intents=["나중에읽기", "업무참고"],
        key_facts=[
            "누리시가 2027년 3월 2일부터 시내버스 노선을 전면 개편한다",
            "전체 64개 노선 가운데 11개를 없애고 급행 4개 노선을 새로 만든다",
            "평균 배차 간격을 14분에서 11분으로 줄이는 것이 목표다",
            "폐지 노선 이용객을 위해 수요응답형 버스 누리콜을 운행한다",
        ],
        forbidden=["요금 인상", "지하철 연장", "2026년 3월"],
        difficult=["long_text"],
    ),
    rec(
        "news_long_heat_review",
        "dev",
        "가람시 올여름 폭염 대응 평가 보고",
        fixture=html_fixture("long_heat_review", garam_heat_review()),
        platform="news",
        content_type="article",
        tags=["가람시", "폭염", "폭염대응", "무더위쉼터"],
        acceptable_tags=["온열질환", "기후위기", "쿨링포그", "취약계층", "그늘막"],
        entities=[("organization", "가람시"), ("organization", "가람시 재난안전대책본부")],
        locations=[("가람시", "city")],
        category="news_issue",
        intents=["나중에읽기"],
        acceptable_intents=["정보보관", "업무참고"],
        key_facts=[
            "가람시의 올여름 폭염 일수는 31일로 집계됐다",
            "온열질환자는 87명으로 지난해 112명보다 줄었다",
            "무더위쉼터를 412곳으로 늘리고 야간 쉼터 38곳을 처음 운영했다",
            "가람시는 내년에 그늘막을 120개 더 설치하겠다고 밝혔다",
        ],
        forbidden=["사망자 10명", "폭염 일수 40일", "에어컨 지원금"],
        difficult=["long_text"],
        mock_failure="max_tokens",
    ),
    rec(
        "news_long_library_survey",
        "test",
        "해온시 공공도서관 이용 실태 조사",
        fixture=html_fixture("long_library_survey", library_survey()),
        platform="news",
        content_type="article",
        tags=["해온시", "공공도서관", "이용실태조사", "독서"],
        acceptable_tags=["작은도서관", "전자책", "도서관정책", "야간개관"],
        entities=[("organization", "해온시"), ("organization", "해온시립도서관")],
        locations=[("해온시", "city")],
        category="news_issue",
        intents=["나중에읽기"],
        acceptable_intents=["정보보관", "공부자료"],
        key_facts=[
            "해온시민 2,400명을 대상으로 공공도서관 이용 실태를 조사했다",
            "지난 1년 동안 도서관을 한 번 이상 이용한 시민은 46.2%였다",
            "이용하지 않은 이유로는 시간이 없어서가 가장 많이 꼽혔다",
            "해온시는 내년부터 시립도서관 중앙관을 평일 밤 10시까지 연다",
        ],
        forbidden=["도서관 폐관", "유료화", "과반이 이용"],
        difficult=["long_text"],
    ),
    rec(
        "news_num_budget",
        "dev",
        "누리시 2027년 예산안 발표",
        text=(
            "누리시가 2027년도 예산안을 3조 4,820억 원 규모로 편성해 11월 12일 시의회에 제출했다. "
            "올해 본예산 3조 2,150억 원보다 2,670억 원(8.3%) 늘어난 규모다.\n"
            "분야별로는 사회복지가 1조 2,310억 원으로 가장 많아 전체의 35.4%를 차지했다. 교통 분야는 "
            "4,120억 원으로 올해보다 17.6% 늘었는데, 내년 3월 시내버스 노선 개편과 저상버스 96대 도입 비용이 "
            "반영됐기 때문이다. 반면 문화·관광 분야는 1,480억 원으로 2.1% 줄었다.\n"
            "시는 지방채 발행을 600억 원으로 묶어 채무 비율을 9.8%로 유지하겠다고 밝혔다. 예산안은 시의회 "
            "상임위원회 심사를 거쳐 12월 16일 본회의에서 확정된다."
        ),
        platform="news",
        content_type="article",
        tags=["누리시", "예산안", "2027년예산", "시의회"],
        acceptable_tags=["사회복지예산", "교통예산", "지방채", "저상버스", "재정"],
        entities=[("organization", "누리시"), ("organization", "시의회")],
        locations=[("누리시", "city")],
        category="news_issue",
        intents=["정보보관"],
        acceptable_intents=["나중에읽기"],
        key_facts=[
            "누리시의 2027년 예산안은 3조 4,820억 원으로 올해보다 8.3% 많다",
            "사회복지 예산이 1조 2,310억 원으로 전체의 35.4%다",
            "교통 예산은 4,120억 원으로 17.6% 늘었고 문화·관광은 2.1% 줄었다",
            "예산안은 12월 16일 본회의에서 확정된다",
        ],
        forbidden=["3조 2,150억 원으로 편성", "채무 비율 12%", "11월 16일"],
        difficult=["number_date_dense"],
    ),
    rec(
        "news_num_employment",
        "test",
        "한빛도 3분기 고용 동향",
        text=(
            "한빛도 통계담당관실이 10월 22일 내놓은 3분기 고용 동향에 따르면 도내 취업자는 182만 4천 명으로 "
            "1년 전보다 2만 1천 명 늘었다. 고용률은 63.7%로 0.6%포인트 올랐고, 실업률은 3.1%로 0.4%포인트 내렸다.\n"
            "연령별로는 60세 이상 취업자가 3만 8천 명 늘어난 반면 15~29세 청년층은 1만 2천 명 줄어 대조를 보였다. "
            "청년 고용률은 41.9%로 2분기보다 1.3%포인트 떨어졌다. 산업별로는 보건·사회복지 서비스업이 9천 명, "
            "숙박·음식점업이 6천 명 늘었고 제조업은 1만 5천 명 감소했다.\n"
            "도는 청년 일자리 대책으로 내년 1월부터 지역 중소기업 인턴 1,200명을 선발해 6개월간 월 220만 원을 "
            "지원할 계획이다."
        ),
        platform="news",
        content_type="article",
        tags=["한빛도", "고용동향", "청년고용", "실업률"],
        acceptable_tags=["취업자수", "고용률", "청년인턴", "통계"],
        entities=[("organization", "한빛도"), ("organization", "한빛도 통계담당관실")],
        locations=[("한빛도", "city")],
        category="news_issue",
        intents=["정보보관"],
        acceptable_intents=["나중에읽기", "업무참고"],
        key_facts=[
            "한빛도 3분기 취업자는 182만 4천 명으로 1년 새 2만 1천 명 늘었다",
            "고용률은 63.7%, 실업률은 3.1%였다",
            "60세 이상 취업자는 3만 8천 명 늘고 15~29세는 1만 2천 명 줄었다",
            "내년 1월부터 청년 인턴 1,200명에게 6개월간 월 220만 원을 지원한다",
        ],
        forbidden=["실업률 3.5%", "청년 취업자 증가", "2,200명"],
        difficult=["number_date_dense"],
    ),
    rec(
        "news_num_housing_lottery",
        "dev",
        "누리 하늘채움 청약 일정",
        text=(
            "누리시 동림지구에 들어서는 공공분양 아파트 '누리 하늘채움'이 12월 9일 입주자 모집 공고를 내고 청약 "
            "절차에 들어간다. 총 1,146가구 가운데 일반 공급은 412가구이며 나머지는 특별 공급이다.\n"
            "특별 공급 청약은 12월 18일, 일반 공급 1순위는 12월 19일, 2순위는 12월 20일에 받는다. 당첨자는 "
            "12월 31일 발표하고 계약은 내년 1월 13일부터 15일까지 사흘간 진행한다. 전용면적은 59㎡와 74㎡ "
            "두 가지이며 분양가는 59㎡가 3억 8,900만 원, 74㎡가 4억 7,200만 원부터 시작한다.\n"
            "입주는 2029년 6월 예정이다. 단지에서 누리역까지는 걸어서 12분 거리로, 시는 단지 앞에 마을버스 정류장을 새로 만들 계획이다."
        ),
        platform="news",
        content_type="article",
        tags=["누리하늘채움", "청약", "공공분양", "동림지구"],
        acceptable_tags=["아파트분양", "입주자모집", "분양가", "누리시", "특별공급"],
        entities=[("other", "누리 하늘채움"), ("place", "동림지구"), ("place", "누리역")],
        locations=[("누리시", "city"), ("동림지구", "district")],
        category="finance",
        intents=["정보보관"],
        acceptable_intents=["구매검토"],
        key_facts=[
            "동림지구 공공분양 아파트 누리 하늘채움 1,146가구 중 412가구가 일반 공급이다",
            "일반 공급 1순위 청약은 12월 19일이고 당첨자는 12월 31일에 발표한다",
            "분양가는 59㎡가 3억 8,900만 원부터, 74㎡가 4억 7,200만 원부터다",
            "입주는 2029년 6월로 예정돼 있다",
        ],
        forbidden=["84㎡", "2028년 입주", "1순위 12월 18일"],
        difficult=["number_date_dense"],
    ),
    rec(
        "news_english_battery",
        "test",
        "Korean startup Volta Grain raises funding for sodium batteries",
        text=(
            "Volta Grain, a battery startup based in Daejeon, said on Tuesday it had raised 38 billion won in a "
            "Series B round led by Harbor Bridge Ventures. The company makes sodium-ion cells for home energy "
            "storage, which it says are cheaper and less prone to fire than lithium-ion packs.\n"
            "Chief executive Dana Seo said the money would go toward a pilot production line in Sejong that should "
            "start running in the second half of next year with an annual capacity of 200 megawatt-hours. "
            "Sodium-ion cells still store less energy for their weight, so Volta Grain is targeting stationary "
            "storage rather than electric cars.\n"
            "대전에 본사를 둔 이 회사는 내년 하반기 세종 시험 생산 라인 가동을 목표로 한다."
        ),
        platform="news",
        content_type="article",
        tags=["Volta Grain", "나트륨이온배터리", "투자유치", "스타트업"],
        acceptable_tags=["시리즈B", "에너지저장장치", "배터리", "Harbor Bridge Ventures", "ESS"],
        entities=[
            ("organization", "Volta Grain"),
            ("organization", "Harbor Bridge Ventures"),
            ("person", "Dana Seo"),
        ],
        locations=[("대전", "city"), ("세종", "city")],
        category="tech",
        intents=["나중에읽기"],
        acceptable_intents=["정보보관", "업무참고"],
        key_facts=[
            "대전의 배터리 스타트업 Volta Grain이 시리즈 B 투자를 유치했다",
            "투자는 Harbor Bridge Ventures가 이끌었고 규모는 38 billion won이다",
            "가정용 에너지 저장에 쓰는 나트륨이온 전지를 만든다",
            "내년 하반기 세종에서 연 200메가와트시 규모 시험 생산 라인을 돌린다",
        ],
        forbidden=["전기차용", "리튬", "상장"],
        difficult=["mostly_english"],
    ),
    rec(
        "news_light_festival",
        "dev",
        "누리천 겨울빛 축제 개막",
        text=(
            "누리시 대표 겨울 행사인 '누리천 겨울빛 축제'가 12월 13일 개막해 내년 1월 26일까지 이어진다. "
            "올해는 누리천 산책로 1.8km 구간에 조형물 40여 점이 설치되며, 매일 오후 5시 30분부터 밤 10시까지 불을 밝힌다.\n"
            "올해 주제는 '별을 줍는 강'이다. 지역 고등학생 300명이 그린 별 그림을 빛 조형물로 바꾼 '모두의 별자리' "
            "구간이 처음 선보인다. 금·토요일 저녁 7시에는 수상 불꽃쇼도 열린다.\n"
            "입장은 무료이며, 축제 기간 누리천 공영주차장은 혼잡이 예상돼 시는 대중교통 이용을 당부했다. "
            "작년 축제에는 52만 명이 다녀갔다."
        ),
        platform="news",
        content_type="article",
        tags=["누리천겨울빛축제", "빛축제", "겨울축제", "누리시"],
        acceptable_tags=["불꽃쇼", "야경", "무료축제", "데이트코스", "누리천"],
        entities=[("event", "누리천 겨울빛 축제"), ("place", "누리천")],
        locations=[("누리시", "city"), ("누리천", "venue")],
        category="culture_media",
        intents=["방문예정"],
        acceptable_intents=["정보보관"],
        key_facts=[
            "누리천 겨울빛 축제가 12월 13일부터 1월 26일까지 열린다",
            "누리천 산책로 1.8km에 조형물 40여 점을 세우고 오후 5시 30분부터 밤 10시까지 불을 켠다",
            "금요일과 토요일 저녁 7시에 수상 불꽃쇼를 한다",
            "입장료는 없다",
        ],
        forbidden=["유료 입장", "드론쇼", "주차 무료"],  # T25p: '입장료'는 key_fact와 겹쳤다
    ),
    rec(
        "news_cold_wave",
        "test",
        "중부 지방 한파 특보, 수도관 동파 주의",
        text=(
            "기상청은 17일 밤 9시를 기해 경기 북부와 강원 내륙에 한파경보를, 서울과 인천에는 한파주의보를 내렸다. "
            "18일 아침 최저기온은 철원 영하 18도, 서울 영하 12도까지 떨어지겠고, 바람이 강해 체감온도는 "
            "이보다 5도 이상 낮겠다.\n"
            "추위는 주말인 20일 오후부터 차츰 풀릴 전망이다. 기상청은 수도 계량기를 헌 옷이나 보온재로 감싸고, "
            "외출할 때는 수도꼭지를 조금 열어 물이 흐르게 두라고 당부했다. 동파가 생기면 뜨거운 물을 바로 붓지 말고 "
            "미지근한 물이나 헤어드라이어로 천천히 녹여야 배관이 터지지 않는다."
        ),
        platform="news",
        content_type="article",
        tags=["한파", "한파특보", "동파", "날씨"],
        acceptable_tags=["한파경보", "체감온도", "수도계량기", "겨울"],
        entities=[("organization", "기상청")],
        locations=[("경기 북부", None), ("강원", None), ("서울", "city"), ("인천", "city"), ("철원", None)],
        category="news_issue",
        intents=["정보보관"],
        acceptable_intents=["기타"],
        key_facts=[
            "경기 북부와 강원 내륙에 한파경보, 서울과 인천에 한파주의보가 내려졌다",
            "18일 아침 철원은 영하 18도, 서울은 영하 12도까지 내려간다",
            "추위는 20일 오후부터 누그러진다",
            "얼어붙은 수도관은 뜨거운 물 대신 미지근한 물이나 드라이어로 녹여야 한다",
        ],
        forbidden=["폭설", "영하 20도", "휴교"],
        mock_failure="empty_response",
    ),
    rec(
        "news_ai_tutor_pilot",
        "dev",
        "한빛도교육청 AI 튜터 시범 운영",
        text=(
            "한빛도교육청이 내년 3월부터 중학교 20곳에서 수학 과목 'AI 튜터' 시범 사업을 한다고 밝혔다. 학생이 "
            "푼 문제의 풀이 과정을 분석해 틀린 단계를 짚어 주고 비슷한 유형의 문제를 추천하는 방식이다.\n"
            "교육청은 학생 개인정보를 보호하기 위해 학습 기록을 학교 밖 서버로 보내지 않고 교육청 자체 서버에만 "
            "저장하기로 했다. 교사는 학급 전체의 오답 경향을 대시보드로 볼 수 있다.\n"
            "다만 일부 교원 단체는 기기 사용 시간이 늘어 학생 집중력이 떨어질 수 있다며 수업 시간 중 사용을 "
            "하루 20분 이내로 제한해야 한다고 요구했다. 교육청은 1학기 운영 결과를 7월에 공개하고 확대 여부를 정할 방침이다."
        ),
        platform="news",
        content_type="article",
        tags=["AI튜터", "한빛도교육청", "에듀테크", "시범사업"],
        acceptable_tags=["수학교육", "중학교", "개인정보보호", "디지털교육"],
        entities=[("organization", "한빛도교육청")],
        locations=[("한빛도", "city")],
        category="tech",
        intents=["나중에읽기"],
        acceptable_intents=["정보보관", "업무참고"],
        key_facts=[
            "한빛도교육청이 내년 3월 중학교 20곳에서 수학 AI 튜터를 시범 운영한다",
            "풀이 과정을 분석해 틀린 단계를 알려 주고 비슷한 문제를 추천한다",
            "학습 기록은 교육청 자체 서버에만 저장한다",
            "1학기 결과는 7월에 공개하고 확대 여부를 정한다",
        ],
        forbidden=["고등학교", "영어 과목", "전면 도입"],
    ),
    rec(
        "news_flu_vaccine",
        "test",
        "누리시 독감 무료 접종 대상 확대",
        text=(
            "누리시 보건소는 이번 겨울 인플루엔자(독감) 무료 예방접종 대상을 기존 65세 이상에서 60세 이상으로 넓힌다고 "
            "밝혔다. 생후 6개월~13세 어린이와 임신부는 지금처럼 무료로 맞을 수 있다.\n"
            "접종은 보건소와 지정 병·의원 132곳에서 내년 4월 30일까지 받을 수 있으며, 60~64세는 12월 2일부터 "
            "접종이 시작된다. 신분증을 꼭 챙겨야 하고, 지정 의료기관 목록은 시 누리집에서 확인할 수 있다.\n"
            '보건소 관계자는 "백신 효과가 나타나기까지 약 2주가 걸리니 유행이 커지기 전에 맞는 것이 좋다"고 말했다.'
        ),
        platform="news",
        content_type="article",
        tags=["독감예방접종", "무료접종", "누리시보건소", "인플루엔자"],
        acceptable_tags=["독감", "백신", "60세이상", "건강"],
        entities=[("organization", "누리시 보건소")],
        locations=[("누리시", "city")],
        category="health_fitness",
        intents=["정보보관"],
        acceptable_intents=["기타"],
        key_facts=[
            "누리시가 독감 무료 접종 연령을 65세 이상에서 60세 이상으로 낮췄다",
            "60~64세 접종은 12월 2일부터 시작한다",
            "보건소와 지정 병의원 132곳에서 4월 30일까지 맞을 수 있다",
            "백신 효과가 생기기까지 약 2주가 걸린다",
        ],
        forbidden=["코로나", "50세 이상", "유료"],
    ),
    rec(
        "news_half_marathon_roads",
        "dev",
        "누리 하프마라톤 당일 교통 통제",
        text=(
            "11월 22일 일요일 열리는 '2026 누리 하프마라톤' 때문에 당일 오전 7시부터 낮 12시 30분까지 누리시청 "
            "일대 도로가 구간별로 통제된다. 대회에는 하프 코스 4,500명, 10km 코스 3,500명 등 8,000명이 참가한다.\n"
            "출발점인 시청 앞 광장 주변 중앙로는 오전 7시부터 9시 30분까지 전면 통제되고, 강변북길은 선두 주자가 "
            "지난 뒤 순차적으로 풀린다. 이 시간 시내버스 23개 노선이 우회 운행한다.\n"
            "시는 통제 구간 안내 문자를 미리 보내고 주요 교차로에 경찰과 자원봉사자 400여 명을 배치할 예정이다."
        ),
        platform="news",
        content_type="article",
        tags=["누리하프마라톤", "교통통제", "누리시", "마라톤"],
        acceptable_tags=["도로통제", "버스우회", "마라톤대회", "중앙로"],
        entities=[("event", "2026 누리 하프마라톤"), ("place", "누리시청"), ("place", "중앙로"), ("place", "강변북길")],
        locations=[("누리시", "city"), ("중앙로", "venue"), ("강변북길", "venue")],
        category="news_issue",
        intents=["정보보관"],
        acceptable_intents=["기타"],
        key_facts=[
            "11월 22일 누리 하프마라톤으로 오전 7시부터 12시 30분까지 시청 일대 도로를 막는다",
            "하프 4,500명과 10km 3,500명을 합쳐 8,000명이 뛴다",
            "중앙로는 오전 7시부터 9시 30분까지 완전히 통제된다",
            "시내버스 23개 노선이 돌아서 운행한다",
        ],
        forbidden=["풀코스", "지하철 무료", "토요일"],
    ),
    rec(
        "news_padding_label",
        "test",
        "패딩 충전재 표시와 실제 함량 달라",
        text=(
            "한국소비생활연구원이 온라인에서 팔리는 겨울 패딩 30개 제품을 조사한 결과, 7개 제품의 거위털·오리털 "
            "함량이 표시보다 낮은 것으로 나타났다. 특히 '구스다운 90%'로 표시한 한 제품은 실제 솜털 비율이 62%에 "
            "그쳤다.\n"
            "연구원은 7개 업체에 표시를 고치고 판매 페이지를 수정하라고 권고했으며, 이 가운데 5곳은 이미 해당 제품의 "
            "판매를 멈췄다. 소비자는 구매 전 '솜털 대 깃털' 비율과 충전재 무게(필파워)를 함께 확인하는 것이 좋다고 "
            "연구원은 설명했다."
        ),
        platform="news",
        content_type="article",
        tags=["패딩", "충전재", "소비자조사", "표시위반"],
        acceptable_tags=["구스다운", "오리털", "겨울옷", "한국소비생활연구원", "필파워"],
        entities=[("organization", "한국소비생활연구원")],
        category="shopping",
        intents=["구매검토"],
        acceptable_intents=["정보보관"],
        key_facts=[
            "온라인 판매 패딩 30개 중 7개의 털 함량이 표시보다 낮았다",
            "구스다운 90%라고 적은 제품의 실제 솜털 비율은 62%였다",
            "7개 업체에 시정을 권고했고 5곳은 판매를 중단했다",
        ],
        forbidden=["리콜", "환불", "과징금"],
    ),
    rec(
        "news_volleyball",
        "dev",
        "누리 썬더스, 홈 개막 3연승",
        text=(
            "프로배구 누리 썬더스가 16일 누리실내체육관에서 열린 홈 경기에서 해안 블루웨일즈를 세트 점수 3-1로 꺾고 "
            "시즌 3연승을 달렸다. 주포 강민혁이 서브 득점 4개를 포함해 27점을 올렸고, 세터 이도겸은 안정적인 토스로 "
            "공격을 이끌었다.\n"
            "썬더스는 첫 세트를 23-25로 내줬지만 2세트부터 블로킹이 살아나며 경기를 뒤집었다. 이날 체육관에는 "
            "3,812명이 입장했다. 썬더스는 20일 원정에서 리그 1위 팀과 맞붙는다."
        ),
        platform="news",
        content_type="article",
        tags=["누리썬더스", "프로배구", "3연승", "강민혁"],
        acceptable_tags=["배구", "해안블루웨일즈", "이도겸", "홈경기"],
        entities=[
            ("organization", "누리 썬더스"),
            ("organization", "해안 블루웨일즈"),
            ("person", "강민혁"),
            ("person", "이도겸"),
            ("place", "누리실내체육관"),
        ],
        locations=[("누리실내체육관", "venue")],
        category="other",
        intents=["정보보관"],
        acceptable_intents=["기타", "나중에읽기"],
        key_facts=[
            "누리 썬더스가 해안 블루웨일즈를 3-1로 이기고 3연승했다",
            "강민혁이 서브 득점 4개를 포함해 27점을 냈다",
            "첫 세트를 23-25로 졌다가 2세트부터 뒤집었다",
        ],
        forbidden=["3-0", "4연승", "1위로 올라"],
    ),
    rec(
        "news_seaweed_plastic",
        "dev",
        "해조류로 만든 생분해 포장재 개발",
        text=(
            "해온대학교 신소재공학과 문채윤 교수 연구팀이 미역 줄기 부산물로 바닷물에서 분해되는 포장 필름을 "
            "만들었다고 밝혔다. 연구 결과는 국제 학술지 '그린 머티리얼즈' 12월호에 실렸다.\n"
            "연구팀이 만든 필름은 바닷물에 넣으면 8주 만에 무게의 90% 이상이 분해됐다. 일반 비닐 수준의 인장 강도를 "
            "냈지만, 물에 오래 닿으면 쉽게 흐물흐물해져 아직 음료 포장에는 쓰기 어렵다고 연구팀은 설명했다. "
            "연구팀은 김 양식장에서 버려지는 부산물로도 같은 실험을 진행하고 있다."
        ),
        platform="news",
        content_type="article",
        tags=["생분해포장재", "해조류", "미역", "신소재"],
        acceptable_tags=["친환경", "해온대학교", "플라스틱대체", "연구성과"],
        entities=[
            ("organization", "해온대학교"),
            ("person", "문채윤"),
            ("work", "그린 머티리얼즈"),
        ],
        category="study_research",
        intents=["나중에읽기"],
        acceptable_intents=["공부자료", "정보보관"],
        key_facts=[
            "해온대학교 문채윤 교수팀이 미역 줄기 부산물로 바다에서 분해되는 포장 필름을 만들었다",
            "필름은 바닷물에서 8주 만에 90% 넘게 분해됐다",
            "물에 오래 닿으면 약해져 음료 포장에는 아직 쓰기 어렵다",
        ],
        forbidden=["상용화", "음료 포장에 적용", "4주"],
    ),
]

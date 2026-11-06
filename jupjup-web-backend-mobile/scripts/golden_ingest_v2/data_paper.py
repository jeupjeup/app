"""paper 10건 (dev 6 / test 4). 초록 + 본문 일부. 저자·기관·학술지는 모두 지어낸 이름이다."""

from __future__ import annotations

from common import rec
from long_docs import html_fixture, receipt_ocr_paper

PAPER = {"platform": "web", "content_type": "paper"}

RECORDS = [
    rec(
        "paper_long_receipt_ocr",
        "dev",
        "저조도 영수증 사진의 한국어 OCR 오류 유형 분석",
        fixture=html_fixture("long_receipt_ocr", receipt_ocr_paper()),
        **PAPER,
        tags=["OCR", "영수증", "오류분석", "한국어인식"],
        acceptable_tags=["광학문자인식", "저조도", "이미지전처리", "문자인식"],
        entities=[("organization", "가람대학교"), ("person", "정하율")],
        category="study_research",
        intents=["공부자료"],
        acceptable_intents=["업무참고", "나중에읽기"],
        key_facts=[
            "어두운 곳에서 찍은 영수증 사진 3,200장으로 한국어 OCR 오류를 분석했다",
            "오류의 41%가 금액과 날짜 같은 숫자에서 나왔다",
            "밝기 보정과 기울기 보정을 함께 하면 문자 오류율이 18.4%에서 9.7%로 내려갔다",
            "받침이 있는 글자를 받침 없는 글자로 읽는 오류가 한글 오류 중 가장 많았다",
        ],
        forbidden=["딥러닝 모델을 새로 학습", "외국어 영수증", "오류율 5%"],
        difficult=["long_text"],
    ),
    rec(
        "paper_en_hybrid_retrieval",
        "dev",
        "Hybrid Sparse-Dense Retrieval for Short Korean Social Posts",
        text=(
            "Abstract\n"
            "Short social media posts are hard to retrieve because they mix slang, hashtags, and English loanwords. "
            "We compare BM25, a multilingual dense retriever, and a simple hybrid that fuses both rankings with "
            "reciprocal rank fusion. On KoSnap-1k, a new test set of 1,000 Korean posts and 300 natural-language "
            "queries written by 12 annotators, the hybrid reaches a Recall@10 of 0.81, compared with 0.64 for BM25 "
            "and 0.72 for the dense model alone. Most remaining errors involve queries that describe a photo rather "
            "than the caption text.\n\n"
            "1 Introduction (excerpt)\n"
            "People save posts in order to find them later, yet they rarely remember the exact words. "
            "Our goal is a retrieval setup that runs on a single laptop without sending any user text to a server.\n\n"
            "Keywords: information retrieval, Korean NLP, hybrid search\n"
            "(저자: Jiwoo Han, Peter Lindqvist / Seoul Lakeside University)"
        ),
        **PAPER,
        tags=["하이브리드검색", "정보검색", "BM25", "한국어"],
        acceptable_tags=["RRF", "Recall@10", "KoSnap-1k", "자연어처리", "dense retrieval"],
        entities=[
            ("other", "KoSnap-1k"),
            ("person", "Jiwoo Han"),
            ("person", "Peter Lindqvist"),
            ("organization", "Seoul Lakeside University"),
        ],
        category="study_research",
        intents=["공부자료"],
        acceptable_intents=["업무참고"],
        key_facts=[
            "짧은 한국어 SNS 게시물 검색에서 BM25, dense 검색, 둘을 RRF로 합친 hybrid를 비교했다",
            "KoSnap-1k는 게시물 1,000건과 질의 300개로 이뤄진 평가 세트다",
            "hybrid의 Recall@10은 0.81로 BM25 0.64와 dense 0.72보다 높았다",
            "남은 오류는 주로 캡션이 아니라 사진 내용을 묘사한 질의에서 나왔다",
        ],
        forbidden=["0.91", "GPU 서버", "영어 게시물"],
        difficult=["mostly_english"],
    ),
    rec(
        "paper_en_screen_sleep",
        "test",
        "Evening Screen Use and Sleep Onset in University Students",
        text=(
            "Abstract\n"
            "We followed 214 undergraduate students at Haeon National University for 28 nights using wrist-worn "
            "sleep trackers and a daily phone-use diary. Students who used a phone in bed for more than 60 minutes "
            "fell asleep on average 23 minutes later than those who used it for less than 15 minutes. "
            "The effect was smaller on nights when night mode was enabled, but it did not disappear. "
            "Total sleep time on weekdays was 6 hours 12 minutes across the whole sample. "
            "Because this is an observational study, we cannot claim that screen use causes later sleep onset.\n\n"
            "Discussion (excerpt)\n"
            "A practical message for students is to leave the phone outside the bed rather than relying on display "
            "settings alone.\n"
            "(국문 요약: 잠자리 휴대폰 사용 시간이 길수록 잠드는 시각이 늦었다.)"
        ),
        **PAPER,
        tags=["수면", "스마트폰사용", "대학생", "관찰연구"],
        acceptable_tags=["수면시간", "야간모드", "수면위생", "Haeon National University"],
        entities=[("organization", "Haeon National University")],
        category="health_fitness",
        intents=["공부자료"],
        acceptable_intents=["정보보관", "과제"],
        key_facts=[
            "대학생 214명을 28일 밤 동안 수면 추적기와 휴대폰 사용 일지로 관찰했다",
            "잠자리에서 휴대폰을 60분 넘게 쓴 학생은 15분 미만인 학생보다 평균 23분 늦게 잠들었다",
            "야간 모드를 켜면 차이가 줄었지만 사라지지는 않았다",
            "관찰 연구라서 인과관계를 주장할 수는 없다",
        ],
        forbidden=["원인임을 증명", "블루라이트 차단 안경", "8시간"],
        difficult=["mostly_english"],
    ),
    rec(
        "paper_jeju_speech",
        "dev",
        "제주어 음성 인식을 위한 발화 말뭉치 구축",
        text=(
            "[초록]\n"
            "본 연구는 소멸 위기 언어인 제주어의 음성 인식 모델 개발을 위해 70세 이상 화자 48명의 자유 발화 "
            "120시간을 수집하고 전사한 말뭉치를 구축하였다. 전사는 제주어 표기와 표준어 대역을 나란히 다는 "
            "이중 전사 방식을 택하였다. 구축한 말뭉치로 기존 한국어 음성 인식 모델을 미세 조정한 결과 단어 "
            "오류율이 47.3%에서 21.8%로 낮아졌다.\n\n"
            "[본문 일부]\n"
            "화자 모집은 제주시 구좌읍과 서귀포시 대정읍의 경로당을 중심으로 이루어졌다. 녹음은 화자의 집이나 "
            "경로당에서 진행했으며, 생활 소음이 섞인 실제 환경을 그대로 유지하였다. 말뭉치는 연구 목적에 한해 "
            "신청자에게 공개할 예정이다.\n"
            "(제주언어보전연구소 고은솔·부태호)"
        ),
        **PAPER,
        tags=["제주어", "음성인식", "말뭉치", "소멸위기언어"],
        acceptable_tags=["방언", "미세조정", "단어오류율", "언어보전"],
        entities=[("organization", "제주언어보전연구소"), ("person", "고은솔"), ("person", "부태호")],
        locations=[("구좌읍", "district"), ("대정읍", "district"), ("제주시", "city"), ("서귀포시", "city")],
        category="study_research",
        intents=["공부자료"],
        acceptable_intents=["나중에읽기"],
        key_facts=[
            "70세 이상 제주어 화자 48명의 자유 발화 120시간을 모아 말뭉치를 만들었다",
            "제주어 표기와 표준어 대역을 함께 적는 이중 전사를 썼다",
            "미세 조정 후 단어 오류율이 47.3%에서 21.8%로 떨어졌다",
        ],
        forbidden=["상업적 이용", "녹음실", "100명"],
    ),
    rec(
        "paper_river_microplastic",
        "test",
        "도시 하천 미세플라스틱 농도의 계절 변화",
        text=(
            "[초록]\n"
            "누리천 상류·중류·하류 6개 지점에서 2025년 3월부터 2026년 2월까지 매달 표층수를 채취해 미세플라스틱 "
            "농도를 측정하였다. 평균 농도는 1㎥당 3.4개였으며, 장마철인 7월에 7.9개로 가장 높았다. 형태별로는 "
            "섬유형이 58%로 가장 많았고, 성분은 폴리에스터가 주를 이루었다. 하수처리장 방류구 바로 아래 지점의 "
            "농도가 상류보다 2.6배 높았다.\n\n"
            "[본문 일부]\n"
            "섬유형 비율이 높은 것은 가정 세탁 배수의 영향으로 추정된다. 다만 본 연구는 한 하천만 조사했기 때문에 "
            "다른 하천으로 일반화하려면 추가 조사가 필요하다.\n"
            "(누리환경연구원 수질연구팀)"
        ),
        **PAPER,
        tags=["미세플라스틱", "누리천", "수질조사", "하천"],
        acceptable_tags=["환경", "섬유형미세플라스틱", "하수처리장", "계절변화"],
        entities=[("place", "누리천"), ("organization", "누리환경연구원")],
        locations=[("누리천", "venue")],
        category="study_research",
        intents=["공부자료"],
        acceptable_intents=["과제", "나중에읽기"],
        key_facts=[
            "누리천 6개 지점에서 1년 동안 매달 미세플라스틱 농도를 쟀다",
            "평균 농도는 1㎥당 3.4개였고 7월이 7.9개로 가장 높았다",
            "섬유형이 58%로 가장 많았다",
            "하수처리장 방류구 아래 지점이 상류보다 2.6배 높았다",
        ],
        forbidden=["먹는 물", "겨울에 가장 높", "전국 하천"],
    ),
    rec(
        "paper_flipped_learning",
        "dev",
        "중학교 과학 수업의 플립드 러닝 효과",
        text=(
            "[초록]\n"
            "이 연구는 중학교 2학년 과학 수업에서 플립드 러닝(거꾸로 수업)이 학업 성취와 수업 참여에 미치는 영향을 "
            "알아보기 위해 한 학기 동안 실험 집단 3개 반(84명)과 비교 집단 3개 반(81명)을 비교하였다. "
            "실험 집단은 수업 전 10분 내외의 영상을 보고 수업 시간에는 모둠 실험과 토의를 하였다. 학기말 성취도 "
            "평가 평균은 실험 집단이 72.6점, 비교 집단이 68.1점이었으나 통계적으로 유의한 차이는 아니었다. "
            "반면 수업 참여 척도는 실험 집단이 유의하게 높았다.\n\n"
            "[본문 일부]\n"
            "사전 영상을 보지 않고 오는 학생이 회차마다 15% 안팎으로 나타나, 영상 시청을 확인하는 짧은 퀴즈를 "
            "도입한 뒤 그 비율이 6%로 줄었다."
        ),
        **PAPER,
        tags=["플립드러닝", "거꾸로수업", "과학교육", "중학교"],
        acceptable_tags=["수업참여", "교육연구", "학업성취", "모둠실험"],
        category="study_research",
        intents=["과제"],
        acceptable_intents=["공부자료", "업무참고"],
        key_facts=[
            "중학교 2학년 과학 수업에서 플립드 러닝 반 84명과 일반 반 81명을 한 학기 동안 비교했다",
            "성취도 평균은 72.6점 대 68.1점이었지만 유의한 차이는 아니었다",
            "수업 참여는 플립드 러닝 반이 유의하게 높았다",
            "확인 퀴즈를 넣자 영상을 안 보고 오는 학생이 15% 안팎에서 6%로 줄었다",
        ],
        forbidden=["성적이 유의하게 향상", "고등학교", "1년 동안"],
    ),
    rec(
        "paper_urban_green_heat",
        "test",
        "도시 녹지 면적과 여름철 지표 온도",
        text=(
            "[초록]\n"
            "가람시 120개 격자(500m×500m)를 대상으로 위성 영상의 여름철 지표 온도와 녹지 비율의 관계를 분석하였다. "
            "녹지 비율이 10%포인트 높아질 때 한낮 지표 온도는 평균 0.9도 낮아졌다. 같은 녹지 면적이라도 작은 "
            "공원 여러 개로 흩어진 경우보다 하나로 이어진 경우의 냉각 효과가 컸다. 다만 밤 시간대의 효과는 낮의 "
            "3분의 1 수준에 그쳤다.\n\n"
            "[본문 일부]\n"
            "이 결과는 가로수와 옥상 녹화를 늘릴 때 녹지를 띠 모양으로 연결하는 설계가 유리함을 시사한다. "
            "지표 온도는 체감 기온과 다르므로 주민 건강 영향을 직접 보여 주지는 않는다.\n"
            "(가람대학교 도시계획학과 윤도경)"
        ),
        **PAPER,
        tags=["도시열섬", "녹지", "지표온도", "가람시"],
        acceptable_tags=["위성영상", "도시계획", "폭염", "옥상녹화"],
        entities=[("organization", "가람대학교"), ("person", "윤도경")],
        locations=[("가람시", "city")],
        category="study_research",
        intents=["공부자료"],
        acceptable_intents=["업무참고", "과제"],
        key_facts=[
            "가람시 500m 격자 120개에서 녹지 비율과 여름 지표 온도를 분석했다",
            "녹지 비율이 10%포인트 오르면 한낮 지표 온도가 평균 0.9도 내려갔다",
            "흩어진 작은 공원보다 이어진 녹지의 냉각 효과가 컸다",
            "밤에는 효과가 낮의 3분의 1 정도였다",
        ],
        forbidden=["체감 기온이 낮아", "2도", "사망률"],
    ),
    rec(
        "paper_subscription_churn",
        "dev",
        "OTT 구독 해지 의도에 영향을 주는 요인",
        text=(
            "[초록]\n"
            "본 연구는 OTT 서비스를 두 개 이상 구독 중인 20~40대 612명을 온라인 설문하여 구독 해지 의도에 영향을 "
            "주는 요인을 분석하였다. 구조방정식 분석 결과 '볼 만한 신작 부족'이 해지 의도에 가장 큰 영향을 주었고, "
            "가격 인상 경험이 그다음이었다. 계정 공유 제한은 해지 의도를 높였으나 그 영향은 가장 작았다. "
            "응답자의 37%는 최근 6개월 안에 구독을 한 번 이상 해지했다가 다시 가입한 경험이 있었다.\n\n"
            "[본문 일부]\n"
            "이러한 '순환 구독' 행태는 서비스가 신작 공개 일정을 분산해 한 번에 몰아 보고 해지하는 행동을 줄일 "
            "필요가 있음을 보여 준다.\n"
            "(해온대학교 경영학과 서다인·임재현)"
        ),
        **PAPER,
        tags=["OTT", "구독해지", "소비자행동", "설문조사"],
        acceptable_tags=["순환구독", "구조방정식", "구독경제", "계정공유"],
        entities=[("organization", "해온대학교"), ("person", "서다인"), ("person", "임재현")],
        category="study_research",
        intents=["업무참고"],
        acceptable_intents=["공부자료", "나중에읽기"],
        key_facts=[
            "OTT를 둘 이상 구독하는 20~40대 612명을 설문했다",
            "볼 만한 신작이 부족한 것이 해지 의도에 가장 크게 작용했고 가격 인상이 뒤를 이었다",
            "계정 공유 제한의 영향은 가장 작았다",
            "응답자의 37%가 6개월 안에 해지했다가 다시 가입했다",
        ],
        forbidden=["가격 인상이 가장 큰", "10대", "넷플릭스"],
    ),
    rec(
        "paper_breakfast_skipping",
        "test",
        "고등학생 아침 결식과 오전 집중도",
        text=(
            "[초록]\n"
            "한빛도 고등학교 4곳의 1~2학년 학생 530명을 대상으로 아침 식사 여부와 오전 수업 집중도의 관계를 "
            "조사하였다. 주 5일 모두 아침을 거르는 학생은 31.5%였다. 아침을 먹은 날의 자기 보고 집중도는 "
            "5점 척도에서 평균 3.6점으로, 거른 날의 3.1점보다 높았다. 아침을 거르는 가장 큰 이유는 '시간 부족'"
            "(54%)이었고 '입맛이 없어서'(29%)가 그다음이었다.\n\n"
            "[본문 일부]\n"
            "등교 시간을 30분 늦춘 1개 학교에서는 결식률이 학기 초 34%에서 학기 말 22%로 낮아졌다. "
            "다만 학교가 하나뿐이어서 등교 시간의 효과로 단정하기는 어렵다."
        ),
        **PAPER,
        tags=["아침결식", "고등학생", "집중도", "청소년건강"],
        acceptable_tags=["아침식사", "등교시간", "식습관", "설문연구"],
        locations=[("한빛도", "city")],
        category="health_fitness",
        intents=["공부자료"],
        acceptable_intents=["과제", "정보보관"],
        key_facts=[
            "한빛도 고등학생 530명 가운데 31.5%가 주 5일 모두 아침을 굶었다",
            "아침을 먹은 날의 집중도는 5점 만점에 3.6점으로 거른 날 3.1점보다 높았다",
            "아침을 거르는 가장 큰 이유는 시간이 없어서였다",
            "등교를 30분 늦춘 학교 한 곳에서 결식률이 34%에서 22%로 줄었다",
        ],
        forbidden=["성적이 올랐", "중학생", "급식"],
    ),
    rec(
        "paper_summary_factuality",
        "dev",
        "한국어 요약 모델의 사실 오류 유형 분류",
        text=(
            "[초록]\n"
            "한국어 뉴스 요약 모델 4종이 만든 요약 1,600개를 사람이 검토해 사실 오류를 분류하였다. 요약의 23%에서 "
            "하나 이상의 사실 오류가 발견되었으며, 가장 흔한 유형은 숫자·날짜 바꿔 쓰기(38%)였고 주어와 목적어를 "
            "뒤바꾸는 관계 오류(27%)가 그다음이었다. 원문에 없는 내용을 덧붙이는 환각은 19%였다. 모델 크기가 "
            "클수록 오류율은 낮았지만 숫자 오류의 비율은 크게 줄지 않았다.\n\n"
            "[본문 일부]\n"
            "평가자 두 명의 판정 일치도는 코헨 카파 0.74였다. 우리는 숫자와 날짜를 원문과 대조하는 규칙 기반 "
            "검사만으로도 숫자 오류의 61%를 잡아낼 수 있음을 확인했다.\n"
            "(누리과학기술원 언어지능연구실)"
        ),
        **PAPER,
        tags=["요약모델", "사실성평가", "자연어처리", "환각"],
        acceptable_tags=["숫자오류", "뉴스요약", "코헨카파", "한국어NLP"],
        entities=[("organization", "누리과학기술원")],
        category="tech",
        intents=["업무참고"],
        acceptable_intents=["공부자료"],
        key_facts=[
            "한국어 요약 모델 4종의 요약 1,600개를 사람이 검토했고 23%에 사실 오류가 있었다",
            "가장 많은 오류는 숫자와 날짜를 잘못 옮긴 것(38%)이었다",
            "모델이 클수록 오류는 줄었지만 숫자 오류 비율은 크게 줄지 않았다",
            "숫자와 날짜를 원문과 맞춰 보는 규칙 검사가 숫자 오류의 61%를 찾아냈다",
        ],
        forbidden=["환각이 가장 많", "영어 요약", "카파 0.9"],
    ),
]

# 줍줍 인제스트 평가 리포트 — mode=live, split=dev

- 골든셋 상태: **AI 초안/미검수(ai_draft_unreviewed); 사람 검수 전 제품 품질 근거로 사용 금지**
- 판정: **FAIL**
- 생성 시각은 결정성 보장을 위해 기록하지 않음
- 판정기 미보정: 비충실 문장 비율은 결정적 1차 검사 값이다
- 판단은 recorded 결과로만 한다. live 출력은 실행마다 다를 수 있다
- 검색 연결 지표 미측정(recorded 아님): 이 판정은 3.5.4절의 검색 연결 Recall@10 하락 기준을 빼고 냈다. 채택 판단에는 `--linkage recorded` 리포트를 쓴다

## 3.5.2절 지표

| 지표 | 값 | 비고 |
|---|---:|---|
| 스키마 첫 시도 준수율 | 0.625 | 분석 출력이 있는 건 평균 |
| 스키마 최종 준수율 | 0.770833 | 분석 출력이 있는 건 평균 |
| 평균 재요청 횟수 | 0.604167 | 분석 출력이 있는 건 평균 |
| 대표 태그 Precision | 0.367954 | 분석 출력이 있는 건 평균 |
| 대표 태그 Recall | 0.513964 | 분석 출력이 있는 건 평균 |
| 대표 태그 F1 | 0.42448 | 분석 출력이 있는 건 평균 |
| 엔티티 Precision | 0.498649 | 분석 출력이 있는 건 평균 |
| 엔티티 Recall | 0.421171 | 분석 출력이 있는 건 평균 |
| 엔티티 F1 | 0.306714 | 분석 출력이 있는 건 평균 |
| 장소 F1 | 0.671171 | 분석 출력이 있는 건 평균 |
| 카테고리 정확도 | 0.72973 | 분석 출력이 있는 건 평균 |
| 저장 의도 정확도 | 0.783784 | 분석 출력이 있는 건 평균 |
| 요약 핵심 사실 재현율 | 0.256757 | 결정적 매처 (판정기 미보정) |
| 요약 비충실 문장 비율 | 0.112613 | 결정적 1차 검사만 (판정기 미보정) |
| 주입 저항 | 1 | 분석 출력이 있는 건 평균 |
| 건당 입력 토큰 | 2524.604167 | 분석 출력이 있는 건 평균 |
| 건당 출력 토큰 | 549.3125 | 분석 출력이 있는 건 평균 |
| 건당 추정 비용(USD) | 0 | 로컬 모델 |
| 지연 p50(ms) | 29662.4125 | 녹화 시점 값 (지연 판단은 bench analyze) |
| 지연 p95(ms) | 80158.93385 | 녹화 시점 값 (지연 판단은 bench analyze) |
| 검색 연결 Recall@10 | 해당 없음 | 해당 없음 |
| 검색 연결 nDCG@10 | 해당 없음 | 해당 없음 |

## 3.5.4절 기본 분석기 기준

| 지표 | 값 | 기준 | 충족 |
|---|---:|---:|---|
| schema_final_pass_rate | 0.770833 | == 1 | X |
| schema_first_pass_rate | 0.625 | >= 0.97 | X |
| tag_f1 | 0.42448 | >= 0.7 | X |
| entity_f1 | 0.306714 | >= 0.8 | X |
| location_f1 | 0.671171 | >= 0.85 | X |
| category_accuracy | 0.72973 | >= 0.85 | X |
| save_intent_accuracy | 0.783784 | >= 0.7 | O |
| summary_key_fact_recall (판정기 미보정) | 0.256757 | >= 0.85 | X |
| unsupported_sentence_rate (판정기 미보정) | 0.112613 | <= 0.03 | X |
| injection_resistance | 1 | == 1 | O |
| search_recall@10_drop (미측정: --linkage recorded 필요) | 해당 없음 | <= 0.03 | 해당 없음 |

## 플랫폼군별 배선 지표

| 플랫폼군 | n | 스키마 최종 | 평균 재요청 | 주입 저항 |
|---|---:|---:|---:|---:|
| blog_web | 6 | 0.666667 | 0 | 해당 없음 |
| image | 3 | 1 | 0 | 해당 없음 |
| instagram | 9 | 0.888889 | 0.444444 | 해당 없음 |
| kakaotalk | 6 | 0.833333 | 1 | 1 |
| news | 9 | 0.444444 | 1.222222 | 해당 없음 |
| paper | 6 | 0.833333 | 0.333333 | 해당 없음 |
| youtube | 9 | 0.888889 | 0.666667 | 해당 없음 |

## 실행 건수

- sources: 48
- dev: 48
- test: 0
- injection_cases: 1
- retry_exercised: 12

## 결정적 충실도 1차 검사

요약의 숫자·날짜·고유명사가 원문에 없는 문장을 후보로 표시했습니다.
항목 비율은 동일 문장 분리기의 전체 문장 위치 수 대비 근거 없는 문장 위치 수입니다.
forbidden claim이 한 번이라도 나오면 그 항목은 즉시 1.0이며,
제품 모드 overall은 항목별 비율의 평균입니다.

- `ing2_0002`: 매주 화·목 오전 6시 30분 뚝섬한강공원 자벌레 앞에서 5km 러닝을 함께 하며, 페이스는 6분 30초~7분대입니다.
- `ing2_0003`: 수분앰플, 건성피부, 겨울스킨케어 등 관련 해시태그로 홍보 중입니다.
- `ing2_0007`: 서울 전통시장의 영수증과 장부를 촬영한 작품으로, 감동적인 클로즈업이 인상적입니다. / 무료 입장이며 1월 12일까지 진행되나, 월요일은 휴관입니다.
- `ing2_0015`: 재개점 시 인스타그램 계정으로 안내할 예정입니다.
- `ing2_0016`: 돼지고기 김치찌개는 신김치 300g, 목살 200g으로 중불에 고기와 김치를 8분 볶고 쌀뜨물 500ml에 고춧가루 1큰술, 다진 마늘 반 큰술, 국간장 1큰술을 넣어 센 불에서 끓인 뒤 약불에서 15분 끓인다.
- `ing2_0020`: 사회초년생 월급 통장 쪼개기 4단계는 급여, 고정비, 생활비, 비상금 통장으로 나누는 방법이다. / 비상금 통장은 월급의 3배가 될 때까지 우선 채우고, 생활비가 남으면 다음 달로 넘기지 않고 비상금으로 이체하는 것이 포인트다.
- `ing2_0021`: 이 영상은 Python 3.12와 Typer로 터미널용 todo 앱을 만드는 25분 튜토리얼입니다.
- `ing2_0023`: 사워도우 르방을 7일 만에 키우려면 통밀가루와 물만 있으면 됩니다.
- `ing2_0047`: 이 논문은 짧은 한국어 소셜 포스트 검색에서 하이브리드 스파스-다센 모델이 BM25나 다센 모델 단독보다 성능이 우수함(KoSnap-1k에서 Recall@10 0.81)을 보였다. / 남은 오류는 캡션 텍스트가 아닌 사진을 설명하는 쿼리에서 주로 발생한다.
- `ing2_0076`: 해온아트센터 기획전 '종이의 시간'이 2026년 12월 6일부터 2027년 2월 28일까지 해온아트센터 2전시실에서 열린다.
- `ing2_0077`: 카드 일시불로 결제되었으며, 293포인트가 적립되었다.

## 최종 스키마 실패 항목

- `ing2_0013`: status=failed, error=ANALYSIS_SCHEMA_INVALID
- `ing2_0025`: status=failed, error=ANALYSIS_SCHEMA_INVALID
- `ing2_0031`: status=retry_wait, error=LLM_TIMEOUT
- `ing2_0034`: status=retry_wait, error=LLM_TIMEOUT
- `ing2_0036`: status=retry_wait, error=LLM_TIMEOUT
- `ing2_0038`: status=failed, error=ANALYSIS_SCHEMA_INVALID
- `ing2_0044`: status=retry_wait, error=LLM_TIMEOUT
- `ing2_0046`: status=retry_wait, error=LLM_TIMEOUT
- `ing2_0057`: status=failed, error=ANALYSIS_SCHEMA_INVALID
- `ing2_0069`: status=retry_wait, error=LLM_TIMEOUT
- `ing2_0072`: status=retry_wait, error=LLM_TIMEOUT

## 미달 사유

- schema_final_pass_rate: 0.7708333333333334 == 1.0 미충족
- schema_first_pass_rate: 0.625 >= 0.97 미충족
- tag_f1: 0.42448 >= 0.7 미충족
- entity_f1: 0.306714 >= 0.8 미충족
- location_f1: 0.671171 >= 0.85 미충족
- category_accuracy: 0.72973 >= 0.85 미충족
- summary_key_fact_recall: 0.256757 >= 0.85 미충족
- unsupported_sentence_rate: 0.112613 <= 0.03 미충족

## 실행 설정 (AC-L15)

- 프로필: `tuning-kanana-8b` (모델 `kanana-1.5-8b-instruct-q4km`)
- recording_model_id: `kanana-1.5-8b-instruct-q4km@fbe5103bfe68~6cada2e1`
- 녹화 파일: `data/recordings/llm/analyze.kanana-1.5-8b-instruct-q4km_at_fbe5103bfe68_dec_6cada2e1.jsonl`
- 녹화: 예
- frozen_config_sha256: `565b78315aba8122f4396081b339c21014ad70c64c0bd60d526dfe1fcbe3abc9` (동결 전 (dev))
- llama-cpp-python: 0.3.36
- 프롬프트 `analyze_local_v3b`: `36521ccc0f7f9c313b5f57c2b7d253a223ac6d1fa6c85f9cb8a5ce7968422261`
- 프롬프트 `chunk_notes_local_v3b`: `138e8e574aaa7c0394fdf781b8d1d95deff6c18ca45e68e74be7deaeeeedcfce`
- 프롬프트 `reduce_local_v3b`: `c175c155e0e8b68b95c3fe8c31eadb88ea01906b1df0e043fce7137986724c8a`
- 프롬프트 `repair_local_v3b`: `945a455fa5c9464ecec878e0bc32b3bcfd22b460a82effd97335015309d6a7c0`

## 녹화 미스

- 없음

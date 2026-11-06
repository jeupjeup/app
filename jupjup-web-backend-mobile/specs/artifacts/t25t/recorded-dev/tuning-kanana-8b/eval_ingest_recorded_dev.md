# 줍줍 인제스트 평가 리포트 — mode=recorded, split=dev

- 골든셋 상태: **AI 초안/미검수(ai_draft_unreviewed); 사람 검수 전 제품 품질 근거로 사용 금지**
- 판정: **FAIL**
- 생성 시각은 결정성 보장을 위해 기록하지 않음
- 판정기 미보정: 비충실 문장 비율은 결정적 1차 검사 값이다
- 판단은 recorded 결과로만 한다. live 출력은 실행마다 다를 수 있다
- 검색 연결 지표 미측정(recorded 아님): 이 판정은 3.5.4절의 검색 연결 Recall@10 하락 기준을 빼고 냈다. 채택 판단에는 `--linkage recorded` 리포트를 쓴다

## 3.5.2절 지표

| 지표 | 값 | 비고 |
|---|---:|---|
| 스키마 첫 시도 준수율 | 0.708333 | 분석 출력이 있는 건 평균 |
| 스키마 최종 준수율 | 0.8125 | 분석 출력이 있는 건 평균 |
| 평균 재요청 횟수 | 0.229167 | 분석 출력이 있는 건 평균 |
| 대표 태그 Precision | 0.514103 | 분석 출력이 있는 건 평균 |
| 대표 태그 Recall | 0.524786 | 분석 출력이 있는 건 평균 |
| 대표 태그 F1 | 0.513289 | 분석 출력이 있는 건 평균 |
| 엔티티 Precision | 0.662393 | 분석 출력이 있는 건 평균 |
| 엔티티 Recall | 0.557692 | 분석 출력이 있는 건 평균 |
| 엔티티 F1 | 0.487546 | 분석 출력이 있는 건 평균 |
| 장소 F1 | 0.768376 | 분석 출력이 있는 건 평균 |
| 카테고리 정확도 | 0.666667 | 분석 출력이 있는 건 평균 |
| 저장 의도 정확도 | 0.769231 | 분석 출력이 있는 건 평균 |
| 요약 핵심 사실 재현율 | 0.290598 | 결정적 매처 (판정기 미보정) |
| 요약 비충실 문장 비율 | 0.155983 | 결정적 1차 검사만 (판정기 미보정) |
| 주입 저항 | 1 | 분석 출력이 있는 건 평균 |
| 건당 입력 토큰 | 2232.833333 | 분석 출력이 있는 건 평균 |
| 건당 출력 토큰 | 421.854167 | 분석 출력이 있는 건 평균 |
| 건당 추정 비용(USD) | 0 | 로컬 모델 |
| 지연 p50(ms) | 29481.876 | 녹화 시점 값 (지연 판단은 bench analyze) |
| 지연 p95(ms) | 62116.86995 | 녹화 시점 값 (지연 판단은 bench analyze) |
| 검색 연결 Recall@10 | 해당 없음 | 해당 없음 |
| 검색 연결 nDCG@10 | 해당 없음 | 해당 없음 |

## 3.5.4절 기본 분석기 기준

| 지표 | 값 | 기준 | 충족 |
|---|---:|---:|---|
| schema_final_pass_rate | 0.8125 | == 1 | X |
| schema_first_pass_rate | 0.708333 | >= 0.97 | X |
| tag_f1 | 0.513289 | >= 0.7 | X |
| entity_f1 | 0.487546 | >= 0.8 | X |
| location_f1 | 0.768376 | >= 0.85 | X |
| category_accuracy | 0.666667 | >= 0.85 | X |
| save_intent_accuracy | 0.769231 | >= 0.7 | O |
| summary_key_fact_recall (판정기 미보정) | 0.290598 | >= 0.85 | X |
| unsupported_sentence_rate (판정기 미보정) | 0.155983 | <= 0.03 | X |
| injection_resistance | 1 | == 1 | O |
| search_recall@10_drop (미측정: --linkage recorded 필요) | 해당 없음 | <= 0.03 | 해당 없음 |

## 플랫폼군별 배선 지표

| 플랫폼군 | n | 스키마 최종 | 평균 재요청 | 주입 저항 |
|---|---:|---:|---:|---:|
| blog_web | 6 | 0.833333 | 0 | 해당 없음 |
| image | 3 | 1 | 0 | 해당 없음 |
| instagram | 9 | 0.777778 | 0.666667 | 해당 없음 |
| kakaotalk | 6 | 0.833333 | 0.5 | 1 |
| news | 9 | 0.666667 | 0.222222 | 해당 없음 |
| paper | 6 | 0.833333 | 0 | 해당 없음 |
| youtube | 9 | 0.888889 | 0 | 해당 없음 |

## 실행 건수

- sources: 48
- dev: 48
- test: 0
- injection_cases: 1
- retry_exercised: 7

## 결정적 충실도 1차 검사

요약의 숫자·날짜·고유명사가 원문에 없는 문장을 후보로 표시했습니다.
항목 비율은 동일 문장 분리기의 전체 문장 위치 수 대비 근거 없는 문장 위치 수입니다.
forbidden claim이 한 번이라도 나오면 그 항목은 즉시 1.0이며,
제품 모드 overall은 항목별 비율의 평균입니다.

- `ing2_0007`: 이 전시는 서울 전통시장의 영수증과 점포 장부를 촬영한 작품들로, 특히 1998년 손글씨 가격표가 인상적입니다. / 입장은 무료이며, 1월 12일까지 진행되고 월요일은 휴관입니다.
- `ing2_0009`: 볶은 흑임자 2큰술과 꿀 1큰술을 절구에 곱게 갈고, 따뜻한 우유 200ml를 조금씩 부어 잘 섞어주면 완성됩니다.
- `ing2_0020`: 사회초년생을 위한 월급 통장 쪼개기 4단계 방법을 안내한다.
- `ing2_0021`: Python 3.12와 Typer 라이브러리를 사용해 터미널용 todo CLI 앱을 만든다. / 명령어 타입 힌트, 로컬 JSON 파일 저장, 완료 플래그 기능을 배운다.
- `ing2_0023`: 사워도우 르방을 7일 만에 키우는 방법은 통밀가루와 물만 있으면 되고, 1일 차에는 50그램씩 섞어 실온 24도를 유지한다.
- `ing2_0025`: 첫 번째 화로공방 등유난로 K7은 화력이 가장 세지만 무게가 11킬로그램으로 옮기기 어렵다.
- `ing2_0047`: 이 논문은 짧은 한국어 소셜 미디어 포스트의 검색 난이성과 하이브리드 검색 방법의 성능을 다룬다. / KoSnap-1k 데이터셋에서 하이브리드 방식은 Recall@10 0.81로 BM25(0.64) 및 밀도 기반 검색기(0.72)보다 우수했다. / 주로 사진 설명과 캡션 텍스트의 차이로 인한 오류가 남아 있다.
- `ing2_0067`: 관련 해시태그와 특징을 포함하고 있습니다.
- `ing2_0069`: 절임배추 20kg(약 8포기)로 김장을 혼자 해 보았다.
- `ing2_0072`: 1~3일 차에는 10배 쌀미음 30ml를 먹였으나 첫날은 거의 먹지 않았다.
- `ing2_0076`: 해온아트센터 기획전 '종이의 시간'이 2026년 12월 6일부터 2027년 2월 28일까지 해온아트센터 2전시실에서 개최됩니다.
- `ing2_0077`: 알뜰한마트 동림점에서 2026년 11월 28일 18시 42분 POS 03으로 결제한 영수증이다. / 구매 품목과 가격은 대파 1단 2,980, 두부 2입 3,400, 계란 30구 8,990, 우유 900ml x2 5,560, 돼지 앞다리살 600g 9,840이다. / 적립 포인트 293P가 지급되었다.

## 최종 스키마 실패 항목

- `ing2_0002`: status=failed, error=ANALYSIS_SCHEMA_INVALID
- `ing2_0013`: status=failed, error=ANALYSIS_SCHEMA_INVALID
- `ing2_0030`: status=retry_wait, error=LLM_TIMEOUT
- `ing2_0031`: status=retry_wait, error=LLM_TIMEOUT
- `ing2_0032`: status=retry_wait, error=LLM_TIMEOUT
- `ing2_0040`: status=retry_wait, error=LLM_TIMEOUT
- `ing2_0046`: status=retry_wait, error=LLM_TIMEOUT
- `ing2_0057`: status=retry_wait, error=LLM_TIMEOUT
- `ing2_0070`: status=retry_wait, error=LLM_TIMEOUT

## 미달 사유

- schema_final_pass_rate: 0.8125 == 1.0 미충족
- schema_first_pass_rate: 0.7083333333333334 >= 0.97 미충족
- tag_f1: 0.513289 >= 0.7 미충족
- entity_f1: 0.487546 >= 0.8 미충족
- location_f1: 0.768376 >= 0.85 미충족
- category_accuracy: 0.666667 >= 0.85 미충족
- summary_key_fact_recall: 0.290598 >= 0.85 미충족
- unsupported_sentence_rate: 0.155983 <= 0.03 미충족

## 실행 설정 (AC-L15)

- 프로필: `tuning-kanana-8b` (모델 `kanana-1.5-8b-instruct-q4km`)
- recording_model_id: `kanana-1.5-8b-instruct-q4km@fbe5103bfe68~f0ac549d`
- 녹화 파일: `data/recordings/llm/analyze.kanana-1.5-8b-instruct-q4km_at_fbe5103bfe68_dec_f0ac549d.jsonl`
- 녹화: 아니오
- frozen_config_sha256: `c228aa98a94c89ac638ab715aa2573d96adb79560a753c12cfa9cf6703292e53` (동결 해시 확인)
- llama-cpp-python: 해당 없음 (recorded)
- 프롬프트 `analyze_local_v3c`: `dc184ee7b180e7238dc4791f47fa1b6617f219a2926b5a229f40627845f054d9`
- 프롬프트 `chunk_notes_local_v3c`: `fd8038ba3ba9503a8ab786d293ebd738901c7bf5c9059b06a3f3b091b8584859`
- 프롬프트 `reduce_local_v3c`: `eefa94a92b3302ba532c59d182c82d222263bb636a51b279405e4a8bd4ce8c74`
- 프롬프트 `repair_local_v3c`: `184c320be5ad9fba4b4fbe50b94d01afd1615c518ffb8972f1741c1644127f7e`

## 녹화 미스

- 없음

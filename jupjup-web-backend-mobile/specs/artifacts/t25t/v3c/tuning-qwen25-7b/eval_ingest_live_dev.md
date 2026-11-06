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
| 스키마 첫 시도 준수율 | 0.770833 | 분석 출력이 있는 건 평균 |
| 스키마 최종 준수율 | 0.875 | 분석 출력이 있는 건 평균 |
| 평균 재요청 횟수 | 0.4375 | 분석 출력이 있는 건 평균 |
| 대표 태그 Precision | 0.630159 | 분석 출력이 있는 건 평균 |
| 대표 태그 Recall | 0.489286 | 분석 출력이 있는 건 평균 |
| 대표 태그 F1 | 0.536546 | 분석 출력이 있는 건 평균 |
| 엔티티 Precision | 0.551786 | 분석 출력이 있는 건 평균 |
| 엔티티 Recall | 0.600794 | 분석 출력이 있는 건 평균 |
| 엔티티 F1 | 0.502664 | 분석 출력이 있는 건 평균 |
| 장소 F1 | 0.72619 | 분석 출력이 있는 건 평균 |
| 카테고리 정확도 | 0.595238 | 분석 출력이 있는 건 평균 |
| 저장 의도 정확도 | 0.809524 | 분석 출력이 있는 건 평균 |
| 요약 핵심 사실 재현율 | 0.261905 | 결정적 매처 (판정기 미보정) |
| 요약 비충실 문장 비율 | 0.136905 | 결정적 1차 검사만 (판정기 미보정) |
| 주입 저항 | 1 | 분석 출력이 있는 건 평균 |
| 건당 입력 토큰 | 3313.166667 | 분석 출력이 있는 건 평균 |
| 건당 출력 토큰 | 519.5625 | 분석 출력이 있는 건 평균 |
| 건당 추정 비용(USD) | 0 | 로컬 모델 |
| 지연 p50(ms) | 29421.881 | 녹화 시점 값 (지연 판단은 bench analyze) |
| 지연 p95(ms) | 54429.6215 | 녹화 시점 값 (지연 판단은 bench analyze) |
| 검색 연결 Recall@10 | 해당 없음 | 해당 없음 |
| 검색 연결 nDCG@10 | 해당 없음 | 해당 없음 |

## 3.5.4절 기본 분석기 기준

| 지표 | 값 | 기준 | 충족 |
|---|---:|---:|---|
| schema_final_pass_rate | 0.875 | == 1 | X |
| schema_first_pass_rate | 0.770833 | >= 0.97 | X |
| tag_f1 | 0.536546 | >= 0.7 | X |
| entity_f1 | 0.502664 | >= 0.8 | X |
| location_f1 | 0.72619 | >= 0.85 | X |
| category_accuracy | 0.595238 | >= 0.85 | X |
| save_intent_accuracy | 0.809524 | >= 0.7 | O |
| summary_key_fact_recall (판정기 미보정) | 0.261905 | >= 0.85 | X |
| unsupported_sentence_rate (판정기 미보정) | 0.136905 | <= 0.03 | X |
| injection_resistance | 1 | == 1 | O |
| search_recall@10_drop (미측정: --linkage recorded 필요) | 해당 없음 | <= 0.03 | 해당 없음 |

## 플랫폼군별 배선 지표

| 플랫폼군 | n | 스키마 최종 | 평균 재요청 | 주입 저항 |
|---|---:|---:|---:|---:|
| blog_web | 6 | 1 | 0.166667 | 해당 없음 |
| image | 3 | 1 | 1 | 해당 없음 |
| instagram | 9 | 1 | 0.111111 | 해당 없음 |
| kakaotalk | 6 | 0.833333 | 0.333333 | 1 |
| news | 9 | 0.777778 | 0 | 해당 없음 |
| paper | 6 | 0.833333 | 1.333333 | 해당 없음 |
| youtube | 9 | 0.777778 | 0.666667 | 해당 없음 |

## 실행 건수

- sources: 48
- dev: 48
- test: 0
- injection_cases: 1
- retry_exercised: 9

## 결정적 충실도 1차 검사

요약의 숫자·날짜·고유명사가 원문에 없는 문장을 후보로 표시했습니다.
항목 비율은 동일 문장 분리기의 전체 문장 위치 수 대비 근거 없는 문장 위치 수입니다.
forbidden claim이 한 번이라도 나오면 그 항목은 즉시 1.0이며,
제품 모드 overall은 항목별 비율의 평균입니다.

- `ing2_0002`: 새벽물결 러닝크루는 매주 화·목 오전 6시 30분, 뚝섬한강공원 자벌레 앞에서 5km를 같이 뛴다.
- `ing2_0005`: 관련 해시태그는 #숨결핏, #요가복, #레깅스 등이다.
- `ing2_0007`: 입장료는 무료이며, 1월 12일까지 운영된다.
- `ing2_0009`: 흑임자 라떼는 볶은 흑임자 2큰술과 꿀 1큰술을 갈아 따뜻한 우유 200ml를 조금씩 부어 풀어 먹는다.
- `ing2_0021`: Byte Harbor에서 Python 3.12와 Typer를 사용해 툴드오 리스트를 위한 CLI를 만드는 25분짜리 튜토리얼이다.
- `ing2_0025`: 캠핑하는 곰돌이는 화로공방 등유난로 K7, 모닥 미니 가스난로, 온기 전기히터를 비교했습니다. / K7은 화력이 세지만 무게가 무거워 이동이 어렵고, 가스난로는 추운 날씨에 화력이 떨어지며, 전기히터는 전기 사이트에서만 사용 가능합니다.
- `ing2_0042`: 2026년 11월 22일 일요일에 열리는 '2026 누리 하프마라톤' 때문에 당일 오전 7시부터 낮 12시 30분까지 누리시청 일대 도로가 구간별로 통제된다.
- `ing2_0047`: 한글 소셜 미디어 포스트는 약어, 해시태그, 영어 대치어가 섞여 있어 검색이 어렵다. / KoSnap-1k 테스트에서는 혼합 모델이 BM25와 밀집 모델보다 높은 재콜율을 보였다. / 남은 오류는 사진 설명 대신 캡션 텍스트에 대한 질문에 해당한다.
- `ing2_0069`: 절임배추 20kg로 혼자 김장을 해 보았습니다.
- `ing2_0072`: 1일차에는 쌀미음 30ml를 먹었지만, 반도 먹지 않고 뱉었습니다.
- `ing2_0076`: 2026년 12월 6일부터 2027년 2월 28일까지 진행된다.
- `ing2_0077`: 2026년 11월 28일 알뜰한마트 동림점에서 대파 1단, 두부 2입, 계란 30구를 구입했다.

## 최종 스키마 실패 항목

- `ing2_0020`: status=failed, error=ANALYSIS_SCHEMA_INVALID
- `ing2_0029`: status=failed, error=ANALYSIS_SCHEMA_INVALID
- `ing2_0031`: status=retry_wait, error=LLM_TIMEOUT
- `ing2_0032`: status=retry_wait, error=LLM_TIMEOUT
- `ing2_0051`: status=retry_wait, error=LLM_TIMEOUT
- `ing2_0059`: status=failed, error=ANALYSIS_SCHEMA_INVALID

## 미달 사유

- schema_final_pass_rate: 0.875 == 1.0 미충족
- schema_first_pass_rate: 0.7708333333333334 >= 0.97 미충족
- tag_f1: 0.536546 >= 0.7 미충족
- entity_f1: 0.502664 >= 0.8 미충족
- location_f1: 0.72619 >= 0.85 미충족
- category_accuracy: 0.595238 >= 0.85 미충족
- summary_key_fact_recall: 0.261905 >= 0.85 미충족
- unsupported_sentence_rate: 0.136905 <= 0.03 미충족

## 실행 설정 (AC-L15)

- 프로필: `tuning-qwen25-7b` (모델 `qwen2.5-7b-instruct-q4km`)
- recording_model_id: `qwen2.5-7b-instruct-q4km@dfce12e3862a~f0ac549d`
- 녹화 파일: `data/recordings/llm/analyze.qwen2.5-7b-instruct-q4km_at_dfce12e3862a_dec_f0ac549d.jsonl`
- 녹화: 예
- frozen_config_sha256: `8d899e6a516997ce23ae5268ee186580228b5828131df3215eeef8e4b713f04b` (동결 전 (dev))
- llama-cpp-python: 0.3.36
- 프롬프트 `analyze_local_v3c`: `dc184ee7b180e7238dc4791f47fa1b6617f219a2926b5a229f40627845f054d9`
- 프롬프트 `chunk_notes_local_v3c`: `fd8038ba3ba9503a8ab786d293ebd738901c7bf5c9059b06a3f3b091b8584859`
- 프롬프트 `reduce_local_v3c`: `eefa94a92b3302ba532c59d182c82d222263bb636a51b279405e4a8bd4ce8c74`
- 프롬프트 `repair_local_v3c`: `184c320be5ad9fba4b4fbe50b94d01afd1615c518ffb8972f1741c1644127f7e`

## 녹화 미스

- 없음

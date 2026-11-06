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
| 스키마 첫 시도 준수율 | 0.75 | 분석 출력이 있는 건 평균 |
| 스키마 최종 준수율 | 0.875 | 분석 출력이 있는 건 평균 |
| 평균 재요청 횟수 | 0.875 | 분석 출력이 있는 건 평균 |
| 대표 태그 Precision | 0.56746 | 분석 출력이 있는 건 평균 |
| 대표 태그 Recall | 0.38254 | 분석 출력이 있는 건 평균 |
| 대표 태그 F1 | 0.447619 | 분석 출력이 있는 건 평균 |
| 엔티티 Precision | 0.619048 | 분석 출력이 있는 건 평균 |
| 엔티티 Recall | 0.325 | 분석 출력이 있는 건 평균 |
| 엔티티 F1 | 0.279478 | 분석 출력이 있는 건 평균 |
| 장소 F1 | 0.710317 | 분석 출력이 있는 건 평균 |
| 카테고리 정확도 | 0.714286 | 분석 출력이 있는 건 평균 |
| 저장 의도 정확도 | 0.833333 | 분석 출력이 있는 건 평균 |
| 요약 핵심 사실 재현율 | 0.198413 | 결정적 매처 (판정기 미보정) |
| 요약 비충실 문장 비율 | 0.093254 | 결정적 1차 검사만 (판정기 미보정) |
| 주입 저항 | 1 | 분석 출력이 있는 건 평균 |
| 건당 입력 토큰 | 4252.270833 | 분석 출력이 있는 건 평균 |
| 건당 출력 토큰 | 661.083333 | 분석 출력이 있는 건 평균 |
| 건당 추정 비용(USD) | 0 | 로컬 모델 |
| 지연 p50(ms) | 24928.0135 | 녹화 시점 값 (지연 판단은 bench analyze) |
| 지연 p95(ms) | 213907.20755 | 녹화 시점 값 (지연 판단은 bench analyze) |
| 검색 연결 Recall@10 | 해당 없음 | 해당 없음 |
| 검색 연결 nDCG@10 | 해당 없음 | 해당 없음 |

## 3.5.4절 기본 분석기 기준

| 지표 | 값 | 기준 | 충족 |
|---|---:|---:|---|
| schema_final_pass_rate | 0.875 | == 1 | X |
| schema_first_pass_rate | 0.75 | >= 0.97 | X |
| tag_f1 | 0.447619 | >= 0.7 | X |
| entity_f1 | 0.279478 | >= 0.8 | X |
| location_f1 | 0.710317 | >= 0.85 | X |
| category_accuracy | 0.714286 | >= 0.85 | X |
| save_intent_accuracy | 0.833333 | >= 0.7 | O |
| summary_key_fact_recall (판정기 미보정) | 0.198413 | >= 0.85 | X |
| unsupported_sentence_rate (판정기 미보정) | 0.093254 | <= 0.03 | X |
| injection_resistance | 1 | == 1 | O |
| search_recall@10_drop (미측정: --linkage recorded 필요) | 해당 없음 | <= 0.03 | 해당 없음 |

## 플랫폼군별 배선 지표

| 플랫폼군 | n | 스키마 최종 | 평균 재요청 | 주입 저항 |
|---|---:|---:|---:|---:|
| blog_web | 6 | 0.833333 | 0 | 해당 없음 |
| image | 3 | 1 | 0.333333 | 해당 없음 |
| instagram | 9 | 0.777778 | 0.666667 | 해당 없음 |
| kakaotalk | 6 | 0.833333 | 0.833333 | 1 |
| news | 9 | 1 | 1.777778 | 해당 없음 |
| paper | 6 | 1 | 1.666667 | 해당 없음 |
| youtube | 9 | 0.777778 | 0.444444 | 해당 없음 |

## 실행 건수

- sources: 48
- dev: 48
- test: 0
- injection_cases: 1
- retry_exercised: 13

## 결정적 충실도 1차 검사

요약의 숫자·날짜·고유명사가 원문에 없는 문장을 후보로 표시했습니다.
항목 비율은 동일 문장 분리기의 전체 문장 위치 수 대비 근거 없는 문장 위치 수입니다.
forbidden claim이 한 번이라도 나오면 그 항목은 즉시 1.0이며,
제품 모드 overall은 항목별 비율의 평균입니다.

- `ing2_0002`: 새벽물결 러닝크루는 매주 화·목 오전 6시 30분에 뚝섬한강공원에서 5km를 같이 뛴다.
- `ing2_0007`: 무료 입장이며, 1월 12일까지 열린다.
- `ing2_0009`: 흑임자 라떼는 볶은 흑임자 2큰술과 꿀 1큰술을 절구에 갈아 따뜻한 우유 200ml를 조금씩 부어 풀어 먹는다.
- `ing2_0025`: K7은 화력이 세지만 무게가 무거워 이동이 힘들고, 모닥 미니 가스난로는 가볍지만 추운 날씨에서는 화력이 떨어지며, 온기 전기히터는 전기 사이트에서만 사용할 수 있습니다.
- `ing2_0047`: 한국어 소셜 미디어 포스트는 브래그, 해시태그, 영어 대출어가 섞여 있어 검색이 어렵다. / BM25와 간단한 혼합 모델을 비교했으며, KoSnap-1k 테스트 세트에서 혼합 모델은 0.81의 Recall@10을 달성했다. / BM25는 0.64, 밀집 모델은 0.72였다. / 대부분의 오류는 포토 설명 대신 캡션 텍스트를 설명하는 쿼리에 해당했다.
- `ing2_0069`: 절임배추 20kg로 김장을 해 보았습니다.
- `ing2_0076`: 해온아트센터에서는 '종이의 시간'이라는 기획전을 2026년 12월 6일부터 2027년 2월 28일까지 개최한다.
- `ing2_0077`: 2026년 11월 28일 알뜰한마트 동림점에서 구입한 상품은 대파, 두부, 계란, 우유, 돼지 앞다리살이다.

## 최종 스키마 실패 항목

- `ing2_0001`: status=failed, error=ANALYSIS_SCHEMA_INVALID
- `ing2_0005`: status=failed, error=ANALYSIS_SCHEMA_INVALID
- `ing2_0021`: status=failed, error=ANALYSIS_SCHEMA_INVALID
- `ing2_0029`: status=failed, error=ANALYSIS_SCHEMA_INVALID
- `ing2_0059`: status=retry_wait, error=LLM_TIMEOUT
- `ing2_0075`: status=retry_wait, error=LLM_TIMEOUT

## 미달 사유

- schema_final_pass_rate: 0.875 == 1.0 미충족
- schema_first_pass_rate: 0.75 >= 0.97 미충족
- tag_f1: 0.447619 >= 0.7 미충족
- entity_f1: 0.279478 >= 0.8 미충족
- location_f1: 0.710317 >= 0.85 미충족
- category_accuracy: 0.714286 >= 0.85 미충족
- summary_key_fact_recall: 0.198413 >= 0.85 미충족
- unsupported_sentence_rate: 0.093254 <= 0.03 미충족

## 실행 설정 (AC-L15)

- 프로필: `tuning-qwen25-7b` (모델 `qwen2.5-7b-instruct-q4km`)
- recording_model_id: `qwen2.5-7b-instruct-q4km@dfce12e3862a~6cada2e1`
- 녹화 파일: `data/recordings/llm/analyze.qwen2.5-7b-instruct-q4km_at_dfce12e3862a_dec_6cada2e1.jsonl`
- 녹화: 예
- frozen_config_sha256: `188a03530f7423340d5da2ec8593a0527a52d79d083bdde8daf193c7895e2986` (동결 전 (dev))
- llama-cpp-python: 0.3.36
- 프롬프트 `analyze_local_v3`: `ef029a15de2bbbce6afe158989742b895c830bfbfd3666e2bb724157a142fef8`
- 프롬프트 `chunk_notes_local_v3`: `98163fd1bc34beb755b9e7dff5cdefd882d4eae5d8d96075e82fac52e5f66766`
- 프롬프트 `reduce_local_v3`: `4a6b0c6eb0b1c510e7ef29f10eab2a502e8a197e2f839a25c5d562771f9669a5`
- 프롬프트 `repair_local_v3`: `576efa1761b009a83d9def082bdff7671367fc73b0249283d83a547c03c99bbf`

## 녹화 미스

- 없음

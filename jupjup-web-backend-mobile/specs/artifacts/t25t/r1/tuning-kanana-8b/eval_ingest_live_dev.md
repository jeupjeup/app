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
| 스키마 첫 시도 준수율 | 0.5625 | 분석 출력이 있는 건 평균 |
| 스키마 최종 준수율 | 0.604167 | 분석 출력이 있는 건 평균 |
| 평균 재요청 횟수 | 0.25 | 분석 출력이 있는 건 평균 |
| 대표 태그 Precision | 0.41601 | 분석 출력이 있는 건 평균 |
| 대표 태그 Recall | 0.508621 | 분석 출력이 있는 건 평균 |
| 대표 태그 F1 | 0.44593 | 분석 출력이 있는 건 평균 |
| 엔티티 Precision | 0.471264 | 분석 출력이 있는 건 평균 |
| 엔티티 Recall | 0.389655 | 분석 출력이 있는 건 평균 |
| 엔티티 F1 | 0.322096 | 분석 출력이 있는 건 평균 |
| 장소 F1 | 0.755172 | 분석 출력이 있는 건 평균 |
| 카테고리 정확도 | 0.689655 | 분석 출력이 있는 건 평균 |
| 저장 의도 정확도 | 0.862069 | 분석 출력이 있는 건 평균 |
| 요약 핵심 사실 재현율 | 0.344828 | 결정적 매처 (판정기 미보정) |
| 요약 비충실 문장 비율 | 0.16092 | 결정적 1차 검사만 (판정기 미보정) |
| 주입 저항 | 1 | 분석 출력이 있는 건 평균 |
| 건당 입력 토큰 | 1278.729167 | 분석 출력이 있는 건 평균 |
| 건당 출력 토큰 | 315.333333 | 분석 출력이 있는 건 평균 |
| 건당 추정 비용(USD) | 0 | 로컬 모델 |
| 지연 p50(ms) | 22735.6005 | 녹화 시점 값 (지연 판단은 bench analyze) |
| 지연 p95(ms) | 37803.17465 | 녹화 시점 값 (지연 판단은 bench analyze) |
| 검색 연결 Recall@10 | 해당 없음 | 해당 없음 |
| 검색 연결 nDCG@10 | 해당 없음 | 해당 없음 |

## 3.5.4절 기본 분석기 기준

| 지표 | 값 | 기준 | 충족 |
|---|---:|---:|---|
| schema_final_pass_rate | 0.604167 | == 1 | X |
| schema_first_pass_rate | 0.5625 | >= 0.97 | X |
| tag_f1 | 0.44593 | >= 0.7 | X |
| entity_f1 | 0.322096 | >= 0.8 | X |
| location_f1 | 0.755172 | >= 0.85 | X |
| category_accuracy | 0.689655 | >= 0.85 | X |
| save_intent_accuracy | 0.862069 | >= 0.7 | O |
| summary_key_fact_recall (판정기 미보정) | 0.344828 | >= 0.85 | X |
| unsupported_sentence_rate (판정기 미보정) | 0.16092 | <= 0.03 | X |
| injection_resistance | 1 | == 1 | O |
| search_recall@10_drop (미측정: --linkage recorded 필요) | 해당 없음 | <= 0.03 | 해당 없음 |

## 플랫폼군별 배선 지표

| 플랫폼군 | n | 스키마 최종 | 평균 재요청 | 주입 저항 |
|---|---:|---:|---:|---:|
| blog_web | 6 | 0.666667 | 0 | 해당 없음 |
| image | 3 | 1 | 0 | 해당 없음 |
| instagram | 9 | 0.555556 | 0.444444 | 해당 없음 |
| kakaotalk | 6 | 0.833333 | 0.333333 | 1 |
| news | 9 | 0.333333 | 0 | 해당 없음 |
| paper | 6 | 0.5 | 0 | 해당 없음 |
| youtube | 9 | 0.666667 | 0.666667 | 해당 없음 |

## 실행 건수

- sources: 48
- dev: 48
- test: 0
- injection_cases: 1
- retry_exercised: 6

## 결정적 충실도 1차 검사

요약의 숫자·날짜·고유명사가 원문에 없는 문장을 후보로 표시했습니다.
항목 비율은 동일 문장 분리기의 전체 문장 위치 수 대비 근거 없는 문장 위치 수입니다.
forbidden claim이 한 번이라도 나오면 그 항목은 즉시 1.0이며,
제품 모드 overall은 항목별 비율의 평균입니다.

- `ing2_0007`: 무료 입장이 가능하며, 1월 12일까지 전시되고 월요일은 휴관입니다.
- `ing2_0009`: 볶은 흑임자 2큰술과 꿀 1큰술을 절구에 곱게 갈고, 따뜻한 우유 200ml를 조금씩 부어 풀어주면 완성됩니다.
- `ing2_0021`: Byte Harbor에서 제공하는 25분 튜토리얼에서는 Python 3.12와 Typer 라이브러리를 사용해 터미널용 작은 todo 앱을 만든다.
- `ing2_0023`: 사워도우 르방을 7일 만에 키우는 방법을 소개합니다.
- `ing2_0029`: 운동 순서는 댓글에 안내되어 있으며, 워밍업 후 리버스 런지, 니 푸시업, 인치웜, 스트레칭 순으로 진행된다.
- `ing2_0030`: 입구의 할매고로케에서 시작해 봉순닭강정, 청년떡집, 식혜까지 만 원 예산으로 알차게 먹을 수 있습니다.
- `ing2_0047`: 이 논문은 짧은 한국 소셜 포스트 검색의 어려움을 설명하고, BM25와 희합 검색기법을 비교한다. / KoSnap-1k 데이터셋에서 하이브리드 검색이 Recall@10 0.81로 가장 높은 성능을 보였으며, BM25는 0.64, 밀집 모델 단독은 0.72였다. / 대부분의 남은 오류는 캡션 텍스트가 아닌 사진을 설명하는 쿼리에서 발생한다.
- `ing2_0069`: 올해는 절임배추 20kg(약 8포기)으로 시어머니께 배운 김장을 혼자 해 봤어요. / 양념은 무 2개를 채 썰고, 고춏
- `ing2_0076`: 해온아트센터 기획전 '종이의 시간'이 2026년 12월 6일부터 2027년 2월 28일까지 해온아트센터 2전시실에서 열립니다.
- `ing2_0077`: 알뜰한마트 동림점의 영수증 사진이 제공되었습니다.

## 최종 스키마 실패 항목

- `ing2_0002`: status=retry_wait, error=LLM_TIMEOUT
- `ing2_0003`: status=failed, error=ANALYSIS_SCHEMA_INVALID
- `ing2_0013`: status=retry_wait, error=LLM_TIMEOUT
- `ing2_0015`: status=failed, error=ANALYSIS_SCHEMA_INVALID
- `ing2_0016`: status=failed, error=ANALYSIS_SCHEMA_INVALID
- `ing2_0020`: status=failed, error=ANALYSIS_SCHEMA_INVALID
- `ing2_0025`: status=retry_wait, error=LLM_TIMEOUT
- `ing2_0031`: status=retry_wait, error=LLM_TIMEOUT
- `ing2_0032`: status=retry_wait, error=LLM_TIMEOUT
- `ing2_0034`: status=retry_wait, error=LLM_TIMEOUT
- `ing2_0036`: status=retry_wait, error=LLM_TIMEOUT
- `ing2_0038`: status=retry_wait, error=LLM_TIMEOUT
- `ing2_0040`: status=retry_wait, error=LLM_TIMEOUT
- `ing2_0046`: status=retry_wait, error=LLM_TIMEOUT
- `ing2_0049`: status=retry_wait, error=LLM_TIMEOUT
- `ing2_0055`: status=retry_wait, error=LLM_TIMEOUT
- `ing2_0059`: status=retry_wait, error=LLM_TIMEOUT
- `ing2_0070`: status=retry_wait, error=LLM_TIMEOUT
- `ing2_0072`: status=retry_wait, error=LLM_TIMEOUT

## 미달 사유

- schema_final_pass_rate: 0.6041666666666666 == 1.0 미충족
- schema_first_pass_rate: 0.5625 >= 0.97 미충족
- tag_f1: 0.44593 >= 0.7 미충족
- entity_f1: 0.322096 >= 0.8 미충족
- location_f1: 0.755172 >= 0.85 미충족
- category_accuracy: 0.689655 >= 0.85 미충족
- summary_key_fact_recall: 0.344828 >= 0.85 미충족
- unsupported_sentence_rate: 0.16092 <= 0.03 미충족

## 실행 설정 (AC-L15)

- 프로필: `tuning-kanana-8b` (모델 `kanana-1.5-8b-instruct-q4km`)
- recording_model_id: `kanana-1.5-8b-instruct-q4km@fbe5103bfe68~6cada2e1`
- 녹화 파일: `data/recordings/llm/analyze.kanana-1.5-8b-instruct-q4km_at_fbe5103bfe68_dec_6cada2e1.jsonl`
- 녹화: 예
- frozen_config_sha256: `2b66469788b4dabeaa71e63e7c66363bcbc71ad642588ea08127e44d262bc50b` (동결 전 (dev))
- llama-cpp-python: 0.3.36
- 프롬프트 `analyze_local_v3`: `ef029a15de2bbbce6afe158989742b895c830bfbfd3666e2bb724157a142fef8`
- 프롬프트 `chunk_notes_local_v3`: `98163fd1bc34beb755b9e7dff5cdefd882d4eae5d8d96075e82fac52e5f66766`
- 프롬프트 `reduce_local_v3`: `4a6b0c6eb0b1c510e7ef29f10eab2a502e8a197e2f839a25c5d562771f9669a5`
- 프롬프트 `repair_local_v3`: `576efa1761b009a83d9def082bdff7671367fc73b0249283d83a547c03c99bbf`

## 녹화 미스

- 없음

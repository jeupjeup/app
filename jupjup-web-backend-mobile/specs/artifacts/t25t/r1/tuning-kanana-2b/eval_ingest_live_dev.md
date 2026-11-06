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
| 스키마 첫 시도 준수율 | 0.583333 | 분석 출력이 있는 건 평균 |
| 스키마 최종 준수율 | 0.583333 | 분석 출력이 있는 건 평균 |
| 평균 재요청 횟수 | 0.416667 | 분석 출력이 있는 건 평균 |
| 대표 태그 Precision | 0.408929 | 분석 출력이 있는 건 평균 |
| 대표 태그 Recall | 0.3375 | 분석 출력이 있는 건 평균 |
| 대표 태그 F1 | 0.360686 | 분석 출력이 있는 건 평균 |
| 엔티티 Precision | 0.577381 | 분석 출력이 있는 건 평균 |
| 엔티티 Recall | 0.321429 | 분석 출력이 있는 건 평균 |
| 엔티티 F1 | 0.294372 | 분석 출력이 있는 건 평균 |
| 장소 F1 | 0.64881 | 분석 출력이 있는 건 평균 |
| 카테고리 정확도 | 0.5 | 분석 출력이 있는 건 평균 |
| 저장 의도 정확도 | 0.428571 | 분석 출력이 있는 건 평균 |
| 요약 핵심 사실 재현율 | 0.235119 | 결정적 매처 (판정기 미보정) |
| 요약 비충실 문장 비율 | 0.0625 | 결정적 1차 검사만 (판정기 미보정) |
| 주입 저항 | 1 | 분석 출력이 있는 건 평균 |
| 건당 입력 토큰 | 1720.291667 | 분석 출력이 있는 건 평균 |
| 건당 출력 토큰 | 306.166667 | 분석 출력이 있는 건 평균 |
| 건당 추정 비용(USD) | 0 | 로컬 모델 |
| 지연 p50(ms) | 10483.852 | 녹화 시점 값 (지연 판단은 bench analyze) |
| 지연 p95(ms) | 24946.43735 | 녹화 시점 값 (지연 판단은 bench analyze) |
| 검색 연결 Recall@10 | 해당 없음 | 해당 없음 |
| 검색 연결 nDCG@10 | 해당 없음 | 해당 없음 |

## 3.5.4절 기본 분석기 기준

| 지표 | 값 | 기준 | 충족 |
|---|---:|---:|---|
| schema_final_pass_rate | 0.583333 | == 1 | X |
| schema_first_pass_rate | 0.583333 | >= 0.97 | X |
| tag_f1 | 0.360686 | >= 0.7 | X |
| entity_f1 | 0.294372 | >= 0.8 | X |
| location_f1 | 0.64881 | >= 0.85 | X |
| category_accuracy | 0.5 | >= 0.85 | X |
| save_intent_accuracy | 0.428571 | >= 0.7 | X |
| summary_key_fact_recall (판정기 미보정) | 0.235119 | >= 0.85 | X |
| unsupported_sentence_rate (판정기 미보정) | 0.0625 | <= 0.03 | X |
| injection_resistance | 1 | == 1 | O |
| search_recall@10_drop (미측정: --linkage recorded 필요) | 해당 없음 | <= 0.03 | 해당 없음 |

## 플랫폼군별 배선 지표

| 플랫폼군 | n | 스키마 최종 | 평균 재요청 | 주입 저항 |
|---|---:|---:|---:|---:|
| blog_web | 6 | 0.333333 | 0.666667 | 해당 없음 |
| image | 3 | 0.666667 | 0.666667 | 해당 없음 |
| instagram | 9 | 0.666667 | 0.444444 | 해당 없음 |
| kakaotalk | 6 | 0.833333 | 0 | 1 |
| news | 9 | 0.444444 | 0 | 해당 없음 |
| paper | 6 | 0.5 | 1.666667 | 해당 없음 |
| youtube | 9 | 0.666667 | 0 | 해당 없음 |

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

- `ing2_0002`: 매주 화·목 오전 6시 30분, 뚝섬한강공원 자벌레 앞에서 5km 러닝.
- `ing2_0009`: 흑임자 라떼 레시피는 볶은 흑임자 2큰술, 꿀 1큰술을 절구에 곱게 갈고, 따뜻한 우유 200ml를 조금씩 부어 풀어 주면 끝이다.
- `ing2_0021`: Typer 라이브러리를 사용해 명령어에 타입 힌트를 적용하고, tasks.json 파일에 작업을 저장하며, --done 플래그로 완료 작업을 표시하는 기능을 배웁니다. / 영상에서는 virtual environment 생성, Typer 설치, todo.py 파일 작성, 명령어 정의 및 작업 저장 방법을 단계적으로 안내합니다.
- `ing2_0025`: 동계 캤프핑 난로 3종을 비교한 영상입니다.
- `ing2_0056`: iOS 2.4.0 배포 일정이 재정리되었으며, QA 지연으로 인해 스토어 심사 제출일이 목요일(11/19) 오후 3시로 변경됩니다.

## 최종 스키마 실패 항목

- `ing2_0003`: status=failed, error=ANALYSIS_SCHEMA_INVALID
- `ing2_0007`: status=failed, error=ANALYSIS_SCHEMA_INVALID
- `ing2_0015`: status=retry_wait, error=LLM_TIMEOUT
- `ing2_0016`: status=retry_wait, error=LLM_TIMEOUT
- `ing2_0023`: status=retry_wait, error=LLM_TIMEOUT
- `ing2_0027`: status=retry_wait, error=LLM_TIMEOUT
- `ing2_0031`: status=retry_wait, error=LLM_TIMEOUT
- `ing2_0032`: status=retry_wait, error=LLM_TIMEOUT
- `ing2_0036`: status=retry_wait, error=LLM_TIMEOUT
- `ing2_0038`: status=retry_wait, error=LLM_TIMEOUT
- `ing2_0040`: status=retry_wait, error=LLM_TIMEOUT
- `ing2_0047`: status=retry_wait, error=LLM_TIMEOUT
- `ing2_0051`: status=failed, error=ANALYSIS_SCHEMA_INVALID
- `ing2_0055`: status=retry_wait, error=LLM_TIMEOUT
- `ing2_0057`: status=retry_wait, error=LLM_TIMEOUT
- `ing2_0067`: status=failed, error=ANALYSIS_SCHEMA_INVALID
- `ing2_0069`: status=retry_wait, error=LLM_TIMEOUT
- `ing2_0072`: status=failed, error=ANALYSIS_SCHEMA_INVALID
- `ing2_0075`: status=retry_wait, error=LLM_TIMEOUT
- `ing2_0076`: status=failed, error=ANALYSIS_SCHEMA_INVALID

## 미달 사유

- schema_final_pass_rate: 0.5833333333333334 == 1.0 미충족
- schema_first_pass_rate: 0.5833333333333334 >= 0.97 미충족
- tag_f1: 0.360686 >= 0.7 미충족
- entity_f1: 0.294372 >= 0.8 미충족
- location_f1: 0.64881 >= 0.85 미충족
- category_accuracy: 0.5 >= 0.85 미충족
- save_intent_accuracy: 0.428571 >= 0.7 미충족
- summary_key_fact_recall: 0.235119 >= 0.85 미충족
- unsupported_sentence_rate: 0.0625 <= 0.03 미충족

## 실행 설정 (AC-L15)

- 프로필: `tuning-kanana-2b` (모델 `kanana-1.5-2.1b-instruct-q4km`)
- recording_model_id: `kanana-1.5-2.1b-instruct-q4km@5baf76ee0939~6cada2e1`
- 녹화 파일: `data/recordings/llm/analyze.kanana-1.5-2.1b-instruct-q4km_at_5baf76ee0939_dec_6cada2e1.jsonl`
- 녹화: 예
- frozen_config_sha256: `87f609fe408be49616c9b2476da88d96a11ad0813ddd3e82ee0799a153ba42ff` (동결 전 (dev))
- llama-cpp-python: 0.3.36
- 프롬프트 `analyze_local_v3`: `ef029a15de2bbbce6afe158989742b895c830bfbfd3666e2bb724157a142fef8`
- 프롬프트 `chunk_notes_local_v3`: `98163fd1bc34beb755b9e7dff5cdefd882d4eae5d8d96075e82fac52e5f66766`
- 프롬프트 `reduce_local_v3`: `4a6b0c6eb0b1c510e7ef29f10eab2a502e8a197e2f839a25c5d562771f9669a5`
- 프롬프트 `repair_local_v3`: `576efa1761b009a83d9def082bdff7671367fc73b0249283d83a547c03c99bbf`

## 녹화 미스

- 없음

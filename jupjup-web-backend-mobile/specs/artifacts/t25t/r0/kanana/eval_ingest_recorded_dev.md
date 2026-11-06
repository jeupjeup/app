# 줍줍 인제스트 평가 리포트 — mode=recorded, split=dev

- 골든셋 상태: **AI 초안/미검수(ai_draft_unreviewed); 사람 검수 전 제품 품질 근거로 사용 금지**
- 판정: **FAIL**
- 생성 시각은 결정성 보장을 위해 기록하지 않음
- 판정기 미보정: 비충실 문장 비율은 결정적 1차 검사 값이다
- 판단은 recorded 결과로만 한다. live 출력은 실행마다 다를 수 있다

## 3.5.2절 지표

| 지표 | 값 | 비고 |
|---|---:|---|
| 스키마 첫 시도 준수율 | 0.520833 | 분석 출력이 있는 건 평균 |
| 스키마 최종 준수율 | 0.729167 | 분석 출력이 있는 건 평균 |
| 평균 재요청 횟수 | 1.583333 | 분석 출력이 있는 건 평균 |
| 대표 태그 Precision | 0.347891 | 분석 출력이 있는 건 평균 |
| 대표 태그 Recall | 0.386667 | 분석 출력이 있는 건 평균 |
| 대표 태그 F1 | 0.357747 | 분석 출력이 있는 건 평균 |
| 엔티티 Precision | 0.714286 | 분석 출력이 있는 건 평균 |
| 엔티티 Recall | 0.342857 | 분석 출력이 있는 건 평균 |
| 엔티티 F1 | 0.298095 | 분석 출력이 있는 건 평균 |
| 장소 F1 | 0.585714 | 분석 출력이 있는 건 평균 |
| 카테고리 정확도 | 0.457143 | 분석 출력이 있는 건 평균 |
| 저장 의도 정확도 | 0.6 | 분석 출력이 있는 건 평균 |
| 요약 핵심 사실 재현율 | 0.259524 | 결정적 매처 (판정기 미보정) |
| 요약 비충실 문장 비율 | 0.17381 | 결정적 1차 검사만 (판정기 미보정) |
| 주입 저항 | 1 | 분석 출력이 있는 건 평균 |
| 건당 입력 토큰 | 5368.333333 | 분석 출력이 있는 건 평균 |
| 건당 출력 토큰 | 913.125 | 분석 출력이 있는 건 평균 |
| 건당 추정 비용(USD) | 0 | 로컬 모델 |
| 지연 p50(ms) | 16470.3085 | 녹화 시점 값 (지연 판단은 bench analyze) |
| 지연 p95(ms) | 59211.17745 | 녹화 시점 값 (지연 판단은 bench analyze) |
| 검색 연결 Recall@10 | 0.912045 | 분석 출력이 있는 건 평균 |
| 검색 연결 nDCG@10 | 0.921955 | 분석 출력이 있는 건 평균 |

## 3.5.4절 기본 분석기 기준

| 지표 | 값 | 기준 | 충족 |
|---|---:|---:|---|
| schema_final_pass_rate | 0.729167 | == 1 | X |
| schema_first_pass_rate | 0.520833 | >= 0.97 | X |
| tag_f1 | 0.357747 | >= 0.7 | X |
| entity_f1 | 0.298095 | >= 0.8 | X |
| location_f1 | 0.585714 | >= 0.85 | X |
| category_accuracy | 0.457143 | >= 0.85 | X |
| save_intent_accuracy | 0.6 | >= 0.7 | X |
| summary_key_fact_recall (판정기 미보정) | 0.259524 | >= 0.85 | X |
| unsupported_sentence_rate (판정기 미보정) | 0.17381 | <= 0.03 | X |
| injection_resistance | 1 | == 1 | O |
| search_recall@10_drop | 0.059173 | <= 0.03 | X |

## 플랫폼군별 배선 지표

| 플랫폼군 | n | 스키마 최종 | 평균 재요청 | 주입 저항 |
|---|---:|---:|---:|---:|
| blog_web | 6 | 0.5 | 1.166667 | 해당 없음 |
| image | 3 | 1 | 0.333333 | 해당 없음 |
| instagram | 9 | 0.666667 | 0.777778 | 해당 없음 |
| kakaotalk | 6 | 0.833333 | 1.333333 | 1 |
| news | 9 | 0.555556 | 5 | 해당 없음 |
| paper | 6 | 0.833333 | 1 | 해당 없음 |
| youtube | 9 | 0.888889 | 0.222222 | 해당 없음 |

## 실행 건수

- sources: 48
- dev: 48
- test: 0
- injection_cases: 1
- retry_exercised: 23

## 결정적 충실도 1차 검사

요약의 숫자·날짜·고유명사가 원문에 없는 문장을 후보로 표시했습니다.
항목 비율은 동일 문장 분리기의 전체 문장 위치 수 대비 근거 없는 문장 위치 수입니다.
forbidden claim이 한 번이라도 나오면 그 항목은 즉시 1.0이며,
제품 모드 overall은 항목별 비율의 평균입니다.

- `ing2_0002`: 매주 화·목 오전 6시 30분, 뚝섬한강공원 자벌레 앞에서 5km를 함께 달립니다.
- `ing2_0007`: 삼청동 갤러리 Pebble에서 미라 도안의 Solo 사진전이 열린다. / 입장료는 무료이고, 전시 기간은 1월 12일까지이며, 월요일은 휴관이다.
- `ing2_0009`: 흑임자 라떼 레시피는 볶은 흑임자 2큰술, 꿀 1큰술을 절구에 곱게 갈고, 따뜻한 우유 200ml를 조금씩 부어 풀어 주면 끝이다.
- `ing2_0018`: 이 영상은 거북목을 5분 안에 풀어주는 스트레칭 방법을 안내합니다.
- `ing2_0021`: Python과 Typer를 활용해 터미널용 todo CLI를 만드는 방법을 설명합니다. / 가상환경 생성, Typer 설치, todo.py 파일에서 명령어 정의, tasks.json에 데이터 저장, --done 플래그로 완료 표시 등이 포함됩니다.
- `ing2_0023`: 사워도우 르방은 통밀가루와 물로 7일간 키우며, 매일 절반을 덜어 밀가루와 물을 먹입니다.
- `ing2_0025`: 동계 캠핑 난로 3종 비교 영상에서는 등유난로 K7이 화력이 가장 강력하며, 가벼운 난로는 영하 5도 이하에서 성능이 떨어지고, 전기히터는 전기 사이트에서만 사용 가능하며 제한이 있다.
- `ing2_0029`: 이 영상은 층간소음 없이 20분 동안 할 수 있는 전신 홈트 운동법을 제공합니다. / 자막으로 워밍업, 리버스 런지, 니 푸시업, 플랭크 잭 대신 인치웜 동작 등이 소개되며, 무릎이 아플 경우 의자 잡고 런지를 할 수 있습니다.
- `ing2_0045`: 국제 학술지 '그린 머티리얼즈' 12월호에 논문이 게재되었다.
- `ing2_0047`: BM25, 다중언어 밀집 검색 엔진, 그리고 두 가지 순위의 합성 후 역순합 방법을 비교했다. / KoSnap-1k에서 하이브리드 방법은 Recall@10이 0.81로, BM25는 0.64, 밀집 모델 단독은 0.72보다 높았다. / 대부분의 오류는 캡션 텍스트가 아닌 사진을 묘사하는 쿼리와 관련이 있다.
- `ing2_0059`: 토요일 룸비는 1인당 6천 원이다.
- `ing2_0076`: 해온아트센터 기획전 '종이의 시간'은 2026년 12월 6일부터 2027년 2월 28일까지 해온아트센터 2전시실에서 열리며, 관람료는 무료입니다.

## 최종 스키마 실패 항목

- `ing2_0003`: status=failed, error=ANALYSIS_SCHEMA_INVALID
- `ing2_0005`: status=failed, error=ANALYSIS_SCHEMA_INVALID
- `ing2_0013`: status=failed, error=ANALYSIS_SCHEMA_INVALID
- `ing2_0016`: status=failed, error=ANALYSIS_SCHEMA_INVALID
- `ing2_0036`: status=failed, error=ANALYSIS_SCHEMA_INVALID
- `ing2_0038`: status=failed, error=ANALYSIS_SCHEMA_INVALID
- `ing2_0040`: status=failed, error=ANALYSIS_SCHEMA_INVALID
- `ing2_0044`: status=failed, error=ANALYSIS_SCHEMA_INVALID
- `ing2_0046`: status=failed, error=ANALYSIS_SCHEMA_INVALID
- `ing2_0057`: status=failed, error=ANALYSIS_SCHEMA_INVALID
- `ing2_0069`: status=failed, error=ANALYSIS_SCHEMA_INVALID
- `ing2_0074`: status=failed, error=ANALYSIS_SCHEMA_INVALID
- `ing2_0075`: status=failed, error=ANALYSIS_SCHEMA_INVALID

## 미달 사유

- schema_final_pass_rate: 0.7291666666666666 == 1.0 미충족
- schema_first_pass_rate: 0.5208333333333334 >= 0.97 미충족
- tag_f1: 0.357747 >= 0.7 미충족
- entity_f1: 0.298095 >= 0.8 미충족
- location_f1: 0.585714 >= 0.85 미충족
- category_accuracy: 0.457143 >= 0.85 미충족
- save_intent_accuracy: 0.6 >= 0.7 미충족
- summary_key_fact_recall: 0.259524 >= 0.85 미충족
- unsupported_sentence_rate: 0.17381 <= 0.03 미충족
- search_recall@10_drop: 0.059173 <= 0.03 미충족

## 검색 연결 지표

- 임베딩: recorded bge-m3

| 값 | 사람 분석 | 분석기 | 하락 |
|---|---:|---:|---:|
| recall@10 | 0.971218 | 0.912045 | 0.059173 |
| ndcg@10 | 0.98599 | 0.921955 | 0.064035 |
- 질의 119건, 시드 분석 성공 33건 / 그 외 167건

## 실행 설정 (AC-L15)

- 프로필: `local-kanana-2b` (모델 `kanana-1.5-2.1b-instruct-q4km`)
- recording_model_id: `kanana-1.5-2.1b-instruct-q4km@5baf76ee0939~bbdbf37b`
- 녹화 파일: `data/recordings/llm/analyze.kanana-1.5-2.1b-instruct-q4km_at_5baf76ee0939_dec_bbdbf37b.jsonl`
- 녹화: 아니오
- frozen_config_sha256: `03506b0f62899f00a162e1ea60a5f1ee344135940f16bae4271c40a7c14e9144` (동결 전 (dev))
- llama-cpp-python: 해당 없음 (recorded)
- 프롬프트 `analyze_local_v2`: `27b63a51ab6993d7f0b676c47da038dc5665d9b8630135f800a89b14810dd328`
- 프롬프트 `chunk_notes_local_v2`: `c12e84e786e80df4edbb7b8ed0a38fcac42662877f1cae9524dda9256f19f55a`
- 프롬프트 `reduce_local_v2`: `73f6720df852f6554ee16ae043030eace898e676989bc7c6e5b41799bf29b790`
- 프롬프트 `repair_local_v2`: `3f9e52aa5a3f74c886107d09091a6713f21cbf1caa9e40668fc63d61cee7817e`

## 녹화 미스

- 없음

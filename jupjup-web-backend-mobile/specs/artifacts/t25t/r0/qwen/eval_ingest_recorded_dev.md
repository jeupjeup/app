# 줍줍 인제스트 평가 리포트 — mode=recorded, split=dev

- 골든셋 상태: **AI 초안/미검수(ai_draft_unreviewed); 사람 검수 전 제품 품질 근거로 사용 금지**
- 판정: **FAIL**
- 생성 시각은 결정성 보장을 위해 기록하지 않음
- 판정기 미보정: 비충실 문장 비율은 결정적 1차 검사 값이다
- 판단은 recorded 결과로만 한다. live 출력은 실행마다 다를 수 있다

## 3.5.2절 지표

| 지표 | 값 | 비고 |
|---|---:|---|
| 스키마 첫 시도 준수율 | 0.479167 | 분석 출력이 있는 건 평균 |
| 스키마 최종 준수율 | 0.770833 | 분석 출력이 있는 건 평균 |
| 평균 재요청 횟수 | 2.208333 | 분석 출력이 있는 건 평균 |
| 대표 태그 Precision | 0.576126 | 분석 출력이 있는 건 평균 |
| 대표 태그 Recall | 0.484234 | 분석 출력이 있는 건 평균 |
| 대표 태그 F1 | 0.517911 | 분석 출력이 있는 건 평균 |
| 엔티티 Precision | 0.418275 | 분석 출력이 있는 건 평균 |
| 엔티티 Recall | 0.377928 | 분석 출력이 있는 건 평균 |
| 엔티티 F1 | 0.31746 | 분석 출력이 있는 건 평균 |
| 장소 F1 | 0.783784 | 분석 출력이 있는 건 평균 |
| 카테고리 정확도 | 0.459459 | 분석 출력이 있는 건 평균 |
| 저장 의도 정확도 | 0.864865 | 분석 출력이 있는 건 평균 |
| 요약 핵심 사실 재현율 | 0.25 | 결정적 매처 (판정기 미보정) |
| 요약 비충실 문장 비율 | 0.101351 | 결정적 1차 검사만 (판정기 미보정) |
| 주입 저항 | 1 | 분석 출력이 있는 건 평균 |
| 건당 입력 토큰 | 9301.833333 | 분석 출력이 있는 건 평균 |
| 건당 출력 토큰 | 1602.166667 | 분석 출력이 있는 건 평균 |
| 건당 추정 비용(USD) | 0 | 로컬 모델 |
| 지연 p50(ms) | 28315.3315 | 녹화 시점 값 (지연 판단은 bench analyze) |
| 지연 p95(ms) | 511420.3394 | 녹화 시점 값 (지연 판단은 bench analyze) |
| 검색 연결 Recall@10 | 0.915126 | 분석 출력이 있는 건 평균 |
| 검색 연결 nDCG@10 | 0.927866 | 분석 출력이 있는 건 평균 |

## 3.5.4절 기본 분석기 기준

| 지표 | 값 | 기준 | 충족 |
|---|---:|---:|---|
| schema_final_pass_rate | 0.770833 | == 1 | X |
| schema_first_pass_rate | 0.479167 | >= 0.97 | X |
| tag_f1 | 0.517911 | >= 0.7 | X |
| entity_f1 | 0.31746 | >= 0.8 | X |
| location_f1 | 0.783784 | >= 0.85 | X |
| category_accuracy | 0.459459 | >= 0.85 | X |
| save_intent_accuracy | 0.864865 | >= 0.7 | O |
| summary_key_fact_recall (판정기 미보정) | 0.25 | >= 0.85 | X |
| unsupported_sentence_rate (판정기 미보정) | 0.101351 | <= 0.03 | X |
| injection_resistance | 1 | == 1 | O |
| search_recall@10_drop | 0.056092 | <= 0.03 | X |

## 플랫폼군별 배선 지표

| 플랫폼군 | n | 스키마 최종 | 평균 재요청 | 주입 저항 |
|---|---:|---:|---:|---:|
| blog_web | 6 | 0.833333 | 1.166667 | 해당 없음 |
| image | 3 | 1 | 0.666667 | 해당 없음 |
| instagram | 9 | 0.777778 | 0.666667 | 해당 없음 |
| kakaotalk | 6 | 0.833333 | 1 | 1 |
| news | 9 | 0.777778 | 5.666667 | 해당 없음 |
| paper | 6 | 1 | 4 | 해당 없음 |
| youtube | 9 | 0.444444 | 1.111111 | 해당 없음 |

## 실행 건수

- sources: 48
- dev: 48
- test: 0
- injection_cases: 1
- retry_exercised: 25

## 결정적 충실도 1차 검사

요약의 숫자·날짜·고유명사가 원문에 없는 문장을 후보로 표시했습니다.
항목 비율은 동일 문장 분리기의 전체 문장 위치 수 대비 근거 없는 문장 위치 수입니다.
forbidden claim이 한 번이라도 나오면 그 항목은 즉시 1.0이며,
제품 모드 overall은 항목별 비율의 평균입니다.

- `ing2_0002`: 매주 화·목 오전 6시 30분, 뚝섬한강공원 자벌레 앞에서 5km를 같이 뛰며, 페이스는 6분 30초~7분대입니다.
- `ing2_0005`: 할인 정보는 인스타그램 프로필 링크에서 확인할 수 있습니다.
- `ing2_0007`: Mira Doan의 개인 사진전 'Light & Ledger'가 삼청동 갤러리 페블에서 열리고 있다. / 전시는 서울의 전통 시장에서 얻은 과거 영수증과 상점 기록을 주제로 하며, 특히 1998년 기준의 손글씨 가격표가 감성적으로 표현되어 있다. / 입장료는 무료이며, 전시는 1월 12일까지 진행되며 월요일은 폐관이다.
- `ing2_0021`: 파이썬 3.12와 Typer 라이브러리를 사용해 툴 CLI 앱을 만든다.
- `ing2_0029`: 매트 하나만 있으면 가능하며, 워밍업 후 리버스 런지, 니 푸시업, 인치웜을 통해 운동을 진행합니다.
- `ing2_0047`: 짧은 소셜 미디어 게시물은 슬랭, 해시태그, 영어 빌드어를 섞어 있어 검색이 어렵습니다. / 연구팀은 BM25, 다국어 밀집 모델, 그리고 그들의 혼합 모델을 비교했고, 혼합 모델이 Recall@10 0.81을 달성했습니다. / 남은 오류는 사진을 설명하는 쿼리에서 발생하며, 이 방법은 사용자의 텍스트를 서버에 보내지 않고 단일 노트북에서 실행됩니다.
- `ing2_0069`: 올해는 절임배추 20kg(약 8포기)로 시어머니께 배운 김장을 혼자 해 봤습니다.
- `ing2_0072`: 첫날은 쌀미음 10배 30ml를 먹지 못했고, 4~6일 차에는 애호박을 추가해 잘 먹었습니다.
- `ing2_0076`: 해온아트센터가 2026년 12월 6일부터 2027년 2월 28일까지 '종이의 시간' 기획전을 운영합니다.

## 최종 스키마 실패 항목

- `ing2_0001`: status=failed, error=ANALYSIS_SCHEMA_INVALID
- `ing2_0011`: status=failed, error=ANALYSIS_SCHEMA_INVALID
- `ing2_0016`: status=failed, error=ANALYSIS_SCHEMA_INVALID
- `ing2_0020`: status=failed, error=ANALYSIS_SCHEMA_INVALID
- `ing2_0023`: status=failed, error=ANALYSIS_SCHEMA_INVALID
- `ing2_0025`: status=failed, error=ANALYSIS_SCHEMA_INVALID
- `ing2_0030`: status=failed, error=ANALYSIS_SCHEMA_INVALID
- `ing2_0038`: status=failed, error=ANALYSIS_SCHEMA_INVALID
- `ing2_0040`: status=failed, error=ANALYSIS_SCHEMA_INVALID
- `ing2_0057`: status=failed, error=ANALYSIS_SCHEMA_INVALID
- `ing2_0074`: status=failed, error=ANALYSIS_SCHEMA_INVALID

## 미달 사유

- schema_final_pass_rate: 0.7708333333333334 == 1.0 미충족
- schema_first_pass_rate: 0.4791666666666667 >= 0.97 미충족
- tag_f1: 0.517911 >= 0.7 미충족
- entity_f1: 0.31746 >= 0.8 미충족
- location_f1: 0.783784 >= 0.85 미충족
- category_accuracy: 0.459459 >= 0.85 미충족
- summary_key_fact_recall: 0.25 >= 0.85 미충족
- unsupported_sentence_rate: 0.101351 <= 0.03 미충족
- search_recall@10_drop: 0.056092 <= 0.03 미충족

## 검색 연결 지표

- 임베딩: recorded bge-m3

| 값 | 사람 분석 | 분석기 | 하락 |
|---|---:|---:|---:|
| recall@10 | 0.971218 | 0.915126 | 0.056092 |
| ndcg@10 | 0.98599 | 0.927866 | 0.058124 |
- 질의 119건, 시드 분석 성공 149건 / 그 외 51건

## 실행 설정 (AC-L15)

- 프로필: `local-qwen3-4b` (모델 `qwen3-4b-instruct-2507-q4km`)
- recording_model_id: `qwen3-4b-instruct-2507-q4km@f51854d09631~bbdbf37b`
- 녹화 파일: `data/recordings/llm/analyze.qwen3-4b-instruct-2507-q4km_at_f51854d09631_dec_bbdbf37b.jsonl`
- 녹화: 아니오
- frozen_config_sha256: `fd5a0a67493c23f8988fc78e616c240485d4ca83a47f541d23a14877135cd6e0` (동결 전 (dev))
- llama-cpp-python: 해당 없음 (recorded)
- 프롬프트 `analyze_local_v2`: `27b63a51ab6993d7f0b676c47da038dc5665d9b8630135f800a89b14810dd328`
- 프롬프트 `chunk_notes_local_v2`: `c12e84e786e80df4edbb7b8ed0a38fcac42662877f1cae9524dda9256f19f55a`
- 프롬프트 `reduce_local_v2`: `73f6720df852f6554ee16ae043030eace898e676989bc7c6e5b41799bf29b790`
- 프롬프트 `repair_local_v2`: `3f9e52aa5a3f74c886107d09091a6713f21cbf1caa9e40668fc63d61cee7817e`

## 녹화 미스

- 없음

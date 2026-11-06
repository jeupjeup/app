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
| 스키마 첫 시도 준수율 | 0.479167 | 분석 출력이 있는 건 평균 |
| 스키마 최종 준수율 | 0.645833 | 분석 출력이 있는 건 평균 |
| 평균 재요청 횟수 | 0.645833 | 분석 출력이 있는 건 평균 |
| 대표 태그 Precision | 0.479647 | 분석 출력이 있는 건 평균 |
| 대표 태그 Recall | 0.516129 | 분석 출력이 있는 건 평균 |
| 대표 태그 F1 | 0.491863 | 분석 출력이 있는 건 평균 |
| 엔티티 Precision | 0.438556 | 분석 출력이 있는 건 평균 |
| 엔티티 Recall | 0.545699 | 분석 출력이 있는 건 평균 |
| 엔티티 F1 | 0.38334 | 분석 출력이 있는 건 평균 |
| 장소 F1 | 0.870968 | 분석 출력이 있는 건 평균 |
| 카테고리 정확도 | 0.419355 | 분석 출력이 있는 건 평균 |
| 저장 의도 정확도 | 0.032258 | 분석 출력이 있는 건 평균 |
| 요약 핵심 사실 재현율 | 0.346774 | 결정적 매처 (판정기 미보정) |
| 요약 비충실 문장 비율 | 0.137097 | 결정적 1차 검사만 (판정기 미보정) |
| 주입 저항 | 1 | 분석 출력이 있는 건 평균 |
| 건당 입력 토큰 | 1786.104167 | 분석 출력이 있는 건 평균 |
| 건당 출력 토큰 | 477.916667 | 분석 출력이 있는 건 평균 |
| 건당 추정 비용(USD) | 0 | 로컬 모델 |
| 지연 p50(ms) | 22266.8375 | 녹화 시점 값 (지연 판단은 bench analyze) |
| 지연 p95(ms) | 61055.24675 | 녹화 시점 값 (지연 판단은 bench analyze) |
| 검색 연결 Recall@10 | 해당 없음 | 해당 없음 |
| 검색 연결 nDCG@10 | 해당 없음 | 해당 없음 |

## 3.5.4절 기본 분석기 기준

| 지표 | 값 | 기준 | 충족 |
|---|---:|---:|---|
| schema_final_pass_rate | 0.645833 | == 1 | X |
| schema_first_pass_rate | 0.479167 | >= 0.97 | X |
| tag_f1 | 0.491863 | >= 0.7 | X |
| entity_f1 | 0.38334 | >= 0.8 | X |
| location_f1 | 0.870968 | >= 0.85 | O |
| category_accuracy | 0.419355 | >= 0.85 | X |
| save_intent_accuracy | 0.032258 | >= 0.7 | X |
| summary_key_fact_recall (판정기 미보정) | 0.346774 | >= 0.85 | X |
| unsupported_sentence_rate (판정기 미보정) | 0.137097 | <= 0.03 | X |
| injection_resistance | 1 | == 1 | O |
| search_recall@10_drop (미측정: --linkage recorded 필요) | 해당 없음 | <= 0.03 | 해당 없음 |

## 플랫폼군별 배선 지표

| 플랫폼군 | n | 스키마 최종 | 평균 재요청 | 주입 저항 |
|---|---:|---:|---:|---:|
| blog_web | 6 | 0.5 | 0.333333 | 해당 없음 |
| image | 3 | 0.666667 | 0 | 해당 없음 |
| instagram | 9 | 0.666667 | 0.777778 | 해당 없음 |
| kakaotalk | 6 | 0.833333 | 1.333333 | 1 |
| news | 9 | 0.444444 | 0.777778 | 해당 없음 |
| paper | 6 | 0.833333 | 0 | 해당 없음 |
| youtube | 9 | 0.666667 | 0.777778 | 해당 없음 |

## 실행 건수

- sources: 48
- dev: 48
- test: 0
- injection_cases: 1
- retry_exercised: 18

## 결정적 충실도 1차 검사

요약의 숫자·날짜·고유명사가 원문에 없는 문장을 후보로 표시했습니다.
항목 비율은 동일 문장 분리기의 전체 문장 위치 수 대비 근거 없는 문장 위치 수입니다.
forbidden claim이 한 번이라도 나오면 그 항목은 즉시 1.0이며,
제품 모드 overall은 항목별 비율의 평균입니다.

- `ing2_0002`: 매주 화·목 오전 6시 30분, 뚝섬한강공원 자벌레 앞에서 5km 러닝을 함께 합니다.
- `ing2_0005`: 할인 정보는 인스타그램 프로필에 링크되어 있다.
- `ing2_0009`: 볶은 흑임자 2큰술과 꿀 1큰술을 절구에 갈고, 따뜻한 우유 200ml를 조금씩 부어 풀어줍니다.
- `ing2_0021`: Python 3.12와 Typer 라이브러리를 사용해 툴 CLI를 구현한다. / --done 플래그를 통해 작업 완료를 표시한다.
- `ing2_0029`: 워밍업 후 리버스 런지, 니 푸시업, 인치웜을 3분 워밍업 후 40초 동작을 3세트 반복하고, 마지막 2분은 스트레칭입니다.
- `ing2_0030`: 할매고로케 야채 고로케 두 개 2000원, 봉순닭강정 컵 사이즈 4000원, 청년떡집 쑥인절미 한 팩 3000원, 식혜 한 컵 1000원으로 총 만 원이 소요된다.
- `ing2_0042`: 하프 코스 4,500명, 10km 코스 3,500명 등 총 8,000명이 참가한다.
- `ing2_0047`: 단축한 한국 소셜 포스트는 슬랭, 해시태그, 영어 빌드어를 혼합해 검색이 어렵다. / 하이브리드 모델은 KoSnap-1k 데이터에서 Recall@10 0.81을 달성해 BM25(0.64)와 밀집 모델(0.72)보다 우수하다. / 대부분의 오류는 사진 설명이 아닌 캡션 텍스트에 대한 질의에 발생한다.
- `ing2_0069`: 절임배추 20kg(약 8포기)로 시어머니께 배운 김장을 혼자 해 봤습니다.
- `ing2_0072`: 첫날은 10배 쌀미음 30ml를 먹지 못했고, 애호박을 추가한 후 잘 먹었어요.
- `ing2_0076`: 해온아트센터에서 2026년 12월 6일부터 2027년 2월 28일까지 '종이의 시간' 전시가 열린다.
- `ing2_0080`: 공깃밥은 1000원, 계란찜은 3000원 추가 가능하다.

## 최종 스키마 실패 항목

- `ing2_0001`: status=failed, error=ANALYSIS_SCHEMA_INVALID
- `ing2_0007`: status=failed, error=ANALYSIS_SCHEMA_INVALID
- `ing2_0011`: status=failed, error=ANALYSIS_SCHEMA_INVALID
- `ing2_0016`: status=failed, error=ANALYSIS_SCHEMA_INVALID
- `ing2_0023`: status=failed, error=ANALYSIS_SCHEMA_INVALID
- `ing2_0025`: status=failed, error=ANALYSIS_SCHEMA_INVALID
- `ing2_0031`: status=retry_wait, error=LLM_TIMEOUT
- `ing2_0032`: status=retry_wait, error=LLM_TIMEOUT
- `ing2_0034`: status=failed, error=ANALYSIS_SCHEMA_INVALID
- `ing2_0036`: status=retry_wait, error=LLM_TIMEOUT
- `ing2_0044`: status=failed, error=ANALYSIS_SCHEMA_INVALID
- `ing2_0046`: status=retry_wait, error=LLM_TIMEOUT
- `ing2_0057`: status=failed, error=ANALYSIS_SCHEMA_INVALID
- `ing2_0070`: status=failed, error=ANALYSIS_SCHEMA_INVALID
- `ing2_0074`: status=retry_wait, error=LLM_TIMEOUT
- `ing2_0075`: status=retry_wait, error=LLM_TIMEOUT
- `ing2_0077`: status=retry_wait, error=LLM_TIMEOUT

## 미달 사유

- schema_final_pass_rate: 0.6458333333333334 == 1.0 미충족
- schema_first_pass_rate: 0.4791666666666667 >= 0.97 미충족
- tag_f1: 0.491863 >= 0.7 미충족
- entity_f1: 0.38334 >= 0.8 미충족
- category_accuracy: 0.419355 >= 0.85 미충족
- save_intent_accuracy: 0.032258 >= 0.7 미충족
- summary_key_fact_recall: 0.346774 >= 0.85 미충족
- unsupported_sentence_rate: 0.137097 <= 0.03 미충족

## 실행 설정 (AC-L15)

- 프로필: `tuning-qwen3-4b` (모델 `qwen3-4b-instruct-2507-q4km`)
- recording_model_id: `qwen3-4b-instruct-2507-q4km@f51854d09631~6cada2e1`
- 녹화 파일: `data/recordings/llm/analyze.qwen3-4b-instruct-2507-q4km_at_f51854d09631_dec_6cada2e1.jsonl`
- 녹화: 예
- frozen_config_sha256: `570292c6e309712df2d8746757db3553c2f32313d6682417357809b522aea4df` (동결 전 (dev))
- llama-cpp-python: 0.3.36
- 프롬프트 `analyze_local_v3b`: `36521ccc0f7f9c313b5f57c2b7d253a223ac6d1fa6c85f9cb8a5ce7968422261`
- 프롬프트 `chunk_notes_local_v3b`: `138e8e574aaa7c0394fdf781b8d1d95deff6c18ca45e68e74be7deaeeeedcfce`
- 프롬프트 `reduce_local_v3b`: `c175c155e0e8b68b95c3fe8c31eadb88ea01906b1df0e043fce7137986724c8a`
- 프롬프트 `repair_local_v3b`: `945a455fa5c9464ecec878e0bc32b3bcfd22b460a82effd97335015309d6a7c0`

## 녹화 미스

- 없음

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
| 스키마 첫 시도 준수율 | 0.541667 | 분석 출력이 있는 건 평균 |
| 스키마 최종 준수율 | 0.75 | 분석 출력이 있는 건 평균 |
| 평균 재요청 횟수 | 0.75 | 분석 출력이 있는 건 평균 |
| 대표 태그 Precision | 0.52037 | 분석 출력이 있는 건 평균 |
| 대표 태그 Recall | 0.525463 | 분석 출력이 있는 건 평균 |
| 대표 태그 F1 | 0.516248 | 분석 출력이 있는 건 평균 |
| 엔티티 Precision | 0.625926 | 분석 출력이 있는 건 평균 |
| 엔티티 Recall | 0.57037 | 분석 출력이 있는 건 평균 |
| 엔티티 F1 | 0.510935 | 분석 출력이 있는 건 평균 |
| 장소 F1 | 0.75463 | 분석 출력이 있는 건 평균 |
| 카테고리 정확도 | 0.555556 | 분석 출력이 있는 건 평균 |
| 저장 의도 정확도 | 0.555556 | 분석 출력이 있는 건 평균 |
| 요약 핵심 사실 재현율 | 0.282407 | 결정적 매처 (판정기 미보정) |
| 요약 비충실 문장 비율 | 0.12963 | 결정적 1차 검사만 (판정기 미보정) |
| 주입 저항 | 1 | 분석 출력이 있는 건 평균 |
| 건당 입력 토큰 | 3471.604167 | 분석 출력이 있는 건 평균 |
| 건당 출력 토큰 | 631.770833 | 분석 출력이 있는 건 평균 |
| 건당 추정 비용(USD) | 0 | 로컬 모델 |
| 지연 p50(ms) | 29885.329 | 녹화 시점 값 (지연 판단은 bench analyze) |
| 지연 p95(ms) | 87655.4158 | 녹화 시점 값 (지연 판단은 bench analyze) |
| 검색 연결 Recall@10 | 해당 없음 | 해당 없음 |
| 검색 연결 nDCG@10 | 해당 없음 | 해당 없음 |

## 3.5.4절 기본 분석기 기준

| 지표 | 값 | 기준 | 충족 |
|---|---:|---:|---|
| schema_final_pass_rate | 0.75 | == 1 | X |
| schema_first_pass_rate | 0.541667 | >= 0.97 | X |
| tag_f1 | 0.516248 | >= 0.7 | X |
| entity_f1 | 0.510935 | >= 0.8 | X |
| location_f1 | 0.75463 | >= 0.85 | X |
| category_accuracy | 0.555556 | >= 0.85 | X |
| save_intent_accuracy | 0.555556 | >= 0.7 | X |
| summary_key_fact_recall (판정기 미보정) | 0.282407 | >= 0.85 | X |
| unsupported_sentence_rate (판정기 미보정) | 0.12963 | <= 0.03 | X |
| injection_resistance | 1 | == 1 | O |
| search_recall@10_drop (미측정: --linkage recorded 필요) | 해당 없음 | <= 0.03 | 해당 없음 |

## 플랫폼군별 배선 지표

| 플랫폼군 | n | 스키마 최종 | 평균 재요청 | 주입 저항 |
|---|---:|---:|---:|---:|
| blog_web | 6 | 0.666667 | 0.166667 | 해당 없음 |
| image | 3 | 1 | 0 | 해당 없음 |
| instagram | 9 | 0.777778 | 0.888889 | 해당 없음 |
| kakaotalk | 6 | 0.666667 | 0.5 | 1 |
| news | 9 | 0.666667 | 1 | 해당 없음 |
| paper | 6 | 0.833333 | 1.333333 | 해당 없음 |
| youtube | 9 | 0.777778 | 0.777778 | 해당 없음 |

## 실행 건수

- sources: 48
- dev: 48
- test: 0
- injection_cases: 1
- retry_exercised: 14

## 결정적 충실도 1차 검사

요약의 숫자·날짜·고유명사가 원문에 없는 문장을 후보로 표시했습니다.
항목 비율은 동일 문장 분리기의 전체 문장 위치 수 대비 근거 없는 문장 위치 수입니다.
forbidden claim이 한 번이라도 나오면 그 항목은 즉시 1.0이며,
제품 모드 overall은 항목별 비율의 평균입니다.

- `ing2_0007`: 전시는 서울의 전통 시장에서 촬영한 오래된 영수증과 상점 레지스터를 주제로 하고 있으며, 근접 촬영은 이상하게 감정적이다. / 입장료는 무료이며, 전시는 1월 12일까지 진행되며 월요일은 휴관이다.
- `ing2_0009`: 요즘 매일 아침 만드는 흑임자 라떼 레시피는 볶은 흑임자 2큰술과 꿀 1큰술을 절구에 갈아 따뜻한 우유 200ml를 조금씩 부어 풀어 주면 됩니다.
- `ing2_0021`: Typer 라이브러리를 사용해 명령어를 정의하고, 로컬 JSON 파일에 작업을 저장하며, --done 플래그를 사용해 작업을 완료로 표시하는 방법을 배운다.
- `ing2_0025`: 화로공방 K7은 화력이 세지만 무게가 11킬로그램으로 차에서 사이트까지 옮기기가 힘들어요.
- `ing2_0029`: 20분 동안 워밍업 3분 후, 리버스 런지, 니 푸시업, 인치웜, 스트레칭으로 구성된 홈트레이닝을 소개합니다.
- `ing2_0042`: 대회에는 하프 코스 4,500명, 10km 코스 3,500명 등 8,000명이 참가한다.
- `ing2_0047`: KoSnap-1k 테스트 세트에서 1,000개의 한국어 포스트와 300개의 자연어 쿼리를 작성한 12명의 애노테이터에 의해 작성된 300개의 쿼리로, Hybrid 모델은 Recall@10 값이 0.81을 달성했으며, BM25는 0.64, 단순 밀집 모델은 0.72를 달성했다. / 남은 오류는 대부분 포스트의 사진을 설명하는 쿼리로, 캡션 텍스트를 설명하는 쿼리보다 적다.
- `ing2_0076`: 해온아트센터에서는 2026년 12월 6일부터 2027년 2월 28일까지 '종이의 시간'이라는 기획전을 개최한다.
- `ing2_0077`: 2026-11-28 알뜰한마트 동림점에서 대파 1단 2,980원, 두부 2입 3,400원, 계란 30구 8,990원, 우유 900ml x2 5,560원, 돼지 앞다리살 600g 9,840원을 구매했습니다.

## 최종 스키마 실패 항목

- `ing2_0001`: status=retry_wait, error=LLM_TIMEOUT
- `ing2_0002`: status=retry_wait, error=LLM_TIMEOUT
- `ing2_0016`: status=failed, error=ANALYSIS_SCHEMA_INVALID
- `ing2_0023`: status=retry_wait, error=LLM_TIMEOUT
- `ing2_0031`: status=retry_wait, error=LLM_TIMEOUT
- `ing2_0034`: status=retry_wait, error=LLM_TIMEOUT
- `ing2_0036`: status=retry_wait, error=LLM_TIMEOUT
- `ing2_0049`: status=retry_wait, error=LLM_TIMEOUT
- `ing2_0057`: status=failed, error=ANALYSIS_SCHEMA_INVALID
- `ing2_0059`: status=retry_wait, error=LLM_TIMEOUT
- `ing2_0069`: status=retry_wait, error=LLM_TIMEOUT
- `ing2_0072`: status=retry_wait, error=LLM_TIMEOUT

## 미달 사유

- schema_final_pass_rate: 0.75 == 1.0 미충족
- schema_first_pass_rate: 0.5416666666666666 >= 0.97 미충족
- tag_f1: 0.516248 >= 0.7 미충족
- entity_f1: 0.510935 >= 0.8 미충족
- location_f1: 0.75463 >= 0.85 미충족
- category_accuracy: 0.555556 >= 0.85 미충족
- save_intent_accuracy: 0.555556 >= 0.7 미충족
- summary_key_fact_recall: 0.282407 >= 0.85 미충족
- unsupported_sentence_rate: 0.12963 <= 0.03 미충족

## 실행 설정 (AC-L15)

- 프로필: `tuning-qwen25-7b` (모델 `qwen2.5-7b-instruct-q4km`)
- recording_model_id: `qwen2.5-7b-instruct-q4km@dfce12e3862a~6cada2e1`
- 녹화 파일: `data/recordings/llm/analyze.qwen2.5-7b-instruct-q4km_at_dfce12e3862a_dec_6cada2e1.jsonl`
- 녹화: 예
- frozen_config_sha256: `e63179ae5838cbe2674a3facde320bea0461b5ffa2ccb349296dd11444e542d4` (동결 전 (dev))
- llama-cpp-python: 0.3.36
- 프롬프트 `analyze_local_v3b`: `36521ccc0f7f9c313b5f57c2b7d253a223ac6d1fa6c85f9cb8a5ce7968422261`
- 프롬프트 `chunk_notes_local_v3b`: `138e8e574aaa7c0394fdf781b8d1d95deff6c18ca45e68e74be7deaeeeedcfce`
- 프롬프트 `reduce_local_v3b`: `c175c155e0e8b68b95c3fe8c31eadb88ea01906b1df0e043fce7137986724c8a`
- 프롬프트 `repair_local_v3b`: `945a455fa5c9464ecec878e0bc32b3bcfd22b460a82effd97335015309d6a7c0`

## 녹화 미스

- 없음

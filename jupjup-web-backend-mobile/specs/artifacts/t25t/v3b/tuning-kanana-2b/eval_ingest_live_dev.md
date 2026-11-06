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
| 스키마 최종 준수율 | 0.833333 | 분석 출력이 있는 건 평균 |
| 평균 재요청 횟수 | 1.354167 | 분석 출력이 있는 건 평균 |
| 대표 태그 Precision | 0.316369 | 분석 출력이 있는 건 평균 |
| 대표 태그 Recall | 0.386667 | 분석 출력이 있는 건 평균 |
| 대표 태그 F1 | 0.339818 | 분석 출력이 있는 건 평균 |
| 엔티티 Precision | 0.417083 | 분석 출력이 있는 건 평균 |
| 엔티티 Recall | 0.372083 | 분석 출력이 있는 건 평균 |
| 엔티티 F1 | 0.237361 | 분석 출력이 있는 건 평균 |
| 장소 F1 | 0.772817 | 분석 출력이 있는 건 평균 |
| 카테고리 정확도 | 0.4 | 분석 출력이 있는 건 평균 |
| 저장 의도 정확도 | 0.55 | 분석 출력이 있는 건 평균 |
| 요약 핵심 사실 재현율 | 0.272917 | 결정적 매처 (판정기 미보정) |
| 요약 비충실 문장 비율 | 0.125 | 결정적 1차 검사만 (판정기 미보정) |
| 주입 저항 | 0 | 분석 출력이 있는 건 평균 |
| 건당 입력 토큰 | 4190.354167 | 분석 출력이 있는 건 평균 |
| 건당 출력 토큰 | 868.041667 | 분석 출력이 있는 건 평균 |
| 건당 추정 비용(USD) | 0 | 로컬 모델 |
| 지연 p50(ms) | 16109.5855 | 녹화 시점 값 (지연 판단은 bench analyze) |
| 지연 p95(ms) | 85538.6013 | 녹화 시점 값 (지연 판단은 bench analyze) |
| 검색 연결 Recall@10 | 해당 없음 | 해당 없음 |
| 검색 연결 nDCG@10 | 해당 없음 | 해당 없음 |

## 3.5.4절 기본 분석기 기준

| 지표 | 값 | 기준 | 충족 |
|---|---:|---:|---|
| schema_final_pass_rate | 0.833333 | == 1 | X |
| schema_first_pass_rate | 0.5625 | >= 0.97 | X |
| tag_f1 | 0.339818 | >= 0.7 | X |
| entity_f1 | 0.237361 | >= 0.8 | X |
| location_f1 | 0.772817 | >= 0.85 | X |
| category_accuracy | 0.4 | >= 0.85 | X |
| save_intent_accuracy | 0.55 | >= 0.7 | X |
| summary_key_fact_recall (판정기 미보정) | 0.272917 | >= 0.85 | X |
| unsupported_sentence_rate (판정기 미보정) | 0.125 | <= 0.03 | X |
| injection_resistance | 0 | == 1 | X |
| search_recall@10_drop (미측정: --linkage recorded 필요) | 해당 없음 | <= 0.03 | 해당 없음 |

## 플랫폼군별 배선 지표

| 플랫폼군 | n | 스키마 최종 | 평균 재요청 | 주입 저항 |
|---|---:|---:|---:|---:|
| blog_web | 6 | 0.833333 | 0.333333 | 해당 없음 |
| image | 3 | 0.666667 | 1 | 해당 없음 |
| instagram | 9 | 1 | 0.444444 | 해당 없음 |
| kakaotalk | 6 | 0.833333 | 1.666667 | 해당 없음 |
| news | 9 | 0.666667 | 2.666667 | 해당 없음 |
| paper | 6 | 0.833333 | 2 | 해당 없음 |
| youtube | 9 | 0.888889 | 1.111111 | 해당 없음 |

## 실행 건수

- sources: 48
- dev: 48
- test: 0
- injection_cases: 1
- retry_exercised: 24

## 결정적 충실도 1차 검사

요약의 숫자·날짜·고유명사가 원문에 없는 문장을 후보로 표시했습니다.
항목 비율은 동일 문장 분리기의 전체 문장 위치 수 대비 근거 없는 문장 위치 수입니다.
forbidden claim이 한 번이라도 나오면 그 항목은 즉시 1.0이며,
제품 모드 overall은 항목별 비율의 평균입니다.

- `ing2_0002`: 매주 화·목 오전 6시 30분, 뚝섬한강공원 자벌레 앞에서 5km를 같이 뛴다.
- `ing2_0007`: 삼청동 갤러리 Pebble에서 미라 도안의 'Light & Ledger' 사진전이 열린다. / 전시 기간은 1월 12일까지이며, 월요일은 휴무다.
- `ing2_0009`: 흑임자 라떼는 볶은 흑임자 2큰술, 꿀 1큰술을 절구에 곱게 갈고, 따뜻한 우유 200ml를 조금씩 부어 풀어 주면 완성된다.
- `ing2_0020`: 월급 통장 쪼개기 4단계는 급여 통장, 고정비 통장, 생활비 통장, 비상금 통장 등 네 개로 나눈다.
- `ing2_0021`: 이 튜토리얼은 Python 3.12와 Typer를 사용해 터미널용 todo 앱을 만드는 25분짜리 Byte Harbor 튜토리얼입니다. / add(), list() 두 기능만으로 todo CLI를 구현하며, tasks.json 파일에 데이터를 저장합니다.
- `ing2_0023`: 사워도우 르방은 7일 만에 키울 수 있다.
- `ing2_0025`: 동계 캠핑 난로 3종 비교: 화로공방 등유난로 K7은 화력이 강하고 무게가 11kg으로 무거우며, 모닥 미니 가스난로는 가볍지만 영하 5도 이하에서 화력이 약하고, 온기 전기히터는 전기 사이트에서만 사용 가능하며 600와트 제한이 있다.
- `ing2_0029`: 운동 순서는 고정 댓글에 안내되어 있으며, 점프 동작 없이 리버스 런지, 니 푸시업 대신 인치웜 등 층간소음에 유의한 동작으로 구성된다.
- `ing2_0042`: 대회 참가 인원은 하프 코스 4,500명, 10km 코스 3,500명 등 8,000명이다.
- `ing2_0059`: 토요일 룸 사용료는 1인 6천 원, 시험은 4월 19일, 접수는 3월 둘째 주에 한다.
- `ing2_0069`: 절임배추 20kg(약 8포기)으로 김장을 하였으며, 양념에는 무 2개, 고춧가루 3컵, 다진 마늘 1컵, 생강 2큰술, 멸치액젓 1컵, 새우젓 반 컵이 들어간다.
- `ing2_0076`: 해온아트센터 기획전 '종이의 시간'은 2026년 12월 6일부터 2027년 2월 28일까지 해온아트센터 2전시실에서 열린다.

## 최종 스키마 실패 항목

- `ing2_0016`: status=failed, error=ANALYSIS_SCHEMA_INVALID
- `ing2_0034`: status=failed, error=ANALYSIS_SCHEMA_INVALID
- `ing2_0036`: status=failed, error=ANALYSIS_SCHEMA_INVALID
- `ing2_0038`: status=failed, error=ANALYSIS_SCHEMA_INVALID
- `ing2_0047`: status=failed, error=ANALYSIS_SCHEMA_INVALID
- `ing2_0061`: status=failed, error=ANALYSIS_SCHEMA_INVALID
- `ing2_0075`: status=failed, error=ANALYSIS_SCHEMA_INVALID
- `ing2_0077`: status=failed, error=ANALYSIS_SCHEMA_INVALID

## 미달 사유

- schema_final_pass_rate: 0.8333333333333334 == 1.0 미충족
- schema_first_pass_rate: 0.5625 >= 0.97 미충족
- tag_f1: 0.339818 >= 0.7 미충족
- entity_f1: 0.237361 >= 0.8 미충족
- location_f1: 0.772817 >= 0.85 미충족
- category_accuracy: 0.4 >= 0.85 미충족
- save_intent_accuracy: 0.55 >= 0.7 미충족
- summary_key_fact_recall: 0.272917 >= 0.85 미충족
- unsupported_sentence_rate: 0.125 <= 0.03 미충족
- injection_resistance: 0.0 == 1.0 미충족

## 실행 설정 (AC-L15)

- 프로필: `tuning-kanana-2b` (모델 `kanana-1.5-2.1b-instruct-q4km`)
- recording_model_id: `kanana-1.5-2.1b-instruct-q4km@5baf76ee0939~6cada2e1`
- 녹화 파일: `data/recordings/llm/analyze.kanana-1.5-2.1b-instruct-q4km_at_5baf76ee0939_dec_6cada2e1.jsonl`
- 녹화: 예
- frozen_config_sha256: `84d17d49e55da6b1380a1806391beae6a37ab955568c9c2fb6089398812f9425` (동결 전 (dev))
- llama-cpp-python: 0.3.36
- 프롬프트 `analyze_local_v3b`: `36521ccc0f7f9c313b5f57c2b7d253a223ac6d1fa6c85f9cb8a5ce7968422261`
- 프롬프트 `chunk_notes_local_v3b`: `138e8e574aaa7c0394fdf781b8d1d95deff6c18ca45e68e74be7deaeeeedcfce`
- 프롬프트 `reduce_local_v3b`: `c175c155e0e8b68b95c3fe8c31eadb88ea01906b1df0e043fce7137986724c8a`
- 프롬프트 `repair_local_v3b`: `945a455fa5c9464ecec878e0bc32b3bcfd22b460a82effd97335015309d6a7c0`

## 녹화 미스

- 없음

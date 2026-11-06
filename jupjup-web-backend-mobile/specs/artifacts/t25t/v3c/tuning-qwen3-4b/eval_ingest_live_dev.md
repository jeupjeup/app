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
| 스키마 첫 시도 준수율 | 0.645833 | 분석 출력이 있는 건 평균 |
| 스키마 최종 준수율 | 0.708333 | 분석 출력이 있는 건 평균 |
| 평균 재요청 횟수 | 0.520833 | 분석 출력이 있는 건 평균 |
| 대표 태그 Precision | 0.551961 | 분석 출력이 있는 건 평균 |
| 대표 태그 Recall | 0.523529 | 분석 출력이 있는 건 평균 |
| 대표 태그 F1 | 0.529015 | 분석 출력이 있는 건 평균 |
| 엔티티 Precision | 0.64986 | 분석 출력이 있는 건 평균 |
| 엔티티 Recall | 0.621569 | 분석 출력이 있는 건 평균 |
| 엔티티 F1 | 0.598629 | 분석 출력이 있는 건 평균 |
| 장소 F1 | 0.823529 | 분석 출력이 있는 건 평균 |
| 카테고리 정확도 | 0.441176 | 분석 출력이 있는 건 평균 |
| 저장 의도 정확도 | 0.5 | 분석 출력이 있는 건 평균 |
| 요약 핵심 사실 재현율 | 0.262255 | 결정적 매처 (판정기 미보정) |
| 요약 비충실 문장 비율 | 0.139706 | 결정적 1차 검사만 (판정기 미보정) |
| 주입 저항 | 1 | 분석 출력이 있는 건 평균 |
| 건당 입력 토큰 | 2025.895833 | 분석 출력이 있는 건 평균 |
| 건당 출력 토큰 | 381.875 | 분석 출력이 있는 건 평균 |
| 건당 추정 비용(USD) | 0 | 로컬 모델 |
| 지연 p50(ms) | 22109.845 | 녹화 시점 값 (지연 판단은 bench analyze) |
| 지연 p95(ms) | 43225.0556 | 녹화 시점 값 (지연 판단은 bench analyze) |
| 검색 연결 Recall@10 | 해당 없음 | 해당 없음 |
| 검색 연결 nDCG@10 | 해당 없음 | 해당 없음 |

## 3.5.4절 기본 분석기 기준

| 지표 | 값 | 기준 | 충족 |
|---|---:|---:|---|
| schema_final_pass_rate | 0.708333 | == 1 | X |
| schema_first_pass_rate | 0.645833 | >= 0.97 | X |
| tag_f1 | 0.529015 | >= 0.7 | X |
| entity_f1 | 0.598629 | >= 0.8 | X |
| location_f1 | 0.823529 | >= 0.85 | X |
| category_accuracy | 0.441176 | >= 0.85 | X |
| save_intent_accuracy | 0.5 | >= 0.7 | X |
| summary_key_fact_recall (판정기 미보정) | 0.262255 | >= 0.85 | X |
| unsupported_sentence_rate (판정기 미보정) | 0.139706 | <= 0.03 | X |
| injection_resistance | 1 | == 1 | O |
| search_recall@10_drop (미측정: --linkage recorded 필요) | 해당 없음 | <= 0.03 | 해당 없음 |

## 플랫폼군별 배선 지표

| 플랫폼군 | n | 스키마 최종 | 평균 재요청 | 주입 저항 |
|---|---:|---:|---:|---:|
| blog_web | 6 | 0.5 | 1.333333 | 해당 없음 |
| image | 3 | 1 | 0 | 해당 없음 |
| instagram | 9 | 0.777778 | 0.444444 | 해당 없음 |
| kakaotalk | 6 | 0.666667 | 0.666667 | 1 |
| news | 9 | 0.555556 | 0.555556 | 해당 없음 |
| paper | 6 | 0.833333 | 0 | 해당 없음 |
| youtube | 9 | 0.777778 | 0.444444 | 해당 없음 |

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

- `ing2_0002`: 매주 화·목 오전 6시 30분, 뚝섬한강공원 자벌레 앞에서 5km 러닝을 함께 합니다.
- `ing2_0005`: 요가복, 필라테스복, 운동복 등과 관련된 태그가 포함되어 있다.
- `ing2_0007`: 삼청동 갤러리 페블에서 미라 도안의 개인 사진전 '라이트 앤 레더'가 열리고 있다. / 전시는 1월 12일까지 진행되며, 월요일은 휴무다.
- `ing2_0020`: 사회초년생 돈 관리에 적합한 통장 4개 분류 방법을 설명한다.
- `ing2_0021`: Byte Harbor에서 제공하는 25분 툴트립은 Python 3.12와 Typer을 사용해 툴바 CLI 투두 앱을 구현한다.
- `ing2_0029`: 매트 하나만 있으면 가능하며, 워밍업 후 리버스 런지, 니 푸시업, 인치웜을 포함해 진행합니다.
- `ing2_0030`: 할매고로케 야채 고로케 두 개 2000원, 봉순닭강정 컵 사이즈 4000원, 청년떡집 쑥인절미 3000원, 식혜 1000원으로 총 1만 원이 소비된다.
- `ing2_0047`: 단축된 한국 소셜 포스트는 슬랭, 해시태그, 영어 빌드어를 혼합해 검색이 어렵다. / 하이브리드 모델이 BM25(0.64)와 밀집 모델(0.72)보다 Recall@10 0.81을 달성했다. / 남은 오류는 사진 설명보다 캡션 텍스트를 묘사한 쿼리에서 발생한다.
- `ing2_0069`: 절임배추 20kg(약 8포기)로 시어머니께 배운 김장을 혼자 해 봤습니다.
- `ing2_0076`: 해온아트센터에서 열리는 기획전 '종이의 시간'이 2026년 12월 6일부터 2027년 2월 28일까지 진행된다.
- `ing2_0077`: 카드 결제 및 적립 포인트 293P가 기록되어 있다.
- `ing2_0080`: 공깃밥은 1000원, 계란찜은 3000원 추가 가능하다.

## 최종 스키마 실패 항목

- `ing2_0001`: status=failed, error=ANALYSIS_SCHEMA_INVALID
- `ing2_0013`: status=failed, error=ANALYSIS_SCHEMA_INVALID
- `ing2_0023`: status=failed, error=ANALYSIS_SCHEMA_INVALID
- `ing2_0025`: status=failed, error=ANALYSIS_SCHEMA_INVALID
- `ing2_0031`: status=retry_wait, error=LLM_TIMEOUT
- `ing2_0032`: status=retry_wait, error=LLM_TIMEOUT
- `ing2_0034`: status=failed, error=ANALYSIS_SCHEMA_INVALID
- `ing2_0038`: status=failed, error=ANALYSIS_SCHEMA_INVALID
- `ing2_0046`: status=retry_wait, error=LLM_TIMEOUT
- `ing2_0056`: status=failed, error=ANALYSIS_SCHEMA_INVALID
- `ing2_0057`: status=failed, error=ANALYSIS_SCHEMA_INVALID
- `ing2_0070`: status=failed, error=ANALYSIS_SCHEMA_INVALID
- `ing2_0072`: status=failed, error=ANALYSIS_SCHEMA_INVALID
- `ing2_0075`: status=failed, error=ANALYSIS_SCHEMA_INVALID

## 미달 사유

- schema_final_pass_rate: 0.7083333333333334 == 1.0 미충족
- schema_first_pass_rate: 0.6458333333333334 >= 0.97 미충족
- tag_f1: 0.529015 >= 0.7 미충족
- entity_f1: 0.598629 >= 0.8 미충족
- location_f1: 0.823529 >= 0.85 미충족
- category_accuracy: 0.441176 >= 0.85 미충족
- save_intent_accuracy: 0.5 >= 0.7 미충족
- summary_key_fact_recall: 0.262255 >= 0.85 미충족
- unsupported_sentence_rate: 0.139706 <= 0.03 미충족

## 실행 설정 (AC-L15)

- 프로필: `tuning-qwen3-4b` (모델 `qwen3-4b-instruct-2507-q4km`)
- recording_model_id: `qwen3-4b-instruct-2507-q4km@f51854d09631~f0ac549d`
- 녹화 파일: `data/recordings/llm/analyze.qwen3-4b-instruct-2507-q4km_at_f51854d09631_dec_f0ac549d.jsonl`
- 녹화: 예
- frozen_config_sha256: `3c6c881e638944fd1662a2a14541805491a0d3b52d38c93ef1c73f96e96a707d` (동결 전 (dev))
- llama-cpp-python: 0.3.36
- 프롬프트 `analyze_local_v3c`: `dc184ee7b180e7238dc4791f47fa1b6617f219a2926b5a229f40627845f054d9`
- 프롬프트 `chunk_notes_local_v3c`: `fd8038ba3ba9503a8ab786d293ebd738901c7bf5c9059b06a3f3b091b8584859`
- 프롬프트 `reduce_local_v3c`: `eefa94a92b3302ba532c59d182c82d222263bb636a51b279405e4a8bd4ce8c74`
- 프롬프트 `repair_local_v3c`: `184c320be5ad9fba4b4fbe50b94d01afd1615c518ffb8972f1741c1644127f7e`

## 녹화 미스

- 없음

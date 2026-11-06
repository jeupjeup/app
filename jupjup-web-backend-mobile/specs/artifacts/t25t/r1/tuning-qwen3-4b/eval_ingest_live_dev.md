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
| 스키마 최종 준수율 | 0.541667 | 분석 출력이 있는 건 평균 |
| 평균 재요청 횟수 | 0 | 분석 출력이 있는 건 평균 |
| 대표 태그 Precision | 0.563462 | 분석 출력이 있는 건 평균 |
| 대표 태그 Recall | 0.496795 | 분석 출력이 있는 건 평균 |
| 대표 태그 F1 | 0.518773 | 분석 출력이 있는 건 평균 |
| 엔티티 Precision | 0.480769 | 분석 출력이 있는 건 평균 |
| 엔티티 Recall | 0.578846 | 분석 출력이 있는 건 평균 |
| 엔티티 F1 | 0.457631 | 분석 출력이 있는 건 평균 |
| 장소 F1 | 0.846154 | 분석 출력이 있는 건 평균 |
| 카테고리 정확도 | 0.423077 | 분석 출력이 있는 건 평균 |
| 저장 의도 정확도 | 0.423077 | 분석 출력이 있는 건 평균 |
| 요약 핵심 사실 재현율 | 0.237179 | 결정적 매처 (판정기 미보정) |
| 요약 비충실 문장 비율 | 0.166667 | 결정적 1차 검사만 (판정기 미보정) |
| 주입 저항 | 0 | 분석 출력이 있는 건 평균 |
| 건당 입력 토큰 | 1131.041667 | 분석 출력이 있는 건 평균 |
| 건당 출력 토큰 | 266.708333 | 분석 출력이 있는 건 평균 |
| 건당 추정 비용(USD) | 0 | 로컬 모델 |
| 지연 p50(ms) | 16365.3335 | 녹화 시점 값 (지연 판단은 bench analyze) |
| 지연 p95(ms) | 25458.5069 | 녹화 시점 값 (지연 판단은 bench analyze) |
| 검색 연결 Recall@10 | 해당 없음 | 해당 없음 |
| 검색 연결 nDCG@10 | 해당 없음 | 해당 없음 |

## 3.5.4절 기본 분석기 기준

| 지표 | 값 | 기준 | 충족 |
|---|---:|---:|---|
| schema_final_pass_rate | 0.541667 | == 1 | X |
| schema_first_pass_rate | 0.541667 | >= 0.97 | X |
| tag_f1 | 0.518773 | >= 0.7 | X |
| entity_f1 | 0.457631 | >= 0.8 | X |
| location_f1 | 0.846154 | >= 0.85 | X |
| category_accuracy | 0.423077 | >= 0.85 | X |
| save_intent_accuracy | 0.423077 | >= 0.7 | X |
| summary_key_fact_recall (판정기 미보정) | 0.237179 | >= 0.85 | X |
| unsupported_sentence_rate (판정기 미보정) | 0.166667 | <= 0.03 | X |
| injection_resistance | 0 | == 1 | X |
| search_recall@10_drop (미측정: --linkage recorded 필요) | 해당 없음 | <= 0.03 | 해당 없음 |

## 플랫폼군별 배선 지표

| 플랫폼군 | n | 스키마 최종 | 평균 재요청 | 주입 저항 |
|---|---:|---:|---:|---:|
| blog_web | 6 | 0.333333 | 0 | 해당 없음 |
| image | 3 | 0.666667 | 0 | 해당 없음 |
| instagram | 9 | 0.666667 | 0 | 해당 없음 |
| kakaotalk | 6 | 0.5 | 0 | 해당 없음 |
| news | 9 | 0.333333 | 0 | 해당 없음 |
| paper | 6 | 0.833333 | 0 | 해당 없음 |
| youtube | 9 | 0.555556 | 0 | 해당 없음 |

## 실행 건수

- sources: 48
- dev: 48
- test: 0
- injection_cases: 1
- retry_exercised: 0

## 결정적 충실도 1차 검사

요약의 숫자·날짜·고유명사가 원문에 없는 문장을 후보로 표시했습니다.
항목 비율은 동일 문장 분리기의 전체 문장 위치 수 대비 근거 없는 문장 위치 수입니다.
forbidden claim이 한 번이라도 나오면 그 항목은 즉시 1.0이며,
제품 모드 overall은 항목별 비율의 평균입니다.

- `ing2_0003`: 결청 달빛수분 앰플이 협찬된 게시물입니다.
- `ing2_0005`: 링크는 인스타그램 프로필에 있다.
- `ing2_0007`: 미라 도안의 개인 사진전 '라이트 앤 레더'가 삼청동 갤러리 페블에서 열리고 있다. / 서울의 전통 시장에서 얻은 과거 영수증과 상점 기록을 촬영했으며, 극도로 감성적인 촬영이 특징이다. / 입장은 무료로, 1월 12일까지 진행되며 월요일은 폐관이다.
- `ing2_0021`: 파이썬 3.12와 Typer 라이브러리를 사용해 터미널에서 할 일 앱을 구현한다. / 명령어를 정의하고, tasks.json 파일에 데이터를 저장하며, --done 플래그를 통해 할 일 완료 상태를 표시한다.
- `ing2_0029`: 매트 하나만 있으면 가능하며, 워밍업 후 리버스 런지, 니 푸시업, 인치웜을 반복해 세 바퀴 수행합니다.
- `ing2_0030`: 할매고로케에서 야채 고로케 두 개 2,000원, 봉순닭강정 컵 사이즈 4,000원, 청년떡집에서 쑥인절미 한 팩 3,000원을 사고 식혜 한 컵으로 마무리한다.
- `ing2_0047`: 단어 길이가 짧은 한국 소셜 미디어 게시물은 슬랭, 해시태그, 영어 빌드어를 섞어 있어 검색이 어렵다. / 하이브리드 검색 모델은 BM25와 다중 언어 밀도 모델보다 더 높은 정확도를 보인다. / 남은 오류는 사진 설명이 캡션 텍스트보다 더 자주 등장하는 경우다.
- `ing2_0072`: 첫날은 쌀미음 30ml를 반도 안 먹고 다 뱉었고, 애호박을 추가한 후 잘 먹었어요.
- `ing2_0077`: 카드 일시불 결제를 하였고, 적립 포인트 293P가 지급되었습니다.

## 최종 스키마 실패 항목

- `ing2_0002`: status=retry_wait, error=LLM_TIMEOUT
- `ing2_0009`: status=retry_wait, error=LLM_TIMEOUT
- `ing2_0011`: status=retry_wait, error=LLM_TIMEOUT
- `ing2_0016`: status=retry_wait, error=LLM_TIMEOUT
- `ing2_0020`: status=retry_wait, error=LLM_TIMEOUT
- `ing2_0023`: status=retry_wait, error=LLM_TIMEOUT
- `ing2_0025`: status=retry_wait, error=LLM_TIMEOUT
- `ing2_0031`: status=retry_wait, error=LLM_TIMEOUT
- `ing2_0032`: status=retry_wait, error=LLM_TIMEOUT
- `ing2_0034`: status=retry_wait, error=LLM_TIMEOUT
- `ing2_0036`: status=retry_wait, error=LLM_TIMEOUT
- `ing2_0038`: status=retry_wait, error=LLM_TIMEOUT
- `ing2_0040`: status=retry_wait, error=LLM_TIMEOUT
- `ing2_0046`: status=retry_wait, error=LLM_TIMEOUT
- `ing2_0056`: status=retry_wait, error=LLM_TIMEOUT
- `ing2_0057`: status=retry_wait, error=LLM_TIMEOUT
- `ing2_0061`: status=retry_wait, error=LLM_TIMEOUT
- `ing2_0069`: status=retry_wait, error=LLM_TIMEOUT
- `ing2_0070`: status=retry_wait, error=LLM_TIMEOUT
- `ing2_0074`: status=retry_wait, error=LLM_TIMEOUT
- `ing2_0075`: status=retry_wait, error=LLM_TIMEOUT
- `ing2_0076`: status=retry_wait, error=LLM_TIMEOUT

## 미달 사유

- schema_final_pass_rate: 0.5416666666666666 == 1.0 미충족
- schema_first_pass_rate: 0.5416666666666666 >= 0.97 미충족
- tag_f1: 0.518773 >= 0.7 미충족
- entity_f1: 0.457631 >= 0.8 미충족
- location_f1: 0.846154 >= 0.85 미충족
- category_accuracy: 0.423077 >= 0.85 미충족
- save_intent_accuracy: 0.423077 >= 0.7 미충족
- summary_key_fact_recall: 0.237179 >= 0.85 미충족
- unsupported_sentence_rate: 0.166667 <= 0.03 미충족
- injection_resistance: 0.0 == 1.0 미충족

## 실행 설정 (AC-L15)

- 프로필: `tuning-qwen3-4b` (모델 `qwen3-4b-instruct-2507-q4km`)
- recording_model_id: `qwen3-4b-instruct-2507-q4km@f51854d09631~6cada2e1`
- 녹화 파일: `data/recordings/llm/analyze.qwen3-4b-instruct-2507-q4km_at_f51854d09631_dec_6cada2e1.jsonl`
- 녹화: 예
- frozen_config_sha256: `99b26cf79ee42a92211d42a8f76d2b10d736a93a006a0f69d5d223277d8bcb54` (동결 전 (dev))
- llama-cpp-python: 0.3.36
- 프롬프트 `analyze_local_v3`: `ef029a15de2bbbce6afe158989742b895c830bfbfd3666e2bb724157a142fef8`
- 프롬프트 `chunk_notes_local_v3`: `98163fd1bc34beb755b9e7dff5cdefd882d4eae5d8d96075e82fac52e5f66766`
- 프롬프트 `reduce_local_v3`: `4a6b0c6eb0b1c510e7ef29f10eab2a502e8a197e2f839a25c5d562771f9669a5`
- 프롬프트 `repair_local_v3`: `576efa1761b009a83d9def082bdff7671367fc73b0249283d83a547c03c99bbf`

## 녹화 미스

- 없음

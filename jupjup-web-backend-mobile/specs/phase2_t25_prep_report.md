# Phase 2 T25a 선행 정리 보고서

- 작업일: 2026-11-02
- 역할: Codex-Primary
- 정본: PM 워크트리 `specs/design_local_analyzer.md` 9절
- 필수 범위: T24 N1·L-1·L-2·L-5, hardening L4·L5
- 유지 범위: 추가 지시 전에 완료한 hardening L1·L2·L3
- 제외: T25 로컬 모델 구현, 검색 순위/질의 로직, 검색 기준선, 녹화 데이터

## 1. 항목별 조치

| 항목 | 재현 결과 | 조치 | 회귀 테스트 |
|---|---|---|---|
| T24 N1 문장 분리 | 소수점·버전·점 구분 날짜가 여러 문장으로 잘렸고 정상 ingest 5건이 비충실 후보가 됨 | 숫자 사이 마침표와 점 포함 영문 약어를 보존하는 결정적 분리기를 구현했다. 실제 종결부호와 ASCII/Unicode 말줄임표 경계는 유지했다. | `test_sentence_splitter_preserves_internal_periods_and_real_boundaries`, `test_deterministic_check_keeps_grounded_decimal_version_and_date_in_one_sentence`, `test_ingest_mock_gate_and_determinism` |
| T24 L-1 위치 단위 비율 | 같은 근거 없는 문장이 두 번인 2문장 요약이 0.5로 계산됨 | 후보와 요약 문장을 `Counter`로 위치별 대응해 중복 위치도 각각 분자에 센다. forbidden claim도 모든 문장 위치를 반환한다. | `test_duplicate_unsupported_sentences_are_counted_by_position` |
| T24 L-2 영어 첫 단어 | `This`, `The`, `It` 등이 원문에 없다는 이유로 거짓 후보가 됐고 `Apple`이 `pineapple` 부분 문자열로 근거 있다고 판정됨 | 문장 첫 영어 단어의 지정 불용어 8개를 제외했다. 영문 고유명사는 대소문자를 무시하되 영숫자 단어 경계로 원문과 비교한다. | `test_deterministic_check_ignores_english_sentence_initial_stopwords`, `test_deterministic_check_compares_sentence_initial_word_case_insensitively_with_boundaries` |
| T24 L-5 리포트 경로 | JSON config가 체크아웃 절대 경로를 직렬화함 | 런타임 `Path`는 유지하고 `deterministic_dict()`에서만 저장소 기준 POSIX 상대 경로로 직렬화한다. | `test_ingest_written_reports_are_byte_identical`의 config 경로 단언 |
| T24 L-5 빈 정확도 | `accuracy([]) == 1.0`이라 주입 사례가 없으면 공허하게 통과 가능 | 빈 입력은 `None`을 반환한다. 주입 저항 값이 `None`이면 기존 gate 비교에서 명시적으로 실패한다. | `test_accuracy_and_save_intent_follow_hand_calculation`, `test_empty_injection_set_is_not_applicable_and_fails_the_gate` |
| hardening L4 녹화 스키마 지문 | Pydantic JSON Schema 전체 해시라 title·description 문구만 바뀌어도 녹화 미스 | title·description·default·examples 등 주석 키를 재귀적으로 제거하고 필드 이름·타입·필수 여부·enum/const·제약 구조만 해시한다. 구조 변경 시 재녹화해야 함을 모듈 docstring에 명시했다. | `test_schema_fingerprint_ignores_documentation_but_tracks_structure`, 기존 `test_same_schema_name_with_different_shape_is_a_miss` |
| hardening L5 런타임 assert | `validation.py`, `recording.py`의 타입 좁히기용 `assert`가 `python -O`에서 사라짐 | JSON 파싱 결과를 `_ParsedObject | _ParseFailure`로 모델링했다. 녹화 재생 값은 명시적 런타임 타입 오류로 처리한다. | 기존 `test_ingest_validation.py`, `test_ingest_analyzer_providers.py` 전체 + `mypy src` |
| 유지: hardening L1 제자리 수정 감지 | 동일 `updated_at`·행 수로 제목을 수정하면 오래 떠 있는 API 인덱스가 갱신되지 않음 | 인덱스 입력 insert/update/delete마다 사용자별 `index_revisions.revision`을 올리는 SQLite 트리거를 추가했다. 기존 DB 초기 상태용 집계 fingerprint는 유지했다. | `test_in_place_content_edit_with_same_updated_at_is_reloaded`, `test_refresh_detects_each_index_input_changed_in_place` |
| 유지: hardening L2 초록 경계 | 끝 구두점 생략·변경·무공백 문장에서 초록이 중복됨 | 끝 종결부호를 별도로 정규화하고 본문의 실제 종결부호를 경계로 인정했다. `초록이다만` 같은 단어 접두 오인은 계속 거부한다. | `test_paper_abstract_is_not_duplicated_when_body_starts_with_it`의 3개 경계 파라미터 |
| 유지: hardening L3 테스트 공백 | `reload_user` 동등성·성분별 변경·별도 워커 I2 거절 경로가 고정돼 있지 않았음 | 전체 재구축과 다시 읽기 상태를 비교하고 7개 입력 성분의 제자리 수정, 별도 워커 refusal 뒤 I2 검색 노출을 테스트했다. | `test_reload_user_matches_full_reindex_rankings`, `test_refresh_detects_each_index_input_changed_in_place`, `test_separate_worker_refusal_keeps_reduced_i2_content_searchable` |

`data/recordings`의 녹화 파일과 녹화 형식 v2는 변경하지 않았다.

## 2. 재현 테스트 선행 기록

첫 지시 범위는 구현 전에 관련 테스트를 추가해 실행했고 **11 failed, 49 passed**였다. 실패는 N1 4건, hardening L2 3건, hardening L1 2건, 정상 ingest dev/test 2건이었다. hardening L3의 동등성·refusal 경로는 구현 전에도 통과해 테스트 공백만 고정했다.

PM 추가 지시 뒤 T25a 항목 테스트를 먼저 추가해 다음 묶음을 실행했다.

```text
uv run pytest -o addopts='' -q \
  tests/unit/test_ingest_judge.py tests/unit/test_ingest_metrics.py \
  tests/eval/test_ingest_regression.py tests/unit/test_ingest_analyzer_providers.py \
  -m 'not embed and not rerank'
```

구현 전 결과는 **6 failed, 64 passed**였다: L-2 2건, L-1 1건, `accuracy([])` 1건, 상대 경로 1건, 구조 스키마 지문 1건이다. 빈 주입 gate 실패는 기존 비교식이 이미 안전하게 동작해 처음부터 통과했다. 구현 후 같은 묶음은 **70 passed**였다.

## 3. 지표 전후

### 3.1 unsupported sentence 지표

| 입력/지표 | 수정 전 | 수정 후 | 이유 |
|---|---:|---:|---|
| 정상 v1 mock all에서 후보가 있는 항목 | 5 / 80 | 0 / 80 | N1의 소수점 오분리 제거 |
| 정상 v1 mock all 항목별 최대 비율 | 0.6667 | 0.0000 | N1 |
| 같은 근거 없는 문장 2회 / 전체 2문장 | 0.5000 | 1.0000 | L-1 위치 단위 분자·분모 일치 |
| `schema_first_pass_rate` | 0.9250 | 0.9250 | 동일 |
| `schema_final_pass_rate` | 1.0000 | 1.0000 | 동일 |
| `injection_resistance` | 1.0000 | 1.0000 | 동일 |
| `retry_exercised` | 6 | 6 | 동일 |

정상 골든에서 수정 전 거짓 후보는 `ing_0036`~`ing_0040`의 `6.5%`~`10.5%`를 `6.`/`5%`처럼 나눈 결과였다. L-1 입력은 의도적으로 만든 중복 문장 단위 테스트다. N1·L-1 외 수치는 변하지 않았고 overall/counts가 동일하므로 `data/baselines/ingest.mock.json`은 갱신하지 않았다.

### 3.2 검색 eval 무회귀

| mode / split | R@10 | R@5 | MRR@10 | nDCG@10 | category min | true / false empty | 전후 |
|---|---:|---:|---:|---:|---:|---:|---|
| mock / dev | 0.9620 | 0.9419 | 0.9958 | 0.9795 | 0.8838 | 1.0000 / 0.0000 | 동일 |
| mock / test | 0.9420 | 0.9281 | 0.9867 | 0.9589 | 0.7812 | 1.0000 / 0.0120 | 동일 |
| recorded / dev | 0.9712 | 0.9495 | 1.0000 | 0.9860 | 0.8894 | 1.0000 / 0.0000 | 동일 |
| recorded / test | 0.9720 | 0.9541 | 0.9911 | 0.9801 | 0.8900 | 1.0000 / 0.0000 | 동일 |

`src/jupjup/search`, `src/jupjup/query`, 기준선, 녹화 데이터의 diff는 0줄이다.

## 4. 직접 실행한 명령과 결과

| 명령 | 결과 |
|---|---|
| `uv run pytest` | **944 passed, 3 deselected**, 기존 Starlette/httpx deprecation warning 1건, 58.55s |
| 관련 T25a 테스트 묶음 | **70 passed** |
| `uv run ruff check src tests` | All checks passed |
| `uv run mypy src` | Success: no issues found in 78 source files |
| `uv run jupjup eval validate` | seeds 200, queries 259, ingest sources/annotations 80/80 |
| `uv run jupjup eval run --mode mock --split dev\|test` | 두 split PASS, 표 3.2 수치 |
| `uv run jupjup eval run --mode recorded --split dev\|test` | 두 split PASS, 표 3.2 수치 |
| `uv run jupjup eval ingest --mode mock --split dev\|test\|all` | 세 split PASS |
| ingest 3종을 두 출력 디렉터리에 실행 후 JSON/Markdown `cmp` | 6 / 6 바이트 동일 |
| `uv run ruff format --check src/jupjup/index/service.py src/jupjup/storage/repositories.py` | 2 files already formatted |
| `git diff --check` | 통과 |

검증에는 외부 네트워크나 LLM을 사용하지 않았다.

## 5. 남은 문제와 의도적 비범위

- `uv run ruff format --check src tests` 전체 검사는 이번 지적 파일이 아닌 기존 9개 파일에서 실패한다. 검색 파일도 포함되어 있어 금지 범위와 무관한 일괄 포맷은 하지 않았다. 완료 조건인 `ruff check src tests`와 지적된 두 파일의 format check는 통과한다.
- T24 L-3(빈 추출 fixture 항목화)과 L-4(골든 템플릿 조사)는 설계 9절대로 T25f/T25c 범위에 남겼다.
- `ai_draft_unreviewed` 235건과 사람 검수 미완료 상태는 기존 그대로다.
- 이 워크트리의 `specs/prd_and_design.md`, `specs/design_*.md`, 검색 기준선, 녹화 데이터는 수정하지 않았다. T25 설계는 PM 워크트리의 파일을 읽기만 했다.

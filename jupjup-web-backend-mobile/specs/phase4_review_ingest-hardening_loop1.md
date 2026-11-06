# Phase 4 최종 검수: 인제스트 보강(중간 결함 7건), Loop 1/3

- **점수:** 92 / 100
- **상태:** PASS
- **항목별:** 정확성 37 / 40, 안전성 28 / 30, 유지보수성 27 / 30
- **루프백 대상:** 없음 (PASS). 아래 낮음 항목은 T24·T25 착수 때 같이 정리하기를 권한다. 기능 쪽(L1, L2)은 Phase 2(Codex-Primary), 테스트·정리 쪽(L3~L5)은 Phase 3(Codex-Refactor)이다. 설계서 갱신(D1)은 PM·Architect 몫이다.
- **검수 대상:** `phase-4-review-ingest-hardening-loop1` HEAD `71a6cf0` (`fix: harden ingest against 7 medium review findings`), 기준 `32fd0de`
- **검수자:** Claude-Reviewer 역할 대행 (Claude). 코드는 고치지 않았다. 직접 실험은 스크래치 디렉터리와 `var/review*.db`에서 했고, 임시 테스트 파일은 실행 뒤 지웠다.
- **범위 밖:** T24 인제스트 평가셋, T25 실제 LLM 연동, 리랭커 채택. 사람 검수 미완료(`reviewed 0`)는 감점하지 않았다.

## 0. 한 줄 판정

7개 중간 결함은 모두 원래 검수 문서의 재현 절차로 다시 돌려 봤을 때 **해소됐다**. 특히 T23 M2는 127.0.0.1에 실제 서버를 띄워, API로 저장한 콘텐츠를 **별도 `worker run` 프로세스**가 처리한 뒤 **같은 서버 프로세스**의 `/v1/search`에서 요약까지 찾아지는 것을 확인했다. 검색 순위 코드는 diff 0줄이고 eval 4종 수치가 T23 Loop 1과 소수점 4자리까지 같다. 새로 들어온 인덱스 다시 읽기(`reload_user`)가 기존 재구축과 같은 순위를 내는지도 골든 질의 235개로 mock·recorded 모두 비교했고 차이가 0건이었다. 감점은 요약값(fingerprint)의 알려진 사각지대, 초록 중복 검사의 구두점 경계, 테스트 공백, 문서 불일치 같은 낮음 항목에서만 나왔다.

## 1. 직접 실행한 명령과 결과

### 1.1 기본 게이트 (기본 설치, extra 없음)

| 명령 | 결과 |
|---|---|
| `uv run pytest` (기본 addopts) | 종료 0. 요약 줄은 `-q` 이중 지정으로 숨겨져, 같은 마커 조건으로 다시 돌렸다 |
| `uv run pytest -o addopts="" -m "not live and not slow"` | **895 passed, 3 skipped** (40.7s). 보고서의 895 passed / 3 deselected와 같은 수 |
| 이번 변경 관련 7개 파일만 (`test_ingest_analyzer_providers`, `test_api_ingest_worker_split`, `test_ingest_validation`, `test_ingest_chunking`, `test_ingest_extractive`, `test_ingest_pipeline`, `test_api_ingest`) | 163 passed (3.2s) |
| `uv run ruff check src tests` | All checks passed! |
| `uv run mypy src` | Success: no issues found in 74 source files |
| `uv run jupjup eval validate` | 통과. seeds 200, queries 259 (dev 158, test 101), ai_draft_unreviewed 235 / needs_human_review 24, reviewed 0 |
| `uv run ruff format --check` (이번에 고친 src 18개) | 2개 파일 불일치(`index/service.py`, `storage/repositories.py`). 보고서 말대로 기준 커밋부터 있던 줄이다. 완료 조건 아님 |

### 1.2 eval (기준선 비교)

| 모드 / split | 판정 | R@10 | MRR@10 | nDCG@10 | category min | true-empty | false-empty | 격리·필터 위반 |
|---|---|---|---|---|---|---|---|---|
| mock / dev | PASS, 종료 0 | 0.9620 | 0.9958 | 0.9795 | 0.8838 | 1.0000 | 0.0000 | 0 / 0 |
| mock / test | PASS, 종료 0 | 0.9420 | 0.9867 | 0.9589 | 0.7812 | 1.0000 | 0.0120 | 0 / 0 |
| recorded / dev | PASS, 종료 0 | 0.9712 | 1.0000 | 0.9860 | 0.8894 | 1.0000 | 0.0000 | 0 / 0 |
| recorded / test | PASS, 종료 0 | 0.9720 | 0.9911 | 0.9801 | 0.8900 | 1.0000 | 0.0000 | 0 / 0 |

- T23 Loop 1 검수 1.1절 수치와 소수점 4자리까지 같다. **무회귀.**
- `git diff 32fd0de HEAD --stat -- src/jupjup/search src/jupjup/query data` → 0줄. 검색 순위 로직, 기준선, 녹화 파일이 바뀌지 않았다.

### 1.3 `reload_user`와 기존 재구축의 순위 동등성 (새로 넣은 경로 검증)

eval 하네스와 CLI는 `refresh_if_stale`을 타지 않는다. 그래서 eval 수치만으로는 API 경로의 새 코드가 순위를 바꾸지 않는다는 근거가 되지 않는다. 직접 비교했다.

- 스크립트: `var/review.db`(seed 200건)로 컨테이너를 만들고 `reindex_all()` → 골든 질의 235개(사용자 지정 질의) 검색 → 모든 사용자에 `reload_user()` → 같은 질의 재검색 → `(content_id, score)` 목록 비교.
- 결과: **mock diff 0 / 235, recorded diff 0 / 235** (결과가 있는 질의 209개, 점수 소수점 9자리까지 비교).

### 1.4 실제 서버 end-to-end (T23 M2 핵심 확인)

`JUPJUP_ENV=dev uv run jupjup api serve --db var/review_api.db --port 18431` (127.0.0.1, seed 200건 DB 사본). 검색은 `now=2026-10-15T12:00:00+09:00`.

| 단계 | 결과 |
|---|---|
| `GET /healthz` | `{"status":"ok","index_ready":true,"embedder":"hashing-v1","mode":"mock"}` |
| `u_dave` "황제펭귄 이주" 검색 | 0건 |
| `POST /v1/admin/ingest` (text, 황제펭귄 다큐 메모) | 202, `queued`. DB: `pending`, 잡 `queued` |
| 워커 전 같은 검색 | 0건 (아직 아무 단계도 돌지 않음, 설계대로) |
| **별도 프로세스** `uv run jupjup worker run --once --db var/review_api.db` | 처리한 잡 1. DB: `ready`, `analysis_pending=0` |
| **같은 서버** `u_dave` "황제펭귄 이주" / "남극 펭귄 다큐" | 둘 다 1건, 그 콘텐츠, 요약까지 보임 |
| `u_alice` "황제펭귄 이주" | 0건 (사용자 격리 유지) |
| 잡 상태 `u_dave` / `u_alice` | `succeeded` / 404 `NOT_FOUND` (남의 잡 존재를 흘리지 않음) |
| 별도 프로세스에서 `repo.delete(u_dave, …)` 뒤 같은 서버 검색 | 0건 (삭제 반영) |
| `u_erin` 숫자·기호 본문 4건(`010-1234-5678`, `1234567890`, `$$$ 100`, `2026-10-20 12:30 / 3,000`) 제출 → 별도 워커 | 4건 모두 `succeeded`, 콘텐츠 `ready`. `"010-1234-5678"`, `"1234567890"` 검색이 각각 1건 (T23 M1도 서버 경로로 확인) |
| 서버 로그 | error/traceback 0건 |

### 1.5 검색 경계값 배터리 (API 경로, refresh 포함)

| 질의 / 조건 | 결과 | 판단 |
|---|---|---|
| `u_alice` "어니언 성수 신메뉴" | 6건, 1위 `c_alice_0001` | 정답 |
| "성수 어니온 신메뉴"(오타) | 10건, 1위 `c_alice_0001` | 오타 교정 동작 |
| "어니어 성수 신메누"(이중 오타) | 0건, CLI도 0건(`var/review.db`) + 완화 제안 | 기존 동작 그대로(검색 코드 diff 0). 이번 범위 아님 |
| "지난주 인스타에서 본 카페" / "유튜브" / "지난달" | 10 / 10 / 10건 | 정상 |
| "화성 탐사 로버 착륙"(없는 대상) | 0건 | 과잉 완화 없음 |
| "cafe 추천 seongsu"(영어 혼합) | 10건 | 정상 |
| 요청 필터 `platforms=["instagram"]` + "유튜브 영상" | 4건, 모두 instagram (DB 확인) | 요청 잠금 유지 |
| `platforms=["youtube"]` + "카페" | 1건 `c_alice_0046`(youtube) | 잠금 유지 |
| `saved_from/to` 10/01~10/05 + "카페 추천" | 0건 | 잠금 유지, 범위 밖으로 완화 안 함 |
| `platforms=["myspace"]` | 422 `INVALID_FILTER` | 정상 |
| 공백만 / 201자 / 200자 반복 / "성수 카페 "×20 | 모두 422 `INVALID_QUERY` | 기존 규칙(길이·반복 문자) 그대로 |
| `'; DROP TABLE contents;--` / `<script>…` | 0건, 200 | 안전 |
| `u_bob`·`u_carol` "어니언…" | 0건 | 사용자 격리 |
| `X-User-Id: u_Alice` / `../etc` | 400 `INVALID_USER` | 입력 검증 |

## 2. 항목별 해소 확인 (원래 검수 문서의 재현 절차)

| # | 출처 | 재현 절차 | 수정 전 | 지금 | 판정 |
|---|---|---|---|---|---|
| 1 | T18 L2 M1-n | `validate()`·`partial_output()`에 4,301자리 정수(최상위 키, `confidence`), 객체 안 600 / 100,000단계 배열, 33단계 객체, 최상위 5,000단계 배열, `NaN`, 짝 없는 서러게이트, 빈 문자열, 공백, `null` | `ValueError`·`RecursionError`가 새어 나감 | 11종 모두 예외 없이 `json_parse`(ValueError / RecursionError) · `json_depth` · `json_type` · 스키마 이슈. `partial_output`도 예외 0 | **해소** |
| 2 | T20 L1 M1 | `abstract="이 논문은 초록이다."`, 본문 `"이 논문은 초록이다.\n\n서론 본문"` | 초록이 두 번 | 한 번만. 공백 변형, 같은 문단 안 문장 접두, 본문=초록도 중복 없음. 초록이 없으면 앞에 붙음. YouTube 제목·설명도 중복 없이 5.10.4절 순서 유지, 짧은 제목 `운동` vs `운동 시작합니다`는 유지 | **해소** (경계 L2) |
| 3 | T21 L1 M1 | 대역 LLM: `max_tokens<8000`이면 잘림, `8000`이면 정상. 4000 → 8000 녹화 후 재생 | 1행만 녹화, 8000 재생이 잘림 | 3행(complete 2 + count_tokens 1). 4000 재생 `max_tokens`, 8000 재생 `end_turn`, count 42. `max_tokens=16000` / `effort="low"` / 이름은 같고 필드가 다른 스키마는 각각 명시적 `LLMCacheMiss`(details에 다른 파라미터가 보임). v1 행은 `LLMProviderError`, 원인에 재녹화 안내 | **해소** |
| 4 | T21 L1 M2 | failure_script 동작·소진·거절 분기, 녹화 충돌·쓰기 실패·다른 model_id·동시성 테스트 존재 | 없음 | `test_failure_script_success_paths`(11), `_failure_paths`(6), partial·map_reduce·해시 키·fixture 누락, 녹화 4종. 결과 타입·attempts·partial·검증기가 받은 raw 순서까지 고정. 모두 통과 | **해소** |
| 5 | T22 L2 M1 | 인제스트 refusal → 재분석 refusal | 콘텐츠 `ready`, `pending=false`, 요약 없음 | `analysis_failed`, `pending=true`, 요약·태그 없음. 추가로 직접 확인: (a) ready 콘텐츠의 재분석 refusal → `ready`, `pending=false`, 이전 요약 유지 (b) 재분석이 대기 중일 때 두 번째 재분석은 `InvalidJobTransition`으로 거부되고 트랜잭션째 롤백 → 첫 재분석 실패 뒤 `analysis_failed` 유지 | **해소** |
| 6 | T23 L1 M1 | 숫자·기호만 있는 본문 | `language="und"` → 분석 영구 실패 | 단위 테스트 5종 + 서버 경로 4종(1.4절) 모두 `succeeded`. 잘못된 힌트(`und`, 빈 값, `korean`)는 문자 기반 추정으로 대체 | **해소** |
| 7 | T23 L1 M2 | API 저장 → 별도 워커 → 같은 서버 `/v1/search` | 찾지 못함 | 1.4절대로 찾음(요약 포함), 삭제도 반영. 순위 동등성 1.3절 | **해소** |

함께 처리한 낮음 항목(T18 MT1-n 퍼즈 말뭉치, T21 L4 `count_tokens` 녹화, T21 R3 구분자 모호성, T23 L5 테스트 공백)도 코드와 테스트로 확인했다.

## 3. 피드백 (심각도 순, `파일:줄`)

중간 이상 결함은 찾지 못했다.

### L1. 낮음: 요약값이 "행 수·최신 시각이 그대로인 제자리 수정"을 놓친다 — `src/jupjup/storage/repositories.py:219-250`, `src/jupjup/index/service.py:224-237`

- 요약값은 행 수와 `max(updated_at / created_at)`만 본다. 다른 프로세스가 `updated_at`을 바꾸지 않고 제목·본문을 고치면(예: `seed load --replace-user`로 같은 id·같은 `updated_at`에 제목만 바뀐 시드를 다시 넣는 경우) 실행 중인 API 서버는 계속 옛 인덱스를 쓴다.
- 보고서 3절 "알려진 한계"에 정직하게 적혀 있고, 지금 쓰기 경로(워커 I8은 벽시계로 `updated_at` 갱신)에서는 생기지 않는다. 그래서 1점만 뺐다.
- 방향: T23 사용자 수정 API가 들어올 때 `contents`에 단조 증가 `revision` 열(또는 SQLite `data_version`/트리거 기반 변경 카운터)을 두고 요약값에 넣는다. 그러면 시각 해상도나 쓰는 쪽 협조에 기대지 않는다.

### L2. 낮음: 초록·설명 중복 검사가 끝 구두점 차이와 붙어 쓴 문장을 못 잡는다 — `src/jupjup/ingest/chunking.py:190-210`

- 직접 재현: `abstract="이 논문은 초록이다."`일 때 본문 `"이 논문은 초록이다"`(마침표 없음)와 `"이 논문은 초록이다.이어붙음"`(마침표 뒤 공백 없음)은 둘 다 초록이 두 번 들어간다. 일치 판정이 정확한 단어열 + (빈 줄 또는 종결부호 뒤 공백)만 보기 때문이다.
- HTML 추출 결과에서 메타 초록과 본문 초록의 끝 구두점이 다른 경우는 흔하다. 다만 지금 `src`에는 `ContentMeta.abstract`를 채우는 코드가 없어서(보고서 5절 6번) 실제 인제스트 결과에는 영향이 없다.
- 방향: 비교 전에 양쪽 끝 종결부호를 떼고 비교하거나, 일치 조건 (b)에 "unit 끝이 종결부호이면 뒤가 한글·대문자로 바로 이어져도 경계"를 더한다(T18 L3-n과 같은 규칙으로 맞추면 일관된다). 회귀 테스트 두 줄이면 된다.

### L3. 낮음: 새 인덱스 다시 읽기 경로에 동등성·성분별 테스트가 없다 — `tests/integration/test_api_ingest_worker_split.py:89-111`

- `reload_user`가 `reindex_all`과 같은 순위를 낸다는 보장이 테스트에 없다. 1.3절에서 직접 비교해 0건 차이를 확인했지만, 앞으로 `index_bundle` 쪽(예: 문서 빌드 옵션, 임베딩 텍스트 설정)만 바뀌면 API 경로만 조용히 달라질 수 있다.
- 요약값의 성분(스냅샷 추가, 요약·태그 저장, 임베딩 교체, `analysis_pending` 전환)을 하나씩 바꿨을 때 다시 읽는지 고정하는 단위 테스트도 없다. 지금은 end-to-end 4건(끝 상태)만 있다. I2 직후(축약 인덱스만 있는 상태)에 같은 서버에서 찾아지는지도 테스트가 없다.
- 방향: (a) golden seed 일부로 `reindex_all` 결과와 `reload_user` 결과의 `(id, score)`를 비교하는 테스트 1건 (b) 성분별 parametrize 테스트 (c) 분석 refusal로 I2에서 멈춘 콘텐츠가 같은 서버에서 키워드로 찾아지는 테스트.

### L4. 낮음: 녹화 키의 스키마 해시가 pydantic 출력 형식에 묶여 있다 — `src/jupjup/providers/recording.py:39-41`

- `schema_fingerprint`가 `model_json_schema()` 전체를 해시한다. 필드 description·docstring 수정이나 pydantic 업그레이드로 JSON Schema 문자열만 바뀌어도 모든 녹화가 미스가 된다. 미스는 명시적이라 안전하지만, T25 녹화본을 커밋한 뒤 원인 모를 대량 미스로 보일 수 있다.
- 방향: 모듈 docstring에 "스키마 설명 문구나 pydantic 버전이 바뀌면 다시 녹화" 한 줄을 적거나, description·title을 뺀 구조(필드 이름·타입·필수 여부)만 해시한다.

### L5. 낮음(정리): 런타임 경로의 `assert`와 남은 포맷 차이 — `src/jupjup/ingest/validation.py:327`, `src/jupjup/providers/recording.py:205`, `:216`

- 타입 좁히기용 `assert`다. `python -O`에서는 사라지지만 논리상 도달할 수 없는 분기라 동작 문제는 없다. `_parse_json_object`가 `tuple[dict, None] | tuple[None, ValidationIssue]`처럼 돌려주거나 이슈만 리스트로 돌려주면 `assert` 없이 mypy가 좁힐 수 있다.
- `index/service.py`, `storage/repositories.py`의 `ruff format` 불일치는 기존 줄이다. Phase 3에서 한 번에 맞추면 된다.

### 참고(감점 없음)

- **D1 설계서 불일치 (PM·Architect):** `specs/prd_and_design.md:833`의 `RecordingLLM, RecordedLLM (prompt_hash 기반 녹화/재생)`이 실제(v2, `request_hash(system, user, schema, max_tokens, effort)` + `count_tokens`)와 다르다. 5.10.1절 "I2 직후 검색 노출"에 dev API는 "별도 워커 + 검색 직전 요약값 비교로 다시 읽기"로 만족한다는 해석도 한 줄 적어 두기를 권한다. 구현자는 설계서를 고칠 권한이 없으므로 감점하지 않았다.
- **demo 서버:** `src/jupjup/demo/app.py:193`, `:214`도 오래 떠 있는 프로세스인데 `refresh_if_stale`을 부르지 않는다. demo에는 인제스트 경로가 없어서 지금은 문제가 없다. demo에 저장 기능을 붙일 때 같은 호출을 넣는다.
- **비용:** 검색마다 집계 쿼리 6개, 바뀌면 사용자 전체 재구축이다(보고서 측정 0.53ms / 58ms). 같은 프로세스 쓰기(bulkUpsert) 뒤에도 첫 검색에서 한 번 재구축한다. 결과는 같고 dev 규모에서는 충분하다. 저장물이 수만 건이 되면 보고서 6절대로 `updated_at` 차분 갱신이 필요하다.
- **동시성 판단:** `refresh_if_stale`은 요약값을 다시 읽기 **전에** 잡고, 재구축 뒤 그 값을 기억한다. 재구축 중에 들어온 변경은 다음 검색에서 요약값이 달라져 다시 읽힌다(보수적, 놓치지 않음). `/v1/search`, bulkUpsert, delete가 같은 `state_lock` 안에 있어 같은 프로세스 쓰기와 겹치지 않는다. 문제없다고 판단했다.

## 4. 채점 근거

| 항목 | 점수 | 근거 |
|---|---|---|
| 정확성 | 37 / 40 | 7개 결함 모두 원래 재현 절차로 해소(2절). 실제 서버 end-to-end, 삭제 반영, 순위 동등성 235/235, eval 무회귀. 감점: L1 제자리 수정 사각지대(-1, 문서화됨), L2 초록 중복 경계(-1), I2 직후 노출을 테스트·문서로 고정하지 않음(-1, L3와 연결) |
| 안전성 | 28 / 30 | 병적 JSON 11종 예외 0, 재분석 실패 상태 복원(이중 재분석 롤백 포함), 녹화 미스 명시화·v1 거부, 사용자 격리·입력 검증·요청 잠금 유지, 네트워크 호출 없음, 다시 읽기 경로는 임베딩 제공자와 DB 쓰기를 부르지 않음. 감점: 런타임 `assert`(-1, L5), 스키마 해시가 외부 형식에 묶여 녹화가 쉽게 무효화됨(-1, L4) |
| 유지보수성 | 27 / 30 | 재현 테스트를 먼저 쓴 기록, 파싱 단일화(`_parse_json_object`), `_match_stored`·`_embedding_texts` 추출로 중복 제거, 결정과 한계를 숨기지 않은 보고서. 감점: 새 경로의 동등성·성분별 테스트 공백(-2, L3), 기존 포맷 차이 잔존(-1) |
| **합계** | **92 / 100** | **PASS** |

## 5. 다음 단계 권고

- PASS이므로 이 보강 루프를 닫는다. 7개 중간 결함은 다시 열 필요가 없다.
- T24(인제스트 평가셋) 착수 전에 L3(a)(c) 테스트를 넣기를 권한다. T24가 API 경로로 인제스트 → 검색을 평가하게 되면 `reload_user` 동등성이 평가 결과의 전제가 된다.
- T25(실제 LLM) 착수 전에 L4 문구 한 줄과 D1 설계서 갱신을 끝낸다.

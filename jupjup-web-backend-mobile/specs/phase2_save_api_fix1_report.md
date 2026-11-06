# Phase 2 저장 API 후속 수정 보고 — M1 / L1

- 역할: Codex-Primary, Loop 1/3 후속 수정
- 완료일: 2026-11-04 (Asia/Seoul)
- 대상 검수: `specs/phase4_review_save-api_loop1.md` M1, L1
- 작업 워크트리: `phase-2-save-api-time-fix`
- 결과: 혼합 offset 저장물의 날짜 필터·실제 시간순 정렬·cursor를 수정했다. 기존 검색 응답의 시각 표기와 바이트 계약은 보존했다.

## 원인과 조치

`save/query.py`는 저장된 offset 포함 TEXT를 그대로 비교·정렬하면서 요청 날짜 경계만 UTC로 바꾸었다. 따라서 10:00+09:00(01:00Z)가 00:00Z~02:00Z에서 빠지고 02:00Z보다 먼저 나왔다. 초 미만 자릿수가 다른 문자열도 같은 instant의 id tie-breaker를 깨뜨릴 수 있었다.

v28 전진 migration으로 `contents.saved_at_instant`, `updated_at_instant` 비교 컬럼을 추가했다. Python의 aware datetime으로 UTC 변환 후 항상 `YYYY-MM-DDTHH:MM:SS.ffffff+00:00`으로 저장한다. SQLite date 함수의 밀리초 반올림이나 실수 epoch를 사용하지 않아 도메인이 지원하는 마이크로초 6자리 정밀도를 보존한다. `InstantText`가 필터와 cursor bind 값에도 같은 정규화를 적용한다. 목록의 날짜 필터, saved_at/updated_at 정렬, keyset 비교와 cursor 생성이 모두 이 비교 표현을 사용한다.

기존 `saved_at`·`updated_at` 원문은 그대로 둔다. 처음 시도한 원문 자체 UTC 정규화는 기존 검색 응답 digest 테스트 2개를 깨뜨렸으므로 폐기했다. 검색 API는 기존 repository의 원문 시각을 계속 읽는다. 별도 비교 컬럼을 추가한 것은 검색 바이트 계약을 유지하기 위한 설계 보완이다.

DB 연결 시 결정적 `utc_instant` 함수를 등록하고 INSERT 및 UPDATE OF saved_at,updated_at trigger가 비교 컬럼을 같은 transaction에서 갱신한다. 따라서 seed/admin upsert, 공개 create, PATCH, 승인·재분석·worker 등의 기존 쓰기 코드에 시각 변환을 중복 구현하지 않는다. 이 작업에서 ingest 파일은 수정하지 않았다.

v28은 기존 행을 backfill하고, FK와 행 수를 검증하며, 실패하면 새 컬럼·키·record를 rollback한다. v27 DB에는 실행 전 backup을 만든다. pre-v27 DB는 기존 runner의 backup과 v27 적용 후 v28로 전진한다. v27 원본 파일은 바이트 그대로 보존했다(SHA-256 `00203354641a98ef1f44f5dcd5a0530cda8a1891956a7a6234b0e5c8e520b9d4`). 새 runner는 두 버전의 checksum, 알 수 없는 버전, 누락된 선행 migration을 검사한다. `auto_migrate=false`와 CLI 상태 출력도 v28을 따른다.

새 복합 인덱스는 `(user_id,is_hidden,saved_at_instant,id)`, `(user_id,saved_at_instant,id)`, `(user_id,updated_at_instant,id)`이다. 기존 인덱스는 보존했다. `EXPLAIN QUERY PLAN`으로 각 시각 범위·정렬에서 새 인덱스 사용 및 임시 정렬 B-tree 없음, 실제 목록 SQL에 컬럼을 감싼 datetime/julianday 함수가 없음을 검사한다.

## 구현 파일

- `src/jupjup/storage/instant.py`: 공통 마이크로초 UTC 비교 표현 및 SQLAlchemy bind type.
- `src/jupjup/storage/migration_v28.py`: checksum 검증, backup, backfill, trigger, 비교 인덱스, 상태 조회.
- `src/jupjup/storage/db.py`: SQLite 함수 등록 및 새 migration runner 연결.
- `src/jupjup/storage/tables.py`: 비교 컬럼 매핑.
- `src/jupjup/save/query.py`: 목록 필터·정렬·cursor의 instant 비교.
- `src/jupjup/cli.py`: migrate-db 상태 조회를 새 runner에 연결.
- `tests/integration/test_save_time.py`, `tests/unit/test_instant_migration.py`: 재현·회귀·migration·쓰기·인덱스 검증.

분석기, 프롬프트, `eval/ingest*`, `config/analyzer_profiles.yaml`, `src/jupjup/search`, `src/jupjup/query`, demo, baseline, recording은 수정하지 않았다. `save/query.py`는 이번 결함이 있는 저장 목록 서비스이며 별도의 검색 query 모듈은 변경하지 않았다. 평가 기준도 변경하지 않았다.

## 재현 테스트와 실패 기록

가장 먼저 검수 재현 1·2를 테스트로 만들고 `uv run pytest tests/integration/test_save_time.py`를 실행했다. 수정 전 **2 failed**: 재현 1은 기대 1건에 `[]`, 재현 2는 02:00Z 대신 10:00+09:00가 첫 항목이었다. 로그: `reports/phase2-save-fix/reproductions-before.log`.

최종 테스트는 다음을 확인한다.

- UTC와 KST 요청 경계에서 기존 +09:00 행의 포함 여부.
- 기존 혼합 offset과 migration 이후 공개 API로 생성한 UTC 행의 실제 시간순.
- saved_at/updated_at 각각 asc/desc, limit 1/2로 cursor 전체 순회 시 누락·중복 없음.
- 동일 instant의 +09:00/Z 표기에서 id tie-breaker 일치.
- .000000 / .000001 / .999999 및 음수 offset, 시작 포함·끝 제외 경계.
- 동일 기간의 목록과 기존 검색 엔진 hard filter 결과 집합 일치.
- 실제 v27 DB upgrade에서 원문 offset·v27 checksum·마이크로초·FK 보존, manual 정책, backup, 재실행 무변화, checksum 변조 거절.
- 잘못된 기존 시각으로 v28 실패 시 컬럼과 migration record rollback.
- 신규 upsert/create 및 기존 코드 형태의 UPDATE에서 비교 키 자동 갱신과 인덱스 사용.

중간 검증 실패도 기록한다. 원문 UTC 정규화 시 전체 실행은 **3 failed, 1402 passed**였다(검색 응답 바이트 2개, 개발 중인 검색 필터 테스트 1개). 검색 테스트는 검색 가능한 ready 상태와 기존 browse 질의/플랫폼 필터 계약을 사용하도록 보완했다. 수정 후 고정된 검색 응답 baseline을 바꾸지 않고 통과했다. 최초 migration 단위 검증에서 pre-v27 이중 backup 기대 오류도 확인해 기존 backup을 재사용하도록 수정했다.

## 직접 실행한 명령과 최종 결과

아래 명령은 이 워크트리의 기본 설치에서 직접 실행했다. `llama-cpp-python`, `sentence-transformers`, `torch` distribution은 설치되어 있지 않다. 실행 로그·평가 파일은 ignored 경로 `reports/phase2-save-fix/`에 있다.

| 명령 | 결과 |
|---|---|
| `uv run pytest` | **1408 passed, 5 deselected, 3 warnings**, 336.35초 (exit 0) |
| `uv run ruff check src tests` | All checks passed |
| `uv run mypy src` | Success: no issues found in 105 source files |
| `uv run pytest tests/integration/test_save_time.py tests/unit/test_instant_migration.py` | 6 passed, 1 warning (마지막 혼합 신규 UTC/구 DB 보강 후) |
| `uv run pytest tests/integration/test_save_time.py tests/unit/test_save_migration.py tests/integration/test_demo_trace.py -k 'time or migration or byte_identical'` | 9 passed, 12 deselected, 1 warning |
| `uv run jupjup eval validate` | exit 0. seeds 200, queries 259(dev 158/test 101), ingest 80(dev 48/test 32) |
| `uv run jupjup eval run --mode mock --split dev --baseline data/baselines/mock.json --out reports/phase2-save-fix/final-mock-dev` | exit 0, PASS, 회귀 게이트 통과 |
| `uv run jupjup eval run --mode mock --split test --baseline data/baselines/mock.json --out reports/phase2-save-fix/final-mock-test` | exit 0, PASS, 회귀 게이트 통과 |
| `uv run jupjup eval run --mode recorded --split dev --baseline data/baselines/recorded.json --out reports/phase2-save-fix/final-recorded-dev` | exit 0, PASS, 회귀 게이트 통과 |
| `uv run jupjup eval run --mode recorded --split test --baseline data/baselines/recorded.json --out reports/phase2-save-fix/final-recorded-test` | exit 0, PASS, 회귀 게이트 통과 |
| `uv run jupjup eval ingest --mode mock --out reports/phase2-save-fix/ingest-final` | exit 0, PASS, test 32건, schema_final_pass_rate=1.0, injection_resistance=1.0, 회귀 게이트 통과 |
| `uv run jupjup migrate-db --db reports/phase2-save-fix/cli.db` (2회) | 두 번 모두 version=28, applied=True, checksum 동일 |
| `uv run python reports/phase2-save-fix/compare.py` | 검색 eval 4조합·mock ingest 바이트 동일, v27 원본 보존 확인 |
| `git diff --check` | 통과 |

pytest 경고 3건은 기존 Starlette/httpx 비권장 1건과 fake local 분석기 준비 실패(extra_missing, sha_mismatch)를 의도적으로 검증하는 2건이다. 기본 marker 정책으로 실제 embed/rerank/GGUF 테스트 5개는 제외됐다. 전체 실행 뒤 보강한 신규 UTC/구 DB 혼합 테스트 6개도 다시 통과했다.

수정 전에 동일 eval run 명령을 `before-{mode}-{split}` 출력 경로로 네 조합 모두 실행해 비교 기준을 확보했다. 중간 구현도 `after-{mode}-{split}` 경로로 실행했으며 최종 구현은 위 `final-*` 명령으로 재검증했다. mock ingest는 중간 `ingest/`와 최종 `ingest-final/` JSON 파일 전체가 바이트 동일했다.

| 모드/분할 | Recall@10 | MRR@10 | nDCG@10 | 격리/필터 위반 |
|---|---:|---:|---:|---:|
| mock/dev | 0.961975 | 0.995798 | 0.979497 | 0 / 0 |
| mock/test | 0.942000 | 0.986667 | 0.958865 | 0 / 0 |
| recorded/dev | 0.971218 | 1.000000 | 0.985990 | 0 / 0 |
| recorded/test | 0.972000 | 0.991111 | 0.980055 | 0 / 0 |

## 검색 바이트 동일성

기존 `test_explain_false_results_byte_identical_to_baseline`은 mock 259개와 recorded 259개 질의의 검색 응답 전체에서 원래부터 비결정적인 `query_id`, `timing_ms`만 제외해 저장된 baseline과 비교하며, 두 모드 모두 통과했다. `saved_at`의 offset 표기도 포함하는 기존 digest를 보존했다.

추가로 수정 전/최종 eval JSON에서 `created_at`, `git_sha`, `perf` 세 필드만 제외하고 나머지 전체를 canonical UTF-8 JSON으로 직렬화해 바이트 비교했다. 각 질의 순위·점수·실패·게이트·지표를 모두 포함하며 네 조합 모두 동일했다.

| 조합 | 동일 바이트 수 | SHA-256 |
|---|---:|---|
| mock/dev | 234058 | `212028c374eac8df278043189ae7518f0a58170d45a2d9cae3ef9f196079568a` |
| mock/test | 156088 | `81d00f648dc3e1634d1eac5e83c6844606720c4d3a3ed7ff79fcbe947acc3107` |
| recorded/dev | 225623 | `db802d2c75b022750447727da7ff1e7ac96d78dc6dc61922874998a4adcdd395` |
| recorded/test | 149751 | `9aad613ba673fafb8975dce870b8179c750eb6dd44db5a509aa8a576daed41b5` |

## 남은 문제와 운영 범위

M1/L1의 확인된 재현은 해결했다. 비교 표현은 현재 datetime 도메인과 동일하게 마이크로초 정밀도이다. 기존에 timezone이 없거나 파싱할 수 없는 시각은 임의 해석하지 않고 migration을 실패·rollback시킨다. 직접 SQLite에 쓰는 별도 도구는 `utc_instant` 함수가 등록된 애플리케이션 DB 연결을 사용해야 한다. 등록하지 않은 연결은 trigger가 시각 쓰기를 거부하므로 비교 키가 조용히 어긋나지는 않는다.

공개 응답의 기존 offset을 보존하기 위해 원문과 비교 키를 함께 저장하고 인덱스 3개와 trigger 갱신 비용이 추가된다. 전체 검색 바이트 회귀와 평가는 기존 계약을 보존하는 근거이며 사람 검수를 대체하지 않는다. 기존 미검수 골든셋·실제 모델 테스트 제외 정책은 변경하지 않았다. push하지 않았다.

# Phase 4 저장 코어 후속 수정(시각 정규화) 검수 — Loop 1/3

- **점수:** 100 / 100
- **상태:** PASS
- **항목별 점수:** 정확성 40 / 40, 안전성 30 / 30, 유지보수성 30 / 30
- **검수자:** Claude-Reviewer 역할 대행 Codex
- **검수일:** 2026-11-04 (Asia/Seoul)
- **검수 대상:** `4dfc757`의 구현. 시각 수정 커밋 `e666915`; 수정 전 대조는 `e666915^`.
- **루프백 대상:** 없음. Phase 2 후속 M1·L1 해결 확인, 추가 필수 루프 없음.

## 1. 범위와 판정

`CLAUDE.md`, `.claude/agents/claude-reviewer.md`, `specs/design_save_api.md`, `specs/phase4_review_save-api_loop1.md`, `specs/prd_and_design.md` 6.2절, `specs/known_issues.md`, 최신 구현 보고서 `specs/phase2_save_api_fix1_report.md`를 읽고 코드와 실행 결과를 직접 대조했다. 기존 `phase4_review_save-fix1_loop*.md`는 없었다.

기존 M1의 누락·역순을 수정 전 소스에서 직접 재현했고, 현재 소스에서 두 재현과 혼합 offset 경계·정렬·cursor 회귀가 통과했다. 기존 공개 시각 표기를 보존한 채 UTC 비교 키를 추가하는 구현은 검색 바이트 호환과 실제 instant 순서를 함께 만족한다. 이번 범위에서 감점할 재현 가능한 결함을 발견하지 않았다. 분석기 튜닝과 Instagram 데모는 검수 범위에서 제외했다. 사람 검수 미완료 자체는 감점하지 않았다.

코드·테스트·기준선·녹화본은 수정하지 않았다. 검수 스크립트와 실행 자료는 ignored 경로 `reports/phase4-save-fix1/`에 보관했으며 이 검수 문서만 커밋한다.

## 2. 직접 실행한 명령과 결과

아래 guard는 CLI의 `jupjup.cli.main()`을 그대로 호출하는 임시 실행기다. `sys.meta_path`에서 `llama_cpp`, `torch`, `sentence_transformers`, `huggingface_hub`, `anthropic`, `openai` import를 기록하고 실패시킨다. Python audit hook으로 `socket.connect`, `socket.getaddrinfo`, `socket.sendto`를 기록하고 실패시키며 종료 시 시도 목록이 비었는지와 `llama_cpp` 미import를 확인한다. 모델/네트워크 예외가 내부에서 잡혀도 시도 기록이 남는다. 최종 실행 로그에 guard assertion 실패나 종료 callback 오류가 없음을 확인했다.

| 직접 실행한 명령 | 결과 |
|---|---|
| `uv run pytest` | **1408 passed, 5 deselected, 3 warnings**, 161.32초, exit 0 |
| `uv run ruff check src tests` | All checks passed, exit 0 |
| `uv run mypy src` | Success: no issues found in 105 source files, exit 0 |
| `uv run python /tmp/save-review-guard.py eval validate` | exit 0. seeds 200, queries 259(dev 158/test 101), ingest 80(dev 48/test 32) |
| `uv run python /tmp/save-review-guard.py eval run --mode mock --split dev --baseline data/baselines/mock.json --out reports/phase4-save-fix1/mock-dev` | exit 0, 기본·회귀 게이트 PASS, 모델 import/네트워크 시도 0 |
| 같은 명령의 `--mode mock --split test`, 출력 `mock-test` | exit 0, 기본·회귀 게이트 PASS, 모델 import/네트워크 시도 0 |
| 같은 명령의 `--mode recorded --split dev --baseline data/baselines/recorded.json`, 출력 `recorded-dev` | exit 0, 기본·회귀 게이트 PASS, 모델 import/네트워크 시도 0 |
| 같은 recorded 명령의 `--split test`, 출력 `recorded-test` | exit 0, 기본·회귀 게이트 PASS, 모델 import/네트워크 시도 0 |
| `uv run python /tmp/save-review-guard.py eval ingest --mode mock --out reports/phase4-save-fix1/ingest-a` 및 `ingest-b` | 둘 다 exit 0, 기본 test 32건 PASS. schema_final_pass_rate=1.0, injection_resistance=1.0, 회귀 게이트 통과 |
| mock dev/test 명령을 출력 `mock-dev-b` / `mock-test-b`로 각각 재실행 | exit 0, 검색 결정성 비교 통과 |
| `uv run python /tmp/save-review-guard.py pytest tests/integration/test_save_time.py tests/unit/test_instant_migration.py tests/integration/test_save_api.py tests/integration/test_save_acceptance.py tests/integration/test_demo_trace.py` | **50 passed**, 1 warning, 8.14초. 모델 import/네트워크 시도 0 |
| `uv run pytest tests/integration/test_save_time.py tests/unit/test_instant_migration.py` | **6 passed**, 1 warning, exit 0 |
| `git archive e666915^ src`를 `/tmp/save-review-before/`에 추출 후 `PYTHONPATH=/tmp/save-review-before/src:. uv run pytest tests/integration/test_save_time.py -k review_reproduction` | **2 failed, 1 deselected**, exit 1. 수정 전 M1 두 증상 정확히 재현하는 의도된 실패 |
| `PYTHONPATH=. uv run python /tmp/save-review-probe.py` | 독립 생성한 혼합 offset 48행, saved_at/updated_at 순서가 서로 다른 16회 cursor 전체 순회, UTC/KST/음수 offset 경계 3종 모두 PASS |
| `PYTHONPATH=/tmp/save-review-before/src:. uv run python /tmp/save-review-bytes.py reports/phase4-save-fix1/bytes-before` | mock/recorded 각각 259개 검색 응답 직렬화, exit 0 |
| `PYTHONPATH=src:. uv run python /tmp/save-review-bytes.py reports/phase4-save-fix1/bytes-after` | 현재 구현에서 동일 질의 직렬화, exit 0 |
| `cmp reports/phase4-save-fix1/bytes-before/mock-responses.json reports/phase4-save-fix1/bytes-after/mock-responses.json` 및 recorded 파일 쌍 | 둘 다 exit 0, 수정 전/후 응답 바이트 동일 |
| `uv run python /tmp/save-review-compare.py` | ingest 파일 전체 및 mock dev/test 반복 report의 결정적 부분 바이트 동일 |
| `uv run jupjup migrate-db --db reports/phase4-save-fix1/cli.db` 2회 | 두 번 모두 version=28, applied=True, 동일 checksum |
| `sha256sum src/jupjup/storage/migration.py`, `git diff e666915^ HEAD -- src/jupjup/storage/migration.py data/baselines tests/fixtures/search_trace/explain_false_baseline.json` | v27 SHA-256 보존, 해당 diff 없음 |
| `git diff --check` | 통과 |

전체 pytest 경고 3건은 기존 Starlette/httpx 비권장 1건과 fake local 준비 실패(extra_missing, sha_mismatch)를 의도적으로 검증하는 2건이다. 실제 embed/rerank/GGUF 테스트 5개는 기본 marker 정책으로 제외됐다. 기본 가상환경의 `llama-cpp-python`, `torch`, `sentence-transformers` distribution은 모두 미설치임을 `importlib.metadata`로 직접 확인했다.

독립 probe 최초 실행은 임시 파일의 모듈 경로에 저장소가 없어 `tests` import 단계에서 실패했다. `PYTHONPATH=.`를 지정해 재실행했다. 수정 전 recorded 바이트 probe도 임시 소스 루트의 기본 녹화 경로가 없어 실패했으며, 원본 `data`를 임시 루트에 연결한 뒤 양 모드 모두 재실행했다. 이는 검수 실행기 경로 문제로 제품 결함에 산입하지 않았다.

## 3. M1·L1 완료 조건 직접 대조

| 완료 조건 | 직접 확인한 결과 |
|---|---|
| M1 재현 1 | `saved_at=2026-11-03T10:00:00+09:00`에 UTC `[00:00Z,02:00Z)` 요청: 수정 전 items=[]로 assertion 실패. 현재는 해당 1건을 반환. 동등한 KST `[09:00+09:00,11:00+09:00)` 요청도 동일 |
| M1 재현 2 | 위 01:00Z 저장물과 02:00Z 저장물의 `order=desc&limit=1`: 수정 전 10:00+09:00를 먼저 반환해 실패. 현재는 실제 최신인 02:00Z를 먼저 반환 |
| 혼합 offset·새 쓰기 | 구 데이터 +09:00/Z/−05:00를 backfill한 뒤 공개 API의 새 UTC 저장물을 추가해 시간순 확인 |
| 경계·정밀도 | .000000/.000001/.999999, 같은 instant의 서로 다른 표기, `[from,to)` 시작 포함·끝 제외. 목록과 기존 검색 hard filter 결과 집합 일치 |
| 정렬·cursor | saved_at/updated_at 각각 asc/desc, limit 1/2 전체 순회에서 누락·중복 없음. 추가 독립 probe는 두 시각의 순서를 서로 다르게 만들고 limit 1/2/7/20에서도 전체 순회 일치 |
| 실제 구 DB upgrade | 비교 컬럼이 없는 실제 v27 파일 DB에서 v28 upgrade. 시각 원문·마이크로초·FK·v27 checksum 보존, backup 생성, 수동 정책 시작 거절, 재실행 파일 바이트 불변 |
| migration 실패 | 잘못된 기존 updated_at 입력에서 새 컬럼·migration record rollback. v28 checksum 변조 후 재실행 거절 |
| 쓰기 경로·인덱스 | repository upsert, 공개 create 형태, 기존 UPDATE 형태에서 trigger로 비교 키 갱신. EXPLAIN에서 새 인덱스 3종 사용과 임시 정렬 B-tree 없음. 실제 목록 SQL의 시각 컬럼에 datetime/julianday 함수 없음 |

v27 원본 SHA-256은 `00203354641a98ef1f44f5dcd5a0530cda8a1891956a7a6234b0e5c8e520b9d4`, v28 상태 checksum은 `8b1561ebaed3c45c6f268dd697d145d35fef873dd1bfff2b0da3af5221cca170`이다. 원문 시각을 바꾸지 않아 PRD 6.2절 기존 +09:00 저장 데이터와 검색 응답 표기를 보존한다.

## 4. 검색 회귀·바이트 동일성·실제 모델 배제

| 모드/분할 | Recall@10 | MRR@10 | nDCG@10 | 사용자 격리/필터 위반 |
|---|---:|---:|---:|---:|
| mock/dev | 0.961975 | 0.995798 | 0.979497 | 0 / 0 |
| mock/test | 0.942000 | 0.986667 | 0.958865 | 0 / 0 |
| recorded/dev | 0.971218 | 1.000000 | 0.985990 | 0 / 0 |
| recorded/test | 0.972000 | 0.991111 | 0.980055 | 0 / 0 |

기준선이나 기준을 갱신하지 않았고 네 조합 모두 기존 수치를 유지했다. test split 평가는 mock 또는 녹화 재생으로만 수행했다. 모델 import guard 및 런타임 미설치 상태에서 두 test 평가가 통과해 실제 모델 실행이 없음을 확인했다. 사람 reviewed 0건과 recorded/test 하한 여유 0은 기존 known issue로 유지하며 이번 수정의 결함으로 추가 감점하지 않는다.

검색은 수정 전/후 독립 프로세스에서 같은 원본 데이터로 응답 전체를 canonical UTF-8 JSON에 직렬화하고 `cmp`로 비교했다. 원래 비결정적인 `query_id`, `timing_ms`만 제외했으며, saved_at offset을 포함한 나머지 모든 응답 필드를 보존했다. mock 259개는 **666,663 bytes**, SHA-256 `a01182d9d8c0a711d7ec8a8c16bf2390e205827dc66cee18be230ba377f4dd81`; recorded 259개는 **696,499 bytes**, SHA-256 `fef956c608c0ab744f5ba3c52695555dad8ce22d4d7d137ca59542a3bd57adde`로 양쪽이 일치했다. 기존 `test_explain_false_results_byte_identical_to_baseline` 두 모드도 guard 아래 통과했고 baseline 파일 변경은 없다.

mock ingest 두 JSON 파일은 제외 필드 없이 **파일 전체 26,826 bytes 동일**, SHA-256 `e3c79ef4cc82a0f54779035b1107cc89d693a50620928e41d3353ac6a38890aa`다. mock 검색 eval 반복 report는 최상위 `created_at`, `git_sha`, `perf`만 제외하고 전체를 canonical JSON 바이트로 비교했다. dev 234,083 bytes / `37d42d2eb61f380fde076870579316344d7acee2c16b6f3455987786deacda33`, test 156,113 bytes / `72598c0b955c1c80384656519a69f1267a5c6fd8ff729b4c0e413a9e719c4428`로 동일했다. 실행 시각·실측 latency를 포함하는 원본 검색 report 파일 전체가 같다고 주장하지 않는다.

저장 API 조립·text/image 인제스트·검색·GET·재분석·trace 경로와 네 eval 조합은 네트워크 guard 아래 통과했다. 설계 7.2절이 허용하는 I1 공개 URL HTTP 수집은 별도 경로다. 따라서 URL worker 전체를 무통신이라고 해석하지 않았다. 전체 pytest의 fetcher 테스트는 resolver/transport stub 및 로컬 서버로 SSRF·redirect·크기·압축·deadline을 확인하며, 이번 diff는 fetcher나 모델 제공자를 바꾸지 않는다.

## 5. 파일:줄 피드백 — 심각도 순

**미해결 높음·중간·낮음 결함 없음.** 아래는 기존 지적의 종결 근거와 구현 확인이며 추가 감점 항목이 아니다.

1. **[기존 중간 M1 — 해결]** `src/jupjup/save/query.py:126`, `:138`, `:140`, `:143`, `:201`: 필터·정렬·keyset 비교·cursor 생성이 같은 instant 표현을 사용한다. `src/jupjup/storage/instant.py:10`, `:23`에서 aware 입력을 UTC 마이크로초 6자리로 맞추므로 문자열 길이/offset 차이 때문에 같은 instant의 id tie-breaker가 깨지지 않는다. 재현 1·2와 독립 혼합 offset probe 통과. 추가 수정 요구 없음.
2. **[기존 낮음 L1 — 해결]** `tests/integration/test_save_time.py:33`, `:48`, `:57`: 기존 검수 두 재현을 별도 테스트로 고정하고 혼합 offset·음수 offset·초 미만·새 UTC 쓰기·asc/desc·전체 cursor 순회를 보강했다. `tests/unit/test_instant_migration.py:18`, `:48`, `:65`는 실제 구 DB, 실패 rollback, 새 쓰기와 인덱스까지 검증한다. 추가 수정 요구 없음.
3. **[보존·안전성 확인]** `src/jupjup/storage/migration_v28.py:21`, `:44`, `:51`, `:61`, `:70`, `:92`: 기존 버전 checksum 확인, backup, transaction, backfill, timestamp trigger, rollback을 확인했다. `src/jupjup/storage/db.py:20`에서 연결마다 결정적 함수를 등록한다. 비교 키는 내부 파생 데이터이며 공개 응답의 원문을 바꾸지 않는다. 등록되지 않은 외부 SQLite 연결의 시각 쓰기는 trigger 함수 부재로 실패하므로 운영상 애플리케이션 연결을 사용한다는 구현 보고서의 제한은 타당하다. 범위 내 재현 결함 없음.
4. **[검색 호환 확인]** `tests/integration/test_demo_trace.py:319`, `tests/integration/_search_digest.py:48`: 기존 응답 전체의 digest 회귀 테스트 통과와 별도로 수정 전/후 실제 직렬화 바이트를 비교했다. `src/jupjup/search/`, `src/jupjup/query/`, 분석기·prompt·eval 본체·녹화본·기준선은 시각 수정에서 변경되지 않았다.

## 6. 채점과 후속

| 항목 | 점수 | 근거 |
|---|---:|---|
| 정확성 | 40 / 40 | M1 두 재현 해결, 날짜 경계·정렬·cursor·동일 instant·마이크로초·구 DB/신규 쓰기 검증 통과. 검색 전후 바이트 동일, 전체 회귀와 네 평가 게이트 통과 |
| 안전성 | 30 / 30 | 입력·사용자 격리·경쟁·삭제·migration backup/rollback/checksum 회귀 통과. guard 실행의 모델 import/통신 시도 없음. 새 데이터 손실·노출 결함 미발견 |
| 유지보수성 | 30 / 30 | UTC 비교 표현과 bind 정규화가 한 모듈에 있고 쓰기 정합성은 trigger에서 유지. v27 불변·v28 전진 적용. L1 회귀 사례 보강, ruff/mypy 통과 |
| **합계** | **100 / 100** | **PASS** |

이전 검수의 M1 −4점과 L1 −1점 근거가 모두 해소됐다. 확인되지 않은 위험이나 사람 검수 미완료를 이유로 감점하지 않았다. 루프백 및 재검수 조건은 없다. 미검수 골든셋의 제품 품질 판정과 실제 모델 평가는 기존 별도 트랙으로 남는다.

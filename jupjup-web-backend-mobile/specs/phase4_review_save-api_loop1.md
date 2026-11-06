# Phase 4 최종 검수 — 저장 코어 T27, Loop 1/3

- **점수:** 95 / 100
- **상태:** PASS
- **항목별:** 정확성 36 / 40, 안전성 30 / 30, 유지보수성 29 / 30
- **피드백:** 아래 M1, L1 참조. 기존 offset 시각을 가진 보관함의 날짜 필터·정렬에 결함이 남는다.
- **루프백 대상:** 필수 루프백 없음(PASS). M1·L1은 Phase 2 후속 수정 권고.
- **검수자:** Claude-Reviewer 역할 대행(Codex 실행)
- **검수일:** 2026-11-03
- **검수 HEAD:** `4dd2bea` (`feat: implement Phase 2 save core and public content API`)
- **기준:** `CLAUDE.md`, `.claude/agents/claude-reviewer.md`, `specs/design_save_api.md` 전체(T27a~h, AC-S1~S28), `specs/prd_and_design.md` 5.9·5.10·6.2절, `specs/known_issues.md`, `specs/phase2_save_api_report.md`.
- **이전 검수:** save-api loop 보고서는 없었다. 기존 search-api 및 관련 Phase 4 보고서의 채점 정책을 참고했다. 사람 검수 미완료 자체, 트랙 B 분석 품질, Instagram 데모, 실제 인증 제공자는 감점하지 않았다.

## 1. 판정

저장·승인·재분석의 주요 기능, 사용자 격리, 멱등·중복 경쟁, 사용자 수정 보존, 삭제 및 실패 복구는 직접 실행한 테스트에서 통과했다. 전체 회귀와 정적 검사도 통과했다. 다만 AC-S4의 기존 시간대 데이터에 대한 날짜 필터·시간순 정렬은 완전히 충족하지 않는다(M1). 이 결함을 포함해 95점으로 PASS 판정한다. 모든 인수 기준이 예외 없이 통과했다는 뜻은 아니다.

코드·설정·기준선·녹화본은 수정하지 않았다. 실행 산출물은 ignored 경로 `reports/phase4-save-review/`, 추가 검증 스크립트와 로그는 `/tmp/save-review-*`에 두었다. 커밋 대상은 이 리뷰 파일 하나다.

## 2. 직접 실행한 명령과 결과

아래 명령은 모두 이 워크트리에서 직접 실행했다. 표의 `eval` 축약 명령도 실제로는 `uv run jupjup eval`로 실행했다.

| 명령 | 직접 확인한 결과 |
|---|---|
| `uv run pytest` | **1,388 passed, 5 deselected, 3 warnings**, 149.32초 |
| `uv run ruff check src tests` | All checks passed |
| `uv run mypy src` | Success: no issues found in 103 source files |
| `uv run jupjup eval validate` | exit 0. 검색 seeds 200 / queries 259(dev 158, test 101), ingest 80(dev 48, test 32) |
| `eval run --mode mock --split dev --baseline data/baselines/mock.json --out reports/phase4-save-review/mock-dev` | exit 0, 기본·회귀 게이트 통과 |
| `eval run --mode mock --split test --baseline data/baselines/mock.json --out reports/phase4-save-review/mock-test` | exit 0, 기본·회귀 게이트 통과 |
| `eval run --mode recorded --split dev --baseline data/baselines/recorded.json --out reports/phase4-save-review/recorded-dev` | exit 0, 기본·회귀 게이트 통과 |
| `eval run --mode recorded --split test --baseline data/baselines/recorded.json --out reports/phase4-save-review/recorded-test` | exit 0, 기본·회귀 게이트 통과 |
| `eval ingest --mode mock --out reports/phase4-save-review/ingest-a` 및 `ingest-b` | 두 번 모두 exit 0. 기본 test 32건, schema_final_pass_rate=1.0, injection_resistance=1.0, 회귀 게이트 통과 |
| mock dev/test 검색을 각각 `mock-dev-b` / `mock-test-b`로 재실행 | 둘 다 exit 0. 아래 결정성 비교도 일치 |
| `uv run jupjup migrate-db --db /tmp/save-review-migration.db` 2회 | 두 번 모두 v27 applied=true, 같은 checksum |
| `uv run python /tmp/save-review-service-guard.py` | 모델 import·외부 socket 차단 상태에서 저장 API 통합 **30 passed**(2.79초) |
| `uv run python /tmp/save-review-guard.py eval run --mode mock --split test --baseline data/baselines/mock.json --out reports/phase4-save-review/guard-mock-test` | exit 0, 모델 import/네트워크 시도 없음 |
| 같은 guard로 recorded/test, recorded baseline, `guard-recorded-test` | exit 0, 모델 import/네트워크 시도 없음 |
| 같은 guard로 `eval ingest --mode mock --out reports/phase4-save-review/guard-ingest` | exit 0, 모델 import/네트워크 시도 없음 |
| `uv run python /tmp/save-review-probes.py`, `/tmp/save-review-time-sort.py` | M1 필터 누락과 잘못된 시간순 재현. 정상 저장·job full trace도 조회 |
| `uv run python /tmp/save-review-compare.py` 및 추가 JSON 비교 | ingest JSON 전체·검색의 결정적 부분 일치(3절) |
| `git diff 17e852b HEAD --` 설계 1.3절 제외 경로·`data/baselines`·`data/recordings` | 변경 없음. 검색·query·demo, 분석기·prompt·eval·provider 본체 변경 없음 |

pytest 경고 3건은 Starlette/httpx 비권장 1건과 fake local 준비 실패(`extra_missing`, `sha_mismatch`)를 의도적으로 확인하는 2건이다. 실제 GGUF·embed·rerank 테스트 5개는 기본 marker 정책으로 제외됐다.

| 모드/분할 | Recall@10 | MRR@10 | nDCG@10 | 사용자 격리/필터 위반 |
|---|---:|---:|---:|---:|
| mock/dev | 0.961975 | 0.995798 | 0.979497 | 0 / 0 |
| mock/test | 0.942000 | 0.986667 | 0.958865 | 0 / 0 |
| recorded/dev | 0.971218 | 1.000000 | 0.985990 | 0 / 0 |
| recorded/test | 0.972000 | 0.991111 | 0.980055 | 0 / 0 |

기존 수치와 같다. 사람 reviewed 0건은 제품 품질 인증으로 해석하지 않았고 감점도 하지 않았다. recorded test의 회귀 하한 여유 0은 기존 이슈이며 이번 변경의 회귀가 아니다.

## 3. 모델·네트워크·결정성

기본 설치의 `llama-cpp-python` distribution이 없음을 `importlib.metadata`로 확인했고, 앱 조립·저장·워커·trace 실행 뒤 `llama_cpp`가 `sys.modules`에 없었다. 추가 guard는 `sys.meta_path`에서 `llama_cpp`, `torch`, `sentence_transformers`, `huggingface_hub` import를 실패시키고, eval guard에서는 외부 API SDK도 차단했다. Python audit hook으로 `socket.connect`, `socket.getaddrinfo`, `socket.sendto`를 예외 처리했다. mock/recorded test 평가와 저장 API 통합 30개가 이 상태로 통과했다. 따라서 이 실행들에서 실제 모델이 동작하거나 외부 통신을 시도하지 않았다.

설계 7.2절은 **I1 공개 URL 수집의 HTTP만 허용**한다. URL worker 전체가 네트워크를 쓰지 않는다고 주장하지 않는다. HTTP fetcher 단위 테스트는 resolver/transport stub과 로컬 서버로 검증하며, 공개 IP 고정 연결, private IP·redirect 차단, 크기·gzip 제한과 DNS deadline을 포함한다. 검색·분석·GET·재분석 경로에서 원본 재수집이나 모델 다운로드를 발견하지 않았다.

- mock 인제스트 `eval_ingest_mock_test.json` 두 파일: **26,826 bytes, 전체 파일 바이트 동일**. SHA-256 `e3c79ef4cc82a0f54779035b1107cc89d693a50620928e41d3353ac6a38890aa`.
- mock 검색 dev/test: report의 명시적 비결정 필드 `created_at`, `git_sha`, `perf`만 제외하고 나머지 전체(각 질의 결과·순위·점수·실패·게이트 포함)를 canonical UTF-8 JSON으로 직렬화하여 바이트 비교했다. **둘 다 동일**.
- 검색 dev SHA-256: `76a70ebd77c1622820a3c8e55d26503e2177f98a2a66b124840207bc0187ee22`.
- 검색 test SHA-256: `e22e410329e8e480703f8082c62ac060b1ebad642282b0e445eed84f6a596897`.
- 검색 report 원본 파일 전체는 실행 시각·실측 latency 때문에 다르다. 이를 결과의 비결정성으로 감점하지 않았다. 임의 id와 실제 시간이 포함된 저장 HTTP/trace 전체의 바이트 동일성을 주장하지 않는다.

## 4. 작업별 완료 조건·인수 기준 대조

아래 테스트는 전체 pytest에서 직접 실행했고, 저장 API 통합 테스트 30개는 위 guard 아래 다시 실행했다. 구현 보고서의 PASS 주장을 단순 인용하지 않았다.

| 작업/인수 기준 | 검증 근거와 판단 |
|---|---|
| T27a / AC-S25 | `test_save_migration.py`: 빈·구 DB, 재실행, 백업, 수동 정책, FK/count/index, checksum 변조 거절, DDL rollback, AI/user 분리 통과. CLI v27 두 번 동일. 기존 offset 값의 목록 해석은 M1 예외 |
| T27b / AC-S22~23 | `test_save_auth.py`, API acceptance: 헤더 오류, prod dev-header 시작 실패, 외부 bind override 거절, non-dev admin 404 통과. 타 사용자 content/job/candidate/full trace 접근 404 |
| T27c / AC-S11~13, S21, S24 | repository/dedupe/HTTP fetcher 테스트: canonical hash, replay/conflict/in-progress, 키 제한, URL 정규화, SSRF/redirect/크기/압축/DNS 제한 통과. 로그·에러의 source/note/key 비노출 |
| T27d / AC-S1~2, S13~15 | 세 source 접수, text/image 처리, URL stub 수집, 정확 replay, URL 사용자별 중복, 파일 DB 동시 create, hash claim 경쟁 통과. alias는 목록/검색 제외, canonical 안내 |
| T27e / AC-S3~4, S17 | effective/AI/user 층, snapshot 상세, 태그 AND 및 필터, 동일 saved_at id tie pagination, cursor 변조·사용자·필터 경계 통과. 원본 fetcher를 실패시키고도 GET/search 보존. **AC-S4 혼합 offset 날짜 필터·정렬은 M1 실패** |
| T27f / AC-S5~7, S16 | summary/tag/detail set/clear/no-op, tombstone, schema 거절, ETag conflict, hide/unhide 검색, DELETE cascade 통과. analyze 중 삭제 후 stale worker가 콘텐츠를 부활시키지 못함 |
| T27g / AC-S9~10, S19~20 | I5 confirm 대기, 미승인 analysis run, effective/검색 미반영, approve persist 재개, reject snapshot/축약 검색 보존, 같은 결정 멱등·반대 결정 충돌 통과. trace 입력·model/profile/prompt/meta·출력/evidence/검증/event 보존 및 삭제 cascade 확인. 없는 점수·진행률·숨은 사고 과정 생성 없음 |
| T27h / AC-S8, S16, S18, S26~28 | snapshot 재분석, active conflict, I6/approve와 PATCH 경합, 성공 및 I6 이후 실패의 AI 복원/user 층 보존 통과. mock/fake local 포트 조립, OpenAPI union/status/error, 기존 search/index/ingest 회귀 통과 |

## 5. 파일:줄 피드백 — 심각도 순

### M1. 중간 — 기존 offset 시각을 가진 저장물이 날짜 필터에서 누락되고 시간순 정렬이 틀린다

- 위치: `src/jupjup/save/query.py:125`, `:135`, `:140`, `:160`; 원인 연결: `src/jupjup/storage/repositories.py:50`, `src/jupjup/storage/migration.py:105`.
- 목록은 SQLite TEXT 시각을 그대로 비교·정렬하지만 필터 경계만 UTC 문자열로 바꾼다. repository는 입력 offset을 유지하고 migration은 기존 날짜를 정규화하지 않는다. PRD 6.2절 기존 데이터는 `+09:00`이며 설계 5.1절도 그 데이터의 의미 보존을 요구한다.
- 직접 재현 1: 저장물 `saved_at='2026-11-03T10:00:00+09:00'`(UTC 01:00)에 `GET /v1/contents?saved_from=2026-11-03T00:00:00Z&saved_to=2026-11-03T02:00:00Z` → **200, items=[]**. 기대는 1건이다. 접수한 콘텐츠의 DB 시각을 기존 데이터 표현으로 설정해 재현했다.
- 직접 재현 2: 위 저장물과 `2026-11-03T02:00:00+00:00` 저장물을 두고 `order=desc&limit=1` → **10:00+09:00가 첫 항목**. 실제로 더 최신인 02:00Z가 먼저여야 한다. 같은 원시 TEXT 값을 쓰는 cursor 정렬도 실제 시간순 계약을 만족하지 못한다.
- 영향: 기존/시드/admin 데이터와 신규 UTC 콘텐츠를 함께 보관하는 정식 목록의 날짜 필터·정렬(AC-S4). 데이터 삭제나 사용자 간 노출은 관찰되지 않았다.
- 개선: offset을 실제 instant로 비교하는 표현을 필터·정렬·cursor에 일관되게 쓰거나, **새 버전 migration**으로 기존 시각과 쓰기 경로를 동일 UTC 표현으로 정규화한다. 적용된 v27의 소스를 고치면 checksum 거절이 생기므로 과거 migration 수정으로 해결하지 않는다. 초 미만 정밀도와 기존 인덱스 사용도 함께 검토한다.

### L1. 낮음 — 날짜 경계 회귀 테스트가 저장 측의 혼합 offset을 다루지 않는다

- 위치: `tests/integration/test_save_acceptance.py:261`, `tests/integration/test_save_api.py:117`.
- 현재 날짜 테스트는 요청 경계의 `+09:00`을 확인하지만 `_client`의 고정 UTC 시계로 저장한다. 동일 시각 pagination도 같은 표현만 써서 M1을 잡지 못한다.
- 개선: 구 DB/seed의 `+09:00`과 신규 `+00:00` 혼합 데이터를 넣고 UTC와 KST 양쪽 경계 요청, asc/desc 및 cursor 페이지 전체를 비교한다. 같은 instant의 다른 offset 표기도 id tie-breaker가 일관되는지 고정한다.

## 6. 채점 근거와 후속

| 항목 | 점수 | 근거 |
|---|---:|---|
| 정확성 | 36 / 40 | M1 −4: 날짜 필터의 실제 누락과 혼합 시각의 잘못된 정렬. 나머지 직접 검증 경로와 전체 회귀 통과 |
| 안전성 | 30 / 30 | 재현된 격리·입력·SSRF·민감 로그·경쟁·삭제 안전성 결함 없음. 실제 인증 및 URL 수집 자체의 허용은 확정된 범위에 따라 판단 |
| 유지보수성 | 29 / 30 | L1 −1: 구 데이터 호환에 필요한 혼합 offset 회귀 사례 누락. 부분 갱신과 transaction 경계, migration rollback/checksum, 서비스/DTO 분리와 테스트 구조는 확인됨 |
| **합계** | **95 / 100** | **PASS** |

필수 재검수 루프는 열지 않는다. M1·L1은 Phase 2 후속으로 처리할 것을 권고한다. 수정 시 혼합 offset의 실제 시간순 필터·cursor 회귀와 migration 보존 검증을 실행하고 기존 pytest/ruff/mypy/eval을 유지해야 한다. 범위 밖 품질 튜닝이나 사람 검수 미완료를 이유로 추가 감점하지 않았다.

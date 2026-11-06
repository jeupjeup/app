# Phase 4 검수 — 계정별 데이터 분리 (Loop 1)

- 대상: `ae19c74` (부모 `92d6364`) "Scope saved data to authenticated accounts and run queued analysis"
- 검수자: Claude-Reviewer · 2026-11-06

## 판정

- **점수:** 91 / 100 (정확성 37/40 · 안전성 28/30 · 유지보수성 26/30)
- **상태:** PASS
- **블로커:** 없음
- **루프백 대상:** 없음. 아래 M1~M2는 후속 Phase 2 작은 작업으로 처리하길 권장.

## 확인한 것

| 항목 | 결과 |
|---|---|
| 인증 경계 | 세션(`Authorization`) 있으면 dev 대체를 쓰지 않음. 잘못된/빈 토큰은 401 (`auth.py:53-66`). dev 헤더는 `u_account_*` 사칭을 막음 (`auth.py:35`). GET/HEAD/OPTIONS와 `/v1/search`, `/v1/query:parse` 말고 dev 헤더로 하는 요청은 401 (`auth.py:73-82`). `env=prod`와 `app_session`에서는 dev 대체가 꺼짐 (`app.py:274`). |
| 계정 간 유출 | 콘텐츠·컬렉션·잡·검색·재분석·멤버십을 다른 계정이 접근하면 404가 남. 테스트로 확인 (`tests/integration/test_account_scoping.py`). 컬렉션 멤버십은 기존 콘텐츠 소유 검사를 그대로 씀 (`collections/service.py:153`). 멱등 키는 계정별로 따로 다룸 (bob이 같은 키로 저장해도 새 콘텐츠가 생김). |
| 마이그레이션 / 데모 보존 | 추가만 하고, 기존 `api_users`는 이전 `u_account_<hex>` 규칙 그대로 매핑함. 데모 네임스페이스(`u_frontend_dev`)는 건드리지 않음. **실제 PM 백업 DB 사본**(`frontend-before-collections-*.db`)에 돌려 봄: contents 4건과 ingest_jobs 8건 수가 같았고, `foreign_key_check`도 깨끗함. `auto_migrate=False`면 `MigrationError`를 냄. 다시 돌려도 결과가 같음. |
| 계정 삭제 | `api_users` 삭제가 CASCADE로 `account_scopes` 삭제로 이어지고, 트리거가 contents·collections·idempotency_keys·index_revisions를 지움. 테스트에서 bob의 데이터만 지워지고 데모 데이터는 남는 것을 확인. |
| 워커 수명주기 | lifespan에서 데몬 스레드를 시작하고, 종료 때 `stop.set()` 후 `join(5s)`. 설정 기본값은 False, CLI `api serve`는 기본 `--with-worker`. 잡이 queued에서 succeeded로 끝까지 가는 것을 테스트로 확인. |
| 세션 유지 (프론트) | `useSyncExternalStore`가 같은 탭 이벤트와 `storage` 이벤트를 구독함. 모든 쿼리 키가 `env.userId` 대신 `scope`(계정 id 또는 데모)를 씀. 남은 `env.userId` 사용처는 배너 한 곳뿐. 세션이 없으면 GET과 검색에만 `X-User-Id`를 붙임 (`client.ts:23`). 로그아웃하면 서버 세션을 무효화하고 로컬 세션을 지움. |

## 실행한 검사

- `pytest tests/integration/test_account_scoping.py tests/unit/test_save_auth.py tests/integration/test_api_ingest.py tests/integration/test_save_api.py tests/integration/test_api_search.py tests/integration/test_api_ingest_worker_split.py`: 모두 통과.
- 전체 `pytest`: 6개 실패 (`test_ingest_record_replay.py` 2개, `test_ingest_golden_v2.py` 4개). **부모 `92d6364`에서도 같은 6개가 실패함**. 이번 커밋 때문이 아니라 원래 있던 문제임 (YouTube `SOURCE_TEXT_UNAVAILABLE` 코드와 골든 재봉인 관련).
- PM `var/demo.db`(11/2)는 v27 마이그레이션(`migration.py:156`, 이번 커밋에서 바뀌지 않음)에서 "row count changed"로 실패함. 이것도 원래 있던 문제이고 이번 범위 밖.
- 프론트 vitest와 tsc는 **실행하지 못함**. 이 워크트리에 `frontend/node_modules`가 없음. PM 쪽에서 `npm test`와 `tsc`를 돌려 확인해야 함.

## 피드백

### Medium
- **M1 `src/jupjup/cli.py:104` + `src/jupjup/api/app.py:250-258`, 내장 워커 기본 ON과 자리 표시자 분석기.** API 프로세스에서 분석기 조립에 실패하면 `_submit_only_ingest_service`가 `UnavailableAnalyzer`로 대체함 (`app.py:220-233`). 이때 기본으로 켜진 내장 워커가 analyze 단계에 온 잡을 재시도 없이 실패시킴. 기존 운영 방식대로 `jupjup worker`를 따로 띄워 둔 경우에는 두 워커가 lease를 나눠 가져, 일부 잡만 이유 없이 실패하게 됨. → 분석기를 쓸 수 없을 때는 내장 워커를 시작하지 않고 경고를 남기거나, 분석기 상태가 정상일 때만 켜도록 바꾸기. 문서에도 "따로 띄운 워커와 같이 쓰지 말 것"을 적기.
- **M2 `src/jupjup/storage/account_migration.py:26-31`, 계정 삭제와 진행 중인 잡.** 트리거가 contents를 지울 때 그 계정의 잡이 워커에서 실행 중이면, 나중 단계가 FK 오류로 실패하거나 주인 없는 행을 다시 만들 수 있음 (확인하지 못함. 유출은 아니고 고아 데이터 위험). 메모리 검색 인덱스에 삭제된 계정의 항목이 남는 것도 같은 문제임. → 삭제 전에 그 계정의 queued/running 잡을 취소하고 인덱스를 비우는 처리와 테스트를 추가하기.

### Low
- **L1 `frontend/src/features/archive/ArchiveLayout.tsx:100`**: 로그인한 상태에서도 배너가 "로컬 개발 사용자: {env.userId}"로 나옴. 세션 상태에 맞게 문구를 바꾸기.
- **L2 `src/jupjup/auth.py:73-82`**: 쓰기를 막는 규칙이 경로 문자열 허용 목록과 HTTP 메서드에 묶여 있음. `contents:write` scope는 정의만 있고 어디서도 검사하지 않음. 새 POST 읽기 라우트를 추가하면 조용히 401이 남. → 라우트별 `require_scope("contents:write")` 의존성으로 바꾸는 걸 고려하기.
- **L3 `frontend/src/shared/auth/session.ts:36-43`**: 로그아웃해도 이전 계정의 React Query 캐시가 메모리에 남음 (scope 키로 분리돼 있어 화면에는 안 나옴). `queryClient.removeQueries`로 정리하면 더 안전함.
- **L4 `tests/legacy_api.py`**: 예전 테스트에서 dev 헤더로 쓰기를 허용하는 우회 장치임. 실제 앱에서 import하지 않는다는 점이 주석에만 적혀 있음. → `src/`에서 import하지 못하게 막는 린트 규칙을 두면 좋음.

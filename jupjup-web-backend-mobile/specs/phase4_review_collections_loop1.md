# Phase 4 독립 검수: 수동 컬렉션 (Loop 1)

- **점수:** 89 / 100 (정확성 33 / 안전성 29 / 유지보수성 27)
- **상태:** REJECT
- **루프백 대상:** Phase 2 — 컬렉션 색상 편집 UI 구현 및 회귀 테스트 추가

## 피드백

- **`frontend/src/features/archive/CollectionEditor.tsx:8-28` — 컬렉션 색상을 사용자가 수정할 수 없습니다.** 편집기는 이름만 상태로 관리하고 `updateCollection(collection.id, name)`만 호출합니다. 색상 입력·전송 경로가 없어 사용자는 생성 시 기본 색상을 계속 사용하게 됩니다. `specs/design_collections.md`의 이름·색 수정 요구를 충족하지 못하므로 Phase 2로 되돌립니다. 색상 수정 컨트롤을 추가하고 API의 `#RRGGBB` 검증과 저장된 색 표시까지 UI 테스트로 확인해야 합니다.

## 확인한 범위

- `src/jupjup/collections/{routes,service}.py`, `storage/migration_v29.py`, `save/query.py` 및 관련 테스트를 검토했습니다. 사용자별 CRUD와 동일 404, NFC+trim 및 NFC+casefold 충돌 409, API 색상 형식 검증, 양쪽 소유권 검사와 복합 FK, 관계의 idempotent 추가·삭제/cascade, 콘텐츠 보존, hidden/duplicate 제외 count, collection cursor 격리와 기본 cursor 호환을 확인했습니다.
- 관계 변경은 콘텐츠 레코드·분석·인덱스 변경 없이 동작하며, pending 분석 후보와 사용자 summary/tags 보존 테스트를 확인했습니다. 검색 순위와 기존 분류 동작을 바꾸는 변경은 발견하지 못했습니다.
- 목록/상세/선택 흐름과 첫 20개 이후 페이지 조회, 실패 입력 보존·재시도, pending 중복 클릭 차단, 삭제 확인 문구를 프론트 테스트에서 확인했습니다. 자동 AI 정리·공유·협업·즐겨찾기·OAuth는 구현 범위 밖입니다.
- `migration_v29.py`에서 v27/v28 파일은 변경되지 않았고, 백업, 원자적 DDL rollback, `BEGIN IMMEDIATE` 뒤 동일 연결 재검사, fresh/v28 초기화와 별도 프로세스 동시 bootstrap 테스트를 확인했습니다.

## 검증

- Backend ownership/migration: **9 passed**
- Save API/acceptance/time 회귀: **33 passed**
- Frontend: **33 passed / 9 files**, typecheck 및 production build 통과
- ruff 통과, mypy **112 source files** 통과, `git diff --check` 통과
- Frontend lint는 비차단 경고 7개를 출력했습니다.
- 검수 워크트리와 `/Users/minjun/orca/workspaces/dc2/phase-2-collections`의 git tree가 동일함을 확인하고 안내된 기존 `node_modules`/PM `.venv`를 재사용했습니다. 실DB·실서버·원본 프론트·실브라우저는 조작하거나 검증하지 않았으며, 해당 최종 확인은 PM 담당입니다.

# Phase 2 수동 컬렉션 구현 보고

상태: 구현·검수·PM 병합 및 실서비스 반영 완료. 아래 초기 인계와 PM 최종 반영 기록을 구분한다. 단일 Codex-Primary, 다른 워커/서브에이전트 사용 없음.

## 변경

- `src/jupjup/collections/{routes,service}.py`: 사용자별 CRUD, NFC+trim 1~80자 및 NFC+casefold 중복 409, 안전한 hex 색상, 양쪽 소유권/동일 404, idempotent PUT/DELETE 관계 API.
- `storage/migration_v29.py`, `storage/db.py`, `cli.py`: v29 registry·백업·원자적 DDL. 관계 PK와 양쪽 `(id,user_id)` 복합 FK/cascade. v27/v28 원본·checksum 소스 무변경.
- PM 지적 반영: BEGIN IMMEDIATE **후 같은 connection에서** 버전/checksum 재검사. 기존 v28이면 역사 runner 재호출을 피한다. fresh/pre-v28 bootstrap은 별도 프로세스도 공유하는 Unix flock(`DB.migration.lock`)으로 불변 v27/v28 runner를 직렬화한다. 잠금 파일은 지우지 않아도 된다.
- `save/{dto,query,routes}.py`: collection_id 필터와 기존 keyset cursor, collection_ids(list/detail/alias), OpenAPI 목록 DTO. collection_id=None 기본 cursor scope 유지. count는 숨김/duplicate 제외.
- 프론트 `CollectionsPage`, `CollectionDetailPage`, `CollectionEditor`, `CollectionMembership`, typed collections client, archive query/store/adapters/router: 실제 API CRUD, 확인 후 삭제, 실패 입력 보존, pending 중복 클릭 차단, 다중 소속, 선택기·상세 페이지 추가 조회. 목록과 선택기는 첫 20건 이후를 서버에서 불러온다.
- `Sidebar`, `ArchiveCard`, `ContentDetailPage`, `HomeDashboardPage`, archive CSS: 서버 컬렉션 목록·추가 진입, 정확한 count, 카드/상세 소속 표시. 기존 디자인 클래스와 AccessibleDialog의 포커스·Escape·inert 유지. 미사용 UnsupportedPage 삭제.
- 캐시 key/무효화에 개발 사용자 범위와 collections/collection/contents/content/count를 포함한다. 관계 API는 인덱서 호출이나 contents UPDATE를 하지 않는다.

## 직접 검증 명령과 결과

작업 cwd는 이 워크트리. PM `.venv`와 기존 frontend node_modules symlink를 재사용했다. 설치·모델 다운로드 없음.

```sh
PYTHONPATH=src /Users/minjun/orca/workspaces/dc2/PM/.venv/bin/ruff check src tests/unit/test_collections_migration.py tests/integration/test_collections.py tests/integration/test_save_time.py tests/unit/test_instant_migration.py tests/unit/test_save_migration.py
PYTHONPATH=src /Users/minjun/orca/workspaces/dc2/PM/.venv/bin/mypy src/jupjup
PYTHONPATH=src /Users/minjun/orca/workspaces/dc2/PM/.venv/bin/pytest -o "addopts=-m 'not embed and not rerank and not local_llm'" -q tests/integration/test_collections.py tests/integration/test_save_api.py tests/integration/test_save_acceptance.py tests/integration/test_save_time.py tests/integration/test_indexing.py tests/integration/test_youtube_metadata.py tests/integration/test_ingest_pipeline.py tests/integration/test_api_ingest.py tests/integration/test_api_ingest_worker_split.py tests/unit/test_collections_migration.py tests/unit/test_save_migration.py tests/unit/test_instant_migration.py tests/unit/test_save_repositories.py tests/unit/test_save_dedupe.py tests/unit/test_save_auth.py tests/unit/test_youtube_metadata.py
npm --prefix frontend run check
npm --prefix frontend run build
node /Users/minjun/.agents/skills/impeccable/scripts/detect.mjs --json frontend/src/features/archive/CollectionEditor.tsx frontend/src/features/archive/CollectionMembership.tsx frontend/src/pages/archive/CollectionsPage.tsx frontend/src/pages/archive/CollectionDetailPage.tsx frontend/src/features/jupjup-dashboard/components/Sidebar.tsx
git diff --check
```

결과: ruff PASS, mypy 112개 소스 PASS, backend **146 passed / 2 skipped**(실제 live metadata 캡처 부재), frontend **33 passed / 9 files**, typecheck/build PASS. lint는 비차단 경고 7개(기존 Fast Refresh/효과 경고 및 새 CollectionMembership의 hook+component export 경고). detector `[]`, diff check PASS.

추가 CLI smoke: `collection_check_dir=$(mktemp -d /tmp/jupjup-collections.XXXXXX)` 후 `PYTHONPATH=src /Users/minjun/orca/workspaces/dc2/PM/.venv/bin/python -m jupjup.cli migrate-db --db "$collection_check_dir/check.sqlite"`를 두 번 실행. `/tmp/jupjup-collections.HO07x3/check.sqlite`에서 모두 version=29/applied=True/동일 checksum, 두 번째 추가 migration 없음.

주요 회귀: 사용자 격리/중복 이름 경합/관계 중복과 cascade/컬렉션 삭제 후 콘텐츠 존속/다중 소속·count·cursor/기본 cursor scope 호환/OpenAPI; awaiting_confirmation 후보와 사용자 summary/tag 수정 뒤 관계를 변경해 contents·snapshots·summaries·tags·detail_tags·jobs·runs·candidates·index_revisions 전체 행 동일 확인. fresh/v28 upgrade/재기동/DDL 실패 rollback/별도 연결 barrier·별도 프로세스 동시 초기화/seed replace·repository upsert 확인. 프론트 생성 실패 입력 보존·이름 변경·페이지 선택·소속 실패 재시도·삭제·pending 중복 요청/닫기 방지를 검증했다.

검증 중 수정: 과거 migration 테스트의 예상 최신 버전·백업 개수와 시간 회귀의 가상 v27 schema 픽스처를 v29 추가에 맞게 갱신. 테스트 기준 완화나 검색/평가 결과 변경 없음.

## PM 실행·복원 안내와 미해결

1. 병합 후 API/worker를 중지하고 실DB 별도 백업을 확보한다. 병합된 소스의 PYTHONPATH=src로 위 migrate-db 명령에 **PM이 선택한 실제 --db 경로**를 지정한다. v29 checksum 검증/FK 확인 후 기존 설정 그대로 API/worker를 127.0.0.1에 재시작한다. node_modules 재설치 없이 frontend build 가능.
2. v29 전 자동 `.bak`은 v28 상태다. 기존 소스로 복귀할 경우 API/worker를 모두 멈추고 v29 전 백업을 복원한다(진행 후 신규 콘텐츠/작업도 되돌아가므로 최신 DB를 별도 보관). 역방향 DROP migration은 제공하지 않는다.
3. 실DB·5177/8791 서버·기존 worker·원본 프론트는 수정/재시작하지 않았다. 실제 C++ awaiting_confirmation 항목을 읽거나 쓰지 않았다. 실브라우저/실DB migration/최종 배포 검증은 PM 담당으로 남긴다. OS 컴퓨터 사용·별도 UI 서버 구축 없음.
4. 범위 밖 자동 AI 분류/공유/협업/중첩/즐겨찾기/OAuth 미구현. 검색/query/embeddings 수정 없음. 외부 LLM·골든 test split·push 없음. 프론트는 저장된 기본색을 표시하며 색상 편집 UI는 추가하지 않았다.

커밋: `9183ab0`(backend/schema), 후속 frontend 커밋은 git log 참조. 모든 커밋에 요청한 Co-Authored-By 포함.

## PM 최종 반영 (2026-11-05 22:19 KST)

- 1차 검수의 색상 편집 UI 누락을 보완하고 2차 독립 검수 100점 PASS. 생성·편집 팔레트/사용자 지정색/이름과 색 전송/실패 입력 보존은 phase2_collections_color_fix_report.md 및 phase4_review_collections_loop2.md 참조.
- 실행 워크트리에서 별도 자동 적용 프론트 수정 2개를 발견해 덮어쓰지 않고 파일·패치 백업 및 23ca0a0 보존 커밋을 생성했다. 별도 워커가 해당 동작과 컬렉션을 함께 병합해 36개 UI 테스트/check/build 및 confirm API 회귀를 통과했다. 보존 커밋이 조상인 이력으로 실행 브랜치 fast-forward 완료. phase2_collections_integration_report.md 참조.
- 실DB 복사본의 v29 이행·재실행/FK 검사/기존14개 테이블 지문 보존 예행 PASS. 실제 서비스 중지 뒤 별도 DB 백업 확보, CLI v29 업그레이드, 기존14개 테이블 지문 동일·콘텐츠4개 보존·FK 위반 없음 확인 후 API/worker 재시작. 백업: `/Users/minjun/orca/workspaces/dc2/PM/var/backups/frontend-before-collections-20261105-221436.db` (Git 제외).
- 실제 API 검증 PASS: 생성/정규화 중복409/이름·색 수정/다중 소속/관계 PUT 멱등/사용자 격리404/컬렉션 필터·count/컬렉션 삭제 후 콘텐츠 보존/콘텐츠 삭제 cascade. 별도 검증 사용자 데이터만 생성·정리.
- 실제 브라우저에서 임시 컬렉션 생성과 하늘색 저장, C++ 강의 추가·카드 소속·count1, 이름/세이지색 변경, 소속 제외·count0 확인. 임시 컬렉션을 API로 삭제하고 기존 강의 존속 확인. 브라우저 native 삭제 확인창 직접 수락은 별도 검증하지 않았으며 삭제 API·컴포넌트 회귀로 확인했다.
- 현재 컬렉션 화면: http://127.0.0.1:5177/collections . 자동 AI 정리/공유/협업/중첩은 범위 밖이며 제공하지 않는다. 컬렉션 삭제는 콘텐츠를 삭제하지 않는다.
- 실행 API `term_bf87c794-20f2-4db3-a306-de3eb9f5ad66`, worker `term_e52a4b8e-3269-4003-a94d-2f2eaf0b52f3`, Vite는 기존 term_cd3df04c-ef52-4412-9c2a-e3003b1b1a37 유지. 기준 소스는 phase-2-frontend-integration 워크트리. AI 구현·검수 워커는 모두 종료.

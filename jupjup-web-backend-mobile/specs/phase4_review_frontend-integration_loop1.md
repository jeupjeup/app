# Phase 4 독립 검수: 프론트엔드 통합 loop 1

- 검수 대상: `30d1f68` 원본 import 이후 `3f6fb67`, `bae0555`, `2d5cbce` 변경 (PM 병합 `32dba0c`)
- 기준: `specs/design_frontend_integration.md`, `specs/phase2_frontend_integration_report.md`, 현재 save/search API 계약
- 방식: 현재 워크트리 코드 읽기 전용. 테스트는 동일 Git tree (`ab43a7c`)인 `/Users/minjun/orca/workspaces/dc2/phase-2-frontend-integration`에서 실행

## 판정

- **점수:** 98 / 100 (정확성 40 / 안전성 28 / 유지보수성 30)
- **상태:** PASS
- **루프백 대상:** 없음. 단, 아래 설정 가드 권고는 다음 정리 시 반영 가능

## 검수 근거

- 저장 POST는 content source와 automation level만 전송하고, `Idempotency-Key`를 같은 body 지문에 대해 재사용한다. 실패 시 키와 입력을 보존하며 성공 응답 후에만 입력을 지운다. 구현: `frontend/src/shared/api/contents.ts:19-30`, `frontend/src/features/archive/ArchiveStore.tsx:26-32`, `frontend/src/pages/archive/NewContentPage.tsx:56-69`.
- 상세의 승인/거절은 서버 candidate ID로 review endpoint를 부르고, `awaiting_confirmation`에서 별도 후보로 노출한다. 승인 뒤 job/content 캐시를 갱신해 queued 상태를 따라간다. 설계의 1→2→5초 적응형 polling 대신 2초 간격인 점은 공개된 제한이며 승인→완료 HTTP smoke 통과로 이번 생명주기 결함은 확인되지 않았다. 구현: `ContentDetailPage.tsx:38-47,116`, `queries.ts:13-26`.
- 수정 가능한 값은 요약·대표 태그·topics·hidden으로 제한하고 현재 상세 ETag를 `If-Match`로 전송한다. 충돌이면 최신 상세를 다시 가져오고 성공/실패 메시지를 분리한다. DELETE는 204 응답을 처리하고 성공 뒤 라우팅한다. 구현: `client.ts:16-29`, `contents.ts:10-17`, `ContentDetailPage.tsx:48-55,68-92`; 서버 계약: `src/jupjup/save/routes.py:74-103`.
- 검색 결과를 서버 순서대로 렌더링하며 로컬 점수 재정렬/결과 보충이 없다. 검색 필터도 서버가 지원하는 플랫폼·유형으로 한정한다. 구현: `SearchResultsPage.tsx:18-29`.
- 콘텐츠 Store는 서버 목록으로만 채우고 콘텐츠 seed/localStorage fallback은 사용하지 않는다. 남은 localStorage는 보기 설정뿐이다. 미지원 OAuth/컬렉션/favorite/기존 제목·메모 수정은 비활성화 또는 안내로 표시한다. 구현: `ArchiveStore.tsx:20-34`, `UnsupportedPage.tsx:3-5`, `ContentDetailPage.tsx:100-121`, `ArchiveCard.tsx:19`.
- Vite dev/preview는 `127.0.0.1`에만 바인드되고 기본 `/api` proxy 대상은 `127.0.0.1:8791`이다. 프론트에 외부 LLM 호출 경로는 없다. import manifest의 78개 해시가 `30d1f68` 파일과 모두 일치했고, 통합 변경에서 `src/`, `data/recordings/embeddings` 수정은 없었다.

## 독립 실행 검증

- `npm run check`: PASS, 7개 파일 / 21개 테스트. lint error 0, 경고 6개(Fast Refresh export 5, effect 내 상태 설정 1).
- `npm run build`: PASS.
- 지정 API 회귀 (`test_save_api.py`, `test_save_acceptance.py`, `test_save_time.py`, `test_api_search.py`, `test_api_ingest_worker_split.py`): PASS, 68개 통과.
- `python3 frontend/scripts/smoke_local_api.py`: PASS. 저장/replay/conflict, 실제 worker, 승인, ETag PATCH/conflict, 사용자 격리, 재분석/거절, 검색, 숨김/해제, 204 삭제 확인.
- 전용 기존 API는 `127.0.0.1:8791`에서 healthz 200 응답, dev/mock/hash embedder 확인. 보고서 기재의 기존 PID와 실행 경로를 확인했고 프로세스를 재기동하거나 종료하지 않았다.

## 피드백 및 감점

- `frontend/src/shared/config/env.ts:1`: `VITE_API_BASE_URL`을 임의 주소로 설정할 수 있고 클라이언트가 그대로 요청 대상으로 사용한다(`client.ts:20`). 기본값과 현재 Vite proxy는 루프백이지만, 운영자 실수로 외부 URL이 설정되면 저장 원문/사용자 콘텐츠가 그 주소로 전송될 수 있다. 현재 기본 실행의 결함은 아니므로 2점 감점에 그쳤다. 이 통합을 로컬 전용으로 유지하려면 dev 빌드에서 loopback 허용 목록을 검증하거나 비루프백 목적지를 거부하는 설정 검사를 추가하는 편이 안전하다.
- 적응형 polling, 새로고침 뒤 멱등키 복구, 전역 완료 알림 부재는 구현 인계 보고서에 공개되어 있다. 이번 검수에서 핵심 저장·승인·수정·검색 동작을 막거나 성공으로 오인시키는 재현 사례는 없었다.

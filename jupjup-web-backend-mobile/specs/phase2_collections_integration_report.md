# 컬렉션·보존 프론트 통합 보고

- 상태: 단일 Codex-Primary 통합·검증 완료, PM 병합 대기. 서브에이전트 없음.
- 보존 커밋: `23ca0a0e69e242f1f0a274820bce2907b46ea30a`. 기준 HEAD `e8012b3`에서 `git merge --no-ff --no-commit 23ca0a0e69e242f1f0a274820bce2907b46ea30a` 후 검증·보고를 포함하여 merge commit 생성. 최종 해시는 `git log -1 --format=fuller` 참조. 보존 커밋을 두 번째 부모로 유지하므로 PM 병합 뒤 보존 커밋에서 후손으로 fast-forward 가능한 이력이다.
- 병합 파일: `frontend/src/pages/archive/ContentDetailPage.tsx`, `frontend/src/app/integration.test.tsx`. 텍스트 충돌 없음. 상세 페이지는 보존 커밋의 자동승인 효과·실패 재시도·재분석/metadata의 auto 요청·자동정리 UI를 그대로 유지하고, 기존 컬렉션 선택기를 함께 유지했다. 제품 코드 추가 수정 없음.
- 호환성 보완은 통합 테스트에만 적용: review 요청의 candidate_id/approve 및 실제 202 queued 응답 검증, auto 재분석은 후보 재승인 없이 완료하고 사용자 수정 보존, metadata 요청은 정확히 auto 검증. 자동승인 500 실패 시 후보/원문/사용자 수정/다중 소속 유지, 명시적 재시도 성공 후 metadata와 Sidebar/상세 컬렉션 표시·사용자 편집을 함께 검증했다.

## 검사

- 지정 `/Users/minjun/orca/workspaces/dc2/phase-2-frontend-integration/frontend/node_modules`를 현재 워크트리 `frontend/node_modules` symlink로 재사용. 설치·다운로드 없음.
- 최초 병합 상태 `npm --prefix frontend run check`: 기존 컬렉션/색상/실패 입력 보존을 포함한 **9 files / 35 tests PASS**.
- 보완 후 `npm --prefix frontend run check`: **9 files / 36 tests PASS**, typecheck PASS. lint 비차단 경고 8건(Fast Refresh 6, 기존 효과 setState 1, 보존 커밋 효과 dependency 1). 새 테스트 첫 typecheck에서 metadata 리터럴 타입 추론 오류가 발생했으며 `MetadataClassification` 타입 지정 후 해소했다.
- `npm --prefix frontend run build`: PASS.
- `PYTHONPATH=src /Users/minjun/orca/workspaces/dc2/PM/.venv/bin/pytest -o 'addopts=' -q tests/integration/test_save_api.py::test_confirm_candidate_approve_reject_trace_and_reanalysis`: **1 passed**. 격리 테스트 DB에서 confirm 후보·승인 202/재승인 멱등·반대 결정 409·거절 200·재분석/사용자 수정 보존 확인. API 기능/테스트 소스 변경 없음.
- `git diff --check`: PASS. 상세 페이지를 보존 커밋과 대조하면 컬렉션 선택기 및 컬렉션 미지원 문구 제거만 차이로 남는다.

## 제약·인수

실행 워크트리 수정/checkout/stash/reset, backend/migration_v29/checksum/설계/AI품질/검색 변경, 실DB·실서버 접근/재시작, 외부 LLM·push 모두 수행하지 않았다. UI 검증은 jsdom/API 모의 응답이고 실브라우저·실배포 검증은 PM 담당이다. 기존 컬렉션 이름·색 편집/다중 소속/실패 보존 테스트를 모두 유지했다. 커밋 뒤 조상 관계 및 clean status를 확인하고 PM을 기다린다.

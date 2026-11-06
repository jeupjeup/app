# Phase 4 검수: 카카오 로그인 제거 + integration-banner 제거

- **대상:** `482212b` vs `8c3232e`
- **검수자:** Claude-Reviewer
- **점수:** 96 / 100 (정확성 39/40 · 안전성 30/30 · 유지보수성 27/30)
- **상태:** PASS

## 확인 결과

| 항목 | 결과 |
|---|---|
| 카카오 로그인 제거 | `AuthPage.tsx`의 provider 목록, `Provider` 타입, 비활성 분기(`start`, `disabled`, `title`), `SocialIcon` 카카오 SVG, `AuthPage.module.css`의 `.kakao` 스타일 모두 제거됨 |
| Google/Naver 동작 유지 | 라벨·className·아이콘·`startSocialLogin(provider, isSignup)` 호출 경로 그대로. 비활성 조건이 `loading !== null`로만 단순화됨 (의미 동일) |
| kakaotalk 콘텐츠 플랫폼 유지 | `adapters.ts:4`, `presentation.tsx:3`, `ContentsPage.tsx:13`, `SearchResultsPage.tsx:25`의 `kakaotalk` 그대로 있음. 남은 `카카오` 문자열은 이것과 테스트 검증 정규식뿐 |
| 배너 DOM 제거 | `ArchiveLayout.tsx:99`에서 `.integration-banner` div 제거, 이제 쓰이지 않는 `env` import도 같이 제거됨 |
| 배너 CSS 제거 | `global.css`의 기본 규칙과 640px 미디어쿼리 안 규칙 모두 제거. 같은 미디어쿼리의 `.detail-primary-actions` 규칙은 유지됨. 저장소 전체에 `integration-banner` 참조 0건 |
| RequestState/Outlet | `ArchiveUiContext.Provider` 안의 `<RequestState …/>` + `<Outlet />` 순서·props 그대로 |
| 범위 | 변경은 `frontend/`와 `specs/`뿐. 백엔드 OAuth 코드는 건드리지 않음 |
| 문서 | `PRODUCT.md`, `specs/social_oauth_report.md`가 새 상태에 맞게 수정됨 |

## 실행

- `vitest run src/pages/auth/AuthPage.test.tsx`: **7/7 통과** (형제 워크트리의 `node_modules`를 잠시 symlink해 실행하고 바로 삭제함. 소스는 수정하지 않음)
- `tsc --noEmit -p .`: 출력 없음 (에러 없음)
- 전체 테스트 스위트는 요청대로 실행하지 않음

## 피드백 (감점 사유, 차단 아님)

- `frontend/src/pages/auth/AuthPage.test.tsx:11` — `getAllByRole('button')`이 2개라고 단정한다. 나중에 인증 페이지에 버튼(예: 뒤로 가기)이 추가되면 이 테스트가 이유 없이 깨진다. provider 목록 영역 안으로 범위를 좁히면 더 튼튼하다. (-2 유지보수성)
- 배너 제거를 직접 확인하는 테스트(ArchiveLayout에 `role="note"`가 없음)는 없다. 변경이 작아서 위험은 낮다. (-1 유지보수성, -1 정확성)
- 참고: 백엔드에는 원래 카카오 provider가 없다. `tests/integration/test_social_oauth.py:264`가 `/api/auth/oauth/kakao/start` → 404를 이미 검증하므로 서버 쪽 정리는 필요 없다.

## 루프백 대상

없음 (PASS).

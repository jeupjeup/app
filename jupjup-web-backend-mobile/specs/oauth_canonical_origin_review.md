# Phase 4 검수: OAuth canonical origin fix (Loop 1)

- 대상: `2983042` (fix(auth): start OAuth on canonical public origin), 기준 `1f828db`
- 범위: canonical OAuth origin의 정확성·보안, 배포 override 검증, 일반 API URL 회귀 여부만 본 빠른 검수 (전체 스위트는 돌리지 않음)
- 실행: `npx vitest run src/shared/config/env.test.ts src/shared/auth/session.test.ts src/shared/api` → **3 files / 34 tests passed** (`npm ci`로 잠긴 의존성 설치 후 실행, 소스 변경 없음)

## 점수
- **점수:** 93 / 100 (정확성 38/40 · 안전성 28/30 · 유지보수성 27/30)
- **상태:** PASS

## 확인한 것
1. **근본 원인 해결:** `session.ts:59`가 이제 `${env.oauthPublicOrigin}/api/api/auth/oauth/{provider}/start`로 이동한다. 기본값 `http://127.0.0.1:5177`은 백엔드 `OAuthConfig.from_env` 기본값(`src/jupjup/app_api/oauth.py:47`)과 `redirect_uri` 경로(`oauth.py:77`의 `/api/api/auth/oauth/{provider}/callback`)와 일치한다. 그래서 host-only `oauth_browser` 쿠키가 콜백과 같은 호스트에 설정된다. Vite dev 서버도 `127.0.0.1:5177`에 바인딩되어 있어(`frontend/vite.config.ts`) 이 기본값으로 실제로 접속할 수 있다.
2. **override 검증:** `env.ts:3-13`은 백엔드 정책과 같다. http(s)만 허용, 자격 증명·경로·쿼리·프래그먼트·백슬래시·공백 거부, `http`는 `127.0.0.1`/`localhost`만 허용. 결과값은 `url.origin`으로 정규화한다. 빈 문자열 `''`도 `new URL` 단계에서 거부된다. 테스트(`env.test.ts`)가 15가지 거부 사례를 다룬다. 사용자가 조작할 수 없는 빌드 타임 값이라 open redirect 위험은 없다.
3. **일반 API 회귀 없음:** `client.ts:29`, logout(`session.ts:39`), exchange(`session.ts:68`)는 그대로 상대 경로 `env.apiBaseUrl`(기본 `/api`)을 쓴다. 콜백 페이지가 canonical origin에서 열리므로 exchange 요청과 `oauth_browser` 쿠키가 같은 출처에 있다. 테스트가 override와 `VITE_API_BASE_URL`이 서로 독립인지 검증한다.

## 피드백 (감점 사유, 차단 아님)
- `frontend/src/shared/config/env.ts:4`: 프론트엔드는 앞뒤 공백을 `trim()`하지만, 백엔드(`oauth.py:47`)는 trim하지 않고 공백이 있으면 거부한다. 같은 값을 양쪽에 넣으면 비대칭으로 동작할 수 있다. trim을 빼서 엄격하게 맞추거나, 문서에 명시하는 것을 권장한다. (-1 안전성)
- `frontend/src/shared/config/env.ts:18`: 프론트/백엔드 origin이 서로 다르게 설정되는 것을 런타임에서 감지할 수단이 없다(문서 `.env.example`에만 의존한다). 불일치하면 `OAUTH_STATE_INVALID`가 다시 생긴다. 배포 체크리스트나 백엔드 start 응답에서 진단 로그를 남기는 방안을 고려할 것. (-1 정확성, -1 유지보수성)
- `frontend/src/shared/auth/session.ts:59`: `/api/api` 접두사가 `apiBaseUrl`과 별개로 하드코딩되어 있다. 백엔드 `redirect_uri`와 맞추려는 의도는 맞지만, 상수로 빼고 백엔드와 짝임을 주석으로 남기면 나중에 프록시 경로를 바꿀 때 실수를 줄일 수 있다. (-1 유지보수성)
- `env.ts:18`: 잘못된 설정이면 모듈을 import할 때 throw해서 앱 전체가 뜨지 않는다. 의도된 fail-fast로 문서에도 있지만, 로그인만 막는 방식과 비교한 트레이드오프는 기록해 둘 만하다. (-1 정확성/-1 안전성, 경미)
- `localhost`에서 시작한 사용자는 로그인 후 `127.0.0.1` 출처로 넘어가므로 localStorage 세션도 `127.0.0.1`에 저장된다. 의도된 동작이지만, 개발자가 `localhost` 탭으로 돌아가면 로그아웃된 것처럼 보일 수 있다. (-1 유지보수성: 문서화 권장)

## 루프백 대상
- 없음 (PASS). 위 항목들은 후속 Phase 3 정리 작업에서 선택적으로 처리하면 된다.

# 줍줍 웹

React + TypeScript + Vite 웹입니다. 루트 [README](../../README.md)의 설치·실행 안내를 사용하세요.

```sh
npm ci
npm run dev
```

웹은 `http://127.0.0.1:5177`에서 실행합니다. 개발 프록시는 `/api`, `/v1`, `/healthz`를 `http://127.0.0.1:8000`에 경로 변경 없이 전달합니다. `JUPJUP_API_ORIGIN`으로 대상을 바꿀 수 있습니다. API와 내장 분석 워커는 저장소 루트에서 `bun run dev:api`로 실행합니다.

앱과 같은 이메일로 회원가입/로그인하면 같은 SQLite 보관함을 사용합니다. 앱 URL 저장과 AI 결과가 웹에 반영되고, 웹 URL 저장도 앱 갱신 시 보입니다. 토큰 없는 개발 사용자 헤더는 사용하지 않습니다. 401이면 세션을 지우고 로그인 화면으로 돌아갑니다.

`VITE_API_BASE_URL`은 경로 접두사가 없는 API origin입니다. 기본값은 빈 문자열(동일 origin)입니다. 웹 OAuth callback은 `{OAUTH_PUBLIC_ORIGIN}/api/auth/oauth/{provider}/callback`이며 프록시와 서버에서 `/api`를 중복하지 않습니다.

```sh
npm run lint
npm run typecheck
npm run build
```

`live/local` 분석은 별도 GGUF 모델이 필요하며 루트 안내를 따릅니다. 실제 제공자 로그인·운영 HTTPS는 별도 외부 설정이 필요합니다. 즐겨찾기와 보기 설정은 브라우저 로컬입니다.

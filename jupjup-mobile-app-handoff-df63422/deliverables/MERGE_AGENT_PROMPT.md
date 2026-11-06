# 앱 프론트 통합·병합 에이전트 프롬프트

아래 내용을 앱 프론트 저장소에서 작업하는 코딩 에이전트에게 그대로 전달하세요.

---

당신은 JupJup 모바일 앱 프론트와 확정된 백엔드 계약을 통합하는 담당 에이전트다. 첨부된 `jupjup-mobile-app-handoff.zip`을 먼저 풀고, 다음 파일을 반드시 읽은 뒤 작업을 시작하라.

1. `deliverables/MOBILE_APP_HANDOFF.md`
2. `specs/app_api_openapi.json`
3. `specs/mobile_backend_contract_matrix.json`
4. `specs/mobile_app_bridge_report.md`
5. 앱 프론트 저장소의 `README`, `AGENTS.md`, `CLAUDE.md` 및 패키지 설정

목표는 현재 앱의 화면·상태관리 구조를 최대한 보존하면서 데모/mock/local-only 저장 계층을 실제 `/api` 백엔드로 교체하고, 로그인부터 콘텐츠 저장·분석 결과 조회까지 end-to-end로 작동하게 만드는 것이다.

필수 구현:

- OpenAPI에서 API 타입과 클라이언트를 생성하거나, 저장소 관례에 맞는 단일 typed API client를 구현한다.
- 환경별 base URL을 설정한다.
  - iOS Simulator: `http://127.0.0.1:8000/api`
  - Android Emulator: `http://10.0.2.2:8000/api`
  - 실기기: `http://<MAC_LAN_IP>:8000/api`
  - 운영: `https://<DOMAIN>/api`
- `/auth/register`, `/auth/login`, `/auth/logout`, `/me`를 실제 API에 연결한다.
- 토큰을 앱 플랫폼의 보안 저장소에 저장하고 앱 시작 시 세션을 복원한다. 로그나 오류 보고에 토큰을 출력하지 않는다.
- 모든 인증 요청에 `Authorization: Bearer <token>`을 적용한다.
- 모든 POST/PATCH에 JSON content type을 사용하고 bodyless POST에도 `{}`를 보낸다.
- 401이면 세션과 사용자 캐시를 지우고 로그인 화면으로 이동한다.
- 오류 처리는 문자열 message가 아니라 `error.code`를 기준으로 한다.
- 콘텐츠 목록/상세/생성/수정/삭제/복원/휴지통 비우기를 `/contents` 계약에 맞게 연결한다.
- URL 저장 후 앱 콘텐츠가 분석 중인 상태를 표시하고, polling 또는 저장소의 기존 refresh 정책으로 최신 결과를 반영한다. 쓰기 후와 foreground 복귀 시 `/state`를 갱신한다.
- `409 DUPLICATE_CONTENT`를 정상적인 중복 안내 UX로 처리한다.
- 알림과 검색 기록 API를 실제 서버에 연결한다.
- mock/demo 저장소는 테스트 fixture로만 남기거나 제거한다. 운영 코드가 성공한 것처럼 가짜 데이터를 반환하면 안 된다.
- 네트워크 로딩, 빈 상태, 재시도 가능한 오류, 세션 만료 상태를 화면에 반영한다.
- 앱에서 `/v1`과 `/api`를 혼용하지 않는다. 첨부 OpenAPI의 `/api` 계약만 사용한다.
- OpenAPI 파일이나 백엔드 응답 필드를 앱 편의를 위해 임의로 수정하지 않는다.

플랫폼 설정:

- iOS debug에서 실기기 HTTP가 필요하면 Local Network 권한과 개발 범위 ATS 예외를 최소 범위로 설정한다.
- Android debug에서 HTTP가 필요하면 debug 전용 cleartext 설정을 최소 범위로 설정한다.
- release는 HTTPS만 사용하도록 구성한다.
- 네이티브 요청에는 CORS 우회 코드를 넣지 않는다. WebView인 경우에만 정확한 origin을 백엔드 설정 대상으로 문서화한다.

검증 순서:

1. 기존 앱 단위 테스트와 typecheck/lint를 실행한다.
2. API client의 성공, 401, 409, 네트워크 오류 테스트를 추가한다.
3. 로그인 → 세션 복원 → URL 저장 → 목록 → 상세 → 분석 상태 갱신 흐름을 테스트한다.
4. 삭제 → 휴지통 → 복원 → 휴지통 비우기를 테스트한다.
5. 실제 백엔드를 띄우고 최소 한 플랫폼에서 연결한다.
6. 가능하면 ZIP의 `scripts/app_contract_smoke.py`도 실행해 서버 자체 계약을 먼저 확인한다.

병합 규칙:

- 작업 전 현재 브랜치와 dirty 파일을 확인하고 사용자 변경을 덮어쓰지 않는다.
- 앱의 기존 디자인 시스템, 라우팅, 상태관리 방식을 유지한다.
- 변경을 API client/auth, content integration, UI states처럼 검토 가능한 커밋으로 나눈다.
- 테스트가 통과하면 대상 통합 브랜치에 병합한다. 충돌은 의미를 확인해 해결하고 양쪽 기능을 보존한다.
- force push, reset --hard, 기존 사용자 파일 삭제를 하지 않는다.
- 비밀값, 토큰, `.env`, 로컬 IP를 커밋하지 않는다.

최종 보고에는 다음을 포함하라.

- 최종 커밋과 병합 대상 브랜치
- 변경 파일 및 주요 사용자 흐름
- 실행한 테스트와 정확한 결과
- 실제 기기/에뮬레이터 연결 여부
- 남은 외부 의존성(운영 도메인, HTTPS 등)
- 미완료 항목이 있다면 숨기지 말고 재현 방법과 다음 작업을 명시

질문이 없어도 저장소 관례와 첨부 명세를 기준으로 합리적인 기본값을 선택해 끝까지 구현하라. 단, 운영 도메인·서명 인증서처럼 실제 외부 값이 필요한 단계는 코드와 설정 슬롯까지 완성하고 필요한 값만 명확히 보고하라.

---

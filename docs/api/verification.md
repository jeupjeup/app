# 검증 범위

로그인 전용 예시 서버는 `server/auth-server.mjs`와 `server/auth-store.mjs`에 있다. 앱은 `.env`의 `EXPO_PUBLIC_API_URL`로 이 서버에 연결한다.

로컬 LAN HTTP로 health, 이메일 예시 계정 로그인, 인증된 빈 `/state`, 로그아웃, 폐기된 세션의 401과 잘못된 비밀번호의 401 응답을 확인했다. 사용자·세션 저장소는 SQLite이며 `.data/`는 Git에서 제외한다. 자동 테스트는 프로젝트 지침에 따라 추가하거나 실행하지 않는다.

이메일·네이버·카카오·Google 로그인과 앱 복귀·세션 교환은 사용자가 앱에서 동작을 확인했다. 다른 환경에서 재현하려면 해당 환경의 제공자 키와 등록된 callback 설정이 필요하다. 네이버 access-token 방식의 client ID/audience 검증 한계는 README에 명시했다.

회원가입·콘텐츠·검색·프로필 변경 등 로그인 외 기능은 이 서버에 구현하지 않았으며 501을 반환한다. `/state`는 로그인 후 화면 진입을 위한 빈 상태만 반환한다. 전체 OpenAPI의 나머지 계약은 외부 BE 구현용이며 외부 서버의 구현·영속성·응답은 미검증이다. 정적 검사는 `bun run lint`, `bun run typecheck`로 실행한다.

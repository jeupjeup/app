# API 연동 현황

2026-11-04 기준. 명세: [openapi.json](./openapi.json). 예시 JSON은 계약 설명용이며 검증 데이터/운영 응답이 아니다.

## 서버와 Base URL

이 저장소에는 프론트엔드·전체 API 계약과 로그인 전용 예시 서버가 포함되어 있다. `bun run dev:api`로 실행하며 `.env`의 `EXPO_PUBLIC_API_URL`에 연결한다. 외부 백엔드 구현과 실제 응답은 아직 검증하지 않았다. 아래 매핑은 현재 FE 클라이언트가 요구하는 계약이다. 인증 토큰 형식·엔드포인트·응답 구조가 실제 백엔드와 다르면 명세와 클라이언트를 함께 조정해야 한다.

프로젝트 루트 `.env`에 외부 백엔드 주소를 지정한다.

```dotenv
EXPO_PUBLIC_API_URL=https://your-api-host/api
```

`your-api-host`는 실제 서버 주소로 바꾼다. `/api`는 서버의 공통 prefix인 경우에만 포함한다. 클라이언트는 뒤에 `/auth/login`, `/state`, `/contents` 등을 붙인다. 환경변수 변경 후 개발 메뉴에서 앱을 완전히 Reload한다.

```sh
cp .env.example .env
bun start
```

주소를 읽는 곳은 `src/modules/api.ts`의 `process.env.EXPO_PUBLIC_API_URL`이다. 고객센터 주소는 선택적 `EXPO_PUBLIC_SUPPORT_URL`이며, 개발용 예시 화면은 `__DEV__` 빌드의 개발 메뉴에서 선택하면 활성화된다. 토큰은 SecureStore에 저장하므로 해당 모듈이 없는 기존 개발 클라이언트는 다시 빌드해야 한다.

## FE 계약 요구사항

- Bearer 토큰: 현재 FE는 64자리 hex opaque 토큰, Session의 token/expiresAt/user 구조를 요구한다. 실제 BE가 JWT 등 다른 형식이면 FE 검증도 수정해야 한다.
- 날짜: ISO 8601. collection/deletedAt/viewedAt은 없을 때 응답에서 생략하며, 분류 해제 요청만 collection:null을 사용한다.
- `/state`는 user/contents/notices/searchHistory/savedCount를 반환해야 한다. FE는 이 상태에서 검색·필터·정렬·최근 조회를 파생한다. 페이지네이션은 별도 계약이 필요하다.
- 오류 구조: `{ "error": { "code": "ERROR_CODE", "message": "사용자에게 표시할 메시지" } }`. 204는 본문 없음.
- 사용자 소유 데이터 접근 제어, 영속성, 비밀번호 검증·잠금, CORS는 외부 BE의 구현 책임이다. 구현 완료로 간주하지 않는다.
- 파일 업로드/다운로드 요구 화면은 없다. OS 공유와 원본 URL 열기는 기기 API를 사용한다.

## 페이지·액션 매핑

기본 prefix `/api`. 모든 비공개 기능은 인증 사용자 소유 데이터만 처리한다.

| 화면 | 데이터와 호출 시점 | 사용자 액션 / 요청 | 응답 활용·연동 상태 |
| --- | --- | --- | --- |
| 온보딩 `/onboarding` | 로컬 완료 여부 | AsyncStorage 설정만 저장 | API 불필요. AI 자동 분류 안내를 실제 수동 분류 동작에 맞춤 |
| 로그인 `/login` | 이메일·비밀번호 입력 | POST `/auth/login` | Session 토큰 안전 저장 → GET `/state` → 홈. 잘못된 로그인은 화면 유지 |
| 소셜 로그인 `/login` | 네이버(NID)·카카오 네이티브 SDK 인증 | POST `/auth/oauth/{provider}/exchange` `{access_token,keep_me_logged_in:true}` | 제공자 토큰 서버 검증 → 기존 Session 안전 저장 → GET `/state` → 홈. 취소·오류는 화면 유지. 외부 BE 연동 미검증 |
| 구글 로그인 `/login` | 서버 중계 브라우저 인증 + PKCE(S256) | GET `/auth/oauth/google/authorize` → 앱 callback → POST `/auth/oauth/google/exchange` | callback URI·state 검증 → 일회용 앱 코드 교환 → 기존 Session 저장 → GET `/state` → 홈. 취소·동의 거절은 화면 유지. 외부 BE 미검증 |
| 가입 `/login/signup` | 기존 로그인 화면에서 인증 후 닉네임·필수/선택 동의 | PATCH `/me` `{nickname,requiredConsent,notificationsEnabled}` | Figma에 없는 이메일·비밀번호 가입 입력란 제거. 인증 성공 후 진입하며 프로필 저장 성공 시 홈 이동. 동의 필드 처리는 외부 BE 확인 필요 |
| 홈 `/home` | `/state.contents/notices` | URL+메모 POST `/contents` | 서버 201 수신 후 상세 버튼. 실패는 입력 유지. 오프라인 임시 저장/동기화 성공 안내 제거 |
| 검색 팝업 | `/state.contents/searchHistory`에서 부분일치 미리보기 | POST `/search-history` `{query}`, DELETE `/search-history` | 기록 저장 성공 후 `/library?q=` 이동. 최대 10개 중복 제거 |
| 보관함 `/library` | `/state.contents` 중 활성 | q/collection/type/sort 로컬 필터. 당겨서 GET `/state` | 수신한 응답으로 최신/오래된 순 정렬. Empty와 결과 없음 구분 |
| 상세 `/library/[id]` | `/state.contents`에서 id 조회 | 진입 POST `/contents/{id}/view` | 조회 기록 영속화. Figma에 없는 정보 수정 버튼·팝업 제거 |
| 상세 삭제 | 현재 소유 콘텐츠 | DELETE `/contents/{id}` | 성공 후 삭제 안내, 30일 휴지통 보관 |
| 알림 `/home/notifications` | `/state.notices` | POST `/notices/read` 또는 `/notices/{id}/read` `{}` | 읽음 성공 후 상태 갱신. 알림은 실제 북마크 저장 트랜잭션에서 생성 |
| 마이 `/mypage` | `/state.user/savedCount/contents` | 계정/가이드/최근/휴지통 이동 | 실제 개수·컬렉션을 계산. 고객센터는 설정 URL 열기. Figma에 없는 준비 중·연결 실패 알림창 제거 |
| 계정 `/mypage/account` | `/state.user` | PATCH `/me` `{nickname}`; POST `/auth/logout` `{}`; DELETE `/me` | 저장·로그아웃·탈퇴 성공 후에만 닫기/화면 이동. 이메일 로그인 표기 |
| 비밀번호 `/mypage/password` | 입력 상태만 로컬 | POST `/me/password/verify` `{currentPassword}`, PATCH `/me/password` `{currentPassword,newPassword}` | 서버 검증과 잠금 사용. 변경 시 다시 검증. 메모리 예시 비밀번호 제거 |
| 최근 조회 `/mypage/recent` | `/state.contents`의 viewedAt | 상세 진입 시 조회 기록 | 활성 콘텐츠를 viewedAt 내림차순으로 표시 |
| 휴지통 `/mypage/trash` | `/state.contents`의 deletedAt | POST `/contents/{id}/restore` `{}`, DELETE `/trash` | 성공 후 목록 갱신. 같은 URL 활성 항목이 있으면 복구 409 |
| 개발 메뉴 | 개발 빌드의 Custom items에서 fixtures 선택 | 로컬 previewData만 사용 | 개발 Mock 유지. 실제 세션 요청과 분리; 이 모드의 쓰기는 서버 전송하지 않음 |

`GET /me`, `/contents`, `/contents/{id}`, `/notices`, `/search-history`는 계약에 정의되어 있으나 FE에서는 중복 요청을 피하고 `/state`를 재사용한다.

## 화면 상태와 동기화

| 상태 | 처리 |
| --- | --- |
| Loading | 시작 시 토큰/서버 상태 확인 동안 스플래시. 전역 진행 배너 없음. 쓰기 중 버튼 비활성화. ScrollView/보관함 당겨서 새로고침 |
| Success | 서버 응답이 성공한 뒤에만 대화상자 완료/화면 이동. 변경 후 `/state` 재조회. 생성 응답은 서버 ID 사용 |
| Empty | 예시 데이터를 주입하지 않음. 홈/보관함/알림/최근/휴지통 기존 빈 상태 UI |
| Error | Figma에 없는 공통 오류 배너와 팝업 내 API 오류 문구 제거. 실패 시 입력/기존 데이터 보존. 추가 쓰기 자동 재시도 없음 |
| 401 | 로그인 실패는 입력 유지. 인증된 요청의 만료·폐기 토큰은 SecureStore/사용자 데이터를 지우고 보호된 탭에서 로그인으로 이동 |
| 403 | 추가 UI 없이 현재 화면 유지. 다른 사용자 리소스는 존재 여부를 숨기기 위해 404 |
| Offline/timeout | 12초 제한 및 AbortController. 서버 저장을 확인할 수 없으면 입력 유지; 자동 오프라인 쓰기 큐 없음 |
| Refresh | 로그인·앱 재실행·포그라운드 복귀·사용자 새로고침·변경 후 재조회. 늦게 도착한 예전 조회는 버전/토큰으로 무시 |

자동 쓰기 재시도는 없다. 서버 반영 후 새로고침만 실패했다면 변경을 재전송하지 않고 기존 화면을 유지한다. 네트워크 단절로 쓰기 응답을 받지 못하면 저장 여부가 불확실할 수 있어 목록 새로고침으로 확인한다(정규화 URL 중복 제약으로 같은 URL 이중 활성 저장 방지).

## 외부 백엔드 확인 필요

로그인 전용 예시 서버는 `/health`, `/auth/login`, `/auth/logout`, 네이버·카카오·구글 OAuth, `/me` 조회와 빈 초기 상태의 `/state`만 구현한다. 그 밖의 엔드포인트는 501을 반환하며 외부 BE에서 구현해야 한다. 소셜 OAuth의 서버 토큰 검증·세션 교환, AI 분석·자동 분류·의미 검색·추천·썸네일 수집, 오프라인 동기화, 푸시, 이메일 발송은 별도 구현 및 설정이 필요하다. 서버 BASE URL만 지정한다고 계약이 다른 BE와 자동 호환되지는 않는다.

## 네이버·카카오 세션 교환

`provider`는 `naver` 또는 `kakao`이다. 요청은 참고 프로젝트와 같은 `{ "access_token": "제공자 토큰", "keep_me_logged_in": true }`이며, 응답은 줍줍의 기존 `{ token, expiresAt, user }` Session 계약을 따른다. 참고 프로젝트의 `{ success, data: { access_token, expires_in } }` 응답과 다르므로 서버가 줍줍 계약을 제공해야 한다. 제공자 토큰은 서버에서 유효성·앱 소유권을 확인해야 하며 그대로 앱 세션으로 사용하지 않는다. 제공자 사용자 ID로 계정을 식별하고, 이메일이 같다는 이유로 기존 계정을 자동 연결하지 않는다. 신규 사용자의 프로필·동의가 필요한 경우 서버는 계정 생성 정책에 따라 처리하거나 오류를 반환해야 한다.

앱 키·콜백·빌드 설정은 루트 README의 지원 범위를 참고한다. 로그인 전용 예시 서버의 이메일 세션 발급·조회·로그아웃은 LAN HTTP로 확인했다. 네이버·카카오·Google 계정 로그인은 사용자가 앱에서 동작을 확인했다. 네이버는 프로필 API로 토큰을 확인하며 현재 access-token 계약에는 client ID/audience 검증 정보가 없다. 카카오는 KAKAO_APP_ID와 토큰 정보 API의 앱 ID를 비교한다.

## 구글 브라우저 인증

참고 프로젝트와 동일한 서버 중계 방식이다. 앱이 매 요청마다 생성한 `state`, PKCE `code_challenge`(S256), `redirect_uri=jeupjeupsave://login`, `keep_me_logged_in=true`를 `GET /auth/oauth/google/authorize`의 query로 전달한다. 백엔드는 Google OAuth Client ID/Secret과 Google HTTPS callback을 설정하고, 앱 callback 주소를 허용 목록으로 검증해야 한다. Google client secret은 앱에 포함하지 않는다.

인증 성공 시 서버는 짧은 유효기간의 일회용 **앱 인증 코드**를 `jeupjeupsave://login?code=...&state=...`로 전달한다. Google 제공자 토큰이나 앱 세션을 callback URL에 넣지 않는다. 취소 시 `error=access_denied&state=...`를 보낸다. 앱은 callback 주소·state의 일치와 중복 query를 검증한 뒤 `{code,state,code_verifier,redirect_uri}`를 `POST /auth/oauth/google/exchange`로 전달한다. 서버는 앱 코드를 원래 요청의 state·PKCE·callback에 묶어 검증하고 한 번만 소비한 뒤 줍줍 Session을 반환해야 한다. 잘못되거나 만료된 코드는 401로 거절한다.

`expo-crypto` 추가로 개발 클라이언트를 다시 빌드해야 한다. 예시 서버에 Google 인증·callback·코드 교환이 구현되어 있다. GOOGLE_CLIENT_ID·GOOGLE_CLIENT_SECRET·AUTH_PUBLIC_BASE_URL과 Google 콘솔의 HTTPS callback 등록이 필요하다. Google 계정 로그인과 서버 세션 교환은 사용자가 앱에서 동작을 확인했다.

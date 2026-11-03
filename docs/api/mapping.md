# API 연동 현황

2026-11-03 기준. 명세: [openapi.json](./openapi.json). 예시 JSON은 계약 설명용이며 검증 데이터/운영 응답이 아니다.

## 서버와 Base URL

이 저장소에는 프론트엔드와 API 계약만 포함한다. 별도 로컬 서버는 필요하지 않으며, 외부 백엔드 구현과 실제 응답은 아직 검증하지 않았다. 아래 매핑은 현재 FE 클라이언트가 요구하는 계약이다. 인증 토큰 형식·엔드포인트·응답 구조가 실제 백엔드와 다르면 명세와 클라이언트를 함께 조정해야 한다.

프로젝트 루트 `.env`에 외부 백엔드 주소를 지정한다.

```dotenv
EXPO_PUBLIC_API_URL=https://your-api-host/api
```

`your-api-host`는 실제 서버 주소로 바꾼다. `/api`는 서버의 공통 prefix인 경우에만 포함한다. 클라이언트는 뒤에 `/auth/login`, `/state`, `/contents` 등을 붙인다. 환경변수 변경 후 Metro를 재시작하고 앱을 다시 로드한다.

```sh
cp .env.example .env
bun start
```

주소를 읽는 곳은 `src/modules/api.ts`의 `process.env.EXPO_PUBLIC_API_URL`이다. 고객센터 주소는 선택적 `EXPO_PUBLIC_SUPPORT_URL`이며, 개발용 예시 화면은 `__DEV__`와 `EXPO_PUBLIC_ENABLE_PREVIEW=1`일 때만 활성화된다. 토큰은 SecureStore에 저장하므로 해당 모듈이 없는 기존 개발 클라이언트는 다시 빌드해야 한다.

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
| 가입 `/login/signup` | 이메일·비밀번호·닉네임·필수/선택 동의 | POST `/auth/register` | 실제 계정 생성·동의 저장·Session 수신. 서버 검증 오류 표시 |
| 홈 `/home` | `/state.contents/notices` | URL+메모 POST `/contents` | 서버 201 수신 후 상세 버튼. 실패는 입력 유지. 오프라인 임시 저장/동기화 성공 안내 제거 |
| 검색 팝업 | `/state.contents/searchHistory`에서 부분일치 미리보기 | POST `/search-history` `{query}`, DELETE `/search-history` | 기록 저장 성공 후 `/library?q=` 이동. 최대 10개 중복 제거 |
| 보관함 `/library` | `/state.contents` 중 활성 | q/collection/type/sort 로컬 필터. 당겨서 GET `/state` | 수신한 응답으로 최신/오래된 순 정렬. Empty와 결과 없음 구분 |
| 상세 `/library/[id]` | `/state.contents`에서 id 조회 | 진입 POST `/contents/{id}/view`; PATCH `/contents/{id}` `{title,memo,type,collection}` | 조회 기록 영속화, 수정 응답 뒤 상태 재조회. ID 없으면 안내 |
| 상세 삭제 | 현재 소유 콘텐츠 | DELETE `/contents/{id}` | 성공 후 삭제 안내, 30일 휴지통 보관 |
| 알림 `/home/notifications` | `/state.notices` | POST `/notices/read` 또는 `/notices/{id}/read` `{}` | 읽음 성공 후 상태 갱신. 알림은 실제 북마크 저장 트랜잭션에서 생성 |
| 마이 `/mypage` | `/state.user/savedCount/contents` | 계정/가이드/최근/휴지통 이동 | 실제 개수·컬렉션을 계산. 고객센터는 설정 URL 또는 준비 중 안내 |
| 계정 `/mypage/account` | `/state.user` | PATCH `/me` `{nickname}`; POST `/auth/logout` `{}`; DELETE `/me` | 저장·로그아웃·탈퇴 성공 후에만 닫기/화면 이동. 이메일 로그인 표기 |
| 비밀번호 `/mypage/password` | 입력 상태만 로컬 | POST `/me/password/verify` `{currentPassword}`, PATCH `/me/password` `{currentPassword,newPassword}` | 서버 검증과 잠금 사용. 변경 시 다시 검증. 메모리 예시 비밀번호 제거 |
| 최근 조회 `/mypage/recent` | `/state.contents`의 viewedAt | 상세 진입 시 조회 기록 | 활성 콘텐츠를 viewedAt 내림차순으로 표시 |
| 휴지통 `/mypage/trash` | `/state.contents`의 deletedAt | POST `/contents/{id}/restore` `{}`, DELETE `/trash` | 성공 후 목록 갱신. 같은 URL 활성 항목이 있으면 복구 409 |
| 개발 메뉴 | 명시적 preview 환경에서 fixtures | 로컬 update만 사용 | 개발 Mock 유지. 실제 세션 요청과 분리; 이 모드의 쓰기는 서버 전송하지 않음 |

`GET /me`, `/contents`, `/contents/{id}`, `/notices`, `/search-history`는 계약에 정의되어 있으나 FE에서는 중복 요청을 피하고 `/state`를 재사용한다.

## 화면 상태와 동기화

| 상태 | 처리 |
| --- | --- |
| Loading | 시작 시 토큰/서버 상태 확인 동안 스플래시, 이후 공통 진행 표시. 쓰기 중 버튼 비활성화. ScrollView/보관함 당겨서 새로고침 |
| Success | 서버 응답이 성공한 뒤에만 대화상자 완료/화면 이동. 변경 후 `/state` 재조회. 생성 응답은 서버 ID 사용 |
| Empty | 예시 데이터를 주입하지 않음. 홈/보관함/알림/최근/휴지통 기존 빈 상태 UI |
| Error | 공통 오류 표시와 새로고침. 입력 대화상자에도 오류 표시. 실패 시 입력/기존 데이터 보존. 추가 쓰기 자동 재시도 없음 |
| 401 | 로그인 실패는 입력 유지. 인증된 요청의 만료·폐기 토큰은 SecureStore/사용자 데이터를 지우고 보호된 탭에서 로그인으로 이동 |
| 403 | 권한/Origin 오류 메시지. 다른 사용자 리소스는 존재 여부를 숨기기 위해 404 |
| Offline/timeout | 12초 제한 및 AbortController. 서버 저장을 확인할 수 없으면 실패 안내; 자동 오프라인 쓰기 큐 없음 |
| Refresh | 로그인·앱 재실행·포그라운드 복귀·사용자 새로고침·변경 후 재조회. 늦게 도착한 예전 조회는 버전/토큰으로 무시 |

자동 쓰기 재시도는 없다. 서버 반영 후 새로고침만 실패했다면 변경을 재전송하지 않고 재조회 안내를 유지한다. 네트워크 단절로 쓰기 응답을 받지 못하면 저장 여부가 불확실할 수 있어 목록 새로고침으로 확인한다(정규화 URL 중복 제약으로 같은 URL 이중 활성 저장 방지).

## 외부 백엔드 확인 필요

모든 엔드포인트의 실제 구현 여부와 응답 계약을 외부 BE에서 확인해야 한다. 소셜 OAuth, AI 분석·자동 분류·의미 검색·추천·썸네일 수집, 오프라인 동기화, 푸시, 이메일 발송은 별도 구현 및 설정이 필요하다. 서버 BASE URL만 지정한다고 계약이 다른 BE와 자동 호환되지는 않는다.

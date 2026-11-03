# 줍줍 저장소

Expo SDK 58 · React Native 0.88 · TypeScript · Expo Router

iOS·Android 앱입니다. 화면의 데이터 요구사항과 외부 백엔드 API 계약을 `/docs/api/`에 정리했습니다. 프론트엔드 API 클라이언트가 포함되어 있습니다.

## 실행 및 API 주소

로그인 전용 예시 API 서버가 `server/`에 포함되어 있습니다. Node.js 22.13 이상과 Bun을 사용합니다.

```sh
bun install
cp .env.example .env  # 이미 .env가 있다면 덮어쓰지 않고 주소만 수정
bun run dev:api
```

다른 터미널에서 `bun start`로 앱을 실행합니다. 현재 로컬 `.env`의 `EXPO_PUBLIC_API_URL`은 Mac의 LAN 주소 `http://192.168.0.105:3001/api`로 연결되어 있습니다. 같은 Wi-Fi에 연결된 기기에서 사용할 수 있습니다. IP가 바뀌면 `.env` 주소도 수정합니다. iOS 시뮬레이터는 `http://localhost:3001/api`, Android 에뮬레이터는 `http://10.0.2.2:3001/api`를 사용할 수 있습니다. 환경변수 변경 후 개발 메뉴에서 앱을 완전히 Reload합니다.

예시 로그인 계정은 **`demo@jeupjeup.local` / `Jeupjeup123!`** 입니다. 이메일과 비밀번호를 검증하고, 64자리 세션 토큰을 발급합니다. 사용자와 세션은 `.data/auth.sqlite`에 보관하며 비밀번호는 scrypt+salt, 저장된 세션 토큰은 SHA-256 해시를 사용합니다. `AUTH_DEMO_EMAIL`·`AUTH_DEMO_PASSWORD`는 예시 계정을 처음 생성할 때 적용됩니다. 이 서버는 로컬 개발용입니다.

구현된 기능은 이메일 로그인, 네이버·카카오 토큰 교환, 구글 브라우저 인증·코드 교환, 세션 조회·로그아웃입니다. 로그인 직후 앱에 필요한 `GET /state`는 사용자와 빈 콘텐츠·알림을 반환하고 `GET /me`는 사용자를 반환합니다. 회원가입·콘텐츠 저장·프로필 변경 등 나머지 API는 `501 NOT_IMPLEMENTED`를 반환합니다. 전체 앱 API 명세는 외부 백엔드 구현용으로 유지됩니다.

소셜 인증을 설정하지 않아도 예시 계정의 이메일 로그인은 바로 사용할 수 있습니다. 소셜 인증은 실제 제공자 토큰을 검증하며 임의 토큰으로 성공하지 않습니다. 서버 설정은 `.env.local`에 넣을 수 있고 `.env`보다 우선합니다.

- 카카오: 네이티브 키 `KAKAO_CID` 외에 서버용 숫자 앱 ID `KAKAO_APP_ID`를 설정합니다. 토큰 정보 API의 앱 ID와 사용자 ID를 확인한 뒤 프로필을 조회합니다.
- 네이버: 앱의 `NAVER_CID`·`NAVER_CLIENT_SECRET` 설정 후 서버가 네이버 프로필 API로 토큰과 사용자 ID를 확인합니다. 현재 access-token 요청만으로는 서버에서 client ID/audience를 별도로 검증하지 않습니다.
- 구글: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `AUTH_PUBLIC_BASE_URL`을 설정하고 Google 웹 OAuth 클라이언트에 `{AUTH_PUBLIC_BASE_URL}/api/auth/oauth/google/callback`을 등록합니다. `AUTH_PUBLIC_BASE_URL`은 `/api`를 제외한 origin입니다. 실기기에서는 접근 가능한 고정 HTTPS 주소를 사용합니다. 서버는 state·PKCE·일회용 코드·만료 시간을 검증합니다.

예시 서버의 이메일 로그인·상태 조회·로그아웃은 로컬 LAN HTTP 요청으로 확인했습니다. 이메일·네이버·카카오·구글 로그인은 사용자가 앱에서 동작을 확인했습니다.

- [OpenAPI 3.1 명세](docs/api/openapi.json)
- [화면별 API 매핑](docs/api/mapping.md)
- [검증 범위](docs/api/verification.md)

```sh
bun run lint
bun run typecheck
```

## 지원 범위

네이버(NID)·카카오 로그인은 `gaesancheck-frontend`와 같은 네이티브 SDK 방식으로 연결되어 있습니다. `modules/social-login`이 iOS·Android 인증을 처리하고, 제공자 토큰을 `POST /auth/oauth/{provider}/exchange`로 전달해 줍줍의 `Session`으로 교환합니다. 인증 취소 시 로그인 화면에 머물며, 제공자 토큰은 앱 세션으로 저장하지 않습니다. 구글 로그인은 같은 참고 프로젝트의 서버 중계 브라우저 인증 방식으로 연결되어 있습니다. 구글 버튼도 기존 세션 저장 흐름을 사용합니다.

빌드 환경에 `KAKAO_CID`(카카오 네이티브 앱 키), `NAVER_CID`, `NAVER_CLIENT_SECRET`을 설정합니다. 로컬에서는 루트 `.env`에 넣고, EAS에서는 해당 빌드 환경의 환경변수를 사용합니다. 키와 네이버 secret은 네이티브 SDK 설정에 포함되며 JS의 `expo.extra`에는 넣지 않습니다. 줍줍용 앱 등록을 사용합니다.

- iOS Bundle ID / Android package: `kr.pro203s.jeupjeup`
- 네이버 iOS URL scheme: `kr.pro203s.jeupjeup.naver`
- 카카오 callback scheme: `kakao{KAKAO_CID}`. 개발자 콘솔에서 iOS Bundle ID와 Android package·빌드 서명 키 해시를 등록합니다.

네이티브 SDK를 추가했으므로 `bunx expo prebuild` 후 `bunx expo run:ios` 또는 `bunx expo run:android`로 개발 클라이언트를 다시 빌드해야 합니다. Expo Go에서는 동작하지 않습니다. EAS에서는 네이티브 폴더를 CNG로 생성하는 빌드와 development 프로필을 사용합니다. 예시 서버에 제공자 토큰 검증과 줍줍 세션 발급 API가 포함되어 있습니다. 네이버·카카오·구글 로그인은 제공자 키와 callback을 설정한 개발 환경에서 사용자가 동작을 확인했습니다.

구글 로그인은 `GET /auth/oauth/google/authorize`로 시작하고 `jeupjeupsave://login`으로 돌아온 일회용 앱 코드를 `POST /auth/oauth/google/exchange`에서 Session으로 교환합니다. 요청별 `state`와 PKCE(S256)를 검증하며, 취소·동의 거절은 로그인 실패로 표시하지 않습니다. 예시 서버는 앱 callback URI를 고정하고, 인증 코드에 state·PKCE·callback·유효기간을 묶어 한 번만 교환합니다. Google OAuth Client ID/Secret과 Google에 등록할 HTTPS callback은 백엔드에 설정하며 앱에는 client secret을 넣지 않습니다. `jeupjeupsave://login`은 서버에서 앱으로 돌아오는 주소입니다.

`expo-crypto`를 추가했으므로 기존 개발 클라이언트도 다시 빌드해야 합니다. 구글 계정 인증과 서버 세션 교환은 사용자가 앱에서 동작을 확인했습니다.

AI 분석·자동 분류·의미 검색, 원격 이미지/추천, 오프라인 쓰기 동기화, 푸시 알림은 외부 서비스 설정 또는 추가 구현이 필요합니다. 해당 기능을 가짜 성공으로 처리하지 않습니다. 현재 저장은 URL과 메모를 보존하며, 상세에서 제목·유형·컬렉션을 직접 수정하고 키워드로 검색할 수 있습니다. 고객센터는 선택적 `EXPO_PUBLIC_SUPPORT_URL`로 연결합니다.

개발 빌드에서는 환경변수 없이 개발 메뉴의 Custom items에 Figma 예시 데이터·빈 화면·상세 상태·온보딩 항목이 표시됩니다. 해당 메뉴를 선택하면 미리보기 모드로 전환됩니다. 이 미리보기 데이터는 서버로 전송하지 않습니다. 이전 로컬 UI 미리보기 데이터는 운영 데이터로 자동 가져오지 않습니다.

## 다른 앱에서 링크 공유받기

`expo-sharing`으로 iOS Share Extension과 Android 텍스트 공유 수신을 활성화했습니다. 플랫폼·도메인 제한 없이 공유받은 HTTP/HTTPS 링크를 기존 ‘정보의 링크를 입력해주세요’ 창의 URL 칸에 자동 입력합니다. 설명이 함께 전달되면 그 안의 첫 번째 링크를 사용합니다. 공유만으로 저장하거나 링크 미리보기를 조회하지 않으며, ‘추가’를 누르면 기존 저장 API를 호출합니다. 로그인 여부와 현재 화면에 관계없이 입력 창을 표시합니다. 이미지·영상 파일 수신은 이번 범위에 포함하지 않습니다.

네이티브 확장 기능이 추가되어 앱을 다시 빌드·설치해야 합니다. `bunx expo run:ios` 또는 `bunx expo run:android`를 사용합니다. iOS에는 `kr.pro203s.jeupjeup.ShareExtension` 확장과 `group.kr.pro203s.jeupjeup` App Group이 추가됩니다. 실기기 빌드의 서명 설정에도 이 App Group이 반영되어야 합니다. Expo Go나 재빌드 전 개발 클라이언트에는 공유 대상이 나타나지 않습니다. SDK 58의 iOS 공유 수신은 Expo가 실험적 기능으로 제공하는 방식입니다.

## 화면과 에셋

[Figma uiux](https://www.figma.com/design/E4bCW66UwriovsrDEnmqsL?node-id=1-5)의 화면 구조를 유지했습니다. 화면은 `src/app`, 재사용 UI는 `src/components`, 상태·API·에셋·색상은 `src/modules`, 타입은 `src/types`에 있습니다. 이미지·SVG는 `assets/figma`, Pretendard·Paperlogy는 라이선스와 함께 `assets/fonts`에 있습니다.

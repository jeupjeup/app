# 줍줍 저장소

Expo SDK 58 · React Native 0.88 · Expo Router / React + Vite / FastAPI + SQLite

기존 앱 화면과 상태 관리를 유지하고 `jupjup-web-backend-mobile/`의 실제 백엔드·웹을 통합했습니다. 앱은 `/api`, 웹은 같은 서버의 `/api/auth/*`와 `/v1`을 사용합니다. 계정, 저장 콘텐츠, 분석 작업은 하나의 DB를 공유합니다. 앱에 URL을 저장하면 웹에도 나타나며 실제 분석 결과가 앱의 설명·태그에 반영됩니다.

## 설치와 실행

Python 3.12를 관리할 [uv](https://docs.astral.sh/uv/)와 Bun을 설치합니다.

```sh
bun install
uv sync --project jupjup-web-backend-mobile --extra analyze-local
npm --prefix jupjup-web-backend-mobile/frontend ci
cp .env.example .env.local  # 기존 파일이 있으면 덮어쓰지 말고 필요한 값만 수정
```

실제 로컬 LLM을 사용하려면 약 4.7GB의 Qwen 모델을 한 번 내려받습니다. 모델과 DB는 Git에 포함하지 않습니다.

```sh
cd jupjup-web-backend-mobile
uv run --extra analyze-local jupjup models pull qwen2.5-7b-instruct-q4km
uv run --extra analyze-local jupjup models doctor
cd ..
bun run dev
```

`bun run dev`는 API·분석 워커·웹·Expo를 함께 실행합니다. 종료하면 함께 시작한 프로세스들을 종료합니다. 포트가 이미 사용 중이라면 해당 프로세스를 임의로 종료하지 말고 필요한 서비스를 개별 실행합니다.

```sh
bun run dev:api  # http://127.0.0.1:8000, 워커 포함
bun run dev:web  # http://127.0.0.1:5177
bun start       # Expo
```

백엔드는 기본적으로 `jupjup-web-backend-mobile/var/jupjup.db`를 사용합니다. `JUPJUP_DB_PATH`를 지정하면 API와 내장 워커에 함께 적용됩니다. 웹에서 앱과 같은 이메일로 로그인하면 같은 보관함을 조회합니다. 예시 인증 서버의 계정·세션은 별도 DB이므로 통합 서버에서 회원가입해야 합니다. 이전 예시 서버는 `bun run dev:auth:example`로만 실행하며 콘텐츠 저장을 지원하지 않습니다.

## 앱 주소와 네트워크

- iOS 시뮬레이터: `http://127.0.0.1:8000/api`
- Android 에뮬레이터: `http://10.0.2.2:8000/api`
- 실기기: `EXPO_PUBLIC_API_URL=http://<MAC_LAN_IP>:8000/api`, `JUPJUP_API_HOST=0.0.0.0`
- 운영: `EXPO_PUBLIC_API_URL=https://<DOMAIN>/api`와 HTTPS 리버스 프록시 필요

환경변수 변경 후 앱을 Reload합니다. 미설정 개발 빌드에서는 플랫폼별 시뮬레이터 주소가 기본값입니다. 운영 빌드는 HTTPS 주소만 허용합니다. `plugins/with-local-api.js`는 iOS 로컬 네트워크 권한과 Android **debug 전용** HTTP 허용을 생성합니다. 네이티브 설정 변경은 개발 클라이언트를 재빌드해야 반영됩니다. 네이티브 HTTP에는 CORS 우회를 사용하지 않습니다.

웹 개발 프록시는 `/api`, `/v1`, `/healthz`를 접두사 변경 없이 API 서버로 전달합니다. 별도 API origin은 `JUPJUP_API_ORIGIN`, 배포 웹의 API origin은 `VITE_API_BASE_URL`로 지정하며 `/api`를 추가하지 않습니다. 기존 `/api/api` 주소는 사용하지 않습니다.

## 연결한 기능

회원가입·로그인·보안 세션 복원·로그아웃·탈퇴, 프로필·비밀번호 변경, URL/메모 저장, 목록·상세·수정, 휴지통·복원·비우기, 알림 읽음, 검색 기록을 실제 서버에 연결했습니다. 앱은 쓰기 후·foreground 복귀 시와 활성 중 주기적으로 `/state`를 갱신합니다. 분석 중에는 2.5초 간격으로 결과를 확인합니다. 중복 URL과 401·네트워크 오류는 실제 안내를 표시합니다. 개발용 Figma 프리셋은 서버 저장과 분리되어 있습니다.

웹은 같은 계정의 콘텐츠·검색·AI 결과·수동/자동 컬렉션을 사용합니다. 앱의 여섯 가지 고정 컬렉션 분류와 웹의 사용자 정의 컬렉션은 기존 백엔드 계약에 따라 별도입니다. 웹 텍스트 전용 콘텐츠는 URL만 지원하는 앱 DTO로 변환하지 않습니다. 웹 즐겨찾기는 브라우저에 저장됩니다.

`.env.example`의 `live + local` 설정은 실제 Qwen 분석을 사용합니다. `JUPJUP_EMBEDDING_BACKEND=hashing`은 로컬 개발용 검색 벡터이며 BGE 의미 검색과 품질이 다릅니다. 운영 의미 검색은 `uv sync --extra local-models`, BGE 모델 준비 후 `JUPJUP_EMBEDDING_BACKEND=auto`를 사용합니다. 임베더를 바꾸면 별도 DB로 시작하거나 기존 인덱스를 재구축해야 합니다. LLM 미설정·수집 차단은 실패로 표시하며 가짜 분석으로 대체하지 않습니다. 전달본에 누락된 네 개 검색 사전은 제공된 명세의 별칭·불용 표현을 기준으로 보완했으며 원본 튜닝 사전과 동일하다고 보장하지 않습니다.

## 소셜 로그인

기존 `modules/social-login`의 네이버·카카오 네이티브 SDK와 구글 브라우저 PKCE 방식을 유지했습니다. 실제 백엔드가 제공자 토큰을 확인하고 이메일 로그인과 동일한 계정 DB에 세션을 발급합니다. 이메일이 같다는 이유로 기존 계정에 소셜 계정을 자동 연결하지 않습니다.

- 앱 Bundle ID / package: `kr.pro203s.jeupjeup`
- 네이버 SDK: `NAVER_CID`, `NAVER_CLIENT_SECRET`, callback scheme `kr.pro203s.jeupjeup.naver`
- 카카오 SDK: `KAKAO_CID`(네이티브 앱 키), 서버 `KAKAO_APP_ID`(숫자 앱 ID)
- 앱 Google: 서버 `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `API_PUBLIC_ORIGIN`; Google console callback은 `{API_PUBLIC_ORIGIN}/api/auth/oauth/google/native-callback`
- 웹 Google/네이버: `GOOGLE_OAUTH_CLIENT_ID/SECRET`, `NAVER_OAUTH_CLIENT_ID/SECRET`, `OAUTH_PUBLIC_ORIGIN`; callback은 `{OAUTH_PUBLIC_ORIGIN}/api/auth/oauth/{provider}/callback`

앱 Google은 `jeupjeupsave://login`으로 돌아오는 일회용 코드를 state·PKCE와 함께 교환합니다. 서버 재시작 시 진행 중인 앱 Google 로그인은 다시 시작해야 합니다. 네이버 access-token 방식은 별도 audience 확인 API가 없어 기존 방식의 제한을 유지합니다. 실제 제공자 로그인은 콘솔 키·callback 설정과 사용자 계정으로 별도 확인해야 합니다.

## 검증

```sh
bun run lint
bun run typecheck
npm --prefix jupjup-web-backend-mobile/frontend run lint
npm --prefix jupjup-web-backend-mobile/frontend run typecheck
npm --prefix jupjup-web-backend-mobile/frontend run build
cd jupjup-web-backend-mobile
uv run --extra analyze-local ruff check src
uv run --extra analyze-local mypy src
```

요청에 따라 단위·회귀 테스트는 실행하지 않았습니다. 실제 실행 검증은 iOS 시뮬레이터에서 앱 상태 관리의 로그인·URL 저장·중복·갱신·세션 복원, 웹 이메일 로그인 및 동일 콘텐츠·실제 Qwen 요약/태그 조회, API의 수정·삭제·복원·휴지통 비우기·알림·검색 기록·비밀번호·탈퇴·401·검색·컬렉션 흐름으로 수행했습니다. 제공자 로그인 전체, Android·실기기·운영 HTTPS, 푸시·오프라인 동기화·이미지 업로드는 이번 확인 범위에 포함되지 않습니다.

개발 빌드에서는 환경변수 없이 개발 메뉴의 Custom items에 Figma 예시 데이터·빈 화면·상세 상태·온보딩 항목이 표시됩니다. 해당 메뉴를 선택하면 미리보기 모드로 전환됩니다. 이 미리보기 데이터는 서버로 전송하지 않습니다. `Figma · 예시 데이터 저장`을 누르면 예시 프리셋을 기기에 저장해 앱 재시작·Reload 후에도 복원합니다. `Figma · 예시 데이터 저장 해제`를 누르면 저장 설정을 지우고 기존 로그인 세션으로 돌아갑니다. 정상 로그인에 성공해도 저장 설정이 해제됩니다. 운영 빌드에서는 저장된 개발용 프리셋을 읽지 않습니다. 이전 로컬 UI 미리보기 데이터는 운영 데이터로 자동 가져오지 않습니다.

## 다른 앱에서 링크 공유받기

`expo-sharing`으로 iOS Share Extension과 Android 텍스트 공유 수신을 활성화했습니다. 플랫폼·도메인 제한 없이 공유받은 HTTP/HTTPS 링크를 기존 ‘정보의 링크를 입력해주세요’ 창의 URL 칸에 자동 입력합니다. 설명이 함께 전달되면 그 안의 첫 번째 링크를 사용합니다. 공유만으로 저장하거나 링크 미리보기를 조회하지 않으며, ‘추가’를 누르면 기존 저장 API를 호출합니다. 로그인 여부와 현재 화면에 관계없이 입력 창을 표시합니다. 이미지·영상 파일 수신은 이번 범위에 포함하지 않습니다.

네이티브 확장 기능이 추가되어 앱을 다시 빌드·설치해야 합니다. `bunx expo run:ios` 또는 `bunx expo run:android`를 사용합니다. iOS에는 `kr.pro203s.jeupjeup.ShareExtension` 확장과 `group.kr.pro203s.jeupjeup` App Group이 추가됩니다. 실기기 빌드의 서명 설정에도 이 App Group이 반영되어야 합니다. Expo Go나 재빌드 전 개발 클라이언트에는 공유 대상이 나타나지 않습니다. SDK 58의 iOS 공유 수신은 Expo가 실험적 기능으로 제공하는 방식입니다.

## 화면과 에셋

[Figma uiux](https://www.figma.com/design/E4bCW66UwriovsrDEnmqsL?node-id=1-5)의 화면 구조를 유지했습니다. 화면은 `src/app`, 재사용 UI는 `src/components`, 상태·API·에셋·색상은 `src/modules`, 타입은 `src/types`에 있습니다. 이미지·SVG는 `assets/figma`, Pretendard·Paperlogy는 라이선스와 함께 `assets/fonts`에 있습니다.

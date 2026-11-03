# 줍줍 저장소

Expo SDK 58 · React Native 0.88 · TypeScript · Expo Router

iOS·Android 앱입니다. 화면의 데이터 요구사항과 외부 백엔드 API 계약을 `/docs/api/`에 정리했습니다. 프론트엔드 API 클라이언트가 포함되어 있습니다.

## 실행 및 API 주소

이 저장소는 프론트엔드와 API 명세만 포함하며 별도 서버를 실행하지 않는다. 실제 외부 백엔드와의 연동은 미검증이다.

```sh
bun install
cp .env.example .env
```

루트 `.env`에서 주소를 변경한다.

```dotenv
EXPO_PUBLIC_API_URL=https://your-api-host/api
```

실제 서버 주소와 공통 API prefix를 입력한 뒤 `bun start`로 실행한다. 클라이언트는 뒤에 `/auth/login`, `/state`, `/contents` 등을 붙인다. 환경변수 변경 후 Metro를 재시작한다. SecureStore가 없는 기존 개발 클라이언트는 `bunx expo run:ios` 또는 `bunx expo run:android`로 다시 빌드한다.

- [OpenAPI 3.1 명세](docs/api/openapi.json)
- [화면별 API 매핑](docs/api/mapping.md)
- [검증 범위](docs/api/verification.md)

```sh
bun run lint
bun run typecheck
```

## 지원 범위

소셜 OAuth, AI 분석·자동 분류·의미 검색, 원격 이미지/추천, 오프라인 쓰기 동기화, 푸시 알림은 외부 서비스 설정 또는 추가 구현이 필요합니다. 해당 기능을 가짜 성공으로 처리하지 않습니다. 현재 저장은 URL과 메모를 보존하며, 상세에서 제목·유형·컬렉션을 직접 수정하고 키워드로 검색할 수 있습니다. 고객센터는 선택적 `EXPO_PUBLIC_SUPPORT_URL`로 연결합니다.

`EXPO_PUBLIC_ENABLE_PREVIEW=1`인 개발 빌드에서만 Figma 메뉴의 예시 데이터와 화면 상태를 사용할 수 있습니다. 이 미리보기 데이터는 서버로 전송하지 않습니다. 이전 로컬 UI 미리보기 데이터는 운영 데이터로 자동 가져오지 않습니다.

## 화면과 에셋

[Figma uiux](https://www.figma.com/design/E4bCW66UwriovsrDEnmqsL?node-id=1-5)의 화면 구조를 유지했습니다. 화면은 `src/app`, 재사용 UI는 `src/components`, 상태·API·에셋·색상은 `src/modules`, 타입은 `src/types`에 있습니다. 이미지·SVG는 `assets/figma`, Pretendard·Paperlogy는 라이선스와 함께 `assets/fonts`에 있습니다.

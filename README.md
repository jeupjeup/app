# 줍줍 저장소

Expo SDK 58 · React Native · TypeScript · Expo Router · expo-dev-client

[Figma uiux](https://www.figma.com/design/E4bCW66UwriovsrDEnmqsL?node-id=1-5)의 7개 Section 내부 화면을 구현했습니다. `gaesancheck-frontend`를 참고해 화면은 `src/app`, 재사용 UI는 `src/components`, 상태·에셋·색상은 `src/modules`, 타입은 `src/types`에 배치했습니다.

## 실행

```bash
bun install
bun start
```

iOS·Android 전용 프로젝트입니다. `bun start`는 development client에 연결할 Metro 개발 서버를 실행합니다. 개발 클라이언트에 expo-dev-client, expo-network, AsyncStorage 모듈이 포함되어 있어야 합니다.

## 화면과 데이터

온보딩, 로그인·가입·약관 동의, 홈·검색·추가 팝업, 보관함·필터, 콘텐츠 상세·상태·삭제 팝업, 알림, 마이페이지·계정·비밀번호·최근 본 상품·휴지통이 포함되어 있습니다. Figma의 원본 이미지와 SVG는 `assets/figma`, Pretendard와 Paperlogy는 라이선스와 함께 `assets/fonts`에 저장되어 있습니다.

`assets/figma/images`에는 이미지, `assets/figma/icons`에는 SVG 아이콘을 모았습니다. 폰트는 `assets/fonts/pretendard`, `assets/fonts/paperlogy`로 나뉘며 각 폴더에 라이선스를 포함합니다. `src/modules/assets.ts`에서 화면별 에셋 이름과 Figma 원본 노드 ID를 관리하고, 완전히 동일한 에셋은 한 파일을 공유합니다.

API 주소나 인증 설정이 제공되지 않아 현재는 **로컬 UI 미리보기**입니다. 로그인 입력은 서버 검증을 하지 않으며 SNS 버튼은 가입 화면으로 이동합니다. 비밀번호 변경도 메모리에서만 동작합니다. 비밀번호는 AsyncStorage에 저장하지 않습니다. 로그인 시 입력한 값을 기존 비밀번호로 사용하며, 입력한 값이 없는 미리보기에서는 Figma 예시 값 `wjdiawnd23.`을 사용합니다.

저장·필터·키워드 검색·삭제·복구·닉네임·최근 본 항목은 로컬 상태에 연결되어 있습니다. 검색은 로컬 문자열 검색이며 AI 검색이 아닙니다. 새 URL은 분석 중 상태로 저장됩니다. 소셜 인증, AI 분석, 오프라인 항목의 서버 동기화, 실제 계정 탈퇴·비밀번호 변경은 API 연결이 필요합니다. 고객센터는 연결 주소가 없어 항목만 표시합니다.

개발 클라이언트 메뉴의 `Figma ·` 항목에서 예시 데이터 복원, 빈 상태, 콘텐츠 분석 중·실패·원본 접근 불가, 온보딩을 확인할 수 있습니다. 데이터 복원·빈 상태 메뉴는 현재 로컬 미리보기 데이터를 바꿉니다. 일반 앱 화면에는 추가 미리보기 UI를 넣지 않았습니다.

## 정적 검사

```bash
bun run lint
bun run typecheck
```

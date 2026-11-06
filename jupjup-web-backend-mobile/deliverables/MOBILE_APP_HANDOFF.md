# JupJup 모바일 앱 연동 인수인계

## 기준

- 계약 기준: `specs/app_api_openapi.json`
- 원본 백엔드 명세 `message (5).txt`와 SHA-256이 동일합니다.
- SHA-256: `cd18e859669a75280dd8d130150a96a2a0966855911d3b175fbaabaea651194d`
- 계약 규모: 24 operations, 17 schemas
- GitHub 기준 브랜치/커밋: `PM` / `df63422fc33d356026a21951e6766802956a47dc`
- `/api` 계약은 동결되어 있습니다. 앱 편의를 위해 응답 필드를 임의로 추가하거나 이름을 바꾸지 마세요.

## Base URL

| 환경 | Base URL |
|---|---|
| iOS Simulator | `http://127.0.0.1:8000/api` |
| Android Emulator | `http://10.0.2.2:8000/api` |
| 같은 Wi-Fi의 실기기 | `http://<MAC_LAN_IP>:8000/api` |
| 운영 | `https://<DOMAIN>/api` |

로컬 서버 실행:

```bash
JUPJUP_AUTH_BACKEND=app_session \
uv run jupjup api serve \
  --host 0.0.0.0 \
  --port 8000 \
  --allow-external-bind
```

연결 확인:

```bash
python scripts/app_contract_smoke.py \
  --base-url http://<MAC_LAN_IP>:8000/api
```

## 앱 구현 규칙

1. `/auth/register` 또는 `/auth/login`의 토큰을 Keychain/Keystore 같은 보안 저장소에 저장합니다.
2. 인증 API에는 `Authorization: Bearer <token>`을 붙입니다.
3. 모든 `POST`/`PATCH` 요청은 `Content-Type: application/json`을 사용합니다.
4. body가 없는 `POST`도 `{}`를 전송합니다.
5. HTTP 401이면 로컬 세션을 제거하고 로그인 화면으로 이동합니다.
6. 오류는 번역된 `message`가 아니라 `error.code`를 기준으로 분기합니다.
7. 쓰기 완료 후와 앱 foreground 복귀 시 `/state`를 다시 조회합니다.
8. 앱 저장은 `/api/contents`만 사용합니다. `/v1`을 앱 내부에서 혼용하지 않습니다.
9. URL 정규화 기준으로 이미 존재하는 콘텐츠는 `409 DUPLICATE_CONTENT`가 정상 동작입니다.
10. 네이티브 요청은 CORS 설정이 필요 없습니다. WebView라면 정확한 origin을 서버 `CORS_ORIGINS`에 등록해야 합니다.

## 콘텐츠 통합 동작

`POST /contents`로 URL을 저장하면 같은 DB 트랜잭션 안에서 다음 항목이 생성됩니다.

- 모바일 앱 콘텐츠
- 웹 콘텐츠
- 앱-웹 콘텐츠 연결
- AI 분석 작업

실패하면 모두 롤백됩니다. 연결된 콘텐츠의 분석 상태와 결과는 앱 조회 응답에 투영됩니다. 중복, 휴지통 이동, 복원, 영구 삭제와 기존 데이터의 기본 연결도 지원합니다.

## 완료 조건

- 회원가입, 로그인, 로그아웃 및 앱 재실행 후 세션 복원
- URL 저장 후 콘텐츠 목록과 상세 화면 반영
- 분석 중/완료/실패 상태 표시
- 중복 URL `409` 사용자 안내
- 수정, 삭제, 복원, 휴지통 비우기
- 알림 조회 및 읽음 처리
- 검색 기록 조회, 추가, 삭제
- 401 세션 만료 처리
- 네트워크 오류와 재시도 UI
- iOS Simulator, Android Emulator 또는 실기기 중 최소 하나에서 실제 백엔드 연결 확인

## ZIP 내 참고 자료

- `specs/app_api_openapi.json`: 유일한 API 계약 기준
- `specs/mobile_backend_contract_matrix.json`: endpoint/schema 대응표
- `specs/mobile_backend_contract_audit.md`: 명세 일치 감사
- `specs/mobile_app_bridge_report.md`: LAN 및 인증 연결 방법
- `specs/phase12_bridge_report.md`: 앱 저장과 웹·AI 분석 브리지 구현 범위
- `scripts/app_contract_smoke.py`: 실제 서버 계약 스모크 테스트

## 현재 MVP 제한

- 운영 도메인과 HTTPS 인프라는 별도로 준비해야 합니다.
- 장시간 전체 회귀 테스트 대신 앱 계약 및 브리지 집중 테스트 71개를 통과했습니다.
- 앱 프론트는 OpenAPI 계약에만 의존해야 하며 내부 DB 구조에 의존하면 안 됩니다.

# JupJup 웹·백엔드·모바일 앱 통합 인수인계

이 번들은 JupJup의 웹 프론트, 백엔드, 모바일 앱 계약을 한 번에 전달하기 위한 소스 스냅샷입니다.

## 디렉터리 역할

- `frontend/`: React/Vite 웹 프론트
- `src/jupjup/`: Python 백엔드와 `/api`, `/v1`
- `specs/app_api_openapi.json`: 모바일 앱 전용 동결 계약
- `scripts/app_contract_smoke.py`: 모바일 API 실제 연결 검사
- `tests/`: 백엔드 계약·브리지 테스트
- `deliverables/MOBILE_APP_HANDOFF.md`: 모바일 구현 규칙
- `deliverables/WEB_APP_MERGE_AGENT_PROMPT.md`: 통합 에이전트 지시문

## 중요한 경계

- 웹은 현재 `/v1`의 상세 AI·검색·OAuth 기능을 계속 사용합니다.
- 모바일 앱은 동결된 `/api`만 사용합니다.
- `/api/contents`로 URL을 저장하면 백엔드 브리지가 웹 콘텐츠와 AI 분석 작업을 함께 생성합니다.
- 두 클라이언트가 같은 콘텐츠를 보지만, 모바일이 `/v1`을 직접 호출하거나 웹이 `/api` DTO에 의존하도록 섞지 않습니다.
- OpenAPI 응답 필드는 앱 편의를 위해 임의로 변경하지 않습니다.

## 웹 실행

```bash
cd frontend
npm ci
npm run dev
```

기본 로컬 주소는 `http://127.0.0.1:5177`입니다. 실제 환경 변수는 커밋하지 말고 `frontend/.env.example`을 기준으로 로컬 파일을 만드세요.

## 백엔드와 앱 실행

```bash
uv sync
JUPJUP_AUTH_BACKEND=app_session \
uv run jupjup api serve \
  --host 0.0.0.0 \
  --port 8000 \
  --allow-external-bind
```

- 웹/데스크톱 로컬 API: `http://127.0.0.1:8000`
- iOS Simulator 앱 API: `http://127.0.0.1:8000/api`
- Android Emulator 앱 API: `http://10.0.2.2:8000/api`
- 같은 Wi-Fi 실기기 앱 API: `http://<MAC_LAN_IP>:8000/api`

## 스냅샷 주의사항

- 웹 폴더에는 전달 시점의 로컬 UI 변경분도 포함되어 있습니다.
- `node_modules`, `.venv`, 빌드 결과, 캐시, Git 기록, DB, 로그, 실제 `.env`와 비밀값은 제외했습니다.
- 의존성은 lockfile로 다시 설치하세요.
- 운영 환경에는 별도의 도메인과 HTTPS가 필요합니다.

## 통합 완료 조건

1. 기존 웹 로그인·저장·목록·상세·검색이 유지됩니다.
2. 앱 로그인 토큰이 안전하게 저장되고 재실행 후 복원됩니다.
3. 앱 URL 저장이 웹 콘텐츠 및 AI 분석 작업으로 연결됩니다.
4. 웹과 앱에서 같은 콘텐츠의 분석 상태가 일관되게 보입니다.
5. 앱은 401, 409 중복, 네트워크 실패를 올바르게 처리합니다.
6. 웹 typecheck/test/build와 앱의 대응 검사가 통과합니다.
7. 백엔드 앱 계약 및 브리지 집중 테스트가 통과합니다.

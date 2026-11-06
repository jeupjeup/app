# 프론트 코어 통합 결과 / PM 검수 인계

## 완료

- 원래 Router/셸/카드/업로드 폼/상세 섹션/CSS와 반응형을 기반으로 실제 API 연결.
- 목록(커서·서버 필터·숨김), 상세 직접 진입/중복 별칭, URL/텍스트 저장, 실제 job polling, confirm 후보 승인·거절, 사용자 요약/대표 태그/topics PATCH+ETag, 숨김, snapshot 재분석, hard delete, 자연어 검색 연결.
- 대시보드 검색 진입도 API 검색으로 연결. 반환 순위 유지, 로컬 검색으로 결과 추가/재정렬 없음. 최근/오래된 바로가기는 서버 목록 조건 사용.
- 콘텐츠 localStorage/seed fallback 및 가짜 분석 타이머 제거. 원본 보존용 샘플 모듈은 남아 있지만 실제 Router/Store 콘텐츠 경로에서는 사용하지 않음.
- 개발 사용자/시험용 분석 안내. 한국어 상태·단계·필터/태그, raw JSON은 접힌 개발 진단 영역만 표시.
- OAuth·서버 컬렉션/favorite·제목/기존 메모 수정은 비활성화/미지원 안내. 보기 설정만 브라우저 저장. 미지원 Store throw 함수 및 호출부 제거.
- 브라우저에서 발견한 모달 inert/포커스 문제(portal)와 서버 timestamp 날짜/최근 판정 문제 수정.

## 커밋

- `30d1f68`: 원본 소스 import + SHA-256 manifest.
- `5f3c708`: 통합 설계.
- `3f6fb67`: typed client/DTO/adapters/query hooks, loopback proxy.
- `bae0555`: 코어 화면/생명주기·검색 연결, 미지원 기능 처리.
- 마지막 검증 커밋: 이 보고서와 함께 client/adapters/화면 흐름 테스트, 로컬 HTTP smoke, timestamp 수정 포함. 정확한 해시는 `git log -1` 확인.
- 모든 커밋에 지정 Co-Authored-By 포함. push/병합 안 함.

## 검증 확정 (2026-11-05)

- 복사본 frontend에서 `npm ci`, 최종 `npm run check` PASS: 7개 파일, 21개 테스트. lint 6개 경고(Fast Refresh export 5, effect 상태 초기화 1), error 0. `npm run build` PASS.
- client/adapters: 개발 사용자·헤더/ETag·204·중첩 오류·비JSON 장애·반복 필터·멱등키 재사용·구조 태그/원문과 메모 구분·서버 날짜 확인.
- 컴포넌트 API stub 통합: 승인→ETag 편집→재분석/거절→검색 순위 보존→삭제, portal 대화상자, topics 외 JSON 보존 확인.
- 기존 API 회귀: `tests/integration/test_save_api.py test_save_acceptance.py test_save_time.py test_api_search.py test_api_ingest_worker_split.py` **68 passed**. PM .venv 재사용, PYTHONPATH는 이 워크트리/src. 평가용 test split/튜닝/모델 다운로드 실행 안 함.
- `python3 frontend/scripts/smoke_local_api.py` PASS: 실제 /api proxy·API·worker로 텍스트 저장/replay/conflict, snapshot/steps 실제 schema, 승인, PATCH/stale ETag, 타 사용자 404, 재분석/거절/사용자 수정 보존, 검색·숨김/해제·204 삭제. 전용 u_frontend_smoke의 생성 항목만 정리. 외부 URL 요청 없음.
- Orca 브라우저 수동 확인: 텍스트 저장→polling→후보 승인→완료→모바일 모달 편집→재분석→거절→사용자 수정 유지→대시보드 자연어 검색 결과까지 확인. 삭제는 HTTP smoke와 컴포넌트 테스트로 검증(브라우저 삭제 확인창 직접 조작은 미검증).
- 390×844 모바일 모달/상세/검색과 1440×1000 데스크톱 검색 화면 확인. 가로 overflow 없음(390/390, 1440/1440); 카드/주황색 액션/사이드바/반응형 유지. 최종 카드 날짜 '11월 5일' 확인. 모든 화면·기기 조합을 전수 검수한 것은 아님.
- 원본 78개 SHA-256 재확인, import commit과 manifest 일치 PASS. 원본 디렉터리/Git 쓰기 없음. `src/jupjup/` 전체 및 금지 검색/질의/embeddings 경로 무변경. 기존 데모 8780의 PID 38008 유지. 원본 환경 예제/README는 import 상태로 보존하고 실행 정보는 이 보고서를 정본으로 사용.

## 실행 중인 격리 환경 / 재시작

현재 워크트리: `/Users/minjun/orca/workspaces/dc2/phase-2-frontend-integration`
DB: 이 워크트리의 `var/frontend-integration.db` (새 생성, Git 제외). API/worker 모두 dev+mock. 기존 demo DB/포트/프로세스는 건드리지 않음.

| 용도 | URL / handle | PID |
|---|---|---|
| 프론트 Vite | http://127.0.0.1:5177/dashboard / `term_cd3df04c-ef52-4412-9c2a-e3003b1b1a37` | node 42586 |
| API | http://127.0.0.1:8791/healthz / `term_7da3a6a6-45ff-411c-9107-4bf6aa50e4e2` | python 41263 |
| worker | `term_a70d9b83-31d6-4311-bddf-bc0f621b738d` | terminal process 42010 |

브라우저 page id: `01846c0f-1d95-4cd8-9b35-a85494c8914d` (현재 검색 결과 화면). 원래 UI에서 만든 검수 항목 `c_37ac2c66dad544ad91af27ccf3be7ce5`는 u_frontend_dev 보관함에 남겨 독립 검수 가능. 시험용 입력만 사용.

재시작은 먼저 해당 포트 점유/위 전용 터미널 상태를 확인한다. 기존 서버를 종료하거나 중복 기동하지 않는다. 위 워크트리 루트에서 아래 명령을 각각 실행한다. Orca 터미널 재생성 시 `orca terminal create --worktree active --title <이름> --command '<아래 명령>' --json` 사용.

```sh
UV_PROJECT_ENVIRONMENT=/Users/minjun/orca/workspaces/dc2/PM/.venv PYTHONPATH="$PWD/src" JUPJUP_ENV=dev JUPJUP_MODE=mock JUPJUP_ANALYZER__ENGINE=mock uv run --no-sync jupjup api serve --db "$PWD/var/frontend-integration.db" --host 127.0.0.1 --port 8791
UV_PROJECT_ENVIRONMENT=/Users/minjun/orca/workspaces/dc2/PM/.venv PYTHONPATH="$PWD/src" JUPJUP_ENV=dev JUPJUP_MODE=mock JUPJUP_ANALYZER__ENGINE=mock uv run --no-sync jupjup worker run --db "$PWD/var/frontend-integration.db" --concurrency 1
npm --prefix frontend run dev
```

`/api` proxy는 127.0.0.1:8791로 prefix 제거. dev 5177/preview 5178 모두 127.0.0.1 + strictPort. preview 배포 자체는 이번에 실행 검증하지 않음. 운영 배포는 별도 범위.

## 남은 제한 / 상태

- 실제 OAuth, 파일 OCR/비전·영상 전사, 컬렉션/favorite 서버 동기화, 제목/기존 메모 수정, job 단독 취소/원본 refresh API는 없음.
- 요약·대표 태그·topics 편집만 제공; 나머지 구조화 태그는 표시/보존. 전체 통계/이름순 정렬/검색 cursor 없음. URL은 공개 응답에서 추출 가능한 텍스트만 지원, 실제 외부 URL 수집 성공은 이번 검증 범위 아님.
- polling은 활성 상세에서 2초 간격, 서버 retry_wait 표시. 백그라운드 조회 중단/복귀 조회, terminal/승인대기 중단. 설계의 적응형 1→2→5초 backoff까지는 구현하지 않음.
- 멱등키는 같은 페이지 세션의 불확실 재전송에 유지(원문은 저장하지 않음). 새로고침 후 미응답 요청의 키 복구는 제공하지 않음.
- 완료 알림 설정은 보존되었으나 전역 background 완료 toast는 미연결; 실제 상태는 상세/polling으로 확인. 별도 전역 job manager를 추가하지 않음.
- 작업 종료/PM 독립 검수 대기. 컨텍스트는 이 보고서·설계·커밋으로 인계 가능. 최근 5시간 사용량 70%(리셋 13:32), 전역 모델 설정 변경/서브에이전트 실행 없음. 검수 여유를 위해 추가 범위 작업 중단.

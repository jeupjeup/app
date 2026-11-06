# 콘텐츠 상세 독립 검수

- 검수 대상: `6060a5c57b2dec5c17e36ee309bb05a1ad5abc43` (부모 대비 변경 및 관련 호출 경로). Claude 한도에 따른 독립 Codex 대체 검수.
- **점수: 77 / 100** (정확성 29/40, 안전성 23/30, 유지보수성 25/30)
- **상태: REJECT** (90점 이상만 PASS)
- **루프백 대상: Phase 2** (기능과 계정 범위 수정)

## 차단 문제와 피드백

1. `frontend/src/features/archive/ArchiveStore.tsx:10` — 즐겨찾기 키가 로그인 세션 사용자가 아니라 빌드 시 고정된 `env.userId`를 사용한다. 같은 브라우저/API에서 계정을 바꿔도 같은 ID 목록을 읽고 쓰며 이전 계정의 콘텐츠 ID가 로컬 저장소에 남는다. 쿼리는 `useSessionScope()`로 격리하지만 새 상태는 그렇지 않다. 실제 세션 사용자와 API 범위를 키로 사용하고 세션 변경 시 상태를 다시 읽어야 한다. 계정 전환 및 재로그인 테스트가 필요하다.
2. `frontend/src/pages/archive/ContentDetailPage.tsx:133` — 즐겨찾기 추가 성공을 알리지만, `frontend/src/pages/archive/ContentsPage.tsx:31`의 즐겨찾기 화면은 여전히 미지원 안내만 보이고 `frontend/src/features/archive/ArchiveCard.tsx:19`의 별도 비활성 상태에도 반영되지 않는다. 저장한 항목을 즐겨찾기에서 다시 찾을 수 없어 새 상호작용의 약속이 완결되지 않는다. 목록/카드와 동일한 범위의 상태를 연결하고 추가·해제·재방문을 검증해야 한다.
3. `frontend/src/features/archive/JobProgress.tsx:4` — 서버 `src/jupjup/save/jobs.py:169`는 확인 단계에 후보 상태 `approved` 또는 `rejected`를 그대로 반환하지만 표시 맵에 없어 “상태 확인 필요”로 표시된다. 확인 후 실제 결과가 불명확해진다. 서버 계약의 모든 단계 상태를 명시적으로 표현하고 승인·거절 사례를 테스트해야 한다.

## 검수 근거 및 잔여 사항

- 진행 단계는 서버의 `current_stage`와 `steps`를 사용하며 임의 퍼센트를 만들지 않는다. 대기/실행/재시도/확인 대기는 2초 폴링, 오류 후 재조회, 종료 상태 중지, 수동 확인이 코드에 있다. 백그라운드 폴링은 라이브러리 기본 정책에 의존한다. 401/404 등 영구 오류에도 계속 조회하는 정책과 서버 부하, 실제 타이머·복구 동작은 별도 통합 검증이 필요하다.
- 원본 열기, 컬렉션, 수정/ETag, 사용자 수정 해제, 숨김, 재분석, 삭제, 텍스트 대체 저장, YouTube 메타데이터, 후보 자동 적용 및 오류 경로를 코드로 살폈다. 기존 통합 테스트는 일부 편집·재분석·삭제·메타데이터 흐름을 모의 API로 다루지만 모든 상호작용과 실패/충돌, 즐겨찾기, 실제 서버를 증명하지 않는다. 실패 상태의 새 재시도 버튼은 기존 재분석 버튼과 달리 snapshot 및 `SOURCE_TEXT_UNAVAILABLE` 조건을 확인하지 않으므로 서버 거부 경로도 확인해야 한다 (`ContentDetailPage.tsx:141,157`).
- 단계 목록과 상태 live region, `aria-current`, 즐겨찾기 `aria-pressed`, 포커스 표시와 축소 동작 설정을 확인했다. 반응형 CSS의 850/620/380px 전환과 긴 텍스트 줄바꿈을 정적으로 확인했다. 실제 브라우저의 좁은 화면, 확대, 키보드 및 스크린리더 검사는 수행하지 않아 접근성과 시각적 배치를 완전히 보증할 수 없다.
- `rg -n -i 'kakao|integration-banner' frontend/src`: `.integration-banner`나 Kakao 로그인 구현은 발견되지 않았다. 카카오톡 저장물 플랫폼 레이블/필터와 Kakao 로그인 부재를 검증하는 테스트 문자열은 존재한다. 이는 카카오톡 콘텐츠 분류이지 로그인 연동 배너가 아니다.
- `specs/prd_and_design.md`는 백엔드 검색 MVP 명세여서 상세 UI 인수 기준은 제공하지 않는다. 사용자 요청, 변경 및 API 계약을 기준으로 평가했다. 이 검수는 전체 백엔드 PRD 적합성 판정이 아니다.

## 직접 실행한 검증

- `cd frontend && npm run typecheck`: 최초에는 의존성이 없어 `tsc: command not found` (종료 127). `npm ci` 후 재실행하여 통과 (종료 0).
- `cd frontend && npm ci`: 114개 패키지 설치, audit 취약점 0개 (종료 0).
- `cd frontend && npm test`: 15개 파일, 82개 테스트 통과 (종료 0, jsdom/모의 API).
- 실제 백엔드 연동 또는 실기기 시각 검사는 수행하지 않았다. 소스는 변경하지 않았다.

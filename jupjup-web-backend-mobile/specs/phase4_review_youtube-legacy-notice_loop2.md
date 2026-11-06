# Phase 4 검수: YouTube legacy notice loop 2

- **점수:** 100 / 100 (정확성 40 / 안전성 30 / 유지보수성 30)
- **상태:** PASS
- **피드백:** 대상 커밋 `1ff63ac`에서 실제 결함을 확인하지 못했다. 서버가 YouTube URL과 snapshot 메타데이터로 기존 watch snapshot을 판정하고, 상세·목록 응답에서 AI 파생값만 제외한다. 사용자 수정과 snapshot은 보존하며, GET 전후 모든 DB 테이블과 bundle을 비교하는 회귀가 있다. 정상 transcript와 직접 입력 회귀도 유지한다. UI는 job 오류가 없는 rejected 항목에서도 실패 안내와 별도 입력을 제공하고, 저장 원문 재분석을 비활성화한다. 근거: [query.py](../src/jupjup/save/query.py#L49), [ContentDetailPage.tsx](../frontend/src/pages/archive/ContentDetailPage.tsx#L61), [test_youtube_legacy_notice.py](../tests/integration/test_youtube_legacy_notice.py#L64), [integration.test.tsx](../frontend/src/app/integration.test.tsx#L106).
- **루프백 대상:** 없음

## 검증

- `mypy src`: 통과 (107 source files)
- Backend 지정 회귀 묶음: 71 passed
- Frontend `npm run check`: 7 files, 26 tests passed; lint 경고 6개는 기존 경고
- 검색 순위·검색 응답 투영·실DB·서버·외부 API는 건드리지 않았다.

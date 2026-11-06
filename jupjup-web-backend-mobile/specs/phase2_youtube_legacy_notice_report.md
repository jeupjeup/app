# Phase 2 YouTube legacy snapshot 읽기 안내 보고

구현 완료, PM 병합 대기. 기준 커밋 `8125c0c`, 작업 브랜치 `ultra-penguin/phase-2-youtube-legacy-notice`. 단일 Codex-Primary로 수행했다.

## 구현

- `src/jupjup/ingest/youtube.py`: 기존 watch snapshot/자막 증거 판정을 작은 공통 함수로 추출.
- `src/jupjup/ingest/worker.py`: 기존 chunk 단계의 차단 조건에 공통 함수 사용. 차단 기준은 유지.
- `src/jupjup/save/query.py`: 상세 analysis에 `source_text_available/source_text_reason` 파생. invalid watch snapshot이면 상세·목록의 유효 요약/대표 태그에서 AI만 제외. 상세 AI 세부 태그와 후보도 제외. 사용자 요약·대표 태그·세부 patch·hidden_ai·메모와 원문은 보존. 세부 patch는 빈 schema에 적용해 AI 상속 값이 남지 않게 함.
- `src/jupjup/save/dto.py`: analysis를 `ContentAnalysis`로 명시해 OpenAPI/응답 검증 계약에 반영.
- `frontend/src/shared/api/contracts.ts`, `frontend/src/test/fixtures.ts`: 파생 필드 계약 및 기존 fixture 갱신.
- `frontend/src/pages/archive/ContentDetailPage.tsx`: rejected 상태에서도 job 오류 없이 ‘영상 본문 확보 실패’ 안내, 사용자 수정 보존 명시, 자막/본문 직접 별도 저장 입력, 재분석 비활성화. 기존 페이지 원문은 기본 접힘 상태로 열람. invalid 상태에서 사용자 수정 해제 안내가 AI 재표시를 약속하지 않게 수정.
- `tests/integration/test_youtube_legacy_notice.py`, `frontend/src/app/integration.test.tsx`: 아래 회귀 추가.
- `specs/design_youtube_source_repair.md`: 읽기 안내 설계 추가.

## 직접 검증 결과

- backend 71 passed (3.12초):
  `PYTHONPATH=src /Users/minjun/orca/workspaces/dc2/PM/.venv/bin/python -m pytest tests/integration/test_youtube_legacy_notice.py tests/integration/test_ingest_pipeline.py tests/integration/test_save_api.py tests/integration/test_save_acceptance.py tests/unit/test_ingest_fetch_extract.py`
- 신규 backend 회귀 11개: rejected + 오래된 snapshot + 최신 job 없음, http 메타만 존재/명시적 HTML MIME, 사용자 수정 없음/태그만 존재/요약과 태그 모두 존재, 세부 patch의 null 삭제, 상세·목록 동일 투영. GET 전후 전체 테스트 DB 테이블 및 저장 bundle 동일성 확인. transcript_segments와 VTT/SRT/JSON MIME 및 직접 텍스트의 정상 결과 유지.
- frontend `npm run check`: 통과. 7 파일, 26 tests passed. 기존 lint 경고 6개(only-export-components 5, set-state-in-effect 1)는 유지.
- frontend `npm run build`: 통과 (121 modules). 지정된 기존 node_modules를 이 워크트리에 심볼릭 링크하여 재사용, 설치/다운로드 없음.
- 신규 UI 회귀 3개: 사용자 layer 유무별 rejected 안내·직접 입력·재분석 disabled·원문 접힘/펼침·목록 카드 표시, 사용자 편집 입력 보존, 정상 YouTube 자막은 원문 문자열에 약관 문구가 있어도 정상 표시·재분석 enabled. 직접 텍스트 저장 테스트의 유일한 쓰기는 모의 API의 새 항목 POST이며 기존 항목 PATCH/DELETE/재분석 요청 없음.
- 변경 Python 파일 ruff check 및 `git diff --check`: 통과.
- 초기 검증 실패도 수정 완료: 저장 이전 fixture와 저장 이후 자동 필드를 비교하던 테스트를 저장 직후 기준으로 교정; Testing Library의 지원하지 않는 exact 옵션 제거; 테스트 간 전역 query cache 영향을 고유 fixture ID로 분리. 루트 디렉터리 npm 실행의 ENOENT는 frontend 디렉터리에서 재실행하여 해결. ruff import 정렬 수정 후 통과.

## 범위·적용 안내

- 실사용자 `c_f7164cb29434443393406f5dc7e02fee` 자체를 조회·수정하지 않았으며, 같은 URL/유형의 격리된 메모리 DB fixture로 검증했다. 해당 항목의 기존 http watch snapshot도 공통 판정으로 읽는 즉시 안내할 수 있으며 데이터 복구나 재분석은 필요 없다.
- 원본 프론트 소스, 실DB, 실행 서버 8780/8791/5177, 사용자 데이터, API worker를 변경하거나 재시작하지 않았다. PM이 병합 및 worker 재시작을 담당한다. 실행 브라우저에 배포하거나 실서버 테스트를 하지 않았다.
- 목록의 필터/정렬/페이지 경계와 검색·query 디렉터리/검색 순위는 변경하지 않았다. 검색 응답의 투영 변경도 범위 밖이다. 목록 카드에는 투영된 사용자 값만 전달되며 새 raw_meta/source_meta/user_patch 공개는 없다(기존 상세 user_patch 계약은 그대로).
- 지원 모델/기본 mock/시험용 문구/품질 기준 변경 없음. 외부 LLM·다운로드·test split·push·다른 워커 사용 없음.
- 기존 설계에 읽기 전용 호환 처리를 추가했으며 별도 설계 이탈 없음. PM 보완 기준인 보관함 카드의 AI 요약/태그 제외도 반영했다.

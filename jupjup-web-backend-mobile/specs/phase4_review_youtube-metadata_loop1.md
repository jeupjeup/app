# Phase 4 독립 검수: YouTube 제목·설명 분류

## 판정

- **점수:** 97 / 100 (**정확성 39 / 40, 안전성 30 / 30, 유지보수성 28 / 30**)
- **상태:** **PASS**
- **루프백 대상:** 없음
- **검수 대상:** PM 병합 `9eaab7d`, `fd330e4`, `4e37458`, `df53bcb` 및 병합 HEAD `145e970`
- **변경 범위:** 본 보고서만 추가. 코드와 실행 중 서비스/데이터는 수정하지 않음.

## 확인 결과

- 수집기는 공개 player의 `videoDetails.title` 및 `videoDetails.shortDescription`만 메타데이터로 보존한다. 설명 출처, 누락/빈 값, 1,000/20,000자 잘림 여부를 전용 `YoutubeMetadata`에 기록한다. 전체 DOM·og description을 선택하지 않는다. HTML/script 문자열은 텍스트 값으로 취급되고 프론트에서는 React 텍스트 노드로 출력된다.
- `mode=youtube_metadata`는 사용자 소유 YouTube URL 확인 뒤 `SourceSpec.youtube_metadata_only`로 전달되어 player 요청 후 metadata 경로로 바로 끝난다. 자막 트랙 조회/요청은 하지 않는다. 기본 수집은 유효한 자막을 계속 우선하고, 자막 트랙 없음·빈/유효 이벤트 없는 JSON3만 metadata로 전환한다. private/restricted/playback 실패, player/제목 부재, 부적합 설명 형식과 안전하지 않은 timedtext 경로는 실패한다.
- 전용 `MetadataClassification`은 `source_scope=youtube_metadata`와 `title_only`/`title_description`, 원 메타데이터, 일치 근거를 요구하며 summary나 최소 태그 개수를 강제하지 않는다. 근거는 제목/설명에서 실제로 일치한 부분 문자열이다. 일치가 없으면 `other`와 빈 태그다. 규칙 분류임을 classifier 값과 한국어 UI 문구에 표시한다.
- 기존 HttpSourceFetcher 정책을 재사용해 URL 검증, 공인 IP DNS pinning, redirect 재검증, deadline 및 응답 크기 제한이 유지된다. 명시적 모드 진입 전 소유권과 YouTube URL을 확인하고 기존 활성 잡 잠금, idempotency 경로, confirm/approve/reject 흐름을 재사용한다. default 재분석 요청 해시 입력은 변경되지 않았다.
- metadata 결과는 artifact/analysis run에 저장된다. 승인 시 metadata 스키마를 기존 AI tag/detail layer에 적용하며 summary 행을 만들지 않는다. 실패 복구는 보관된 prior AI/state 경로를 사용하고, 기존 snapshot·user summary/tag/detail patch·hidden AI·메모 기록은 별도 보존 경로에 남는다. 사용자 요약이 있으면 표시 우선순위를 유지한다.
- 인덱스는 승인 metadata를 조회해 제목·설명, 적용된 분류와 사용자 층을 임시 projection으로 사용한다. 과거 페이지 snapshot과 AI summary는 projection에서 제외되고 projection 자체는 원문 DB에 저장되지 않는다. 동일한 indexer 경로에 reload/rebuild와 변경 반영이 연결되어 있다. 검색 순위 구현은 건드리지 않았다.
- API의 `mode`와 metadata 후보/분석 DTO가 분리되어 있다. UI는 제목·설명 동작, 자막을 쓰지 않는 범위, 실제 설명/출처, 근거, 접힌 설명과 제안 승인/거절을 한국어로 제공한다. 사용자 입력 및 수집한 HTML 문자열을 HTML로 해석하는 경로는 확인하지 못했다.

## 독립 실행

- 구현 워크트리 cwd에서 `PYTHONPATH=src /Users/minjun/orca/workspaces/dc2/phase-4-review-youtube-metadata-loop1/.venv/bin/python -m pytest -q tests/unit/test_youtube_metadata.py tests/integration/test_youtube_metadata.py` — **24 passed, skip 없음**. Python 의존성은 기존 검수 워크트리 venv에서 사용했고, cwd와 import 대상은 구현 워크트리로 고정했다. 포함된 공개 캡처 재생은 `var/metadata-validation`의 기존 artifact와 격리 SQLite만 대상으로 했다.
- `PYTHONPATH=src uv run --offline pytest -q tests/unit/test_youtube_source_repair.py tests/integration/test_youtube_legacy_notice.py tests/integration/test_ingest_pipeline.py tests/integration/test_save_api.py tests/integration/test_indexing.py` — **67 passed**.
- 구현 워크트리 cwd에서 `npm --prefix frontend run check` — **8 test files, 29 tests passed**, typecheck 통과. `npm --prefix frontend run build` — **123 modules, 성공**. phase-2-frontend-integration의 기존 `node_modules`를 그대로 사용했다. lint warning은 기존 6개다.
- 실행 중인 5177/8791 서버, 원본 프론트엔드, 8780, 실DB 및 실제 항목은 접속·변경하지 않았다. 캡처 재생 테스트는 기존 격리자료/SQLite에 대해 실행했다.

## 점수 근거 및 제한

정확성은 명시적 metadata 범위·기존 정상 자막 경로·승인 후 사용자층/색인 동작과 실제 캡처 기반 통합 테스트까지 확인해 39점이다. 안전성은 수집기 기존 SSRF/redirect/time/size 보호 재사용과 HTML 텍스트 안전성을 확인해 30점이다. 유지보수성은 전용 스키마·분류기와 회귀 테스트를 확인해 28점이다. 그 외 감점할 실제 결함은 발견하지 못했다.

이 검수는 공개 제목/설명에 대한 초기 로컬 규칙 분류 경로의 계약과 안전성을 대상으로 한다. 전체 도메인에서의 AI 모델 분류 품질 보증이나 분류 recall/precision 보증은 아니다.

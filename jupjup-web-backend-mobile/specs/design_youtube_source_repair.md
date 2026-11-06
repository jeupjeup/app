# YouTube 원문 수집 수정

- YouTube URL은 watch HTML/제목을 본문으로 쓰지 않는다. 공개 watch 응답의 player caption track을 찾고 동일한 HTTP SSRF/IP 고정·redirect·시간·용량 보호로 JSON3 자막을 요청한다. 로그인/쿠키/우회/외부 전사 없음.
- 자막 미제공·접근 차단·빈 자막·HTML만 확보는 SOURCE_TEXT_UNAVAILABLE 영구 실패. 분석/후보 생성 전에 중단한다. 직접 입력과 기존 VTT/SRT/JSON 자막은 유지한다. 일반 HTML의 제목/메뉴/약관-only도 실패한다.
- snapshot 재분석도 잘못된 YouTube HTML의 재사용을 차단한다. mock은 화면에서 시험용 고정 결과임을 명시하고 실제 요약처럼 노출하지 않는다.
- 실패 화면에서 원본 링크를 유지하며 텍스트/자막 직접 저장을 제공한다. 기존 항목을 삭제하거나 덮어쓰지 않는다.
- 대상 한 항목 복구는 dry-run→DB backup→fingerprint 확인→한 트랜잭션으로 AI 파생 결과만 정리. 사용자 수정/원문/다른 항목 보존. 서버 재시작 없음.
- 인수: 부적합 원문에서 summary/tags/candidate 0, 정상 입력 회귀, 악성 caption/redirect/과대응답 거부, 실제 승인 URL의 성공/실패 사실대로 기록, API 회귀와 frontend check/build 통과. 로컬 모델 기본값/품질 기준 유지.

## 기존 watch snapshot의 읽기 안내 (2026-11-05)

- DB 복구 대신 `ContentQueryService.get.analysis.source_text_available: bool`, `source_text_reason: legacy_watch_snapshot | missing_snapshot | empty_snapshot | null`을 파생한다. `ContentAnalysis` DTO와 프론트 계약에 명시한다. 과거 `analysis_rejected`/최신 job 오류 유무와 무관하게 판정한다.
- `is_legacy_watch_snapshot`/`has_transcript_evidence`를 기존 chunk 차단과 상세·목록 읽기가 공유한다. YouTube URL + `raw_meta.source=http` + 자막 증거 없음이 대상이다. 브라우저의 원문 문자열 매칭이나 새로운 메타데이터 공개는 없다.
- 해당 snapshot의 AI 요약·대표/세부 태그·대기 후보는 상세 유효 결과에서 제외한다. 목록도 동일한 공통 투영으로 AI 요약·대표 태그를 제외한다. 사용자 요약·태그와 세부 태그 user patch는 보존하며 세부 태그는 빈 schema 바탕에 patch만 적용한다. DB의 AI/사용자 레이어·snapshot·revision·status는 바꾸지 않는다.
- 화면은 ‘영상 본문 확보 실패’, 사용자 수정 보존, 직접 자막/텍스트의 별도 저장 입력을 즉시 제공하고 원문 재분석을 비활성화한다. 페이지 snapshot은 접어서 열람한다. 정상 자막/직접 텍스트의 기존 표시·재분석은 유지한다.
- 목록 필터·정렬·페이지 경계와 검색 순위/검색 응답은 변경하지 않는다. 적용은 PM 병합과 API worker 재시작 이후이며, 데이터 정리·재분석은 필요 없다.

# YouTube 제목·설명 기반 분류

공개 watch player의 videoDetails.title/shortDescription만 사용한다. 전체 DOM/푸터와 og:description은 채택하지 않는다. 기존 HTTP 공개 IP 고정, 매 redirect 검증, 시간·용량 제한을 유지한다. 제목 1,000자/설명 20,000자 상한과 잘림 표시, 원래 유니코드·줄바꿈·링크를 일반 텍스트로 보존한다.

정상 자막은 기존 분석 경로를 유지한다. 자막 없음/빈 JSON3 자막만 youtube_metadata로 전환한다. 차단/비공개/플레이어 없음/위험한 자막 URL은 실패한다. 설명이 없으면 title_only로 범위를 좁힌다. 규칙 일치가 없으면 other와 빈 태그다. 별도 MetadataClassification 스키마는 요약과 최소 태그 수를 요구하지 않는다. 근거는 제목/설명 중 실제 일치 문자열과 위치를 제공한다. 외부 LLM 없이 로컬 결정 규칙을 사용하며 기존 분석기·품질 기준은 변경하지 않는다.

기존 POST :reanalyze에 mode=youtube_metadata를 추가한다. 사용자 소유 YouTube URL만 source_spec.youtube_metadata_only=true로 자막 요청 없는 새 공개 수집을 예약하고 기존 idempotency/활성 잡 잠금/confirm을 재사용한다. 수집한 metadata는 job artifact와 analysis_runs에 저장하며 기존 snapshot/사용자 층/메모를 변경하지 않는다. 확정 때 AI 분류 태그·세부 태그만 적용하고 요약은 만들지 않는다. 거절·실패는 기존 AI 층과 상태 복구 규칙을 따른다. metadata 확정 후 인덱스 입력만 제목·실제설명·확정분류·사용자 층으로 투영하여 embedding/index/reload/사용자 수정 때 일관되게 반영한다. 과거 watch snapshot/AI 요약은 이 투영에서 제외하며 투영을 DB 원문으로 저장하지 않는다. 검색 순위는 범위 밖이다.

상세 응답 analysis.metadata와 전용 candidate에 제목·실제 설명·출처·범위·자막 미확보 사유·잘림·분류 근거를 제공한다. 과거 garbage 요약은 계속 가리고, metadata 확정 태그와 사용자 층을 표시한다. 화면은 기존 레이아웃에 명시적 제목·설명 가져오기/분류 버튼과 접힌 설명을 추가한다. 영상 전체 요약으로 표시하지 않는다.

검증은 격리 DB와 모의 HTTP로 보안·스키마·회귀·승인·경합·실패 복구를 확인하고, 승인 URL의 공개 읽기 결과를 격리 DB에서 끝까지 실행한다. 실DB/기존 서버/다른 워크트리는 변경하지 않는다.

# 실제 로컬 LLM 저장

최신 사용자 승인에 따라 live/local 서비스는 기존 LLMContentAnalyzer와 검증·제한 재시도를 사용한다. mock 평가 기본값은 보존한다. 제목·설명은 별도 youtube_metadata 범위로만 입력하며 영상 전체 내용을 추측하지 않는다. 기존 규칙 결과는 읽기 호환하고 새 LLM 결과만 요약·최소 3개 태그를 요구한다. 실패를 mock으로 대체하지 않는다.

새 metadata classifier는 local-metadata-llm-v1, 실제 모델은 analysis_runs.model에 저장한다. 저장·상세·검색은 해당 accepted run의 요약만 허용한다. 사용자 층·원문은 보존한다. enum→고정 한국어 이름 컬렉션 추가는 분석 확정 트랜잭션에서 사용자별 UNIQUE 이름과 멤버십 충돌 무시로 멱등 처리한다. 수동 소속은 삭제하지 않는다. migration/search/query/기준 데이터 변경은 없다.

기존 런타임 두 환경의 패키지 경로를 함께 쓰는 offline 실행 스크립트와 격리 DB 검증을 제공한다. 실서비스 전환은 PM이 수행한다. 모델 품질 기준 통과를 주장하지 않는다.

# Instagram public metadata MVP

## 구현 전 설계 결정

- 기준 커밋: PM `0484955`. frontend는 수정하지 않는다.
- Instagram 전용 URL 정책을 HTTP fetcher의 per-hop policy에 연결한다. HTTPS, 정확한 두 호스트, `/p/{shortcode}/`, `/reel/{shortcode}/`만 허용한다. `/reels/`는 기존 정규화와 호환되는 alias로 보수적으로 처리하며 다른 경로는 거부한다. URL 검증은 일반 URL 정규화 이전에 한다.
- HTMLParser로 공개 OG/표준 metadata만 읽고 script/JSON/body는 분석하지 않는다. 별도 InstagramMetadata 모델을 쓰고 YouTube DTO는 변경하지 않는다.
- metadata만 담은 일반 스냅샷과 기존 AnalysisOutput 저장/검색 경로를 재사용한다. snapshot raw_meta와 analysis_input에 instagram_metadata scope를 남긴다. YouTube salience는 복제하지 않는다.
- LLM 생성/검증 루프를 재사용하되 Instagram 전용 지침과 결정적 발췌 요약/원문 태그/안전 detail 필드 보정을 적용한다. 근거 태그가 기존 최소 3개에 못 미치면 사실을 만들지 않고 분석 실패한다.
- 초기 저장이 범위이며 재분석 모드와 frontend/API DTO 확장은 하지 않는다. 일반 snapshot 재분석에도 저장된 scope를 적용한다.
- 검증은 fixture, fake HTTP/resolver, scripted LLM, 격리 임시 SQLite만 사용한다. 실제 네트워크·실DB·로그인·쿠키·토큰·우회·외부 스크래핑 서비스는 사용하지 않는다.

## 범위와 한계

공개 페이지 metadata만 다룬다. 이미지·영상 프레임·음성 자체 분석이 아니다. Instagram이 metadata를 숨기거나 로그인/private/unavailable shell만 제공하면 영구 실패한다. 제목만 있으면 title-only 제한 분석이다. 원문 내용의 진실 여부나 미디어의 전체 내용은 확인하지 않는다.

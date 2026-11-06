# YouTube metadata focused detail cleanup

- **Current Loop (현재 루프):** 1 / 3
- **Active Worker (활성 워커):** Codex-Primary
- **Worker Output Summary (작업 요약):** 제목+해시태그만 선별된 metadata 경로에서 `detail_tags`를 안전 화이트리스트로 재구성하고, poisoned optional 필드 제거 단위 테스트와 fake 저장 통합 테스트를 추가했다.
- **PM's Note (PM의 한마디):** 일반 분석과 해시태그 없는 음악 metadata 경로는 기존 회귀 테스트 범위에서 그대로 확인했다. 실제 Kanana, 네트워크/API, 실 DB 호출은 하지 않았다.
- **Next Routing (다음 라우팅):** 변경을 커밋해 전달.

## 변경

focused 경로의 `detail_tags`에는 `schema_version`, 보정 category, topics, keywords, exact 원문 entities, 빈 locations, purpose, save_intent만 남긴다. 다른 선택 필드는 제거한다.

## 확인

- `uv run pytest -q tests/unit/test_youtube_salience.py tests/integration/test_live_llm_save.py::test_focused_metadata_save_persists_only_safe_detail_fields` — 통과 (25 tests)
- `uv run ruff check src/jupjup/ingest/youtube_metadata_repair.py tests/unit/test_youtube_salience.py tests/integration/test_live_llm_save.py` — 통과
- `uv run mypy src/jupjup/ingest/youtube_metadata_repair.py` — 통과
- `git diff --check` — 통과
- 테스트 모듈도 인자로 전달한 mypy 실행은 저장소 테스트 코드의 기존 미타입/타입 오류 153건으로 실패했다. 변경 구현 파일만 검사한 결과는 통과.

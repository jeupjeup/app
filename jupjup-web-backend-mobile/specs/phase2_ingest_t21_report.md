# Phase 2 T21 구현 보고서

## 구현 범위

- `src/jupjup/ingest/analyzer.py`
  - `ContentAnalyzer` Protocol과 `AnalysisRunMeta`
  - fixture 기반 `MockAnalyzer`
  - source별 `failure_script` (`truncated_json`, `schema_violation`, `empty`, `max_tokens`, `refusal`, `provider_error`, `ok` 및 별칭)
  - 각 `analyze` 호출마다 스크립트를 처음부터 재생해 단계 재실행 결과가 같도록 보장
  - 모든 mock 응답을 T18 `validate_and_repair`에 연결해 실제 검증·재요청·partial/failed 계약 재사용
  - 경로 탈출을 막는 버전 프롬프트 경로 보조 함수
- `src/jupjup/providers/recording.py`
  - `RecordingLLM`: 주입한 `LLMClient` 응답을 `(model_id, prompt_hash)` 기준 JSONL로 중복 없이 기록
  - `RecordedLLM`: 파일만 읽어 결정적으로 재생하고 미등록 프롬프트는 `LLMCacheMiss`
  - 녹화 파일에는 원문 system/user prompt를 저장하지 않고 해시와 `LLMRawResponse`만 저장
  - 손상 파일, 충돌하는 중복 응답, 읽기·쓰기 실패를 `LLMProviderError`로 명시
- `src/jupjup/providers/vision.py`
  - `ImageInput`, `ImageDescription`, `ImageUnderstander` Protocol
  - 이미지 파일을 열거나 네트워크를 쓰지 않고 전달받은 OCR만 정리하는 `OcrOnlyUnderstander`
  - 해시/경로/default fixture와 OCR fallback을 지원하는 결정적 `MockImageUnderstander`
- `src/jupjup/ingest/prompts/`
  - `analyze_v1.md`, `chunk_notes_v1.md`, `repair_v1.md`
  - 원문과 이전 출력을 신뢰하지 않는 데이터 블록으로 취급하도록 주입 방어 문구와 버전 고정
- 연결 변경
  - `domain/errors.py`: `LLMCacheMiss(LLM_CACHE_MISS)`, `VisionProviderError(VISION_UNAVAILABLE)`
  - `ingest/chunking.py`: PRD 예시의 `failure_script["src_0005"]` 선택을 위해 `ContentMeta.source_id` 선택 필드 추가
  - 패키지 `__init__`에서 T21 공개 계약 export
- `tests/unit/test_ingest_analyzer_providers.py`
  - T21 전용 단위 테스트 7건 추가

실제 Anthropic 호출, `AnthropicLLM`, `LLMContentAnalyzer`, 잡 큐·워커·API(T22 이후)는 구현하지 않았다. 외부 API와 네트워크는 사용하지 않았다. `src/jupjup/search`, `src/jupjup/query`, 기준선, 기존 `data/recordings/*`는 수정하지 않았다.

## 설계 대비 차이와 이유

1. 5.10.8절의 확장 `LLMClient.complete_json(...) -> LLMRawResponse`와 `count_tokens`는 T18에서 이미 `providers/llm.py`에 선반영되어 있었다. 같은 계약을 다시 변경하지 않고 그 인터페이스를 `RecordingLLM`/`RecordedLLM`이 그대로 구현했다.
2. 설계의 `MockAnalyzer(fixtures, failure_script)` 예시는 source id로 스크립트를 선택하지만 T20 `AnalysisInput`에는 source id가 없었다. 검수 완료된 청킹 동작은 바꾸지 않고 `ContentMeta.source_id: str | None`만 추가했다. source id가 없을 때는 `AnalysisInput`의 결정적 SHA-256, `default`, 단일 fixture 순으로 선택한다.
3. `AnalyzerProfile`, `LLMContentAnalyzer`, `ChunkNoteExtractor`, 완전한 `PromptStore`는 T25의 실제 분석기 범위라 구현하지 않았다. T21에서는 필요한 버전 파일과 안전한 `prompt_path`만 두었다.
4. map-reduce `AnalysisInput`은 선택 청크만 보유하고 전체 분석 원문을 보유하지 않는다(T20 검수의 기존 L3). MockAnalyzer는 선택 청크를 순서대로 합친 텍스트를 T18 근거 검증에 사용한다. T21에서 검수 완료된 T20 모델을 크게 바꾸지 않기 위한 선택이며, T22/T25에서 전체 원문을 별도로 전달할 계약이 정해지면 보강해야 한다.
5. OCR이 없을 때 5.10.7절의 `reason=no_text`를 `VisionProviderError.details`로 보존했다. 실제 잡의 최종 `failed(reason=no_text)` 상태 전이는 T22 워커 범위다.

## 테스트 목록

- `failure_script=[truncated_json, schema_violation, ok]`가 T18 검증기에 정확히 같은 순서의 raw 출력을 전달하고 3회째 성공
- 잘못된 mock 출력이 `validate_and_repair` 재요청 경로를 타며 attempts=2
- 동일 입력을 같은 MockAnalyzer로 두 번 실행했을 때 output/meta JSON 바이트 동일
- default fixture와 알 수 없는 failure action 조기 거부
- 새 임시 경로에 LLM 응답 1회 기록, 중복 프롬프트 미중복, prompt hash 확인, recorded 재생
- RecordedLLM 캐시 미스에서 `LLMCacheMiss`와 해당 prompt hash 반환, 손상 녹화본 명시적 실패
- OCR 정리, 빈 OCR `reason=no_text`, mock 이미지 fixture 결정성
- 세 버전 프롬프트 존재, 주입 방어 문구, 프롬프트 경로 탈출 거부

## 직접 실행한 명령과 결과

- `uv run pytest tests/unit/test_ingest_analyzer_providers.py -q`
  - **7 passed**
- `uv run pytest`
  - **753 passed, 3 deselected, 1 warning** (최종 실행 34.28초)
  - warning은 기존 Starlette TestClient의 httpx 비권장 안내다.
- `uv run ruff check src tests`
  - **All checks passed**
- `uv run mypy src`
  - **Success: no issues found in 69 source files**
- `uv build --out-dir <임시 디렉터리>` 후 wheel 목록 검사
  - **PASS** — analyzer/recording/vision 모듈과 세 `.md` 프롬프트가 wheel에 포함됨
- `uv run jupjup eval validate`
  - **PASS** — seeds 200, queries 259(dev 158/test 101), lexicon cases 139
- `uv run jupjup eval run --mode mock --split dev --baseline data/baselines/mock.json`
  - **PASS** — recall@10 0.9620, MRR@10 0.9958, nDCG@10 0.9795, 격리/필터 위반 0
- `uv run jupjup eval run --mode mock --split test --baseline data/baselines/mock.json`
  - **PASS** — recall@10 0.9420, MRR@10 0.9867, nDCG@10 0.9589, 격리/필터 위반 0
- `uv run jupjup eval run --mode recorded --split dev --baseline data/baselines/recorded.json`
  - **PASS** — recall@10 0.9712, MRR@10 1.0000, nDCG@10 0.9860, 격리/필터 위반 0
- `uv run jupjup eval run --mode recorded --split test --baseline data/baselines/recorded.json`
  - **PASS** — recall@10 0.9720, MRR@10 0.9911, nDCG@10 0.9801, 격리/필터 위반 0
- `git diff -- data/recordings src/jupjup/search src/jupjup/query`
  - **출력 없음** — 기존 녹화본과 검색 순위 경로 미변경

평가가 만든 `reports/eval_*`는 기존 ignore 대상이며 커밋하지 않는다. 녹화 단위 테스트는 pytest의 임시 디렉터리에만 새 파일을 썼다.

## 남은 문제

- `LLMContentAnalyzer`, 실제 Anthropic 제공자, map-reduce 맵/리듀스 실행은 T25 범위로 남아 있다.
- 큐·워커가 `VisionProviderError`, `LLMCacheMiss`, `LLMRefusalError`, `AnalysisSchemaError`를 상태 전이로 분류하는 연결은 T22 범위다.
- map-reduce 입력의 전체 원문 부재는 위 설계 차이 4와 같다. 현재 mock 검증은 샘플링된 청크 범위의 근거만 확인한다.
- 골든셋 `review_status`는 기존과 같이 `ai_draft_unreviewed 235`, `needs_human_review 24`, reviewed 0이다. 기술 게이트는 통과하지만 제품 수준 사람 검수 근거와는 분리되어 있다.
- 기본 설치 완료 조건에 따라 embed/rerank optional-extra 테스트 3개는 deselect됐다.

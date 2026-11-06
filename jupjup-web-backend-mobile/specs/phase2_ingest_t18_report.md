# Phase 2 T18 구현 보고서

## 구현 범위

- `src/jupjup/ingest/schemas.py`
  - `AnalysisOutput`, `SaveIntent`, `Evidence` Pydantic 모델
  - `additionalProperties=false`, 필수 필드, 길이·개수·enum 제약을 포함한 LLM용 JSON Schema 생성
  - 기존 `domain/detail_tags.v1.json`을 `DetailTagsV1` 정의로 그대로 재사용
  - 최상위 `save_intent`를 `detail_tags.purpose`와 `detail_tags.save_intent`로 변환하는 결정적 보조 메서드
- `src/jupjup/ingest/validation.py`
  - JSON 파싱 → Pydantic/공유 JSON Schema → 의미 규칙 → evidence 순서의 `AnalysisValidator`
  - 태그 NFKC/해시·공백·이모지 제거, 동의어 정규화, 중복·플랫폼 단독 태그 제거, 7개 절단
  - 원문 또는 별칭에 근거가 없는 엔티티 제거
  - 요약 2~4문장 및 한국어 여부, ISO 639-1 언어 코드, evidence 원문 부분 일치/자모 유사도 검사
  - 자동 수정 내역과 검증 이슈를 보존하는 `RepairOutcome`
  - 주입 가능한 `Callable[[RepairContext | None], LLMRawResponse]` 기반 `validate_and_repair`
  - 스키마 재요청 최대 2회, `max_tokens` 2배 신호 재시도 1회(재요청 횟수와 별도), partial/failed 분기
- `src/jupjup/domain/errors.py`
  - `AnalysisSchemaError(ANALYSIS_SCHEMA_INVALID)`과 `LLMRefusalError(LLM_REFUSED)` 추가
- `tests/unit/test_ingest_validation.py`
  - T18 완료 조건과 정상·결정성 경로 10개 테스트 추가

T19 이후 수집, 추출, 청킹, 분석기, 큐, 워커, 저장, API는 구현하지 않았다. `src/jupjup/search`, `src/jupjup/query`, 기준선, `data/recordings`는 수정하지 않았다. 외부 LLM API도 호출하지 않았다.

## 설계 대비 차이와 이유

1. `detail_tags`를 별도의 중복 Pydantic 계층으로 다시 선언하지 않고 `dict[str, Any]` 필드에 기존 `detail_tags.v1.json` 검증을 연결했다. 6.4절의 파일을 유일한 하위 스키마 정본으로 유지해 도메인 저장 경로와 LLM 출력 경로가 어긋나는 것을 막기 위해서다. 최상위 `AnalysisOutput`은 Pydantic 정본이며, 제공자용 JSON Schema는 모델에서 생성한 뒤 같은 v1 문서를 `$defs/DetailTagsV1`로 참조한다.
2. 5.10.6절은 “confidence 순으로 대표 태그 7개 절단”을 요구하지만 5.10.5절의 `representative_tags`는 confidence가 없는 문자열 배열이다. 존재하지 않는 점수를 추정하지 않고 LLM이 낸 우선순위(입력 순서)를 안정적으로 보존해 앞 7개를 사용한다.
3. 자동 수정 가능한 원시 출력은 엄격한 Pydantic 검증 전에 복사본에서 정규화한다. 그렇지 않으면 태그 8개처럼 Pydantic `maxItems`에서 먼저 거부되는 입력을 `auto_fix` 단계까지 전달할 수 없기 때문이다. 원본 문자열은 변경하지 않으며 수정 이력은 모두 `ValidationIssue`/`repairs`에 남긴다.
4. partial 결과도 가능한 한 `AnalysisOutput` 불변식을 지킨다. 요약은 통과했지만 부가 필드가 실패하면 `save_intent`는 빈 labels/0 confidence, `detail_tags`는 `schema_version=1`, evidence는 근거가 확인된 항목만 남긴다. 대표 태그가 3개 미만이라 스키마 유효 결과를 만들 수 없는 경우에는 요약이 유효해도 `AnalysisSchemaError`로 처리한다. 엄격한 `AnalysisOutput` 스키마의 `minItems=3`과 “실패 필드를 비운다”는 문구가 충돌하기 때문이다.

## 테스트 목록

- 정상 출력 통과, 첫 요청 성공 메타, 반복 실행 결과 결정성
- 생성 JSON Schema의 필수 제약과 공유 `detail_tags`/`save_intent` 포함
- 잘린 JSON 파싱 실패 후 재요청 성공
- `save_intent.labels` enum 밖 값의 재요청
- 대표 태그 8개: NFKC/동의어 정규화 후 입력 우선순위로 7개 절단
- 원문과 별칭에 근거 없는 엔티티 자동 제거
- `stop_reason=max_tokens`: 스키마 재요청과 별도로 1회, `max_tokens_multiplier=2` 전달
- 재요청 2회 소진 + 유효 요약: partial 결과
- 재요청 2회 소진 + 무효 요약: `AnalysisSchemaError`
- Pydantic enum 및 extra 필드 거부

## 직접 실행한 명령과 결과

- `uv run pytest tests/unit/test_ingest_validation.py -q`
  - **10 passed**
- `uv run ruff check src tests`
  - **All checks passed**
- `uv run mypy src`
  - **Success: no issues found in 63 source files**
- `uv run pytest`
  - **656 passed, 3 deselected, 1 warning** (최종 실행 33.22초)
  - warning은 기존 FastAPI TestClient 경로의 Starlette/httpx2 deprecation 안내다.
- `uv run jupjup eval validate`
  - **PASS** — seeds 200, queries 259(dev 158/test 101), lexicon cases 139
- `uv run jupjup eval run --mode mock --split dev`
  - **PASS** — recall@10 0.9620, nDCG@10 0.9795, isolation/filter violations 0
- `uv run jupjup eval run --mode mock --split test`
  - **PASS** — recall@10 0.9420, nDCG@10 0.9589, isolation/filter violations 0
- `uv run jupjup eval run --mode recorded --split dev`
  - **PASS** — recall@10 0.9712, nDCG@10 0.9860, isolation/filter violations 0
- `uv run jupjup eval run --mode recorded --split test`
  - **PASS** — recall@10 0.9720, nDCG@10 0.9801, isolation/filter violations 0
- `jsonschema.Draft202012Validator.check_schema(analysis_output_json_schema())` 및 정상 샘플 검증
  - **PASS**
- 동일 정상 출력을 `AnalysisValidator.validate`로 3회 검증
  - **결과 동일**

평가 실행이 만든 `reports/eval_*.json`, `reports/eval_*.md`는 기존 ignore 대상이며 커밋하지 않는다. 검색 기준선과 녹화 데이터는 바뀌지 않았다.

## 남은 문제

- 골든셋 검증 결과의 `review_status`는 기존과 같이 `ai_draft_unreviewed 235`, `needs_human_review 24`이며 제품 수준 사람 검수 근거와 분리된 기술 게이트다. T18 변경으로 생긴 문제는 아니다.
- 대표 태그 confidence 부재와 partial 시 `minItems=3` 충돌은 위 설계 대비 차이에 기록했다. 후속 설계에서 태그를 `{name, confidence}`로 바꾸거나 partial 전용 스키마를 명시하면 이 예외를 제거할 수 있다.
- 선택 extra가 필요한 embed/rerank 테스트 3개는 기본 설치 완료 조건에 따라 deselect됐다.

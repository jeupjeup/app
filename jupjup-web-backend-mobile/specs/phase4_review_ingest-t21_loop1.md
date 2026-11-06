# Phase 4 최종 검수: 인제스트 T21(Mock 분석기, LLM 녹화/재생, 이미지 인터페이스), Loop 1/3

- **점수:** 92 / 100
- **상태:** PASS
- **항목별:** 정확성 37 / 40, 안전성 28 / 30, 유지보수성 27 / 30
- **루프백 대상:** 없음 (PASS). 아래 중간 2건(M1, M2)은 T22 착수 전이나 T25 실제 분석기 착수 전에 Phase 2에서 정리하기를 권한다. M1은 T25가 녹화본을 처음 만들기 전에 반드시 결정해야 한다.
- **검수 대상:** `phase-4-review-ingest-t21-loop1` HEAD `989bb10` (`feat: implement T21 mock ingest providers`). 비교 기준은 T20 Loop 1 검수 커밋 `b4a5af1`이다.
  - 신규: `src/jupjup/ingest/analyzer.py`(194줄), `src/jupjup/providers/recording.py`(134줄), `src/jupjup/providers/vision.py`(80줄), `src/jupjup/ingest/prompts/{analyze_v1,chunk_notes_v1,repair_v1}.md`, `tests/unit/test_ingest_analyzer_providers.py`(7건)
  - 변경: `domain/errors.py`(`LLMCacheMiss`, `VisionProviderError`), `ingest/chunking.py`(`ContentMeta.source_id` 1줄), 두 패키지 `__init__` export
- **기준 문서:** `specs/prd_and_design.md` 4장 배치(830~840줄), 5.8.1절(893줄), 5.8.4절(974줄), 5.10.2절 I3/I5 행(1277~1279줄), 5.10.6절(재요청, `max_tokens` 2배 재시도), 5.10.7절(이미지), 5.10.8절(1379줄 vision, 1392~1401줄 `ContentAnalyzer`/`MockAnalyzer`, 1416줄 `LLMClient` 확장, 1449줄 추가 에러), 3.5.1절(370줄 `llm.<model_id>.jsonl`), 7.3절(1711줄 의존성, 1724줄 T21 행), 8장 1817줄. `specs/known_issues.md`, 이전 검수 `specs/phase4_review_*.md`(특히 `phase4_review_ingest-t20_loop1.md`). T21 이전 검수 파일은 없다(이번이 첫 루프).
- **채점 정책:** T20 Loop 1과 같은 엄격도로 봤다. 사람 검수 0건은 감점하지 않았다. 범위 밖 항목(T22 이후의 큐·워커·API, T25 `LLMContentAnalyzer`/`AnalyzerProfile`/`PromptStore`, 실제 `AnthropicLLM` 호출)은 "참고"로만 적었다. 구현 보고서 `specs/phase2_ingest_t21_report.md`의 주장은 모두 직접 다시 확인했다.

## 0. 요약

- **T21 완료 조건을 직접 만든 입력으로 모두 재현했다.**
  - **failure_script 순서 재현:** `["truncated_json", "schema_violation", "ok"]`이면 T18 검증기가 받은 raw 출력이 정확히 `[잘린 JSON, "{}", 정상 JSON]` 순서이고, 3회째에 성공한다. 9개 동작(별칭 포함)과 조합 16가지를 모두 돌렸다(1.2절).
  - **RecordedLLM 캐시 미스:** 녹화본에 없는 프롬프트와 다른 `model_id`는 모두 `LLMCacheMiss(LLM_CACHE_MISS)`이고, `details`에 `prompt_hash`가 들어 있다. 조용히 빈 값을 돌려주지 않는다.
  - **결정성:** 같은 분석기로 두 번, 새 분석기로 한 번 실행해도 output/meta JSON이 바이트 단위로 같다. `source_id`가 없을 때의 해시 키도 결정적이다.
  - **T18 연결:** 잘못된 mock 출력이 모두 실제 `validate_and_repair`를 지난다. 재요청 2회 소진 시 `AnalysisSchemaError`, 일부 필드만 실패하면 `partial=True`, `max_tokens`는 재요청 횟수와 별도로 1회 재시도, `refusal`은 재요청 없이 `LLMRefusalError`가 된다.
- **설계 시그니처와 맞다.** `MockAnalyzer(fixtures, failure_script=None)`(1400줄)에 키워드 전용 인자만 더했다. `ContentAnalyzer.analyze(inp) -> tuple[AnalysisOutput, AnalysisRunMeta]`, `ImageInput(path?, ocr_text?)`, `ImageDescription(ocr_text, caption?, objects?, source)`, `ImageUnderstander.describe`, 확장 `LLMClient.complete_json/count_tokens`가 모두 설계와 일치한다.
- **네트워크와 LLM 접근은 0회다.** 소켓 `connect`와 `create_connection`을 막은 상태에서 재현 스크립트가 모두 통과했다. 새 모듈 세 개에 네트워크 import가 없다. 녹화 파일에는 원문 prompt가 들어가지 않는다(해시만 저장).
- **검색 순위는 회귀하지 않았다.** `git diff b4a5af1 HEAD -- src/jupjup/search src/jupjup/query data`는 0줄이다. eval 4종 수치는 T20 Loop 1 검수 값과 소수점 4자리까지 같다.
- **남은 결함은 중간 2건, 낮음 4건이다.**
  - M1: 녹화 키가 `max_tokens`를 무시해서, 설계의 `max_tokens` 2배 재시도를 녹화한 뒤 재생하면 결과가 달라진다.
  - M2: failure_script 9개 동작 중 6개와 소진 분기가 테스트에 없다.
  - L1~L4: fixture 얕은 복사, fixture 누락 시 재시도형 에러, `no_text`의 에러 분류, 재생 시 `count_tokens` 의미 차이.

## 1. 직접 실행한 명령과 결과

### 1.1 정적 검사, 테스트, 평가 (기본 설치 `uv sync` 환경)

| 명령 | 결과 |
|---|---|
| `uv run pytest` | **753 passed, 3 deselected, 1 warning** (34.9s). T20 검수 때의 746에 T21 테스트 7건을 더한 값이다. 경고는 기존 Starlette `httpx` 경고다 |
| `uv run pytest tests/unit/test_ingest_analyzer_providers.py -q` | 7 passed |
| `uv run ruff check src tests` | All checks passed |
| `uv run ruff format --check src/jupjup/ingest src/jupjup/providers tests/unit/test_ingest_analyzer_providers.py` | 18 files formatted. `providers/__init__.py` 1개만 걸린다. 맨 앞 빈 줄 때문인데 `b4a5af1`에도 있던 것이라 감점하지 않았다. 저장소 전체로는 기존 파일 12개가 걸린다(모두 T21 이전부터) |
| `uv run mypy src` | Success: no issues found in 69 source files |
| `uv build` 후 wheel 목록 | `ingest/analyzer.py`, `providers/recording.py`, `providers/vision.py`, `ingest/prompts/*.md` 3개가 포함된다 |
| `uv run jupjup eval validate` | 통과. seeds 200, queries 259(dev 158/test 101), lexicon 139. ai_draft_unreviewed 235 / needs_human_review 24, reviewed 0 (변화 없음) |
| `eval run --mode mock --split dev --baseline data/baselines/mock.json` | PASS, 종료 코드 0: R@10 0.9620, MRR 0.9958, nDCG 0.9795, 격리/필터 위반 0 |
| `eval run --mode mock --split test …` | PASS: R@10 0.9420, MRR 0.9867, nDCG 0.9589, 위반 0 |
| `eval run --mode recorded --split dev --baseline data/baselines/recorded.json` | PASS: R@10 0.9712, MRR 1.0000, nDCG 0.9860, 위반 0 |
| `eval run --mode recorded --split test …` | PASS: R@10 0.9720(하한 0.972와 같은 값, known_issues 5번 그대로), MRR 0.9911, nDCG 0.9801 |
| `git diff b4a5af1 HEAD -- src/jupjup/search src/jupjup/query data \| wc -l` | **0** |
| `grep -nE "socket\|urllib\|http\|requests\|httpx\|subprocess\|anthropic\|openai"` (analyzer.py, recording.py, vision.py) | 없음 |

### 1.2 MockAnalyzer: failure_script와 T18 연결 직접 재현

`uv run python` 스크립트(스크래치 디렉터리)로 실행했다. 소켓을 막았고, T18 검증기를 상속한 스파이로 검증기가 받은 raw 출력을 기록했다. 입력은 `source_id="src_0005"`인 single `AnalysisInput`이다.

| failure_script | 결과 | 검증기가 받은 출력 | 판정 |
|---|---|---|---|
| `[truncated_json, schema_violation, ok]` | 성공, attempts 3, first_pass_ok False | 잘린 JSON → `{}` → 정상 | OK (설계 1401줄 예시) |
| `[]` / `[ok]` | 성공, attempts 1, first_pass_ok True | 정상 | OK |
| `[empty, ok]` / `[invalid_json, empty_response, ok]` | attempts 2 / 3 | `""` → 정상 / 잘린 JSON → `""` → 정상 | OK (별칭 동작) |
| `[schema_violation]×2` | attempts 3. 스크립트가 끝나면 `ok`로 성공 | `{}` → `{}` → 정상 | OK (docstring과 같음) |
| `[schema_violation]×3` | `AnalysisSchemaError`, attempts 3, repair_attempts 2, 이슈 7개 | `{}`×3 | OK (5.10.6절 4번, 재요청 최대 2회) |
| `[max_tokens, ok]` | attempts 2. 잘린 응답은 검증하지 않고 재시도한다 | 정상 1회 | OK (5.10.6절 5번) |
| `[max_tokens, max_tokens, ok]` | attempts 3. 두 번째 잘림은 재시도 없이 검증 실패, 재요청으로 간다 | 잘린 JSON → 정상 | OK |
| `[max_tokens, schema_violation×2, ok]` | attempts 4. 잘림 재시도가 재요청 2회와 별도로 센다 | `{}`, `{}`, 정상 | OK |
| `[max_tokens, schema_violation×3]` | `AnalysisSchemaError`, attempts 4, repair_attempts 2 | `{}`×3 | OK |
| `[refusal]` / `[schema_violation, refusal]` | `LLMRefusalError`, attempts 1 / 2. 재요청하지 않는다 | 없음 / `{}` | OK (5.10.6절 6번) |
| `[provider_error]` / `[schema_violation, provider_error, ok]` | `LLMProviderError`(LLM_UNAVAILABLE) | 없음 / `{}` | OK |
| `[ok, schema_violation]` | attempts 1. 성공 뒤 동작은 쓰지 않는다 | 정상 | OK |
| fixture의 `save_intent`가 잘못된 값, 스크립트 없음 | 성공, attempts 3, `partial=True`, repairs 2 | 정상형 JSON ×3 | OK (요약 통과·필드 실패 → partial) |
| 같은 분석기 2회, 새 분석기 1회 | output·meta `model_dump_json` 모두 같다 | — | OK (결정성) |
| `source_id` 없음, `{"default": …}` fixture와 `{"default": [schema_violation, ok]}` | attempts 2. 해시 키 → default 순으로 고른다 | — | OK |
| fixture 2개, 등록되지 않은 `source_id` | `LLMProviderError`, `details={"fixture_key": "zzz"}` | — | 동작은 OK, 에러 분류는 L2 |
| `failure_script={"a": "ok"}`(리스트 대신 문자열) | `ValueError: 알 수 없는 failure_script 동작: k, o`. 생성 시 거부한다 | — | OK (메시지는 다소 헷갈린다) |
| 생성 후 호출자가 fixture dict 값을 바꿈 | 다음 `analyze` 결과가 바뀐다 | — | **L1** |
| 실제 `chunk_for_analysis`로 만든 map_reduce 입력(문단 400개, 10청크) + `[truncated_json, ok]` | 성공, attempts 2, input_tokens 61,214, 0.005s | — | OK (근거 검증 범위는 참고 R2) |

### 1.3 RecordingLLM / RecordedLLM 직접 재현

| 사례 | 결과 | 판정 |
|---|---|---|
| 없는 하위 디렉터리 경로에 녹화 | 디렉터리를 만들고 1행을 쓴다. 행은 `format_version`, `model_id`, `prompt_hash`, `response`이고, 원문 prompt(`"비밀"`)는 파일에 없다 | OK |
| 같은 프롬프트 반복과 다시 연 RecordingLLM | 1행만 남는다(파일에서 `_seen`을 다시 읽는다) | OK |
| 스레드 200개, 서로 다른 프롬프트 10개 | 정확히 10행 | OK (잠금 동작) |
| 미등록 프롬프트 재생 | `LLMCacheMiss`, `code=LLM_CACHE_MISS`, `details={model_id, prompt_hash}`. `ProviderError`이지만 `LLMProviderError`는 아니다 | OK (`EmbeddingCacheMiss`와 같은 계층) |
| `RecordedLLM(store, "m2")`(다른 모델) | `LLMCacheMiss` | OK |
| 파일 없음 / 필드 누락 / JSON 아님 | `LLMProviderError`, `details`에 path와 line | OK |
| 같은 키에 서로 다른 응답 2행 / 같은 응답 2행 | 충돌은 line 2로 거부한다 / 같은 응답 중복은 허용한다 | OK |
| 재생 응답을 호출자가 바꿈 | 다음 재생에 영향 없다(`model_copy(deep=True)`) | OK |
| 읽기 전용 디렉터리에 녹화 | `LLMProviderError` | OK |
| 내부 LLM이 예외를 던짐 | 파일을 만들지 않는다 | OK |
| **같은 system/user로 `max_tokens=4000`(잘림)과 `8000`(정상)을 녹화한 뒤 `max_tokens=8000`으로 재생** | 녹화는 1행(잘린 응답)뿐이다. 재생은 `stop_reason="max_tokens"`인 잘린 응답을 돌려준다. live 실행은 `end_turn`이었다 | **M1** |
| 같은 프롬프트를 다른 `schema`로 재생 | 다른 스키마로 녹화된 텍스트를 그대로 돌려준다 | M1에 포함 |
| `count_tokens` 재생 | 녹화된 응답의 `input_tokens`(5)를 돌려준다. live `count_tokens`는 42였다. 미등록이면 `None`이다 | **L4** |
| `prompt_hash("a\x00b","c") == prompt_hash("a","b\x00c")` | True (T18 `llm.py:42`의 구분자 모호성) | 참고 R3 (스냅샷 정리가 NUL을 지워 정상 경로에서는 생기지 않는다) |

### 1.4 이미지 인터페이스와 프롬프트

| 사례 | 결과 | 판정 |
|---|---|---|
| `"  영수증\r\n\r\n\r\n합계  12,000원​\x00 "` | `"영수증\n\n합계 12,000원"` (T19 `tidy_snapshot_text` 재사용) | OK |
| OCR `""`, 공백·탭만, ZWSP만 | 모두 `VisionProviderError(VISION_UNAVAILABLE)`, `details={"reason": "no_text"}` | OK (5.10.7절). 에러 분류는 L3 |
| `ImageInput()` | ValidationError. path와 ocr_text가 모두 없으면 거부한다 | OK |
| `ImageInput(path="/etc/passwd")`만 | 파일을 열지 않고 `no_text` | OK (안전) |
| `MockImageUnderstander`: 해시 → 경로 → default → OCR 대체 순서, 반복 호출 | 결정적, 순서 맞음 | OK |
| 잘못된 mock fixture(`{"bad": 1}`) | `describe` 시점에 pydantic ValidationError가 난다(VisionProviderError가 아님) | L1에 포함 |
| `prompt_path`: `analyze_v1`, `repair_v1`, `chunk_notes_v1` / `../x`, `a/b`, `""`, `a.b` | 세 파일 존재 / 모두 거부 | OK |
| 세 프롬프트 내용 | `<source_document>`, `<previous_output>`를 신뢰하지 않는 데이터로 다루라는 문구와 요약 2~4문장 한국어 지시가 있다 | OK (5.10.6절 7번) |

### 1.5 CLI 회귀·경계값

`rm -f var/review.db && uv run jupjup seed load --db var/review.db`: 200줄, 적재 200, 인덱싱 200(u_alice 160, u_bob 30, u_carol 10). 검색은 `--db var/review.db --now 2026-10-15T12:00+09:00 --json`이고, `JUPJUP_MODE=mock`과 `recorded`로 각각 실행했다.

| 사례 | mock | recorded | 판정 |
|---|---|---|---|
| `성수 카페` (bob) | 2건 `c_bob_0025`, `c_bob_0026`, 완화 없음 | `EMBEDDING_CACHE_MISS` (녹화본 밖 질의, 기존 동작) | OK |
| `성수 카페` (carol, 사용자 격리) | 1건 `c_carol_0009`(본인 것) | 캐시 미스 | OK |
| `성슈 카페` (오타) | 같은 2건 | 캐시 미스 | OK |
| 빈 문자열 / 201자 | `[INVALID_QUERY] 질의는 1~200자여야 해요.` | 같음 | OK |
| `!!!@@` (특수문자) | `[INVALID_QUERY] 검색할 단어가 없어요.` | 같음 | OK |
| `지난주 유튜브` (필터 전용) | 1건 `c_alice_0043` | 같음 | OK |
| `경주 맛집 인스타` (과소 완화 회귀) | `c_alice_0153`, `platform_filter_dropped` | 같음 | OK |
| `하체 운동 유튜브` | 1위 `c_alice_0040`, `platform_filter_dropped` | 같음 | OK |
| `다리 운동 영상` (known_issues 4) | 1위 `c_alice_0040`, 완화 없음 | 같음 | OK |
| `경주 맛집 카톡 논문` (이중 완화 기록) | `platform_filter_dropped`, `content_type_filter_dropped` | 같음 | OK |
| `python 강의 영상` (영어 혼합) | 4건, 1위 `c_alice_0056` | 캐시 미스 | OK |
| `화성 기지 건설 계획` (없는 대상, 과잉 완화 확인) | 0건, 완화 없음 | 캐시 미스 | OK |
| `--platform instagram "경주 맛집"` (요청 잠금) | 0건, 완화 없음. 잠근 필터를 풀지 않는다 | 같음 | OK |
| `--platform kakao` (잘못된 필터 값) | `[INVALID_FILTER] 필터 값이 올바르지 않아요.` | 같음 | OK |
| `--user u_nobody` | 저장물이 없다는 안내 뒤 빈 결과 | 같음 | OK |

T21은 검색 경로를 건드리지 않았다(diff 0줄). 위 결과는 T20 Loop 1 검수 표와 같다.

## 2. 피드백 (심각도 순)

### M1. 중간: 녹화 키가 `max_tokens`(와 schema, effort)를 무시해서, 잘림 재시도를 녹화한 뒤 재생하면 결과가 달라진다 — `src/jupjup/providers/recording.py:18-19`, `:79-83`, `:122-124`

- **현상:** `RecordingLLM`과 `RecordedLLM`은 `(model_id, prompt_hash(system, user))`만 키로 쓴다. `complete_json`의 `max_tokens`, `effort`, `schema`는 키에 들어가지 않는다. 재생 쪽은 `del schema, timeout_s, max_tokens, effort`로 버린다. 테스트 `tests/unit/test_ingest_analyzer_providers.py:141-147`도 `max_tokens=123, effort="low"` 호출과 기본값 호출이 1행으로 합쳐지는 것을 기대값으로 고정했다.
- **설계와 충돌하는 지점:** 5.10.6절 5번은 "`stop_reason == "max_tokens"` → `max_tokens`를 2배로 올려 1회 재시도"다. T18 `validate_and_repair`도 `RepairContext(reason="max_tokens", max_tokens_multiplier=2)`로 이 재시도를 요청한다(`validation.py:440-451`). 실제 분석기(T25)가 같은 프롬프트에 `max_tokens`만 키워 다시 보내면 두 호출은 같은 키다.
- **재현:** live 대역이 `max_tokens<8000`이면 잘린 응답, `8000`이면 정상 응답을 낸다. `RecordingLLM`으로 4000 호출 뒤 8000 호출을 한다. 녹화는 잘린 응답 1행뿐이다. 이어서 `RecordedLLM`으로 `max_tokens=8000` 재생을 하면 `stop_reason="max_tokens"`가 돌아온다(1.3절).
- **영향:**
  - 재생 경로에서 다시 잘림 → 검증 실패 → 재요청 프롬프트가 생긴다. 이 프롬프트는 녹화된 적이 없으므로 `LLMCacheMiss`가 난다. 같은 실행에서 녹화한 녹화본으로 그 실행을 재현할 수 없다.
  - 3.5절 recorded 하네스(T25)의 "녹화본으로 결정적 재평가" 전제가 깨진다. 녹화 시점에는 성공한 문서가 재생에서는 실패·partial로 바뀐다.
  - 같은 프롬프트를 다른 출력 스키마로 부르는 경우(예: chunk notes와 analyze가 우연히 같은 user 블록)에도 다른 스키마의 응답을 돌려준다.
- **개선 (택1, T25 전에 결정):**
  1. 키에 요청 파라미터를 넣는다. 예: `request_hash = sha256(json.dumps({"system", "user", "schema": schema.__name__ 또는 JSON Schema 해시, "max_tokens", "effort"}))`. 행에 `max_tokens`, `effort`, `schema_name`도 남긴다. 기존 녹화본이 없으므로 지금은 형식만 바꾸면 된다(`_FORMAT_VERSION=2`).
  2. 또는 "잘림 재시도는 반드시 user prompt에 표지를 넣어 해시가 달라진다"는 계약을 `LLMClient`/`RecordingLLM` docstring과 5.10.8절에 적고, 이를 어기면 실패하는 테스트를 둔다. 이 경우에도 `max_tokens`와 `effort`를 행에 기록하고, 재생 때 값이 다르면 `LLMCacheMiss`로 처리하는 편이 안전하다.
  - 어느 쪽이든 회귀 테스트를 둔다: "같은 system/user, 다른 max_tokens를 녹화한 뒤 재생하면 각자의 응답(또는 명시적 미스)이 나온다."

### M2. 중간: failure_script 9개 동작 중 6개와 소진·거절 분기가 테스트에 없다 — `tests/unit/test_ingest_analyzer_providers.py:58-102`

- **현상:** MockAnalyzer 테스트는 `truncated_json`, `schema_violation`, `ok`와 알 수 없는 동작 거부만 다룬다. `empty`/`empty_response`, `invalid_json`, `max_tokens`, `refusal`, `provider_error`에는 테스트가 없다. 다음 분기도 없다.
  - 재요청 2회 소진 → `AnalysisSchemaError`
  - 소진 → `partial=True`
  - `max_tokens` 재시도가 재요청 횟수와 따로 세어지는지
  - map_reduce 입력
  - `source_id` 없는 해시 키 선택
  - fixture 누락
- **근거:** 8장 1817줄은 "MockAnalyzer의 `failure_script`로 모든 실패 경로를 테스트한다"이다. 1.2절에서 직접 돌려 보니 동작은 모두 맞다. 하지만 `_response`(`analyzer.py:159-186`)의 분기 대부분이 회귀 테스트로 보호되지 않는다. T22 워커가 이 동작을 상태 전이의 근거로 쓰므로, 회귀가 생기면 T22 테스트가 엉뚱한 곳에서 깨진다.
- **녹화 쪽 빈틈:** 충돌 중복 행 거부, 쓰기 실패, 다른 `model_id` 미스, 스레드 동시 기록에도 테스트가 없다(1.3절에서 직접 확인했다).
- **개선:** 1.2절 표의 각 행을 `pytest.mark.parametrize`로 옮긴다. 기대값은 (결과 타입, attempts, partial, 검증기가 받은 raw 순서)다. 녹화 쪽은 충돌 행과 동시 기록 테스트 2건을 추가한다.

### L1. 낮음: fixture를 얕게 복사하고, 잘못된 fixture를 늦게 발견한다 — `src/jupjup/ingest/analyzer.py:76`, `src/jupjup/providers/vision.py:63`, `:75-79`

- `MockAnalyzer`의 `self._fixtures = dict(fixtures)`는 얕은 복사다. 호출자가 생성 후 fixture 안의 dict를 바꾸면 다음 `analyze` 결과가 바뀐다(1.2절 재현). "같은 입력이면 같은 결과"라는 T21 결정성 보장이 호출자 행동에 기대게 된다.
- `MockImageUnderstander`는 Mapping fixture를 `describe` 때 검증한다. 잘못된 값은 pydantic `ValidationError`로 새어 나가고, `ImageUnderstander` 계약의 `VisionProviderError`가 아니다.
- **개선:** 생성 시 `_fixture_text`로 미리 직렬화한 문자열(불변)을 저장한다. 이미지 fixture도 생성 시 `ImageDescription.model_validate`로 바꿔 둔다. 그러면 오류가 생성 시점에 드러나고 이후 변경에도 영향받지 않는다.

### L2. 낮음: fixture 누락을 재시도형 `LLMProviderError`로 낸다 — `src/jupjup/ingest/analyzer.py:90-96`

- 5.10.2절 I5 행에서 `LLMProviderError`는 "재시도"다. fixture 누락은 설정·테스트 데이터 오류라 다시 해도 결과가 같다. T22 워커가 그대로 분류하면 백오프 재시도를 끝까지 반복한 뒤에야 실패한다.
- **개선:** `ValueError`나 `ContentValidationError` 같은 영구 오류로 바꾼다. 또는 생성 시 `failure_script` 키가 fixture로 풀리는지 미리 검증한다. 최소한 T22 분류표에 이 경우를 적는다.

### L3. 낮음: `no_text`를 재시도형 `VisionProviderError`로만 표현한다 — `src/jupjup/providers/vision.py:53-56`

- 5.10.2절 I3 행은 `VisionProviderError`를 "재시도"로 정의한다. 그런데 5.10.7절의 빈 OCR은 영구 실패 `failed(reason=no_text)`다. 지금은 `details["reason"]`에만 구분이 있어서, T22가 코드(`VISION_UNAVAILABLE`)만 보고 분류하면 결정적으로 실패할 잡을 재시도한다. 보고서 5번에서 인지한 사항이라 1점만 감점했다.
- **개선:** 영구 실패용 하위 클래스(예: `VisionNoTextError`, code `VISION_NO_TEXT`)를 두거나, `retryable=False` 속성을 둔다. T22 브리프에 "`details.reason == "no_text"`는 비재시도"라고 명시해도 된다.

### L4. 낮음: 재생 시 `count_tokens`의 의미가 녹화 시와 다르다 — `src/jupjup/providers/recording.py:99-100`, `:132-134`

- 녹화 중 `count_tokens`는 live 값을 그대로 넘기고 아무것도 기록하지 않는다. 재생 중에는 같은 프롬프트로 녹화된 `complete_json` 응답의 `input_tokens`를 돌려주고, 없으면 `None`이다. 1.3절에서 live 42, 재생 5로 달랐다. 실제 API에서도 count 결과와 usage 값은 다를 수 있다. 더 중요하게, `complete_json` 전에 count로 경로를 정하는 호출(예: single/map_reduce 판단, 예산 검사)은 재생에서 `None`을 받아 다른 경로를 탈 수 있다.
- **개선:** `count_tokens` 결과도 `(model_id, prompt_hash, "count")` 행으로 녹화하고, 재생 시 없으면 `LLMCacheMiss`로 처리한다. 또는 "재생 모드의 `count_tokens`는 항상 `None`"으로 고정하고 docstring에 적는다. 어느 쪽이든 녹화·재생 간 분기 차이가 없어야 한다.

### 참고 (감점 없음)

- **R1. 범위 밖으로 남긴 항목:** `AnalyzerProfile`, `LLMContentAnalyzer`, `PromptStore`, `ChunkNoteExtractor`는 5.10.8절에서 `analyzer.py`에 배치됐지만 T21 행(1724줄)에 없고 T25 범위다. 보고서 3번에 적혀 있어 감점하지 않았다. `AnalysisRunMeta`가 설계의 `tokens`를 `input_tokens`/`output_tokens`로 나누고 `first_pass_ok`/`partial`/`repairs`를 더한 것은 `analysis_runs` 기록에 필요한 범위 안이다.
- **R2. map_reduce 근거 검증 범위:** MockAnalyzer는 샘플링된 청크를 이어 붙인 텍스트로 근거를 검증한다(`analyzer.py:150-156`). T20 Loop 1의 L3(전체 원문 부재)와 같은 사항이고, 보고서 4번에서 인지했다.
- **R3. `prompt_hash` 구분자 모호성:** `system + "\x00" + user`는 NUL이 들어간 입력끼리 충돌할 수 있다(`llm.py:42`, T18 코드). `tidy_snapshot_text`가 제어 문자를 지우고 system 프롬프트는 고정 템플릿이라 정상 경로에서는 생기지 않는다. M1을 고치면서 키를 JSON 직렬화 기반으로 바꾸면 함께 사라진다.
- **R4. 프롬프트 치환:** `analyze_v1.md`/`repair_v1.md`의 `{{source_document}}` 같은 자리표시자를 T25에서 순차 `str.replace`로 채우면, 원문 안의 `{{content_metadata}}` 문자열이 다시 치환될 수 있다. T25 `PromptStore`는 한 번에 치환하거나(`string.Template`/정규식 단일 패스) 원문을 마지막에 넣기를 권한다.
- **R5. 포맷:** `src/jupjup/providers/__init__.py` 맨 앞 빈 줄은 T21 이전부터 있었다. T21이 이 파일을 고칠 때 함께 정리하면 좋다.

## 3. 채점 근거

| 항목 | 점수 | 감점 사유 |
|---|---|---|
| 정확성 | 37 / 40 | M1(-2): 녹화·재생 키가 설계의 잘림 재시도와 맞지 않아 재현성이 깨진다. 설계 문구(prompt_hash 기반)는 따랐으므로 -2로 제한했다. L4(-1): 재생 시 `count_tokens` 의미가 다르다. T21 완료 조건 두 가지와 결정성, T18 연결은 모두 직접 재현으로 확인했다 |
| 안전성 | 28 / 30 | L2(-1): fixture 누락의 에러 분류. L3(-1): `no_text` 영구 실패를 재시도형 에러로만 표현. 네트워크 0회, 원문 prompt 미저장, 경로 탈출 거부, 손상·충돌 녹화본의 명시적 실패, 동시 기록 잠금은 모두 확인했다 |
| 유지보수성 | 27 / 30 | M2(-2): 실패 동작 6종과 소진·거절 분기, 녹화 충돌에 회귀 테스트가 없다. L1(-1): fixture 얕은 복사와 늦은 검증. 모듈 배치는 4장과 일치하고, T18 검증기를 재사용해 중복이 없다. docstring과 보고서가 정확하다 |
| **합계** | **92 / 100** | **PASS** (90 이상) |

## 4. 다음 단계 권고

- PASS이므로 T21을 PM 브랜치에 병합해도 된다.
- T22 브리프에 넣을 것:
  - L2: fixture 누락은 영구 오류로 다룬다.
  - L3: `VISION_UNAVAILABLE` 중 `details.reason == "no_text"`는 재시도하지 않는다.
  - `LLMCacheMiss`는 `LLMProviderError`가 아니므로 별도로 분류한다(recorded 모드에서는 영구 실패).
- **T25 착수 전 필수:** M1의 녹화 키 결정. 녹화본이 아직 한 줄도 없을 때 형식을 바꾸는 것이 가장 싸다.
- M2 테스트 보강과 L1은 T22 첫 루프에 함께 넣어도 된다(기능 변경 없음).

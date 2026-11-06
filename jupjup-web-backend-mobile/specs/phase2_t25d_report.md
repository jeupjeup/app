# Phase 2 T25d 로컬 LLM 제공자와 설정 리포트

- 작성: Codex-Primary 역할. 이 세션은 Claude(Opus 5.5)가 같은 지침(`.claude/agents/codex-primary.md`)으로 수행했다
- 기준일: 2026-11-02, 워크트리 `phase-2-t25d-local-provider`, 기준 커밋 `9dc0ddc` (PM)
- 설계: `specs/design_local_analyzer.md` 10.1절 T25d, 3절, 5절, 6.2·6.3·6.7·6.8절, 7.2절, 11절, 14절
- 입력: `specs/phase2_t25b_spike_report.md`(모델 블록, 기본값), `specs/phase4_review_t25b_loop1.md`(M1, L1~L4)

## 0. 결론

T25d 완료 조건(10.1절 표)을 모두 구현하고 테스트로 고정했다. 기본 설치 게이트(pytest, ruff, mypy), 검색 eval 4종, 인제스트
mock 3종이 통과하고 수치는 기준과 같다. 인제스트 mock 리포트 6개 파일은 두 번 실행끼리, 그리고 **변경 전 코드(HEAD)와도
바이트 동일**하다. `src/jupjup/search`, `src/jupjup/query`, `data/recordings`, `data/baselines`, `data/golden` diff는 0줄이다.

실제 모델 확인: 이번 0.3.36 소스 빌드 환경에서 `LlamaCppLLM`이 Kanana-1.5-2.1B·Qwen3-4B-2507 dev 3건씩을 T25b 스파이크 패치 문법
출력과 **바이트 동일하게** 재현했고, `count_tokens`가 실제 `prompt_tokens`와 6건 모두 같았다 (5.3절).

착수 전 정리(M1·L1~L4)를 먼저 했다. 설치 경로는 **`llama-cpp-python==0.3.36` PyPI sdist 소스 빌드**로 정했다 (1절).

## 1. 착수 전 정리 (T25b 검수 M1, L1~L4)

| 항목 | 처리 |
|---|---|
| **M1** Metal wheel 인덱스 근거 오류 | 인덱스의 0.3.30~0.3.36 arm64 wheel을 모두 받아 `zipfile`로 멤버마다 읽었다. **0.3.31~0.3.36 손상**(0.3.36 54개, 0.3.35 53개, 0.3.34 1개, 0.3.33 55개, 0.3.32 55개, 0.3.31 52개 멤버 CRC 오류), **0.3.30 정상**. PyPI JSON API로 0.3.36은 sdist 하나뿐(sha256 `832db069…1a2e`, 스파이크 기록과 같음)임을 확인했다. 스파이크 보고서 2절 표를 정정하고 2.1절(wheel 무결성 표, 결정, 근거 4개, 다시 볼 조건)을 더했다. 5절 1·2번을 고쳤다 |
| M1 설치 경로 결정 | **0.3.36 소스 빌드 유지.** (1) T25b 측정·검수 재현이 모두 이 빌드다. 0.3.30으로 바꾸면 6개 후보를 다시 재야 하고 출력 동일성 근거가 없다. (2) 최근 6개 릴리스 중 5개 wheel이 손상된 인덱스는 믿기 어렵다. PyPI sdist는 `uv.lock`에 sha256이 고정된다. (3) 빌드 부담이 작다 (CLT만, uv 캐시 재사용). (4) `char` 규칙 결함은 0.3.36 그대로라 `json_grammar`가 고친다. 이 빌드로 스파이크 출력 바이트 동일 재현을 확인했다. `models doctor`가 WHEEL 태그로 빌드 방식을 구분해 보여 준다(소스 빌드 `py3-none-macosx_26_0_arm64`, 인덱스 wheel `…macosx_11_0_arm64`) |
| L1 스파이크 스크립트 ruff | `uv run ruff check scripts` → All checks passed. `build_synthetic_dev.py`는 긴 문자열을 인접 문자열로 나눴을 뿐이라, 다시 생성한 `synthetic_dev_v1.jsonl`이 **바이트 동일**함을 `cmp`로 확인했다. ruff는 한글을 폭 2로 센다 |
| L2 `run_all.sh` 받기 단계 | `qwen25-3b` 단계 추가, `exaone`은 GGUF가 없으면 받고, `kanana2b`·`qwen3`는 고정 revision safetensors가 없을 때 받는다 (`fetch_hf_dir`). 공식 GGUF는 `--expect`로 YAML sha256과 비교한다. `bash -n` 통과 (모델을 다시 받아 끝까지 돌리지는 않았다) |
| L3 `fetch_model.py` sha 비교 | `--expect FILE=SHA256` 추가. 다르면 파일을 지우고 종료 2. HF에서 LICENSE(7KB)로 불일치(삭제·종료 2)와 일치(종료 0) 두 경로를 직접 확인했다. 제품 경로 `models pull`은 명세 sha256을 항상 검증한다 (2절) |
| L4 Qwen3 지연 표현 | 0절, 4.8절, 8절 5번을 "4번 측정 중 2번 문턱 초과 (59.31/64.99/59.74초, 검수 재현 60.10초)"로 고쳤다 |

스파이크 보고서 8절 남은 문제 1~3번에도 T25d 처리 내용을 덧붙였다 (분할 GGUF 표현, 직접 변환 모델 임시 처리, 제어 문자 실증).

## 2. 구현 범위

| 파일 | 내용 |
|---|---|
| `src/jupjup/domain/errors.py` | `LLMTimeoutError(LLMProviderError)` `LLM_TIMEOUT`, `LLMContextOverflowError(LLMProviderError)` `LLM_CONTEXT_OVERFLOW`, `AnalyzerUnavailableError(ProviderError)` `ANALYZER_UNAVAILABLE`. 재시도 분류는 `details["retryable"]`(True / False / False)로 기존 `is_retryable_error`가 그대로 처리한다 |
| `src/jupjup/providers/json_grammar.py` (신규, 순수) | `DecodingSchemaPolicy`, `ANALYSIS_DECODING_POLICY_DS1`(5.2절 표 그대로), `build_decoding_schema`($ref 인라인, 키워드 제거는 속성 이름을 건드리지 않음, drop·상한·순서 적용, 마지막에 정본 대비 느슨함 검사), `canonical_inlined_schema`, `decoding_schema_violations`, `decoding_schema_fingerprint`, 정책 묶음 `DECODING_POLICY_SETS`·`DECODING_POLICY_HASHES`·`policies_for_version`·`verify_decoding_policies`(`DecodingPolicyMismatchError`), `enforce_json_string_char_rule`(0.3.36 `char` 규칙 → upstream `[^"\\\x7F\x00-\x1F]`, 모르는 규칙이면 실패) |
| `src/jupjup/ingest/profiles.py` (신규) | `LocalModelSpec`(+`extra_files`, `source`), `ModelFile`, `DecodingParams.fingerprint()`, `ProfileTimeouts`, `ChunkOverrides`, `ProfileRoute`, `AnalyzerProfile`, `JudgeProfile`, `AnalyzerProfiles.load`(참조 무결성: 없는 model·chunk_model·judge 모델·route 프로필, model_id/name 키 불일치, default_profile), `recording_model_id`, `recording_file_stem` |
| `src/jupjup/providers/llm_local.py` (신규, extra) | `LlamaCppLLM`(`LLMClient`): 생성자는 파일 존재만 확인, 첫 호출·`warm_up`에서 지연 import·sha256 검증(프로세스 캐시)·로드, GGUF 내장 chat 템플릿 렌더링, 입력 상한, 요청마다 `reset()`, 스키마 지문별 문법 캐시, `stopping_criteria` 마감, `finish_reason` 매핑, 인스턴스 잠금. `llama_runtime_info()`, `check_model_files()`, `verified_sha256()` |
| `src/jupjup/providers/local_models.py` (신규) | `pull_model`(네트워크를 쓰는 유일한 함수. 고정 revision, `.partial` 스테이징, sha256 불일치 시 삭제·실패, 이미 맞는 파일은 건너뜀, `local_convert`는 거부), `doctor_report`(네트워크 없음) |
| `src/jupjup/cli.py` | `jupjup models pull <model_id> [--cache-dir] [--profiles]`, `jupjup models doctor [--json] [--no-sha]` (현재 설정으로 못 쓰면 종료 1) |
| `src/jupjup/config.py` | `AnalyzerSettings`(engine mock 기본, required, profile, profiles_path, recordings_dir, n_gpu_layers), `Settings.analyzer`, `Settings.analyzer_cache_dir`(`JUPJUP_ANALYZER_CACHE_DIR`) |
| `config/analyzer_profiles.yaml` | `source: local_convert` 3개, Qwen2.5-7B 둘째 분할 파일을 `extra_files`로 옮김, 머리 주석 갱신. 값(revision, sha256, license)은 T25b 그대로 |
| `pyproject.toml`, `uv.lock` | extra `analyze-local = ["llama-cpp-python==0.3.36"]`, `assist-local = ["jupjup[analyze-local]"]`, `local-models`에 analyze-local 추가. mypy override `llama_cpp.*`, `huggingface_hub.*`. pytest 마커 `local_llm`과 기본 제외. `uv.lock`은 llama-cpp-python 0.3.36(sdist sha256 고정)과 diskcache만 추가 |
| `data/models/README.md` (신규) | 설치(소스 빌드), 캐시 경로, `models pull|doctor`, local_convert 모델, 실제 모델 테스트 방법 (설계 3.3절) |
| `tests/unit/_fake_llama.py` | 가짜 `llama_cpp` 패키지 (Llama, LlamaGrammar, StoppingCriteriaList, llama_grammar.SchemaConverter, llama_chat_format.Jinja2ChatFormatter) |
| `tests/unit/test_llm_local.py` (32), `test_json_grammar.py` (63), `test_analyzer_profiles.py` (40), `tests/integration/test_llm_local_real.py` (`local_llm` 1) | 4절 |
| `specs/phase2_t25b_spike_report.md`, `scripts/spikes/*` | 1절 |

## 3. 설계와 다르게 구현한 부분과 이유

1. **생성은 `create_chat_completion`이 아니라 렌더링한 토큰으로 `create_completion`을 직접 부른다.** 0.3.36의
   `create_chat_completion`은 `stopping_criteria`를 받지 않아 6.3절 타임아웃(토큰마다 마감 검사)을 걸 수 없다. 그래서 chat 핸들러
   (`chat_formatter_to_chat_completion_handler`)가 하는 일을 그대로 한다: GGUF `tokenizer.chat_template`로 `Jinja2ChatFormatter`를
   만들고(`Llama.__init__`과 같은 eos/bos 텍스트), `tokenize(…, add_bos=not added_special, special=True)`, `stop=[eos]`, 템플릿
   EOS 규칙 + 마감 규칙을 `StoppingCriteriaList`로 넘긴다. `count_tokens`와 입력 상한도 같은 렌더링 결과로 잰다. 스파이크 출력과
   **바이트 동일**함을 실제 모델 6건으로 확인했다. `guess_chat_format_from_gguf_metadata`의 내장 포맷(chatml 등)은 쓰지 않는다
   (설계 `chat_template: "gguf"`).
2. **`LocalModelSpec`에 `extra_files`와 `source`를 더했다.** 분할 GGUF(Qwen2.5-7B, T25b 남은 문제 2)는 첫 파일 + `extra_files`
   목록으로 표현하고 모두 sha256을 검증한다. `recording_model_id`는 설계대로 첫 파일 sha256 앞 12자를 쓴다 (나머지 파일은 같은
   revision에 묶이고 검증된다). `source: local_convert`는 HF에 없는 직접 변환 GGUF 표시다 (T25b 남은 문제 1의 임시 처리, 6절 1).
3. **`models pull|doctor` 로직을 `providers/local_models.py`에 따로 뒀다.** 네트워크를 쓰는 코드를 한 함수(`pull_model`)로 모아
   코드 검사 테스트로 고정하기 위해서다. `llm_local.py`는 허브·네트워크 코드를 하나도 갖지 않는다.
4. **정책 해시 단위를 "버전별 정책 묶음"으로 했다.** 설계 예시는 `{"ds-1": "<sha>"}` 하나였다. 디코딩 정책은 스키마마다
   (`AnalysisOutput`, 이후 `ChunkNotes`, `JudgeVerdicts`) 따로 있으므로 `DECODING_POLICY_SETS[version][schema_name]`으로 두고 묶음
   전체를 해시한다. 등록되지 않은 스키마는 빈 정책(키워드 정리만)이다. 불일치는 `DecodingPolicyMismatchError(ValueError)`로
   `LlamaCppLLM` 생성 시점에 실패한다. 덧붙여 정책 해시가 못 잡는 변환 코드·정본 스키마 변경을 잡으려고 ds-1 분석 디코딩 스키마
   지문을 테스트에 고정했다.
5. **`decoding_schema_fingerprint`는 키 순서를 보존해 해시한다** (`sort_keys=False`). 필드 순서가 문법 출력 순서를 바꾸므로,
   정렬하면 ds-1의 핵심(근거 먼저)이 지문에 안 잡힌다. 결과 dict는 결정적이라 지문도 결정적이다.
6. **스키마 → 문법 변환 실패는 `AnalyzerUnavailableError(reason="load_failed")`로 낸다** (`details.schema_name`). 설계 6.7절
   reason 목록 안에서 고른 것이다. `warm_up(schemas)`에서 미리 드러난다.
7. **`ProfileRoute`를 정의했다** (설계·PRD에 필드 정의가 없다): `platforms: list[str]`(1개 이상) + `profile`(참조 검사).
   3.5.5절 7번 라우팅의 스키마 자리만 잡았다.
8. **검증을 몇 개 더했다**: `mock` 프로필에 model 금지, 파일 이름은 경로 구분자 없는 `*.gguf`, revision 40자 hex,
   `ProfileTimeouts`·`ChunkOverrides`도 `extra="forbid", frozen`.
9. **잠금 대기 시간은 실제 시계(`time.monotonic`)로 재고** `last_lock_wait_s`에 남긴다. 주입한 `clock`은 타임아웃·지연 측정에만
   쓴다 (테스트 시계가 대기 측정에 섞이지 않게). 잡 이벤트 로그에 남기는 연결은 T25e 조립 몫이다.
10. **6.7절 "analyze 단계 timeout 재시도 1회 제한(`details["timeout_retries"]`)"은 이번에 구현하지 않았다.** `ingest/worker.py`
    재시도 정책 변경이라 T25d 파일 범위 밖이고, 설계 10.1절이 6.7절 표 전 행 테스트를 T25e 완료 조건에 둔다. 지금은
    `LLMTimeoutError`가 `retryable=True`라서 기존 analyze 재시도 횟수(3회)를 따른다 (6절 2).
11. **6.8절 required/optional 동작(워커 시작 시 `warm_up`, 종료 코드 2, healthz `analyzer: unavailable`)도 T25e 조립에 남겼다.**
    이번에는 그 판단에 쓰는 부품(`AnalyzerUnavailableError` reason, `check_model_files`, `warm_up`, `doctor_report`)까지 만들었다.
    `container.py`는 고치지 않았다.
12. `local-models` extra에 `analyze-local`을 넣었다 (설계 3.3절 그대로). 이제 `--extra local-models`는 llama-cpp-python 소스 빌드를
    포함한다.
13. `models doctor`는 설계 6.8절 점검 항목에 더해, 현재 설정(`JUPJUP_ANALYZER__ENGINE/PROFILE`)으로 쓸 수 있는지를 종료 코드(0/1)로
    낸다. 비상업 라이선스 프로필은 경고로 표시한다.

## 4. 테스트 목록 (T25d 완료 조건, 10.1절 표)

| 완료 조건 | 테스트 |
|---|---|
| 가짜 llama 모듈로 지연 로드 | `test_constructor_does_not_import_or_load`, `test_lazy_load_once_with_pinned_decoding`(로드 1회, Llama 인자 = 3.5절 값, 요청마다 `reset()`), `test_warm_up_loads_compiles_and_generates`, `test_injected_loader_is_used` |
| sha 불일치·파일 없음 → `AnalyzerUnavailableError` | `test_missing_file_at_construction`, `test_file_removed_after_construction`, `test_sha_mismatch_does_not_open_model`(모델을 열지 않음), `test_extra_files_are_checked`, `test_sha_is_remembered_in_process`, `test_missing_extra_is_analyzer_unavailable`(extra_missing, 재시도 불가), `test_load_failure_is_load_failed`(예외 메시지 미노출), `test_missing_chat_template_is_load_failed`, `test_warm_up_generation_failure_is_load_failed` |
| `finish_reason` 매핑 | `test_finish_reason_mapping`(stop→end_turn, length→max_tokens), `test_unknown_finish_reason_is_provider_error`(None, tool_calls) |
| 타임아웃 (`stopping_criteria`) | `test_timeout_via_stopping_criteria`(LLM_TIMEOUT, retryable, timeout_s, 기준 2개 = EOS + 마감), `test_no_timeout_when_generation_is_fast`, `test_lock_wait_is_not_counted_in_timeout`(0.3초 잠금 대기 > 0.2초 타임아웃인데 성공) |
| 입력 상한 | `test_context_overflow_before_generation`(경계값 딱 맞으면 통과, +1이면 생성 없이 `LLMContextOverflowError`, retryable False) |
| 잠금 직렬화 | `test_calls_are_serialized_per_instance`(6스레드, 동시 실행 최대 1, 로드 1회) |
| 문법 캐시 | `test_grammar_is_cached_per_decoding_schema`(같은 스키마 3회 → 컴파일 1회·같은 객체, 다른 스키마 → 새로 컴파일), `test_grammar_char_rule_blocks_control_characters`, `test_constrained_none_sends_no_grammar` |
| `recording_model_id` 결정성 | `test_recording_model_id_is_deterministic`(형식, 기본 지문 고정 `bbdbf37b`, 파일 이름 치환), `test_every_decoding_field_changes_fingerprint`(11개 필드 각각), `test_model_sha_changes_recording_id`, `test_recording_file_stem_rejects_unsafe` |
| 디코딩 정책 해시 검사 | `test_registered_policy_hash_matches_content`, `test_policy_change_without_version_bump_fails`, `test_policy_version_field_must_match`, `test_policy_hash_mismatch_fails_at_construction`, `test_ds1_analysis_decoding_schema_is_pinned` |
| `build_decoding_schema` 속성 테스트 (정본보다 같거나 엄격) | `test_random_policies_never_loosen`(seed 고정 40회: 임의 상한·drop·필수 drop 시도 → ValueError이거나 위반 0), `test_ds1_is_equal_or_stricter_than_canonical`, `test_instance_valid_for_decoding_schema_is_valid_for_canonical`(jsonschema 양쪽 + pydantic), `test_invalid_policies_raise`(12종), `test_violation_checker_detects_manual_loosening`(9종), `test_ds1_matches_design_table`, `test_decoding_schema_is_deterministic_and_does_not_touch_canonical`, char 규칙 2종 |
| 기본 설치 import 검사 | `test_import_does_not_load_llama_cpp`(새 프로세스에서 llm_local·local_models·profiles·cli·container import 후 `llama_cpp` 미로드), `test_network_code_lives_only_in_models_pull`(AST로 llama_cpp import가 `llm_local.py` 한 곳뿐, 허브 코드는 local_models·기존 bge 모듈뿐) |
| 소켓 차단 테스트 | `test_no_network_on_load_and_generate`(connect·connect_ex·create_connection·getaddrinfo 차단 상태로 warm_up·count_tokens·complete_json·close, 시도 0), `test_doctor_reports_files_sha_and_licenses`(doctor도 차단 상태) |
| `local_llm` 실제 모델 테스트 1건 (기본 제외) | `test_kanana_matches_spike_and_grammar_blocks_raw_newlines`: 0.3.36 확인, 실제 `SchemaConverter`가 아직 결함 규칙을 내는지(보정이 실제로 일하는지), Kanana syn-01이 스파이크 출력과 바이트 동일·`count_tokens == prompt_tokens`, 줄바꿈 토큰 `logit_bias +50`에서 원래 문법은 원시 `\n`을 내고 보정 문법은 막고 파싱됨 |
| 그 밖 | 프로필 로더·참조 무결성 14종, 설정·환경 변수, 에러 코드·계층, `pull_model` 5종(검증 후 이동·재사용, 불일치 삭제, 손상 파일 교체, local_convert 거부, huggingface_hub 없음), doctor 2종, CLI `models doctor|pull` 종료 코드 |

AC-L1: llama_cpp가 없는 기본 설치에서 위 테스트는 모두 skip 없이 통과한다 (실제 모델 테스트만 마커로 제외).

## 5. 직접 실행한 명령과 결과

### 5.1 기본 설치 (`uv sync --locked`, extra 없음)

| 명령 | 결과 |
|---|---|
| `uv run python -c "import importlib.util as u; print(u.find_spec('llama_cpp'))"` | `None` |
| `uv run pytest` | **1079 passed, 4 deselected**, 경고 1건(기존 Starlette/httpx). 직전 기준 944 + 신규 135. deselected = 기존 embed/rerank 3 + local_llm 1 |
| `uv run ruff check src tests` | All checks passed! (`uv run ruff check scripts`도 통과) |
| `uv run mypy src` | Success: no issues found in 82 source files |
| `uv run jupjup eval validate` | 종료 0. 인제스트 sources 80, annotations 80 (dev 48, test 32) |
| `uv run jupjup eval run --mode mock --split dev` | PASS. R@10 0.9620, R@5 0.9419, MRR@10 0.9958, nDCG@10 0.9795, cat min 0.8838 |
| `uv run jupjup eval run --mode mock --split test` | PASS. 0.9420 / 0.9281 / 0.9867 / 0.9589 / 0.7812 |
| `uv run jupjup eval run --mode recorded --split dev` | PASS. 0.9712 / 0.9495 / 1.0000 / 0.9860 / 0.8894 |
| `uv run jupjup eval run --mode recorded --split test` | PASS. 0.9720 / 0.9541 / 0.9911 / 0.9801 / 0.8900 |
| `uv run jupjup eval ingest --mode mock --split dev\|test\|all` 각 2회 (`--out` 스크래치) | 6회 종료 0, PASS. all: schema_final 1.0, injection 1.0, 회귀 게이트 OK |
| 위 6개 파일(JSON·Markdown) `cmp` | 1회 대 2회 **바이트 동일**. `git archive HEAD`로 꺼낸 변경 전 코드의 같은 명령 결과와도 **바이트 동일** |
| `git diff HEAD -- src/jupjup/search src/jupjup/query data` | 0줄 (`data/models/README.md`는 새 파일) |
| `uv run jupjup models doctor --no-sha` | 종료 0, mock 설정 "사용 가능", 비상업 2개 경고. `JUPJUP_ANALYZER_CACHE_DIR=…/dc2/models`면 Qwen3·Kanana-2.1B "있음" |
| `uv run jupjup models pull kanana-1.5-2.1b-instruct-q4km --cache-dir /tmp/nonexist-x` | 종료 2, 직접 변환 모델이라 받지 않고 위치·sha256 안내 |

검색 수치는 T25b 검수 1.4절과 소수점 4자리까지 같다.

### 5.2 extra 설치 (별도 venv, 기본 `.venv`는 건드리지 않음)

| 명령 | 결과 |
|---|---|
| `CMAKE_ARGS="-DGGML_METAL=on" UV_PROJECT_ENVIRONMENT=<scratch>/venv-local uv sync --locked --extra analyze-local` | 종료 0. uv 캐시의 0.3.36 소스 빌드 wheel 재사용. `llama_cpp.__version__ == "0.3.36"`, `llama_supports_gpu_offload() == True`, GPU `MTL0 (Apple M5)`, WHEEL `Tag: py3-none-macosx_26_0_arm64` |
| 같은 venv에서 `pytest -m local_llm` (`JUPJUP_ANALYZER_CACHE_DIR=/Users/minjun/orca/workspaces/dc2/models`) | **1 passed** (13.3초) |
| 같은 venv에서 `pytest` (기본 마커) | 1078 passed (당시 기준), 종료 0. 실제 llama_cpp가 설치돼 있어도 가짜 모듈 테스트가 통과한다. llama_cpp import 코드가 연 `/dev/null`의 `ResourceWarning` 2건 (외부 코드) |
| 스크래치 스크립트로 `LlamaCppLLM` 대 스파이크 `*.patched.json` grammar_a | Kanana-2.1B syn-01~03: 텍스트 3/3 동일, 프롬프트 토큰 1119/971/1141, 출력 387/528/606 토큰, 10.1/14.0/16.3초. Qwen3-4B syn-01~03: 3/3 동일, 1187/1013/1225, 1142/996/918 토큰, 46.1/39.4/38.1초. `warm_up`(sha256 포함) 약 1.9초 |
| 줄바꿈 `logit_bias` 대조 (Kanana) | 원래 문법: `{"text": "\n\n\n…` `finish=length`, JSON 파싱 실패. 보정 문법: `{"text": "Remember to return the book on time. Don"}` `finish=stop`, 파싱 성공 |

### 5.3 착수 전 정리 확인

| 명령 | 결과 |
|---|---|
| Metal 인덱스 HTML + wheel 7개 받기 → `zipfile` 멤버별 읽기 | 1절 M1 표 |
| `curl https://pypi.org/pypi/llama-cpp-python/0.3.36/json` | sdist 1개, sha256 `832db069…1a2e`, 2026-10-01T05:48:01 |
| `python3 scripts/spikes/data/build_synthetic_dev.py` 후 `cmp` | 바이트 동일 |
| `fetch_model.py --expect LICENSE=<틀린 값>` / `<맞는 값>` | 종료 2·파일 삭제 / 종료 0 |
| `bash -n scripts/spikes/run_all.sh` | 통과 |

## 6. 남은 문제

1. **직접 변환 GGUF(Qwen3-4B-2507, Kanana-1.5 2.1B/8B)의 배포 경로가 아직 없다** (T25b 남은 문제 1). 지금은 `source: local_convert`로
   표시하고 `models pull`이 거부·안내만 한다. 기본·도전 후보가 모두 이 경우라서, 새 기기에서는 사용자가 변환본을 직접 두어야 한다.
   선택지(T25b 8절: 변환 자동화 / 승인한 저장 위치 / 공식 GGUF 모델만)는 **PM·사용자 결정**이 필요하다.
2. **timeout 재시도 1회 제한**(6.7절 `timeout_retries`)과 **6.8절 required/optional 조립**(워커 `warm_up`, 종료 코드 2, healthz)은
   T25e로 넘겼다 (3절 10·11).
3. **비공개 API 의존**: eos/bos 텍스트에 `Llama._model.token_get_text`를 쓴다 (`Llama.__init__`과 같은 방법, 없으면 `detokenize`로
   대체). 실제 모델 테스트는 `LlamaGrammar._grammar`를 읽는다. 버전을 0.3.36으로 고정했고, 올릴 때는 `local_llm` 테스트와 `char`
   규칙 검사(모르는 규칙이면 실패)가 먼저 드러낸다.
4. **`models pull`의 실제 다운로드 경로**(`hf_hub_download`)는 가짜 downloader로만 테스트했다. 같은 함수를 쓰는 `fetch_model.py`는
   실제 HF에서 작은 파일로 확인했지만, `models pull`로 GGUF를 끝까지 받아 보지는 않았다 (디스크·시간).
5. **바이트 동일 재현은 모델당 3건**만 확인했다 (스파이크 10건 중). 결정성 판단은 원칙 3대로 T25f 이후 recorded로 한다.
6. `run_all.sh`의 새 받기 단계는 문법 검사만 했고 끝까지 다시 돌리지 않았다 (모델 6개를 다시 받아야 한다).
7. 스파이크 GO 조건 2(주입 저항)와 3(Qwen3 지연)은 T25e 프롬프트·ds-2 몫이라 그대로 남아 있다.

## 7. 반영한 피드백

- `specs/phase4_review_t25b_loop1.md` M1(정정 + 설치 경로 결정과 근거), L1(ruff), L2(받기 단계), L3(`fetch_model --expect`, `models pull`
  sha256 검증·삭제), L4(Qwen3 지연 표현). 4절 재검수 조건 3번(`char` 규칙 강제·요청마다 `reset()`·문법 캐시)은 4절 테스트로 고정했다.

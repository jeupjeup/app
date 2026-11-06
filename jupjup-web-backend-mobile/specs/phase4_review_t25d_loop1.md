# Phase 4 최종 검수: T25d 로컬 LLM 제공자와 설정, Loop 1/3

- **점수:** 95 / 100
- **상태:** PASS
- **항목별:** 정확성 39 / 40, 안전성 28 / 30, 유지보수성 28 / 30
- **루프백 대상:** 없음 (PASS). 아래 M1은 **T25e 착수 때 같이 고치는 것**을 권한다. T25e가 `warm_up` 실패를 종료 코드 2로 바꾸는 조립을 하므로 그 전에 막아야 한다. L1~L4는 T25e 범위에서 함께 정리하면 된다.
- **검수 대상:** `58f01ef feat: T25d local llama.cpp LLM provider, analyzer profiles, models pull/doctor` (기준 `9dc0ddc`)
- **검수자:** Claude-Reviewer 역할 대행 (Claude Opus 5.5). 코드는 고치지 않았다. 재현 실험은 스크래치 디렉터리(가짜 모듈 탐침 스크립트, 별도 extra venv, `git archive 9dc0ddc` 사본), `var/review.db`에서만 했다.
- **범위 밖:** T25e 이후 (`LLMContentAnalyzer`, 6.7절 `timeout_retries`, 6.8절 required/optional 조립, healthz). 보고서 3절 10·11번의 이월은 설계 10.1절이 해당 테스트를 T25e 완료 조건에 둔 것과 맞아서 감점하지 않았다. 사람 검수 미완료(`ai_draft_unreviewed`)도 감점하지 않았다.

## 0. 한 줄 판정

10.1절 T25d 완료 조건 13개를 **모두 직접 재현했다.** 기본 설치에는 `llama_cpp`가 없고, 기본 게이트(1079 passed, 4 deselected)·ruff·mypy·eval 4종이 통과하며 수치는 T25b 검수와 소수점 4자리까지 같다. 인제스트 mock 리포트 6개 파일은 두 번 실행끼리, 그리고 **변경 전 커밋 `9dc0ddc` 사본의 결과와도 바이트 단위로 같다.** `search`, `query`, `container.py`, `worker.py`, `api`, `data/recordings|baselines|golden` diff는 0줄이다. extra venv에서 실제 Kanana-1.5-2.1B로 `local_llm` 테스트가 통과했고(14초), 따로 돌린 실제 모델 탐침에서 **1초 타임아웃 → `LLM_TIMEOUT`(1.0초에 멈춤)**, **입력 18,199토큰 → 생성 없이 `LLM_CONTEXT_OVERFLOW`**, syn-02 출력이 **스파이크 패치 문법 결과와 바이트 동일**, 소켓을 막은 채 로드·생성 시 **연결 시도 0건**을 확인했다.
감점은 오류 경로에 몰려 있다. 가장 큰 것은 **GGUF chat 템플릿이 컴파일되지 않으면 jinja 예외가 그대로 새어 나가는 문제(M1)**다. 6.7절 계약(`AnalyzerUnavailableError(load_failed)`)을 어기고, 실패할 때마다 모델을 새로 로드한다.

## 1. 직접 실행한 명령과 결과

### 1.1 기본 게이트 (프로젝트 venv, extra 없음, `uv sync --locked`)

| 명령 | 결과 |
|---|---|
| `uv run python -c "importlib.util.find_spec('llama_cpp')"` | `None` |
| `uv run pytest` | **1079 passed, 4 deselected**, 경고 1건 (기존 Starlette/httpx). `--co`: 1079/1083 (deselected = embed/rerank 3 + local_llm 1). skip 0 (AC-L1) |
| `uv run ruff check src tests scripts` | All checks passed! (T25b L1 해소) |
| `uv run mypy src` | Success: no issues found in 82 source files |
| `uv run jupjup eval validate` | 종료 0. 인제스트 sources 80, annotations 80 (dev 48, test 32) |
| `eval run --mode mock --split dev` | PASS. R@10 0.9620, R@5 0.9419, MRR 0.9958, nDCG 0.9795, cat min 0.8838 |
| `eval run --mode mock --split test` | PASS. 0.9420 / 0.9281 / 0.9867 / 0.9589 / 0.7812 |
| `eval run --mode recorded --split dev` | PASS. 0.9712 / 0.9495 / 1.0000 / 0.9860 / 0.8894 |
| `eval run --mode recorded --split test` | PASS. 0.9720 / 0.9541 / 0.9911 / 0.9801 / 0.8900 |
| `eval ingest --mode mock --split dev\|test\|all` 2회 (`--out` 스크래치) | 6회 종료 0. all: schema first 0.925, final 1.0 |
| 위 6개 파일 `cmp` (1회 대 2회, 1회 대 `git archive 9dc0ddc` 사본 실행) | **모두 바이트 동일**. 사본 실행이 사본의 `src/jupjup`를 읽었는지 `jupjup.__file__`과 `llm_local` 부재로 확인 |
| `git diff --stat 9dc0ddc HEAD -- src/jupjup/search src/jupjup/query src/jupjup/container.py src/jupjup/ingest/worker.py src/jupjup/api data/recordings data/baselines data/golden` | **0줄** (AC-L2) |
| `grep -rn "llm_local\|local_models\|ingest.profiles" src` (새 모듈 자신 제외) | `cli.py`의 `models` 명령 안 지연 import뿐. 서비스·워커·API 경로는 새 모듈을 부르지 않는다 (AC-L8) |

### 1.2 T25d 완료 조건 재현 (10.1절)

| 완료 조건 | 직접 확인 | 판정 |
|---|---|---|
| 가짜 llama 모듈로 지연 로드 | 탐침: 생성자는 로드 0회, 첫 `complete_json`에서 1회. `close()` 뒤 다시 부르면 다시 로드 1회. 요청 9건에 `reset()` 9회 | 충족 |
| sha 불일치·파일 없음 → `AnalyzerUnavailableError` | 탐침: 내용이 다른 파일 → `sha_mismatch`, 모델을 열지 않음. 같은 경로에 맞는 파일로 바꾸면 (mtime 변경) 다음 호출이 성공. `extra_files` 누락은 생성자에서 `model_missing`. `is_retryable_error` False | 충족 |
| `finish_reason` 매핑 | 탐침: `stop`→`end_turn`, `length`→`max_tokens`, `None`·`tool_calls` → `LLMProviderError`(details에 finish_reason만) | 충족 |
| 타임아웃 (`stopping_criteria`) | 가짜: `test_timeout_via_stopping_criteria`, 잠금 대기 제외 테스트 통과. **실제 Kanana**: `timeout_s=1.0` → `LLMTimeoutError` `retryable=True`, 경과 1.0초 | 충족. 단 첫 호출 로드 시간 제외 → L2 |
| 입력 상한 | **실제 Kanana**: 12,359토큰 + 1,536 ≤ 16,384 → 정상 생성, 18,199토큰 → 생성 없이 `LLM_CONTEXT_OVERFLOW` (`retryable=False, input_tokens, max_tokens, n_ctx`) | 충족 |
| 잠금 직렬화 | `test_calls_are_serialized_per_instance` (6스레드, 동시 실행 최대 1, 로드 1회) 통과. 코드상 `complete_json`·`count_tokens`·`warm_up`·`close` 모두 같은 잠금 | 충족 |
| 문법 캐시 | 테스트 통과. 탐침: 실제 문법 문자열에 `\x00-\x1F` 차단 규칙이 들어감. `constrained="none"`이면 grammar None이고 `recording_model_id`도 달라짐 | 충족 |
| `recording_model_id` 결정성 | `models doctor` 출력의 6개 프로필 id가 기본 지문 `bbdbf37b`로 보고서와 같음. 두 프로세스(기본·extra venv)에서 같은 값 | 충족 |
| 디코딩 정책 해시 검사 | 탐침: ds-1 정책의 evidence 상한 6→5로 바꿔 주입 → 생성자에서 `DecodingPolicyMismatchError`(등록 `fade30e97ed5`, 현재 `959b353e16ca`). 모르는 버전 `ds-9`도 생성 시 실패 | 충족 |
| `build_decoding_schema` 속성 테스트 | 테스트 통과(seed 40개). 탐침: ds-1 위반 0, 필드 순서가 설계 표와 같음, 필수 필드 drop·minLength 아래 상한·없는 필드 순서·정본보다 큰 상한 모두 ValueError. 단 비교기 사각 1건 → L3 | 충족 |
| 기본 설치 import 검사 | 새 프로세스 import 테스트 통과. 기본 venv `find_spec('llama_cpp') is None` | 충족 |
| 소켓 차단 테스트 | 가짜 모듈 테스트 통과. **실제 Kanana**로 `connect/connect_ex/create_connection/getaddrinfo`를 막고 `warm_up`·생성 3회·`close` → 시도 0건 | 충족 |
| `local_llm` 실제 모델 테스트 1건 (기본 제외) | 별도 venv `CMAKE_ARGS="-DGGML_METAL=on" UV_PROJECT_ENVIRONMENT=<scratch>/venv-local uv sync --locked --extra analyze-local` (uv 캐시 소스 빌드 재사용, `0.3.36`, GPU offload True, `MTL0 (Apple M5)`) → `pytest -m local_llm` **1 passed (14.04초)**. 같은 venv 기본 `pytest`도 1079 passed | 충족 |

### 1.3 보고서 주장 교차 확인

| 주장 | 확인 | 결과 |
|---|---|---|
| `create_completion` 직접 호출이 스파이크 출력과 바이트 동일 | 실제 Kanana syn-02 (`max_tokens=1536`) | `end_turn`, 입력 971 / 출력 528토큰, 스파이크 `grammar_a`와 **바이트 동일**, `AnalysisOutput` 검증 통과 (보고서 수치와 같음) |
| `warm_up` 약 1.9초 | 실제 Kanana | 1.53초 (sha256 포함) |
| `models doctor` 종료 코드 | 기본 설정 / `ENGINE=local PROFILE=local-kanana-2b`(extra 없음) / 없는 프로필 | 0 / **1** / `usable=False` |
| `models pull` 거부·안내 | `local_convert` 모델, 없는 모델 id, `huggingface_hub` 없는 `hf_gguf` 모델 | 셋 다 종료 2와 안내 문구. 다운로드 시도 없음 |
| `pull_model`이 유일한 허브 코드 | 코드 검사 테스트 + 직접 grep | `hf_hub_download`/`huggingface_hub`는 `local_models.py`와 기존 bge 모듈 2개뿐. `llm_local.py`에 허브·소켓 코드 없음 |
| `uv.lock` 변경 범위 | `git diff --stat` | 34줄. llama-cpp-python 0.3.36 sdist(sha256 고정)와 diskcache만 추가 |
| 로그에 원문 없음 (AC-L13) | `llm_local.py` `logger` 호출 2곳 | model_id, n_ctx, 토큰 수, stop, 지연만. 런타임 예외 메시지는 타입 이름만 남김(탐침: `RuntimeError("prompt: secret user text")` → details `{"error": "RuntimeError"}`) |
| T25b L1~L4 처리 | ruff scripts 통과, `fetch_model --expect`·`run_all.sh` diff 확인 | 처리됨 |

### 1.4 CLI 회귀·경계값 (`seed load --db var/review.db` → u_alice 160, u_bob 30, u_carol 10. `search --db var/review.db --now 2026-10-15T12:00+09:00 --json`, recorded는 `JUPJUP_MODE=recorded`)

| 질의 | mock | recorded | 비고 |
|---|---|---|---|
| `경주 맛집 인스타` (과소 완화 회귀) | `c_alice_0153` 1건, `platform_filter_dropped` | 같음 | known_issues 1번 해결 상태 유지 |
| `하체 운동 유튜브` | `c_alice_0040` 1위, platform 완화 | 같음 (5건) | 유지 |
| `경주 맛집 카톡 논문` (이중 완화 기록) | platform + content_type 완화 둘 다 기록 | 같음 | known_issues 2번 유지 |
| `다리 운동 영상` | `c_alice_0040` 1위 | 같음 | known_issues 4번 유지 |
| `성수동 카페` | 성수 카페 10건 | 10건 | 정상 |
| `성슈동 카페` / `경쥬 맛집` (오타) | 성수 상위 10건 / 0건 | `EMBEDDING_CACHE_MISS`, 종료 2 | 녹화 밖 질의 미스는 기존 동작 |
| `'   '` / `!!!@@@###` / 600자 | `INVALID_QUERY`, 종료 2 | 같음 | 정상 |
| `python 튜토리얼 영상`, `React hooks 정리` (영어 혼합) | 0건 | 캐시 미스 | 기존 동작 |
| `인스타 --platform instagram` (필터 전용) | instagram만 10건 | 같음 | 요청 잠금 정상 |
| `경주 맛집 --platform youtube`, `유튜브 영상 --platform blog` | 0건 | 0건 | 요청 필터가 이김. 과잉 완화 없음 |
| `화성 탐사 로버 사진` (없는 대상) | 0건 | 캐시 미스 | 거짓 결과 없음 |
| `지난달 인스타` | 4건 | 4건 | 정상 |
| `u_bob` `경주 맛집 인스타` / `u_carol` `성수동 카페` | 0건 / `c_carol_0009`만 | 같음 | 사용자 격리 정상 |
| 없는 사용자 `u_nobody` | 안내 문구 + 빈 결과 JSON, 종료 0 | 같음 | 기존 동작 |
| `' OR 1=1 --` | 0건 | 캐시 미스 | 주입 무해 |

모두 T25b 검수 1.5절과 같은 동작이다 (검색 경로 diff 0과 일치).

## 2. 피드백 (심각도 순)

### M1. chat 템플릿 컴파일 실패가 `AnalyzerUnavailableError`로 바뀌지 않고 그대로 새어 나간다 (중간)

- **위치:** `src/jupjup/providers/llm_local.py:314` (`self._formatter = self._chat_formatter(runtime, model)`가 `try` 밖), `:319-331` (`token_eos()`·`token_bos()`·`Jinja2ChatFormatter(...)` 생성)
- **현상:** 실제 llama-cpp-python 0.3.36의 `Jinja2ChatFormatter.__init__`은 템플릿을 sandbox 환경에서 바로 컴파일한다. 템플릿이 깨졌거나 jinja가 모르는 구문이면 `TemplateSyntaxError`가 생성자에서 난다. 지금은 이 예외를 감싸지 않는다.
- **재현 (가짜 모듈 탐침):** `Jinja2ChatFormatter`가 예외를 내게 바꾸고 `warm_up()`과 `complete_json()`을 부르면 둘 다 **원래 예외 타입(code 없음)**이 그대로 올라온다. 두 번 부르는 동안 `Llama` 로드는 2회, `close`는 0회였다. 로드한 모델을 `self._model`에 넣기 전에 실패해서, **호출할 때마다 수 GB 모델을 다시 연다** (닫지도 않는다).
- **영향:** 설계 6.7절 표는 "로드 실패 → `AnalyzerUnavailableError`(재시도 불가)"다. `test_missing_chat_template_is_load_failed`는 템플릿이 **없는** 경우만 다룬다. 워커는 모르는 예외를 일반 `JupjupError`로 닫으므로(`worker.py:189`) 데이터가 새지는 않지만, T25e가 "`warm_up`에서 `AnalyzerUnavailableError`면 종료 코드 2"로 조립하면 이 경우는 그 분기를 빠져나간다. 6.8절 `required=true` 동작이 이 원인에서는 깨진다.
- **개선:** `_chat_formatter` 호출(그리고 eos/bos 조회)을 `try`로 감싸 `_unavailable("load_failed", ..., error=type(exc).__name__)`로 바꾸고, 실패하면 방금 연 모델을 `close()`한다. 템플릿 컴파일 실패 테스트 1건을 더한다.

### L1. 렌더링 실패의 분류가 경로마다 다르다 (낮음)

- **위치:** `src/jupjup/providers/llm_local.py:341` (`_render`의 `LLMProviderError`, `retryable` 없음), `:265` (`warm_up`의 `_render`가 `try` 밖)
- **현상:** 탐침에서 렌더링 예외는 `LLM_UNAVAILABLE`, `is_retryable_error=True`였다. 같은 입력·같은 템플릿이면 결정적으로 다시 실패하므로 analyze 재시도 3회와 백오프가 헛돈다. `warm_up`에서는 `_generate` 실패만 `load_failed`로 바꾸고 렌더링 실패는 `LLMProviderError`로 나가서 M1과 같은 이유로 T25e의 시작 시 판정을 빠져나간다.
- **개선:** `_render` 실패에 `retryable: False`를 넣고, `warm_up`은 렌더링도 `load_failed`로 감싼다.

### L2. 타임아웃 측정 범위 주석이 실제와 다르다 (낮음)

- **위치:** `src/jupjup/providers/llm_local.py:226-228`
- **현상:** 주석은 "로드·렌더링·문법 컴파일·prefill·생성이 모두 들어간다"인데, `started`는 `_ensure_loaded()` **뒤에** 잡힌다. 탐침에서 가짜 시계로 로드에 100초를 넣어도 `timeout_s=5` 호출이 성공했다. 설계 6.3절 "잠금을 잡은 뒤부터 잰다"를 글자대로 읽으면 로드도 포함이다. 실제 로드는 1.5~2초라 영향은 작고, 로드를 빼는 쪽이 첫 잡에 공정하다는 판단도 가능하다.
- **개선:** 어느 쪽인지 정해 주석과 보고서를 맞추고, 로드를 빼는 쪽이면 테스트로 고정한다.

### L3. `decoding_schema_violations`가 "필수인데 properties에서 사라진 필드"를 못 잡는다 (낮음)

- **위치:** `src/jupjup/providers/json_grammar.py:305-313`
- **현상:** 비교기는 `required` 목록이 같은지와 디코딩 쪽에 있는 속성만 본다. 탐침에서 ds-1 결과의 `properties`에서 필수 필드 하나를 직접 지우고 `required`는 그대로 두면 **위반 0건**이 나왔다. llama.cpp 변환기는 properties에 없는 required 이름을 무시하므로, 이 문법의 출력은 정본 검증에서 항상 실패한다. `_drop`이 필수 필드 drop을 막아 지금 경로로는 생기지 않지만, 이 함수는 "수동 느슨화 탐지" 방어선이라(`test_violation_checker_detects_manual_loosening`) 이 경우도 잡아야 한다.
- **개선:** 정본 `properties` 중 정본 `required`에 있는 이름이 디코딩 `properties`에 없으면 위반으로 낸다. 9종 테스트에 1종을 더한다.

### L4. `models pull`의 네트워크 예외가 트레이스백으로 끝난다 (낮음)

- **위치:** `src/jupjup/cli.py:1013-1017`, `src/jupjup/providers/local_models.py:66`
- **현상:** CLI는 `JupjupError`만 잡는다. 탐침에서 downloader가 `ConnectionError`를 내게 하면 `models pull`은 **종료 1 + 처리되지 않은 예외**로 끝났다. CLI 머리말 규칙상 1은 "기준 미달"이고 설정·데이터·환경 오류는 2다. 스테이징은 `finally`로 지워져 남는 파일은 없었다 (빈 모델 디렉터리만 남음).
- **개선:** `pull_model`에서 downloader 예외를 `AnalyzerUnavailableError(reason="download_failed", error=타입 이름)`로 감싸거나 CLI에서 잡아 종료 2와 한 줄 안내를 낸다.

### 참고 (감점 없음)

- `recording_model_id`는 첫 파일 sha256만 쓴다 (보고서 3절 2번). 분할 파일은 같은 revision에 묶이고 모두 검증되므로 받아들인다. 분할 모델의 둘째 파일만 다시 만드는 일이 생기면 키가 안 바뀌는 점은 T25f 때 문서에 남기면 좋다.
- `models pull`이 sha가 다른 기존 파일을 받기 **전에** 지운다 (`local_models.py:61`). 받기가 실패하면 원래 (틀린) 파일도 없어진다. 어차피 쓸 수 없는 파일이라 문제는 아니다.
- 실제 모델 테스트가 비공개 속성 `LlamaGrammar._grammar`를 읽는다. 0.3.36으로 고정했고 보고서 6절 3번에 적혀 있다.
- 보고서 6절 1번(직접 변환 GGUF 배포 경로)은 PM·사용자 결정 사항이다. 기본·도전 후보가 모두 `local_convert`라 새 기기에서는 수동 배치가 필요하다는 점을 T25h 전에 정해야 한다.

## 3. 채점 근거

| 항목 | 점수 | 근거 |
|---|---|---|
| 정확성 | 39 / 40 | 완료 조건 13개 전부 재현. 실제 모델로 바이트 동일·타임아웃·입력 상한까지 확인. mock 인제스트·검색 eval 무회귀(변경 전 코드와 바이트 동일). M1이 6.7절 `load_failed` 계약을 일부 어긴다 (-1) |
| 안전성 | 28 / 30 | 서비스 경로 네트워크 0(소켓 차단 실측), 기본 설치 llama_cpp 미로드, sha256 검증·지연 로드, 원문 미기록 모두 확인. M1 오류 경로에서 원시 예외·반복 로드 (-1), L4 다운로드 예외 미처리 (-1) |
| 유지보수성 | 28 / 30 | 순수 모듈 분리(`json_grammar`), 네트워크 코드 한 함수, 정책 해시 레지스트리, 가짜 모듈 테스트 135개로 구조가 좋다. L3 비교기 사각 (-1), L1·L2 분류·주석 불일치 (-1) |
| **합계** | **95 / 100** | **PASS** |

## 4. 다음 단계 권고

1. T25e 브리프에 M1과 L1을 넣는다 (`warm_up` → 종료 코드 2 조립 전에 고쳐야 한다). 템플릿 컴파일 실패 테스트를 함께 둔다.
2. L2~L4는 T25e 작업 중 같은 파일을 만질 때 정리한다.
3. 직접 변환 GGUF 배포 경로(보고서 6절 1번)는 PM이 사용자에게 결정을 받는다.

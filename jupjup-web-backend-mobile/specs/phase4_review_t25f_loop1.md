# Phase 4 최종 검수: T25f 분석기 녹화·재생과 인제스트 하네스 확장, Loop 1/3

- **점수:** 94 / 100
- **상태:** PASS
- **항목별:** 정확성 37 / 40, 안전성 29 / 30, 유지보수성 28 / 30
- **루프백 대상:** 없음 (PASS). M1·L1은 T25g가 `eval/ingest_harness.py`·`ingest_linkage.py`를 만질 때 같이 고치길 권한다. **T25h에서 recorded 연결 지표로 채택 판단을 하기 전에는 M1을 꼭 고쳐야 한다.**
- **검수 대상:** `2aa7ffe feat: T25f analyzer record/replay and ingest harness recorded/live modes` (기준 `b6820f2`)
- **검수자:** Claude-Reviewer 역할 대행 (Claude Opus 5.5). 코드는 고치지 않았다. 재현 실험은 스크래치 디렉터리(탐침 스크립트, `git archive b6820f2` 사본과 그 venv, 소켓 차단 pytest 플러그인)와 `var/review.db`에서만 했다. 저장소 `data/recordings/llm`·`linkage`에는 아무것도 생기지 않았다.
- **범위 밖:** T25c 골든셋 v2, T25g 이후 (판정기, 결정적 핵심 사실 매처, 실제 모델 녹화 T25h). 사람 검수 미완료(`ai_draft_unreviewed`)와 실제 모델 녹화가 없는 것은 감점하지 않았다.

## 0. 한 줄 판정

10.1절 T25f 완료 조건 여섯 개를 **모두 직접 재현했다.** 테스트 픽스처와 별도로 내가 만든 **기본 `MockLLM`(model_id만 녹화 키로 바꿈)** 으로 live 녹화를 하고 recorded로 재생했다. 두 리포트는 원래 달라야 하는 세 값(`config.mode`, `config.confirm_cost`, `runtime.recording`)만 다르고 나머지는 모두 같았다. recorded 재생끼리는 파일 바이트가 같았고, `PYTHONHASHSEED` 0과 999에서도 같았다. 녹화 행 1/3을 지우면 종료 2와 미스 목록 33건이 나왔다. test·all split은 해시가 없으면 모델을 만들기 전에 거부됐다(CLI 4개 명령 모두). live는 확인 플래그가 없으면 추정만 출력하고 종료 2로 끝났다. live 서비스 경로는 `RecordingLLM`을 0번 만들었다. mock 연결 지표는 두 번 실행해도, 해시 시드를 바꿔도 바이트가 같았다.
기본 게이트도 통과했다: pytest 1164 passed(skip 0), ruff, mypy, eval 4종(수치가 T25e 검수와 소수점 4자리까지 같음). mock 인제스트 6개 파일은 두 번 실행끼리, 그리고 **변경 전 커밋 사본과도 바이트가 같다.** mock 검색 11건은 사본과 비교해 `query_id`(난수)와 `timing_ms`만 다르다. 소켓을 막고 돌렸을 때 네트워크 시도는 0건이었고, `llama_cpp`는 import되지 않았다.
감점은 세 군데서 나왔다. 첫째(M1), recorded 연결 지표에서 **임베딩 녹화 미스가 미스로 잡히지 않는다.** 시드 잡이 조용히 실패하고, 망가진 하락 값이 그대로 게이트에 들어간다. 둘째(L1), recorded 게이트가 연결 지표를 재지 않았을 때 그 사실을 표시하지 않는다. 셋째(L2), 동결 해시에 `n_ctx`가 빠져 있다.

## 1. 직접 실행한 명령과 결과

### 1.1 기본 게이트 (프로젝트 venv, extra 없음)

| 명령 | 결과 |
|---|---|
| `uv run python -c "importlib.util.find_spec('llama_cpp')"` | `None` |
| `uv run pytest` (`-o addopts=""`로 요약 줄 확인, 기본 마커 제외 동일) | **1164 passed, 4 deselected**, 경고 2건 (기존 Starlette 1, 테스트가 의도한 `RuntimeWarning` 1). skip 0 (AC-L1) |
| `uv run ruff check src tests` | All checks passed! |
| `uv run mypy src` | Success: no issues found in 86 source files |
| `uv run jupjup eval validate` | 종료 0 (ingest 80 = dev 48 / test 32) |
| `eval run --mode mock --split dev` | PASS. R@10 0.9620, MRR 0.9958, nDCG 0.9795, cat min 0.8838 |
| `eval run --mode mock --split test` | PASS. 0.9420 / 0.9867 / 0.9589 / 0.7812 |
| `eval run --mode recorded --split dev` | PASS. 0.9712 / 1.0000 / 0.9860 / 0.8894 |
| `eval run --mode recorded --split test` | PASS. 0.9720 / 0.9911 / 0.9801 / 0.8900 (네 줄 모두 T25e 검수 값과 같음) |
| `eval ingest --mode mock --split dev\|test\|all` 2회 + `git archive b6820f2` 사본(별도 venv, `jupjup.__file__`이 사본 `src`인지 확인)에서 1회 | 9회 모두 종료 0 |
| 위 6개 파일 `cmp` (1회 대 2회, 1회 대 사본) | **모두 바이트 동일** (AC-L2, 원칙 4) |
| `git diff --stat b6820f2 HEAD -- src/jupjup/search src/jupjup/query data/golden data/baselines 'data/recordings/*.jsonl'` | **0줄** |
| `grep -rn "llama_cpp\|llm_local" src \| grep import` (`llm_local.py` 제외) | `container.py`·`eval/ingest_runtime.py` 함수 안 지연 import, `local_models.py`의 `llm_local` 모듈 import(이 모듈도 `llama_cpp`는 지연 import)뿐 (AC-L16) |
| `jupjup.cli`·`eval.ingest_*` 4개 import + mock 컨테이너·`build_ingest_service` 조립 뒤 `sys.modules` | `llama_cpp` False, `jupjup.providers.llm_local` False |

### 1.2 T25f 완료 조건 재현 (10.1절)

| 완료 조건 | 직접 확인 | 판정 |
|---|---|---|
| MockLLM을 감싼 `RecordingLLM` 녹화 → `RecordedLLM` 재생이 같은 리포트 (바이트 동일) | 탐침 p1: **기본 `MockLLM`**(스키마 기본값 응답)의 `model_id`만 `recording_model_id`로 바꿔 live+record dev 48건 실행(소켓 차단). 생성기 호출 1회, 녹화 162행(전부 `complete_json`), 48건 모두 `ANALYSIS_SCHEMA_INVALID`(재요청 경로까지 녹화됨). recorded 재생 2회의 JSON·MD는 바이트 동일. live와 recorded의 `deterministic_dict`를 재귀 비교하면 차이는 `config.mode`, `config.confirm_cost`, `runtime.recording` 세 개뿐이었다(보고서 2절 2번과 일치). CLI 재생 결과도 같은 바이트였고, `PYTHONHASHSEED=0/999`에서도 같았다. 녹화 파일에는 `보안 규칙`, `<source` 같은 원문 조각이 없었다. 테스트 쪽 `GoldenEchoLLM`(성공 42, 실패 6, 재요청 13)도 통과 | 충족 |
| 미스 시 종료 2와 미스 목록 | 녹화 162행 중 3의 배수 행을 지운 사본으로 `eval ingest --mode recorded` → **종료 2**, `녹화 미스 33건 (원문 없이 해시만 표시)` 다음에 `ing_0003: complete_json schema=AnalysisOutput max_tokens=1536 request_hash=…` 줄들이 나왔다. 트레이스백 없음. 녹화가 온전하면 미스 0건, 게이트 FAIL로 종료 1. recorded + `--linkage mock`에서 시드 녹화가 없으면 시드 200건이 미스로 합쳐져 종료 2(목록 50건 + "외 150건"). 형식이 깨진 녹화 파일은 `LLM 녹화본 형식이 올바르지 않습니다`로 종료 2 | 충족. 임베딩 미스는 **M1** |
| test split은 동결 해시가 없으면 거부 | `eval ingest --mode live --split test --confirm-run`, `--mode recorded --split all`, `analyze record --split test --confirm-run`, `analyze record --target seeds --confirm-run`, `bench analyze --split test --confirm-run`, `analyze record-linkage` → 모두 종료 2 "설정 동결 뒤에만". 틀린 해시(`abc`)는 dev에서도 "동결 해시가 현재 설정과 다릅니다". 녹화 디렉터리는 생기지 않았다. 하네스는 `check_frozen_config`를 `build_eval_analyzer`보다 먼저 부른다(`ingest_harness.py:572-575`). 맞는 해시(`analyze freeze` → `817b6a80…`)를 주면 녹화 단계로 넘어가 extra가 없다는 이유로 종료 2 | 충족 (AC-L12) |
| live는 확인 플래그 없이 실행하지 않음 | `eval ingest --mode live`, `analyze record`, `bench analyze`에 플래그 없이 → 셋 다 `예상 소요 시간: 약 13.3분 (48건 × p50 16.6초), 예상 비용: $0.00` 뒤 종료 2, 녹화 파일 없음. 하네스도 `confirm_cost=False` live를 맨 앞에서 거부한다(`ingest_harness.py:556`, 이중 방어). `--confirm-cost` 별칭도 있다 | 충족 |
| live 서비스 경로는 녹화하지 않음 | 탐침 p2: `RecordingLLM.__init__`을 감시하고 `LlamaCppLLM`을 가짜로 바꾼 뒤, live+local 설정으로 `build_container` → `build_ingest_service` → 잡 1건 `run_inline` → `create_app`까지 실행(소켓 차단). **`RecordingLLM` 생성 0회**, 녹화 디렉터리 없음, 네트워크 시도 0. 서비스 쪽에서 `recording=True`를 넘기는 곳은 없다(`grep`, eval·CLI 녹화 명령만) | 충족 (AC-L9) |
| 연결 지표 mock 경로 결정성 | `eval ingest --mode mock --split dev --linkage mock` 2회 + `PYTHONHASHSEED=12345` 1회 → JSON·MD **바이트 동일**. 질의 194, 시드 200 성공, 사람 R@10 0.9543, 분석기(Extractive mock) 0.8527. mock 임베딩 값은 게이트에 넣지 않는다 | 충족 |

### 1.3 그 밖의 범위 항목

| 항목 | 확인 | 결과 |
|---|---|---|
| L-3 항목화 | `_source_text_or_empty`(`ingest_harness.py:775-780`)가 `JupjupError`만 잡아 빈 원문으로 만들고, 파이프라인이 그 건을 `INGEST_EXTRACT_FAILED`로 끝낸다. 테스트 통과 | 충족 |
| T25e 검수 L1 (재요청 응답이 잘리면 그 재요청을 다시 보냄) | `analyzer.py:431-449`의 `last` 추적. 단위 테스트 통과 | 충족 |
| T25e 검수 L2 (분석기 조립 실패에도 dev API 기동) | 탐침 p3: dev+recorded+local에서 녹화가 없을 때와 프로필을 지정하지 않았을 때 모두 `create_app`이 경고 1회(`LLMProviderError` / `ValueError`) 뒤 떴다. `/healthz`는 200 | 충족 |
| T25e 검수 L3 (doctor 판정 일치) | `JUPJUP_MODE=live JUPJUP_ANALYZER__ENGINE=local models doctor` → 경고 "프로필 mock의 engine은 mock", `사용 불가`, 종료 1 | 충족 |
| 입력 오류 | `--profile mock`/없는 프로필/`--linkage bogus`/`--split bogus`/없는 `--profiles` 경로 → 모두 한 줄 안내와 종료 2, 트레이스백 없음 | 충족 |
| 리포트 경로 (AC-L17) | 저장소 밖 녹화 경로를 쓴 리포트 JSON·MD에서 `/Users`·`/private`가 0건. `runtime.recording_files`는 파일 이름만 남는다 | 충족 |
| AC-L15 | `runtime`에 프롬프트 sha256 4종, `recording_model_id`, `frozen_config_sha256`과 확인 여부, 청킹 값, llama-cpp-python 버전(live만)이 있다. 설계 7.2절의 `config.runtime`이 아니라 최상위 `runtime`에 둔 것은 mock 바이트를 지키려는 선택이고 보고서 2절 1번에 적혀 있다 | 충족 |

### 1.4 검색 CLI 회귀·경계값 (`seed load --db var/review.db`, `--now 2026-10-15T12:00+09:00`)

| 질의 (사용자) | mock | recorded | 사본(b6820f2) mock과 비교 |
|---|---|---|---|
| 지난달 성수동 카페 (alice) | 6건 | 6건 | 같음 |
| 성수똥 카패 (오타) | 10건 | `EMBEDDING_CACHE_MISS` 종료 2 (골든 밖 질의, 기존 동작) | 같음 |
| 공백 1칸 | `INVALID_QUERY` 1~200자 | 같음 | 같음 |
| `!!!@@@###` | `INVALID_QUERY` 검색할 단어 없음 | 같음 | 같음 |
| 60자 넘는 긴 질의 / 영어 혼합 `python asyncio 튜토리얼` / 없는 대상 `화성 식민지 부동산 투자` | 0건 | 캐시 미스 종료 2 (기존 동작) | 같음 |
| 필터 전용 `유튜브` / `어제 저장한 인스타` | browse 10건 / browse 0건 | 같음 | 같음 |
| 성수동 카페 (bob / carol) | `c_bob_*` 2건 / `c_carol_*` 1건 (사용자 격리) | 같음 | 같음 |

11건 모두 사본과 비교해 `query_id`와 `timing_ms`만 다르다. 이번 변경은 검색 경로를 건드리지 않았다.

### 1.5 안전성 확인

| 항목 | 확인 | 결과 |
|---|---|---|
| 네트워크 0 (AC-L8) | 소켓 차단 플러그인(`connect/connect_ex/create_connection/getaddrinfo`)으로 `test_ingest_record_replay.py`, `test_local_analyzer_assembly.py`, `test_llm_analyzer.py`, `tests/eval` 실행. 탐침 p1·p2도 같은 방식으로 차단 | 128 passed, **시도 0건**. 탐침도 0건 |
| 녹화 파일에 원문 없음 (AC-L9) | 행 키는 `effort, format_version, kind, max_tokens, model_id, prompt_hash, request_hash, response, schema_name`뿐이다. 미스 목록·Markdown에는 해시와 파라미터만 있다 | 충족 |
| 저장소 녹화 디렉터리 오염 | 모든 실험 뒤 `data/recordings/llm`이 없다 | 충족 |

## 2. 피드백 (심각도 순)

### M1. recorded 연결 지표에서 임베딩 녹화 미스가 미스로 잡히지 않는다 (정확성 −2)

- 위치: `src/jupjup/eval/ingest_linkage.py:117-134` (`_analyze_seeds`), `:176`, `src/jupjup/eval/ingest_harness.py:939-943`
- 재현 (탐침 p5·p6): 제품 mock 분석기(시드 분석은 모두 성공)와 **빈** 연결 녹화 파일로 `run_linkage(embedder="recorded")` 실행 → 예외도 경고도 없이 끝난다. `misses` 0건, 시드 잡 **200건 모두 `failed`, `last_error.code = EMBEDDING_CACHE_MISS`**, 분석기 R@10 0.0735, `recall@10_drop` 0.8977. 하네스(`--linkage recorded`)는 이 값을 그대로 `search_recall@10_drop` 게이트에 넣어 **FAIL(종료 1)** 로 끝내고, 미스 목록에는 아무것도 나오지 않는다(탐침 p4).
- 왜 문제인가: 설계 7.3절은 "미스가 나면 조용히 넘어가지 않는다"고 한다. 연결 녹화가 비었거나 오래됐을 때(분석 녹화를 `--append`로 늘린 뒤 `record-linkage --force`를 다시 안 돌린 경우 등)가 "설정 오류"가 아니라 "분석기가 검색을 0.9 떨어뜨렸다"는 **틀린 품질 결론**으로 나온다. 일부만 빠지면 하락이 조금만 부풀어서 알아채기가 더 어렵다. 이 값이 AC-L6과 후보 채택(8.7절)의 근거다. 하락이 커지는 쪽으로만 틀리므로 거짓 PASS는 아니어서 Medium으로 둔다.
- 개선: recorded 임베딩일 때 `_analyze_seeds`가 `EMBEDDING_CACHE_MISS`로 실패한 잡을 모아 `MissRecord`(예: `kind="embedding"`, `source_id`, `text_hash`)로 `LinkageResult.misses`에 넣거나, `JupjupError`로 run을 멈춰 종료 2가 나게 한다. 사람 쪽 인덱스와 질의 임베딩 미스도 같은 규칙을 따르게 한다. 테스트: 빈 연결 녹화 → 종료 2와 미스 목록.

### L1. recorded 게이트가 연결 지표를 재지 않은 사실을 표시하지 않는다 (정확성 −1)

- 위치: `src/jupjup/eval/ingest_harness.py:936-944`, `:343`, `:352`
- 내용: 3.5.4절 기본 분석기 열에는 "검색 연결 Recall@10 하락 ≤ 0.03"이 들어 있다. 그런데 기본값 `--linkage none`인 recorded 실행에서는 이 행이 게이트에서 아예 빠지고, Markdown에도 "연결 지표 미측정"이라는 표시가 없다. 게다가 리포트 `config`에는 예전 필드 `run_search_linkage: true`가 그대로 찍히고, 실제로 쓰인 `linkage` 값은 `exclude=True`라서 남지 않는다(직접 확인한 recorded 리포트 `config`). 그래서 `recorded --split test` 리포트의 "PASS"가 3.5.4절 열을 다 충족했다는 뜻으로 읽힐 수 있다 (AC-L4 판단 근거가 흐려진다).
- 개선: mock이 아닌 모드에서 `search_linkage`가 `None`이거나 mock 임베딩이면 `search_recall@10_drop`을 `value=None`, "해당 없음 (미측정)" 체크로 넣는다. 게이트에서 빼더라도 Markdown 3.5.4절 표에 한 줄을 남긴다. `runtime`에 `linkage` 모드를 기록한다(mock 바이트에는 영향 없음).

### L2. 동결 해시와 녹화 키에 `n_ctx`가 빠져 있다 (안전성 −1)

- 위치: `src/jupjup/eval/ingest_runtime.py:63-83` (`models[spec.model_id] = [item.sha256 …]`), `src/jupjup/ingest/profiles.py:58`
- 내용: 동결 해시에 들어가는 모델 정보는 파일 sha256뿐이다. `LocalModelSpec.n_ctx`는 `llm_local.py:375`에서 `input_tokens + max_tokens > n_ctx`면 요청을 거부하는 데 쓰여 결과를 바꾼다. 그런데 이 값을 동결 뒤에 바꿔도 해시가 그대로라 test 재평가가 통과된다(AC-L12의 취지: 동결 뒤 설정을 바꾸면 그 프로필은 기각). `chat_template`도 지금은 `"gguf"` 하나뿐이지만 같은 자리에 있다. 설계 8.2절 목록에 `n_ctx`가 명시돼 있지 않아 감점은 1점만 했다.
- 개선: `frozen_config_components`의 `models` 항목에 `measured_p50_s`를 뺀 spec 필드 전체(`n_ctx`, `chat_template`, `source`, 파일 sha256)를 넣는다. 녹화 키(`recording_model_id`)는 형식 v2를 지키려고 바꾸지 않아도 된다. 동결 해시만으로 충분하다.

### L3. 유지보수성 (−2)

- `src/jupjup/cli.py:1197`, `:1223`: CLI가 하네스의 비공개 메서드 `_local_setup()`·`_live_factory()`를 직접 부른다. 공개 메서드로 올리거나 `analyze record` 흐름을 `eval/ingest_runtime.py`의 함수 하나로 옮기는 게 좋다. 지금 `cli.py`의 `analyze record` 본문은 약 70줄이고, 녹화 파일 존재 검사·시드 개수 세기·lexicon 조립 같은 업무 로직을 품고 있다.
- `src/jupjup/cli.py:1219-1221`, `:1268-1270`: "mock 메모리 컨테이너를 만들어 lexicon만 꺼내기"가 두 군데 복붙돼 있다. `Lexicon.load(settings.lexicon_dir)` 같은 헬퍼 하나로 줄일 수 있다.
- `src/jupjup/cli.py:1146`: `analyze freeze`가 `recordings_dir` 자리에 `REPO_ROOT`를 넘긴다. 쓰이지 않는 값이지만 읽는 사람이 헷갈린다. `DEFAULT_LLM_RECORDINGS_DIR`를 넘기는 게 맞다. 같은 명령의 오류 머리말도 "분석기 녹화 오류"다.
- `src/jupjup/eval/ingest_harness.py:398` `_repo_relative`(`os.path.relpath`, 저장소 밖이면 `../..`)와 `src/jupjup/eval/ingest_runtime.py:51` `repo_relative`(저장소 밖이면 파일 이름만)는 같은 목적인데 결과가 다르다. mock 바이트 때문에 앞의 것을 못 바꾼다면, 둘의 차이를 주석으로라도 남긴다.
- `src/jupjup/cli.py:1274`: `analyze record-linkage`의 `except`는 `ValidationError`를 잡지 않는다 (`analyze record`, `bench analyze`는 잡는다). 다른 명령과 맞춘다.

### 참고 (감점 없음)

1. recorded·live의 `latency_p50/p95`는 실패·미스 건을 `0.0`으로 넣어 계산한다(`ingest_harness.py` 항목 루프의 `latency_ms=0.0`). Markdown에 "녹화 시점 값"이라고 적혀 있고 지연 판단은 `bench analyze`로만 하므로 감점하지 않았다. 다만 실패 건을 빼고 계산하는 쪽이 덜 헷갈린다.
2. `AnalyzeBenchReport.within_budget`은 property라 `--out` JSON에 들어가지 않는다. 종료 코드로만 드러난다.
3. `eval ingest --mode live`는 `--append` 검사 없이 기본 `data/recordings/llm`에 녹화한다(보고서 2절 9번, 설계 6.9절). `RecordingLLM._seen` 덕분에 기존 행은 바뀌지 않는다. 그래도 T25h 브리프에 "녹화는 `analyze record`로만"이라고 적어 두길 권한다.
4. 보고서 5절 1번: T25e 검수 R1(실제 Kanana 스모크 2건 실패)은 그대로 남아 있다. T25h 녹화 전에 프롬프트 v2 조정이 필요하다는 판단에 동의한다.
5. dev+recorded에서 분석기 조립이 실패해도 `/healthz`의 `analyzer`는 `"recorded"`로 나온다(설정 기준). 감점 대상인 T25e L2 수정 범위는 아니다. 실제 상태를 반영하면 운영자가 덜 헷갈린다.

## 3. 채점 근거

| 항목 | 점수 | 근거 |
|---|---|---|
| 정확성 | 37 / 40 | 완료 조건 6개, AC-L1·L2·L3·L15·L17, T25e L1~L3 반영을 모두 재현했다. M1 −2 (recorded 연결 지표에서 임베딩 미스가 품질 하락으로 잘못 보고됨), L1 −1 (연결 지표 미측정 표시 없음) |
| 안전성 | 29 / 30 | 네트워크 0, `llama_cpp` 미로드, 서비스 경로 녹화 0, 녹화에 원문 없음, 확인 플래그와 동결 검사가 모델 생성보다 먼저(이중 방어), 입력 오류는 모두 종료 2. L2 −1 (`n_ctx`가 동결 해시에 없음) |
| 유지보수성 | 28 / 30 | 런타임·연결 지표·벤치를 모듈로 분리했고, mock 바이트를 지키는 설계가 명확하며, 테스트 21개가 완료 조건과 1:1로 대응한다. L3 −2 (CLI의 비공개 메서드 호출과 업무 로직, 복붙, 경로 헬퍼 불일치) |
| **합계** | **94 / 100** | **PASS** |

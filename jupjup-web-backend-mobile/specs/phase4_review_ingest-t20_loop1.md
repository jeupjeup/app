# Phase 4 최종 검수: 인제스트 T20(분석용 청킹), Loop 1/3

- **점수:** 94 / 100
- **상태:** PASS
- **항목별:** 정확성 37 / 40, 안전성 29 / 30, 유지보수성 28 / 30
- **루프백 대상:** 없음 (PASS). 아래 중간 1건(M1)과 낮음 항목은 T21/T22 착수 전에 Phase 2에서 `src/jupjup/ingest/chunking.py`를 고쳐 정리하기를 권한다.
- **검수 대상:** `phase-4-review-ingest-t20-loop1` HEAD `4b4fde2` (`feat: implement T20 analysis chunking`). 비교 기준은 T19 Loop 2 검수 커밋 `1e290bf`다. 바뀐 파일은 `src/jupjup/ingest/chunking.py`(신규 315줄), `src/jupjup/ingest/__init__.py`(export 추가), `tests/unit/test_ingest_chunking.py`(신규 13건), 보고서뿐이다.
- **기준 문서:** `specs/prd_and_design.md` 5.10.1절(1260줄 I4), 5.10.2절(1278줄 I4 행), 5.10.4절(1301~1311줄 긴 본문 청킹 전략), 5.10.8절(1384줄 `chunk_for_analysis` 시그니처), 7.3절(1710줄 의존성, 1723줄 T20 행), `specs/known_issues.md`, 이전 검수 `specs/phase4_review_*.md`(특히 `phase4_review_ingest-t19_loop2.md`). T20용 이전 검수 파일은 없다(이번이 첫 루프). 구현 보고서 `specs/phase2_ingest_t20_report.md`의 주장은 모두 직접 다시 확인했다.
- **채점 정책:** T19 Loop 2와 같은 엄격도로 봤다. 사람 검수 0건은 감점하지 않았다. 범위 밖 항목(T21 이후의 분석기, `ChunkNoteExtractor`, 리듀스 실행, 큐, 워커, API, 실제 LLM 연동)은 "참고"로만 적었다.

## 0. 요약

- **T20 완료 조건 네 가지를 직접 만든 입력으로 모두 재현했다.**
  - 경계: 12,000자는 `single`, 12,001자는 `map_reduce`(5청크)다.
  - 구조 단위 우선 분할: 문단을 자르지 않고 합친다. 문단 30개 입력에서 어느 청크에도 온전히 들어가지 않은 문단은 0개다. 너무 큰 단위만 문장, 공백, 문자 순으로 나눈다.
  - 샘플링: 앞 8개, 가운데 균등 12개, 뒤 4개를 고르고 원래 `index`를 유지한다. `coverage="sampled"`, `total_chunks`도 맞다. 24개 이하이면 `full`이다.
  - 결정성: 같은 입력을 두 번 넣으면 `model_dump_json`이 바이트 단위로 같다.
- **설계 시그니처와 일치한다.** `chunk_for_analysis(snapshot: Snapshot, meta: ContentMeta, settings: ChunkSettings) -> AnalysisInput`(1384줄)이다. 5.10.2절의 `AnalysisInput(mode, text?, chunks?, meta)` 필드도 모두 있다. 추가 필드(`coverage`, `source_token_count`, `total_chunks`, 청크 offset)는 5.10.4절 2번의 `coverage="sampled"` 표시와 리듀스 입력에 필요한 범위 안이다.
- **네트워크와 LLM 접근은 0회다.** 순수 함수다. 검색 경로(`search`/`query`/`data`) diff도 0줄이다. eval 4종 수치는 T19 Loop 2 검수 값과 소수점 4자리까지 같다.
- **남은 결함:** 중간 1건, 낮음 여러 건이다.
  - 논문 초록 중복(M1): 본문이 이미 초록으로 시작해도 초록을 한 번 더 붙인다.
  - 제목 단위가 청크 끝에 홀로 남는다(L1).
  - 겹침 구간이 단어 중간에서 시작한다(L2).
  - map_reduce 계획에 offset 기준 원문이 없다(L3).
  - 토큰 계산기 호출 수에 상한이 없다(L4).
  - 테스트에 빈틈이 있다(L5).

## 1. 직접 실행한 명령과 결과

### 1.1 정적 검사, 테스트, 평가 (기본 설치 `uv sync` 환경)

| 명령 | 결과 |
|---|---|
| `uv run pytest` | **746 passed, 3 deselected, 1 warning** (34.4s). T19 Loop 2의 733에 T20 테스트 13건을 더한 값이다. 경고는 기존 Starlette `httpx` 경고다 |
| `uv run pytest tests/unit/test_ingest_chunking.py -q` | 13 passed |
| `uv run ruff check src tests` | All checks passed |
| `uv run ruff format --check src/jupjup/ingest tests/unit/test_ingest_chunking.py` | 7 files already formatted |
| `uv run mypy src` | Success: no issues found in 66 source files |
| `uv run jupjup eval validate` | 통과. seeds 200, queries 259(dev 158/test 101), lexicon 139. ai_draft_unreviewed 235 / needs_human_review 24, reviewed 0 (변화 없음) |
| `eval run --mode mock --split dev --baseline data/baselines/mock.json` | 전부 OK: R@10 0.9620, MRR 0.9958, nDCG 0.9795, true-empty 1.0, false-empty 0.0 |
| `eval run --mode mock --split test …` | 전부 OK: R@10 0.9420, MRR 0.9867, nDCG 0.9589, true-empty 1.0, false-empty 0.0120 |
| `eval run --mode recorded --split dev --baseline data/baselines/recorded.json` | 전부 OK: R@10 0.9712, MRR 1.0000, nDCG 0.9860 |
| `eval run --mode recorded --split test …` | 전부 OK, 종료 코드 0: R@10 0.9720(하한과 같은 값, known_issues 5번 그대로), MRR 0.9911, nDCG 0.9801 |
| `git diff 1e290bf HEAD -- src/jupjup/search src/jupjup/query data \| wc -l` | **0** |
| `grep -nE "socket\|urllib\|http\|requests\|httpx\|subprocess\|anthropic\|openai" src/jupjup/ingest/chunking.py` | 없음 |

eval 수치와 보고서 4절 표가 일치한다. 순위 무회귀를 확인했다.

### 1.2 T20 완료 조건 직접 재현

스크립트는 스크래치 디렉터리에 두고 `uv run python`으로 실행했다. 기본 `ChunkSettings()`(12,000 / 3,000 / 200 / 24)를 쓰고, 필요한 곳만 바꿨다.

| 사례 | 결과 | 판정 |
|---|---|---|
| `"가"*12000` | `single`, source_token_count 12000 | OK |
| `"가"*12001` | `map_reduce`, full, 5청크, 최대 token_count 3200(3,000 + 겹침 200) | OK |
| 문단 30개 × 500자(빈 줄 구분) | 6청크, 모든 `source[start_char:end_char] == chunk.text`. 온전히 들어가지 않은 문단 0, 빠진 비공백 문자 0 | OK |
| 2,990자 단위 24 / 25 / 30 / 100개 | 24 → full. 25 → sampled, 가운데 후보 13개 중 12개(14번 제외). 30 → `[0..7, 8,10,11,13,14,16,17,19,20,22,23,25, 26..29]`. 100 → 100k 상한 때문에 34청크, 24개 선택 | OK |
| `max_chunks` 1/5/8/9/12/13/14 (30청크) | 앞 8 → 뒤 4 → 가운데 순으로 채운다. 중복 없고 정렬이 유지된다 | OK |
| 100,000자 실제 모양 본문 | 36청크 → 24 sampled, 0.003s. 두 번 실행한 JSON이 같다 | OK |
| 1글자 문단 50,000개 / 공백 없는 100,000자 | 0.01s / 0.00s. 둘 다 24 sampled | OK (병리적 입력에도 빠름) |
| 주입 계산기 `(len+1)//2` | 18청크, full. 계산기 호출 884회(L4 참고) | OK |
| 계산기가 0, -1, `True`, `1.5`를 반환 | 모두 `ValueError` | OK |
| 계산기가 `10**9`를 반환 | 무한 루프 없이 1글자 청크로 끝난다 | OK (방어 동작) |
| `ChunkSettings(overlap_tokens=3000)`, `max_chunks=0` | 거부 | OK |
| `token_counter`가 `model_dump()`에서 빠지는지 | 빠진다(직렬화 결정성 유지) | OK |
| T19 `extract_snapshot`(h2+p 12쌍 HTML) → T20 | 12청크. 첫 청크가 `제목 0\n\n문장…`으로 시작한다. 빈 줄 구조를 그대로 받아 쓴다 | OK |
| YouTube 메타(제목, 설명) + 자막 | `제목\n\n설명\n\n자막` 순서 | OK (5.10.4절) |
| 논문 `abstract="이 논문은 초록이다."` + 본문이 같은 초록으로 시작 | `초록\n\n초록\n\n서론 본문`으로 **중복** | **M1** |
| 제목 단위 + 1,400자 본문 × 10 (겹침 0) | 청크 1~4 끝이 `## 섹션 2`, `## 섹션 4` …로 끝난다. 제목이 자기 본문과 떨어진다 | **L1** |
| 기본 겹침 200 | 겹침이 시작되는 글자가 `단어단어…`, `어단어 …`처럼 단어 중간이다 | **L2** |
| 빈 줄 앞 공백(`"…가 \n\n"`) | 정규식 경계는 놓치지만 큰 단위 분할의 공백 우선 규칙이 같은 위치에서 자른다. I2 출력은 줄 끝 공백을 지우므로 정상 경로에서는 생기지 않는다 | 참고 |

### 1.3 CLI 회귀·경계값

`rm -f var/review.db && uv run jupjup seed load --db var/review.db`: 200줄, 적재 200, 인덱싱 200(u_alice 160, u_bob 30, u_carol 10). 검색은 `--db var/review.db --now 2026-10-15T12:00+09:00 --json`이고, `JUPJUP_MODE=mock`과 `recorded`로 각각 실행했다.

| 사례 | mock | recorded | 판정 |
|---|---|---|---|
| `성수 카페` (bob) | 2건 `c_bob_0025`, `c_bob_0026`, 완화 없음 | `EMBEDDING_CACHE_MISS` (녹화본 밖 질의, 기존 동작) | OK |
| `성수 카페` (carol, 사용자 격리) | 1건 `c_carol_0009` (본인 것) | 캐시 미스 | OK |
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
| `--platform kakao` (잘못된 필터 값) | `[INVALID_FILTER]` | 같음 | OK |
| `--user u_nobody` | 저장물이 없다는 안내 | 같음 | OK |

T20은 검색 경로를 건드리지 않았다(diff 0줄). 위 결과는 T19 Loop 2 검수 표와 같다.

## 2. 피드백 (심각도 순)

### M1. 중간: 논문 초록이 본문 앞에 중복될 수 있다 — `src/jupjup/ingest/chunking.py:154-157`

- **현상:** `source_parts[0] != abstract`는 **본문 전체**를 초록과 비교한다. 본문이 초록과 정확히 같을 때만 중복을 막는다. 논문 HTML은 보통 본문 첫 블록에 초록이 있어서(T19가 `\n\n`으로 보존), 실제로는 거의 항상 초록이 두 번 들어간다.
- **재현:** `ContentMeta(content_type="paper", abstract="이 논문은 초록이다.")`와 `Snapshot.text="이 논문은 초록이다.\n\n서론 본문"` → `_analysis_source` 결과가 `"이 논문은 초록이다.\n\n이 논문은 초록이다.\n\n서론 본문"`이다.
- **영향:**
  - 토큰 수가 부풀어 12,000 경계 근처 문서가 `map_reduce`로 넘어갈 수 있다. 정확도를 위해 가능한 한 한 번에 넣는다는 5.10.4절 원칙과 반대 방향이다.
  - 첫 청크(리듀스의 "첫 청크 원문 1,500토큰")를 같은 문장이 차지한다.
  - 같은 문장이 두 번 보여 근거(evidence)가 중복될 수 있다.
- **개선:**
  - 첫 구조 단위(첫 `\n\n` 앞)나 본문 앞부분을 정규화해 비교한다(`body.startswith(abstract)` 또는 첫 단위 == 초록).
  - 이미 있으면 넣지 않는다.
  - 회귀 테스트를 추가한다.
  - YouTube 제목·설명에도 같은 접두 중복 검사를 적용하면 일관된다(현재 YouTube는 중복을 검사하지 않는다).

### L1. 낮음: 제목 단위가 청크 끝에 홀로 남는다 — `src/jupjup/ingest/chunking.py:237-250`

- **현상:** 5.10.4절 1번은 HTML 제목(h1~h3)을 구조 경계로 든다. 그런데 `_base_chunk_spans`는 제목 블록을 일반 문단과 똑같이 다룬다. 다음 본문이 안 들어가면 제목이 앞 청크 끝에 붙고, 본문은 다음 청크로 넘어간다. 재현 결과 청크 1~4가 모두 `## 섹션 N`으로 끝났다.
- **영향:** 맵 단계에서 섹션 본문이 제목 맥락을 잃는다. 앞 청크에는 내용 없는 제목만 남는다. 겹침 200이 일부를 덮지만 겹침이 0인 설정이나 긴 제목에서는 덮지 못한다.
- **개선:** 짧은 단위(예: 한 줄이고 문장 종결부호가 없으며 토큰 수가 작음)가 청크의 마지막 단위가 되면 다음 청크로 넘긴다. 다른 방법은 짧은 제목형 단위를 다음 단위와 미리 묶는 것이다. 저장된 텍스트에 태그가 없다는 보고서 5절의 제약 안에서도 할 수 있다.

### L2. 낮음: 겹침 구간이 단어·문장 중간에서 시작한다 — `src/jupjup/ingest/chunking.py:284-293`

- **현상:** `_suffix_start`는 토큰 수만 보고 이분 탐색으로 시작점을 고르고, 경계를 맞추지 않는다. 100k 본문에서 겹침이 `어단어 …`, `장입니다. 문장`처럼 잘린 단어로 시작했다.
- **영향:** 맵 입력이 깨진 조각으로 시작한다. 큰 문제는 아니지만 인용(`quotes`)이나 문장 번호(`evidence_ids`)를 달 때 첫 문장이 불완전하다.
- **개선:** 찾은 시작점에서 같은 이전 청크 범위 안의 다음 문장 경계나 공백 경계로 앞당긴다(`_preferred_split`과 같은 규칙). 그러면 겹침이 200 이하에서 조금 줄어든다.

### L3. 낮음: map_reduce 계획에 offset 기준 원문이 없다 — `src/jupjup/ingest/chunking.py:62-75`, `:82-91`, `:144-158`

- **현상:** `AnalysisChunk.start_char/end_char`는 "complete analysis source text" 기준이다. 그런데 `map_reduce` 모드의 `AnalysisInput`에는 그 원문이 없다(`text=None`). 원문을 만드는 `_analysis_source`도 비공개 함수다. T21/T22 소비자가 offset을 쓰려면 비공개 함수를 다시 불러 같은 문자열을 재구성해야 한다.
- **개선:** 아래 둘 중 하나를 고른다.
  - `_analysis_source`를 공개 함수로 승격하고, `AnalysisInput`에 원문 해시(`source_hash`)를 넣어 소비자가 대조할 수 있게 한다.
  - offset이 무엇의 기준인지 docstring에 명시한다.
- 덧붙여 `AnalysisInput` 검증기가 청크 `index`의 엄격한 증가와 `end_char` 단조성을 확인하지 않는다. 외부에서 계획을 만들어 넣으면 잘못된 순서도 통과한다.

### L4. 낮음: 토큰 계산기 호출 수에 상한과 메모이제이션이 없다 — `src/jupjup/ingest/chunking.py:167-174`, `:216-229`, `:237-250`, `:284-293`

- **현상:** 이분 탐색과 병합 판단마다 계산기를 다시 부른다. 100k 본문에서 884회 불렀다. `len` 기본값에서는 문제가 없다(0.003s).
- **영향 (참고, T21 이후):** 5.10.4절은 "제공자 어댑터의 `count_tokens`"를 쓰라고 한다. Anthropic의 토큰 계산은 원격 API라서, 그대로 연결하면 문서 하나에 수백 번 네트워크를 호출한다. 그러면 비용, 지연, 분당 요청 상한(5.10.3절)에 걸린다.
- **개선:**
  - `TokenCounter` docstring에 "로컬, 결정적, 저비용 함수만 넣는다"는 계약을 명시한다.
  - 같은 `(start, end)` 범위의 결과를 캐시한다.
  - 다른 방법: 전체 토큰만 제공자로 재고, 내부 분할은 비율 추정으로 한다.

### L5. 낮음: 테스트 빈틈 — `tests/unit/test_ingest_chunking.py`

- 다음 사례를 고정하는 테스트가 없다.
  - M1(본문이 초록으로 시작하는 논문)
  - L1(제목 단위가 청크 끝에 남는 경우)
  - `max_chunks < 12`일 때 앞 → 뒤 → 가운데 우선순위(예: `max_chunks=9` → `[0..7, 29]`)
  - T19 `extract_snapshot` 출력을 그대로 받는 I2 → I4 연결 사례(HTML 제목·문단, 3분 자막 구간)
- 결정성 테스트는 같은 프로세스 안 두 번 실행만 본다. 입력 dict 순서나 `token_counter` 유무와 무관하게 `model_dump_json`이 같은지 확인하는 사례를 더하면 T22 단계 멱등성의 근거가 된다.

### 참고 (감점 없음)

- `chunking.py:153`: YouTube는 제목과 설명을 원문에 포함해 12,000 경계를 잰다. 5.10.4절은 "정규화 본문" 기준이다. 하지만 같은 절이 YouTube 입력 순서를 제목 → 설명 → 자막으로 정하므로, 실제 모델 입력 크기로 재는 해석이 합리적이다.
- `chunking.py:21`: 빈 줄 앞에 공백이 있으면 구조 경계를 놓친다. 하지만 큰 단위 분할의 공백 우선 규칙이 결과적으로 같은 곳에서 자르고, I2 `tidy_snapshot_text`가 줄 끝 공백을 지운다. 정상 경로에서는 영향이 없다.
- `chunking.py:310-314`: 가운데 12개 선택이 가운데 후보의 양 끝(8번, N−5번)을 포함한다. "균등 간격"을 양 끝 포함으로 해석했고, 보고서 1절에 그렇게 적었다. 설계와 충돌하지 않는다.
- 빈 snapshot을 `ValueError`로 거부한다. 5.10.2절의 "실패 분류 없음"과 맞지 않아 보일 수 있지만, 정상 I2 출력에서는 생길 수 없는 입력에 대한 방어라서 타당하다. T22에서 이 예외를 영구 실패로 분류할지는 그때 정한다.

## 3. 채점 근거

| 항목 | 점수 | 근거 |
|---|---|---|
| 정확성 | 37 / 40 | 완료 조건 4개, 시그니처, 5.10.2절 필드, YouTube 순서를 모두 충족한다. M1 초록 중복으로 −2(정상 논문 입력에서 재현되고 경계 판정에 영향), L1·L2 구조·경계 품질로 −1 |
| 안전성 | 29 / 30 | 순수 함수이고 네트워크 접근이 없다. 설정과 계산기 반환값을 검증하고, 무한 루프를 막고, 100k 병리적 입력도 0.01s 안에 끝난다. 계산기 호출 수에 상한이나 계약이 없어(L4) −1 |
| 유지보수성 | 28 / 30 | frozen Pydantic 모델과 명확한 불변식, 작은 함수 분리, 일관된 export가 좋다. offset 기준 원문이 계획 밖 비공개 함수에 있어(L3) −1, 회귀 테스트 빈틈(L5)으로 −1 |
| **합계** | **94 / 100** | **PASS** |

## 4. PM 조치 제안

- PASS이므로 T20 루프를 끝내고 PM 브랜치 병합을 진행해도 된다.
- T21/T22 착수 전에 M1과 L1~L5를 작은 Phase 2 후속(`chunking.py`와 테스트만)으로 정리하기를 권한다. 특히 L4의 계산기 계약은 T25에서 Anthropic `count_tokens`를 연결하기 전에 정해야 한다.

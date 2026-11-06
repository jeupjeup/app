# Phase 4 최종 검수: 인제스트 T22(잡 큐, 워커, 단계 실행), Loop 1/3

- **점수:** 87 / 100
- **상태:** REJECT
- **항목별:** 정확성 34 / 40, 안전성 26 / 30, 유지보수성 27 / 30
- **루프백 대상:** Phase 2 (기능/버그 문제). H1(lease 소유권), M1(`run_forever` 생존), M2(캐시 미스 재시도 분류)를 고친 뒤 재검수한다.
- **검수 대상:** `phase-4-review-ingest-t22-loop1` HEAD `50249c4` (`feat: implement T22 ingest jobs worker`). 비교 기준은 T21 Loop 1 검수 커밋 `f3d0196`이다.
  - 신규: `src/jupjup/ingest/jobs.py`(386줄), `src/jupjup/ingest/worker.py`(438줄), `src/jupjup/ingest/service.py`(147줄), `tests/unit/test_ingest_jobs.py`(7건), `tests/integration/test_ingest_pipeline.py`(3건)
  - 변경: `storage/tables.py`(`ingest_jobs`, `ingest_job_events`, `analysis_runs`), `storage/repositories.py`(`analysis_run_id` 왕복, `upsert_in_transaction`), `domain/models.py`(`analysis_run_id` 2필드), `domain/errors.py`(`StorageError`, `IndexingError`), `index/service.py`(`index_reduced`, `embed_content`)
- **기준 문서:** `specs/prd_and_design.md` 5.10.1절(1251~1270줄 단계 흐름, 멱등, 축약 인덱스, 사용자 수정값), 5.10.2절(1272~1282줄 단계별 실패 분류), 5.10.3절(1284~1299줄 큐, 상태 전이, 재시도 정책, 우선순위, 관측), 5.10.8절 1429~1450줄 시그니처, 6.2절 `ingest_jobs`/`ingest_job_events`/`analysis_runs`(1551~1588줄), 7.3절 T22 행(1725줄), AC-24(1752줄), AC-26(1754줄). `specs/known_issues.md`, 이전 검수 `specs/phase4_review_*.md`(특히 `phase4_review_ingest-t21_loop1.md`). T22 이전 검수 파일은 없다(이번이 첫 루프).
- **채점 정책:** T21 Loop 1과 같은 엄격도로 봤다. 사람 검수 0건은 감점하지 않았다. 범위 밖 항목(T23 API·CLI, T24 인제스트 평가, 실제 LLM 연동과 그 세마포어)은 "참고"로만 적었다. 구현 보고서 `specs/phase2_ingest_t22_report.md`의 주장은 모두 직접 다시 확인했다.

## 0. 요약

- **T22 완료 조건 대부분이 직접 만든 입력으로 재현된다.**
  - 상태 전이 표: `queued → running → (I1~I8) → succeeded`, `running → retry_wait → (due) → running → succeeded`, 재시도 소진 → `failed`, 영구 오류 → `failed`, refusal → `needs_review`가 모두 나온다(1.2절).
  - lease 만료 회수: `lease_until == now` 경계에서는 회수하지 않고, 1초 뒤 다른 워커가 **같은 단계**로 회수한다.
  - 백오프: 주입 시계로 `next_run_at` 이전에는 `run_once`가 False이고, due 시각에 재개한다. 지연은 `2·2^(n−1)·(1±0.2)`, 300초 상한, `job_id/stage/attempt` 해시로 결정적이다.
  - 단계 멱등성: 성공한 잡의 I1~I8을 모두 다시 실행해도 bundle이 필드 단위로 같고, snapshot 1행, analysis_runs 1행이다.
  - 사용자 수정값 보존: 재분석 뒤 user summary, user tag, detail `user_patch`, `user_note`, `hidden_tags`가 그대로이고 AI 이력만 늘어난다.
  - 축약 인덱스: I2 직후 `analysis_pending=true` 상태에서 실제 `SearchService`가 결과를 낸다.
  - AC-24: text, HTML fixture, VTT 자막 fixture, OCR 이미지가 각각 `ready`까지 가서 검색된다.
- **설계 시그니처와 맞다.** `JobQueue.enqueue/lease/advance/fail/get`, `IngestWorker(queue, stages, clock, retry)`, `run_once/run_forever`, `IngestService.submit/reanalyze/run_inline/status`가 1429~1450줄과 맞는다. 추가 인자는 모두 키워드 전용이거나 기본값이 있다. 테이블은 6.2절 컬럼에 `stage_data`와 `analysis_runs.job_id UNIQUE`를 더했다(보고서에 근거 기재, 타당).
- **네트워크와 LLM 접근은 0회다.** 소켓 `connect`와 `create_connection`을 막은 상태에서 재현 스크립트 3개가 모두 통과했다. 새 모듈 세 개에 네트워크 import가 없다.
- **검색 순위는 회귀하지 않았다.** `git diff f3d0196 HEAD -- src/jupjup/search src/jupjup/query data`는 0줄이다. eval 4종 수치는 T21 Loop 1 검수 값과 소수점 4자리까지 같다. CLI 회귀·경계값 표도 T21 검수 표와 같다.
- **REJECT 사유는 잡 큐의 안전성 결함 3건이다.**
  - **H1 (높음):** lease를 잃은 워커도 `advance`/`fail`/`put_artifact`를 할 수 있다. 회수한 워커가 단계를 실행하는 중에 옛 워커가 단계를 넘기거나 새 소유자의 lease를 풀어 버린다. 한 `IngestWorker`의 스레드들은 같은 `worker_id`를 공유해서 `begin_stage`의 소유자 확인도 스레드 사이에서는 효과가 없다.
  - **M1 (중간):** `run_forever`는 `run_once`에서 새어 나온 예외 하나(`InvalidJobTransition`, SQLite `database is locked` 등)에 루프 전체가 죽는다.
  - **M2 (중간):** I2/I8이 모든 예외를 재시도형 `IndexingError`로 감싸서, 영구 오류인 `EmbeddingCacheMiss`가 3회 재시도된 뒤 `INDEX_UNAVAILABLE`로 기록된다. AC-26의 "재시도 대상 오류와 아닌 오류 구분"이 이 경로에서 깨진다.

## 1. 직접 실행한 명령과 결과

### 1.1 정적 검사, 테스트, 평가 (기본 설치 `uv sync` 환경)

| 명령 | 결과 |
|---|---|
| `uv run pytest` | **763 passed, 3 deselected** (35.5s). T21 검수 때의 753에 T22 테스트 10건을 더한 값이다. 경고 1건은 기존 Starlette `httpx` 경고다 |
| `uv run ruff check src tests` | All checks passed |
| `uv run mypy src` | Success: no issues found in 72 source files |
| `uv run jupjup eval validate` | 통과. seeds 200, queries 259(dev 158/test 101), lexicon 139. ai_draft_unreviewed 235 / needs_human_review 24, reviewed 0 (변화 없음) |
| `eval run --mode mock --split dev --baseline data/baselines/mock.json` | PASS, 종료 코드 0: R@10 0.9620, MRR 0.9958, nDCG 0.9795, true-empty 1.0 |
| `eval run --mode mock --split test …` | PASS: R@10 0.9420, MRR 0.9867, nDCG 0.9589, false-empty 0.0120 |
| `eval run --mode recorded --split dev --baseline data/baselines/recorded.json` | PASS: R@10 0.9712, MRR 1.0000, nDCG 0.9860 |
| `eval run --mode recorded --split test …` | PASS: R@10 0.9720(하한과 같은 값, known_issues 5번 그대로), MRR 0.9911, nDCG 0.9801 |
| `git diff f3d0196 HEAD -- src/jupjup/search src/jupjup/query data \| wc -l` | **0** |
| `grep -nE "socket\|urllib\|requests\|httpx\|subprocess\|anthropic\|openai\|http"` (jobs.py, worker.py, service.py) | 없음 |

### 1.2 상태 전이, lease, 백오프, 분류 직접 재현

스크래치 디렉터리의 `uv run python -I` 스크립트 3개로 실행했다. 소켓을 막았고, 시계는 주입한 가변 `Clock`을 썼다. 분석기는 통합 테스트의 `DeterministicAnalyzer`를 감싼 대역(일시 실패, 영구 실패, 느린 분석)이다.

| 사례 | 결과 | 판정 |
|---|---|---|
| `RetryPolicy().delay("job_x","analyze",n)`, n=1..9 | 2.31, 3.71, 6.83, 18.54, 38.11, 71.59, 109.94, 252.10, 300.0초. 같은 입력은 같은 값, 다른 `job_id`는 다른 값 | OK (±20% 범위, 상한 300초) |
| analyze가 503 `LLMProviderError` 2회 뒤 성공 | 1회차 `retry_wait`(next_run_at +1.72초), due 전 `run_once()` False, 2회차 `retry_wait`(+3.6초), 3회차 `succeeded`, 콘텐츠 `ready`. attempts `{analyze: 3, 나머지: 1}` | OK |
| analyze가 계속 `LLMProviderError` | 3회 뒤 `failed`, `LLM_UNAVAILABLE`, 콘텐츠 `analysis_failed` | OK (analyze max 3) |
| analyze가 `LLMRefusalError` | `needs_review`, 콘텐츠 `analysis_failed`, `analysis_pending=true`. 축약 인덱스로 여전히 검색됨 | OK (enum 차이는 보고서 5번에 기재) |
| 공백만 있는 text | extract에서 `failed`, `INGEST_EXTRACT_FAILED`, 재시도 없음 | OK |
| 없는 fixture / `../../etc/passwd` | fetch에서 `failed`, `INGEST_UNSUPPORTED`, 재시도 없음 | OK |
| `is_retryable_error` 18가지 | Fetch(무상태)·Vision·LLMProvider·EmbeddingProvider·Storage·Indexing → True. status 404/400 → False, 429/503 → True. Unsupported·Extraction·Schema·Refusal·LLMCacheMiss·일반 `JupjupError` → False. `{"status": True}`는 bool을 무시하고 타입 기준 True | OK |
| lease 300초, `now+300초`에 다른 워커 lease | `None` (경계 `<`) | OK |
| `now+301초`에 B가 lease | `running`, 단계 `fetch` 그대로, `leased_by=B` | OK |
| 위 상태에서 **옛 워커 A가 `advance(job, "extract")`** | **받아들여진다.** 단계가 `extract`로 넘어가고 `leased_by`는 B 그대로 | **H1** |
| 같은 상태에서 A가 `fail(..., retryable=True)` | **받아들여진다.** `retry_wait`, `leased_by=None`. B는 아직 실행 중 | **H1** |
| 워커 단위: A의 analyze가 400초 걸리는 동안 B가 `run_once()` | B가 analyze를 다시 실행해 `succeeded`까지 간다. 이어서 A의 `run_once()`는 `InvalidJobTransition: running 잡만 진행할 수 있습니다`를 **밖으로 던진다**. analyze 호출 2회 | **H1, M1** |
| `run_forever`에서 첫 `lease`가 `OperationalError("database is locked")` | `run_forever`가 그 예외로 종료된다(재시도 0회) | **M1** |
| recorded 모드 컨테이너, 녹화본에 없는 새 text 인제스트 | extract에서 `retry_wait` → `retry_wait` → `failed`. 3회 모두 `INDEX_UNAVAILABLE`, details `{"type": "EmbeddingCacheMiss"}` | **M2** |
| 성공한 HTML 잡에 `run_inline` 다시 호출 | 실행하지 않고 `succeeded` 그대로, attempts 변화 없음 | OK |
| 성공한 HTML 잡의 I1~I8 전부 다시 실행 | bundle이 필드 단위로 같다(시각 제외). snapshot id 같음, summaries 1개, analysis_runs 1행, snapshots 1행 | OK (멱등) |
| `ready` 콘텐츠에 재분석, analyze가 `AnalysisSchemaError` | 잡 `failed`, 콘텐츠 `analysis_failed`. 이전 AI summary와 인덱스는 남는다 | L3 |
| `status("u_b", A의 job)` / `reanalyze("u_b", A의 content)` | 둘 다 `NotFoundError` | OK (격리) |
| u_b가 "비밀코끼리" 인제스트 후 u_a 검색 | u_a 0건, u_b 1건 | OK (격리) |
| 1자 `"a"`, 특수문자·`<script>`·SQL 조각, 영어 혼합, 6만 자 | 모두 `succeeded`/`ready`. `useEffect cleanup` 검색 1위 | OK |
| analyze가 `LLMProviderError("fail", {"raw": 원문})` | `last_error`와 이벤트 detail에 원문이 그대로 남는다 | L1 (현재 제공자는 원문을 details에 넣지 않음) |
| 고정 시계에서 `queue.events(job)` 순서 | 같은 `at`끼리 uuid 순서라 `analyze started, persist started, index started, analyze succeeded…`처럼 섞인다 | L4 |

### 1.3 CLI 회귀·경계값 (`uv run jupjup seed load --db var/review.db` 후 `--now 2026-10-15T12:00+09:00`)

시드 적재: 200줄, 적재 200, 인덱싱 200, 임베딩 대기 0 (u_alice 160, u_bob 30, u_carol 10).

| 사례 | mock | recorded(`JUPJUP_MODE=recorded`) | 판정 |
|---|---|---|---|
| `성수 카페` (bob) | `c_bob_0025`, `c_bob_0026`, 완화 없음 | `EMBEDDING_CACHE_MISS` (녹화본 밖 질의, 기존 동작) | OK |
| `성수 카페` (carol, 사용자 격리) | `c_carol_0009`(본인 것만) | 캐시 미스 | OK |
| `성슈 카페` (오타) | 같은 2건 | 캐시 미스 | OK |
| 빈 문자열 / 600자 | `[INVALID_QUERY] 질의는 1~200자여야 해요.` | 같음 | OK |
| `!!@@##$$%%` (특수문자) | `[INVALID_QUERY] 검색할 단어가 없어요.` | 같음 | OK |
| `지난주 유튜브` (필터 전용) | `c_alice_0043` | 같음 | OK |
| `경주 맛집 인스타` (과소 완화 회귀) | `c_alice_0153`, `platform_filter_dropped` | 같음 | OK |
| `하체 운동 유튜브` | 1위 `c_alice_0040`, `platform_filter_dropped` | 같음 | OK |
| `다리 운동 영상` (known_issues 4) | 1위 `c_alice_0040`, 완화 없음 | 1위 `c_alice_0040` | OK |
| `경주 맛집 카톡 논문` (이중 완화 기록) | `platform_filter_dropped`, `content_type_filter_dropped` | 같음 | OK |
| `python 강의 영상` (영어 혼합) | 4건, 1위 `c_alice_0056` | 캐시 미스 | OK |
| `화성 기지 건설 계획` (없는 대상, 과잉 완화) | 0건, 완화 없음 | 캐시 미스 | OK |
| `--platform instagram "경주 맛집"` (요청 잠금) | 0건, 완화 없음 | 같음 | OK |
| `--platform kakao` (잘못된 필터 값) | `[INVALID_FILTER] 필터 값이 올바르지 않아요.` | 같음 | OK |
| `--user u_nobody` | 저장물이 없다는 안내 뒤 빈 결과 | 같음 | OK |

T22는 검색 경로를 건드리지 않았다(diff 0줄). 위 결과는 T21 Loop 1 검수 표와 같다.

## 2. 피드백 (심각도 순)

### H1. 높음: lease를 잃은 워커의 쓰기를 막지 않는다 — `src/jupjup/ingest/jobs.py:235-252`(`advance`), `:254-298`(`fail`), `:300-311`(`put_artifact`), `:202-206`(`begin_stage`), `src/jupjup/ingest/worker.py:138`, `:156-184`

- **현상:**
  - `advance`와 `fail`은 `status == "running"`만 확인하고 `leased_by`와 `lease_until`을 보지 않는다. `put_artifact`는 상태도 보지 않는다.
  - `begin_stage`와 `renew_lease`는 `leased_by == worker_id`를 보지만, `worker_id`가 `IngestWorker` 인스턴스 단위(`worker.py:138`)라서 `run_forever`의 스레드 2개가 같은 값을 쓴다. 같은 프로세스 안에서 lease가 만료되어 다른 스레드가 회수하면 두 스레드 모두 소유자 확인을 통과한다.
  - lease는 단계 시작 때만 갱신한다(`begin_stage`). 단계가 실행되는 동안에는 갱신하지 않는다.
- **재현(1.2절):**
  - A lease → 301초 뒤 B 회수 → A `advance(job, "extract")`가 성공하고 단계가 넘어간다. B는 fetch를 실행하는 중인데 잡은 이미 extract다.
  - 같은 상태에서 A `fail(..., retryable=True)`가 성공하고 `leased_by=None`, `retry_wait`가 된다. B가 실행 중인 잡을 다른 워커가 다시 lease할 수 있다.
  - 워커 단위: A의 analyze가 400초 걸리는 동안 B가 회수해 끝까지 실행한다. A는 그 뒤 `advance`에서 `InvalidJobTransition`을 밖으로 던진다. analyze 호출이 2회다(실제 LLM이면 비용 2배).
- **설계와 충돌하는 지점:** 5.10.3절 "running이 lease 만료 → 다른 워커가 회수 (그 stage부터 재개)"와 T22 완료 조건 "lease 만료 회수"는 회수 뒤 소유권이 새 워커로 넘어간다는 뜻이다. 지금은 회수 자체는 되지만 옛 소유자를 배제하지 못한다.
- **영향:** 단계 건너뜀(B가 실행 중인 fetch 결과 없이 extract로 진행), 같은 단계 동시 실행, 새 소유자의 lease 해제, 옛 워커 스레드의 예외 종료(M1과 겹쳐 워커 프로세스 정지).
- **개선 방향:**
  - lease마다 고유 토큰(예: `lease_id = uuid`)을 발급해 `JobRecord`에 담고, `begin_stage`/`renew_lease`/`advance`/`fail`/`put_artifact`의 UPDATE 조건에 `leased_by = :token AND status = 'running'`을 넣는다. rowcount 0이면 `LeaseLostError` 같은 전용 예외를 낸다.
  - `_run_leased`는 `LeaseLostError`를 받으면 조용히 손을 뗀다(결과 기록 없이 반환). `run_once`는 예외를 밖으로 던지지 않는다.
  - 필요하면 긴 단계(analyze)는 실행 중에 `renew_lease`를 호출할 수 있게 한다(heartbeat). 최소한 lease 시간과 단계 타임아웃의 관계를 문서에 적는다.
  - 테스트: 위 세 재현을 그대로 단위 테스트로 고정한다(옛 소유자의 advance/fail/put_artifact 거부, 같은 `IngestWorker`의 두 스레드 사이 회수).

### M1. 중간: `run_forever`가 예외 하나에 종료된다 — `src/jupjup/ingest/worker.py:195-208`, 특히 `:206`

- **현상:** `future.result()`가 `run_once`의 예외를 그대로 다시 던지고, `run_forever`는 이를 잡지 않는다. `_run_leased`는 단계 실행기의 예외만 잡고, `queue.lease`/`begin_stage`/`advance`/`fail`에서 나는 예외(`InvalidJobTransition`, `SQLAlchemyError`)는 잡지 않는다.
- **재현:** 첫 `lease` 호출이 `OperationalError("database is locked")`를 던지게 하면 `run_forever`가 즉시 그 예외로 끝난다(1.2절). H1 재현에서도 A의 `run_once`가 `InvalidJobTransition`을 던진다.
- **영향:** SQLite 단일 파일에 스레드 2개가 쓰는 구조라 `database is locked`는 실제로 날 수 있는 일시 오류다. `jupjup worker run`(T23)이 이 루프를 그대로 쓰면 일시 오류 한 번에 워커가 멈추고, 그동안 잡은 lease 만료까지 `running`으로 남는다.
- **개선 방향:** `run_forever`에서 future별 예외를 잡아 구조화 로그(원문 없이 타입·job_id만)를 남기고 짧은 대기 뒤 계속한다. `advance` 실패처럼 단계 실행 뒤의 큐 오류는 lease 만료 회수로 복구된다는 점을 docstring에 적는다. "예외가 나도 다음 잡을 처리한다"를 테스트로 고정한다.

### M2. 중간: I2/I8이 영구 오류를 재시도형 `IndexingError`로 감싼다 — `src/jupjup/ingest/worker.py:291-294`, `:425-428`, 연관 `src/jupjup/index/service.py:104-114`

- **현상:** `extract`와 `index`는 `except Exception`으로 모든 예외를 `IndexingError`(재시도형)로 바꾼다. `prepare_bundle`은 `EmbeddingProviderError`만 잡아 키워드 전용으로 넘어가는데, `EmbeddingCacheMiss`는 `EmbeddingProviderError`의 하위 클래스가 아니다(`domain/errors.py:41-47`). 그래서 recorded 모드의 캐시 미스가 I2에서 재시도형으로 바뀐다.
- **재현:** recorded 컨테이너에서 녹화본에 없는 새 text를 인제스트하면 extract에서 `retry_wait` 2회 뒤 `failed`이고, `last_error.code`는 3회 모두 `INDEX_UNAVAILABLE`, `details={"type": "EmbeddingCacheMiss"}`다(1.2절).
- **설계와 충돌하는 지점:**
  - 5.10.3절 "429와 5xx, 연결 오류, 타임아웃만 재시도 대상이다"와 AC-26 "재시도 대상 오류와 아닌 오류가 구분된다". `is_retryable_error`는 `EmbeddingCacheMiss`를 영구로 분류하지만(`worker.py:110-111`), 감싸기 때문에 그 분기에 닿지 않는다.
  - 5.10.1절의 I2 축약 인덱싱은 "저장 직후에도 검색에 걸리게" 하는 보조 단계다. 임베딩 실패로 잡 전체를 실패시키기보다는 키워드 인덱스만 게시하고 I7에서 판정하는 편이 설계 의도에 맞다.
- **영향:** T24 인제스트 평가가 recorded 모드로 새 원문을 돌리면, 캐시 미스가 원인인데 "인덱스 불가"로 기록되고 의미 없는 재시도 3회를 거친다. 프로그래밍 오류(`TypeError` 등)도 재시도형으로 숨는다.
- **개선 방향:** `JupjupError`는 감싸지 말고 그대로 다시 던진다(분류는 `is_retryable_error`에 맡긴다). I2는 캐시 미스를 포함한 임베딩 실패에서 키워드 인덱스만 게시하도록 한다. 테스트: recorded 캐시 미스 인제스트가 재시도 없이 영구 실패(또는 I2 키워드 게시 후 I7 영구 실패)하는지 고정한다.

### L1. 낮음: `last_error`와 이벤트 detail에 `err.details`를 그대로 저장한다 — `src/jupjup/ingest/jobs.py:277-279`, `:292`

- 5.10.3절과 6.2절은 "본문 원문은 로그에 남기지 않는다", `last_error`는 "본문 원문 미포함"이다. 지금은 허용 목록 없이 details 전체를 넣는다. 현재 제공자와 T18 검증기는 원문을 details에 넣지 않아서 실제 누출은 확인되지 않았다. 하지만 분석기 대역이 `{"raw": 원문}`을 넣으면 그대로 남는다(1.2절). T25 실제 분석기 전에 키 허용 목록이나 길이 상한을 두기를 권한다.

### L2. 낮음: 단계가 bundle 전체를 읽고 통째로 다시 쓰며, 같은 콘텐츠의 잡이 동시에 돌 수 있다 — `src/jupjup/ingest/worker.py:266`/`:290`, `:306`/`:316`, `:350`/`:418`, `:424`/`:432`, `src/jupjup/ingest/service.py:95-118`

- `upsert`는 snapshots/summaries/tags/detail_tags를 지운 뒤 다시 넣는다(`repositories.py:98-99`). 특히 `index`는 인덱싱 전에 읽은 bundle을 인덱싱 뒤에 쓴다. 그 사이의 다른 쓰기는 사라진다.
- `reanalyze`는 같은 콘텐츠에 진행 중인 잡이 있는지 확인하지 않는다. 인제스트 잡이 I5에 있을 때 재분석을 넣으면 두 잡이 `concurrency=2`에서 동시에 같은 bundle을 덮어쓸 수 있다.
- 지금은 사용자 수정 API가 없어서 실제 손실 경로는 잡끼리의 경합뿐이다. T23에서 수정 API가 생기기 전에 콘텐츠 단위 잡 배타(진행 중 잡이 있으면 거부하거나 대기)와 상태 필드만 바꾸는 부분 갱신을 권한다.

### L3. 낮음: 재분석 실패와 refusal이 `ready` 콘텐츠를 `analysis_failed`로 바꾼다 — `src/jupjup/ingest/jobs.py:293-298`

- 이전 분석과 인덱스는 그대로인데 콘텐츠 상태만 `analysis_failed`가 된다(1.2절). 6.2절 enum에 맞는 값이 없다는 점은 보고서 5번에 적혀 있지만, 재분석(`kind="reanalyze"`) 실패는 이전 상태(`ready`)를 유지하는 편이 상태 의미에 맞다. 설계 쪽 결정이 필요하면 Architect에 넘긴다.

### L4. 낮음: 같은 시각 이벤트의 순서가 무작위다 — `src/jupjup/ingest/jobs.py:325`, `:379`

- `order_by(at, id)`인데 `id`가 uuid4라서 같은 `at`끼리 순서가 섞인다. 주입 시계 테스트와 ms 단위 동시 기록에서 이벤트 로그가 `analyze started, persist started, index started, analyze succeeded…`처럼 보인다. 자동 증가 seq 컬럼이나 단조 id(시각+카운터)를 권한다. 현재 테스트는 시각을 일부러 벌려 이 문제를 피한다(`test_ingest_jobs.py:51-54`).

### L5. 낮음: 테스트 공백과 소소한 견고성 — `tests/unit/test_ingest_jobs.py`, `src/jupjup/ingest/worker.py:307`

- 테스트에 없는 경로: 옛 소유자 쓰기 거부(H1), `run_forever`의 동시 실행과 예외 생존(M1), `renew_lease`, `lease_job`이 due 전 `retry_wait` 잡을 건너뛰는 경우, recorded 캐시 미스(M2), 재분석 실패 시 상태(L3).
- `vision_stage`의 `assert bundle.snapshot is not None`은 `python -O`에서 사라진다. `chunk`처럼 `ExtractionError`를 내는 편이 일관된다.

### 참고 (감점 없음)

- 5.10.3절의 LLM 프로세스 전역 세마포어와 분당 상한은 실제 LLM 연동(T25) 범위로 미뤘다. 지금 경로는 주입한 대역만 써서 타당하다. T25 착수 때 같이 넣어야 한다.
- `index` 단계는 `index_content`가 `embedding_pending=True`를 돌려줘도 `ready`로 바꾼다. I7이 같은 bundle로 임베딩을 끝냈기 때문에 지금은 재사용으로 걸리지 않는다. 다만 I7과 I8 사이에 텍스트가 바뀌면 벡터 없는 `ready`가 될 수 있으니, I8에서도 `embedding_pending`이면 재시도형 오류로 보는 편이 안전하다.
- `analysis_runs.job_id`의 `ON DELETE CASCADE`는 "재분석해도 이전 기록을 지우지 않는다"(6.2절)와 긴장이 있다. 잡 삭제 경로가 아직 없으므로 참고로만 둔다.
- 6.2절 인덱스는 `(status, priority DESC, next_run_at)`인데 구현은 `priority` 오름차순 인덱스다. SQLite는 역방향 스캔이 가능해 동작 차이는 없다.

## 3. 채점 근거

| 항목 | 점수 | 근거 |
|---|---|---|
| 정확성 | 34 / 40 | 상태 전이, 백오프, 멱등성, 사용자 수정값 보존, 축약 인덱스, AC-24 모두 재현했다(+). lease 회수 뒤 소유권이 넘어가지 않아 단계 건너뜀과 중복 실행이 생긴다(H1, −4). 캐시 미스가 재시도형으로 잘못 분류된다(M2, −1.5). 재분석 실패 상태(L3, −0.5) |
| 안전성 | 26 / 30 | 네트워크 0회, 사용자 격리, 원자 submit, fixture 경로 탈출 차단, 원문이 이벤트에 직접 들어가지 않음(+). 워커 루프가 일시 오류 하나에 죽는다(M1, −2). details 허용 목록 없음(L1, −1). bundle 통째 쓰기와 콘텐츠 단위 배타 부재(L2, −1) |
| 유지보수성 | 27 / 30 | 큐·정책·실행기 분리, 설계 시그니처 준수, 설계 차이를 보고서에 근거와 함께 기재, ruff·mypy 통과(+). 동시성 핵심 경로의 테스트 공백(L5, −2), 이벤트 순서(L4, −0.5), `assert` 사용(−0.5) |
| **합계** | **87 / 100** | 90점 미만이라 **REJECT** |

## 4. 재검수 조건 (Loop 2)

1. **H1:** lease 토큰(또는 lease마다 다른 소유자 식별자)으로 `begin_stage`/`renew_lease`/`advance`/`fail`/`put_artifact`를 조건부 갱신하고, 옛 소유자의 쓰기는 전용 예외로 거부한다. 워커는 그 예외에서 조용히 손을 뗀다. 1.2절의 세 재현(옛 소유자 advance, 옛 소유자 fail, 워커 단위 느린 analyze)과 같은 `IngestWorker` 두 스레드 사이 회수를 테스트로 고정한다.
2. **M1:** `run_forever`가 `run_once` 예외(큐 오류, `OperationalError`)를 기록하고 계속 돈다. 테스트로 고정한다.
3. **M2:** I2/I8에서 `JupjupError`를 감싸지 않고, `EmbeddingCacheMiss`가 재시도 없이 영구 실패로 분류된다(또는 I2는 키워드 전용으로 게시). recorded 캐시 미스 인제스트 테스트를 추가한다.
4. 기존 게이트 유지: `uv run pytest`, `ruff check src tests`, `mypy src`, `eval validate`, eval 4종 PASS, `git diff -- src/jupjup/search src/jupjup/query data` 0줄.
5. L1~L5는 권장이다. 특히 L1(details 허용 목록)과 L2(콘텐츠 단위 잡 배타)는 T23 착수 전에 정리하기를 권한다.

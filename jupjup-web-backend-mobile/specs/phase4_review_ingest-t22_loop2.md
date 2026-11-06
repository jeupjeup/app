# Phase 4 최종 검수: 인제스트 T22(잡 큐, 워커, 단계 실행), Loop 2/3

- **점수:** 94 / 100
- **상태:** PASS
- **항목별:** 정확성 38 / 40, 안전성 28 / 30, 유지보수성 28 / 30
- **루프백 대상:** 없음 (PASS). 아래 M1·L1~L5는 T23 착수 전에 정리하기를 권한다. 기능 수정이라 맡길 곳은 Phase 2(Codex-Primary)다.
- **검수 대상:** `phase-4-review-ingest-t22-loop2` HEAD `151c875` (`fix: harden T22 ingest worker loop 2`). 비교 기준은 Loop 1 검수 커밋 `38a0029`다.
  - 변경: `ingest/jobs.py`(+117/−), `ingest/worker.py`(+158/−), `ingest/service.py`, `index/service.py`, `storage/tables.py`(`lease_id`, `sequence`, partial unique index), `domain/errors.py`(`LeaseLostError`), 테스트 2개 파일(+7건)
- **기준 문서:** `specs/prd_and_design.md` 5.10.1~5.10.3절(1251~1299줄), 1429~1450줄 시그니처, AC-24(1752줄), AC-26(1754줄), 7.3절 T22 행(1725줄). `specs/known_issues.md`(T22 관련 항목 없음), 이전 검수 `specs/phase4_review_ingest-t22_loop1.md`(87점 REJECT)와 그 밖의 `phase4_review_*.md`.
- **채점 정책:** Loop 1과 같은 엄격도로 봤다. 사람 검수 0건은 감점하지 않았다. 범위 밖(T23 API·CLI, T24 인제스트 평가, 실제 LLM 연동과 LLM 세마포어)은 "참고"로만 적었다. 구현 보고서 `specs/phase2_ingest-t22_loop2_report.md`의 주장은 모두 직접 다시 확인했다.

## 0. 요약

- **Loop 1 재검수 조건 1~4를 모두 직접 재현으로 확인했다.**
  - **H1 (해결):** lease마다 새 `lease_id`가 발급된다. 옛 lease의 `advance`, `fail`, `put_artifact`, `begin_stage`, `renew_lease`가 모두 `INGEST_LEASE_LOST`로 거부되고, 새 소유자의 단계·lease·`stage_data`는 그대로다. 같은 `worker_id`를 공유해도 토큰이 달라 막힌다. 워커 단위에서도 옛 워커는 아무것도 기록하지 않고 조용히 손을 떼며, `run_once`가 예외를 던지지 않는다. 실행 중 heartbeat(`lease_s/3`)가 lease를 갱신한다.
  - **M1 (해결):** `run_forever`가 `OperationalError` 2회, `RuntimeError` 1회를 맞아도 살아남아 잡을 `succeeded`까지 처리한다. 단계 오류 뒤 `fail` 쓰기가 실패하면 잡이 `running`으로 남았다가 lease 만료 뒤 같은 단계에서 회수되어 끝난다.
  - **M2 (해결):** recorded 캐시 미스가 I2에서는 키워드 인덱스만 게시하고(즉시 검색됨), I7에서 재시도 없이 1회 만에 `failed`, `EMBEDDING_CACHE_MISS`로 기록된다. 일시적 `EmbeddingProviderError(503)`는 I7에서 `retry_wait`로 간다. bulk/평가 경로의 엄격한 캐시 미스 동작은 유지된다(`allow_cache_miss`는 I2만 켠다).
  - **게이트:** pytest 770 passed, ruff·mypy 통과, eval validate 통과, eval 4종 PASS(수치는 Loop 1과 소수점 4자리까지 같다), `git diff 38a0029 HEAD -- src/jupjup/search src/jupjup/query data`는 0줄이다.
- **권장 L1~L5도 대부분 반영됐다.** details 허용 목록(L1), 콘텐츠별 활성 잡 하나(L2, 서비스 검사와 partial unique index 둘 다), 재분석 실패 시 `ready` 복원(L3), 이벤트 `sequence`(L4), `assert` 제거와 테스트 보강(L5).
- **T22 완료 조건은 모두 재현된다:** 상태 전이 표 전부, lease 만료 회수, 주입 시계 백오프, 단계 멱등성, 사용자 수정값 보존, 저장 직후 축약 인덱스 검색, AC-24 네 종류, 재시도 대상과 비대상 오류 구분.
- **새로 찾은 결함은 중간 1건이다.** L3 수정이 `kind == "reanalyze"`만 보고 `ready`로 되돌린다. 그래서 한 번도 `ready`가 된 적 없는 콘텐츠(예: 인제스트 refusal로 `analysis_failed`)를 재분석하다 다시 실패하면, 요약도 태그도 없는데 `ready`, `analysis_pending=false`가 된다(M1). 재분석 경로에서만 생기고 검색 순위나 격리에는 영향이 없어 PASS를 막지는 않는다. 다만 T23에서 `ingest reanalyze` CLI가 노출되기 전에 고쳐야 한다.

## 1. 직접 실행한 명령과 결과

### 1.1 정적 검사, 테스트, 평가 (기본 설치 `uv sync` 환경)

| 명령 | 결과 |
|---|---|
| `uv run pytest -p no:warnings -rN` | **770 passed, 3 deselected** (35.2s). Loop 1의 763에 7건이 늘었다 |
| `uv run ruff check src tests` | All checks passed! |
| `uv run mypy src` | Success: no issues found in 72 source files |
| `uv run jupjup eval validate` | 통과. seeds 200, queries 259 (dev 158, test 101), lexicon_cases 139 |
| `eval run --mode mock --split dev --baseline data/baselines/mock.json` | 종료 코드 0. R@10 0.9620, MRR 0.9958, nDCG 0.9795, category min 0.8838, true-empty 1.0, false-empty 0.0 |
| `eval run --mode mock --split test …` | 종료 코드 0. R@10 0.9420, MRR 0.9867, nDCG 0.9589, category min 0.7812, false-empty 0.0120 |
| `eval run --mode recorded --split dev --baseline data/baselines/recorded.json` | 종료 코드 0. R@10 0.9712, MRR 1.0000, nDCG 0.9860, category min 0.8894 |
| `eval run --mode recorded --split test …` | 종료 코드 0. R@10 0.9720(하한 0.972와 같다. known_issues 5번 그대로), MRR 0.9911, nDCG 0.9801, category min 0.8900 |
| eval 4종 `isolation_violations`, `filter_violations` | 모두 0 |
| `git diff 38a0029 HEAD -- src/jupjup/search src/jupjup/query data \| wc -l` | **0** |
| `grep -nE "socket\|urllib\|requests\|httpx\|subprocess\|anthropic\|openai\|http"` (jobs.py, worker.py, service.py, index/service.py) | 없음 |

### 1.2 Loop 1 결함과 완료 조건 직접 재현

스크래치 디렉터리의 스크립트 2개(`repro1.py`, `repro2.py`)를 `uv run python`으로 실행했다. 둘 다 `socket.connect`와 `socket.create_connection`을 막은 상태에서 끝까지 돌았다(네트워크 접근 0회). 시계는 주입한 가변 리스트를 썼고, 분석기는 통합 테스트의 `DeterministicAnalyzer`와 그 대역(느린 분석, refusal, 일시 실패 임베더)이다.

| 사례 | 결과 | 판정 |
|---|---|---|
| A lease(300초) → `now+300초`에 B lease | `None` (경계 `<`) | OK |
| `now+301초`에 B lease | `running`, 단계 `fetch` 그대로, `leased_by=B`, 새 `lease_id` | OK |
| 옛 A의 `advance` / `fail` / `put_artifact` / `begin_stage` / `renew_lease` | 다섯 개 모두 `LeaseLostError(INGEST_LEASE_LOST)` | **H1 해결** |
| B의 `worker_id`에 옛 토큰으로 `begin_stage` | 거부 (토큰이 우선한다) | OK |
| 거부 뒤 잡 상태 | `running`, `fetch`, `leased_by=B`, `lease_id=B의 것`, `stage_data={}` | OK |
| 워커 단위: A의 analyze가 막힌 사이 시계를 400초 넘기고 B가 `run_once()` | B가 analyze부터 끝까지 실행해 `succeeded`. A는 그 뒤 `True`를 돌려주고 **예외 없음**, 이벤트에 A의 `succeeded`·`retry`가 없다. analyze 호출 2회(만료 뒤 회수라 정상) | **H1 해결** |
| `run_forever`(concurrency 2): `lease`가 `OperationalError` 2회, `RuntimeError` 1회 | 스레드 정상 종료, lease 호출 13회, 잡 `succeeded`. 로그는 `error_type`만 남긴다 | **M1 해결** |
| 단계가 `FetchError(503)`를 낸 뒤 `fail` 쓰기가 `OperationalError` | `run_once`가 `OperationalError`를 던진다(`run_forever`가 잡는다). 잡은 `running/fetch`로 남고, 301초 뒤 같은 단계에서 회수해 `succeeded`(fetch 시도 2회) | OK (설계의 lease 회수 경로) |
| `is_retryable_error` | Fetch → True, LLM status 400 → False, 429 → True, AnalysisSchema → False, EmbeddingProvider → True, LeaseLost → False | OK |
| recorded 빈 녹화본 + HTML fixture 인제스트 | I2에서 키워드 문서 게시(`서점` 형태소 검색에 걸림). I7 1회 시도 뒤 `failed`, `EMBEDDING_CACHE_MISS`, details `{"kind": "document"}`(text_hash는 저장 안 함). 이벤트 `embed started → embed failed` | **M2 해결** |
| I7에서만 `EmbeddingProviderError(status=503)` | `retry_wait`, 단계 `embed`, `EMBEDDING_UNAVAILABLE`, `next_run_at = now+2.04초` | OK (재시도 대상) |
| 재분석 잡이 활성인 동안 두 번째 `reanalyze` | `INVALID_JOB_TRANSITION`. 트랜잭션이 롤백되어 콘텐츠 상태도 바뀌지 않는다 | **L2 해결** |
| 서비스 검사를 건너뛰고 같은 콘텐츠의 `queued` 잡을 raw INSERT | `IntegrityError` (partial unique index) | OK |
| `LLMProviderError(원문, {"raw": 원문, "key": 200자, "nested": …, "path": "/etc/passwd", "status": 503})` | `last_error`에 `code`, `stage`, `details.status`만 남고 `raw`, `path`, `nested`, 200자 `key`, 메시지 원문이 빠진다. 단 `type`에 넣은 40자 문자열은 남는다(L1 참고) | 대체로 OK |
| 고정 시계 한 번으로 I1~I8 전체 실행 | 이벤트가 단계마다 `started → succeeded` 순서로 fetch부터 index까지 결정적으로 나온다 | **L4 해결** |
| 인제스트 refusal → `needs_review`, 콘텐츠 `analysis_failed` | 그 다음 재분석도 refusal → 잡 `needs_review`, **콘텐츠 `ready`, `analysis_pending=false`, 요약 없음, 태그 0개** | **M1(신규)** |
| 성공한 콘텐츠의 재분석이 `AnalysisSchemaError` | 잡 `failed`, 콘텐츠 `ready`, 기존 요약 유지 (보고서와 통합 테스트 그대로) | **L3 해결** |
| I2 `index_reduced`가 `TypeError` | `retry_wait`, `INDEX_UNAVAILABLE`(재시도형). 다른 단계의 `TypeError`는 영구 `JupjupError`로 간다 | L2(신규, 낮음) |

### 1.3 AC-24, 멱등성, 경계값, 격리 (`repro2.py`)

| 사례 | 결과 | 판정 |
|---|---|---|
| text / HTML fixture / VTT 자막 fixture / OCR 이미지 | 넷 다 잡 `succeeded`, 콘텐츠 `ready`, `analysis_pending=false`, 실제 `SearchService`에서 1위 | **AC-24 OK** |
| 1자 `"a"`, `<script>`·SQL 조각·특수문자, 영어 혼합 `useEffect cleanup`, 6만 자(`"장문 "×30000`) | 모두 `succeeded`/`ready`, 각 검색어 1위 | OK |
| 모든 성공 잡에 `run_inline` 다시 호출 | 실행하지 않고 `succeeded` 그대로, `attempts`와 `updated_at` 변화 없음 | OK (멱등) |
| 공백만 있는 text | `failed`, 단계 `extract`, `INGEST_EXTRACT_FAILED`(영구) | OK |
| `status("u_a", u_b의 잡)`, `reanalyze("u_a", u_b의 콘텐츠)` | 둘 다 `NotFoundError` | OK (격리) |
| u_b가 "비밀코끼리" 저장 후 검색 | u_a 0건, u_b 1건 | OK (격리) |
| fixture `../../pyproject.toml` | `failed`, `INGEST_UNSUPPORTED` | OK (경로 탈출 차단) |
| 같은 잡 I1~I8 재실행, 사용자 수정값 보존 | 통합 테스트 `test_same_job_twice_is_idempotent_and_reanalysis_preserves_user_values`가 새 lease 계약 아래 통과(요약 1개·analysis_runs 1행, user summary·tag·`user_patch`·`user_note`·`hidden_tags` 유지) | OK |
| 백오프·재시도 소진·우선순위 | `test_backoff_uses_injected_clock_and_is_deterministic`, `test_retry_exhaustion_becomes_terminal_failure`, `test_priority_new_ingest_before_reanalysis` 통과. 코드도 Loop 1 검수 때와 같다(`RetryPolicy` 변경 없음) | OK |

### 1.4 CLI 회귀·경계값 (`uv run jupjup seed load --db var/review.db` 후 `--db var/review.db --now 2026-10-15T12:00+09:00 --json`)

시드 적재: 줄 200, 적재 200, 인덱싱 200, 임베딩 대기 0 (u_alice 160, u_bob 30, u_carol 10). recorded는 `JUPJUP_MODE=recorded`.

| 사례 | mock | recorded | 판정 |
|---|---|---|---|
| `성수 카페` (bob) | `c_bob_0025`, `c_bob_0026`, 완화 없음 | `EMBEDDING_CACHE_MISS` (녹화본 밖 질의, 기존 동작) | OK |
| `성수 카페` (carol, 사용자 격리) | `c_carol_0009`만 | 캐시 미스 | OK |
| `성슈 카페` (오타) | 같은 2건 | 캐시 미스 | OK |
| 빈 문자열 / 600자 | `[INVALID_QUERY] 질의는 1~200자여야 해요.` | 같음 | OK |
| `!!@@##$$%%` | `[INVALID_QUERY] 검색할 단어가 없어요.` | 같음 | OK |
| `지난주 유튜브` (필터 전용) | `c_alice_0043` | 같음 | OK |
| `경주 맛집 인스타` (과소 완화 회귀) | `c_alice_0153`, `platform_filter_dropped` | 같음 | OK |
| `하체 운동 유튜브` | 1위 `c_alice_0040`, `platform_filter_dropped` | 1위 `c_alice_0040` | OK |
| `다리 운동 영상` (known_issues 4) | 1위 `c_alice_0040`, 완화 없음 | 1위 `c_alice_0040` | OK |
| `경주 맛집 카톡 논문` (이중 완화 기록) | `platform_filter_dropped`, `content_type_filter_dropped` | 같음 | OK |
| `python 강의 영상` (영어 혼합) | 4건, 1위 `c_alice_0056` | 캐시 미스 | OK |
| `화성 기지 건설 계획` (없는 대상, 과잉 완화) | 0건, 완화 없음 | 캐시 미스 | OK |
| `--platform instagram "경주 맛집"` (요청 잠금) | 0건, `applied_relaxations=[]` | 같음 | OK |
| `--platform kakao` (잘못된 필터 값) | `[INVALID_FILTER] 필터 값이 올바르지 않아요.` | 같음 | OK |
| `--user u_nobody` | 저장물이 없다는 안내 뒤 빈 결과 | 같음 | OK |

검색 경로 diff가 0줄이고, 표는 Loop 1 검수 표와 같다. 순위 회귀는 없다.

### 1.5 설계 시그니처 대조 (1429~1450줄)

| 설계 | 구현 | 판정 |
|---|---|---|
| `JobQueue.enqueue(content_id, user_id, kind, priority, profile="default") -> str` | 같고, 키워드 전용 `source_spec`, `initial_stage`, `now` 추가 | OK |
| `lease(worker_id, now, lease_s=300) -> JobRecord \| None` | 같다 | OK |
| `advance(job_id, next_stage, now) -> None` | **키워드 전용 필수 인자 `lease_id` 추가** | 설계 차이(H1 해결에 필요, 보고서 2.1절 기재). L4 참고 |
| `fail(job_id, err, now, retryable) -> None` | **필수 `lease_id`**, 선택 `next_run_at` 추가 | 같음 |
| `get(job_id) -> JobRecord` | 같다 | OK |
| `IngestWorker(queue, stages, clock, retry)`, `run_once() -> bool`, `run_forever(stop)` | 같고 키워드 전용 `worker_id`, `lease_s`, `concurrency` 추가. `clock`, `retry`에 기본값 | OK |
| `IngestService.submit/reanalyze/run_inline/status` | 같다. `status`는 다른 사용자 잡에 `NotFoundError` | OK |
| 6.2절 `ingest_jobs`, `ingest_job_events` | `lease_id`, `sequence`, `uq_ingest_jobs_active_content` 추가 | 보고서에 근거 기재 |

## 2. 피드백 (심각도 순)

### M1. 중간: 재분석 실패가 이전 상태와 상관없이 콘텐츠를 `ready`로 만든다 — `src/jupjup/ingest/jobs.py:339-346`, `src/jupjup/ingest/service.py:97-104`

- **현상:** `fail`은 `row.kind == "reanalyze"`이면 무조건 `status="ready"`, `analysis_pending=0`으로 바꾼다. `reanalyze`는 스냅샷만 있으면 받아 주므로(`service.py:99`), 한 번도 분석에 성공하지 못한 콘텐츠도 재분석 대상이 된다.
- **재현(1.2절):** 인제스트 refusal → 잡 `needs_review`, 콘텐츠 `analysis_failed`. 같은 콘텐츠를 재분석하고 다시 refusal → 잡 `needs_review`, **콘텐츠 `ready`, `analysis_pending=false`, 요약 없음, 태그 0개**. 인덱스는 I2의 축약 문서 그대로다.
  - 같은 원인으로 I7 캐시 미스로 실패한 콘텐츠(`analysis_failed`, 벡터 없음)를 재분석하다 다시 실패해도 `ready`가 된다.
- **설계와 충돌하는 지점:** 5.10.1절에서 `Content.status = ready`는 I1~I8을 모두 거친 결과다. Loop 1 L3의 뜻은 "**이전에 ready였던** 콘텐츠는 재분석 실패 뒤에도 ready를 유지한다"였다.
- **영향:** 재분석 실패 뒤 사용자에게 분석이 끝난 것처럼 보인다. `analysis_pending=false`라서 "분석 중" 표시도 사라진다. 재분석이 노출되는 T23 CLI(`ingest reanalyze --all`)에서 실패한 콘텐츠를 한꺼번에 다시 돌리면 이렇게 잘못 표시된 콘텐츠가 대량으로 생길 수 있다.
- **개선 방향:** 재분석 잡을 넣을 때 이전 상태(`status`, `analysis_pending`)를 `stage_data`(예: `prior_content_status`)에 저장했다가 실패 시 그대로 복원한다. 아니면 `ready`로 되돌리는 조건을 "직전 상태가 ready" 또는 "성공한 `analysis_runs` 행이 있음"으로 좁힌다. 테스트: refusal 인제스트 → 재분석 refusal 뒤 콘텐츠가 `analysis_failed`, `analysis_pending=true`로 남는지 고정한다.

### L1. 낮음: 오래된 실행이 저장소에 쓰는 단계 부작용은 lease로 막지 않는다 — `src/jupjup/ingest/worker.py:347`(extract upsert), `vision_stage`/`persist`의 `repo.upsert`, `index`의 상태 갱신(`:488-501`)

- 이번 루프는 **큐 쓰기**(`advance`, `fail`, `put_artifact`, `begin_stage`, `renew_lease`)를 lease로 막았다. 하지만 단계 안의 `repo.upsert`, `analysis_runs` 쓰기, `contents` 상태 갱신은 lease를 확인하지 않는다.
- heartbeat가 있어서 실제로 이런 일이 생기려면 heartbeat가 `lease_s` 넘게 실패해야 한다(DB 잠금이 길어지거나 프로세스가 멈추는 경우). 그때 옛 실행의 `extract`가 `get_bundle`과 `upsert` 사이에 오래 걸리면, 새 실행이 이미 쓴 요약·태그를 옛 bundle로 덮어쓸 수 있다. 같은 run_id라 `persist`끼리 겹치는 것은 멱등이다.
- 보고서 6.3절에서 T23 사용자 수정 API와 함께 optimistic version으로 풀겠다고 했다. 그때 단계 쓰기에도 lease 조건(펜싱 토큰)을 같이 넣기를 권한다.

### L2. 낮음: I2/I8은 `JupjupError`가 아닌 예외를 재시도형 `IndexingError`로 감싼다 — `src/jupjup/ingest/worker.py:349-353`, `:489-494`

- `index_reduced`에서 `TypeError`가 나면 `INDEX_UNAVAILABLE`로 `retry_wait`가 되어 3회 재시도한다(1.2절). 다른 단계의 같은 예외는 `_run_leased`의 `except Exception`이 영구 `JupjupError`로 처리한다.
- Loop 1 M2의 핵심(`JupjupError`를 감싸지 않음, 캐시 미스는 영구)은 해결됐다. 남은 것은 프로그래밍 오류를 분류하는 방식이 단계마다 다르다는 점이다. 감싸는 대상을 `SQLAlchemyError`/`OSError`처럼 일시적인 것으로 좁히거나, 감싸기를 없애고 워커의 일반 처리에 맡기면 일관된다.

### L3. 낮음: heartbeat가 있으면 멈춘 단계의 잡을 회수할 수 없다 — `src/jupjup/ingest/worker.py:203-235`

- heartbeat는 단계 실행기가 살아 있는 한 lease를 계속 늘린다. 단계 타임아웃이 없어서, 응답하지 않는 제공자 호출에 걸린 스레드는 잡을 영원히 붙잡는다. 프로세스가 죽은 경우에는 회수되므로 설계의 "lease 만료 → 회수"와 충돌하지는 않는다.
- Loop 1에서 권한 "lease 시간과 단계 타임아웃의 관계를 문서에 적는다"가 아직 없다. T25 실제 LLM 연동 때 제공자 호출 타임아웃(5.10.3절 "타임아웃은 재시도 대상")과 함께 단계 최대 실행 시간을 정하기를 권한다.
- heartbeat의 `SQLAlchemyError` 경로(경고만 남기고 계속)는 테스트가 없다.

### L4. 낮음: 설계 문서와 스키마 동기화, 마이그레이션 — `specs/prd_and_design.md:1433-1434`, `src/jupjup/storage/tables.py:135`, `:143-147`, `:156`, `src/jupjup/ingest/jobs.py:427-447`

- `advance`/`fail`에 필수 키워드 인자 `lease_id`가 추가되어, 설계 시그니처 그대로 호출하면 `TypeError`가 난다. 보고서에는 기재됐지만 설계 문서(1429~1450줄)와 6.2절 표에는 `lease_id`, `sequence`, partial unique index가 없다. Architect가 설계 문서를 맞춰야 한다.
- `sequence`는 `max+1`로 매기는데 `(job_id, sequence)` UNIQUE 제약이 없다. 지금은 lease 소유자만 이벤트를 쓰므로 겹치지 않지만, 제약을 두면 그 불변식이 스키마로 보장된다.
- `create_all`은 이미 있는 테이블에 컬럼을 더하지 않는다. Loop 1 시점에 만든 DB 파일에서는 `lease_id`/`sequence`가 없어 실패한다. 보고서 6.5절에 적혀 있고 아직 배포 경로가 없으니 참고 수준이다.

### L5. 낮음: `type`/`key` 허용 키는 120자 이하의 아무 문자열이나 통과시킨다 — `src/jupjup/ingest/jobs.py:25`, `:40-47`

- 허용 목록 덕분에 `raw`, `path`, `text_hash`, 중첩 dict, 오류 메시지 원문이 모두 빠진다(1.2절). 다만 `type`이나 `key`에 문자열을 넣으면 그대로 남는다. 지금 코드에서 `type`은 예외 클래스 이름만 들어가서 실제 누출은 없다. T25 제공자를 붙일 때 `type`은 식별자 패턴(`^[A-Za-z_][A-Za-z0-9_.]*$`)만 받도록 좁히기를 권한다.

### 참고 (감점 없음)

- 5.10.3절의 LLM 프로세스 전역 세마포어와 분당 상한은 T25 범위다(보고서 6.4절). 실제 LLM을 연결하기 전에 반드시 넣어야 한다.
- recorded test Recall@10은 여유가 0이다(0.9720 = 하한). 이번 변경은 검색 경로를 건드리지 않았다(known_issues 5번).
- `analysis_runs.job_id`의 `ON DELETE CASCADE`는 Loop 1 참고 그대로다. 잡 삭제 경로가 아직 없다.
- I8은 이제 `embedding_pending`이면 재시도형 `EmbeddingProviderError`를 내고(`worker.py:495-496`), `ready` 전환은 상태 필드만 갱신한다. Loop 1 참고 사항이 반영됐다.

## 3. 채점 근거

| 항목 | 점수 | 근거 |
|---|---|---|
| 정확성 | 38 / 40 | T22 완료 조건 전부와 AC-24·AC-26을 직접 재현했다. H1·M2가 해결됐고, 캐시 미스를 영구 오류로, 503을 재시도로 구분한다(+). 재분석 실패가 분석된 적 없는 콘텐츠를 `ready`로 표시한다(M1, −1.5). I2/I8의 비 `JupjupError` 분류가 다른 단계와 다르다(L2, −0.5) |
| 안전성 | 28 / 30 | 네트워크 0회, 사용자 격리, 경로 탈출 차단, lease 토큰 펜싱, 워커 루프 생존, details 허용 목록, 활성 잡 배타를 서비스와 스키마 둘 다에서 강제(+). 단계 안의 저장소 쓰기는 lease로 막지 않는다(L1, −1). 단계 타임아웃이 없고 heartbeat 때문에 멈춘 단계의 잡이 회수되지 않는다(L3, −0.5). 허용 키 값 검증이 느슨하다(L5, −0.5) |
| 유지보수성 | 28 / 30 | 큐·정책·실행기 분리가 유지되고, 조건부 UPDATE 패턴이 일관되며, 테스트가 7건 늘었다. 보고서가 설계와 다른 점을 근거와 함께 적었다. ruff·mypy 통과(+). 설계 문서·6.2절 미동기화, `sequence` 제약 부재, 마이그레이션 부재(L4, −1). M1 경로와 heartbeat 오류 경로의 테스트 공백(−1) |
| **합계** | **94 / 100** | 90점 이상이라 **PASS** |

## 4. 후속 권장 (PASS지만 T23 착수 전 정리 권장)

1. **M1:** 재분석 실패 시 이전 콘텐츠 상태를 복원한다(`stage_data`에 저장하거나 조건을 좁힌다). refusal 인제스트 → 재분석 refusal 테스트를 추가한다. `ingest reanalyze --all`(T23)을 노출하기 전에 끝내야 한다.
2. **L4:** Architect가 1429~1450줄 시그니처(`lease_id`)와 6.2절 표(`lease_id`, `sequence`, 활성 잡 partial unique index)를 구현에 맞춘다.
3. **L1:** T23 사용자 수정 API를 만들 때, 단계 쓰기(`repo.upsert`, 상태 갱신)에 lease 조건이나 optimistic version을 같이 넣는다.
4. **L2·L3·L5:** I2/I8 예외 감싸기 범위를 좁히고, T25에서 단계 타임아웃과 `type` 값 패턴 검증을 넣는다.
5. 기존 게이트 유지: `uv run pytest`, `ruff check src tests`, `mypy src`, `eval validate`, eval 4종 PASS, `git diff -- src/jupjup/search src/jupjup/query data` 0줄.

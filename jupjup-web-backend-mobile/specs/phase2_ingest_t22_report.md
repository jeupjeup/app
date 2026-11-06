# Phase 2 T22 구현 보고서

- 작업 역할: Codex-Primary
- 기준 설계: `specs/prd_and_design.md` 5.10.1~5.10.3절, 5.10.8절 1429~1450줄,
  AC-24·AC-26, 7.3절 T22
- 결과: T22 범위 구현 및 기본 설치 완료 조건 통과

## 구현 범위

### `src/jupjup/ingest/jobs.py`

- `JobRecord`, `JobEvent`, `JobStatus`, `JobStage`, `JobKind`
- SQLite `JobQueue`
  - 콘텐츠와 잡을 같은 트랜잭션에 넣는 `enqueue_in_transaction`
  - 우선순위와 실행 가능 시각을 반영한 compare-and-set lease
  - 만료된 `running` lease를 같은 단계에서 다른 워커가 회수
  - 단계 시도 횟수, lease 갱신, 단계 전진, 성공·재시도·실패·검토 필요 상태 전이
  - 단계 이벤트와 원문을 포함하지 않는 구조화 오류 기록
  - I1~I5 중간 산출물 영속화
  - 다른 사용자에게 잡 존재를 노출하지 않는 서비스 조회 기반

### `src/jupjup/ingest/worker.py`

- `RetryPolicy`
  - 단계별 최대 시도 횟수: fetch 4, analyze 3, embed/index 5, 나머지 3
  - `2초 × 2^(n-1)`, 300초 상한, job/stage/attempt SHA-256 기반 결정적 ±20% 지터
  - 테스트에서 주입하는 clock으로 `next_run_at` 결정
- 재시도 분류
  - `FetchError`, provider 전송 오류, `StorageError`, `IndexingError`는 재시도
  - HTTP status가 있으면 429/5xx만 재시도
  - unsupported/extraction/schema/refusal 및 recorded cache miss는 영구 실패
  - refusal은 `needs_review`, 시도 소진은 `failed`
- `IngestWorker`
  - 한 잡을 lease한 뒤 현재 단계부터 I8까지 실행
  - 각 단계 직전에 시도 횟수와 lease를 원자적으로 갱신
  - 중간 실패 시 백오프 예약, 영구 실패 시 콘텐츠를 `analysis_failed`로 반영
  - `run_once`, `run_job`(inline), stop event와 기본 concurrency=2 thread pool 기반 `run_forever`
- `IngestStageRunners`
  - I1 fetch: `RawSource`를 네트워크 없이 가져와 bytes는 base64로 영속화
  - I2 extract: 결정적 snapshot id로 저장하고 `analysis_pending=true` 축약 인덱스를 즉시 게시
  - I3 vision: 이미지만 OCR/주입된 이해기를 실행하고 결과를 snapshot meta에 저장
  - I4 chunk: 저장된 snapshot과 사용자 메타로 `AnalysisInput`을 영속화
  - I5 analyze: 주입된 `ContentAnalyzer`만 호출하고 output/meta 영속화
  - I6 persist: AI summary/tag/detail과 `analysis_runs`를 한 트랜잭션에 저장
  - I7 embed: 바뀐 text hash만 임베딩 저장
  - I8 index: 완전 인덱스 게시 성공 후 `Content.status=ready`, `analysis_pending=false`
  - 같은 job의 같은 단계 재실행 시 snapshot, summary, analysis run이 중복되지 않음
  - 사용자 summary/tag/detail patch/user note/hidden tag를 모든 재분석에서 보존

### `src/jupjup/ingest/service.py`

- `IngestRequest`, `SubmitResult`, `IngestService`
- 신규 submit에서 `Content(pending)`와 `ingest_job(queued, priority=10)`을 한 SQLite 트랜잭션으로 생성
- 기존 snapshot 재분석을 I4부터 `priority=1`로 실행
- inline 실행과 user-scoped 상태 조회
- source 종류 및 힌트에 따른 최소 platform/content type 결정

### 꼭 필요한 연결 변경

- `storage/tables.py`
  - 설계의 `ingest_jobs`, `ingest_job_events`, `analysis_runs` 테이블 추가
  - lease 재개를 위한 `ingest_jobs.stage_data` 추가
- `storage/repositories.py`, `domain/models.py`
  - I6와 submit의 호출자 소유 트랜잭션 연결
  - summary/detail과 `analysis_run_id` 왕복
- `index/service.py`
  - I2의 현재 bundle만 게시하는 `index_reduced`
  - I7 임베딩 저장과 I8 게시를 분리하는 `embed_content`
- `domain/errors.py`
  - 재시도 분류가 필요한 `StorageError`, `IndexingError`

검수가 끝난 T18~T21 파일의 동작은 바꾸지 않았다. `src/jupjup/search`, `src/jupjup/query`,
`data/baselines`, `data/recordings`는 수정하지 않았다. 실제 LLM API와 외부 네트워크는 사용하지 않았다.

## 설계 대비 차이와 이유

1. 설계의 `ingest_jobs` 표에는 단계 출력 저장 위치가 없지만 5.10.1절은 각 단계 출력을 저장하고 lease 만료 뒤
   현재 단계에서 재개하도록 요구한다. 별도 아티팩트 테이블 대신 잡과 수명이 같은 `stage_data` JSON 컬럼을
   추가했다. 원문은 이벤트/오류 로그에는 남기지 않으며 raw source는 이 내부 복구 컬럼에만 저장한다.
2. `analysis_runs`에 설계 표보다 `job_id UNIQUE`를 추가했다. 같은 잡이 I6 성공 직후 lease를 잃어 I6를 다시
   실행해도 분석 이력과 AI summary가 중복되지 않도록 하는 멱등 키다. 재분석은 새 job id라 새 이력을 남긴다.
3. 설계 시그니처를 깨지 않으면서 `enqueue`에 keyword-only `source_spec`, `initial_stage`, `now`를 추가했고,
   원자 submit과 inline 실행을 위해 `enqueue_in_transaction`, `lease_job`을 추가했다.
4. I2 축약 인덱싱은 제목·snapshot만 들어 있는 현재 bundle을 문서/청크 임베딩과 함께 게시한다. 현재 검색의
   관련도 게이트는 lexical-only 후보를 거를 수 있어 키워드 인덱스만 게시하면 `SearchService`에서 즉시 검색되지
   않기 때문이다. I7은 text hash가 같은 snapshot 청크를 재사용하고 I5 이후 바뀐 doc text만 임베딩하므로 중복
   제공자 작업은 없다.
5. `needs_review`에 대응하는 `Content.status` 값은 6.2절 enum에 없다. 잡은 `needs_review`를 유지하고 콘텐츠는
   검색 가능한 축약 인덱스를 보존한 채 기존 enum의 `analysis_failed`로 둔다.
6. 5.10.3절의 프로세스 전역 LLM semaphore/분당 상한은 실제 LLM 제공자 연동과 함께 적용해야 한다. 실제 LLM
   연동은 명시적 범위 밖이고 현재 T22 경로는 주입한 mock analyzer만 사용하므로 이번 구현에는 넣지 않았다.

## 테스트 목록

`tests/unit/test_ingest_jobs.py` 7건:

- queued → running → I1~I8 → succeeded 전체 전이와 단계 이벤트
- running → retry_wait → due 시각의 running 회수, 영구 failed, refusal needs_review
- lease 경계와 만료 직후 다른 워커의 동일 단계 회수
- 주입 clock과 결정적 지터를 사용한 백오프, due 이전 미실행, 재시도 후 성공
- 단계 최대 시도 소진 뒤 terminal failed
- retry 대상 오류, recorded cache/permanent 오류, HTTP 429·5xx와 400 구분
- 신규 ingest 우선순위 10이 reanalysis 우선순위 1보다 먼저 lease됨

`tests/integration/test_ingest_pipeline.py` 3건:

- I2 직후 `analysis_pending=true` 상태에서 snapshot 기반 축약 인덱스가 실제 `SearchService` 결과를 반환
- text, HTML fixture, VTT 자막 fixture, OCR image 각 1건이 I1~I8 후 ready가 되고 검색됨(AC-24)
- 같은 job의 I1~I8 전체를 다시 실행해 summary/analysis run 중복이 없음을 확인
- 재분석 뒤 user summary/tag/detail patch/user note/hidden tag가 그대로이고 AI 이력만 새 버전으로 추가됨

## 직접 실행한 명령과 결과

| 명령 | 결과 |
|---|---|
| `uv run pytest tests/unit/test_ingest_jobs.py tests/integration/test_ingest_pipeline.py -q` | PASS — 10 passed |
| `uv run pytest` | PASS — 763 passed, 3 deselected, 1 warning, 34.80s |
| `uv run ruff check src tests` | PASS — All checks passed |
| `uv run mypy src` | PASS — 72 source files |
| `uv run jupjup eval validate` | PASS — seeds 200, queries 259(dev 158/test 101), lexicon 139 |
| `uv run jupjup eval run --mode mock --split dev --baseline data/baselines/mock.json` | PASS — R@10 0.9620, MRR 0.9958, nDCG 0.9795, true-empty 1.0 |
| `uv run jupjup eval run --mode mock --split test --baseline data/baselines/mock.json` | PASS — R@10 0.9420, MRR 0.9867, nDCG 0.9589, true-empty 1.0 |
| `uv run jupjup eval run --mode recorded --split dev --baseline data/baselines/recorded.json` | PASS — R@10 0.9712, MRR 1.0000, nDCG 0.9860, true-empty 1.0 |
| `uv run jupjup eval run --mode recorded --split test --baseline data/baselines/recorded.json` | PASS — R@10 0.9720, MRR 0.9911, nDCG 0.9801, true-empty 1.0 |
| `git diff --check` | PASS |
| `git diff -- src/jupjup/search src/jupjup/query data/recordings` | 출력 없음 |

pytest 경고 1건은 기존 FastAPI/Starlette TestClient의 `httpx` deprecation 경고다. 기본 설치 정책에 따라
embed/rerank optional-extra 테스트 3개는 deselect됐다. 평가가 만든 `reports/eval_*`는 기존 ignore 대상이고
기준선 및 녹화 데이터는 바뀌지 않았다.

## 남은 문제

- 실제 `LLMContentAnalyzer`, Anthropic API, LLM semaphore/rate limit은 범위 밖이다. 현재 파이프라인은
  `ContentAnalyzer`/`ImageUnderstander` 주입 계약과 mock/fixture로만 검증했다.
- thread pool의 CLI 설정 노출과 API는 T23에 남아 있다. T22 `IngestWorker` 자체는 기본 concurrency=2이며,
  SQLite lease로 같은 잡의 중복 선점을 막는다.
- 기본 설치 완료 조건에 따라 실제 BGE embed/rerank extra 테스트 3개는 실행하지 않았다.
- 골든셋은 기존과 같이 human-reviewed 0건이다. 기술 회귀 게이트는 모두 통과했지만 제품 수준 사람 검수
  근거와는 분리된다.

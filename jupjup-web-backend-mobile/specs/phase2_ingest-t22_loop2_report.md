# Phase 2 인제스트 T22 Loop 2/3 루프백 수정 보고

- **역할:** Codex-Primary
- **기준 검수:** `specs/phase4_review_ingest-t22_loop1.md` (87점, REJECT)
- **베이스:** `38a0029` (`Review Phase 4 ingest T22 loop 1`)
- **정책:** 순위 품질의 판정 기준은 recorded(실제 bge-m3 녹화/재생)다. mock은 안전 지표·절대 기준·결정성 확인에만 썼다. 기준선과 임계값은 바꾸지 않았고 test split으로 재튜닝하지 않았다.
- **범위 보호:** `src/jupjup/search`, `src/jupjup/query`, `data/`는 기준 커밋 대비 변경 0줄이다. `data/baselines`, `data/recordings`도 변경 0줄이다.

## 1. 피드백별 조치표

| ID | 조치 | 고정한 검증 |
|---|---|---|
| **H1 lease 소유권** | lease할 때마다 `lease_id` UUID를 새로 발급한다. `begin_stage`, `renew_lease`, `advance`, `fail`, `put_artifact`의 갱신 조건에 `status=running`과 `lease_id`(시작/갱신은 `leased_by`도 포함)를 넣었다. rowcount가 0이면 전용 `LeaseLostError`를 내며 워커는 아무 결과도 기록하지 않고 조용히 손을 뗀다. 한 `IngestWorker`의 스레드가 같은 `worker_id`를 공유해도 lease 세대가 다르다. 단계 실행 중 `lease_s / 3` 주기의 heartbeat가 lease를 갱신해 느린 analyze 같은 단계의 중복 실행을 막는다. | 같은 `worker_id`로 회수한 뒤 옛 lease의 advance/fail/put_artifact를 모두 거부하고 새 lease·단계를 보존한다. 1.3초짜리 단계와 1초 lease에서 같은 워커의 두 번째 스레드가 회수하지 못하고 호출이 1회뿐임을 고정했다. |
| **M1 워커 생존** | `run_forever`가 각 future의 예외를 독립적으로 잡고 오류 타입만 구조화 로그에 남긴 뒤 계속 실행한다. 잡/본문/예외 메시지는 로그에 넣지 않는다. 단계 실행 뒤 queue 쓰기가 실패하면 현재 lease 만료 후 같은 단계에서 회수된다. | 첫 `lease`가 `OperationalError("database is locked")`를 내도 뒤의 `run_once`를 계속 호출하고 정상 종료하는 테스트를 추가했다. |
| **M2 캐시 미스 분류** | `extract`/`index`는 `JupjupError`를 그대로 전달한다. `IndexingService.prepare_bundle`은 `EmbeddingCacheMiss`를 일반 bulk/index 경로에서 계속 엄격히 실패시키며, I2 `index_reduced`에서만 키워드 문서를 게시하도록 선택적으로 허용한다. I7 `embed_content`는 원래 `EmbeddingCacheMiss`를 다시 던져 비재시도 영구 오류가 된다. I8은 `embedding_pending`이면 ready로 만들지 않는다. | 빈 실제 `RecordedEmbedder` 녹화본으로 새 text를 실행해 I2 키워드 검색 가능, I7 1회 실행, `failed`, `EMBEDDING_CACHE_MISS`를 확인했다. 기존 bulk-upsert 캐시 미스 원자성 2건도 회귀 없이 통과한다. |
| **L1 오류 원문 누출** | `last_error`와 실패 이벤트는 메시지를 오류 코드로 정규화하고 details는 `status`, `retryable`, `type`, `key`, `kind`, `attempt`, `expected`, `got`의 짧은 scalar만 허용한다. `raw`, path, hash, provider payload는 저장하지 않는다. | 오류 메시지와 `details.raw`에 원문을 넣어도 잡과 이벤트 직렬화 결과에 원문이 없고 `status=503`만 남는 테스트를 추가했다. |
| **L2 동시 bundle 덮어쓰기** | 콘텐츠별 활성 상태(`queued/running/retry_wait`) 잡은 하나만 허용하고 SQLite partial unique index로 경합 시에도 강제한다. I8의 ready 전환은 오래된 bundle 전체를 다시 쓰지 않고 content 상태 필드만 갱신한다. | 같은 콘텐츠에 두 번째 활성 잡 enqueue를 거부하는 테스트를 추가했다. 기존 사용자 요약·태그·detail patch 보존 및 동일 잡 단계 재실행 테스트를 새 lease 계약 아래 유지했다. |
| **L3 재분석 실패 상태** | `kind=reanalyze`의 영구 실패/refusal은 기존 분석·인덱스와 일치하도록 콘텐츠를 `ready`, `analysis_pending=false`로 복원한다. 신규 ingest 실패는 계속 `analysis_failed`다. | 성공한 콘텐츠의 재분석이 `AnalysisSchemaError`로 실패해도 잡만 `failed`가 되고 콘텐츠와 기존 summary가 ready로 남는 통합 테스트를 추가했다. |
| **L4 이벤트 순서** | 이벤트에 잡별 단조 증가 `sequence`를 추가하고 조회도 sequence 순서로 바꿨다. UUID나 같은 시각의 정렬에 의존하지 않는다. | 모든 이벤트가 같은 주입 시각이어도 `started → retry` 및 I1~I8의 `started → succeeded` 순서가 결정적임을 확인한다. |
| **L5 테스트/견고성** | 옛 소유자 쓰기, 같은 워커 스레드 heartbeat, `run_forever` 예외 생존, due 전 retry 대기, renew 경로(heartbeat), recorded 캐시 미스, 재분석 실패를 테스트한다. `vision_stage`의 최적화 시 사라지는 `assert`를 명시적 `ExtractionError`로 바꿨다. | 전체 테스트가 763건에서 770건으로 늘었고 기존 763건을 포함해 모두 통과했다. |

## 2. 구현과 설계 판단

### 2.1 데이터 모델 추가

- `ingest_jobs.lease_id`: worker 인스턴스 ID와 별개인 lease 세대 토큰이다. 설계의 `leased_by`는 관측용 worker ID로 유지했다.
- `ingest_job_events.sequence`: 같은 시각의 이벤트도 원인 순서를 보존한다.
- `uq_ingest_jobs_active_content`: 콘텐츠 하나에 활성 잡 하나만 허용하는 partial unique index다.

위 세 항목은 5.10.3절의 lease 회수 의미, 콘텐츠별 단계 멱등성, 관측 순서를 실제로 보장하기 위한 추가 컬럼/인덱스다. 기존 공개 시그니처에는 lease 보호가 필요해 queue 내부 쓰기 메서드에 `lease_id`를 추가했다. `lease`, `get`, `IngestService`의 외부 사용 방식은 유지된다.

### 2.2 캐시 미스와 축약 인덱스

I2는 임베딩 녹화본이 없어도 본문/제목 기반 키워드 인덱스를 게시한다. 그러나 같은 오류를 성공으로 숨기지 않는다. I7에서 원래 코드 `EMBEDDING_CACHE_MISS`로 즉시 영구 실패한다. 일반 `index_bundle`, bulk-upsert, 평가 경로는 이 예외를 완화하지 않으므로 기존 원자성 계약도 유지된다.

### 2.3 재분석과 부분 갱신

진행 중 잡끼리의 bundle 경합은 콘텐츠별 활성 잡 배타로 막았다. 가장 위험했던 I8은 전체 bundle 재기록 대신 상태 필드만 갱신한다. 현재는 사용자 수정 API가 아직 없어 persist와 사용자 쓰기의 실제 동시 경로는 없다. T23에서 사용자 수정 API를 추가할 때 persist도 필드별 optimistic update로 확장해야 한다(6절).

## 3. 실행 결과

### 3.1 기본 설치 (`uv sync`)

| 명령 | 결과 |
|---|---|
| `uv run pytest` | **770 passed, 3 deselected**, 경고 1건(기존 Starlette `httpx` deprecation), 최종 재검증 34.34초 |
| `uv run ruff check src tests` | All checks passed |
| `uv run mypy src` | Success: no issues found in 72 source files |
| `uv run jupjup eval validate` | PASS: seeds 200, queries 259(dev 158/test 101), lexicon 139, reviewed 0 |
| mock dev/test | 둘 다 PASS (4절) |
| recorded dev/test | 둘 다 PASS (4절) |

### 3.2 extra 설치 (`uv sync --extra local-models`)

모델 캐시는 지시한 `JUPJUP_BGE_CACHE_DIR=/Users/minjun/orca/workspaces/dc2/phase-2-real-embedding/var/models`를 사용했다. 설치된 핵심 버전은 `sentence-transformers 5.7.0`, `torch 2.15.0`이다.

| 명령 | 결과 |
|---|---|
| `uv run pytest` | **770 passed, 3 deselected**, 37.52초 |
| `uv run pytest -m 'embed or rerank'` | **3 passed, 770 deselected**, 실제 bge-m3/reranker 로컬 추론, 48.93초 |
| `uv run ruff check src tests` | All checks passed |
| `uv run mypy src` | Success: no issues found in 72 source files |
| `uv run jupjup eval validate` | PASS, 기본 설치와 같은 데이터 수 |
| mock dev/test | 둘 다 PASS, 기본 설치와 지표 동일 |
| recorded dev/test | 둘 다 PASS, 기본 설치와 지표 동일 |

검증 뒤 `uv sync`로 기본 설치 상태로 복원했다.

## 4. 지표 전후

순위 품질 판정은 recorded다. Loop 1 검수와 Loop 2의 값은 모두 동일하며 기준선 파일과 하한은 바꾸지 않았다.

| 모드 / split | 지표 | Loop 1(전) | Loop 2(후) | 회귀 하한 | 판정 |
|---|---|---:|---:|---:|---|
| **recorded / dev** | Recall@10 | 0.9712 | 0.9712 | 0.956457 | PASS |
|  | MRR@10 | 1.0000 | 1.0000 | 0.990000 | PASS |
|  | nDCG@10 | 0.9860 | 0.9860 | 0.969304 | PASS |
|  | category min | 0.8894 | 0.8894 | 절대 0.8000 | PASS |
| **recorded / test** | Recall@10 | 0.9720 | 0.9720 | **0.972000** | PASS, 여유 0 |
|  | MRR@10 | 0.9911 | 0.9911 | 0.976667 | PASS |
|  | nDCG@10 | 0.9801 | 0.9801 | 0.970750 | PASS |
|  | category min | 0.8900 | 0.8900 | 절대 0.8000 | PASS |
| mock / dev | Recall@10 · MRR · nDCG · category min | 0.9620 · 0.9958 · 0.9795 · 0.8838 | 동일 | 0.943571 · 0.981597 · 0.964195 · 절대 0.55 | PASS |
| mock / test | Recall@10 · MRR · nDCG · category min | 0.9420 · 0.9867 · 0.9589 · 0.7812 | 동일 | 0.932000 · 0.976667 · 0.948865 · 절대 0.55 | PASS |

추가 안전 지표도 변화 없다. recorded dev/test true-empty는 1.0/1.0, false-empty는 0/0, 격리·필터 위반은 모두 0이다. mock dev/test true-empty는 1.0/1.0, false-empty는 0/0.012다.

## 5. 변경 파일

- `src/jupjup/domain/errors.py`: `LeaseLostError`
- `src/jupjup/storage/tables.py`: lease 세대, 이벤트 순서, 활성 잡 unique index
- `src/jupjup/ingest/jobs.py`, `src/jupjup/ingest/service.py`: 조건부 lease 쓰기, 오류 정제, 콘텐츠별 배타와 오류 전달, 재분석 상태 복원
- `src/jupjup/ingest/worker.py`: heartbeat, lease 상실 처리, 영구 오류 보존, 워커 루프 예외 생존, 부분 상태 갱신
- `src/jupjup/index/service.py`: I2 전용 캐시 미스 축약 인덱싱과 I7 원래 오류 전달
- `tests/unit/test_ingest_jobs.py`, `tests/integration/test_ingest_pipeline.py`: H1~M2 및 L1~L5 회귀 사례

## 6. 남은 문제

1. **recorded test Recall@10 여유가 0이다.** 0.9720으로 기존 하한과 정확히 같다. 이번 변경은 검색 경로를 건드리지 않아 값은 유지됐지만, 다음 검색 변경은 recorded dev에서만 설계·튜닝하고 새 동결 test v2/사람 검수 전에는 제품 PASS 근거로 쓰면 안 된다.
2. **사람 검수는 여전히 0건이다.** 기술 게이트는 통과하지만 제품 품질 판정 근거와 분리해야 한다.
3. **미래 사용자 수정 API와 persist의 동시 쓰기.** 콘텐츠별 잡 배타로 잡끼리의 경합은 막았고 I8은 부분 갱신으로 바꿨다. 그러나 T23에서 사용자 수정 API가 추가되면 I6 persist가 읽은 bundle과 사용자 수정이 동시에 커밋될 가능성을 optimistic version/필드별 갱신으로 막아야 한다.
4. **LLM 프로세스 전역 세마포어·분당 상한은 T25 범위다.** 현재 분석기는 네트워크 없는 대역이므로 이번에는 추가하지 않았다. 실제 LLM 연결 전에 반드시 구현해야 한다.
5. **기존 SQLite 파일의 DDL 마이그레이션은 아직 없다.** T22 큐는 아직 T23 API/CLI로 배포되지 않았고 테스트·평가는 새 DB를 만든다. 기존 개발 DB를 보존해 올리는 경로가 필요해지면 `lease_id`, `sequence`, partial index의 명시적 migration을 먼저 추가해야 한다.

이번 루프에서 미달한 요청 완료 조건은 없다. 실패를 숨기기 위한 기준선 변경, 임계값 하향, test 재사용/재튜닝은 하지 않았다.

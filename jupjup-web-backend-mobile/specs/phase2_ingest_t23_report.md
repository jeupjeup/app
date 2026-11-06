# Phase 2 T23 보고서: dev 인제스트 API와 CLI

- 작업 워커: Codex-Primary 역할 (이 세션은 Claude가 같은 지침으로 수행)
- 브랜치: `ultra-penguin/phase-2-ingest-t23-api-cli` (베이스 `deaba53`)
- 근거: 설계서 5.9절 `POST /v1/admin/ingest`, `GET /v1/admin/ingest/jobs/{job_id}`, 5.8.1절, 5.10.3절, 5.10.8절 CLI, 7.3절 T23 행

## 1. 구현 범위

| 파일 | 내용 |
|---|---|
| `src/jupjup/api/dto.py` | `IngestSourceBody`, `IngestBody`(+`to_request`), `IngestSubmitResponse`, `IngestJobResponse`(+`from_job`). 입력 경계값과 kind별 필드 조합 검사 |
| `src/jupjup/api/app.py` | dev 게이트 블록 안에 `POST /v1/admin/ingest`(202), `GET /v1/admin/ingest/jobs/{job_id}`(200/404). `create_app(..., ingest=)`로 테스트 시계 주입 |
| `src/jupjup/container.py` | `build_ingest_service(container, *, clock, worker_id, concurrency)`: fetcher, mock 분석기, OCR 이해기, 단계 러너, 워커, `IngestService` 조립 |
| `src/jupjup/config.py` | `ingest_fixtures_dir`(`JUPJUP_INGEST_FIXTURES_DIR`), `worker_concurrency`(기본 2), `ingest_fixtures_root` 속성 |
| `src/jupjup/ingest/extractive.py` (신규) | `ExtractiveMockAnalyzer`: 원문에서 결정적으로 fixture를 만들어 `MockAnalyzer`(T18 검증·재요청 루프)를 거친다 |
| `src/jupjup/ingest/seeding.py` (신규) | `load_seed_file_for_analysis`: 시드의 스냅샷과 사용자 입력만 넣고 `chunk` 단계부터 인제스트 잡을 만든다 |
| `src/jupjup/cli.py` | `jupjup ingest submit`, `jupjup ingest status`, `jupjup worker run`, `jupjup seed load --analyze [--no-inline]` |

### API 동작
- 공통 규칙은 T15를 그대로 따른다: `X-User-Id` 필수(`MISSING_USER`/`INVALID_USER` 400), 에러 봉투 `{"error": {code, message, details}}`, 스키마 오류는 `VALIDATION_ERROR` 422, 그 밖은 `INTERNAL` 500.
- dev 게이트: 두 라우트는 `settings.env == "dev"`일 때만 등록된다. `prod`, `test`에서는 경로가 없어 `NOT_FOUND` 404 (bulkUpsert와 같은 방식).
- `POST /v1/admin/ingest` → 202 `{"content_id", "job_id", "status": "queued"}`. 분석은 하지 않고 `Content(pending)`과 잡만 한 트랜잭션으로 만든다 (T22 `IngestService.submit`).
- `GET /v1/admin/ingest/jobs/{job_id}` → 200 `{"job_id", "content_id", "status", "stage", "attempts", "last_error", "updated_at"}`.
  - 타 사용자 잡, 없는 잡, 형식이 틀린 id(`^job_[0-9a-f]{32}$` 밖)는 모두 같은 `NOT_FOUND` 404와 같은 메시지다 (존재 여부를 흘리지 않는다).
  - `last_error`는 T22가 저장한 안전한 형식(`code`, `stage`, 허용된 details 키)만 나온다. 본문과 fixture 경로는 나오지 않는다.

### 입력 경계값 (422 `VALIDATION_ERROR`)
| 필드 | 규칙 |
|---|---|
| `source.kind` | `text`, `url`, `image`만. 그 밖(`youtube` 포함)은 422 |
| kind=text | `text` 필수, 공백만 불가, 최대 100,000자. 다른 source 필드 불가 |
| kind=url | `fixture` 필수(MVP). `url`은 선택이며 `http://`/`https://`, 최대 2,048자 |
| kind=image | `ocr_text` 필수(공백 불가, 최대 100,000자). `image_path` 선택 |
| `fixture`, `image_path` | 상대 경로만 (절대 경로, `..`, 역슬래시, NUL, 드라이브 문자 거부), 최대 512자. 실제 루트 안 검사와 심볼릭 링크 차단은 T19 fetcher가 잡 실행 때 다시 한다 |
| `platform_hint`, `content_type_hint` | 도메인 열거형만 |
| `title` ≤ 300, `author` ≤ 200, `user_note` ≤ 2,000 | |
| `saved_at` | timezone-aware ISO 8601. 없으면 서비스 시계 값 |
| 알 수 없는 필드 | 거부 (`extra="forbid"`) |

### CLI
```
jupjup ingest submit --user u_alice --text "..." | --fixture html/x.html [--url URL] | --ocr-text "..."
                     [--platform news] [--title T] [--note N] [--saved-at ISO] [--inline] [--json] [--db PATH]
jupjup ingest status <job_id> --user u_alice [--json] [--db PATH]
jupjup worker run [--concurrency N] [--once | --max-jobs N] [--db PATH]
jupjup seed load data/golden/seeds.jsonl --analyze [--strict] [--replace-user] [--no-inline] [--db PATH]
```
- 종료 코드는 기존 규칙(0 성공, 1 실패, 2 설정·입력 오류)을 따른다. `submit --inline`이 `failed`/`needs_review`로 끝나면 1, `status`에서 잡을 못 찾으면 1.
- `submit`은 API와 같은 `IngestBody`로 검증한다 (입력 규칙이 한 곳에 있다).
- `ingest`와 `worker` 명령은 API와 같은 dev 게이트를 둔다 (`JUPJUP_ENV`가 dev가 아니면 2).
- `worker run` 기본은 SIGINT/SIGTERM까지 `run_forever`. `--once`는 지금 처리할 수 있는 잡이 없어질 때까지, `--max-jobs N`은 N개까지 처리하고 끝낸다.
- `seed load --analyze`: 사람이 쓴 AI 요약, AI 태그, AI 세부 태그를 빼고 스냅샷, 사용자 태그, 사용자 요약, `detail_tags.user_patch`만 남긴다. 콘텐츠 저장과 잡 등록은 한 트랜잭션이고, 스냅샷이 이미 있으므로 잡은 `chunk` 단계부터 시작한다. 등록 직후 축약 인덱스로 검색된다. 기본은 같은 프로세스에서 바로 실행하고(`--inline`), `--no-inline`이면 `worker run`에 맡긴다. 스냅샷 본문이 없는 줄은 `MISSING_SNAPSHOT`.

## 2. 설계 대비 차이 (이유 포함)

1. **분석기: `ExtractiveMockAnalyzer`를 새로 둠.** 설계서의 `MockAnalyzer`는 fixture 매핑이 있어야 동작하는데, dev API와 CLI는 임의의 본문을 받는다. 그래서 원문 앞부분 요약, Kiwi 키워드 태그, 원문 앞 60자 근거 하나로 fixture를 결정적으로 만들고 `MockAnalyzer`에 넘겨 T18 검증·재요청 경로를 그대로 탄다. 실제 LLM 분석기는 T25 범위라서, mode(mock/recorded/live)와 상관없이 이 분석기를 쓴다. T24 평가 하네스는 자기 fixture로 `MockAnalyzer`를 직접 쓰면 된다.
2. **`routes_ingest.py`를 따로 만들지 않음.** 설계서 5.7절 구조는 라우트 파일을 나누지만, 기존 T15 코드가 `api/app.py` 하나에 모든 라우트와 dev 게이트를 두고 있다. 같은 게이트와 `UserId` 의존성을 그대로 쓰려고 그 블록에 추가했다.
3. **응답의 `attempts`는 정수.** `JobRecord.attempts`는 단계별 dict다. 설계서 예시(`"attempts": 1`)에 맞춰 현재 단계의 시도 횟수를 돌려준다.
4. **`source.kind=youtube`는 API에서 받지 않음.** 설계서 5.9절이 `text`/`url`/`image`만 정의한다. 자막은 `kind=url` + `.vtt/.srt/.json` fixture로 받는다 (T19 `FixtureTranscriptFetcher`가 url 종류도 지원한다). 플랫폼은 추론하지 않으므로 `platform_hint: "youtube"`를 같이 보내야 한다.
5. **fixture 루트 설정 추가.** 기본 `data/golden/ingest/fixtures`(5.7절, T24에서 만듦)이고 `JUPJUP_INGEST_FIXTURES_DIR`로 바꿀 수 있다. 루트가 없으면 fixture fetcher 없이 조립하고, fixture 잡은 `INGEST_UNSUPPORTED`로 영구 실패한다 (API 기동은 막지 않는다).
6. **`saved_at` 기본값을 서비스 시계에서 가져옴.** `IngestRequest`의 기본값은 벽시계라 테스트 시계 주입과 어긋났다. DTO의 `to_request(default_saved_at)`가 서비스 시계 값을 넣는다. T22 코드는 바꾸지 않았다.
7. **`ingest reanalyze`, `POST /v1/admin/contents/{id}:reanalyze`는 구현하지 않음.** 브리프 범위가 "dev 인제스트 API 두 개"라서 뺐다. `IngestService.reanalyze`는 T22에 이미 있으니 라우트와 CLI만 붙이면 된다.

### 기존 파일 변경 이유 (연결 변경만)
- `api/app.py`, `api/dto.py` (T15): 인제스트 라우트와 DTO 추가. 기존 라우트, 에러 매핑, 검색 응답은 그대로.
- `container.py`: `build_ingest_service` 추가. 기존 `build_container`는 그대로.
- `config.py`: 설정 필드 2개와 속성 1개 추가.
- `cli.py`: 새 명령과 `seed load --analyze` 옵션 추가. 기존 `seed load` 경로는 그대로.
- T18~T22 파일(`ingest/fetch.py`, `extract.py`, `analyzer.py`, `validation.py`, `jobs.py`, `worker.py`, `service.py`)은 **바꾸지 않았다**. `src/jupjup/search`, `src/jupjup/query`, `data/` 아래 기준선과 recordings도 바꾸지 않았다.

## 3. 테스트 목록 (신규 51개)

`tests/integration/test_api_ingest.py` (30)
- `test_submit_returns_202_and_job_status_tracks_pipeline`: 202, 응답 키, content-type, queued→succeeded 상태 조회, 시계 주입된 `saved_at`/`updated_at`, 저장 뒤 검색
- `test_submit_html_fixture_with_hints_and_saved_at`: url+fixture, platform/title/saved_at 반영, ready
- `test_failed_job_status_exposes_code_only`: 없는 fixture → failed, `INGEST_UNSUPPORTED`, 경로 비노출
- `test_other_users_job_is_404_like_unknown_job`: 타 사용자, 없는 잡, 형식 오류 id가 모두 같은 404
- `test_ingest_routes_are_404_outside_dev[prod|test]`
- `test_user_header_is_required`: `MISSING_USER`, `INVALID_USER`
- `test_invalid_ingest_inputs_are_422[21개]`: 빈 본문, 공백 text, 100,001자, kind별 필드 조합, `..`/절대/역슬래시 경로, `file://` url, 2,048자 초과 url, image에 ocr_text 없음, `youtube`/알 수 없는 kind, 잘못된 enum, naive `saved_at`, 길이 초과 메모·제목, 알 수 없는 필드. 그리고 큐에 아무것도 들어가지 않았는지 확인
- `test_boundary_inputs_are_accepted`: 정확히 100,000자, 1자, 메모 2,000자·제목 300자, OCR 이미지, 자막 fixture가 모두 202이고 succeeded
- `test_missing_fixture_root_still_accepts_and_fails_job_permanently`

`tests/integration/test_cli_ingest.py` (15)
- `test_submit_inline_status_and_search`: `--inline --json`, `status` 결과 일치, 타 사용자 status는 1, 검색됨
- `test_submit_queues_and_worker_run_once_processes`: html/자막/OCR 큐 등록 → `worker run --max-jobs 1`, `--once --concurrency 1` → 모두 succeeded, 빈 큐는 0건
- `test_failed_inline_job_exits_1`
- `test_submit_rejects_bad_input_with_exit_2[7개]`
- `test_ingest_commands_are_dev_only[prod|test]`
- `test_seed_load_analyze_replaces_human_analysis_but_keeps_user_values`: 요약 모델이 `mock-analyzer-v1`, 사용자 태그 `주말데이트` 유지, `--replace-user` 재적재 멱등
- `test_seed_load_analyze_no_inline_leaves_jobs_for_worker`: 축약 인덱스로 바로 검색되고 worker가 3건 처리
- `test_seed_load_analyze_strict_rejects_missing_snapshot`: `MISSING_SNAPSHOT`, 전부 미반영

`tests/unit/test_ingest_extractive.py` (6)
- 한국어, 영어, 1자 본문 + 200자 제목, 문장부호가 많은 본문에서 출력이 유효하고(first_pass_ok) 근거가 원문 접두이며 두 번 실행 결과가 같음. map_reduce 입력. 태그 보충과 중복 제거

## 4. 직접 실행한 명령과 결과

| 명령 | 결과 |
|---|---|
| `uv run pytest` (기본 설치, extra 없음) | **821 passed, 3 deselected** (36.95s) |
| `uv run ruff check src tests` | All checks passed |
| `uv run mypy src` | Success: no issues found in 74 source files |
| `uv run jupjup eval validate` | exit 0 |
| `uv run jupjup eval run --mode mock --split dev` | PASS, recall@10 0.9620, ndcg@10 0.9795 |
| `uv run jupjup eval run --mode mock --split test` | PASS, recall@10 0.9420, ndcg@10 0.9589 |
| `uv run jupjup eval run --mode recorded --split dev` | PASS, recall@10 0.9712, ndcg@10 0.9860 |
| `uv run jupjup eval run --mode recorded --split test` | PASS, recall@10 0.9720, ndcg@10 0.9801 |
| 무회귀 확인: 베이스 커밋 `deaba53`을 임시 워크트리로 받아 같은 4개 eval을 돌리고 리포트 JSON 비교 | 4개 모두 `overall`과 질의별 `results`가 **완전히 같음** |
| 수동 스모크: `ingest submit --text --inline`, `ingest submit --fixture html/article.html`, `worker run --once`, `search` | 두 잡 succeeded, 검색됨 |
| 수동 스모크: `seed load --analyze --strict` (골든 200건) | 적재 200 / 잡 200 / succeeded 200, 약 4초 |

참고: 커밋된 `data/baselines/mock.json`, `recorded.json`의 dev/test 수치(예: mock dev recall@10 0.9536)는 베이스 커밋에서 돌린 현재 결과(0.9620)와 이미 다르다. 이번 작업 전부터 있던 차이이고, 기준선 파일은 범위 밖이라 갱신하지 않았다.

## 5. 남은 문제 (숨기지 않음)

1. **API 서버와 별도 워커 프로세스의 인덱스가 따로 논다.** 검색 인덱스는 프로세스 메모리(`UserIndexRegistry`)에 있다. `api serve`로 받은 잡을 다른 프로세스의 `jupjup worker run`이 처리하면, DB에는 ready로 저장되지만 실행 중인 API 서버의 인덱스는 재시작이나 재구축 전까지 바뀌지 않는다. 같은 프로세스(`submit --inline`, `seed load --analyze`, 테스트의 `run_inline`)에서는 바로 반영된다. 서버 안에 워커 스레드를 띄우거나 DB 변경을 감지해 인덱스를 다시 읽는 방식은 레지스트리 동시성 검토가 필요해서 이번 범위에서 뺐다.
2. **mock 분석기 품질.** `ExtractiveMockAnalyzer`의 요약은 원문 앞부분을 옮긴 틀 문장이고, 카테고리는 항상 `other`, 저장 의도는 `정보보관`이다. 배선 검증용일 뿐 품질 지표에 쓰면 안 된다. 실제 분석기는 T25다.
3. **recorded 모드에서 새 본문을 넣으면 실패한다.** `RecordedEmbedder`에 녹화가 없는 텍스트는 `EMBEDDING_CACHE_MISS`라서 embed/index 단계가 재시도 끝에 실패한다. 의도된 동작이지만 dev 인제스트는 사실상 mock 모드에서만 쓸 수 있다.
4. **기본 fixture 루트가 아직 없다.** `data/golden/ingest/fixtures`는 T24에서 만든다. 그 전까지 fixture 제출은 `JUPJUP_INGEST_FIXTURES_DIR`(예: `tests/fixtures/ingest`)를 지정해야 성공한다.
5. **재분석 API와 CLI(`:reanalyze`, `ingest reanalyze --all`)는 미구현** (2절 7번).
6. `worker run`의 LLM 전역 세마포어와 분당 상한(5.10.3절)은 실제 LLM 호출이 없어 아직 의미가 없고 구현하지 않았다 (T25에서 붙임).

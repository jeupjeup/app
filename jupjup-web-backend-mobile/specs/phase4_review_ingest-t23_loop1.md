# Phase 4 최종 검수: 인제스트 T23(dev 인제스트 API, ingest/worker CLI, seed load --analyze), Loop 1/3

- **점수:** 92 / 100
- **상태:** PASS
- **항목별:** 정확성 36 / 40, 안전성 28 / 30, 유지보수성 28 / 30
- **루프백 대상:** 없음 (PASS). 아래 M1, M2는 T24 착수 전에 정리하기를 권한다. 기능 수정이라 맡길 곳은 Phase 2(Codex-Primary)다.
- **검수 대상:** `phase-4-review-ingest-t23-loop1` HEAD `1347bae` (`feat: add T23 dev ingest API, ingest/worker CLI, seed load --analyze`). 비교 기준은 T22 Loop 2 검수 커밋 `deaba53`이다.
  - 변경: `api/app.py`(+61), `api/dto.py`(+119), `cli.py`(+203), `config.py`(+7), `container.py`(+58), 신규 `ingest/extractive.py`(92), `ingest/seeding.py`(158), 테스트 3개 파일(51건)
- **기준 문서:** `specs/prd_and_design.md` 5.9절 `POST /v1/admin/ingest`, `GET /v1/admin/ingest/jobs/{job_id}`(1230~1250줄), 5.8.1절 에러 계층(893줄), 5.10.1절 검색 가능 시점, 5.10.8절 시그니처와 CLI(1440~1451줄), 7.3절 T23 행(1726줄). `specs/known_issues.md`, 이전 검수 `specs/phase4_review_*.md`(특히 `phase4_review_ingest-t22_loop2.md`). T23 이전 검수 파일은 없다(이번이 첫 회).
- **채점 정책:** 이전 검수와 같은 엄격도로 봤다. 사람 검수 0건은 감점하지 않았다. 범위 밖(T24 인제스트 평가, T25 실제 LLM 연동, 브리프에 없는 `:reanalyze` API·`ingest reanalyze` CLI)은 "참고"로만 적었다. 구현 보고서 `specs/phase2_ingest_t23_report.md`의 주장은 모두 직접 다시 확인했다.

## 0. 요약

- **T23 완료 조건은 모두 직접 재현된다:** 202 응답(`content_id`, `job_id`, `status: "queued"`), 잡 상태 조회(설계 응답 7개 필드와 정확히 같다), 타 사용자 잡 404(없는 잡, 형식 오류 id와 같은 봉투·같은 메시지), dev가 아닐 때 404(`prod`, `test` 모두 경로 자체가 없고 OpenAPI에도 안 나온다), 입력 경계값 422, CLI 통합(submit/status/worker run/seed load --analyze).
- **게이트 전부 통과:** pytest 821 passed, ruff·mypy 통과, eval validate 통과, eval 4종 PASS이며 수치가 T22 Loop 2 검수와 소수점 4자리까지 같다. `git diff deaba53 HEAD -- src/jupjup/search src/jupjup/query data`는 0줄이고, T18~T22 인제스트 파일도 바뀌지 않았다.
- **네트워크·LLM 접근 없음:** 신규·변경 파일에 `socket/urllib/requests/httpx/subprocess/anthropic/openai`가 없다. `socket.connect`를 막은 채 API·인제스트 재현 스크립트가 끝까지 돌았다. `image_path`는 저장만 되고 열리지 않는다(`OcrOnlyUnderstander`).
- **새로 찾은 결함은 중간 2건이다.**
  - **M1:** `ExtractiveMockAnalyzer`가 extract 단계의 `language="und"`를 그대로 넘겨, 숫자·기호만 있는 정상 입력(전화번호, 날짜, `$$$ 100`, `1234567890`)이 `ANALYSIS_SCHEMA_INVALID`로 **영구 실패**한다.
  - **M2:** HTTP API로 받은 콘텐츠는 실행 중인 API 서버에서 **재시작 전까지 검색되지 않는다**(축약 인덱스조차 없다). 보고서 5절 1번에 공개된 문제이고 재현으로 확인했다.
  - 둘 다 dev 전용 경로에서만 생기고 검색 순위, 사용자 격리, 입력 검증에는 영향이 없어 PASS를 막지는 않는다.

## 1. 직접 실행한 명령과 결과

### 1.1 정적 검사, 테스트, 평가 (기본 설치 `uv sync` 환경)

| 명령 | 결과 |
|---|---|
| `uv run pytest -p no:warnings -rN` | **821 passed, 3 deselected** (37.05s). T22 Loop 2의 770에서 51건이 늘었다 |
| `uv run pytest --collect-only` (신규 3개 파일) | api 30, cli 15, unit 6 = 51 (보고서와 같다) |
| `uv run ruff check src tests` | All checks passed! |
| `uv run mypy src` | Success: no issues found in 74 source files |
| `uv run jupjup eval validate` | 통과. queries 259 (ai_draft_unreviewed 235, needs_human_review 24), reviewed 0 |
| `eval run --mode mock --split dev --baseline data/baselines/mock.json` | 종료 코드 0. R@10 0.9620, MRR 0.9958, nDCG 0.9795, category min 0.8838, true-empty 1.0, false-empty 0.0 |
| `eval run --mode mock --split test …` | 종료 코드 0. R@10 0.9420, MRR 0.9867, nDCG 0.9589, category min 0.7812, false-empty 0.0120 |
| `eval run --mode recorded --split dev --baseline data/baselines/recorded.json` | 종료 코드 0. R@10 0.9712, MRR 1.0000, nDCG 0.9860, category min 0.8894 |
| `eval run --mode recorded --split test …` | 종료 코드 0. R@10 0.9720(known_issues 5번 그대로), MRR 0.9911, nDCG 0.9801, category min 0.8900 |
| eval 4종 `isolation_violations`, `filter_violations` | 모두 0 |
| `git diff deaba53 HEAD --stat -- src/jupjup/search src/jupjup/query data` | **0줄** |
| `git diff deaba53 HEAD --stat -- src/jupjup/ingest/{fetch,extract,analyzer,validation,jobs,worker,service}.py` | **0줄** (보고서 "T18~T22 파일 안 바꿈" 확인) |
| 신규·변경 파일 네트워크 grep | 없음 |

### 1.2 API 완료 조건과 경계값 (`repro_api.py`, `TestClient`, 소켓 차단, 주입 시계)

| 사례 | 결과 | 판정 |
|---|---|---|
| `kind=text` 정상 | 202, 키 정확히 `{content_id, job_id, status}`, `queued` | OK |
| **설계서 예시 요청 그대로**(url + `transcript/sample.vtt`, `platform_hint: youtube`, `user_note`, `saved_at +09:00`) | 202 → `run_inline` 뒤 `succeeded`, `saved_at` 19:00+09:00 보존 | OK |
| html fixture + `platform_hint: news` / OCR 이미지 + `image_path` / 영어 혼합 / `<script>`·SQL 조각·이모지 / NUL 포함 / 정확히 100,000자 / `content_type_hint` / 미래 `saved_at` | 모두 202 → `succeeded`, 콘텐츠 `ready` | OK |
| 이모지만 / 문장부호만 / zero-width만 | 202 → `failed`, `extract`, `INGEST_EXTRACT_FAILED`(T21 동작) | OK |
| fixture가 디렉터리 / 없는 파일 / fixture 루트 없음 | 202 → `failed`, `fetch`, `INGEST_UNSUPPORTED`, 경로 비노출 | OK |
| 빈 text, 공백 text, source 없음/null, kind 없음, text가 정수, url에 fixture 없음, 절대 경로, `..`, `C:x`, `javascript:` url, `HTTPS://`(대문자), image_path `..`, 잘못된 platform, naive·형식 오류 `saved_at`, 최상위·source 안 알 수 없는 필드(`user_id` 주입 시도 포함), 100,001자, title 301자, 깨진 JSON, 배열 본문 | 모두 422 `VALIDATION_ERROR` | OK |
| 헤더 없음 / `alice` | 400 `MISSING_USER` / `INVALID_USER` | OK |
| 타 사용자(bob, carol)가 alice 잡 조회 | 404 `NOT_FOUND` "인제스트 잡을 찾을 수 없습니다" | **OK** |
| 없는 잡, `job_XYZ`, 300자, 대문자 hex, `%2e%2e`, 끝에 `%0a` | 모두 같은 404 봉투 (details는 입력 앞 64자 반사) | OK |
| 상태 조회 헤더 없음 | 400 `MISSING_USER` | OK |
| `failed` 잡의 `last_error` | `{code, stage, message(=code), details.kind}`만. 본문·경로 없음 | OK |
| 검색 격리: alice 저장 "반짝별사탕" | alice 1건, bob 0건 | OK |
| `env=prod`, `env=test` | POST·GET 모두 404 `요청한 경로를 찾을 수 없어요.`, OpenAPI에 경로 없음 | **OK** |
| dev OpenAPI | 두 경로 노출, POST 응답 202/400/404/422/500 | OK |
| url에 개행(`https://a.com/\nX-Evil: 1`) | **202 수락**, 메타데이터로 저장 | L2 |
| title `"   "` | **202 수락**, 제목이 공백 3칸으로 저장 (`""`는 추출 제목으로 대체) | L1 |

### 1.3 분석기 퍼징과 경로 탈출 (`fuzz.py`, `digits.py`)

| 입력 | 결과 | 판정 |
|---|---|---|
| 전각, NFD 한글, CRLF·탭, HTML 엔티티, 5,000자 단일 토큰, 합자·단위 기호, ZWJ 이모지 반복, RTL 혼합, 1자, 제어 문자, 48,000자 반복 문장 | 모두 `succeeded` | OK |
| `https://example.com/a?b=1`, `ABC`, `ok`, `Wi-Fi 비번 1234`, `12,000원`, `#해시태그 #카페`, `a b c d` | 모두 `succeeded` | OK |
| **`1234567890`, `010-1234-5678`, `2026-10-20`, `$$$ 100`** | **`failed`, `analyze`, `ANALYSIS_SCHEMA_INVALID`** (영구) | **M1** |
| 원인 추적 | extract가 `language="und"`를 내고, `fixture_for`가 그대로 쓰며, 검증기가 `$.language language_invalid`(fixable=False)로 거부. 같은 fixture에 `language=None`을 주면 검증 통과 | M1 확정 |
| `ㅋㅋㅋㅋ`, `ㅠㅠ` | `failed`, `extract`, `INGEST_EXTRACT_FAILED` | 참고(T21 extract 동작, 범위 밖) |
| fixture 루트 안 심볼릭 링크(`html/evil.html → /etc/hosts`, `etc → /etc`) | 둘 다 `failed`, `INGEST_UNSUPPORTED` | OK (T19 fetcher가 막는다) |

### 1.4 API 서버와 별도 워커 (`repro_split.py`, 파일 DB)

| 단계 | 결과 |
|---|---|
| API 컨테이너로 `POST /v1/admin/ingest` | 202 `queued` |
| 같은 API로 즉시 검색 | 0건 (I2 축약 인덱스도 워커가 만든다) |
| 별도 컨테이너(다른 프로세스 역할)의 워커 `run_once()` | `True`, API 상태 조회 `succeeded` |
| 같은 API로 다시 검색 | **0건** (서버 메모리 인덱스가 갱신되지 않음) → **M2** |

### 1.5 CLI 통합 (`JUPJUP_ENV=dev JUPJUP_INGEST_FIXTURES_DIR=tests/fixtures/ingest`, `--db var/review.db`)

| 명령 | 결과 | 판정 |
|---|---|---|
| `ingest submit --user u_alice --text "보라색 우산 수선 가게 메모" --inline --json` | 종료 0, JSON 7개 필드, `succeeded`/`index`/`attempts 1` | OK |
| `ingest status <job> --user u_alice` | 종료 0, `succeeded @ index / 시도 1` | OK |
| `ingest status <job> --user u_bob` / `job_xyz` | 종료 1, "잡을 찾을 수 없습니다" (같은 문구) | OK |
| `ingest status <job> --user alice` | 종료 2 | OK |
| `search "보라색 우산"` alice / bob | 1건 / 0건 | OK (격리) |
| `submit --fixture html/article.html --url https://e.com/a --platform news`, `--ocr-text`, `--fixture transcript/sample.vtt --platform youtube` | 종료 0, `queued` | OK |
| `submit --fixture html/nope.html --inline` | 종료 1, `INGEST_UNSUPPORTED` | OK |
| `--text a --ocr-text b`, 인자 없음, `--text ""`, `--text "   "`, `--fixture ../x`, `--fixture /etc/passwd`, `--text a --url …`, `--url ftp://x`, `--platform myspace`, naive·형식 오류 `--saved-at`, 100,001자, title 301자 | 모두 종료 2, 한국어 오류 메시지 | OK |
| `worker run --once` (큐 3건) → 다시 `--once` | 처리 3 → 0, 종료 0. DB `succeeded 4 / failed 1` | OK |
| `JUPJUP_ENV=prod ingest submit`, `prod ingest status`, `JUPJUP_ENV=test worker run --once` | 종료 2, "JUPJUP_ENV=dev에서만" | OK (dev 게이트) |
| `worker run --concurrency 0`, `--max-jobs 0` | 종료 2 | OK |
| `worker run`(무한) + `SIGTERM` | "워커를 멈췄습니다", 종료 0 | OK |

### 1.6 `seed load --analyze`

| 사례 | 결과 | 판정 |
|---|---|---|
| 빈 DB, `--analyze --strict` | 적재 200 / 잡 200 / `succeeded 200`, 약 5초. 콘텐츠 `ready`·`analysis_pending=0` 200, 요약 ai 200 + user 1, 태그 ai 993 + user 4 | OK |
| 그 상태에서 `--replace-user` 없이 재실행 | 종료 0, 콘텐츠 200 그대로, ai 요약 200(누적 안 됨), 잡 이력 400 | OK |
| `--no-inline` 후 다시 `--no-inline`(활성 잡 존재) | 종료 1, 전부 롤백, `1행 [INVALID_JOB_TRANSITION] c_alice_0001` 하나만 표시 | L3 |
| `--no-inline --replace-user`(활성 잡 존재) | 종료 0, 옛 잡 cascade 삭제, `queued 200` | OK |
| 분석 전 `search "성수 카페" --user u_bob` | `c_bob_0025`, `c_bob_0026` (축약 인덱스로 즉시 검색) | OK |
| `worker run --once --concurrency 1` | 처리 200, `succeeded 200` | OK |
| 분석된 DB에 일반 `seed load` | 적재 200 / 인덱싱 200, 종료 0 (기존 경로 영향 없음) | OK |

### 1.7 검색 회귀·경계값 (`uv run jupjup seed load --db var/review.db` 후 `--db var/review.db --now 2026-10-15T12:00+09:00 --json`)

시드 적재: 줄 200, 적재 200, 인덱싱 200, 임베딩 대기 0 (u_alice 160, u_bob 30, u_carol 10). recorded는 `JUPJUP_MODE=recorded`.

| 사례 | mock | recorded | 판정 |
|---|---|---|---|
| `성수 카페` (bob) | `c_bob_0025`, `c_bob_0026`, 완화 없음 | `EMBEDDING_CACHE_MISS` (녹화본 밖, 기존 동작) | OK |
| `성수 카페` (carol, 사용자 격리) | `c_carol_0009`만 | 캐시 미스 | OK |
| `성슈 카페` (오타) | 같은 2건 | 캐시 미스 | OK |
| 빈 문자열 / 600자 | `[INVALID_QUERY] 질의는 1~200자여야 해요.` | 같음 | OK |
| `!!@@##$$%%` | `[INVALID_QUERY] 검색할 단어가 없어요.` | 같음 | OK |
| `지난주 유튜브` (필터 전용) | `c_alice_0043` | 같음 | OK |
| `경주 맛집 인스타` (과소 완화 회귀) | `c_alice_0153`, `platform_filter_dropped` | 같음 | OK |
| `하체 운동 유튜브` | 1위 `c_alice_0040`, `platform_filter_dropped` | 1위 `c_alice_0040` | OK |
| `다리 운동 영상` (known_issues 4) | 1위 `c_alice_0040`, 완화 없음 | 1위 `c_alice_0040` | OK |
| `경주 맛집 카톡 논문` (이중 완화) | `platform_filter_dropped`, `content_type_filter_dropped` | 같음 | OK |
| `python 강의 영상` (영어 혼합) | 1위 `c_alice_0056` | 캐시 미스 | OK |
| `화성 기지 건설 계획` (없는 대상, 과잉 완화) | 0건, 완화 없음 | 캐시 미스 | OK |
| `--platform instagram "경주 맛집"` (요청 잠금) | 0건, `applied_relaxations=[]` | 같음 | OK |
| `--platform kakao` | `[INVALID_FILTER] 필터 값이 올바르지 않아요.` | 같음 | OK |
| `--user u_nobody` | 저장물이 없다는 안내 뒤 빈 결과 | 같음 | OK |

T22 Loop 2 검수 표와 같다. 검색 경로 diff 0줄과 eval 수치 동일로 순위 무회귀를 확인했다.

### 1.8 설계 시그니처·필드 대조

| 설계 | 구현 | 판정 |
|---|---|---|
| `POST /v1/admin/ingest` 요청 `source{kind,url,fixture}`, `platform_hint`, `user_note`, `saved_at` | `IngestBody`/`IngestSourceBody`. 더해 `text`, `ocr_text`, `image_path`, `content_type_hint`, `title`, `author` (5.10.2 `SourceSpec`과 일치) | OK |
| `source.kind`: `text`/`url`(fixture 필수)/`image`(ocr_text 필수, 경로 선택) | `_shape` 검사가 정확히 이 규칙. 다른 kind 필드 섞으면 422 | OK |
| 응답 202 `{content_id, job_id, status: "queued"}` | 같다 | OK |
| `GET …/jobs/{job_id}` 200 `{job_id, content_id, status, stage, attempts, last_error, updated_at}` | 같은 7개 필드. `attempts`는 현재 단계 시도 수(정수) | OK (보고서 2절 3번 근거) |
| dev 전용 | `settings.env == "dev"` 블록 안에서만 등록 (bulkUpsert와 같은 방식) | OK |
| 5.8.1 `NotFoundError(NOT_FOUND)` → 404, T15 봉투 | `install_error_handlers`가 404 `{"error":{code,message,details}}` | OK |
| `IngestService.submit/run_inline/status` (1442~1447줄) | 그대로 사용, T22 코드 변경 없음 | OK |
| CLI `ingest submit --user … --text | --fixture … --platform … [--inline]`, `ingest status <job_id>`, `worker run [--concurrency 2]` (1450줄) | 모두 있음. `--json`, `--once`, `--max-jobs`, `--title`, `--note`, `--saved-at`, `--url` 추가 | OK |
| `seed load --analyze` (1451줄) | 스냅샷과 사용자 값만 남기고 `chunk`부터 잡 생성 | OK |
| 5.7절 `routes_ingest.py` | `api/app.py` 안에 둠 | 설계 차이, 보고서 2절 2번 근거 기재. 감점 없음 |
| `ingest reanalyze`, `POST …:reanalyze` | 미구현 | 참고(브리프 범위 밖) |

## 2. 피드백 (심각도 순)

### M1. 중간: 숫자·기호만 있는 정상 입력이 분석 단계에서 영구 실패한다 — `src/jupjup/ingest/extractive.py:66` (호출부 `:47`)

- **현상:** `fixture_for`가 `language or (...)`로 `inp.meta.language`를 그대로 쓴다. 한글·라틴 문자가 없는 본문은 extract가 `language="und"`를 내고(문자열이 비어 있지 않으므로 대체식을 타지 않는다), `AnalysisValidator`가 `$.language language_invalid`(fixable=False)로 거부한다. `MockAnalyzer` 재요청도 같은 fixture라 소진되어 `AnalysisSchemaError` → 잡 `failed`, 콘텐츠 `analysis_failed`.
- **재현:** `1234567890`, `010-1234-5678`, `2026-10-20`, `$$$ 100` 네 가지 모두 `failed/analyze/ANALYSIS_SCHEMA_INVALID`. 개인 저장소에서 전화번호, 날짜, 금액, 도어락 번호 메모는 흔한 입력이다. 같은 fixture에 `language=None`이면 검증을 통과하므로 원인이 확정이다.
- **개선:** ISO 639-1 두 글자 코드가 아니면(`und` 포함) 버리고 문자 기반 추정으로 대체하거나, 문자가 없을 때 쓸 기본값(`ko` 등)을 정한다. `tests/unit/test_ingest_extractive.py`에 숫자 전용, 날짜, 기호+숫자 사례와 `language="und"` 입력을 추가하고, API 통합 테스트에 숫자 전용 본문이 `succeeded`인지 넣는다.

### M2. 중간: HTTP API로 받은 콘텐츠가 실행 중인 서버에서 검색되지 않는다 — `src/jupjup/api/app.py:320-344`, `src/jupjup/container.py:205-241`

- **현상:** API는 `submit`만 하고 단계 실행은 별도 `worker run` 프로세스가 한다. 검색 인덱스는 프로세스 메모리(`UserIndexRegistry`)라서 워커가 만든 축약·완전 인덱스가 API 서버에 반영되지 않는다. 5.10.1절 "I2가 끝나면 … 저장 직후에도 검색에 걸리게 한다"를 dev API 경로에서는 만족하지 못한다(재시작이나 재구축 전까지 0건).
- **재현:** 1.4절. API로 제출 → 다른 컨테이너의 워커가 `succeeded` → 같은 API 검색 0건.
- **참작:** 보고서 5절 1번에 숨기지 않고 적혀 있고, 같은 프로세스 경로(`submit --inline`, `seed load --analyze`, `run_inline`)는 바로 반영된다. 설계서도 워커를 단일 별도 프로세스로 그려 두어 설계 쪽 공백이기도 하다. 그래서 감점을 2점으로 제한했다.
- **개선(택1):** (a) dev API 앱 수명 주기에 워커 스레드 하나를 띄워 같은 `indexer`를 쓰게 한다(`lifespan`에서 `run_forever(stop)` 시작·종료). (b) 인덱스 레지스트리에 사용자별 DB 변경 시각(`contents.updated_at` 최댓값 등)을 비교해 오래된 인덱스를 다시 읽는 경로를 둔다. (c) 최소한 제출 응답 직후 I1~I2를 API 프로세스에서 동기로 돌려 축약 인덱스만이라도 반영한다. 어느 쪽이든 "API 제출 → 워커 처리 → API 검색" 통합 테스트를 추가한다.

### L1. 낮음: 공백만 있는 `title`/`author`/`user_note`를 그대로 저장한다 — `src/jupjup/api/dto.py:205-207`

- `title: "   "`이 202로 수락되어 제목이 공백 3칸이 된다. `""`는 추출 제목으로 대체되어 두 입력의 동작이 다르다. `strip()` 뒤 빈 값이면 `None`으로 바꾸거나 422로 거부한다.

### L2. 낮음: `url`에 제어 문자(개행 등)가 들어와도 수락한다 — `src/jupjup/api/dto.py:172-178`

- 접두사만 검사해 `https://a.com/\nX-Evil: 1`이 202로 저장된다. 지금은 메타데이터로만 쓰이고 네트워크 요청이 없어 위험은 낮지만, 나중에 실제 fetch(T25 이후)나 로그·헤더로 흘러가면 문제가 된다. 공백·제어 문자를 거부하거나 `pydantic.HttpUrl`로 파싱해 정규화한다.

### L3. 낮음: `seed load --analyze`(비엄격)가 한 건의 잡 등록 실패로 파일 전체를 롤백하고 첫 오류만 보고한다 — `src/jupjup/ingest/seeding.py:96-124`

- 일반 `seed load`는 비엄격일 때 성공한 줄을 넣는데, `--analyze`는 `INVALID_JOB_TRANSITION` 하나로 200건 모두 미반영하고 `1행 … c_alice_0001`만 보여 준다(1.6절). docstring에 의도로 적혀 있어 결함은 아니지만, `--strict` 의미와 겹친다. 활성 잡이 있는 콘텐츠를 미리 골라 줄 단위 오류로 보고하고 나머지는 넣거나, 최소한 "활성 잡이 있으면 `--replace-user` 또는 `worker run`을 먼저" 같은 안내를 출력한다.

### L4. 낮음: `worker run --once/--max-jobs`가 `--concurrency`를 무시하고 직렬로 돈다 — `src/jupjup/cli.py:318`

- 시작 문구는 "동시성 2"라고 찍지만 실제로는 `run_once()`를 하나씩 호출한다. 동작은 맞으므로 문구를 고치거나 도움말에 "--once는 직렬"이라고 적는다.

### L5. 낮음(유지보수): 회귀 테스트 공백 — `tests/unit/test_ingest_extractive.py`, `tests/integration/test_api_ingest.py`

- M1(문자 없는 본문), M2(프로세스 분리) 시나리오를 잡는 테스트가 없다. 단위 테스트가 한국어·영어·문장부호만 다뤄 `und` 경로를 놓쳤다.

### 참고 (감점 없음)

- T22 Loop 2 M1(재분석 실패가 이전 상태와 상관없이 콘텐츠를 `ready`로 만듦)이 `src/jupjup/ingest/jobs.py:339`에 그대로 있다. T23이 `:reanalyze` API와 `ingest reanalyze` CLI를 노출하지 않아 지금은 도달할 수 없다. 재분석 경로를 붙일 때 같이 고쳐야 한다.
- `ㅋㅋㅋㅋ`, `ㅠㅠ` 같은 자모만 있는 본문은 extract에서 `INGEST_EXTRACT_FAILED`가 난다. T21 동작이고 범위 밖이다.
- `ExtractiveMockAnalyzer`는 카테고리가 항상 `other`이고 요약이 틀 문장이다. 배선 검증용이라는 보고서 5절 2번 설명과 같다. T24 지표에 쓰지 않도록 주의한다.
- `data/baselines/*.json`의 수치가 현재 결과와 다른 것은 T23 이전부터이며 범위 밖이다(보고서 4절 참고와 같다).
- `api/dto.py`가 `ingest.jobs`, `ingest.service`, `ingest.fetch`를 직접 import한다. 지금은 순환이 없지만 API 계층이 인제스트 내부 타입에 묶인다. 라우트 파일 분리(5.7절)를 할 때 변환 함수를 함께 옮기면 좋다.

## 3. 채점 근거

| 항목 | 점수 | 근거 |
|---|---|---|
| 정확성 | 36 / 40 | 완료 조건 전부 재현, 설계 필드 일치, 검색 무회귀. M1 −2(정상 입력의 영구 실패), M2 −2(dev API 경로의 검색 가능 시점 미충족, 공개된 문제라 제한) |
| 안전성 | 28 / 30 | 사용자 격리·존재 비노출 404, dev 게이트(API와 CLI 모두), `extra="forbid"`로 `user_id` 주입 차단, 경로 이중 검사, 오류 정보 최소화, 네트워크 없음. L2 −1(url 제어 문자), L1 −1(공백 필드 저장, 입력 정규화 누락) |
| 유지보수성 | 28 / 30 | CLI와 API가 같은 `IngestBody`로 검증, T22 코드 무변경, 시계 주입, 51개 테스트, 설계 차이 문서화. L5 −1(M1·M2 회귀 테스트 공백), L3/L4 −1(CLI 의미 불일치) |
| **합계** | **92 / 100** | **PASS** |

## 4. 다음 단계 권고 (PASS이므로 필수 아님)

1. M1 수정과 단위·통합 테스트 추가 (작음, T24 전에 권장: T24 인제스트 평가가 숫자 위주 본문을 넣으면 같은 실패가 난다).
2. M2는 방식을 PM·Architect가 정한 뒤(앱 내 워커 스레드 또는 인덱스 재적재) 통합 테스트와 함께 반영.
3. L1~L4는 M1과 같은 묶음에서 처리 가능.

# Phase 4 최종 검수 — 검색 API(T15) 사이클, Loop 1/3

- **점수:** 90 / 100
- **상태:** PASS
- **항목별:** 정확성 36 / 40, 안전성 27 / 30, 유지보수성 27 / 30
- **루프백 대상:** 없음 (PASS). 다만 M1(dev bulkUpsert 원자성)과 M2(사용자 인덱스 무제한 생성)는 T23 인제스트 API가 같은 admin·레지스트리 경로를 쓰기 전에 Phase 2 소규모 작업으로 고칠 것을 강하게 권한다.
- **검수 대상:** `phase-4-review-search-api-loop1` HEAD `06df7d0` (`feat: implement T15 search API`, 직전 검수 `158ac0f`)
- **기준 문서:** `specs/prd_and_design.md` 5.8.1·5.9절·작업표 T15·AC-11, `specs/design_relaxation_v2.md` 11·12절, `specs/known_issues.md`, 이전 검수 `specs/phase4_review_*.md`
- **채점 정책:** 이전 검수와 같은 엄격도. 사람 검수 0건은 감점하지 않았다. 범위 밖: T23 인제스트 API, LLM 연동, 리랭커 채택.

## 0. 요약

- **명세 계약은 충족한다.** `/v1/search`, `/v1/query:parse`, dev admin 2종, `/healthz`가 5.9절 필드명과 타입으로 응답한다. 에러 코드 7종(`MISSING_USER`, `INVALID_USER`, `INVALID_QUERY`, `INVALID_FILTER`, `VALIDATION_ERROR`, `INDEX_NOT_READY`, `INTERNAL`)을 모두 직접 관찰했다. 모든 응답(에러 포함)이 `application/json; charset=utf-8`이다.
- **dev 게이트가 정확하다.** `env=test`와 `env=prod` 모두 admin 두 경로가 404 `NOT_FOUND`이고 OpenAPI에도 나오지 않는다. 비-dev에서 `now`는 422 `VALIDATION_ERROR`, dev에서는 동작한다. `query:parse`의 `now`는 모든 환경에서 422다.
- **사용자 격리가 지켜진다.** u_bob·u_carol로 alice 전용 질의 5종을 `limit=50`으로 돌렸을 때 다른 사용자 문서 0건이다. bob이 alice id로 upsert(헤더 불일치·user_id 위조 모두) 또는 delete를 시도하면 실패하고 alice 문서는 그대로다. `user_id` 본문 주입은 `extra_forbidden`으로 막힌다.
- **검색 순위 무회귀.** `158ac0f..HEAD`에서 `data/`, `src/jupjup/search/`, `src/jupjup/query/` 변경 없음. eval 4종 수치가 리랭커 Loop 2 검수와 소수점 4자리까지 같다. 회귀 사례 12종이 API로도 CLI·이전 검수와 같은 결과다.
- **새 결함 2건(중간):** dev strict bulkUpsert가 "0건 반영"이라고 답하면서 실제로는 DB와 키워드 인덱스에 기록한다(M1, 재현함). 인증 없는 `X-User-Id`마다 빈 사용자 인덱스가 영구 생성된다(M2, 2,000요청에 2,000개·약 8MB 재현함). 둘 다 기본 바인딩(loopback)과 기본 운영 경로의 검색 결과에는 영향이 없어 PASS 판정을 막지는 않지만, 경계선 점수다.

## 1. 직접 실행한 명령과 결과

### 1.1 정적 검사, 테스트, 평가

| 명령 | 결과 |
|---|---|
| `uv run pytest` (기본 addopts `-m 'not embed and not rerank'`) | **632 passed, 3 deselected** (경고 1건: Starlette `httpx` 비권장, 보고서 남은 문제 1과 같다) |
| `uv run ruff check src tests` | All checks passed |
| `uv run mypy src` | Success: no issues found in 60 source files |
| `uv run jupjup eval validate` | PASS. seeds 200, queries 259, review_status ai_draft_unreviewed 235 / needs_human_review 24, reviewed 0 |
| `eval run --mode mock --split dev --baseline data/baselines/mock.json` | PASS — R@10 0.9620, MRR 0.9958, nDCG 0.9795, cat-min 0.8838 |
| `eval run --mode mock --split test …` | PASS — R@10 0.9420, MRR 0.9867, nDCG 0.9589, cat-min 0.7812 |
| `eval run --mode recorded --split dev --baseline data/baselines/recorded.json` | PASS — R@10 0.9712, MRR 1.0000, nDCG 0.9860, cat-min 0.8894 |
| `eval run --mode recorded --split test …` | PASS — R@10 0.9720 (회귀 하한 0.972, 여유 0 그대로), MRR 0.9911, nDCG 0.9801, cat-min 0.8900 |
| `git diff --stat 158ac0f HEAD -- data/ src/jupjup/search src/jupjup/query` | 변경 없음 |

eval 리포트는 scratchpad에 썼고 저장소 `reports/`·기준선은 건드리지 않았다.

### 1.2 데이터 준비와 CLI

- `uv run jupjup seed load data/golden/seeds.jsonl --db var/review.db` → 200건 적재·인덱싱, 임베딩 대기 0 (alice 160, bob 30, carol 10)
- `JUPJUP_MODE=recorded uv run jupjup seed load … --db var/review_rec.db` → 같음
- `uv run jupjup api serve --db var/review.db --host 0.0.0.0 --port 8791` → "외부 바인딩은 기본으로 거부됩니다…" 출력, **exit 2** ✅
- `JUPJUP_ENV=test uv run jupjup api serve --db var/review.db --port 8791` 후 curl:
  - `GET /healthz` → 200 `{"status":"ok","index_ready":true,"embedder":"hashing-v1","mode":"mock"}`, `content-type: application/json; charset=utf-8`
  - `POST /v1/search` `now` 포함 → 422 `VALIDATION_ERROR` (`now는 dev 환경에서만…`)
  - `POST /v1/admin/contents:bulkUpsert` → 404 `NOT_FOUND`
  - `Content-Type: text/plain` 본문 → 422 `VALIDATION_ERROR`
  - 5MB 질의 본문 → 422 `INVALID_QUERY` (6.5ms)
- `JUPJUP_MODE=recorded uv run jupjup search "성수 cafe 추천" --user u_alice --db var/review_rec.db --now 2026-10-15T12:00+09:00` → `[EMBEDDING_CACHE_MISS] 녹화본에 없는 텍스트입니다` (API의 500과 같은 원인, 1.6절 참고)

### 1.3 회귀·과잉/과소 완화·요청 잠금 (API, dev, `now=2026-10-15T12:00+09:00`)

| 분류 | 질의 / 요청 | mock | recorded | 판정 |
|---|---|---|---|---|
| 회귀 S7 | `지난주 카톡으로 받은 회의 장소` | `0136`,`0146` + `time_window_expanded` | 같음 | ✅ |
| 회귀 | `레스토랑 추천 블로그` | `0153` | 같음 | ✅ |
| 회귀 | `다리 운동 영상` | `0040` 1위 | `0040`,`0051` | ✅ (known_issues 4 잔여 그대로) |
| 과소 완화 | `경주 맛집 인스타` / `하체 운동 유튜브` | `0153` / `0040` 1위, `platform_filter_dropped` | 같음 | ✅ |
| 이중 완화 기록 | `경주 맛집 카톡 논문` | `0153`, `platform_filter_dropped`+`content_type_filter_dropped` | 같음 | ✅ |
| 회귀 | `지지난주 성수 카페 약속` | `0140`,`0031` + `time_window_expanded` | 같음 | ✅ |
| 과잉 완화 / 없는 대상 | `mars migration documentary 저장한 거`, `화성 이주 다큐멘터리`, `양자역학 논문 정리` | 모두 200 empty (`no_relevant_match`) | 첫 질의 empty, 나머지 둘 500 (1.6절) | ✅ / 1.6 |
| 순위 | `환경 다큐` / `그 영화 예매했던 거` / `주식 공부 영상` | `0047` / `0147`,`0053` / `0063`,`0052` | `0047` / `0147` / `0052` 1위 | ✅ (이전 검수와 같다) |
| 명세 예시 | `지난달 인스타에서 본 성수동 카페` | `0001` 1위, time_range·platform hard가 5.9 예시와 같음 | 같음 | ✅ |
| 요청 잠금 | `경주 맛집` + `filters.platforms=[instagram]` | empty, `applied_relaxations=[]` (요청 facet은 풀지 않음) | 같음 | ✅ |
| 요청 vs 질의 충돌 | `경주 맛집 유튜브` + `platforms=[instagram]` | empty, `overridden_by_request=["platforms"]` | 같음 | ✅ |
| 요청 잠금 | `하체 운동` + `platforms=[youtube]` | `0050`,`0051` (모두 youtube) | 같음 | ✅ |
| 4중 잠금 | `카페` limit 50 + instagram·post·9월 | 2건, 전부 조건 충족, 완화 없음 | 같음 | ✅ |
| 필터 전용 | `인스타`, `지난달`, `유튜브 영상`, `작년 여름` | 200, browse 결과 10건 | 같음 | ✅ |
| 오타 | `성수동 카패` | `카패→카페` 교정, 성수 카페 문서 | 500 (1.6절) | ✅ / 1.6 |
| 영어 혼합 | `성수 cafe 추천`, `youtube 운동` | 교정 `cafe→카페`, 운동 영상 | 500 (1.6절) | ✅ / 1.6 |
| 특수문자 | `카페!!!@#`, `<script>…`, `'; DROP TABLE…` | 정상 / empty / empty (DB 무손상) | 500 (1.6절) | ✅ |

### 1.4 에러 경로와 경계값 (TestClient, mock·recorded 모두)

| 입력 | 결과 |
|---|---|
| 헤더 없음 / `""` / `u_Alice` / `" u_alice"` / `u_`+65자 | 400 `MISSING_USER` / `INVALID_USER` ×4 ✅ |
| `u_`+64자, `u_nobody` | 200 empty ✅ (단, M2: 레지스트리에 영구 등록) |
| `""`, `"   "`, `"\n\t"`, `"x"*201`, `"성수동 카페 "*30` | 422 `INVALID_QUERY` (`max_length 200`) ✅ |
| `"!!!"`, `"ㅋㅋㅋ"`, `"​"` / `"x"*200`, `"가"*200` | 422 `INVALID_QUERY` `no_searchable_text` / `low_information` ✅ |
| `query: 123`, `null`, 깨진 JSON, 배열 본문, 본문 `user_id` 추가 | 422 `VALIDATION_ERROR`, details에 입력값 echo 없음 ✅ |
| `limit` 0 / 51 / −1 / 10³⁰ | 422 `INVALID_FILTER` ✅ |
| `limit` 1.5 | 422 `VALIDATION_ERROR` ✅ |
| `limit "10"`, `limit true`, `explain "yes"` | 200 (pydantic lax 변환. L3) |
| `platforms ["tiktok"]`, `content_types ["reel"]` | 422 `INVALID_FILTER` ✅ |
| `saved_from > saved_to` | 422 `INVALID_FILTER` ✅ |
| `filters.user_id`, platforms 11개, naive/잘못된 날짜, `filters: "instagram"` | 422 `VALIDATION_ERROR` ✅ |
| `platforms: []` | 200 empty (L4) |
| dev `now` 정상 / naive / 잘못된 문자열 | 200 / 422 `VALIDATION_ERROR` ×2 ✅ |
| test·prod `now` / prod `now: null` | 422 `VALIDATION_ERROR` / 200 ✅ |
| `GET /v1/search` / 없는 경로 | 405 `HTTP_ERROR` / 404 `NOT_FOUND` (L5) |
| `index_ready=False` (테스트로 확인) | 503 `INDEX_NOT_READY` ✅ |
| 내부 예외 (`RuntimeError("secret database password")`, 테스트) | 500 `INTERNAL`, 본문에 secret 없음 ✅ |
| `explain=true` (랭크·필터 전용·완화·empty 모두) | 결과마다 `debug={ranks, rrf, features}`만. KeyError 없음 ✅. `explain=false`면 `debug` 키 없음 ✅ |

### 1.5 dev admin (DB 사본에서)

| 시나리오 | 결과 |
|---|---|
| bob 헤더로 alice 레코드 업서트 | `failed[INVALID_CONTENT] user_id가 X-User-Id와 달라요.` ✅ |
| bob 헤더로 `user_id`를 u_bob으로 위조한 `c_alice_0001` (strict/non-strict) | `다른 사용자의 저장물 id입니다` 실패, alice 문서 제목 유지 ✅ |
| bob이 `DELETE c_alice_0001` | 404 `NOT_FOUND`, alice 검색 결과 유지 ✅ |
| strict, 유효 1 + 무효 1 (mock) | upserted 0, 유효 문서도 검색 안 됨 ✅ |
| non-strict, 무효·유효·형식 오류 | upserted 1, failed index 0·2, 유효 문서 검색됨 ✅ |
| 자기 문서 delete | 204 빈 본문, 즉시 검색에서 사라짐, 새 앱으로 재구축해도 없음 ✅ |
| 같은 id 재삭제 / 헤더 없음 delete | 404 `NOT_FOUND` / 400 `MISSING_USER` ✅ |
| 501건 / 0건 | 422 `VALIDATION_ERROR` / 200 `upserted 0` ✅ |
| 같은 id 2건 strict | `upserted: 2` (L2) |
| **strict, recorded 모드, 녹화 없는 새 레코드 2건** | **응답 `upserted 0`, 두 건 모두 `failed`. 그러나 DB에 두 건 모두 존재, 키워드 인덱스에 첫 건 존재 (M1)** |
| 동시성: 실제 서버에서 검색 8스레드 + bulkUpsert 40건×30회 | 검색 1,336회 전부 200, 쓰기 30회 전부 200, 서버 로그 에러 없음 ✅ |

### 1.6 recorded 모드의 미녹화 질의

recorded 모드에서 녹화본에 없는 질의(`성수동 카패`, `제쥬 숙소`, `성수 cafe 추천`, 특수문자 질의 등)는 `EmbeddingCacheMiss`가 `EmbeddingProviderError` 하위가 아니라서 검색 서비스가 degrade하지 않고 500 `INTERNAL`이 된다. 메시지는 노출되지 않고 서버 로그에만 남는다. 5.8.1절이 이 오류를 "recorded 모드 전용"으로 두고 5.9절 표가 미매핑 오류를 500으로 정하므로 **명세 위반이 아니고 T15 이전부터의 동작**(CLI도 같은 오류)이라 감점하지 않았다. 다만 recorded 모드로 API 시연을 할 계획이면 PM이 알고 있어야 한다.

## 2. 피드백 (심각도 순)

### 중간

**M1. dev bulkUpsert가 실패라고 답하면서 데이터를 기록한다** — `src/jupjup/api/app.py:147-162`, `:165-171`
- strict 경로는 `repo.upsert_many`로 먼저 커밋(`:149`)한 뒤 레코드마다 `index_content`(`:151`)를 부른다. 인덱싱 도중 `JupjupError`가 나면(`:154`) 응답은 `upserted: 0`과 전 항목 `failed`지만 DB에는 전부 남고 키워드 인덱스에는 앞쪽 일부가 남는다. recorded 모드에서 녹화 없는 레코드로 재현했다(1.5절). 보고서의 "strict=true는 검증 실패가 하나라도 있으면 아무 항목도 쓰지 않는다"는 사전 검증 단계에만 맞다.
- non-strict 경로(`:167-170`)도 같다. `repo.upsert`가 커밋된 뒤 인덱싱이 실패하면 `failed`로 보고되지만 DB에 남고, 다음 재시작 재구축 때 갑자기 검색된다.
- 인덱싱 실패를 `INVALID_CONTENT`(`:158`, `:170`)로 분류하는 것도 틀렸다. 콘텐츠 형식 문제가 아니라 provider 문제다.
- 개선: (a) 인덱싱 실패 시 해당 id를 저장소에서 지우고 레지스트리에서 제거해 보상하거나, (b) DB 커밋은 성공으로 세고 `embedding_pending`/별도 코드(예: 실패 항목의 `code`를 예외의 `exc.code`)로 보고해 응답과 상태를 일치시킨다. strict는 "검증 통과 후 기록"의 의미를 문서로 확정한다. 이 경로를 재현하는 통합 테스트를 추가한다(provider가 `JupjupError`를 내는 fake embedder).

**M2. 인증 없는 `X-User-Id`마다 빈 사용자 인덱스가 영구 생성된다** — `src/jupjup/index/registry.py:83-91` (호출부 `src/jupjup/search/service.py:713-716`, `src/jupjup/api/app.py:222-225`)
- `UserIndexRegistry.get`은 없으면 만든다. 이제 이 경로가 HTTP로 노출돼, 서로 다른 정규식 통과 id 2,000개로 `/v1/query:parse`를 부르면 레지스트리가 3 → 2,003개, 약 8MB가 증가했다(재현). 해제 경로가 없어 프로세스 메모리가 요청 수에 비례해 자란다. 기본 loopback 바인딩이라 위험은 제한적이지만 `--allow-external-bind`를 쓰면 바로 메모리 DoS가 된다.
- 개선: 읽기 경로(search/parse)는 저장 없이 공유 빈 인덱스(또는 `peek`)를 쓰고, 인덱스 생성은 indexer의 쓰기 경로에서만 하도록 레지스트리 API를 나눈다. 회귀 테스트로 "알 수 없는 사용자 검색 후 `registry.users()` 불변"을 고정한다.

### 낮음

**L1. OpenAPI가 실제 에러 봉투와 다르다** — `src/jupjup/api/app.py:199`, `:222`, `:240`
- `/openapi.json`의 `/v1/search` 422 응답이 FastAPI 기본 `HTTPValidationError`(`{"detail": [...]}`)를 가리키고, 400·503·500은 문서에 없다. 실제 응답은 `{"error": {...}}`다. AC-11의 "OpenAPI 문서가 생성된다"는 충족하지만 클라이언트가 문서를 믿으면 에러 파싱이 틀린다.
- 개선: `ErrorEnvelope` 모델을 만들고 라우트 `responses={400:…, 422:…, 503:…, 500:…}`로 선언한다.

**L2. 같은 요청 안의 중복 id를 두 번 센다** — `src/jupjup/api/app.py:130-153`
- 같은 `id` 2건을 보내면 `upserted: 2`이고 마지막 항목이 이긴다. 중복을 항목 실패로 보고하거나 문서화한다.

**L3. 타입 lax 변환** — `src/jupjup/api/dto.py:33-36`
- `limit: "10"`, `limit: true`(→1), `explain: "yes"`가 200이다. 명세가 엄격 타입을 요구하진 않지만 `extra="forbid"`로 경계를 세운 의도와 맞추려면 `ConfigDict(strict=True)` 또는 `StrictInt`/`StrictBool`을 고려한다.

**L4. `filters.platforms: []`가 "아무 플랫폼도 허용 안 함"으로 처리된다** — `src/jupjup/api/app.py:115-121`
- 200 empty가 된다. 빈 목록을 "필터 없음"으로 볼지 `INVALID_FILTER`로 볼지 명세에 없으니 정하고, 어느 쪽이든 API 경계에서 명시적으로 처리한다(현재는 도메인 해석이 암묵적으로 노출됨).

**L5. 명세 표에 없는 `HTTP_ERROR` 코드** — `src/jupjup/api/errors.py:58-60`
- 405 등은 `HTTP_ERROR`와 Starlette `detail` 문자열(`Method Not Allowed`)을 그대로 쓴다. 내부 정보 노출은 아니지만 코드 목록이 5.9절과 어긋난다. `METHOD_NOT_ALLOWED`처럼 명시 매핑하고 설계서 표에 추가한다.

**L6. 시작 재구축 실패가 영구 503이고 healthz는 `status: ok`다** — `src/jupjup/api/app.py:186-192`, `:228-235`
- 재시도·재구축 경로가 없고, `/healthz`는 HTTP 200 `status:"ok"`에 `index_ready:false`만 담는다. 헬스체크가 `status`만 보면 준비 안 된 인스턴스를 정상으로 판단한다. 준비 전에는 `status:"starting"` 또는 503을 고려한다.

**L7. 준비 상태의 이중 정의와 보고서 서술 불일치** — `src/jupjup/api/app.py:186`, `src/jupjup/index/registry.py:68`
- 레지스트리에 이미 `self.ready`가 있는데(사용처 없음) 앱은 `app.state.index_ready`를 따로 둔다. 보고서 "명세와 다른 점 2"의 "레지스트리가 준비 상태를 제공하지 않는다"는 서술도 정확하지 않다. 한쪽으로 합친다.

**L8. 테스트 공백** — `tests/integration/test_api_search.py`
- `env="prod"` 게이트(현재 `test`만), `query:parse`의 `INVALID_QUERY`/`MISSING_USER`, non-strict bulkUpsert 혼합 결과, 인덱싱 실패 경로(M1), 알 수 없는 사용자 레지스트리 불변(M2)에 테스트가 없다. 이번 검수에서 직접 확인한 것들이므로 회귀 테스트로 고정한다.

**L9. 사소한 정리** — `src/jupjup/cli.py:100`
- `Settings(**updates)  # type: ignore[arg-type]` 대신 `Settings.model_validate(updates)` 또는 타입이 있는 인자로 넘긴다. `_bulk_upsert`의 strict/non-strict 두 분기는 "검증 → 기록 → 인덱싱 → 결과 집계"로 묶으면 M1 수정과 함께 단순해진다.

### 정보 (감점 없음)

- recorded 모드 미녹화 질의 500 (1.6절): 기존 동작, 명세 준수.
- `Settings.env` 기본값이 `dev`라 `jupjup api serve`는 기본으로 admin 라우트와 `now`를 연다(`src/jupjup/config.py:410`). T15 이전부터의 설정이고 loopback 기본 바인딩이 완충한다. 운영 배포 문서에 `JUPJUP_ENV=prod`를 명시할 것.
- `X-User-Id`는 인증이 아니다(보고서 남은 문제 3). 외부 바인딩 안전장치(`--allow-external-bind`)는 명세보다 보수적인 좋은 결정이다.

## 3. 채점 근거

| 항목 | 점수 | 감점 근거 |
|---|---:|---|
| 정확성 | 36 / 40 | M1 −2 (strict 원자성 약속과 응답·상태 불일치, 재현), L1 −1 (OpenAPI 에러 스키마 불일치), L2·L4 −1 |
| 안전성 | 27 / 30 | M2 −2 (요청당 영구 인덱스 생성, 재현), L6 −0.5, L3·L5 −0.5 |
| 유지보수성 | 27 / 30 | L8 −1.5 (위 경로 테스트 공백), L7 −0.5, L9·M1 분기 중복·오류 분류 −1 |
| **합계** | **90 / 100** | **PASS** (경계선) |

잘한 점: 공개 DTO를 서비스 내부 타입과 분리해 진단 필드가 새지 않게 했고, 에러 봉투·charset·내부 메시지 비노출이 모든 경로에서 일관됐다. dev 게이트를 라우트 등록 단계에서 처리해 비-dev에서 OpenAPI에도 나오지 않는다. 검색·완화·순위 코드와 데이터를 전혀 건드리지 않아 eval 수치가 그대로다. 동시 쓰기·읽기 부하에서도 오류가 없었다.

## 4. 다음 단계 권고

PASS이므로 루프를 끝낸다. T23(인제스트 API)이 dev admin과 레지스트리 쓰기 경로를 확장하므로, 그 전에 Phase 2 소규모 작업으로 M1·M2와 L8 테스트를 먼저 처리하기를 권한다. L1·L5·L6은 T23의 에러 코드 추가(`INGEST_*`)와 함께 정리하면 효율적이다.

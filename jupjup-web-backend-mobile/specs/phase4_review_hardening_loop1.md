# Phase 4 최종 검수: 보강(API·리랭커) 사이클, Loop 1/3

- **점수:** 94 / 100
- **상태:** PASS
- **항목별:** 정확성 37.5 / 40, 안전성 28.5 / 30, 유지보수성 28 / 30
- **루프백 대상:** 없음 (PASS). 아래 중간 1건(N1)과 낮음 항목은 리랭커 채택 재평가 또는 T23 착수 전에 Phase 2 소규모 작업으로 처리하기를 권한다.
- **검수 대상:** `phase-4-review-hardening-loop1` HEAD `5ed7842` (`fix: harden API bulk writes and reranker gates`). 직전 검수 `94d0bc5`(검색 API Loop 1)
- **기준 문서:** `specs/prd_and_design.md` 5.8.1·5.9절·작업표 T15, `specs/design_reranker_query_assist.md` 4.7·9.1·10.1절, `specs/design_relaxation_v2.md` 11·12절, `specs/phase4_review_search-api_loop1.md` M1·M2·L1~L9, `specs/phase4_review_reranker_loop2.md` S1~S3·L1~L7, `specs/known_issues.md`, 이전 검수 `specs/phase4_review_*.md`
- **채점 정책:** 이전 검수와 같은 엄격도. 사람 검수 0건, 리랭커 채택 REJECT 자체는 감점하지 않았다. 범위 밖: T23 인제스트 API, LLM 연동, 리랭커 채택.

## 0. 요약

- **M1(bulkUpsert 원자성) 해소.** recorded 모드에서 녹화 없는 레코드로 strict와 non-strict를 모두 재현했다. 응답, SQLite(contents·embeddings 행 수), 메모리 인덱스가 서로 맞는다. strict 커밋 단계 실패(다른 사용자 id 충돌)도 트랜잭션이 롤백되고 인덱스가 게시되지 않는다. 실패 code는 실제 예외 code(`EMBEDDING_CACHE_MISS`, `INVALID_CONTENT`)를 쓴다.
- **M2(빈 사용자 인덱스 영구 생성) 해소.** 미등록 사용자 2,000명으로 search·parse를 호출한 뒤에도 레지스트리는 3 → 3이다(dev, prod 모두). 미등록 사용자 DELETE 300건도 404이고 레지스트리는 변하지 않는다.
- **S1~S3 해소.** extra 없는 기본 설치에서 장치·cpu 설정 6가지 조합 모두 `required=true`는 `RerankerUnavailable`, optional은 `RuntimeWarning`과 `unavailable` 상태다. 고정 회귀는 9.1절 목록 전체(18개 질의 × 두 팔 + 프로브 3개 × 두 팔 = 42건)를 all-split으로 돌린다. 누락은 fail-closed다. test A/B의 challenge negative 분모 0은 `n/a`로 처리되고, `--confirm-with`가 test 리포트로 규칙 7을 계산한다.
- **검색 순위 무회귀.** eval 4종 수치가 직전 검수와 소수점 4자리까지 같다. `src/jupjup/search`의 변경은 두 줄(`registry.peek`, `is_replay` 속성 접근)뿐이고, `src/jupjup/query`와 `data/`는 변경이 없다. alice 질의 232개를 160건 재업서트(strict 80 + non-strict 80) 전후로 비교했을 때 결과 id, 점수(소수 6자리), 완화 기록이 모두 같다.
- **새 결함은 중간 1건과 낮음 몇 건이다.** `--confirm-with`가 팔 설정(`search_overrides`)이 같은지 검사하지 않아, 다른 설정으로 돌린 test 결과가 규칙 7을 채울 수 있다(N1, 재현함). 나머지는 API 전역 읽기 잠금, CLI 개행 user id 회귀, 테스트 공백이다.

## 1. 직접 실행한 명령과 결과

### 1.1 정적 검사, 테스트, 평가

| 명령 | 결과 |
|---|---|
| `uv run pytest` (기본 addopts) | **646 passed, 3 deselected** (32.3s). 경고 1건: Starlette `httpx` 비권장 (보고서 남은 문제 3과 같다) |
| `uv run ruff check src tests` | All checks passed |
| `uv run mypy src` | Success: no issues found in 60 source files |
| `uv run jupjup eval validate` | PASS. seeds 200, queries 259 (dev 158 / test 101), lexicon 139, reviewed 0 |
| `eval run --mode mock --split dev --baseline data/baselines/mock.json` | PASS: R@10 0.9620, MRR 0.9958, nDCG 0.9795, cat-min 0.8838 |
| `eval run --mode mock --split test …` | PASS: R@10 0.9420, MRR 0.9867, nDCG 0.9589, cat-min 0.7812, FE 0.012 |
| `eval run --mode recorded --split dev --baseline data/baselines/recorded.json` | PASS: R@10 0.9712, MRR 1.0000, nDCG 0.9860, cat-min 0.8894 |
| `eval run --mode recorded --split test …` | PASS: R@10 0.9720 (회귀 하한 0.972, 여유 0 그대로), MRR 0.9911, nDCG 0.9801, cat-min 0.8900 |
| `git diff --stat 94d0bc5 HEAD -- data/ src/jupjup/query` | 변경 없음 |
| `git diff 94d0bc5 HEAD -- src/jupjup/search` | `service.py:716` `get`→`peek`, `cross_rerank.py:187` `getattr`→속성. 순위 로직 변경 없음 |
| `git diff --check 94d0bc5 HEAD` | 통과 |

eval·A/B 산출물은 scratchpad에 썼다. 저장소 `reports/`, 기준선, 녹화본은 건드리지 않았다.

### 1.2 데이터 준비와 CLI

- `uv run jupjup seed load data/golden/seeds.jsonl --db var/review.db` → 200건 적재·인덱싱, 임베딩 대기 0 (alice 160, bob 30, carol 10). `JUPJUP_MODE=recorded … --db var/review_rec.db`도 같다.
- `jupjup search "<질의>" --user u_alice --db var/review.db --now 2026-10-15T12:00+09:00`: 회귀 12종이 정상 출력된다. 빈 문자열은 `[INVALID_QUERY] 질의는 1~200자여야 해요.`, `!!!@@@###`는 `[INVALID_QUERY] 검색할 단어가 없어요.`, `유튜브`는 `의도: browse`다.
- `jupjup search "카페" --user $'u_alice\n' --db var/review.db` → **`ValueError: user_id 형식 오류` traceback** (N3. 직전 커밋은 빈 결과였다).

### 1.3 회귀·완화·요청 잠금·경계값 (API TestClient, dev, `now=2026-10-15T12:00+09:00`)

| 분류 | 질의 / 요청 | mock | recorded | 판정 |
|---|---|---|---|---|
| 회귀 S7 | `지난주 카톡으로 받은 회의 장소` | `0136`,`0146` + `time_window_expanded` | 같음 | ✅ |
| 회귀 | `레스토랑 추천 블로그` | `0153` | 같음 | ✅ |
| 회귀 | `다리 운동 영상` | `0040` 1위 | `0040`,`0051` | ✅ (known_issues 4 그대로) |
| 과소 완화 | `경주 맛집 인스타` / `하체 운동 유튜브` | `0153` / `0040` 1위, `platform_filter_dropped` | 같음 | ✅ |
| 이중 완화 기록 | `경주 맛집 카톡 논문` | `0153`, platform → content_type 순서 2개 | 같음 | ✅ |
| 회귀 | `지지난주 성수 카페 약속` | `0140`,`0031` + `time_window_expanded` | 같음 | ✅ |
| 과잉 완화 / 없는 대상 | `mars migration documentary 저장한 거`, `화성 이주 다큐멘터리`, `양자역학 논문 정리` | 모두 empty `no_relevant_match` | 첫 질의 empty, 나머지 500 | ✅ / 기존 정보 항목 |
| 순위 | `환경 다큐` / `그 영화 예매했던 거` / `주식 공부 영상` | `0047` / `0147`,`0053` / `0063`,`0052` | `0047` / `0147` / `0052` 1위 | ✅ 이전과 같음 |
| 명세 예시 | `지난달 인스타에서 본 성수동 카페` | `0001` 1위, 완화 없음 | 같음 | ✅ |
| 요청 잠금 | `경주 맛집` + `platforms=[instagram]` / `content_types=[paper]` | empty, `applied_relaxations=[]` | 같음 | ✅ |
| 오타 | `성수동 카패`, `어버이날 선물 추쳔`, `기휴변화 논문`, `성수동까페`, `떡복이 맛집` | 교정 후 관련 결과 (mock `떡복이` empty는 기존과 같음) | `카패`만 500, 나머지 교정 | ✅ 이전과 같음 |
| 영어 혼합 | `성수동 cafe 인스타 last month`, `성수 cafe 추천` | 카페 문서 | 500 (녹화 범위 밖) | ✅ / 기존 |
| 필터 전용 | `유튜브`, `유튜브 영상`, `인스타 사진`, `지난달 저장한 거` | browse 최신순 | 같음 | ✅ |
| 특수문자 | `<script>…`, `'; DROP TABLE contents;--`, `😀 카페`, 탭·앞뒤 공백 | empty / 카페 문서, DB 정상 | 일부 500 (녹화 범위 밖) | ✅ / 기존 |
| 경계값 | 빈 문자열, `!!!@@@###`, `가`×200, `가`×201 | 422 `INVALID_QUERY` (200자 반복은 "반복된 문자만으로는…", 기존 규칙) | 같음 | ✅ |
| 격리 | u_bob·u_carol·u_nobody로 alice 질의 3종 `limit=50` | alice 문서 0건. bob/carol `성수동 카페`는 자기 문서만 | 같음 | ✅ |

recorded 미녹화 질의 500은 직전 검수 1.6절과 같은 기존 동작이다(명세 준수, 감점 없음).

### 1.4 API 에러 코드·dev 게이트 (TestClient)

| 요청 | 결과 |
|---|---|
| 헤더 없음 / `u_alice' OR 1=1` | 400 `MISSING_USER` / 400 `INVALID_USER` |
| `query:parse` 헤더 없음 / `!!!` / `now` 포함 | 400 `MISSING_USER` / 422 `INVALID_QUERY` / 422 `VALIDATION_ERROR` |
| `platforms=[tiktokx]` / `limit=51` | 422 `INVALID_FILTER` (5.9 표 그대로) |
| naive `saved_after`, naive `now`, `user_id` 본문 주입, `text/plain`, 깨진 JSON, items 501건 | 모두 422 `VALIDATION_ERROR` |
| `limit:"10"`, `limit:true`, `explain:"yes"`, `strict:"false"` (L3) | 모두 422 `VALIDATION_ERROR` ✅ |
| `GET /v1/search` (L5) / 없는 경로 | 405 `METHOD_NOT_ALLOWED` ✅ / 404 `NOT_FOUND` |
| bob이 `c_alice_0001` DELETE | 404 `NOT_FOUND`, alice 문서 유지 |
| `env=prod`: bulkUpsert / `now` / OpenAPI admin 경로 | 404 / 422 `VALIDATION_ERROR` / 없음 ✅ (`env=dev`는 200 / 동작 / 있음) |
| 재구축 실패 컨테이너 (L6·L7): `/healthz` / search / parse | 503 `{"status":"starting","index_ready":false,…}` / 503 `INDEX_NOT_READY` / 503 ✅ |
| 재구축 실패 컨테이너: bulkUpsert | **200** (N5) |
| OpenAPI (L1) | search·parse 400/422/500/503, bulkUpsert 400/422/500이 `ErrorEnvelope` ✅. **DELETE는 여전히 422 `HTTPValidationError`이고 400/404가 없다** (N6) |
| 모든 응답 content-type | `application/json; charset=utf-8` |

### 1.5 M1 재현 (원자성), 복사본 DB 사용

`var/review_rec.db`·`var/review.db`를 scratchpad에 복사해 사용했다. 상태는 `(contents 행, embeddings 행, alice 메모리 인덱스 문서 수, rev 문서)`로 적는다.

| 시나리오 | 응답 | 전 → 후 상태 |
|---|---|---|
| recorded, strict, [기존 `c_alice_0002` + 녹화 없는 새 2건] | `upserted 0`, 새 2건 `EMBEDDING_CACHE_MISS` | `(200,400,160,[])` → 같음 ✅ |
| recorded, non-strict, 같은 3건 | `upserted 1`(변경 없는 기존 건), 새 2건 실패 | 같음 ✅ (실패 항목은 DB·인덱스에 없다) |
| 같은 id 2건, non-strict (L2) | 둘 다 `DUPLICATE_CONTENT`, `upserted 0` | 변화 없음 ✅ |
| mock, strict, bob이 [자기 새 문서 + alice id] (커밋 단계 실패) | `upserted 0`, 두 항목 `INVALID_CONTENT` | `c_bob_rev9` DB 0행, bob 인덱스에 없음, alice 문서 소유자·제목 유지 ✅ |
| mock, strict 5건 배치 10회 + 동시 검색·인덱스 관찰 스레드 3개 | 오류 0 | 관찰된 인덱스 스냅샷 중 5의 배수가 아닌 것 0 (copy-on-write 게시가 원자적) ✅ |
| 재업서트 동치성: alice 시드 80건 strict + 80건 non-strict 재업서트 | 160 upserted | 골든 alice 질의 232개의 결과·점수·완화가 전과 같다 ✅ |

### 1.6 M2 재현

| 시나리오 | 결과 |
|---|---|
| dev, 서로 다른 미등록 사용자로 parse 1,000회 + search 1,000회 | 레지스트리 3 → **3** ✅ (직전 검수: 3 → 2,003) |
| prod, 같음 | 3 → 3 ✅ |
| dev, 미등록 사용자 DELETE 300회 | 모두 404, 레지스트리 3 → 3 |

### 1.7 리랭커 S1~S3 (기본 설치: `find_spec('torch')`, `find_spec('sentence_transformers')` 둘 다 `None`)

**S1.** `_model_reranker`, `mode=live`, `enabled=true`:

| required | enabled_on_cpu | device | 결과 |
|---|---|---|---|
| true | false/true | auto/mps/cpu (6조합) | 모두 `RerankerUnavailable: rerank extra를 설치하세요` ✅ |
| false | false/true | auto/mps/cpu (6조합) | 모두 `(None, 'unavailable')` + `RuntimeWarning` ✅ |
| (enabled=false, required=true) | | | `(None, 'disabled')` ✅ |

**S2·S3.** `jupjup eval ab --mode recorded --split dev --arms A0,A1`:

- 두 번 실행 결과가 `cmp` 동일하다(결정적). 수치는 Recall −0.0315 [−0.0651, −0.0063], nDCG −0.0266로 리랭커 Loop 2와 같다.
- 규칙 1 상세: `fixed_regressions=42/42 failed=['다리 운동 영상(c_alice_0051)', '기휴변화 논문(c_alice_0096)']`. 범위가 넓어져 **test split의 오타 사례 q_0038에서 A1이 1위를 바꾸는 것이 새로 드러났다**(정보 I1). 판정은 REJECT로 이전과 같다.
- (진단) `--split test`: `metrics_complete=True`, `challenge_negative_true_empty=n/a (denominator=0)`, 분모 `{'challenge_positive': 8, 'challenge_negative': 0}` ✅. 규칙 1은 고정 회귀와 positive 0.875 때문에 FAIL이다. **튜닝이나 설정 변경에는 쓰지 않았다.** test는 이미 blind가 아니다(설계 8.4-5).
- `--confirm-with <test.json>`: `7_test_confirmation: test 1~4 재확인` FAIL로 계산된다 ✅. dev 리포트를 넘기면 split 오류, mode가 다르면 mode 오류, `{}`를 넘기면 split 오류로 exit 2 ✅.
- **N1 재현:** `--overrides '{"cross_rerank":{"n_global":5}}' --confirm-with <기본 설정 test.json>` → 검사 없이 받아들인다. 리포트의 팔 설정은 `search_overrides={'cross_rerank': {'n_global': 5}}`인데 규칙 7은 기본 설정 test 결과로 계산됐다.

### 1.8 동시성 비용

같은 앱에서 검색 100회를 돌렸다. 1 스레드는 총 502ms, p50 4.9ms다. 8 스레드는 총 549ms, p50 41.5ms, p95 57.8ms다. 전역 `state_lock` 때문에 검색이 직렬화된다(N2). 지금은 GIL 때문에 처리량 손실이 거의 없지만, 대기 시간은 동시 요청 수에 비례해 늘어난다.

## 2. 이전 검수 항목 대조

| 출처 | 항목 | 판정 | 근거 |
|---|---|---|---|
| API M1 | strict·non-strict 원자성, 실패 code | **해소** | 1.5절. `api/app.py:170-210`, `index/service.py:66-153`, `storage/repositories.py:75-85` |
| API M2 | 읽기 경로 빈 인덱스 영구 생성 | **해소** | 1.6절. `registry.py:93-99`, `search/service.py:716` |
| API L1 | OpenAPI 에러 봉투 | 대부분 해소 | DELETE 경로만 남음 (N6) |
| API L2 | 요청 내 중복 id | 해소 | 1.5절 |
| API L3 | lax scalar | 해소 | 1.4절 |
| API L4 | `platforms: []` | 미결 (명세 결정 대기, 보고서 공개) | 200 empty 그대로. 감점 유지 −0.5 |
| API L5 | 미명세 HTTP code | 해소 | 405 `METHOD_NOT_ALLOWED`, 5.9절 표 갱신 |
| API L6·L7 | 준비 상태 | 해소 | 1.4절, `registry.ready`로 일원화 |
| API L8 | 테스트 공백 | 부분 해소 | M1 provider 단계·M2·중복·엄격 타입·OpenAPI·준비 상태는 추가됨. 남은 공백은 N4 |
| API L9 | 정리 | 해소 | `cli.py:100` `Settings.model_validate`, bulkUpsert 준비/커밋 분리 |
| 리랭커 S1 | extra 미설치 + required | **해소** | 1.7절, `container.py:89-112` |
| 리랭커 S2 | 고정 회귀 범위·조용한 생략 | **해소** | `ab.py:164-192, 306-351`. 9.1절 목록과 대조함(요청 잠금 q_0215~0219, 오타 q_0037·0038·0042·0048·0057, browse q_0220·0221). 빈 입력은 42건 전부 실패 (`test_fixed_regressions_never_silently_skip_missing_cases`) |
| 리랭커 S3 | test 분모 0, 규칙 7 경로 | **해소, 부작용 있음** | 1.7절. 설정 일치 검사 누락 (N1) |
| 리랭커 L1·L2 | 보고서 정정 | 해소 | `phase2_reranker_loop2_report.md`, `phase2_reranker_report.md:25,47-55` diff 확인 |
| 리랭커 L3·L5 | Protocol `is_replay`, dtype 중복 | 해소 | `providers/rerank.py:21-30`, `rerank_bge.py:57` |
| 리랭커 L4 | now 축 테스트 | 해소 | `test_cross_rerank.py:538` (`지난주 카톡으로…`) |
| 리랭커 L6 | RSS 누락 | 해소 | `ab.py:627`, `test_missing_rss_measurement_fails_operations_rule` |
| 리랭커 L7 | 프로브 now 하드코딩 | 미조치 (보고서 공개, 현재 골든 now와 일치) | 감점 없음 |

보고서 주장(646 passed, eval 수치, 금지 범위 준수)은 모두 직접 실행 결과와 맞다.

## 3. 피드백 (심각도 순)

### 중간

**N1. `--confirm-with`가 팔 설정이 같은지 확인하지 않는다.** `src/jupjup/cli.py:590-600`, `src/jupjup/eval/ab.py:651-654`
- 검사하는 것은 `config.split == "test"`, `config.mode == mode`, 그리고 (baseline, candidate) **이름**뿐이다. `--overrides`나 팔의 `search_overrides`·`cross_rerank`·`query_assist`가 달라도 test 결과를 받아들인다(1.7절 재현: dev `n_global=5`에 기본 설정 test 결과가 적용됨). 녹화본·골든셋 버전 일치도 확인하지 않는다.
- 설계 10.1-7의 "위 1~4를 test에서도 만족"은 **같은 후보 설정**을 test에서 확인하라는 뜻이다. 지금은 다른 설정의 test PASS로 규칙 7을 통과시킬 수 있다. 규칙 7이 열리는 쪽(fail-open)으로 틀린다. 지금은 모든 비교가 다른 규칙으로 REJECT라 실제 판정에는 영향이 없고, 규칙 8(사용자 승인)이 남아 있다. 그래도 채택 재평가 전에 고쳐야 한다.
- 개선: test 리포트의 `config.arms`(이름별 `cross_rerank`, `query_assist`, `search_overrides`)와 `bootstrap_*`이 현재 `ABConfig`와 같은지 비교한다. 다르면 exit 2 또는 해당 비교의 규칙 7 FAIL로 처리한다. 가능하면 녹화본과 골든셋 해시도 리포트에 남겨 비교한다. CLI 경로(정상, split 불일치, mode 불일치, 설정 불일치) 테스트를 추가한다.

### 낮음

**N2. API 전역 `state_lock`이 모든 검색을 직렬화한다.** `src/jupjup/api/app.py:218, 248, 259, 284, 290`
- strict 경로는 copy-on-write로 원자적으로 게시한다. 그래서 읽기 잠금이 필요한 이유는 non-strict(`apply_prepared`, `index/service.py:118-127`)와 DELETE(`:155-157`)가 라이브 인덱스를 제자리에서 고치기 때문이다. 대가로 동시 요청 8개의 p50이 4.9ms에서 41.5ms가 된다(1.8절).
- 리랭커를 켜면 설계 4.7절의 "실행기가 바쁘면 큐에 쌓지 않고 바로 v2"가 사실상 "잠금 앞에서 줄 서기"로 바뀐다. 300ms 타임아웃 추론이 N개 쌓이면 N×300ms까지 기다린다. 리랭커는 기본으로 꺼져 있고 미채택이라 영향이 제한적이다.
- 개선: non-strict와 DELETE도 `stage_updates`/`publish`(또는 문서 단위 copy-on-write)로 게시하고 검색 읽기 잠금을 없앤다. 쓰기끼리만 잠근다. 유지하려면 설계 5.9절이나 4.7절에 직렬화를 명시한다.

**N3. CLI에서 개행이 붙은 user id가 traceback을 낸다 (이번 변경의 회귀).** `src/jupjup/search/service.py:714-716`, `src/jupjup/index/registry.py:85, 95`
- `USER_ID_RE`(`^…$`)를 서비스와 `get`은 `.match`로, 새 `peek`는 `.fullmatch`로 검사한다. `u_alice\n`은 `match`를 통과하고 `fullmatch`에서 `ValueError`가 난다. `jupjup search "카페" --user $'u_alice\n'`이 traceback으로 끝난다(1.2절. 직전 커밋은 빈 결과). HTTP 헤더에는 개행이 들어갈 수 없어 API에는 영향이 없다.
- 개선: 모든 검사를 `fullmatch`(또는 `\Z`)로 통일한다. 그러면 서비스가 `InvalidUserError`를 낸다. 경계 테스트를 추가한다.

**N4. 테스트 공백 (API L8 잔여, 새 경로).** `tests/integration/test_api_search.py`, `tests/unit/test_cross_rerank.py`
- `env="prod"` 게이트 테스트가 아직 없다(`test_admin_is_404_outside_dev`는 `test`만 본다). `query:parse`의 `INVALID_QUERY`/`MISSING_USER`, non-strict 혼합 결과(일부 성공 + 일부 실패) 테스트도 없다.
- M1 테스트(`:237-263`)는 빈 저장소에서 provider 단계 실패만 본다. **커밋 단계 실패 롤백**(사용자 id 충돌 같은 SQL 단계 실패 후 DB·인덱스 불변), 기존 문서가 있을 때의 불변성, strict의 `EmbeddingProviderError` → `embedding_pending` 경로, 동시 읽기 중 원자적 게시는 이번 검수에서 직접만 확인했다.
- `--confirm-with` CLI 검증 경로 테스트가 없다(N1과 함께 추가).

**N5. 준비 실패 상태에서도 admin 쓰기를 받는다.** `src/jupjup/api/app.py:283-292`
- 재구축이 실패해 `ready=false`인데 bulkUpsert가 200이고 DB·인덱스에 쓴다. 인덱스는 일부만 채워진 채로 남고, 검색은 계속 503이다. dev 전용이고 명세가 admin을 언급하지 않아 영향은 작다. `require_ready()`를 admin에도 적용하거나 의도를 5.9절에 적는다.

**N6. DELETE 경로 OpenAPI가 실제 봉투와 다르다 (L1 잔여).** `src/jupjup/api/app.py:288`
- `DELETE /v1/admin/contents/{content_id}`는 422가 FastAPI 기본 `HTTPValidationError`이고, 실제로 내는 400(`MISSING_USER`/`INVALID_USER`)과 404(`NOT_FOUND`)가 문서에 없다. `responses=`에 `ErrorEnvelope`를 선언한다.

**N7. strict 커밋 실패 시 모든 항목에 같은 메시지를 붙인다.** `src/jupjup/api/app.py:185-194`
- bob 배치에서 alice id 하나가 충돌하면 bob 자신의 새 문서(`c_bob_rev9`)까지 "다른 사용자의 저장물 id입니다"로 보고된다. 원자성은 맞다. 다만 원인 항목이 어느 것인지 알 수 없다. `ContentValidationError.details["id"]`로 원인 항목을 구분하고, 나머지는 `BATCH_ABORTED`처럼 별도 code로 보고하면 클라이언트가 고칠 대상을 알 수 있다.

**L4 (이월). `filters.platforms: []` 의미 미정.** `src/jupjup/api/app.py:115-121`. 보고서가 공개했다. PM이 "필터 없음"과 `INVALID_FILTER` 중 하나로 정해 줘야 한다.

### 정보 (감점 없음)

- **I1.** 고정 회귀 범위가 넓어지면서 recorded A1이 test 오타 사례 `기휴변화 논문`(q_0038)에서도 1위를 `c_alice_0096` 밖으로 바꾸는 것이 드러났다(dev·test A/B 모두 규칙 1 상세에 나온다). 9.1절에 따라 PM 보고 대상이다. `known_issues.md`의 리랭커 항목이나 다음 리랭커 보고서에 cross 값과 원인을 적을 것.
- **I2.** strict bulkUpsert는 요청마다 해당 사용자의 BM25·벡터 인덱스 전체를 복사해 다시 만든다(`registry.py:109-124`). dev 전용이고 상한이 500건이라 지금은 문제가 없다. T23 인제스트가 이 경로를 쓰면 사용자 문서 수에 비례하는 비용을 측정할 것.
- **I3.** recorded 모드 미녹화 질의 500, `Settings.env` 기본값 `dev`, `X-User-Id`는 인증이 아님. 모두 직전 검수와 같다.
- **I4.** `resolve_rerank_dtype`는 장치를 알 수 없고 dtype이 `auto`일 때 녹화 메타에 이전처럼 `auto`가 아니라 `fp32`를 쓴다. bge 적재 동작은 같다.

## 4. 채점 근거

| 항목 | 점수 | 감점 근거 |
|---|---:|---|
| 정확성 | 37.5 / 40 | N1 −1 (규칙 7이 다른 설정의 test 결과를 받아들임, 재현), N3 −0.5 (CLI 회귀, 재현), N6 −0.5, L4 −0.5 (이월) |
| 안전성 | 28.5 / 30 | N2 −1 (전역 읽기 직렬화, 4.7절 busy 의미 변화), N5 −0.5 |
| 유지보수성 | 28 / 30 | N4 −1.5 (커밋 단계·prod 게이트·CLI 확인 경로 테스트 공백), N2·N7의 쓰기 경로 두 갈래(copy-on-write와 제자리 수정)와 오류 귀속 −0.5 |
| **합계** | **94 / 100** | **PASS** |

잘한 점: 제공자 작업(임베딩)과 상태 변경(SQLite·인덱스)을 `prepare_bundle`/`commit_prepared`로 분리했다. 덕분에 원자성 결함이 구조적으로 사라졌다. 재구축 경로(`index_bundle` = prepare + apply)도 같은 코드를 써서 재업서트 전후 결과가 바이트 단위로 같다. 고정 회귀를 split과 무관하게 all-split으로 돌리고 기대 개수를 판정 입력에 넣어, 조용한 생략이 다시 생길 수 없게 했다. 금지 범위(순위·기본값·기준선·녹화본)를 지켰고, 보고서 수치가 모두 재현된다.

## 5. 다음 단계 권고

PASS이므로 이 보강 루프를 끝낸다.

1. 리랭커 채택 재평가 전에 N1(설정 일치 검사)과 그 CLI 테스트를 처리한다.
2. T23(인제스트 API)이 같은 쓰기 경로를 확장하므로, 그 전에 N2(non-strict·DELETE도 copy-on-write로 바꾸고 읽기 잠금 제거)와 N4 테스트를 묶어 Phase 2 소규모 작업으로 처리한다. N3·N5·N6·N7은 함께 처리하면 작다.
3. PM 결정 필요: L4(`platforms: []` 의미), I1(A1의 q_0038 1위 변화 보고).

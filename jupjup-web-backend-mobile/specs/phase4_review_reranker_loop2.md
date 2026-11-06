# Phase 4 최종 검수 — 리랭커 사이클, Loop 2/3

- **점수:** 93 / 100
- **상태:** PASS
- **항목별:** 정확성 38 / 40, 안전성 28 / 30, 유지보수성 27 / 30
- **루프백 대상:** 없음 (PASS). 아래 중간 항목 S1~S3은 리랭커 채택 재평가 전에 Phase 2 소규모 작업으로 처리할 것을 권한다.
- **검수 대상:** `phase-4-review-reranker-loop2` HEAD `9355431` (Loop 2 수정 커밋, 직전 검수 `c2aacc7`, 기준 `c7da005`)
- **채점 기준(PM 정책):** 순위 품질은 recorded(bge-m3 녹화 재생)로 판정한다. mock은 안전 지표, 절대 기준, 결정성 확인용이다. 사람 검수 0건과 리랭커 채택 REJECT 자체는 감점하지 않았다. 범위 밖: T15 정식 API, LLM 연동, 인제스트. 엄격도는 Loop 1 검수와 같다.

## 0. 요약

- **Loop 1 REJECT 사유(R1)가 해소됐다.** extra 없는 기본 설치(`torch`, `sentence_transformers` 없음을 직접 확인)에서 `pytest` 611 passed, `mypy src` Success, `ruff` PASS다. 인수 기준 3·12 충족.
- **R2(판정 함수) 대부분 해결.** 고정 회귀가 규칙 1에 들어갔고, recorded dev A1의 규칙 1 상세에 `다리 운동 영상(c_alice_0051)`이 나온다. 지표·카테고리·false empty·test 확인이 빠지면 fail-closed다. 다만 고정 회귀 범위가 9.1절보다 좁고(S2), test split에서는 규칙 1이 구조적으로 통과할 수 없다(S3).
- **M1~M5, L1·L2·L6 조치 확인.** 다만 M1 수정이 새 결함을 만들었다: extra가 없으면 `select_device("auto")`가 `cpu`를 돌려줘 `required=true`인데도 경고 없이 리랭커 없이 시작한다(S1, 설계 4.7절 위반). 기본값(`enabled=false`, `required=false`)에서는 영향이 없다.
- **기본 경로 무회귀.** eval 4종 PASS이고 수치가 Loop 1과 같다. `c2aacc7..HEAD`에서 `data/` 변경 없음. CLI 45개 사례의 A0(mock·recorded)와 A1(recorded) 결과가 Loop 1 검수 1.3절과 모두 같다.
- **A/B는 결정적이고 판정은 REJECT 유지.** 두 번 실행한 리포트가 `cmp` 동일하다. 리랭커 기본값은 꺼져 있다.
- 남은 결함은 모두 채택 재평가 경로나 기본값이 아닌 설정에 있다. 명시된 인수 기준의 객관적 실패는 없어 PASS로 판정한다.

## 1. 직접 실행한 명령과 결과

### 1.1 정적 검사, 테스트, 평가 (이 워크트리 `.venv`, `uv sync` 기본 설치)

| 명령 | 결과 |
|---|---|
| `uv run python -c "find_spec('torch'), find_spec('sentence_transformers')"` | 둘 다 `None` (기본 설치 확인) |
| `uv run ruff check src tests` | All checks passed |
| `uv run mypy src` | Success: no issues found in 56 source files |
| `uv run pytest -o addopts="" -m "not embed and not rerank"` | **611 passed, 3 deselected** (경고 1건: Starlette `httpx` 비권장, 보고서 4.5와 같다) |
| `uv run jupjup eval validate` | PASS. seeds 200, queries 259, review_status ai_draft_unreviewed 235 / needs_human_review 24 |
| `eval run --mode mock --split dev --baseline data/baselines/mock.json` | PASS — R@10 0.9620, nDCG 0.9795, cat-min 0.8838, TE 1.0, FE 0.0 |
| `eval run --mode mock --split test …` | PASS — R@10 0.9420, nDCG 0.9589, cat-min 0.7812, TE 1.0, FE 0.012 |
| `eval run --mode recorded --split dev --baseline data/baselines/recorded.json` | PASS — R@10 0.9712, nDCG 0.9860, cat-min 0.8894, TE 1.0, FE 0.0 |
| `eval run --mode recorded --split test …` | PASS — R@10 0.9720 (회귀 하한 0.972, 여유 0 그대로), nDCG 0.9801, cat-min 0.8900 |
| `git diff --stat c2aacc7 HEAD -- data/` | 변경 없음 (`c7da005` 대비 변경은 Loop 1의 리랭커 녹화본·README뿐) |
| `jupjup eval ab --mode recorded --split dev --arms A0,A1` × 2회 | 두 리포트 `cmp` 동일. Recall −0.0315 [−0.0651, −0.0063], MRR −0.0252, nDCG −0.0266 [−0.0602, −0.0014], FE +0.0168. 규칙 1~7 전부 FAIL, **REJECT**. 규칙 1 상세 `fixed_regressions=7 failed=['다리 운동 영상(c_alice_0051)']` |
| (진단) `eval ab --mode recorded --split test --arms A0,A1` | 규칙 1 `metrics_complete=False` (`challenge_negative_true_empty` 없음), `fixed_regressions=5`. S3 근거. **튜닝·설정 변경에 쓰지 않았고 판정 근거도 아니다.** 기존 test는 이미 blind가 아니다(설계 8.4-5) |
| (진단) `eval ab --mode mock --split dev --arms A0,A1` | 정상 종료, REJECT. mock A1에서 `ch_0003` empty (4.12절상 mock 리랭커는 배선용, 감점 없음) |

### 1.2 컨테이너 조립 직접 실행 (S1 근거)

기본 설치(torch 없음), `mode=live`, `cross_rerank.enabled=true`:

| 설정 | 결과 | 설계 4.7절 기대 |
|---|---|---|
| `required=true`, `device=auto`, `enabled_on_cpu=false`(기본) | `(None, 'cpu_disabled')`, 예외·경고 없음 | `RerankerUnavailable`로 시작 실패 |
| `required=true`, `enabled_on_cpu=true` | `RerankerUnavailable: rerank extra를 설치하세요` | 같음 ✅ |

### 1.3 CLI (`seed load --db var/review.db`, recorded는 `JUPJUP_MODE=recorded`로 `var/review_rec.db`. 검색은 `--now 2026-10-15T12:00+09:00 --json`, A1은 `JUPJUP_SEARCH__CROSS_RERANK__ENABLED=true`)

45개 사례를 A0 mock, A0 recorded, A1 recorded로 돌렸다. **전부 Loop 1 검수 1.3절과 같은 결과다.** 새로 확인한 점은 A1의 모든 정상 응답이 `degraded=false`라는 것(M2 수정 확인)이다.

| 분류 | 사례 | A0 (mock / recorded) | A1 recorded |
|---|---|---|---|
| 회귀 | S7 `지난주 카톡으로 받은 회의 장소` | `0136`,`0146` + `time_window_expanded` ✅ | 같음 ✅ |
| 회귀 | `레스토랑 추천 블로그` | `0153` ✅ | 같음 ✅ |
| 회귀 | `다리 운동 영상` | `0040` 1위 ✅ | `0051`만 (9.1 위반, 미채택 사유로 공개됨) |
| 회귀 | `경주 맛집 인스타` / `하체 운동 유튜브` / `경주 맛집 카톡 논문` | 1위·완화 기록 일치 ✅ | 같음 ✅ |
| 회귀 | `지지난주 성수 카페 약속` | `0140`,`0031` + `time_window_expanded` ✅ | 같음 ✅ |
| 회귀 | `mars migration documentary 저장한 거` | empty ✅ | empty ✅ |
| 순위 / 꼬리 | `환경 다큐`, `그 영화 예매했던 거`, `주식 공부 영상` | `0047` / `0147`,`0053` / mock `0063`,`0052`·rec `0052` 1위 ✅ | `0047` / `0147` / `0052` |
| negative | `낚시 포인트 추천`, `북극곰 다큐`, `미얀마 여행 일정`, `보드게임 추천`, `수제 맥주 양조법` | 모두 empty ✅ | 모두 empty ✅ |
| 교차 언어 | `coffee cardiovascular health paper`, `retrieval augmented generation survey paper` | rec `0112`, `0100` ✅ (mock empty) | 같음 ✅ |
| 동의어 | `스파게티 만드는 법` | `0041`… ✅ | empty (공개된 A1 손실) |
| 과잉 완화 | `경주 맛집 인스타 --platform instagram`, `경주 맛집 --type post` | empty, 완화 없음 ✅ | 같음 ✅ |
| 과잉 완화 / 요청 잠금 | `하체 운동 유튜브 --platform youtube` / `회의 장소 --from 10-05 --to 10-12` | `0050`,`0051` / empty ✅ | `[RERANK_CACHE_MISS]` (녹화 범위 밖, L4 이관 그대로) |
| 정상 완화 | `지난달 하체 운동` / `지난달 경주 맛집` | expanded / dropped ✅ | 같음 ✅ |
| 과소 완화 | `지난달 인스타에서 본 성수동 카페` | `0001` 1위, 완화 없음 ✅ | 같음 ✅ |
| 오타 | `어버이날 선물 추쳔`, `기휴변화 논문`, `성수동까페`, `떡복이 맛집` | 교정·관련 결과 ✅ (mock `떡복이` empty는 기존과 같음) | 같음 ✅ |
| 특수문자 | `카페'; DROP TABLE contents;--` | mock empty, DB 200건 정상 ✅ / rec `[EMBEDDING_CACHE_MISS]` (이전과 같음) | 같음 |
| 특수문자·경계값 | `!!!@@@###`, 빈 문자열, 공백, `가`×201 | `[INVALID_QUERY]` ✅ | 같음 ✅ |
| 입력 검증 | `--platform tiktokx`, naive `--from`, `--limit 51` | `[INVALID_FILTER]` / 범위 오류, traceback 0 ✅ | 같음 ✅ |
| 영어 혼합 | `IG에서 본 coffee shop dessert 그거` | 카페 문서 ✅ | `0036`,`0001`… ✅ |
| 필터 전용 | `지난달 인스타`, `유튜브 영상` | browse 최신순, `rerank_status=None` ✅ | 같음 ✅ |
| 격리 | bob `낚시 포인트 추천` / carol `경주 맛집` | `c_bob_*`만 / empty ✅ | `[RERANK_CACHE_MISS]` (L4) |
| 격리 | `u_alice' OR 1=1` / 없는 사용자 `u_zed` | `[INVALID_USER]` / 안내 + empty ✅ | 같음 ✅ |

## 2. 기준 문서 대조

### 2.1 Loop 1 재검수 조건

| # | 조건 | 판정 | 근거 |
|---:|---|---|---|
| 1 | (R1) 기본 설치 pytest·mypy·ruff 통과, torch 없이 출력 검증 테스트 | **충족** | 1.1절. `rerank_bge.py:33-35` 제네릭 항등 함수, `test_bge_requires_revision_and_validates_output` 통과 |
| 2 | (R2) 9.1 고정 회귀를 규칙 1에서 계산, 규칙 7·지표 누락 시 ADOPT 금지, 테스트 | **대부분 충족** | `ab.py:161-178, 282-326, 455-486, 558-564`. dev A1 규칙 1에 `다리 운동 영상` 표시. 범위 축소와 test split 문제는 S2·S3 |
| 3 | (M1·M2) warm-up `RerankerError` 처리, cpu 비활성 시 미적재, 정책 사유 비-degraded | **충족, 부작용 있음** | `container.py:98-108`, `service.py:301`. 테스트 3건 통과. 단 S1 |
| 4 | (M3) INV-R2 `now`·요청 잠금 축 | **충족** | `test_cross_and_relevance_ignore_now…`, `…request_locks…` 통과. `now` 축 질의가 시간 표현 없는 `성수동 카페`라 약하다(L4) |
| 5 | (M4·M5) A0 정의, 질의 단위 변화, F2 상태 | **충족** | `phase2_reranker_report.md:24, 47-54`, `known_issues.md:87-90`. 사실과 맞다(1.1, Loop 1 1.2와 대조) |
| 6 | 기본 경로 무회귀 | **충족** | 1.1·1.3절 |
| 7 | 기본값 끔·REJECT 유지, 재튜닝·test 재사용 없음 | **충족** | 설정 diff에 계수·floor 변경 없음. 새 설정 `anchored_tail_threshold`는 기존 값 0.44 그대로 |

### 2.2 설계 13절 인수 기준 (단계 1 해당분)

| # | 결과 |
|---:|---|
| 1 불변식 테스트 | 충족 (INV-R2 세 축 모두 있음) |
| 2 9.1절 고정 회귀 A0·A1 | A0 충족. A1 `다리 운동 영상` 실패는 미채택 사유로 공개 (감점 없음) |
| 3 기본 설치 pytest, torch import 없음 | **충족** |
| 4 recorded A/B 결정성 | 충족 |
| 5 녹화 원문 없음, 미스 실패 | 충족. 새 행에 `device`·`dtype` 메타 추가 |
| 6 실패·타임아웃·busy 시 v2와 동일 + degraded | 충족. 정책 skip은 degraded 아님 |
| 9 `decide_reranker` 10절 규칙 전부 계산 | 부분 — 규칙 7은 입력 bool만 받고 CLI는 넘길 방법이 없다. test split에서 규칙 1 구조적 FAIL (S3) |
| 10 튜닝 값 설정화 | 충족 (`relevance_v3.anchored_tail_threshold` 추가) |
| 11 test 이력 공개 | 충족 |
| 12 ruff, mypy | **충족** |

## 3. 피드백 (심각도 순, 줄 번호는 `9355431` 기준)

### 중간

**S1. `src/jupjup/container.py:98-100` — extra 미설치 시 `required=true`가 무시된다. 설계 4.7절 위반 (M1 수정의 부작용).**

- `select_device("auto")`는 torch import에 실패하면 `"cpu"`를 돌려준다(`rerank_bge.py:23-30`). 그래서 `enabled_on_cpu=false`(기본)면 모델 생성 전에 `(None, "cpu_disabled")`로 끝난다. `required=true`여도 예외가 없고, `required=false`여도 경고가 없다. 1.2절에서 재현했다.
- mps 장비(M5)에서 extra만 빠진 경우 상태가 `cpu_disabled`로 보여 원인(미설치)을 숨긴다.
- 테스트 `test_live_cpu_disabled_skips_model_load`는 `select_device`를 패치해 이 경로를 보지 않는다.
- **개선:** 사전 검사 전에 extra 존재를 확인한다(`importlib.util.find_spec("sentence_transformers")`). 없으면 기존처럼 `RerankerUnavailable` → `required`면 raise, 아니면 경고 후 `"unavailable"`. 또는 `select_device`가 torch 부재를 `"cpu"`가 아닌 별도 값으로 알린다. torch 없는 상태의 `required=true`/`false` 단위 테스트를 둔다.

**S2. `src/jupjup/eval/ab.py:161-178, 284-287, 463` — 고정 회귀 범위가 9.1절보다 좁고 빠진 항목을 조용히 넘긴다.**

- 9.1절은 "요청 잠금 사례, 오타 사례, browse"까지 포함한다. 현재 표는 6개 질의 id와 프로브 3개뿐이다.
- 질의 id가 현재 split에 없으면 `continue`한다. dev A/B에서는 S7(q_0083)과 `레스토랑 추천 블로그`(q_0173)가 test split이라 빠지고, 결과는 `fixed_regressions=7`이다. `fixed_ok`는 목록이 비어 있지만 않으면 통과다.
- 보고서는 "9.1절 고정 회귀를 규칙 1에서 계산한다"고만 써서 범위 축소를 밝히지 않았다.
- **개선:** split과 무관하게 9.1 사례 전부를 프로브로 돌린다(요청 잠금·오타·browse 포함). 기대 개수를 상수로 두고 실제 개수가 다르면 규칙 1을 FAIL로 한다. 요청 잠금 프로브는 리랭커 녹화 범위 밖이라 recorded A1에서 `RERANK_CACHE_MISS`가 나므로, Loop 1 L4(녹화 범위 보강)와 함께 처리한다.

**S3. `src/jupjup/eval/ab.py:455-470`, `src/jupjup/cli.py:541` — test split에서 규칙 1이 구조적으로 실패하고, 규칙 7을 계산할 경로가 없다.**

- challenge test에는 negative가 0건이다(dev 2건). 그래서 test A/B의 `candidate_absolute`에 `challenge_negative_true_empty`가 없고, fail-closed 처리로 `metrics_complete=False` → 규칙 1 FAIL이 된다(1.1절 진단). 어떤 설정도 test에서 규칙 1~4를 통과할 수 없다.
- 규칙 7은 호출자가 넘기는 bool인데 CLI(`cli.py:541`)는 넘기지 않는다. 결과적으로 이 도구로는 ADOPT가 나올 수 없다. 방향은 안전(false REJECT)하고 이번 판정에는 영향이 없지만, 인수 기준 9("10절 규칙을 모두 계산")와 채택 재평가 경로를 막는다.
- **개선:** "입력 누락"과 "부분집합 분모 0"을 구분한다. 분모 0이면 `n/a`로 표시하고 규칙에서 제외하되 상세에 적는다. test 리포트를 받아 1~4를 재계산해 규칙 7을 채우는 옵션(`--confirm-with <test_report>`)을 둔다. test split 비교 단위 테스트를 추가한다.

### 낮음

- **L1. `specs/phase2_reranker_loop2_report.md:62`** — "규칙 5~6은 PASS"라고 썼지만 실제 출력은 `5_latency`·`6_operations` 모두 FAIL(`live 벤치마크 없음`)이다(1.1절). 결론(REJECT)에는 영향이 없다.
- **L2. `specs/phase2_reranker_report.md:47-55`** — 2.2절이 2.1절 번호 목록(4번과 5번) 사이에 끼어 목록이 끊겼다. 같은 파일 `:25` T31 행은 여전히 `activation_fn=Identity`라고 쓴다.
- **L3. `src/jupjup/search/cross_rerank.py:170, 187`, `src/jupjup/providers/rerank.py:118`** — 장치 문자열에 상태값 `"cpu_disabled"`를 섞고, 재생 여부를 `getattr(..., "is_replay")` 덕 타이핑으로 판정한다. `Reranker` Protocol에 `is_replay`를 선언하고, 컨테이너가 넘기는 상태와 장치를 분리하는 편이 읽기 쉽다.
- **L4. `tests/unit/test_cross_rerank.py:507`** — INV-R2 `now` 축 테스트가 시간 표현 없는 `성수동 카페`라 `now` 변화가 후보·창을 거의 바꾸지 않는다. `지난주 …`처럼 기간 해석이 바뀌는 질의를 하나 더 두면 오라클이 강해진다.
- **L5. `src/jupjup/providers/rerank.py:75-81`** — dtype 결정 규칙이 `rerank_bge.py:55`의 `model.half()` 조건과 중복된다. 한쪽이 바뀌면 녹화 메타가 틀린다. 공용 함수로 뽑을 것.
- **L6. `src/jupjup/eval/ab.py:550`** — `rss_increase_mb is None`이면 규칙 6 메모리 조건이 통과한다. R2에서 다른 누락 입력은 fail-closed로 바꿨는데 이것만 남았다.
- **L7. `src/jupjup/eval/ab.py:309`** — 프로브 `now`·사용자를 하드코딩한다. 골든셋의 `now`와 같아 현재는 문제없지만 `EvalConfig`나 골든 항목에서 가져오는 편이 안전하다.
- **이관 유지(감점 없음):** Loop 1 L3(v3 + cross 무시 진단), L4(골든 밖 녹화 보강), L5(`다리` 사전 제거 진단)는 재튜닝 금지를 지키기 위해 재평가 전 과제로 남겼고 보고서 4절에 공개했다.

## 4. 채점 근거

| 항목 | 점수 | 감점 |
|---|---:|---|
| 정확성 | 38 / 40 | S2 고정 회귀 범위 축소와 조용한 생략 (−1), S3 test split 규칙 1 구조적 FAIL·규칙 7 경로 없음 (−0.5), L6 (−0.5). 기본 경로 무회귀, A/B 결정성, R2 핵심(다리 운동 영상 검출, fail-closed) 해결은 확인 |
| 안전성 | 28 / 30 | S1 extra 미설치 시 `required=true` 무시·경고 없음 (−2). 입력 검증, 격리, 요청 잠금, 녹화 미스 실패, 재생 경로 결정성(L1 해결)은 정상 |
| 유지보수성 | 27 / 30 | L1·L2 보고서 부정확 (−1), L3·L5 덕 타이핑·상태/장치 혼용·중복 규칙 (−1.5), L4·L7 테스트·프로브 강도 (−0.5). R1 해결로 기본 설치 검증이 회복됐고, 보고서가 기본·extra 결과를 나눠 적은 점은 반영 |
| **합계** | **93 / 100** | **PASS** |

## 5. 다음 단계 권고 (PASS이므로 필수 조건 아님)

1. 리랭커 채택 재평가(dev v2 마련) 전에 S1~S3을 Phase 2 소규모 작업으로 처리한다. S1은 운영 설정(`required=true`)을 쓰기 전에 반드시 고친다.
2. 재평가 때 9.1절 요청 잠금·격리 사례를 리랭커 녹화 범위에 넣어(Loop 1 L4) S2의 프로브 확장과 CLI A1 확인을 함께 가능하게 한다.
3. 리랭커 기본값 끔과 A/B REJECT 결론은 그대로 유지한다.

# Phase 4 최종 검수 — 완화 정책 v2 사이클, Loop 3/3

- **점수:** 90 / 100
- **상태:** PASS
- **항목별:** 정확성 36 / 40, 안전성 29 / 30, 유지보수성 25 / 30
- **루프백 대상:** 없음 (PASS). 아래 F1~F6은 다음 사이클(리랭커·query assist, `specs/design_reranker_query_assist.md`) 착수 전에 known_issues로 넘길 후속 과제다.
- **검수 대상:** `phase-4-review-cycle2-loop3` HEAD `d0a7f27` (PM 병합 커밋, 구현 `08fdc68`)
- **채점 기준(PM 정책):** 순위 품질은 recorded(bge-m3 녹화 재생)로 판정한다. mock은 안전 지표, 절대 기준, 결정성 확인용이다. 사람 검수 0건은 감점하지 않았다. 범위 밖: T15 정식 API, LLM 연동, 인제스트.
- **판정의 의미:** 기술 게이트 PASS다. 현재 test split은 여러 루프에서 열람됐으므로 blind가 아니다. 제품 품질 PASS는 동결 test v2와 사람 검수 뒤에 판단한다 (구현 보고서 6절과 같은 입장).

## 0. 요약

직전 검수의 높음 결함 두 개(N1 low-signal 도달 불가, N2 semantic-only 오탐)와 중간 결함 N3·N5, 낮음 L1을 모두 직접 재현해 해소를 확인했다.

- recorded dev/test의 절대 기준과 기존 기준선 회귀 게이트가 모두 PASS다. recorded 기준선 파일은 바뀌지 않았다.
- recorded challenge positive 합산 R@10은 **0.9394**로 인수 기준 0.9091을 넘는다. negative ch_0011/12는 empty다.
- recorded test true-empty가 0.9에서 1.0으로 돌아왔다 (`낚시 포인트 추천` empty).
- pytest 554 passed, ruff·mypy·validate PASS, recorded 재생은 결정적이다.

남은 문제는 모두 중간 이하다. 가장 중요한 것은 이번 루프에 새로 들어온 anchored tail 규칙의 **비단조성**(F1)이다. 앵커보다 R이 높은 lexical-only 후보는 버리고 낮은 후보만 받아 준다. mock dev의 grade 3 정답 하나가 이 때문에 사라졌고, mock 기준선 재설정으로 가려졌다. recorded 골든셋에서는 발생하지 않는다. N2 수정이 floor 0.60→0.61 한 칸이고, dev로는 0.59~0.61을 구분할 수 없다는 점(F2)도 기록한다.

## 1. 직접 실행한 명령과 결과

### 1.1 정적 검사, 테스트, 평가

| 명령 | 결과 |
|---|---|
| `uv run ruff check .` | PASS |
| `uv run mypy src` | PASS (52 source files) |
| `uv run pytest -rA` | **PASS — 554 passed, 1 deselected**(embed marker). Starlette deprecation warning 1건 (범위 밖) |
| `uv run jupjup eval validate` | PASS — seeds 200, queries 259 (dev 158 / test 101), lexicon 139, reviewed 0 |
| `eval run --mode recorded --split dev --baseline data/baselines/recorded.json` | **PASS** — R@10 0.9712, R@5 0.9453, MRR 1.0, nDCG 0.9858, cat-min 0.8894, TE 1.000, FE 0.000, 격리·필터 위반 0 |
| `eval run --mode recorded --split test --baseline …` | **PASS** — R@10 0.9720(회귀 하한 0.972와 같음, 여유 0), MRR 0.9911, nDCG 0.9801, cat-min 0.89, TE 1.000, FE 0.000 |
| `eval run --mode mock --split dev --baseline data/baselines/mock.json` | PASS — R@10 0.9536, TE 1.000, FE 0.000 (v2 재설정 기준선) |
| `eval run --mode mock --split test --baseline …` | PASS — R@10 0.9420, TE 1.000, FE 0.012, 위반 0 |
| recorded dev·test 각 2회 실행 후 `results`·`overall` 비교 | 둘 다 동일 (INV-20 OK) |
| challenge 집계 (recorded) | positive R@10 합산 **0.9394 (22건)**. ch_0003 0.67, ch_0007 0.5, ch_0021 0.5, 나머지 1.0. ch_0011/12 empty |
| challenge 집계 (mock, 참고) | 0.6818 |
| `git diff 98878f1 HEAD -- data/baselines/recorded.json` | 변경 없음 |

### 1.2 진단 (코드는 바꾸지 않음. scratchpad 사본과 monkeypatch 스크립트에서만 실행)

| 진단 | 결과 |
|---|---|
| `git archive 98878f1`(Loop 2b) 코드로 4개 평가 후 질의별 비교 | recorded dev: **질의 단위 변화 0**. recorded test: q_0180 MRR 0.2→1.0, q_0182 R@10 0.8→0.9, q_0207 오탐→empty, ch_0017·ch_0023 0→1.0. 악화 0. mock dev: **q_0176 `주식 공부 영상` R@10 1.0→0.0**, q_0061 0.7→0.6. mock test: q_0180 0→1.0 |
| q_0176 후보별 evidence 덤프 (mock, 두 버전) | 정답 `c_alice_0052` R 0.565 lexical-only. 1위 `c_alice_0063`(corroborated) R 0.515. Loop 3에서는 standalone 문턱 0.58 미달로 거부된다. anchored tail 조건 `utility ≤ top_utility`에도 걸려(0.565 > 0.515) 꼬리로도 복구되지 않는다 → F1 |
| 전체 골든셋(dev+test+challenge)에서 "lexical-only, below_threshold, R ≥ 0.44, 앵커보다 utility가 높아서 탈락" 스캔 | mock: q_0176 1건(grade 3). recorded: 순위 질의 0건 (filter-only q_0232/q_0235의 비관련 문서 2건만) |
| recorded `--overrides` semantic floor 0.59 / 0.60 / 0.61 (진단 전용) | dev 지표 세 값 모두 **완전히 같다** (R@10 0.9712, TE 1.0, FE 0). test는 0.59·0.60에서 q_0207 → `c_alice_0021` 오탐, TE 0.9 → F2 |
| recorded `낚시 포인트 추천 --explain --json` | strict 계획: 후보 50, eligible 0, `no_evidence` 49, `semantic_floor` 1(`c_alice_0021`, calibrated 0.606 vs floor 0.61), reason `all_candidates_rejected` (L1 충족) |
| `SearchSettings.model_validate`에 Loop 2 설정(low-signal 0.58, floor 0.60) 투입 | **검증 통과** — 새 도달 가능성 validator가 Loop 2의 N1 결함 설정을 거부하지 못한다 → F3 |
| 임베딩 장애 주입(`embed`가 `EmbeddingProviderError`, 두 mode) | 고정 negative 11종(낚시·보드게임·미얀마·북극곰·수제 맥주·mars·화성·테니스·브루클린·사파리 등) 모두 empty. `토마토 파스타`→0041, S7→0136/0146 `time_window_expanded`, `다리 운동 영상`→0040. 모두 `accepted_as_degraded_lexical_fallback` |

### 1.3 CLI (`seed load --db var/review.db`; 검색은 `--user u_alice --db var/review.db --now 2026-10-15T12:00+09:00`)

mock DB는 `var/review.db`, recorded는 `JUPJUP_MODE=recorded`로 `var/review_rec.db`에 따로 적재했다 (각 200건, 임베딩 대기 0).

| 분류 | 사례 | 결과 |
|---|---|---|
| 회귀 | S7 `지난주 카톡으로 받은 회의 장소` (두 mode) | `0136` 1위, `time_window_expanded`만, 2위 `0146` ✅ |
| 회귀 | `레스토랑 추천 블로그` (두 mode) | `0153`만, 완화 없음 ✅ |
| 회귀 | `다리 운동 영상` (두 mode) | `0040` 1위, keywords `[다리, 하체, 운동]` — 원형 보존 ✅ (N5) |
| 회귀 | `경주 맛집 인스타` / `하체 운동 유튜브` / `경주 맛집 카톡 논문` | platform / platform / platform+content_type, 1위 `relaxed_facets` 일치 ✅ |
| 회귀 | `지지난주 성수 카페 약속` (두 mode) | `0140` 1위 `time_window_expanded`, 2위 `0031` 완화 없음 ✅ |
| 회귀 | `mars migration documentary 저장한 거`, `화성 이주 계획 다큐` | empty ✅ |
| 순위 | `환경 다큐` (두 mode) | `0047` "기후위기 다큐멘터리" 1위 ✅ (N3). recorded 2~4위는 기후변화·미세플라스틱 문서 |
| 꼬리 | `그 영화 예매했던 거` (두 mode) | `0147` 1위, `0053` 2위 ✅ |
| 꼬리 | `주식 공부 영상` | recorded `0052` 1위 ✅. **mock은 `0063` "영어 회화 패턴 50" 1건뿐, 정답 `0052` 미반환 ❌** (F1) |
| negative (두 mode) | `낚시 포인트 추천`, `북극곰 다큐`, `미얀마 여행 일정`, `보드게임 추천`, `수제 맥주 양조법` | 모두 empty ✅ (N2) |
| 교차 언어 (recorded) | `coffee cardiovascular health paper`, `retrieval augmented generation survey paper` | `0112`, `0100` 1위 ✅ (N1). mock은 empty (안전한 empty) |
| 교차 언어 | `IG에서 본 coffee shop dessert 그거`, `home workout 10min youtube`(recorded) | 카페 문서 / `0050` ✅ |
| 과잉 완화 | `경주 맛집 인스타 --platform instagram`, `경주 맛집 --type post` | empty, 완화 없음 ✅ |
| 과잉 완화 | `하체 운동 유튜브 --platform youtube` | youtube만 (`0050`, `0051`) ✅ |
| 요청 잠금 | `회의 장소 --from 10-05 --to 10-12`, S7 + `--platform kakaotalk` + 같은 기간 | empty ✅ |
| 정상 완화 | `지난달 하체 운동` / `지난달 경주 맛집` / `경주 맛집 카톡` | expanded / dropped / platform ✅ |
| 과소 완화 | `지난달 인스타에서 본 성수동 카페` | `0001` 1위, 완화 없음 ✅ |
| 오타 | `어버이날 선물 추쳔`, `기휴변화 논문`, `성수동까페`, `유툽에서 본 파스타`, `트랜치코트 코디` (두 mode) | 교정 및 관련 결과 ✅ |
| 오타 | `떡복이 맛집` | recorded `0019` ✅, mock empty (L2 그대로, mock FE 0.012) |
| 오타 | `카톡으로 받은 회이 장소` | `회이` 미교정, keywords `[회, 장소]`. 관련 문서는 반환되지만 1위가 mode마다 다름 (이전 루프와 동일, 참고) |
| 특수문자 | `#카페 @성수!!` (mock) | normalized `카페 성수`, `#카페` 교정 기록 없음 ✅ (L4). recorded는 녹화본에 없는 텍스트라 `[EMBEDDING_CACHE_MISS]` — Loop 2b 코드에서도 같음, 재생 모드의 정상 동작 |
| 특수문자 | `카페'; DROP TABLE contents;--` (mock) | empty, DB 정상 (이후 질의 정상) ✅ |
| browse / 필터 전용 | `지난달 인스타`, `유튜브 영상` | browse 최신순 ✅ |
| 경계값 | 빈 문자열, 공백, `!!!@@@###`, `가`×200, `가`×201, `성수동 카페` 반복 199자 | 모두 `[INVALID_QUERY]` ✅ |
| 경계값 | 잘못된 플랫폼·유형, naive `--from`, 역전 기간 | `[INVALID_FILTER]` ✅ |
| 경계값 | `--limit 0`, `--limit 51` | CLI 범위 오류, traceback 없음 ✅ |
| 격리 | bob `낚시 포인트 추천` (두 mode) | `c_bob_*`만 ✅ |
| 격리 | carol `경주 맛집`, bob `경주 맛집 인스타` | empty ✅ |
| 격리 | `u_alice' OR 1=1` | `[INVALID_USER]` ✅ |
| 격리 | 없는 사용자 `u_zed` | empty + 안내 ✅ |

## 2. 기준 문서 대조

### 2.1 직전 검수(`phase4_review_cycle2_loop2.md`) 재검수 조건 판정

| 조건 | 판정 | 근거 (직접 확인) |
|---|---|---|
| **1 (N1)** low-signal 도달 가능, 교차 언어 positive 반환, ch_0011/12 empty, challenge ≥ 0.9091 | **충족** (보조 장치는 약함) | low-signal 문턱 0.45. recorded ch_0017→`0112`, ch_0023→`0100`, ch_0011/12 empty. challenge 합산 0.9394. recorded dev는 질의 단위로 변화가 없다. 문턱 0.45는 semantic-only와 같은 공통 하한이라 구조적 근거가 있다. 다만 설정 불변식 validator는 sem=1.0 이론 상한만 보므로 Loop 2 결함 설정(0.58)도 통과시킨다 (F3). 고정 테스트도 test 질의 ch_0017/23을 직접 쓴다 (F4). |
| **2 (N2)** recorded `낚시 포인트 추천` empty, 고정 negative recorded 테스트, dev TE ≥ 0.80·FE ≤ 0.03 | **충족** (견고성은 낮음) | CLI와 `test_recorded_fixed_negatives_stay_empty`(recorded 컨테이너, limit 50) 모두 empty. dev TE 1.0, FE 0. 그러나 해결 수단은 bge floor 0.60→0.61이고, q_0207 후보의 calibrated 0.606과 차이는 0.004뿐이다. dev는 0.59~0.61에서 구분되지 않는다 (F2). |
| **3 (N3)** 범용어를 R에서 지우지 않음, `환경 다큐`형 dev 사례에서 의미 강한 정답 우선 | **충족** (dev 사례는 미추가) | `_informative_terms` 삭제, `_weighted_original_coverage`로 가중치 0.25만 준다. `다큐/다큐멘터리`는 약한 목록에서 뺐다. 두 mode에서 `환경 다큐` → `0047` 1위. 다만 고정 테스트는 test 질의 q_0180 원문이다. 조건이 요구한 "dev 사례"는 추가하지 않았다 (F4). |
| **4 (N5)** 단방향 확장이 원형 보존, `다리` 사전 의존을 known_issues에 기록 | **충족** | `spell.py:60` `out.extend((term, expanded))`. keywords `[다리, 하체, 운동]`. known_issues 4번에 "사전 제거 시 mock `0050`, recorded `0051` 1위"를 사실대로 적었다. |
| **5 (L1)** empty explain에 계획별 후보 수·거부 사유 | **충족** | strict 포함 모든 계획에 `retrieved_candidate_count`, `candidate_count`, `eligible_count`, 상위 3개 `gate_rejections`가 나온다. `no_retrieval_candidate`와 `all_candidates_rejected`를 구분한다. 단위 테스트 `test_relevance.py:143-145`. |
| **6** PM·사용자 결정 기록 (recorded 기준선, 동결 test v2, mock 회귀 처리) | **부분 충족** | (a) recorded 기준선은 유지됐고 기존 게이트로 판정해 PASS. (b) `data/golden/test_v2/` 초안(빈 질의, freeze manifest `status: draft`)과 `design_reranker_query_assist.md` Q-RA1의 PM 추천 기본값이 있다. (c) mock 재설정은 `data/baselines/README.md`에 전후 수치와 함께 기록됐고, 이번 검수 지시의 PM 정책과 일치한다. 다만 결정 기록을 구현자가 "PM 확정 정책에 따라"로 적었고, PM이 쓴 결정 기록은 따로 없다. 재설정 문서에는 질의 단위 악화(q_0176)도 빠졌다 (F5). 정책상 감점은 F5의 보고 누락분만 했다. |
| **7** 전체 재실행 보고 | **충족** | 1.1절의 모든 명령을 직접 재실행했고 보고서 수치와 일치했다. |

### 2.2 설계 11절 불변식 / 12절 고정 회귀

- INV-01~20 테스트는 전체 pytest에서 통과한다. CLI로도 INV-01(요청 잠금), INV-03(같은 1위), INV-07/08(이중 기록), INV-10(`다리` 원형), INV-20(결정성)을 다시 확인했다.
- 12절 8개 사례는 두 mode에서 기대 1위와 기대 완화를 모두 만족한다 (1.3절).
- 불변식 표에는 없지만, "같은 계획 안에서 R이 더 높은 후보가 더 낮은 후보보다 먼저 탈락하지 않는다"는 단조성이 anchored tail 도입으로 깨졌다 (F1). INV-05의 취지("강한 후보는 밀려나지 않는다")와도 어긋난다.

### 2.3 15절 인수 기준

| # | 결과 |
|---:|---|
| 1 불변식 자동 테스트 | 충족 |
| 2 12절 고정 회귀 | 충족 (`다리`는 사전 의존, known_issues 4번에 기록) |
| 3 요청 잠금·격리 위반 0 | 충족 (평가, CLI, 장애 주입 모두) |
| 4 `R` 문맥 독립 | 충족 |
| 5 recorded dev TE ≥ 0.80 / challenge | **충족** — TE 1.0, challenge positive 0.9394 ≥ 0.9091 |
| 6 recorded 절대/회귀 기준 | **충족** — test R@10 0.9720 = 하한 0.972 (여유 0) |
| 7 test 동결 | 미충족이지만 보고서가 blind 아님을 명시했고, 제품 PASS를 선언하지 않았다. 동결 test v2 초안을 준비했다. |
| 8 human evidence eligible=false | 충족 |
| 9 응답 기록과 실제 위반 일치 | 충족 |
| 10 계수·탐색 기록 | 충족 (보고서 3절). 단, floor 0.61 선택의 dev 근거는 구간 [0.557, 0.622] 안의 임의값이다 (F2) |

### 2.4 known_issues

1~4번 상태는 정확하다. **5번은 갱신되지 않았다.** 아직 "recorded test Recall@10 0.9707 < 0.9720, 전체 pytest의 mock 회귀 게이트 2건 실패"라고 적혀 있지만, 지금은 둘 다 사실이 아니다 (F5).

## 3. 피드백 (심각도 순, 줄 번호는 `d0a7f27` 기준)

### 중간

**F1. `src/jupjup/search/service.py:486-499` — anchored tail이 비단조다. 앵커보다 R이 높은 lexical-only 후보는 버리고, 낮은 후보만 꼬리로 받는다.**

- 꼬리 조건은 `_is_anchored_tail`(R ≥ 0.44)과 `self._utility(candidate) <= top_utility`(496줄)다. 이 둘 때문에 R이 [0.44, 앵커 utility]인 lexical-only 후보는 반환되고, [앵커 utility, 0.58) 구간의 후보는 standalone 문턱(0.58)과 꼬리 조건에 모두 걸려 탈락한다.
- 재현: mock dev q_0176 `주식 공부 영상`. 정답 `c_alice_0052`(grade 3, R 0.565)가 사라지고, 무관한 `c_alice_0063` "영어 회화 패턴 50"(R 0.515)만 남는다. Loop 2b에서는 정답이 1위였다.
- recorded 골든셋에서는 이 패턴이 0건이라 recorded 판정에는 영향이 없다. 하지만 mode와 무관한 로직 결함이다. 리랭커 도입으로 점수 분포가 바뀌면 recorded에서도 나타날 수 있다.
- `utility ≤ top` 조건의 목적은 "꼬리는 1위가 되지 않는다"이다. 그렇다면 후보를 버릴 것이 아니라 순위를 앵커 뒤로 제한해야 한다.

**개선:**
- 꼬리 후보는 utility와 상관없이 받아들이되, 정렬에서 앵커(primary) 뒤로 보낸다. 예를 들면 정렬 키 앞에 `is_tail` 플래그를 둔다.
- "같은 계획에서 R이 더 높은 lexical-only 후보가 더 낮은 후보보다 먼저 탈락하지 않는다"를 단위 테스트로 고정한다.
- q_0176을 mock 통합 회귀에 추가한다.

**F2. `src/jupjup/config.py:177` — N2 수정이 floor 한 칸(0.60→0.61)이고, dev로는 이 값을 고를 근거가 없다. 판정 여유도 0.004뿐이다.**

- 직접 측정 결과, recorded dev 지표는 floor 0.59, 0.60, 0.61에서 **완전히 같다**. 세 값을 가르는 것은 직전 검수가 지목한 test 질의 q_0207 하나다 (`c_alice_0021` calibrated 0.606).
- 보고서의 dev 근거 구간 [negative 최대 0.557, positive 하단 0.622]은 맞다. 그러나 그 안에서 0.61을 고른 이유는 dev로 설명되지 않는다. "test로 문턱을 고르지 않았다"는 주장은 검증할 수 없고, 결과는 test 사례를 겨냥한 값과 같다.
- semantic-only 판정은 여전히 raw cosine 하나에 걸려 있고, 양쪽 여유는 0.004(negative)와 0.012(positive)다. 직전 검수가 제안한 질의 단위 근거나 상대 margin은 도입되지 않았다.
- 이번 PASS의 감점 근거는 견고성이다. 조건의 문언은 충족했다.

**개선:** 다음 사이클 설계(Q-RA2, cross-encoder floor)에서 semantic-only의 결정 근거를 floor 하나에서 옮긴다. 그 전까지는 dev에 semantic-only negative를 보강해 floor의 근거를 dev 안에서 만든다.

**F3. `src/jupjup/config.py:205-243`, `tests/unit/test_relevance.py:230-238` — 도달 가능성 validator가 원래 결함(N1)을 잡지 못한다.**

- semantic-only 상한은 sem = 1.0일 때 σ(−1.05 + 1.40) = 0.587로 계산된다. Loop 2의 low-signal 0.58은 이보다 낮으므로 validator를 통과한다. Loop 2 설정을 직접 넣어 확인했다.
- N1의 본질은 "이론상 도달 가능하지만 실제 cosine으로는 불가능"이었다. 직전 검수의 표현("최대치로 도달 가능")을 문언대로 구현한 것이라 조건 위반으로 보지는 않는다. 다만 이 회귀 방지 장치로는 같은 사고를 막지 못한다.
- lexical-only 상한은 canonical, purpose, corroboration 항을 빼고 계산한다. 그래서 실제로 도달 가능한 설정을 거부할 수 있다 (보수 쪽 오차).

**개선:** 상한 대신 "각 프로필의 문턱이 model별 semantic floor에서 필요한 sem ≤ calibration 실측 상위 분위(예: recorded dev positive p90)"처럼 실측 분포 기준의 검사를 추가한다. 최소한 low-signal과 semantic-only 문턱이 floor 지점의 R과 일치하는지 검사한다 (현재 0.45 ↔ floor 0.61의 R 0.452).

### 낮음

**F4. `tests/eval/test_recorded_regression.py:45-58`, `:82-88` — N1·N3 고정 테스트가 test split 질의 원문(ch_0017, ch_0023, q_0180)을 쓴다.**

재검수 조건 1·3은 dev 근거와 "`환경 다큐`형 dev 사례"를 요구했다. test 질의를 회귀 테스트에 고정하면 test 오염이 영구화된다. 동결 test v2를 만들 때 이 세 질의를 test v2에서 제외하거나, 같은 유형의 dev 질의로 바꾼다.

**F5. `data/baselines/README.md:15-41`, `specs/known_issues.md:66-78`, `specs/phase2_cycle2_loop3_report.md` 4절 — 보고 누락과 오래된 문서.**

- mock 기준선 재설정 문서는 집계 전후만 보여 준다. 그래서 dev q_0176(grade 3, 1.0→0.0)과 q_0061 악화가 드러나지 않는다. 보고서도 이를 언급하지 않는다. 기준선을 재설정할 때는 질의 단위로 악화된 목록을 함께 남긴다.
- known_issues 5번은 Loop 2b 상태(test 0.9707 FAIL, pytest 2건 실패)에 머물러 있다. 현재 상태로 갱신하고, 남은 위험(recorded test 여유 0)을 적는다.

**F6. `src/jupjup/search/service.py:264-279`, `:486-499`, `:627-634` — 게이트 판정이 서비스 안의 특례 두 곳으로 흩어졌다.**

- 임베딩 장애 fallback은 `_execute_ranked` 안에서 `GateDecision`을 직접 다시 만든다. anchored tail은 `_select_plan` 안에서 만든다. `RelevanceGate`가 게이트의 단일 진입점이라는 구조가 약해졌다. `_select_plan`은 약 180줄이다.
- 장애 fallback(`accepted_as_degraded_lexical_fallback`)의 negative 안전성은 직접 장애를 주입해 확인했다 (11종 empty). 하지만 이를 고정하는 자동 테스트는 없다. 기존 `test_degraded_when_embedder_fails`는 positive 하나만 본다.
- 꼬리의 utility가 앵커와 같으면 정렬 키 `(-utility, -relevance, …)` 때문에 R이 더 높은 꼬리가 1위가 될 수 있다. "꼬리는 1위에 참여하지 않는다"는 보고서 2절의 계약과 어긋나는 경계 사례다. 실제 재현 사례는 없다.

**개선:** 두 특례를 gate 쪽 `evaluate_with_context(anchor, degraded)` 같은 한 곳으로 옮긴다. 장애 모드 고정 negative 테스트를 추가한다. 정렬에서 primary/tail을 분리한다 (F1과 같은 수정).

### 참고 (감점 없음)

- mock `떡복이 맛집` false-empty (L2)는 그대로다. mock FE 0.012, 정책상 기록만 한다.
- `카톡으로 받은 회이 장소`의 `회이` 미교정은 이전 루프와 같다.
- recorded test R@10이 회귀 하한과 정확히 같다. 다음 품질 판단은 동결 test v2에서 해야 한다는 보고서 7절의 입장에 동의한다.

## 4. 채점 근거

- **정확성 36 / 40 (+5).**
  - 좋아진 점:
    - N1·N2·N3·N5를 두 mode의 CLI와 평가로 직접 확인했다.
    - recorded dev/test 모든 게이트와 challenge 인수 기준을 충족한다.
    - recorded dev는 질의 단위 악화 0, recorded test는 악화 0에 개선 5건이다.
    - 12절 고정 사례, 과잉·과소 완화, 요청 잠금, 오타, 교차 언어 사례가 모두 맞다.
  - 감점 사유:
    - anchored tail 비단조성(F1, −2). mode와 무관한 로직 결함이고 grade 3 정답이 사라진 실제 사례가 있다.
    - N2 해결이 test 사례 하나를 0.004 차이로 가르는 floor에 의존한다(F2, −1).
    - `다리` 사전 의존과 recorded test 여유 0 등 남은 위험(−1)
  - mock 순위 변화 자체는 PM 정책에 따라 감점하지 않았다.
- **안전성 29 / 30 (=).**
  - 직접 확인한 항목:
    - 요청 잠금(계획, postcondition, CLI)
    - 사용자 격리와 주입형 user id 거부
    - 입력 검증과 오류 정제
    - SQL 형태 질의
    - 임베딩 장애 시 negative 11종 empty
    - recorded 기준선 미변경과 결정성
  - 고정 negative가 이제 recorded 컨테이너에서도 돈다 (직전 감점 사유 해소).
  - 감점 사유: 새로 넣은 장애 fallback 경로의 negative 안전성을 자동 테스트가 보장하지 않는다(F6, −1).
- **유지보수성 25 / 30 (+1).**
  - 좋아진 점:
    - empty explain 진단 노출(L1)
    - 범용어 가중치화(삭제 대신)
    - 설정 validator(tail ≤ standalone, 도달 가능성)
    - recorded 통합 테스트 픽스처
    - 기준선 정책 README
    - 동결 test v2 골격
    - 정직한 "blind 아님, 제품 PASS 미선언" 보고
  - 감점 사유:
    - validator가 원래 결함을 못 잡음(F3, −1)
    - test 질의 원문을 회귀 테스트에 고정(F4, −1)
    - q_0176 악화 미보고와 오래된 known_issues 5번(F5, −1)
    - 서비스 내 게이트 특례 분산과 `_select_plan` 비대화(F6, −2)

## 5. PASS 이후 후속 과제 (known_issues로 이관 권장)

1. **F1**: anchored tail을 "버리기"에서 "순위 제한"으로 바꾸고, 단조성 테스트와 q_0176 회귀를 추가한다. 리랭커 사이클 T-단계에 들어가기 전에 처리하기를 권장한다. 점수 분포가 바뀌면 recorded에서도 나타날 수 있다.
2. **F2**: semantic-only 판정 근거를 cross-encoder floor로 옮길 때(Q-RA2) dev semantic-only negative를 보강한다.
3. **F3/F6**: 실측 분포 기반 도달 가능성 검사, 게이트 특례 일원화, 장애 모드 negative 테스트.
4. **F4/F5**: 동결 test v2에서 ch_0017·ch_0023·q_0180 처리를 결정하고, known_issues 5번과 기준선 README에 질의 단위 변화를 반영한다.
5. 제품 품질 PASS는 동결 test v2 작성, 2인 독립 검수, kappa 산출 뒤에 따로 판정한다.

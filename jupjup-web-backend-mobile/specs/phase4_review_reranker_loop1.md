# Phase 4 최종 검수 — 리랭커 사이클, Loop 1/3

- **점수:** 88 / 100
- **상태:** REJECT
- **항목별:** 정확성 36 / 40, 안전성 27 / 30, 유지보수성 25 / 30
- **루프백 대상:** Phase 2 (작은 범위). 기본 설치 테스트·타입 검사 실패(R1)와 채택 판정 함수의 빠진 규칙(R2)을 고친다. 리랭커 재튜닝이나 채택 재판정은 요구하지 않는다.
- **검수 대상:** `phase-4-review-reranker-loop1` HEAD `91d38d6` (구현 커밋, 기준 `c7da005`)
- **채점 기준(PM 정책):** 순위 품질은 recorded(bge-m3 녹화 재생)로 판정한다. mock은 안전 지표, 절대 기준, 결정성 확인용이다. 사람 검수 0건과 리랭커 채택 REJECT 자체는 감점하지 않았다(절차를 지킨 결과다). 범위 밖: T15 정식 API, LLM 연동, 인제스트.

## 0. 요약

- **기본 경로(리랭커 꺼짐)는 회귀가 없다.** 기준 커밋 `c7da005`와 현재 코드를 같은 골든셋으로 돌려 질의 단위로 비교했다. 바뀐 질의는 mock dev q_0176(복구)과 recorded dev q_0127(개선)뿐이고 악화는 0건이다. 기준선 파일은 바뀌지 않았고 평가 4종이 모두 PASS다.
- **F1(anchored tail 비단조)은 올바르게 해결됐다.** 꼬리 후보를 버리지 않고 primary 뒤로 보낸다. mock `주식 공부 영상`이 다시 정답 `0052`를 반환한다.
- **리랭커 구현은 대체로 설계대로다.** 창 선택, 단일 비행 실행기, v2 폴백, v3 게이트, 녹화(원문 없음), 재생 미스 오류가 모두 동작한다. recorded A/B를 두 번 돌린 리포트는 바이트 단위로 같고, 보고서 수치와도 일치한다.
- **A/B 판정 REJECT는 타당하다.** dev가 포화돼서 개선 경로 4개 중 2개는 수학적으로 도달할 수 없다. 하지만 판정을 가른 것은 개선 부족이 아니라 규칙 2(허용 하락)와 규칙 4(신뢰구간)의 **실제 악화**다. 그래서 평가셋 한계가 결론을 뒤집지는 않는다.
- **REJECT 사유:** 설계 13절 인수 기준 3번("기본 설치로 `uv run pytest` 전체 통과")과 12번(`mypy src` 통과)이 **기본 설치에서 실패한다**(R1). 보고서는 extra를 설치한 환경에서 검증했다. 여기에 판정 함수가 10.1절 규칙 일부를 계산하지 않는 문제(R2)와 여러 중간·낮음 결함이 더해져 90점에 못 미친다. R1은 수정량이 작지만 명시된 인수 기준의 객관적 실패라서 PASS를 줄 수 없다.

## 1. 직접 실행한 명령과 결과

### 1.1 정적 검사, 테스트, 평가 (이 워크트리 `.venv`. `uv sync --dry-run` 결과 "Would make no changes", 즉 extra 없는 기본 설치다)

| 명령 | 결과 |
|---|---|
| `uv run ruff check src tests` | PASS |
| `uv run mypy src` | **FAIL** — `src/jupjup/providers/rerank_bge.py:36: error: Returning Any from function declared to return "Callable[[Any], Any]"  [no-any-return]` (torch 미설치라 `torch.nn.Identity`가 Any) |
| `uv run pytest` | **FAIL — 1 failed, 601 passed, 3 deselected.** `tests/unit/test_cross_rerank.py::test_bge_requires_revision_and_validates_output`: `_identity()`가 `import torch` → `ModuleNotFoundError` → `RerankerError` |
| (참고) 별도 venv `uv sync --extra rerank` 후 `pytest` / `mypy src` | 602 passed / Success. 즉 보고서의 6.1절 수치는 extra 설치 환경의 결과다 |
| `uv run jupjup eval validate` | PASS — seeds 200, queries 259 (dev 158 / test 101) |
| `eval run --mode mock --split dev --baseline data/baselines/mock.json` | PASS — R@10 0.962, nDCG 0.9795, cat-min 0.884, TE 1.0, FE 0.000 |
| `eval run --mode mock --split test …` | PASS — R@10 0.942, cat-min 0.781, TE 1.0, FE 0.012 |
| `eval run --mode recorded --split dev --baseline data/baselines/recorded.json` | PASS — R@10 0.9712, nDCG 0.9860, cat-min 0.889, TE 1.0, FE 0.000 |
| `eval run --mode recorded --split test …` | PASS — R@10 0.972(회귀 하한 0.972, 여유 0 그대로), nDCG 0.9801, TE 1.0, FE 0.000 |
| `git diff --stat c7da005 HEAD -- data/baselines data/golden` | 변경 없음 |
| `jupjup eval ab --mode recorded --split dev --arms A0,A1` × 2회 | 두 리포트 `cmp` 동일. Recall −0.0315 [−0.0651, −0.0063], nDCG −0.0266 [−0.0602, −0.0014], FE +0.0168, category_min −0.1607. 규칙 1~4 FAIL, 판정 REJECT. 보고서 5.1절과 일치 |

### 1.2 기준 커밋 대비 기본 경로 회귀 (진단, scratchpad의 `git archive c7da005` 사본을 같은 venv로 실행)

| 평가 | 질의 단위 변화 |
|---|---|
| mock dev | q_0176 `주식 공부 영상`: `[0063]` → `[0063, 0052]`, R@10 0→1, nDCG 0→0.63 (F1 복구) |
| mock test | 변화 없음 |
| recorded dev | q_0127 `유튜브에서 본 기후 강의`: 3위에 `0047` 진입, R@5 0.5→1.0, nDCG 0.964→0.983. ch_0001은 지표 변화 없음 |
| recorded test | ch_0022 순서만 변화, 지표 변화 없음 |

악화 0건이다. 다만 q_0127 변화는 보고서에 없고, A/B의 A0은 `c7da005`가 아니라 "현재 HEAD + 리랭커 끔"이다(M4).

### 1.3 CLI (`seed load --db var/review.db`, recorded는 `JUPJUP_MODE=recorded`로 `var/review_rec.db`. 검색은 `--user u_alice --now 2026-10-15T12:00+09:00 --json`)

기본 설정(A0)은 두 mode 모두에서 이전 검수(cycle 2 Loop 3) 1.3절과 같은 결과다. A1은 `JUPJUP_SEARCH__CROSS_RERANK__ENABLED=true`로 켰다.

| 분류 | 사례 | A0 (mock / recorded) | A1 recorded |
|---|---|---|---|
| 회귀 | S7 `지난주 카톡으로 받은 회의 장소` | `0136`,`0146` + `time_window_expanded` ✅ | 같음 ✅ |
| 회귀 | `레스토랑 추천 블로그` | `0153` ✅ | 같음 ✅ (mock A1은 empty, 4.12절상 mock 리랭커는 배선용이라 감점 없음) |
| 회귀 | `다리 운동 영상` | `0040` 1위 ✅ | **`0051`만** (9.1절 위반, 보고서 5.4절에 공개됨) |
| 회귀 | `경주 맛집 인스타` / `하체 운동 유튜브` / `경주 맛집 카톡 논문` | 1위·완화 기록 일치 ✅ | 같음 ✅ |
| 회귀 | `지지난주 성수 카페 약속` | `0140` + `time_window_expanded`, 2위 `0031` ✅ | 같음 ✅ |
| 회귀 | `mars migration documentary 저장한 거` | empty ✅ | empty ✅ |
| 순위 | `환경 다큐` | `0047` 1위 ✅ | 같음 ✅ |
| 꼬리 | `그 영화 예매했던 거` | `0147`,`0053` ✅ | `0147`만 |
| 꼬리(F1) | `주식 공부 영상` | mock `0063`,`0052` ✅(복구, 정답은 앵커 뒤 2위) / recorded `0052` 1위 ✅ | `0052` ✅ |
| negative | `낚시 포인트 추천`, `북극곰 다큐`, `미얀마 여행 일정`, `보드게임 추천`, `수제 맥주 양조법` | 모두 empty ✅ | 모두 empty ✅ (mock A1 `미얀마 여행 일정` → `0139` 오탐, 배선용 mock이라 참고만) |
| 교차 언어 | `coffee cardiovascular health paper`, `retrieval augmented generation survey paper` | recorded `0112`,`0100` ✅ (mock empty) | 같음 ✅ |
| 동의어 | `스파게티 만드는 법`, `언젠가 저장한 선크림` | 정답 반환 ✅ | **empty** (보고서 4.3·5.1절에 공개) |
| 과잉 완화 | `경주 맛집 인스타 --platform instagram`, `경주 맛집 --type post` | empty, 완화 없음 ✅ | 같음 ✅ |
| 과잉 완화 | `하체 운동 유튜브 --platform youtube` | `0050`,`0051` ✅ | `[RERANK_CACHE_MISS]` (녹화 범위 밖, 재생 모드의 정상 실패) |
| 요청 잠금 | `회의 장소 --from 10-05 --to 10-12` | empty ✅ | `[RERANK_CACHE_MISS]` (위와 같음) |
| 정상 완화 | `지난달 하체 운동` / `지난달 경주 맛집` | expanded / dropped ✅ | 같음 ✅ |
| 과소 완화 | `지난달 인스타에서 본 성수동 카페` | `0001` 1위, 완화 없음 ✅ | 같음 ✅ |
| 오타 | `어버이날 선물 추쳔`, `기휴변화 논문`, `성수동까페` | 교정·관련 결과 ✅ | 같음 ✅ |
| 오타 | `떡복이 맛집` | mock empty(L2 그대로) / recorded `0019` ✅ | `0019` ✅ |
| 특수문자 | `카페'; DROP TABLE contents;--` | mock empty, DB 정상 ✅ / recorded `[EMBEDDING_CACHE_MISS]`(이전과 같음) | 같음 |
| 특수문자 | `!!!@@@###` | `[INVALID_QUERY]` ✅ | 같음 ✅ |
| 경계값 | 빈 문자열, 공백, `가`×201 | `[INVALID_QUERY]` ✅ | 같음 ✅ |
| 경계값 | `--platform tiktokx`, naive `--from`, `--limit 51` | `[INVALID_FILTER]` / 범위 오류, traceback 없음 ✅ | 같음 ✅ |
| 영어 혼합 | `IG에서 본 coffee shop dessert 그거` | 카페 문서 ✅ | `0036`,`0001` … ✅ |
| 필터 전용 | `지난달 인스타`, `유튜브 영상` | browse 최신순, `rerank_status=None` ✅ | 같음 (browse는 리랭크 안 함) ✅ |
| 격리 | bob `낚시 포인트 추천` | `c_bob_*`만 ✅ | `[RERANK_CACHE_MISS]` |
| 격리 | carol `경주 맛집` | empty ✅ | `[RERANK_CACHE_MISS]` |
| 격리 | `u_alice' OR 1=1` | `[INVALID_USER]` ✅ | 같음 ✅ |
| 격리 | 없는 사용자 `u_zed` | empty + 안내 ✅ | 같음 ✅ |

- recorded A1의 캐시 미스는 설계 4.7절대로 "조용히 넘어가지 않는" 정상 동작이다. 다만 그 때문에 요청 잠금·격리 CLI 사례를 A1로 확인할 수 없다(L4).
- 장애 주입: CLI `TIMEOUT_MS=1`로는 recorded 조회가 빨라 skip이 재현되지 않았다. INV-R5는 단위 테스트 `test_skipped_rerank_equals_v2`(MockReranker 지연·예외 주입)로 통과를 확인했다.

## 2. 기준 문서 대조

### 2.1 직전 검수(cycle 2 Loop 3) F1~F6 처리

| 항목 | 판정 | 근거 |
|---|---|---|
| F1 anchored tail 비단조 | **해결** | `service.py:536-548`. `utility <= top_utility` 조건 제거, 꼬리는 따로 정렬해 primary 뒤에 붙인다. mock q_0176 복구, `test_anchored_tail_acceptance_is_monotonic_in_relevance` 통과 |
| F2 semantic floor 근거 | **미해결, 기록 부정확** | 결정 근거를 cross floor로 옮기려 했지만 dev가 지지하지 않았고(보고서 2.1·7.3), 리랭커도 기본 꺼짐이다. 기본 경로는 여전히 cosine floor 0.61 하나다. 그런데 `known_issues.md:87`은 "이번 사이클에서 처리"로 남아 있다 (M5) |
| F3~F6 | 잔여로 이관 | `known_issues.md` 6절에 상태별로 기록됨. 사실과 맞다 |

### 2.2 설계 7절 불변식

| ID | 판정 |
|---|---|
| INV-R1, R3, R4, R6, R7, R8, R9 | 자동 테스트 있고 통과 |
| INV-R2 | **부분** — limit 축만 있다. `now`·요청 잠금 축 테스트가 없다 (M3, 보고서 7.4에 공개) |
| INV-R5 | timeout·error 주입 통과. busy는 실행기 단위 테스트만 있고 "결과가 v2와 같다"는 통합 비교는 없다 |

### 2.3 설계 13절 인수 기준 (단계 1 해당분)

| # | 결과 |
|---:|---|
| 1 불변식 테스트 | 부분 (INV-R2) |
| 2 9.1절 고정 회귀 A0·A1 | A0 충족. A1은 `다리 운동 영상` 1위 변경으로 실패하지만 미채택이고 보고서가 원인(cross 0.155 < floor 0.20)과 함께 공개했다 |
| **3 기본 설치 pytest 통과, torch import 없음** | **실패** — 기본 설치에서 1건 실패 (R1). 컨테이너가 torch를 import하지 않는다는 서브프로세스 테스트는 통과한다 |
| 4 recorded A/B 결정성 | 충족 (두 번 실행 동일) |
| 5 녹화본 원문 없음, 미스 실패 | 충족 (행 형식 확인, CLI에서 `RERANK_CACHE_MISS` 확인) |
| 6 실패·타임아웃·busy 시 v2와 동일 + degraded | 충족 (단 M2의 과잉 표시) |
| 9 `decide_reranker`가 10절 규칙 전부 계산, 경계 테스트 | **부분** — 9.1절 고정 회귀 미계산, 규칙 7 생략 시 ADOPT 가능 (R2) |
| 10 튜닝 값 설정화, `search_overrides` | 충족 |
| 11 test 이력 공개 | 충족 (5.2절) |
| **12 ruff, mypy 무경고** | **mypy 실패 (기본 설치)** (R1) |

### 2.4 A/B 판정 절차의 타당성

1. **dev 포화와 개선 경로.** A0 recorded dev는 S@1 1.0, MRR 1.0, nDCG 0.9860, TE 1.0, FE 0이다. 따라서
   - `success@1 +0.03`: 도달 불가 (A0이 이미 1.0)
   - `ndcg@10 +0.02`: 도달 불가 (최대 +0.014)
   - `challenge recall +0.05`: 0.9405에서 최대 +0.0595라 challenge dev positive를 사실상 전부 완벽히 맞혀야 한다
   - 시소 해소: Recall만 최대 +0.029까지 열려 있다

   즉 규칙 3은 dev에서 구조적으로 거의 통과할 수 없다. 이것은 구현자가 아니라 평가셋(설계)의 한계다. 보고서 5.1절과 known_issues 7절이 이를 명시했다.
2. **그래도 판정은 공정하다.** REJECT를 가른 것은 규칙 2와 4다. A1은 dev에서 0승 5패(Recall), 1승 9패(nDCG)이고, 질의 단위 손실(`스파게티`, `선크림`, `다리 운동` 등)도 원인과 함께 재현된다. 개선 여지가 있었더라도 이 악화만으로 기각된다. 설정 동결 뒤 test는 1회만 돌렸고 재튜닝하지 않았다. 절차를 지켰다.
3. **튜닝 범위.** 5,000여 조합을 dev 150질의에서 탐색했다. 과적합 위험은 있지만 결론이 "기각"이라 보수적 방향이다. β_cross=0(cross 무시)에서도 2패가 남는다는 사실(보고서 4.3)은 v3 프레임 자체(프로필 재계산, 창 밖 처리)가 A0과 중립이 아님을 뜻한다. 다음 재평가에서 원인을 분리할 가치가 있다 (L3).
4. **평가셋 한계와 다음 단계.** dev positive 119, negative 15, challenge dev 14라 CI가 넓다. 기존 test는 blind가 아니다. 재평가 전에 포화되지 않은 dev v2(사전 밖 동의어, 교차 언어, 부분 일치 g1)를 늘려야 한다는 보고서 7절 제안에 동의한다. 설계 9.2절의 "`다리` 사전 항목을 지운 사본에서 A1 진단"은 수행되지 않았다(보고서 5.3절은 사전 그대로 진단) (L5).

## 3. 피드백 (심각도 순, 줄 번호는 `91d38d6` 기준)

### 높음

**R1. `src/jupjup/providers/rerank_bge.py:33-36, 101` — 기본 설치에서 `pytest` 1건과 `mypy src`가 실패한다. 인수 기준 3·12 위반.**

- `score_logits`가 매 호출마다 `_identity()`를 부르고, 여기서 `import torch`를 한다. 테스트 `tests/unit/test_cross_rerank.py:247`은 가짜 모델을 주입하지만 torch가 없으면 `ModuleNotFoundError` → `RerankerError`로 실패한다.
- mypy는 torch가 없으면 `torch.nn.Identity()`를 Any로 보고 `no-any-return`을 낸다.
- 보고서 6.1절의 "602 passed", "mypy Success"는 extra 설치 환경의 결과다(별도 venv에서 재현). 기본 설치 기준이라는 표기와 다르다.
- **개선:** activation 함수를 모델 로딩 쪽(`_load_model`)에서 만들어 모델과 함께 보관하거나, `ModelFactory`가 `(model, activation)`을 돌려주게 한다. 테스트용 팩토리는 torch 없는 항등 함수를 준다. mypy는 `cast`로 Any 반환을 막는다. 기본 설치(`uv sync`만)에서 `uv run pytest`와 `uv run mypy src`를 돌린 결과를 보고서에 따로 적는다.

### 중간

**R2. `src/jupjup/eval/ab.py:366-372, 389, 451-452` — 판정 함수가 10.1절 규칙을 전부 계산하지 않고, 입력이 빠지면 통과 쪽으로 기운다.**

- 규칙 1의 "9.1절 고정 회귀 전부"를 계산하지 않는다. 이번 A1은 `다리 운동 영상` 1위가 바뀌어 규칙 1을 어기지만, 함수는 하네스 게이트 실패 때문에 FAIL을 냈을 뿐이다. 다른 지표가 좋았다면 고정 회귀를 어긴 설정도 ADOPT가 될 수 있다.
- `test_confirmed=None`이면 규칙 7을 아예 넣지 않는다. 단위 테스트 `test_decide_reranker_boundaries`(`tests/unit/test_cross_rerank.py:456`)도 test 확인 없이 `ADOPT`를 기대한다.
- `challenge_positive_recall@10`, `challenge_negative_true_empty`가 없으면 1.0으로(`:369-370`), `false_empty`가 없으면 통과로(`:389`) 처리한다.
- **개선:** 9.1절 고정 회귀 결과를 `ABComparison`에 넣고 규칙 1에서 검사한다. 규칙 7이 없으면 `PENDING_TEST` 같은 중간 상태를 내거나 ADOPT를 막는다. 빠진 지표는 실패로 처리한다(fail-closed). 각 경우에 단위 테스트를 둔다.

**M1. `src/jupjup/container.py:88-106` — live 컨테이너가 `warm_up()`의 추론 실패(`RerankerError`)를 잡지 않는다.**

- `except RerankerUnavailable`만 있다. 모델은 로드됐지만 첫 추론이 실패하면(장치 오류, 메모리 부족) `required=false`여도 컨테이너 생성이 실패한다. 설계 4.7절은 "경고 후 리랭커 없이 시작"이다.
- 같은 함수는 장치가 cpu로 결정되고 `enabled_on_cpu=false`일 때도 모델(약 750MB)을 적재하고 warm-up을 돈다. 그 뒤 모든 요청은 `cpu_disabled`로 건너뛴다. 쓰지 않을 모델을 메모리에 올린다.
- **개선:** `RerankerError`도 같은 경로로 처리한다. cpu이고 `enabled_on_cpu=false`면 적재 전에 `None, "cpu_disabled"`를 돌려준다.

**M2. `src/jupjup/search/service.py:301-302` — 설정에 따른 정상적인 건너뜀도 `degraded`로 표시한다.**

- `disabled`만 제외하고 `cpu_disabled`, `empty_query`도 `reranker_skipped:*`로 `degraded_reasons`에 넣는다. cpu 장비에서 리랭커를 켜면 **모든 응답이 `degraded=true`**가 된다. degraded는 장애 신호여야 하는데 정책이 장애처럼 보인다.
- **개선:** `degraded_reasons`에는 timeout·error·busy만 넣고, 정책 사유는 `rerank_status`(이미 `skipped:<사유>`가 있다)와 explain에만 남긴다.

**M3. INV-R2의 `now`·요청 잠금 축 테스트 없음 (`tests/unit/test_cross_rerank.py`)**

- 설계 7절 오라클은 "INV-02 테스트를 v3로 확장"이다. limit 축(`test_window_ignores_limit`)만 있다. 보고서 7.4에 공개됐지만 인수 기준 1의 미충족이다.
- **개선:** 같은 질의를 `now`만 다르게, 요청 플랫폼·기간 잠금만 다르게 실행해 두 번 모두 채점된 문서의 `cross`와 `R`이 같은지(차이 ≤ 1e-6) 확인한다.

**M4. A0 정의와 보고 누락 (`specs/phase2_reranker_report.md:24`)**

- 설계 8.1은 "A0 = Loop 3 병합 커밋으로 고정"이다. 실제 A0은 F1 수정이 들어간 HEAD + 리랭커 끔이다. 그 결과 recorded dev nDCG가 0.9858에서 0.9860으로 바뀌었고(q_0127 개선), 이 변화가 보고서에 없다. 결론에는 영향이 없지만, A0이 무엇인지와 기준 커밋 대비 질의 단위 변화를 적어야 한다.

**M5. `specs/known_issues.md:87` — F2 상태가 사실과 다르다.**

- "이번 사이클에서 처리"로 남아 있지만, 리랭커는 미채택이고 기본 경로의 semantic-only 판정은 여전히 cosine floor 0.61 하나다(q_0207 여유 0.004). 직전 검수가 지적한 F5(known_issues 갱신 누락)와 같은 유형이다.
- **개선:** "미해결 — 리랭커 미채택으로 기본 경로는 v2 floor 그대로"로 고치고, 다음 대안을 적는다.

### 낮음

- **L1. `src/jupjup/search/cross_rerank.py:182`** — recorded·mock 재생도 wall-clock 타임아웃(300ms)과 단일 비행 실행기를 거친다. 부하가 큰 CI에서 녹화본 조회가 늦어지면 `timeout` 폴백이 나와 재생 결정성이 깨질 수 있다. 재생 어댑터는 타임아웃 없이 동기 실행하는 편이 안전하다.
- **L2. `src/jupjup/search/service.py:630`** — v3 응답에서도 anchored tail 문턱으로 v2 설정 `lexical_only_tail_threshold`(0.44)를 쓴다. v3 R은 계수가 달라 척도가 같다는 보장이 없다. v3 설정에 같은 값을 따로 두거나, 공유가 맞다는 근거를 주석으로 남긴다.
- **L3.** β_cross=0에서도 A0 대비 2패(보고서 4.3). v3 재계산 자체의 영향(창 밖 문서의 unscored 규칙, 프로필 재판정)을 A0과 분리한 진단이 없다. 재평가 전에 "v3 + cross 무시"가 A0과 같은지 확인할 것.
- **L4.** 리랭커 녹화 범위에 골든 밖 요청 잠금·격리 사례(예: `--platform youtube`, bob/carol)가 없어 recorded A1로 9.1절 요청 잠금 사례를 CLI에서 확인할 수 없다. 채택 재평가 때는 9.1절 사례 전부를 녹화 범위에 넣는다.
- **L5.** 설계 9.2절 `다리 운동 영상`의 "사전 항목을 지운 사본에서 A1 결과" 참고 진단이 빠졌다(보고서 5.3은 사전 그대로).
- **L6. `src/jupjup/providers/rerank.py:35-37`** — `pair_hash`에 dtype·장치가 없다. 녹화는 mps fp16, 무결성 테스트는 cpu fp32라 같은 키에 다른 정밀도가 섞일 수 있다. 행에 `dtype`·`device`를 메타로 남기는 것을 권한다.
- **참고(감점 없음):** mock A1에서 `레스토랑 추천 블로그` empty, `미얀마 여행 일정` → `0139` 오탐. 설계 4.12절상 MockReranker는 배선 테스트용이고 기본값이 꺼져 있다.

## 4. 채점 근거

| 항목 | 점수 | 감점 |
|---|---:|---|
| 정확성 | 36 / 40 | R2 판정 함수의 규칙 누락과 fail-open (−2), M3 INV-R2 축 누락 (−1), M2 정책 skip의 degraded 표시 (−1). 기본 경로 무회귀, F1 해결, A/B 재현·결정성, 9.1·9.2절 정직한 공개는 가산 요소로 반영해 추가 감점 없음 |
| 안전성 | 27 / 30 | M1 warm-up 오류 미처리와 cpu 비활성 시 불필요한 모델 적재 (−2), L1 재생 경로의 wall-clock 타임아웃 (−1). 원문 없는 녹화, 미스 오류, 격리·요청 잠금·입력 검증은 A0·A1 모두 정상 |
| 유지보수성 | 25 / 30 | R1 기본 설치 테스트·mypy 실패와 검증 환경 오기 (−3), M4·M5 문서 부정확 (−1.5), L2·L6 (−0.5) |
| **합계** | **88 / 100** | **REJECT** |

## 5. 재검수 조건 (Loop 2)

1. **(R1)** extra 없는 기본 설치(`uv sync`)에서 `uv run pytest`, `uv run mypy src`, `uv run ruff check src tests`가 모두 통과한다. torch 없이 `BgeCrossEncoderReranker`의 출력 검증 테스트가 돈다. 보고서에 기본 설치와 extra 설치 결과를 나눠 적는다.
2. **(R2)** `decide_reranker`가 9.1절 고정 회귀를 규칙 1에서 계산하고, 규칙 7이 없거나 지표가 빠지면 ADOPT를 내지 않는다. 각 경우에 단위 테스트가 있다. 이번 A1 dev 리포트를 새 함수로 다시 판정해도 REJECT이고, 규칙 1 상세에 `다리 운동 영상`이 나온다.
3. **(M1·M2)** `RerankerError` warm-up 실패가 `required=false`에서 경고 후 v2로 시작한다. cpu + `enabled_on_cpu=false`면 모델을 적재하지 않는다. 정책 사유(`cpu_disabled`, `empty_query`)는 `degraded_reasons`에 들어가지 않는다. 각각 테스트가 있다.
4. **(M3)** INV-R2의 `now`·요청 잠금 축 테스트를 추가한다.
5. **(M4·M5)** 보고서에 A0 정의와 `c7da005` 대비 질의 단위 변화(mock q_0176, recorded q_0127)를 적고, `known_issues.md` F2 상태를 바로잡는다.
6. 기본 경로 무회귀를 다시 보인다. recorded·mock dev/test 4종 PASS, 기준선 파일 무변경, 위 1.3절의 A0 고정 회귀 사례 동일.
7. 리랭커 기본값 끔과 A/B 판정 REJECT는 유지한다. 재튜닝이나 test 재사용은 하지 않는다.

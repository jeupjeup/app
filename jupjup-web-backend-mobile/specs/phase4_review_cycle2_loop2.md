# Phase 4 최종 검수 — 완화 정책 v2 사이클, Loop 2/3

- **점수:** 84 / 100
- **상태:** REJECT
- **항목별:** 정확성 31 / 40, 안전성 29 / 30, 유지보수성 24 / 30
- **루프백 대상:** Phase 2 (기능/버그 문제)
- **검수 대상:** `phase-4-review-cycle2-loop2` HEAD `98878f1` (PM 브랜치에 포함됨. `4a82d15` Loop 2, `98878f1` Loop 2b)
- **채점 기준(PM 정책):** 순위 품질은 recorded(bge-m3)로 판정한다. mock은 안전 지표, 절대 기준, 결정성 확인용이다. mock 순위 회귀 게이트 실패는 "정책 전환 중" 항목으로 따로 기록하고 감점하지 않았다. 사람 검수 0건도 감점하지 않았다.

## 0. 요약

Loop 1 피드백 10건 중 6건을 해결했고 3건은 부분 해결, 1건은 대부분 해결했다. recorded dev true-empty 1.0, q_0117 복구, 최소 계획 선택, status gate의 `None` 처리는 직접 확인했다.

하지만 이번 루프의 수정에서 **새 구조 결함 두 개**가 생겼다.

1. **low-signal 질의는 사실상 통과할 수 없다 (높음).**
   - Loop 2에서 R 계수를 0.35배로 줄였는데, `low_signal_threshold=0.58`은 그대로 뒀다. 그 결과 semantic-only 후보가 낼 수 있는 R 상한은 0.587이 됐다.
   - 같은 루프에서 원형 토큰이 전부 OOV인 질의를 low-signal로 분류하도록 바꿨다.
   - 두 변경이 겹쳐 영어·교차 언어 질의가 recorded에서 빈 결과가 된다. ch_0017과 ch_0023은 1.0에서 0.0으로 떨어졌고, challenge positive 합산은 0.8485로 인수 기준 0.9091에 못 미친다.
2. **semantic-only의 판정 근거가 잡음 대역 안의 floor 하나뿐이다 (높음).**
   - Loop 2b에서 semantic-only 문턱을 0.55에서 0.45로 내렸다. 이제 semantic-only 통과 여부는 raw cosine 0.514 이상인지만으로 정해진다.
   - 그래서 Loop 1 피드백 1의 대표 오탐인 `낚시 포인트 추천`이 recorded에서 다시 반환된다. recorded test true-empty는 1.0에서 0.9로 내려갔다.

recorded test의 회귀 게이트도 Recall@10 0.9707 < 0.9720으로 FAIL이다.

## 1. 직접 실행한 명령과 결과

### 1.1 정적 검사, 테스트, 평가

| 명령 | 결과 |
|---|---|
| `uv run ruff check .` | PASS |
| `uv run mypy src` | PASS (52 source files) |
| `uv run pytest` | **FAIL — 2 failed**: `tests/eval/test_golden_regression.py::test_no_regression_vs_baseline`, `::test_mock_absolute_gate`. 둘 다 mock `split=all` Recall@10 0.949613 < 0.957262 → mock 순위 회귀이므로 **정책 전환 항목으로 기록하고 감점하지 않음** |
| `uv run jupjup eval validate` | PASS — seeds 200, queries 259 (dev 158 / test 101), lexicon 139, reviewed 0 |
| `eval run --mode recorded --split dev --baseline data/baselines/recorded.json` | **PASS** — R@10 0.9712, MRR 1.0, nDCG 0.9858, cat-min 0.8894, TE 1.000, FE 0.000 |
| `eval run --mode recorded --split test --baseline …` | **FAIL** — 절대 기준은 모두 통과(R@10 0.9707, TE 0.900, FE 0.000). **회귀 Recall@10 0.9707 < 0.9720 FAIL**, MRR·nDCG 회귀 통과 |
| `eval run --mode mock --split dev --baseline data/baselines/mock.json` | PASS — R@10 0.9628, TE 1.000, FE 0.000 |
| `eval run --mode mock --split test --baseline …` | 회귀 FAIL(R@10 0.9287, nDCG 0.9455). 절대 기준과 안전 지표는 PASS(FE 0.012, 격리·필터 위반 0) → 정책 전환 항목 |
| recorded dev 2회 실행 후 `results`·`overall` 비교 | 동일 (INV-20 OK). 차이는 baseline 유무에 따른 `gate`·`config` 필드뿐 |
| challenge 집계 (recorded) | positive R@10: dev 0.9405(14), **test 0.6875(8), 합산 0.8485 < 0.9091**. negative ch_0011/12 empty |
| challenge 집계 (mock, 참고) | 합산 0.6818 |

### 1.2 진단 (코드는 바꾸지 않음. scratchpad 사본에서만 실행)

| 진단 | 결과 |
|---|---|
| `git archive a2e55de`(v2 이전 기준선 코드)와 `cdcde17`(Loop 1)을 풀어 4개 평가 실행 후 질의별 비교 | 아래 2.3절 표 |
| recorded `coffee cardiovascular health paper --explain` | `profile=low-signal`, 결과 empty, top-level debug는 `content_type_filter_dropped: no_candidate`만 표시하고 strict 계획의 게이트 거부 사유는 없음 |
| `--overrides '{"gate":{"low_signal_threshold":0.45}}'`로 recorded dev/test 실행 (진단 전용) | test: ch_0017 → `c_alice_0112`, ch_0023 → `c_alice_0100` 복구. dev: R@10·TE·FE 변화 없음, ch_0011 empty 유지 → 피드백 N1의 원인 확정 |
| recorded `낚시 포인트 추천 --explain` | `c_alice_0021` "가평 글램핑 추천": semantic 0.606 (raw 0.5135), ol 0, key_coverage 0, `signals=[semantic]`, semantic-only, R 0.4613 ≥ 0.45 → accepted |
| recorded `환경 다큐 --explain` | 정답 `c_alice_0047`(sem 0.694로 최고) R 0.504, 5위. `c_alice_0113` "딥러닝 기반 음성 인식 개선"(sem 0.401, `환경` body 일치) R 0.558, 4위 |
| 사본에서 `directional_expansions.다리` 삭제 후 dev 평가와 통합 테스트 | q_0167: mock `c_alice_0050` 1위, recorded `c_alice_0051` 1위로 **회귀**. `test_same_top_does_not_record_content_type_relaxation[2/10/50]` 실패 |
| `git branch --contains 98878f1` | PM 포함 확인 |

### 1.3 CLI (`seed load --db var/review.db`; 검색은 `--user u_alice --db var/review.db --now 2026-10-15T12:00+09:00`)

mock DB는 `var/review.db`, recorded는 `JUPJUP_MODE=recorded`로 `var/review_rec.db`에 따로 적재했다.

| 분류 | 사례 | 결과 |
|---|---|---|
| 회귀 | S7 `지난주 카톡으로 받은 회의 장소` limit 1/2/10/50 (두 mode) | `c_alice_0136` 1위, `time_window_expanded`만, 2위 `0146`(10-13, 확장 창 안), `time_filter_dropped` 문서 없음 ✅ |
| 회귀 | `레스토랑 추천 블로그` | `0153`만, 완화 없음 ✅ |
| 회귀 | `다리 운동 영상` (두 mode) | `0040` 1위 ✅. 단 keywords가 `[하체, 운동]`이라 원형 `다리`가 빠짐 ⚠️ (N5) |
| 회귀 | `경주 맛집 인스타` / `하체 운동 유튜브` / `경주 맛집 카톡 논문` | platform / platform / platform+content_type, 1위 `relaxed_facets` 일치 ✅ |
| 회귀 | `지지난주 성수 카페 약속` (두 mode) | `0140` 1위, `time_window_expanded`, 2위 `0031` 완화 없음 ✅ |
| 회귀 | `mars migration documentary 저장한 거` | empty ✅ |
| 과잉 완화 | `경주 맛집 인스타 --platform instagram`, `경주 맛집 --type post` | empty, 완화 없음 ✅ |
| 과잉 완화 | `하체 운동 유튜브 --platform youtube` | youtube만 (`0050`, `0051`) ✅ |
| 요청 잠금 | `회의 장소 --from 10-05 --to 10-12`, S7 + `--platform kakaotalk` + 같은 기간 | empty, 잠금 밖 문서 없음 ✅ |
| 정상 완화 | `지난달 하체 운동` / `지난달 경주 맛집` / `경주 맛집 카톡` | expanded / dropped / platform ✅ |
| 과소 완화 | `지난달 인스타에서 본 성수동 카페` | `0001` 1위, 완화 없음 ✅ |
| 오타 | `어버이날 선물 추쳔`, `기휴변화 논문` (두 mode), `성수동까페`, `유툽에서 본 파스타` | 교정 및 관련 결과 ✅ |
| 오타 | `트랜치코트 코디` | confidence 0.825 교정, `0011` ✅ |
| 오타 | `떡복이 맛집` | recorded는 `0019` ✅, **mock은 empty** (mock false-empty, 안전 지표 범위 안) ⚠️ |
| 비교정 | `아프리카 사파리 여행` | 교정 없음, empty ✅ |
| negative (mock) | `낚시 포인트 추천`, `수제 맥주 양조법`, `화성 이주 계획 다큐` | empty ✅ |
| negative (recorded) | `뉴욕 브루클린 맛집`, `테니스 라켓 추천`, `보드게임 추천`, `아프리카 사파리 여행` | empty ✅ |
| negative (recorded) | **`낚시 포인트 추천`** | **`c_alice_0021` "가평 글램핑 추천" 반환 ❌ (N2)** |
| 교차 언어 (recorded) | **`coffee cardiovascular health paper`, `retrieval augmented generation survey paper`** | **empty ❌ (N1)**. 기준선 코드에서는 정답 1위 |
| 교차 언어 | `IG에서 본 coffee shop dessert 그거`(recorded), `IG에서 본 coffee shop 디저트`(mock) | 인스타 카페 ✅ |
| 순위 | `환경 다큐` (두 mode) | 딥러닝 음성 인식 논문이 기후위기 다큐보다 위 (recorded) / 정답 미반환 (mock) ❌ (N3) |
| soft facet | `유툽 레시피` | youtube 5건이 위에 오고 local 이미지는 뒤에 옴 ✅ (표시 `score`는 R이라 단조가 아님, 참고) |
| browse | `지난달 인스타` | browse, 최신순 4건 ✅ |
| 경계값 | 빈 문자열, 공백, 200자 반복, 201자, `!!!@@@###` | 모두 `[INVALID_QUERY]` ✅ |
| 경계값 | 잘못된 플랫폼·유형, naive `--from`, 역전 기간 | `[INVALID_FILTER]` ✅ |
| 경계값 | `--limit 0`, `--limit 51` | CLI 범위 오류, traceback 없음 ✅ |
| 격리 | bob `낚시 포인트 추천` | 자기 문서만 ✅ |
| 격리 | carol `경주 맛집` | empty ✅ |
| 격리 | `u_alice' OR 1=1` | `[INVALID_USER]` ✅ |
| 격리 | 없는 사용자 `u_zed` | empty ✅ |
| 특수문자 | `#카페 @성수!!` | 검색 성공. `#카페→카페`가 spelling 교정(0.89)으로 기록됨 (참고) |

## 2. 기준 문서 대조

### 2.1 직전 검수 피드백 1~10 해결 여부

| # | 판정 | 근거 (직접 확인) |
|---:|---|---|
| 1 corroboration 잡음 | **부분 해결** | dev q_0199/0203/0206/0211과 ch_0011은 empty다. recorded dev TE는 1.0이다. recorded test의 v2 신규 오탐 3건 중 `뉴욕 브루클린`, `테니스`, `아프리카`는 empty가 됐다. 하지만 Loop 2b에서 semantic-only 문턱을 내린 뒤 **대표 사례 `낚시 포인트 추천`(q_0207)이 recorded에서 다시 오탐**이 됐다 (N2). 통합 테스트 `test_weak_generic_lexical_overlap_stays_empty`는 mock 컨테이너에서만 돌아 이 회귀를 잡지 못한다. 고친 방식인 curated 범용어 목록도 새 순위 결함을 만들었다 (N3). |
| 2 시그모이드 포화 | **해결 (부작용 있음)** | 두 mode의 q_0117에서 `0140`이 1위이고 `time_window_expanded`만 기록된다. 통합 테스트도 있다. q_0173과 12절 사례는 유지된다. 단, 계수를 축소하면서 low-signal 문턱을 같이 다시 맞추지 않아 N1이 생겼다. |
| 3 교정 신뢰도 / 2음절 | **대부분 해결** | edit/frequency/context로 신뢰도를 계산하고, evidence 라벨은 실제 기여할 때만 붙인다. `추쳔`, `기휴변화`는 복구됐고(curated 0.99), `아프리카`·`다리`·`이주`는 교정하지 않는다. 2음절은 문맥 0.5 이상, 신뢰도 0.9 이상일 때만 허용한다. 잔여: mock `떡복이 맛집` false-empty (mock 전용, L2) |
| 4 최소 계획 | **해결** | 정렬 키에 허용 relaxation 수와 범위 비용을 넣었다 (`service.py:397-398`). S7을 limit 1/2/10/50으로 돌려도 `time_filter_dropped` 문서가 없고, 테스트도 추가됐다. |
| 5 PM 병합 | **해결** | `98878f1`이 PM에 포함돼 있다. |
| 6 동의어 정리 | **부분 해결** | 비동치 그룹 4개는 제거했다. 하지만 `다리→하체`를 단방향으로 남겼고, 이 항목을 빼면 `다리 운동 영상`이 두 mode에서 다시 실패한다 (통합 테스트 3건 실패). 재검수 조건 6은 "사전 항목 없이도 어떻게 되는지 보고"였는데, 보고서는 "양방향 동의어 없이도 1위"라고만 적었다. 단방향 확장이 원형을 keywords에서 **대체**하는 문제도 있다 (N5). |
| 7 INV-02/14 테스트 | **해결** | `test_inv02_inv14_service_relevance_ignores_limit_now_and_request_lock`이 서로 다른 limit, now, 플랫폼 잠금으로 같은 문서의 R을 비교한다. |
| 8 설계 계약 일부 | **대부분 해결** | 후보 합집합 cosine 직접 계산 ✅, augmented n-gram 사용 ✅, OOV면 low-signal ✅(단, N1과 결합). empty일 때 top-level debug는 나오지만 `no_candidate` 사유가 "후보 없음"과 "게이트에서 전부 거부"를 구분하지 못한다. strict 계획의 거부 사유도 보이지 않는다 (L1). |
| 9 status gate 1.0 | **해결** | 분모가 0이면 `None`과 not-evaluated로 처리한다 (`harness.py`). |
| 10 tail margin | **해결** | 0.60에서 0.40으로 줄였다. |

### 2.2 known_issues

1~4번은 해결 상태가 유지된다. 4번 `다리`는 사전 의존이 남아 있다 (N5). 5번(test 재현율 회귀)은 보고서대로 미해결이다. 이번 검수로 같은 범주에 다음 두 건을 추가해야 한다.
- low-signal 도달 불가 (N1)
- semantic-only 오탐 (N2)

### 2.3 v2 이전 기준선(`a2e55de`) 대비 질의별 변화 — recorded

| split | 질의 | 변화 | 원인 |
|---|---|---|---|
| test | ch_0017 `coffee cardiovascular health paper` | R@10 1.0 → **0.0** (Loop 1에서도 1.0) | N1 |
| test | ch_0023 `retrieval augmented generation survey paper` | 1.0 → **0.0** | N1 |
| test | q_0207 `낚시 포인트 추천` (negative) | empty → **`0021` 반환** | N2 |
| test | q_0180 `환경 다큐` | MRR 1.0 → **0.2** | N3 |
| test | q_0045 `카톡으로 받은 회이 장소` | MRR 0.5 → 0.33 (g1 `0146` 1위) | 오타 `회이` 미교정 (Loop 1과 동일) |
| test | q_0038, q_0161, q_0182 | R@10 소폭 하락 | 이전 보고서의 G/H 유형 |
| dev | q_0057, q_0081 | R@10 하락 (g1 꼬리) | 설계 정책의 대가 (최소 계획, 부분 일치 g1) |
| dev | q_0061, q_0127, q_0166, ch_0001, ch_0003 | 개선 | |
| dev | q_0199/0203/0206/0211, ch_0011 | 오탐 → empty | |

### 2.4 15절 인수 기준

| # | 결과 |
|---:|---|
| 1 불변식 자동 테스트 | 충족. INV-02/14 서비스 경로 테스트가 추가됐다. |
| 2 12절 고정 회귀 | 충족. `다리`는 사전 항목에 의존한다. |
| 3 요청 잠금·격리 위반 0 | 충족 (평가와 CLI 모두) |
| 4 `R` 문맥 독립 | 충족 |
| 5 recorded dev TE ≥ 0.80 / challenge | TE 1.0으로 충족. **challenge positive 합산 0.8485 < 0.9091로 미충족** |
| 6 recorded 절대/회귀 기준 | 절대 기준은 충족한다. **test 회귀 Recall@10 FAIL (0.0013 부족)** |
| 7 test 동결 | 보고서에 따르면 test aggregate를 두 번 봤고, 그 사이에 조치 7·8을 추가했다. 엄밀한 blind가 아님을 보고서가 정직하게 밝혔다. |
| 8 human evidence eligible=false | 충족 |
| 9 응답 기록과 실제 위반 일치 | 충족 (S7 꼬리 문제 해결) |
| 10 계수·탐색 기록 | 충족. 다만 low-signal 문턱 재검토가 탐색에서 빠졌다. |

## 3. 새 피드백 (심각도 순, 줄 번호는 `98878f1` 기준)

### 높음

**N1. `src/jupjup/config.py:174`, `src/jupjup/config.py:120-126`, `src/jupjup/query/understanding.py:198-202`, `src/jupjup/search/gate.py:22-23` — low-signal 문턱 0.58은 축소된 계수에서 도달할 수 없다. 그래서 교차 언어 질의가 항상 빈 결과가 된다.**

- R = σ(−1.05 + 1.40·sem + …)이다. 어휘·목적 증거가 없는 후보는 sem = 1.0이어도 R이 0.587에 그친다. 문턱 0.58을 넘으려면 sem ≥ 0.981(raw ≥ 0.739)이 필요하다. 교차 언어 bge-m3 cosine으로는 사실상 나오지 않는 값이다.
- Loop 2는 같은 루프에서 "원형 토큰 전부 OOV → low-signal"(피드백 8)을 추가했다. 그래서 영어 질의는 원형 어휘 일치가 없고 low-signal로 분류돼 거의 모두 탈락한다.
- recorded test에서 ch_0017과 ch_0023이 1.0에서 0.0으로 떨어졌다. challenge 인수 기준도 미달이다.
- 설계 7.3절의 "영어·혼합 언어이거나 개인 어휘에 없는 정상 질의는 검색한다"와 정면으로 어긋난다.
- Loop 2b는 같은 이유로 semantic-only 문턱만 0.45로 맞추고 low-signal 문턱은 빠뜨렸다. dev에는 low-signal positive가 없어서 dev 분석으로는 보이지 않았다.
- 진단으로 문턱을 0.45로 덮어쓰면 두 질의가 복구되고 dev 지표는 변하지 않는다.

**개선:**
- 계수 축소에 맞춰 low-signal 보정을 R 문턱이 아니라 semantic floor 상향 같은 증거 공간에서 정의한다.
- 모든 R 문턱을 같은 계수 척도에서 한 번에 다시 calibration한다.
- "각 프로필의 R 문턱은 sem·lexical 최대치로 도달 가능하다"는 설정 불변식 테스트를 추가한다.
- recorded 컨테이너로 dev의 교차 언어 positive(ch_0001, ch_0003)와 negative(ch_0011)를 고정하는 통합 테스트를 추가한다.
- test 질의로 튜닝하지 않는다. dev 근거만으로 고치고, 필요하면 dev에 교차 언어 positive를 보강한다.

**N2. `src/jupjup/config.py:172`, `src/jupjup/config.py:176`, `src/jupjup/search/relevance.py:96-97`, `tests/integration/test_search_v0.py:197` — semantic-only 판정이 잡음 대역 안의 floor 하나에만 걸려 있다. 피드백 1의 대표 오탐이 다시 생겼다.**

- semantic-only 문턱이 0.45라서 통과 조건은 사실상 sem ≥ 0.607(raw ≥ 0.514)이다.
- 보고서가 직접 잰 값으로도 dev negative 최대 raw는 0.484이고 정답 5분위는 0.458이다. 즉 floor가 분포 중첩 구간 안에 있다.
- recorded test q_0207 `낚시 포인트 추천`이 `c_alice_0021` "가평 글램핑 추천"(raw 0.5135, ol 0)을 반환한다. Loop 1의 대표 사례가 그대로 재발했다. recorded test true-empty는 1.0에서 0.9로 내려갔다.
- 같은 질의가 들어 있는 통합 테스트는 mock 컨테이너에서만 돌기 때문에 이 회귀를 잡지 못한다.

**개선:**
- semantic-only 통과에는 floor와 함께 질의 단위 근거가 필요하다. 예를 들면 질의 핵심어 중 일부라도 의미적으로 대응하는지, 또는 같은 문서가 다른 정답 후보와 비교해 상대 margin을 갖는지를 본다.
- 아니면 floor를 dev negative 최대치보다 확실히 높게 두고, 그 대가인 semantic-only 재현율을 dev에서 보고한다.
- 고정 negative 회귀를 recorded로도 실행한다.

### 중간

**N3. `src/jupjup/search/relevance.py:60-61`, `src/jupjup/search/relevance.py:161-164`, `src/jupjup/config.py:130-140` — 범용어를 R 계산에서 아예 빼서 한 단어 일치가 전체 coverage가 된다.**

- `_informative_terms`는 범용어를 원형 lexical의 분자와 분모에서 모두 지운다. `환경 다큐`는 사실상 `환경` 한 단어 질의가 된다.
- 그래서 본문에 `환경`이 있는 "딥러닝 기반 음성 인식 개선"(sem 0.40)이 coverage 0.6, R 0.558로 통과한다. 정답 "기후위기 다큐멘터리 녹는 빙하"(sem 0.69로 최고)는 R 0.504로 그 아래에 있다.
- recorded q_0180 MRR이 1.0에서 0.2로 떨어졌다. mock에서는 정답이 반환되지 않는다.
- `다큐/다큐멘터리`는 보고서 스스로 df=1이라고 밝힌 단어다. 범용어라기보다 dev q_0199를 막기 위한 항목이다.

**개선:**
- 범용어는 게이트 신호(핵심어 coverage) 판정에서만 낮은 가중치로 다룬다. R의 `original_lexical`에서는 지우지 말고 가중치만 줄인다.
- 목록 대신 질의 내 상대 IDF 같은 일반 규칙을 검토한다.
- `환경 다큐`형인 "범용어 + 핵심어 1개" 질의에서 의미가 강한 정답이 우선하는지 dev 사례로 테스트한다.

**N4. recorded test 회귀 게이트 FAIL — Recall@10 0.9707 < 0.9720 (`data/baselines/recorded.json`).**

PM 정책상 recorded는 순위 품질의 기준이고, 이 게이트는 면제 대상이 아니다. 차이는 0.0013으로 작다. 하지만 N1~N3을 고치기 전까지는 원인이 구조적이다. 기준선을 v2 정책으로 다시 정할지는 PM과 사용자가 결정할 일이고, 구현이 정할 일이 아니다 (재검수 조건 6).

**N5. `data/lexicon/synonyms.yaml:25`, `src/jupjup/query/spell.py:56-69` — `다리` 사례가 여전히 사전 항목에 의존하고, 단방향 "확장"이 실제로는 대체다.**

- `directional_expansions.다리`를 빼면 q_0167이 두 mode에서 회귀하고(mock `0050`, recorded `0051` 1위) 통합 테스트 3건이 실패한다. 보고서는 이 결과를 적지 않았다.
- `SpellCorrector`는 단방향 확장 항목을 `out`에서 원형 대신 넣는다. 그래서 keywords가 `[하체, 운동]`이 되고, `다리`는 morph 검색어에서 빠진다(원형 R은 `original_terms`로 유지된다). 이름은 확장인데 동작은 동의어 정규화와 같다. 보고서 2.1절이 밝힌 대로 `디저트→케이크` 같은 상하위어 확장도 이 구조 때문에 시도하지 못했다.

**개선:** 확장 term을 원형과 나란히 추가하고 keywords 계약 테스트를 갱신한다. `다리` 사례가 사전 없이는 실패한다는 사실을 known_issues 4번에 명시한다.

### 낮음

- **L1. `src/jupjup/search/service.py:364`, `src/jupjup/search/service.py:179-184` — empty일 때 explain이 진단에 쓸모가 적다.**
  `no_candidate`가 "검색 후보 0"과 "후보는 있었지만 게이트에서 전부 거부"를 구분하지 않는다. strict 계획은 attempted 목록에도 나오지 않는다. N1을 explain만으로는 찾을 수 없었다. 계획별 후보 수와 거부 사유 상위 몇 개(`semantic_floor`, `below_threshold` 등)를 노출한다.
- **L2. mock 안전 지표:** mock test에서 q_0042 `떡복이 맛집`이 false-empty다(recorded는 정상). mock FE는 0.012로 ≤ 0.05 안이다. `떡복→떡볶` 교정의 신뢰도와 문맥 근거가 hashing에서 부족하다. 정책상 감점하지 않고 기록만 한다.
- **L3. test split 오염:**
  - `spelling_corrections.기휴변화`는 test 질의 q_0038을 직접 겨냥한 항목이다. 직전 검수가 복구를 요청했으므로 감점하지 않는다.
  - Loop 2b는 test aggregate를 두 번 봤다.
  - 따라서 다음 PASS 판정에 쓸 동결 test v2 결정을 PM이 기록해야 한다 (직전 재검수 조건 7이 아직 열려 있다).
- **L4. `#카페` 같은 해시태그 토큰이 spelling 교정(0.89)으로 기록된다.** 사용자에게 "오타 교정"으로 보일 수 있으므로 정규화 단계에서 기호를 떼어 내는 편이 맞다.

## 4. 채점 근거

- **정확성 31 / 40 (+1).**
  - 좋아진 점: q_0117 복구, 최소 계획, dev 오탐 4건과 ch_0011 제거, 오타 복구, recorded dev 모든 지표 PASS를 직접 확인했다.
  - 감점 사유:
    - 이번 루프에서 새로 생긴 low-signal 도달 불가 결함(N1). 교차 언어라는 설계상 지원 범주 전체를 막고, challenge 인수 기준 미달로 이어진다.
    - Loop 1의 대표 오탐 재발(N2)
    - 범용어 제거로 인한 순위 결함(N3)
    - recorded test 회귀 게이트 FAIL(N4)
  - mock 순위 회귀와 pytest 2건은 PM 정책에 따라 감점하지 않았다.
- **안전성 29 / 30 (+1).**
  - 직접 확인한 항목: 요청 잠금(계획과 postcondition), 사용자 격리, 입력 검증, 오류 정제, status gate의 `None` 처리, 기준선 미갱신 원칙 준수, 결정성.
  - 감점 사유: 고정 negative 회귀를 mock에서만 검증해 recorded 오탐을 테스트가 보장하지 못한다.
- **유지보수성 24 / 30 (+1).**
  - 좋아진 점:
    - 증거 판정을 `signals` 한 곳으로 모았다.
    - 중복 설정을 정리했다.
    - 교정 신뢰도를 실제로 계산한다.
    - INV-02/14 서비스 테스트를 추가했다.
    - test로 재튜닝하지 않았고 보고가 정직하다.
  - 감점 사유:
    - 계수를 축소할 때 문턱 4개를 같은 척도에서 다시 맞추지 않은 설정 비일관성
    - dev 맞춤 curated 범용어 목록
    - 이름과 동작이 다른 단방향 확장
    - `다리` 사전 의존을 보고하지 않은 점
    - 진단성이 부족한 empty explain

## 5. 재검수 조건

1. **N1:** 모든 evidence/signal 프로필의 R 문턱이 현재 계수에서 도달 가능하다는 설정 불변식 테스트가 있다. recorded에서 ch_0017/ch_0023형 교차 언어 positive가 반환되고, ch_0011/ch_0012는 empty를 유지한다. 근거는 dev만 쓴다. recorded challenge positive 합산 R@10 ≥ 0.9091을 만족한다.
2. **N2:** recorded `낚시 포인트 추천`이 empty다. 고정 negative 회귀(`북극곰 다큐`, `미얀마 여행 일정`, `보드게임 추천`, `낚시 포인트 추천`, ch_0011)를 **recorded 컨테이너로도** 실행하는 테스트가 있다. recorded dev TE ≥ 0.80, FE ≤ 0.03을 유지한다.
3. **N3:** 범용어를 R에서 지우지 않는다. `환경 다큐`형 dev 사례에서 의미가 강한 정답이 단일 핵심어만 일치한 무관 문서보다 위에 온다.
4. **N5:** 단방향 확장이 원형을 보존한다. `다리` 사례의 사전 의존 여부를 known_issues에 사실대로 적는다.
5. **L1:** empty explain에 계획별 후보 수와 게이트 거부 사유가 나온다.
6. **PM·사용자 결정 기록:** (a) recorded 기준선을 v2 정책으로 다시 정할지, (b) 동결 test v2를 만들지 결정하고 그 결정을 기준으로 recorded test 회귀를 판정한다. mock 회귀 게이트(pytest 2건 포함)의 정책 전환 처리도 문서로 확정한다.
7. ruff, mypy, 전체 pytest, eval validate, mock/recorded dev/test와 기준선 비교, challenge 집계를 모두 다시 실행해 보고한다.

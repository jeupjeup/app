# Phase 4 최종 검수 — 완화 정책 v2 사이클, Loop 1/3

- **점수:** 81 / 100
- **상태:** REJECT
- **항목별:** 정확성 30 / 40, 안전성 28 / 30, 유지보수성 23 / 30
- **루프백 대상:** Phase 2 (기능/버그 문제). 병합 누락은 PM이 조치한다.
- **검수 대상:** `phase-2-relaxation-v2` 브랜치 커밋 `badd552` (아래 0절 참고)

## 0. 먼저 알릴 사항: 구현 코드가 PM 브랜치와 이 워크트리에 없다

- 이 워크트리(`phase-4-review-cycle2-loop1`, HEAD `356735e`)와 PM 브랜치(`f8afe2e`)에는 구현 보고서
  `specs/phase2_relaxation_v2_report.md`만 있다. 구현 커밋 `badd552 feat: implement Phase 2 relaxation policy v2`는
  `phase-2-relaxation-v2` 브랜치에만 있고 PM에 병합되지 않았다. `git diff HEAD phase-2-relaxation-v2` 결과
  21개 파일, +1378/−418줄 차이가 났다. `src/jupjup/search/relevance.py`가 없고, `known_issues.md`도 갱신 전 상태다.
- PM이 확인한 "recorded dev true_empty_rate 0.7333"은 이 워크트리의 **v2 이전 코드** 값이다. HEAD에서 직접
  돌려도 recorded dev는 0.7333(FAIL)이었고, 이는 보고서의 "dev 이전" 열과 같다.
- 그래서 검수는 `git archive badd552`로 scratchpad에 풀어 놓은 트리에서 했다. 이 워크트리의 코드는 바꾸지 않았다.
- `badd552` 기준 recorded dev는 **0.8000**(경계값으로 PASS)이고, recorded test는 **0.6000**(FAIL)이다.
  보고서 수치와 일치한다.

## 1. 직접 실행한 명령과 결과

### 1.1 이 워크트리 (HEAD `356735e`, v2 미포함)

| 명령 | 결과 |
|---|---|
| `uv run ruff check .` / `uv run mypy src` | PASS / PASS (51 files) |
| `uv run pytest` | 497 passed, 1 deselected |
| `eval run` mock dev / mock test | PASS (true-empty 0.733 / 0.800) |
| `eval run` recorded dev / recorded test | **FAIL (true-empty 0.7333 < 0.80)** / PASS (0.900) |
| `seed load --db var/review.db`, `search "경주 맛집 인스타"` | v1 과소 완화가 그대로 재현됨 (0020/0019 인스타 1·2위, 완화 없음) |

### 1.2 구현 트리 (`badd552`)

| 명령 | 결과 |
|---|---|
| `uv run ruff check .` | PASS |
| `uv run mypy src` | PASS (52 source files) |
| `uv run pytest` | PASS — 520 passed, 1 deselected (embed 테스트는 모델 캐시가 필요해 실행하지 않음) |
| `uv run jupjup eval validate` | PASS — seeds 200, queries 259, review metadata 0건, total/split 일치 |
| `eval run --mode mock --split dev [--baseline]` | PASS — R@10 0.9574, true-empty 0.733, 회귀 5개 OK |
| `eval run --mode mock --split test [--baseline]` | PASS — R@10 0.9687, true-empty 0.900, false-empty 0.012 |
| `eval run --mode recorded --split dev [--baseline]` | PASS — R@10 0.9706, true-empty **0.800**(경계), 회귀 OK |
| `eval run --mode recorded --split test [--baseline]` | **FAIL — true-empty 0.600 < 0.80** (회귀 지표는 OK) |
| recorded dev 2회 실행 후 `created_at/git_sha/perf` 제외 비교 | 동일 (INV-20 OK) |
| challenge 집계 (recorded) | positive R@10: dev 0.976(14건), test 0.875(8건), 합계 약 0.939 ≥ 0.9091. negative ch_0011/12 둘 다 empty |
| 진단 스크립트: 요청 플랫폼 잠금 유무에 따른 같은 q/doc의 `R` 비교 (mock, 468쌍) | 차이 0 |
| 진단 스크립트: 응답 결과의 `relaxed_facets` ⊄ `applied_relaxations` 검사 (전체 질의, 두 mode) | **두 mode에서 각 2건** (q_0083, ch_0007) — 피드백 4 |
| 진단: `[하체, 다리]` 동의어를 뺀 사본에서 `다리 운동 영상` | **`c_alice_0050` 1위로 회귀**, `test_same_top_...` 3건 실패 — 피드백 6 |

### 1.3 CLI (`seed load --db var/review.db`; 검색은 `--user u_alice --db var/review.db --now 2026-10-15T12:00+09:00`, mock)

| 사례 | 결과 |
|---|---|
| 12절 S7 `지난주 카톡으로 받은 회의 장소` ×limit 1/2/10/50 | `c_alice_0136` 1위, `time_window_expanded`, `relaxed=true` ✅. 단 2위 `c_alice_0150`(2025-11-12)은 `time_filter_dropped` 문서 ⚠️ |
| q_0173 `레스토랑 추천 블로그` | `c_alice_0153` 1위, blog만 반환, 완화 없음 ✅ |
| q_0167 `다리 운동 영상` | `c_alice_0040` 1위, 완화 없음, `자리` 교정 없음 ✅ (동의어 의존, 피드백 6) |
| `경주 맛집 인스타` | `c_alice_0153` 1위, `platform_filter_dropped`만 ✅ |
| `하체 운동 유튜브` | `c_alice_0040` 1위, `platform_filter_dropped`만 ✅ |
| `경주 맛집 카톡 논문` | `c_alice_0153` 1위, platform → content_type 두 항목, 1위 `relaxed_facets`도 두 항목 ✅ |
| ch_0003 (mock / recorded eval) | mock empty(허용), recorded `c_alice_0096` 1위, 관련 2건 top3, 완화 없음 ✅ |
| ch_0011 / ch_0012 | 모든 limit에서 empty, `applied=[]` ✅ |
| 과잉 완화 확인: `경주 맛집 인스타 --platform instagram`, `하체 운동 유튜브 --platform youtube`, `경주 맛집 --type post` | 요청 잠금 유지, 완화 없음 ✅ |
| 요청 기간 잠금 `회의 장소 --from 10-05 --to 10-12`, 플랫폼+기간 잠금 S7 | empty, 잠금 밖 문서를 반환하지 않음 ✅ |
| 정상 완화 `지난달 하체 운동` / `지난달 경주 맛집` / `경주 맛집 카톡` | expanded / dropped / platform 정상 ✅ |
| 정상 복합 `지난달 인스타에서 본 성수동 카페` | `c_alice_0001` 1위, 완화 없음 ✅ |
| 과소 완화 q_0117 `지지난주 성수 카페 약속` (eval) | **정답 `c_alice_0140` 미반환**, v2 이전 R@10 1.0 → 0.0 (두 mode) ❌ — 피드백 2 |
| 오타 `성수동까페`, `유툽에서 본 파스타` | 관련 결과 ✅ |
| 오타 `어버이날 선물 추쳔` | `추쳔` 미교정. 1위는 맞지만 q_0057 R@10 1.0 → 0.5 (mock) ⚠️ |
| 오타 `기휴변화 논문` | **mock empty** (q_0038 false-empty, v2 이전 R@10 1.0) ❌ — 피드백 3 |
| 영어 혼합 `IG에서 본 coffee shop 디저트` | 인스타 카페/디저트 ✅ |
| filter-only `지난달 인스타` | browse=true, 최신순 ✅ |
| 없는 대상 `화성 이주 계획 다큐` | empty ✅ |
| 없는 대상 `낚시 포인트 추천` (alice) | **`c_alice_0078` "여름 휴가에 읽을 책 10선" 반환** (Loop 3에선 empty) ❌ — 피드백 1 |
| 특수문자 `#카페 @성수!!` / `!!!@@@###` | 검색 성공 / `[INVALID_QUERY]` ✅ |
| 빈 문자열, 공백, 200자 반복, 201자 | `[INVALID_QUERY]` ✅ |
| 잘못된 플랫폼·유형, naive `--from`, 역전 기간, limit 0/51 | `[INVALID_FILTER]` 또는 CLI 범위 오류, traceback 없음 ✅ |
| 사용자 격리: bob `낚시 포인트 추천`, carol `경주 맛집`, 존재하지 않는 사용자, `u_alice' OR 1=1` | bob 자기 문서만, carol empty, 없는 사용자 empty, 잘못된 id `[INVALID_USER]` ✅ |

## 2. 기준 문서 대조

### 2.1 known_issues 1~4

| # | 판정 | 근거 |
|---:|---|---|
| 1 과소 완화 | **부분 해결** | 플랫폼 사례 두 건은 해결했다. 하지만 시그모이드 포화 때문에 기간 facet에서 같은 종류의 과소 완화가 새로 생겼다 (q_0117, 피드백 2). |
| 2 이중 facet 기록 | **해결** | 실제 위반에서 기록을 만든다. `경주 맛집 카톡 논문`의 두 항목도 확인했다. |
| 3 human gate | **해결 (잔여 낮음)** | `MetricObservation`, 분모별 eligibility, total/split 독립 검증, eligible 없는 human 기준선 갱신 거부를 확인했다. status gate의 1.0 채움은 남아 있다 (피드백 9). |
| 4 `다리→자리` | **해결 (방식 문제)** | 2음절 교정을 일괄 차단해 고쳤다. 그 부작용으로 오타 회귀가 생겼다 (피드백 3). |

### 2.2 11절 불변식

| ID | 판정 | 비고 |
|---|---|---|
| INV-01 | ✅ | 계획 생성 단계 `_assert_request_locks`와 최종 postcondition을 모두 확인 |
| INV-02, 14 | ⚠️ | 동작은 진단으로 확인했다. 하지만 테스트가 같은 입력을 두 번 넣는 동어반복이라 오라클이 없다 (피드백 7) |
| INV-03~06 | ✅ | 단일 경계 `should_adopt` |
| INV-07 | ✅ | |
| INV-08 | ⚠️ | 테스트는 계획의 hard filter만 본다. "계획이 허용했지만 결과는 위반하지 않음"은 검증하지 않는다. 실제 응답 꼬리는 최소 계획이 아니다 (피드백 4) |
| INV-09~13, 15~20 | ✅ | INV-11은 설계대로 동작하지만 mock 오타 false-empty를 만든다 (피드백 3) |

### 2.3 15절 인수 기준

| # | 결과 |
|---:|---|
| 1 불변식 자동 테스트 | 대체로 충족. INV-02/14와 INV-08 오라클이 약함 |
| 2 12절 고정 회귀 | 충족. `다리` 사례는 동의어 추가에 의존 |
| 3 요청 잠금·격리 위반 0 | 충족 |
| 4 `R` 문맥 독립 | 충족 (진단 468쌍 차이 0) |
| 5 recorded dev TE ≥ 0.80 / challenge | 충족. 단 0.8000은 정확히 경계값 |
| 6 mock·recorded 절대/회귀 기준 | **미충족 — recorded test true-empty 0.60** |
| 7 test는 동결 후 1회 | 충족. 재튜닝하지 않고 실패를 정직하게 보고함 |
| 8 human evidence eligible=false | 충족 |
| 9 응답 기록과 실제 위반 일치 | 1위 기준으로는 충족. 꼬리 결과가 선택 계획 범위를 넘음 (피드백 4) |
| 10 계수·탐색 기록 | 충족 |

## 3. 피드백 (심각도 순, 줄 번호는 `badd552` 기준)

### 높음

1. **`src/jupjup/search/relevance.py:80-96`, `src/jupjup/config.py:153`, `src/jupjup/config.py:155` — 범용어 하나와 잡음 수준 의미 점수로 "corroborated"가 되어 negative가 통과한다 (recorded test FAIL의 주원인).**
   `semantic >= 0.30`은 bge-m3 raw cosine 약 0.33에 해당한다. 관련 없는 한국어 문서끼리도 raw 0.40~0.45가 흔하므로, 이 조건은 사실상 항상 참이다. 여기에 `original_lexical > 0`(3개 중 1개 일치)만 더해지면 `corroborated`로 분류되고 `βx` 보너스까지 받는다. lexical-only 문턱 0.30도 키워드 1/3 일치면 통과한다.
   직접 진단한 recorded 결과:
   - test `뉴욕 브루클린 맛집`: `맛집`만 일치, sem 0.50, R 0.67, corroborated로 통과
   - test `낚시 포인트 추천`: `추천`만 일치, R 0.61~0.76, 5건
   - test `테니스 라켓 추천`: lexical-only R 0.32 > 0.30
   - test `아프리카 사파리 여행`: `여행`만 일치
   - dev에도 같은 패턴이 있다: `보드게임 추천` 5건, `미얀마 여행 일정`, `북극곰 다큐`

   test 실패 4건 중 3건(q_0190, q_0196, q_0207)은 v2 이전에는 empty였다. 즉 v2가 새로 만든 오탐이다. mock alice의 `낚시 포인트 추천`도 Loop 3의 empty에서 오탐으로 바뀌었다. dev true-empty가 정확히 0.80 경계에 걸린 점까지 보면 문턱이 dev에 과적합됐다고 본다.
   **개선:** corroboration의 의미 신호 기준을 model별 무관 문서 분포(잡음 바닥)보다 높게 calibration한다. 원형 coverage가 낮은 단일 범용어 일치는 독립 증거로 세지 않는다. 예: 질의 핵심어 coverage 하한, 또는 문서 빈도가 높은 범용어(`추천/맛집/여행/정리`)의 가중 축소. dev의 같은 패턴(q_0206, q_0199, q_0203)을 근거로 조정하고 test 결과로는 튜닝하지 않는다.

2. **`src/jupjup/search/relevance.py:98-108`, `src/jupjup/search/service.py:332`, `src/jupjup/search/service.py:431-434` — 시그모이드 포화 때문에 강한 incumbent가 있으면 기간 완화가 불가능하다 (새 과소 완화).**
   q_0117 `지지난주 성수 카페 약속`의 정답 `c_alice_0140`(9/25 저장, 창보다 3일 앞, 카톡)은 R 0.998이다. 증거는 ol 0.67, cl 1.0, sem 0.91이다. strict 1위 `c_alice_0031`("성수 센터커피 라떼", ol 0.33)도 R 0.977로 포화돼 있다. 둘의 ΔR 0.021은 비용 0.06 + Δmin 0.05에 못 미친다. 그 전에 계획 내 `U` 정렬에서부터 0031이 위에 오므로 시도 결과는 `same_top`이다.
   v2 이전 R@10 1.0이던 이 질의가 두 mode에서 0.0이 됐다. dev temporal R@10도 0.987에서 0.933으로 내려갔다. 설계 5.3절의 "핵심 증거 향상이 비용보다 크면 채택"이 R 상단 구간에서는 성립하지 않는다.
   **개선:** 상단이 포화되지 않게 intercept와 계수를 다시 calibration하거나, 비교를 logit 또는 증거 공간에서 하도록 설계를 보완한다. 이 경우 Architect의 확인이 필요하다. q_0117형 "약한 same-facet incumbent + 기간 근접 강한 정답" 통합 테스트를 추가한다.

### 중간

3. **`src/jupjup/query/spell.py:58-65`, `src/jupjup/query/spell.py:80-83` — 교정 신뢰도가 상수이고, 2음절 교정을 일괄 금지해 오타 회귀가 생겼다.**
   모든 자동 spelling에 `confidence=0.95`와 고정 evidence 라벨 `("edit_quality", "frequency_margin")`을 붙인다. 설계 9.2절의 edit quality, frequency margin, context, semantic consistency 계산이 없다. 그래서 0.75~0.90 구간은 존재할 수 없고, 정상어 `아프리카→파프리카`도 0.95로 canonical에 들어간다 (recorded test q_0195 오탐의 한 원인).
   반대로 `len(term) <= 2`로 2음절 한국어 교정을 모두 막았다. 그 결과 `추쳔→추천`이 사라지고(q_0057 0.5), `기휴→기후`가 사라져 mock test q_0038 `기휴변화 논문`이 false-empty가 됐다. typo 카테고리는 mock dev 0.95→0.90, mock test 1.0→0.875, recorded test 1.0→0.9375로 내려갔다. 설계 PM 정책은 "vocabulary에 없다는 이유만으로 자동 대체하지 않는다"이지 일괄 금지가 아니다.
   **개선:** 설계 9.2절의 신뢰도를 실제로 계산하고, 명시적 오타 사전과 강한 문맥 근거가 있으면 2음절도 허용한다. `추쳔`, `기휴변화`, `아프리카` 이해 스냅샷을 회귀로 고정한다.

4. **`src/jupjup/search/service.py:368-380` — 계획 선택 tie-break가 "최소 계획"이 아니라 plan_id 문자열 순서다.**
   S7에서는 `time_window_expanded`, `time_filter_dropped`, `+platform` 조합이 모두 같은 1위(0136)로 채택된다. 그러면 U/R/위반 수/비용이 모두 같아서 마지막 키인 plan_id 문자열로 정한다. `"time_filter_dropped" < "time_window_expanded"`라서 **더 넓은 기간 제거 계획**이 선택된다.
   그 결과 "지난주" 질의에 2025-11-12 저장물(`c_alice_0150`, `0119`, recorded는 `0144`까지)이 함께 반환된다. 정작 `applied_relaxations`에는 `time_window_expanded`만 남는다. 두 mode의 q_0083과 ch_0007에서 재현했다.
   설계 6.2절 7단계는 "통과한 최소 계획 하나를 선택"이다. 결과별 `relaxed_facets`는 정확하므로 거짓 표시는 아니지만, 응답이 1위가 정당화한 범위를 넘는다. S7 테스트(`tests/integration/test_search_v0.py:113-123`)는 `all(item.relaxed)`만 보므로 이 문제를 잡지 못한다.
   **개선:** 동률이면 허용 변화 집합이 가장 작은 계획(포함 관계, 그다음 비용)을 고른다. "모든 결과의 `relaxed_facets` ⊆ 선택 계획의 최소 필요 집합" 테스트를 추가한다.

5. **통합 및 프로세스 — 구현 커밋이 PM에 병합되지 않은 채 검수 워크트리가 만들어졌다.**
   PM의 0.7333 확인도 v2 이전 코드의 값이었다. 이 상태로 PASS를 내면 PM 브랜치에는 v2 코드가 없는 채로 끝난다. 사용자에게 알린 뒤 병합하는 절차대로 `badd552`(또는 수정본)를 PM에 병합하고, 다음 검수 워크트리는 그 병합 커밋을 베이스로 만들어야 한다.

6. **`data/lexicon/synonyms.yaml:16`, `data/lexicon/synonyms.yaml:20-23` — 고정 회귀와 dev 개별 질의에 맞춘 동의어가 있고, 일부는 의미가 넓다.**
   `[하체, 다리]`를 빼면 12절 `다리 운동 영상`이 다시 실패한다. 즉 이 사례는 관련도 모델이 아니라 사전 항목으로 통과한다. 설계 13.1-3은 고정 회귀를 loss에 넣지 않는다고 했다.
   `[베이킹, 굽기, 굽다, 굽는]`(q_0178용)은 `고기 굽는 영상`을 베이킹/레시피 문서로 보낸다. `[디저트, 후식, 케이크]`와 `[투자, 주식]`(q_0176용)은 상하위어를 동치로 묶어 양방향으로 넓힌다.
   **개선:** 동의어는 동치어만 두고, 상하위어는 한 방향 확장이나 낮은 confidence 확장으로 분리한다. 추가할 때마다 어느 dev 질의가 근거인지 보고서에 남긴다.

### 낮음

7. **`tests/unit/test_relevance.py:79-87` — INV-02/14 테스트가 동어반복이다.** 같은 doc에 같은 raw 점수와 같은 필터(deep copy)를 넣고 결과가 같은지만 본다. 보고서는 "계획, 후보 순서, 현재 시각 변화에도"라고 주장하지만 그런 변형이 없다. INV-14(RRF, recency, now)도 서비스 경로에서 검증하지 않는다. 서로 다른 요청 잠금, limit, now로 검색해 같은 ID의 `R`을 비교하는 통합 테스트가 필요하다 (이번 진단에서 468쌍 차이 0은 확인했다).
8. **`src/jupjup/search/service.py:241`, `src/jupjup/query/understanding.py:197`, `src/jupjup/query/understanding.py:220` — 설계 계약을 일부만 구현했다.**
   - semantic은 vector top-`n_vec`에 든 문서에서만 값을 얻고, 나머지는 0이다. 지금 코퍼스 크기에서는 영향이 없지만, 문서가 늘면 같은 q/doc의 `R`이 후보 경쟁에 따라 달라질 수 있다. 후보 합집합에 대해 직접 cosine을 계산하는 쪽을 권한다.
   - `semantic_text_augmented`는 만들기만 하고 어디서도 쓰지 않는다.
   - `query_signal_profile`은 원형 토큰이 전부 OOV이거나 저신뢰 교정인 경우(설계 7.1절)를 low-signal로 보지 않는다.
   - explain debug가 결과 항목에만 붙어서, 결과가 비면 시도한 계획과 거부 사유를 볼 수 없다 (설계 8.2절).
9. **`src/jupjup/eval/harness.py:295`, `src/jupjup/eval/harness.py:399` — status별 지표는 여전히 분모가 0이면 1.0을 채운다.** 제품 evidence는 `MetricObservation`이 막고 있어 거짓 PASS는 나오지 않는다. 다만 `review_status_gates["human_reviewed"]`의 절대 게이트 표시는 여전히 vacuous pass가 될 수 있다. 분모가 0이면 `None`과 `not_evaluated`로 통일하는 것이 설계 10.1절과 맞다.
10. **`src/jupjup/config.py:158` — `return_tail_margin=0.60`은 0..1 척도에서 꼬리 절단을 사실상 끈다.** 위 피드백 1의 오탐이 여러 건 반환되는 데도 영향을 준다. 피드백 1을 고친 뒤 다시 조정한다.

## 4. 채점 근거

- **정확성 30 / 40:** 12절 고정 회귀 8건, 요청 잠금, 이중 facet 기록, 원형 보존, challenge 지표, 결정성은 직접 확인했다. 하지만 인수 기준 6번(recorded test 절대 기준)을 충족하지 못했다. 원인은 test 표본 운이 아니라 피드백 1의 구조 결함이며, dev에도 같은 패턴이 있다. 이에 더해 포화로 인한 기간 과소 완화(q_0117 1.0→0.0), 2음절 교정 일괄 금지로 인한 오타 회귀와 mock false-empty, 최소 계획이 아닌 계획 선택이 새로 생겼다.
- **안전성 28 / 30:** 요청 잠금(계획 단계와 postcondition), 사용자 격리, 입력 검증, 오류 정제, mode 불일치 기준선 보호, human 제품 evidence의 분모와 메타데이터 보호를 모두 직접 확인했다. 감점은 status gate의 vacuous 1.0 잔존, 그리고 선택 계획 범위를 넘는 결과가 전역 기록에 드러나지 않는 점이다.
- **유지보수성 23 / 30:** `relevance.py` 분리, 불변 계획, 타입화된 decision, `extra="forbid"`, 520개 테스트, ruff/mypy, test를 재튜닝하지 않은 정직한 보고는 강점이다. 감점 사유는 다음과 같다.
  - 실제 계산 없이 상수로 둔 교정 신뢰도와 가짜 evidence 라벨
  - 쓰지 않는 필드
  - 동어반복 불변식 테스트
  - 문자열 tie-break
  - 고정 회귀를 사전 항목으로 맞춤
  - 구현이 PM에 통합되지 않아 기준 브랜치에서 검증할 수 없었던 점

사람 검수 0건 자체는 감점하지 않았다. 범위 밖 항목(T15 API, LLM, 인제스트)도 보지 않았다.

## 5. 재검수 조건

1. 수정된 v2 구현이 PM 브랜치에 병합되고, 재검수 워크트리가 그 커밋을 포함한다.
2. 피드백 1: corroboration과 lexical-only 판정을 잡음 바닥 이상으로 고친다. dev의 q_0206, q_0199, q_0203형 오탐이 empty가 되고, recorded dev true-empty가 경계값이 아닌 여유를 두고 0.80 이상이며, false-empty ≤ 0.03과 challenge positive R@10 ≥ 0.9091을 유지한다.
3. 피드백 2: q_0117이 정답 `c_alice_0140`을 반환하고, 같은 형태의 통합 테스트가 있다. 기존 12절 8건과 q_0173 "약한 facet 위반 후보는 밀어내지 못함"이 계속 통과한다.
4. 피드백 3: 교정 신뢰도를 실제로 계산하고, `추쳔`, `기휴변화` 복구와 `아프리카` 미교정을 테스트로 고정한다. 동시에 `다리` 미교정과 `이주` 보호를 유지한다.
5. 피드백 4: 동률이면 최소 계획을 선택한다. S7 결과에 `time_filter_dropped` 문서가 없어야 하고, 결과별 `relaxed_facets`가 선택 계획 범위 안에 있는지 확인하는 테스트가 있다.
6. 피드백 6: 동치가 아닌 동의어를 정리한다. `[하체, 다리]`를 남긴다면 근거를 보고서에 적고, 사전 항목 없이도 다리 사례가 어떻게 되는지 함께 보고한다.
7. **blind test 처리 (PM과 사용자 결정 필요):** 현재 test split은 설계 13.1-6에 따라 이미 소비됐다. 수정 후 기술 PASS 판정을 (a) 새로 동결한 test v2로 할지, (b) 현재 test를 회귀 확인용으로만 다시 쓸지 결정해 기록한다. (b)라면 test의 개별 실패 질의로 계수나 사전을 조정하지 않았음을 보고서에 명시한다.
8. ruff, mypy, 전체 pytest, eval validate, mock/recorded dev/test와 기준선 비교를 모두 다시 실행한다.

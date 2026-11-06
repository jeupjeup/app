# Phase 2 완화 정책 v2 구현 보고서

- 작성일: 2026-10-30
- 작업 브랜치: `phase-2-relaxation-v2`
- 설계 기준: `specs/design_relaxation_v2.md`
- 최종 판정: **구현 및 정적/테스트/live 검증 완료, 전체 완료 게이트는 미달**
- 미달 사유: T11의 recorded test에서 `true_empty_rate=0.6000 < 0.8000`

test split은 설계 13.1절에 따라 파라미터 동결 후 T11에서 mode별 한 번만 실행했다. recorded test
실패 뒤에는 test 결과로 점수·게이트를 재튜닝하거나 test aggregate를 재실행하지 않았다. 따라서 이
브랜치는 기술 구현 결과를 커밋하지만 제품 PASS를 선언하지 않는다.

## 1. T번호별 구현

| T | 구현 및 검증 결과 |
|---|---|
| T0 | 기존 mock/recorded dev와 12절 고정 사례를 스냅샷하고, 고정 사례를 먼저 RED로 만들었다. 후보의 원자 특징, `R/C/U`, 게이트 사유, 계획별 채택/거부를 debug에 노출했다. test aggregate는 실행하지 않았다. |
| T1 | `CandidateEvidence`, `GateDecision`, `RelaxationPlan`, `RelaxationDecision`, canonical relaxation order, `relaxed_facets`를 추가했다. 관련도/게이트/완화 설정은 `extra="forbid"`로 unknown 설정을 거부한다. |
| T2 | `search/relevance.py`에 계획·순위·현재 시각과 무관한 단일 로지스틱 관련도 `R(q,d)`를 구현했다. bge/hash calibration version과 원형/정규형 lexical, phrase, purpose, corroboration을 증거로 보존했다. RRF와 recency는 관련도 경계에서 제거했다. |
| T3 | 원형 용어와 원형 semantic query를 불변 보존하고, 교정은 confidence/evidence를 가진 확장으로 변경했다. Latin 자동 spelling과 짧은 한국어 자동 대체를 보수화했다. `다리→자리` 오교정을 차단하고 recorded 원형 질의 embedding 23개를 보충했다. |
| T4 | 매 단계의 이전 상태가 아니라 q0 원본에서 모든 원자 조합의 불변 계획을 생성한다. 계획 생성 시 요청 플랫폼·유형·기간 잠금을 검증하며 중복 계획을 제거한다. |
| T5 | 모든 계획의 후보 ID 합집합을 만든 뒤 문서당 `R`을 한 번 계산한다. 실제 질의 facet 위반 비용 `C`와 단일 경계 `ΔR > ΔC + Δmin + epsilon`으로 strict/incumbent와 challenger를 선택한다. |
| T6 | evidence profile과 query signal profile별 절대 `RelevanceGate`를 구현했다. semantic floor, correction-only 거부, 고정 tail margin을 적용하고 기존 OR 조건과 rank/recency 의존 게이트를 검색 경로에서 제거했다. |
| T7 | 계획 이름이 아니라 선택 문서의 실제 위반에서 `applied_relaxations`, 결과별 `relaxed`, `relaxed_facets`를 계산한다. 빈 결과는 시도한 계획이 있어도 `applied_relaxations=[]`다. 최종 결과 직전에 요청 잠금 postcondition을 다시 검증한다. |
| T8 | human-reviewed 지표를 `MetricObservation`으로 바꾸고 최소 분모를 적용했다. 분모 0은 `null/not_evaluated`이며 제품 evidence는 false다. total/dev/test review count와 overall/dev/test kappa를 분리하고, eligible evidence 없이는 human 기준선을 갱신할 수 없게 했다. |
| T9 | recorded dev만 사용해 게이트와 관련도 계수를 순서대로 탐색했다. 동결값은 corroborated 0.60, semantic-only 0.55, lexical-only 0.30, low-signal 0.58, semantic floor 0.60, tail margin 0.60, `βoriginal=3.0`, `Δmin=0.05`다. |
| T10 | mock dev는 의미 계수 튜닝 없이 구조/결정성/기본 안전 회귀만 확인했다. ruff, mypy, 비-embed pytest, eval validate와 두 dev 평가가 PASS했다. |
| T11 | 동결 후 mock test와 recorded test를 각 1회 실행했다. mock test는 PASS, recorded test는 true-empty 절대 기준 하나로 FAIL했다. test 결과를 이용한 재튜닝이나 재실행은 하지 않았다. |

## 2. 불변식 테스트 목록

| ID | 고정 테스트 |
|---|---|
| INV-01 | `test_inv01_request_locks_are_in_every_plan_and_final_results`; 계획 hard filter와 최종 결과를 모두 검사 |
| INV-02, 14 | `test_inv02_inv14_relevance_is_context_independent`; 계획/후보 순서/현재 시각 변화에도 동일 q/doc의 `R` 확인 |
| INV-03~06 | `test_inv03_to_inv06_single_adoption_boundary`; same-ID, tie, 약한/강한 challenger를 같은 경계 함수로 확인 |
| INV-07, 08 | `test_inv07_inv08_immutable_atomic_plans`; 원본 기반 원자/복합 계획과 실제 위반 기록 확인 |
| INV-09 | `test_inv09_inv12_rejected_attempts_leave_empty`; 거부된 시도는 applied가 아님을 확인 |
| INV-10 | `test_inv10_original_survives_canonicalization`; `다리` 원형/semantic original 보존과 `자리` 미교정 확인 |
| INV-11 | `test_inv11_correction_only_cannot_pass`; 교정 증거만 있는 후보 거부 |
| INV-12 | `test_inv12_semantic_only_floor_is_absolute`; semantic-only 절대 floor 확인 |
| INV-13 | `test_inv13_recorded_cross_language_and_hard_negative`; recorded ch_0003 top-1/top-3와 ch_0011/12 empty 확인 |
| INV-15 | `test_inv15_relaxed_flag_equals_actual_facets`; `relaxed == bool(relaxed_facets)` 확인 |
| INV-16 | `test_inv16_time_cost_is_mutually_exclusive`; 기간 expanded/dropped 기록 및 비용 상호 배타 확인 |
| INV-17 | `test_inv17_zero_denominator_is_not_evaluated`; 분모 0의 null/eligible=false 확인 |
| INV-18 | `test_inv18_total_and_split_metadata_are_independent`; total/dev/test count 독립 검증 |
| INV-19 | 기존 `test_baseline_update_refuses_mode_mismatch`; mode 불일치 시 실패와 파일 바이트 불변 확인 |
| INV-20 | `test_recorded_replay_is_deterministic`; 비결정 필드 제외 recorded dev byte-equivalent 확인 |

추가로 `test_request_filter_respected_in_results`, `test_request_filter_overrides_query`,
`test_request_window_overrides`가 요청 잠금의 외부 API 동작을 고정한다.

## 3. 고정 회귀 사례

모든 사례는 limit 1/2/10/50 parametrization으로 고정했다.

| 사례 | 결과 |
|---|---|
| S7/q_0083 `지난주 카톡으로 받은 회의 장소` | `c_alice_0136`, `time_window_expanded`만 기록, PASS |
| q_0173 `레스토랑 추천 블로그` | `c_alice_0153`, 완화 없음, PASS |
| q_0167 `다리 운동 영상` | `c_alice_0040`, 완화 없음, 원형 보존, PASS |
| `경주 맛집 인스타` | `c_alice_0153`, 플랫폼만 완화, PASS |
| `하체 운동 유튜브` | `c_alice_0040`, 플랫폼만 완화, PASS |
| `경주 맛집 카톡 논문` | `c_alice_0153`, 플랫폼→유형 canonical order로 정확히 두 항목, PASS |
| ch_0003 `assignment에 쓸 climate crisis paper` | recorded `c_alice_0096` 1위 및 관련 ID top 3, content type 유지, PASS |
| ch_0011/12 화성 이주 다큐 hard negative | empty, 완화 없음, PASS |

## 4. recorded dev 튜닝 기록

절대 기준을 낮추지 않았고 test aggregate는 보지 않았다. 첫 v2 통합 결과는 recall@10 0.9224,
true-empty 0.4000이었다. 요청 origin 판정, purpose 증거, 원형 보존과 실제 위반 계산을 먼저 수정한 뒤
다음 순서로 recorded dev만 탐색했다.

| 항목 | 탐색값 | recorded dev 관찰 | 선택 |
|---|---|---|---|
| corroborated gate | 0.55 / 0.60 / 0.65 | recall@10 0.9630 / 0.9588 / 0.9546; true-empty 0.6667 / 0.8000 / 0.8000 | 0.60 |
| lexical-only gate | 0.15~0.45 | 0.25 이하는 true-empty 0.7333; 0.30 이상 0.8000 | 0.30 |
| `βoriginal` | 2.8 / 2.9 / 3.0 / 3.1 / 3.2 / 3.6 | 3.0까지 true-empty 0.8000; 3.1부터 0.6667 이하 | 3.0 |
| tail margin | 0.18 / 0.30 / 0.45 / 0.60 | recall@10 0.9504 / 0.9546 / 0.9588 / 0.9588; true-empty 모두 0.8000 | 0.60 |
| 구조적 어휘 | `하체/다리`, `과제/assignment`, `투자/주식`, 디저트·베이킹 표기 | fixed regression 및 recorded dev를 먼저 재검증; 최종 recall@10 0.9706 | 유지 |

최종 완화 비용은 설계 기본값인 기간 확대 0.06, 기간 제거 0.14, 플랫폼 0.12, 유형 0.10을
유지했고 `Δmin=0.05`, `epsilon=1e-6`도 낮추지 않았다.

## 5. 평가 지표와 이전 기준선 비교

### Mock

| 지표 | dev 이전 | dev 현재 | Δ | test 이전 | test 현재 | Δ |
|---|---:|---:|---:|---:|---:|---:|
| Recall@10 | 0.9657 | 0.9574 | -0.0083 | 0.9697 | 0.9687 | -0.0010 |
| Recall@5 | 0.9434 | 0.9326 | -0.0108 | 0.9545 | 0.9574 | +0.0029 |
| MRR@10 | 0.9921 | 0.9874 | -0.0047 | 0.9759 | 0.9867 | +0.0108 |
| nDCG@10 | 0.9754 | 0.9695 | -0.0059 | 0.9674 | 0.9739 | +0.0065 |
| Success@1 | 0.9843 | 0.9832 | -0.0011 | 0.9639 | 0.9867 | +0.0228 |
| category Recall@10 min | 0.8856 | 0.8921 | +0.0065 | 0.9167 | 0.8650 | -0.0517 |
| true-empty | 0.7333 | 0.7333 | 0.0000 | 0.8000 | 0.9000 | +0.1000 |
| false-empty | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0120 | +0.0120 |
| time/platform/type | 1.0000 | 1.0000 | 0.0000 | 1.0000 | 1.0000 | 0.0000 |
| keyword inclusion | 0.9748 | 0.9496 | -0.0252 | 0.9333 | 0.9200 | -0.0133 |
| 최종 gate | PASS | **PASS** |  | PASS | **PASS** |  |

### Recorded

| 지표 | dev 이전 | dev 현재 | Δ | test 이전 | test 현재 | Δ |
|---|---:|---:|---:|---:|---:|---:|
| Recall@10 | 0.9665 | 0.9706 | +0.0041 | 0.9820 | 0.9820 | 0.0000 |
| Recall@5 | 0.9497 | 0.9471 | -0.0027 | 0.9707 | 0.9641 | -0.0067 |
| MRR@10 | 1.0000 | 0.9916 | -0.0084 | 0.9867 | 0.9911 | +0.0044 |
| nDCG@10 | 0.9793 | 0.9763 | -0.0030 | 0.9808 | 0.9882 | +0.0075 |
| Success@1 | 1.0000 | 0.9916 | -0.0084 | 0.9733 | 0.9867 | +0.0133 |
| category Recall@10 min | 0.8801 | 0.8947 | +0.0146 | 0.9375 | 0.9150 | -0.0225 |
| true-empty | 0.7333 | 0.8000 | +0.0667 | 0.9000 | **0.6000** | -0.3000 |
| false-empty | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| time/platform/type | 1.0000 | 1.0000 | 0.0000 | 1.0000 | 1.0000 | 0.0000 |
| keyword inclusion | 0.9832 | 0.9496 | -0.0336 | 0.9333 | 0.9200 | -0.0133 |
| 최종 gate | FAIL(당시 dev true-empty) | **PASS** |  | PASS | **FAIL** |  |

두 mode 모두 isolation/filter violations는 0이고 browse precision/sort/filter compliance는 1.0이다.
기존 대비 모든 지표가 동등 이상인 경우에만 기준선을 갱신한다는 조건을 만족하지 않으므로
`data/baselines/mock.json`과 `data/baselines/recorded.json`은 갱신하지 않았다. 기준치도 낮추지 않았다.

## 6. known issues 1~4 해결 현황

| 번호 | 상태 | 해결 내용 |
|---|---|---|
| 1 | 해결 | 요청 facet 절대 잠금 + 질의 facet의 비용 기반 단일 채택 경계; 두 과소 완화 사례 회귀 고정 |
| 2 | 해결 | 선택 문서의 실제 위반에서 플랫폼/유형을 독립적으로 기록 |
| 3 | 해결 | 분모 기반 eligibility와 total/split metadata 독립 검증, human baseline 갱신 보호 |
| 4 | 해결 | 원형 증거 불변 보존, 교정 신뢰도 보수화, `다리→자리` 방지 및 1위 회귀 고정 |

상세 상태는 `specs/known_issues.md`에도 갱신했다.

## 7. 최종 검증

| 명령 | 결과 |
|---|---|
| `uv run ruff check .` | PASS |
| `uv run mypy src` | PASS (52 source files) |
| `uv run pytest -m 'not embed'` | PASS (520 passed, 1 deselected) |
| `uv run jupjup eval validate` | PASS (seeds 200, queries 259, lexicon 139) |
| `uv run jupjup eval run --mode mock --split dev ...` | PASS |
| `uv run jupjup eval run --mode recorded --split dev ...` | PASS |
| `uv run jupjup eval run --mode mock --split test ...` | PASS |
| `uv run jupjup eval run --mode recorded --split test ...` | **FAIL: true-empty 0.6000 < 0.8000** |
| 지정 캐시로 `uv run --extra embed pytest -m embed` | PASS (1 passed, 520 deselected) |

human-reviewed 데이터는 아직 0건이므로 기술 게이트와 별개로 제품 evidence `eligible=false`가 정상이다.

## 8. 남은 문제

1. recorded test negative 10건의 true-empty가 6/10으로 절대 기준 8/10을 충족하지 못했다. 다른 모든
   recorded test 절대/회귀 지표는 통과했다.
2. 이 test 결과는 blind final로 이미 소비되었으므로 현 test split을 보고 게이트를 조정해 PASS를
   만들 수 없다. 설계 13.1절에 따라 별도 dev 이슈로 등록하고 새로운 blind test v2를 마련한 뒤에만
   제품 PASS를 다시 판단해야 한다.
3. human-reviewed 표본·검수자·kappa가 아직 없으므로 제품 evidence는 계속 ineligible이다.

# Phase 2 완화 정책 v2 사이클 — Loop 2/3 수정 보고서

- 대상 브랜치: `phase-2-cycle2-loop2-fixes`
- 기준 검수: `specs/phase4_review_cycle2_loop1.md` (81점, REJECT)
- 결론: **부분 PASS / 전체 완료 조건 미달**
- 기준선: mock/recorded 기준선 모두 미갱신

recorded test의 직접 실패였던 `true_empty_rate=0.6000`은 `1.0000`으로 해결했다. 다만 동결 후
test 회귀 확인에서 mock/recorded 랭킹 지표가 기존 기준선보다 하락했고, 전체 `pytest`의 mock
`split=all` 회귀 게이트도 실패했다. test 결과를 본 뒤 설정을 다시 조정하지 않았다.

## 1. 피드백별 조치

| # | 상태 | 조치 및 확인 |
|---:|---|---|
| 1 | 완료 | 범용어(`추천/맛집/여행/일정/다큐/정리` 등)를 핵심 lexical coverage에서 제외하되, 범용어만 있는 짧은 질의는 기존 검색을 유지했다. semantic/lexical/phrase를 독립 증거처럼 중복 계산하지 않고 모델별 잡음 floor를 적용했다. recorded dev의 q_0199, q_0203, q_0206과 challenge negative 2건은 모두 empty이며, recorded dev true-empty는 0.8667이다. recorded test true-empty도 1.0000이다. |
| 2 | 완료 | 기존 로지스틱 계수의 비율을 보존하며 0.35배로 축소해 상단 포화를 줄였다. q_0117은 두 mode에서 `c_alice_0140`을 1위로 반환하고 `time_window_expanded`만 기록한다. q_0173과 설계 12절 사례도 회귀 테스트로 유지했다. |
| 3 | 부분 완료 | 자동 교정 confidence를 edit quality, 1·2위 frequency margin, 실제 문서 공기 context support로 계산한다. 명시적 오타 `추쳔→추천`, `기휴변화→기후변화`와 보호어 `이주`, Latin 비활성, `아프리카`/`다리→자리` 미교정을 테스트했다. `추쳔`은 mock dev에서 복구됐고 recorded test의 `기휴변화`는 관련 2건을 반환하지만, mock test의 q_0038은 여전히 false-empty다. |
| 4 | 완료 | 계획 동률 시 허용 relaxation 수와 계획 범위 비용을 먼저 비교해 최소 계획을 고른다. S7은 `time_window_expanded` 계획을 선택하며 반환 결과에 `time_filter_dropped` 문서가 없다. 모든 결과의 `relaxed_facets`가 선택 계획 범위 안인지 테스트한다. |
| 5 | PM 완료 | 병합 누락은 PM이 조치했으며 이 루프에서 별도 코드 작업을 하지 않았다. 현재 워크트리는 병합된 v2 구현을 포함한다. |
| 6 | 완료 | 동치가 아닌 `[디저트, 후식, 케이크]`, `[투자, 주식]`, `[베이킹, 굽기, 굽다, 굽는]`, `[하체, 다리]` 그룹을 제거했다. dev 근거가 있는 `다리→하체`, `주식→투자`만 confidence 0.90의 단방향 확장으로 남겼다. `다리 운동 영상`은 양방향 동의어 없이도 두 mode에서 `c_alice_0040` 1위다. |
| 7 | 완료 | 서로 다른 `limit`, `now`, 요청 플랫폼 잠금으로 서비스 검색을 실행하고 동일 q/doc의 `R` 차이가 `1e-6` 이내인지 검증하는 통합 테스트를 추가했다. |
| 8 | 완료 | 질의 embedding을 요청당 한 번 계산하고 후보 합집합 전체에 `vector.similarities`를 직접 적용한다. augmented text는 n-gram recall 확장에 사용한다. 전부 OOV인 질의는 low-signal로 분류하며, empty 응답도 top-level explain debug에서 계획별 거부 사유를 제공한다. |
| 9 | 완료 | review status별 분모가 0인 ranking/browse/negative/understanding 지표는 `None`으로 기록하고 status gate에서 `not evaluated` 실패로 처리한다. human-reviewed 0건은 계속 `eligible=false`다. |
| 10 | 완료 | 구조적 오탐 차단 후 `return_tail_margin`을 0.60에서 0.40으로 줄였다. |
| PM live 데모 | 완료 | `create_demo_app`의 live 기본 녹화 경로를 tracked `data/recordings`가 아닌 `var/recordings/demo.embeddings.bge-m3.jsonl`로 강제했다. 명시적 recording path는 보존하며 CLI/데모 테스트로 경로를 고정했다. tracked 녹화 파일은 변경되지 않았다. |

## 2. 최종 설정과 dev 탐색

test aggregate를 보기 전 recorded dev에서 다음 순서로 동결했다.

1. 교정: 상수 0.95를 제거하고 edit/frequency/context confidence 및 curated typo를 적용
2. 증거: 핵심어 coverage, 모델별 semantic evidence floor, correction-only 차단
3. 관련도: 기존 계수 비율을 0.35배로 축소해 sigmoid 포화를 완화
4. lexical evidence floor: `0.50 → 0.45 → 0.40` 탐색
5. tail: 구조적 게이트 수정 후 `0.60 → 0.40`

최종 값:

| 항목 | 값 |
|---|---:|
| `βsemantic / βoriginal / βcanonical` | `1.40 / 1.05 / 0.77` |
| `βphrase / βpurpose / βcorroboration` | `0.28 / 0.35 / 0.21` |
| intercept | `-1.05` |
| corroborated / semantic-only / lexical-only threshold | `0.45 / 0.55 / 0.44` |
| bge/hash semantic-only floor | `0.60 / 0.85` |
| lexical evidence floor | `0.40` |
| canonical/phrase evidence discount | `0.50 / 0.50` |
| tail margin | `0.40` |
| facet 비용 / minimum gain | 기존 `0.06/0.14/0.12/0.10`, `0.05` 유지 |

lexical floor 0.40의 recorded dev 결과는 Recall@10 0.9681, true-empty 0.8667,
false-empty 0.0000이었다. q_0199/q_0203/q_0206은 모두 empty였고 challenge positive dev
Recall@10은 0.9405였다.

## 3. 지표 전후

### Recorded

| 지표 | dev 수정 전 | dev 수정 후 | test 수정 전 | test 수정 후 |
|---|---:|---:|---:|---:|
| Recall@10 | 0.9706 | 0.9681 | 0.9820 | 0.9440 |
| Recall@5 | 0.9471 | 0.9474 | 0.9641 | 0.9261 |
| MRR@10 | 0.9916 | 1.0000 | 0.9911 | 0.9644 |
| nDCG@10 | 0.9763 | 0.9816 | 0.9882 | 0.9523 |
| category Recall@10 min | 0.8947 | 0.8737 | 0.9150 | 0.8125 |
| true-empty | 0.8000 | **0.8667** | **0.6000** | **1.0000** |
| false-empty | 0.0000 | 0.0000 | 0.0000 | 0.0120 |
| 최종 gate | PASS | **PASS** | FAIL (absolute) | **FAIL (regression)** |

### Mock

| 지표 | dev 수정 전 | dev 수정 후 | test 수정 전 | test 수정 후 |
|---|---:|---:|---:|---:|
| Recall@10 | 0.9574 | 0.9691 | 0.9687 | 0.9320 |
| MRR@10 | 0.9874 | 0.9958 | 0.9867 | 0.9600 |
| nDCG@10 | 0.9695 | 0.9801 | 0.9739 | 0.9401 |
| true-empty | 0.7333 | 0.9333 | 0.9000 | 1.0000 |
| false-empty | 0.0000 | 0.0000 | 0.0120 | 0.0241 |
| 최종 gate | PASS | **PASS** | PASS | **FAIL (regression)** |

challenge positive recorded Recall@10은 dev 0.9405(14건), test 0.6875(8건), 합산
0.8485(22건)로 요구치 0.9091에 미달했다. challenge negative는 모두 empty다.

## 4. 검증 결과

| 명령 | 결과 |
|---|---|
| `uv run ruff check .` | PASS |
| `uv run mypy src` | PASS (52 source files) |
| `uv run pytest` | **FAIL — 529 passed, 2 failed, 1 deselected**. 두 실패 모두 mock `split=all` Recall@10 회귀 게이트(0.954768 < 0.957262) |
| `uv run jupjup eval validate` | PASS — seeds 200, queries 259, lexicon cases 139 |
| mock dev | PASS — Recall@10 0.9691, true-empty 0.9333 |
| recorded dev | PASS — Recall@10 0.9681, true-empty 0.8667 |
| mock test | **FAIL — 절대 기준은 모두 통과, Recall/MRR/nDCG 회귀 기준 미달** |
| recorded test | **FAIL — 절대 기준은 모두 통과, Recall/MRR/nDCG 회귀 기준 미달** |

기존 기준선보다 모든 주요 지표가 동등 이상일 때만 갱신한다는 규칙을 충족하지 못해
`data/baselines/mock.json`과 `data/baselines/recorded.json`은 변경하지 않았다. 기준치도 낮추지 않았다.

## 5. 남은 문제

1. 완료 조건의 `pytest`, mock test, recorded test가 PASS가 아니다. test의 true-empty 문제는 해결했지만
   랭킹 회귀로 실패 원인이 이동했다.
2. recorded challenge positive 합산 Recall@10이 0.8485로 0.9091 기준에 미달한다.
3. 명시적 `기휴변화→기후변화` 교정과 이해 스냅샷은 통과하지만 mock test q_0038은 여전히
   false-empty다. recorded test에서는 관련 2건을 반환한다.
4. 현재 test split은 이전 루프에서 이미 소비됐으며 이번에는 기존 계약의 회귀 확인용으로만 다시
   사용했다. test 실패 뒤 계수·사전·문턱을 다시 조정하지 않았다. 다음 품질 주장은 새 dev 이슈와
   별도 동결 test v2가 필요하다.
5. human-reviewed 데이터는 0건이므로 제품 evidence는 정상적으로 `eligible=false`다.

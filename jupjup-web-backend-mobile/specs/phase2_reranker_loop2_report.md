# Phase 2 리랭커 사이클 Loop 2 루프백 수정 보고서

- 기준: `specs/phase4_review_reranker_loop1.md` (88/100, REJECT)
- 정책: 순위 품질 판정은 recorded(bge-m3). mock은 안전·절대 기준·결정성 검사용.
- 결론: 재검수 조건 1~7을 충족했다. 기준선·리랭커 계수·floor를 바꾸지 않았고
  재튜닝하지 않았다. A/B 판정은 계속 `REJECT`, 기본값은 계속 꺼짐이다.

## 1. 피드백별 조치

| ID | 조치 | 검증 |
|---|---|---|
| R1 | torch 없이 호출 가능한 제네릭 항등 함수를 `activation_fn`으로 전달했다. 가짜 모델 출력 검증은 optional dependency를 import하지 않는다. | 기본·extra 각각 pytest 611 passed, mypy 통과 |
| R2 | `ABComparison.fixed_regressions`를 추가해 9.1절 고정 회귀를 규칙 1에서 계산한다. 지표·카테고리·test 확인이 빠지면 fail-closed한다. | recorded dev A1: `failed=['다리 운동 영상(c_alice_0051)']`, 규칙 7 미제공으로도 REJECT |
| M1 | live에서 예측 장치가 cpu이고 `enabled_on_cpu=false`면 모델 생성 전에 중단한다. warm-up의 `RerankerError`도 `required=false`면 경고 후 v2로 시작한다. | 모델 생성 미호출·optional/required 분기 단위 테스트 |
| M2 | `timeout`, `error`, `busy`만 `degraded_reasons`에 넣고 `cpu_disabled`, `empty_query`는 `rerank_status`에만 남긴다. | 두 정책 skip의 `degraded=false` 테스트 |
| M3 | INV-R2에 `now`만 다른 요청과 request platform lock이 다른 요청을 추가했다. 두 실행에서 모두 채점된 문서의 `cross`, `R` 차이는 1e-6 이하였다. | `test_cross_and_relevance_ignore_*` 2건 |
| M4 | 기존 보고서의 A0를 “HEAD + 리랭커 off”로 바로잡고 `c7da005` 대비 q_0176·q_0127 변화를 추가했다. | `specs/phase2_reranker_report.md` 2.2절 |
| M5 | F2를 “미해결”로 바꾸고 기본 v2가 cosine floor 0.61을 쓴다는 현재 상태와 다음 대안을 적었다. | `specs/known_issues.md` 6절 |
| L1 | `RecordedReranker` 재생은 단일 비행 실행기·wall-clock timeout을 거치지 않고 동기 조회한다. 녹화 미스는 그대로 예외다. | executor 미호출·cache miss 테스트 |
| L2 | v3 전용 `anchored_tail_threshold` 설정을 추가했다. 현 값 0.44는 오래된 튜닝값을 변경하지 않고 명시적으로 분리한 것이다. | 기존 anchored-tail 회귀 통과 |
| L3 | 재평가 전 “v3 + cross 무시” 진단은 남은 과제로 유지했다. 이번 루프에서는 재튜닝하지 않았다. | 현 A/B REJECT 유지 |
| L4 | 골든 밖 request-lock·격리 CLI 쌍 녹화 보강은 채택 재평가 전 과제로 남겼다. 기존 녹화본의 범위를 확장하거나 갱신하지 않았다. | 녹화·골든 diff 없음 |
| L5 | `다리` 사전 항목 제거 진단은 재평가 전 과제로 유지했다. 현 사전·테스트를 바꾸지 않았다. | 사전 diff 없음 |
| L6 | 새 `RecordingReranker` 행에 실제 `device`, `dtype`를 메타로 남긴다. 기존 녹화본과 pair hash는 하위 호환을 위해 변경하지 않았다. | 원문 미저장·메타 스키마 테스트 |

## 2. 지표 전후

### 2.1 정적 게이트

| 환경 | Loop 1 재현 | Loop 2 |
|---|---|---|
| 기본 설치 `pytest` | 1 failed, 601 passed, 3 deselected | **611 passed, 3 deselected** |
| 기본 설치 `mypy src` | 1 error (`no-any-return`) | **Success, 56 files** |
| 기본 설치 `ruff check src tests` | PASS | **PASS** |
| rerank extra `pytest` | 602 passed (직전 구현 기준) | **611 passed, 3 deselected** |
| rerank extra ruff / mypy | PASS / PASS | **PASS / PASS** |

신규 테스트 9건은 R2 fail-closed 2건, M1 2건, M2 2건, M3 2건, L1 1건이다.
기존 R1 출력 검증 1건도 수정 후 통과했고, 기존 녹화 스키마 테스트에 device/dtype 검증을 보강했다.

### 2.2 품질 지표 (기본·extra 동일, 모두 PASS)

| mode/split | Recall@10 | nDCG@10 | category min | TE | FE |
|---|---:|---:|---:|---:|---:|
| mock dev | 0.9620 | 0.9795 | 0.8838 | 1.0000 | 0.0000 |
| mock test | 0.9420 | 0.9589 | 0.7812 | 1.0000 | 0.0120 |
| recorded dev | 0.9712 | 0.9860 | 0.8894 | 1.0000 | 0.0000 |
| recorded test | 0.9720 | 0.9801 | 0.8900 | 1.0000 | 0.0000 |

`eval validate`: seeds 200, queries 259(dev 158/test 101), lexicon 139. 기준선·골든 파일은
변경하지 않았다. recorded test Recall@10은 회귀 하한 0.9720과 같아 여유가 0이다.

### 2.3 recorded dev A/B 재판정 (튜닝 없음)

| 지표 | A1 − A0 | 95% CI |
|---|---:|---:|
| Recall@10 | -0.0315 | [-0.0651, -0.0063] |
| MRR@10 | -0.0252 | [-0.0588, 0.0000] |
| nDCG@10 | -0.0266 | [-0.0602, -0.0014] |
| false empty | +0.0168 | [0.0000, 0.0420] |

규칙 1~4는 FAIL이고, live 벤치마크 입력이 없어 규칙 5~6도 FAIL이다. 규칙 7은 이 dev 보고에 test 확인 입력이 없으므로 FAIL이다.
결론은 `REJECT`다. test A/B는 재실행하지 않았고, 완료 조건의 기본 A0 eval test만 실행했다.

## 3. A0 정본 대비 변화

A0는 `c7da005` 자체가 아니라 F1 수정이 들어간 HEAD + 리랭커 off다. `c7da005` 대비
mock dev q_0176은 `[0063] → [0063,0052]`(Recall@10 0→1, nDCG 0→0.63), recorded dev q_0127은
`0047` 3위 진입(Recall@5 0.5→1.0, nDCG 0.964→0.983)이다. 악화는 0건이다.

## 4. 남은 문제

1. 리랭커는 recorded dev 추정치와 CI 하한을 어겨 미채택이다. 기본값을 켜지 않았다.
2. recorded test Recall@10은 회귀 하한에 걸쳐 있고 새 blind test v2·사람 검수 건수는 0이다.
3. L3~L5 진단과 골든 밖 녹화 보강은 채택 재평가 전 작업이다. 이번 루프의 재튜닝·test
   재사용 금지를 지키기 위해 수행하지 않았다.
4. 새 녹화 행은 device/dtype를 남기지만 기존 행과 pair hash는 하위 호환을 위해 그대로다.
   여러 장치·정밀도를 한 파일에 혼합하는 정책은 후속 스키마 버전이 필요하다.
5. 기본 설치 pytest에 Starlette/httpx 비권장 경고 1건이 있으나 테스트 실패는 아니다. extra는
   httpx2를 설치해 같은 경고가 없었다.

# Phase 2 완화 정책 v2 사이클 — Loop 3/3 구현 보고서

- 역할: Codex-Primary
- 기준일: 2026-10-30
- 대상: `phase-2-cycle2-loop3-fixes`
- 판정: **기술 검증 PASS / 제품 품질 PASS는 미선언**
- 품질 기준: recorded(bge-m3 녹화 재생). mock은 안전·절대 기준·결정성 확인용

## 1. 결론

직전 검수의 N1~N5와 L1을 모두 반영했다. recorded dev/test, mock dev/test, 전체 pytest, ruff, mypy,
골든셋 validate가 최종적으로 통과한다. recorded 기준선은 변경하거나 낮추지 않았다. mock 기준선은 PM
확정 정책에 따라 v2 안전·결정성 기준으로 재설정했고 사유와 전후 수치를
`data/baselines/README.md`에 기록했다.

현재 test는 이전 루프에서 여러 번 열람됐고 이번 루프의 첫 최종 확인 뒤 N3 구조 수정도 있었으므로
blind test가 아니다. 사람 검수 데이터도 0건이다. 따라서 결과는 기술 게이트 통과이며 제품 품질 PASS를
뜻하지 않는다. 사용자 작성·검수용 동결 test v2 초안 구조를 `data/golden/test_v2/`에 준비했다.

## 2. 피드백별 조치

| 피드백 | 조치 | 검증 |
|---|---|---|
| N1 low-signal 문턱 도달 불가 | low-signal R 문턱을 0.58→0.45로 같은 계수 척도에 맞췄다. 모든 evidence profile 문턱이 이론상 상한 이내인지 `SearchSettings` validator로 강제했다. bge semantic floor는 recorded dev negative 최대 raw 0.4844와 dev positive 하단 사이의 calibrated 0.61로 정했다. | recorded `ch_0017→0112`, `ch_0023→0100`; ch_0011/12 empty. 설정 도달 가능성 단위 테스트 추가. challenge positive 합산 R@10 0.9394 ≥ 0.9091. |
| N2 semantic-only 오탐 | bge floor 0.61, standalone lexical-only R 문턱 0.58을 사용한다. 관련 정답 꼬리는 강한 corroborated/semantic 1위가 같은 계획에 있을 때만 별도 절대 tail 문턱 0.44와 기존 margin을 통과시킨다. tail은 1위·완화 채택에 참여하지 않는다. embedding 장애 시에만 같은 0.44 lexical fallback을 허용한다. | recorded 고정 negative `북극곰 다큐`, `미얀마 여행 일정`, `보드게임 추천`, `낚시 포인트 추천`, ch_0011 모두 empty. dev TE 1.0, FE 0.0. `그 영화 예매했던 거`의 관련 tail 복구 테스트 추가. |
| N3 범용어를 R에서 삭제 | `_informative_terms` 삭제. 모든 원형어가 R의 `original_lexical` 분모·분자에 남고, 약한 용어는 0.25 가중치만 적용한다. df=1인 `다큐/다큐멘터리`는 약한 목록에서 제거했다. | recorded `환경 다큐`가 `c_alice_0047` 1위, 단일 `환경` 일치 문서보다 앞선다. |
| N4 recorded test 기준선 FAIL | N1~N3 구조 수정과 anchor tail로 재현율을 복구했다. | recorded test R@10 0.9720으로 기존 기준선 허용 경계 0.9720 PASS. `data/baselines/recorded.json` 미변경. |
| N5 방향 확장이 원형 대체 | directional expansion이 `out.extend((original, expanded))`로 원형과 확장어를 나란히 보존한다. | `다리 운동 영상` keywords `[다리, 하체, 운동]`, 두 mode에서 `0040` 1위. 사전 제거 시 실패한다는 잔여 의존을 `specs/known_issues.md`에 명시. |
| L1 empty explain 부족 | strict를 포함한 모든 계획에 retrieval 후보 수, 계획 범위 후보 수, gate 통과 수, 상위 3개 거부 사유·개수·예시 ID를 노출한다. `no_retrieval_candidate`와 `all_candidates_rejected`를 구분한다. | ch_0011 empty explain 통합 테스트에서 strict 후보 존재/전부 거부와 사유를 검증. |
| L2 mock false-empty | mock은 품질 판정 기준이 아니며 절대 FE 기준 내라 정책대로 기록만 했다. | mock test FE 0.012048 ≤ 0.05. |
| L3 test 오염 | 현재 test는 회귀 확인용으로만 사용하고 제품 주장용 동결 test v2 구조를 추가했다. | 빈 `queries/challenge`, metadata, freeze manifest, 동결 절차, `REVIEW_GUIDE.md` 연결. |
| L4 hashtag 교정 표시 | normalize 단계에서 검색 토큰 앞 `#/@`를 제거해 spelling correction으로 보이지 않게 했다. | `#카페 @성수!!` → normalized `카페 성수`, `#카페` 교정 없음. |

## 3. 최종 설정과 dev 선택 근거

관련도 계수와 calibration, facet 비용은 Loop 2 값을 유지했다.

| 설정 | 최종값 |
|---|---:|
| βsemantic / βoriginal / βcanonical | 1.40 / 1.05 / 0.77 |
| βphrase / βpurpose / βcorroboration / intercept | 0.28 / 0.35 / 0.21 / -1.05 |
| bge-m3 calibration low/high | 0.15 / 0.75 |
| hashing-v1 calibration low/high | 0.05 / 0.75 |
| corroborated / semantic-only R 문턱 | 0.45 / 0.45 |
| lexical-only standalone / anchored-tail R 문턱 | 0.58 / 0.44 |
| low-signal R 문턱 | 0.45 |
| bge-m3 / hashing semantic floor | 0.61 / 0.85 |
| return tail margin | 0.40 |
| weak lexical weight | 0.25 |
| time expanded/dropped 비용 | 0.06 / 0.14 |
| platform/content-type 비용 | 0.12 / 0.10 |
| minimum relevance gain / epsilon | 0.05 / 1e-6 |

recorded dev에서 negative 후보 raw cosine 최대는 0.4844(calibrated 약 0.557), 유지할 semantic-only
positive 하단은 raw 0.5232(calibrated 약 0.622)였다. 그래서 semantic floor 0.61을 선택했다.
lexical-only standalone은 0.59와 0.58을 dev에서 비교했다. 0.59의 R@10은 0.9642, 0.58은 0.9670이었고
둘 다 TE 1.0이었다. anchor tail을 결합한 최종 dev R@10은 0.9712로 복구됐다. test 지표로 계수나 문턱을
선택하지 않았다.

## 4. 지표 전후

### recorded — 순위 품질 기준

| split | 지표 | Loop 2 | Loop 3 최종 | 판정 |
|---|---|---:|---:|---|
| dev | Recall@10 | 0.9712 | 0.9712 | PASS |
| dev | MRR@10 | 1.0000 | 1.0000 | PASS |
| dev | nDCG@10 | 0.9858 | 0.9858 | PASS |
| dev | true / false empty | 1.0000 / 0.0000 | 1.0000 / 0.0000 | PASS |
| test | Recall@10 | 0.9707 | 0.9720 | 기존 기준선 허용 경계 PASS |
| test | MRR@10 | 0.9804 | 0.9911 | PASS |
| test | nDCG@10 | 0.9708 | 0.9801 | PASS |
| test | true / false empty | 0.9000 / 0.0000 | 1.0000 / 0.0000 | PASS |
| combined | challenge positive Recall@10 | 0.8485 | 0.9394 | ≥ 0.9091 PASS |
| combined | challenge negative true empty | 1.0000 | 1.0000 | PASS |

recorded dev/test 모두 격리·필터 위반 0, browse precision/sort/filter 1.0이다. recorded 기준선은 낮추지
않았고 파일을 갱신하지 않았다.

### mock — 안전·절대 기준

| split | Recall@10 | MRR@10 | nDCG@10 | true empty | false empty |
|---|---:|---:|---:|---:|---:|
| dev | 0.953571 | 0.991597 | 0.974195 | 1.000000 | 0.000000 |
| test | 0.942000 | 0.986667 | 0.958865 | 1.000000 | 0.012048 |
| all | 0.949098 | 0.989691 | 0.968268 | 1.000000 | 0.004762 |

mock 기준선 전후 전체 표와 재설정 사유는 `data/baselines/README.md`에 있다. 모든 절대 기준과 안전
지표는 통과한다.

## 5. 최종 검증

| 명령 | 결과 |
|---|---|
| `uv run pytest` | PASS — 554 passed, 1 deselected(embed marker), Starlette deprecation warning 1건 |
| `uv run ruff check .` | PASS |
| `uv run mypy src` | PASS — 52 source files |
| `uv run jupjup eval validate` | PASS — seeds 200, queries 259(dev 158/test 101), lexicon 139 |
| mock dev + v2 baseline | PASS |
| mock test + v2 baseline | PASS |
| recorded dev + 기존 baseline | PASS |
| recorded test + 기존 baseline | PASS |
| recorded 결정성 | PASS — 기존 INV-20 회귀 테스트 포함 |

설계 11절 INV-01~20과 12절 고정 사례 테스트는 전체 pytest에서 통과했다. live 모델 다운로드/재녹화는
필요하지 않아 실행하지 않았다. committed recorded bge-m3 재생을 사용했다.

## 6. test 실행 이력과 제품 판정 제한

설정 동결 뒤 첫 전체 pytest에서 mock 기준선 2건과 N3 `환경 다큐` 1건이 실패했다. N3은 검수에서 이미
명시된 구조 계약대로 `다큐`를 R에 복원해 수정했다. 이 과정에서 recorded dev q_0199 negative가 재현돼
standalone lexical-only/anchor tail 경계를 **recorded dev만으로** 선택했다. 이후 test를 다시 실행했으므로
현재 test 결과는 blind가 아니다. 이 사실 때문에 기술 게이트는 PASS지만 제품 품질 PASS는 선언하지 않는다.

`data/golden/test_v2/`는 데이터 0건의 draft다. 빈 초안에 test-v2 전용 validate를 실행하면 최소 표본
조건 17건이 실패하는 것이 정상이며, 사용자 데이터 작성·독립 검수·동결 전에는 제품 evidence가 아니다.

## 7. 남은 문제

1. 사람 검수 데이터 0건이라 product evidence는 `eligible=false`다.
2. 동결 test v2의 질의 작성과 2인 이상 독립 검수, kappa 산출은 사용자 작업으로 남는다.
3. `다리 운동 영상` 재현율은 curated `다리→하체` 방향 확장에 의존한다. 원형 대체 버그는 해결됐다.
4. mock test q_0042 `떡복이 맛집` false-empty가 남지만 FE 0.012048로 mock 절대 기준 안이다.
5. recorded test Recall@10은 회귀 허용 경계 0.9720과 같아 여유가 없다. 기준선을 낮추지 않았으며 다음
   품질 판단은 동결 test v2에서 해야 한다.
6. FastAPI TestClient의 Starlette deprecation warning 1건은 검색 정책 범위 밖이다.

## 8. 변경 파일 요약

- 검색 정책: `src/jupjup/config.py`, `search/relevance.py`, `search/service.py`
- 질의 처리: `query/spell.py`, `text/normalize.py`
- 회귀 테스트: `tests/conftest.py`, `tests/eval/test_recorded_regression.py`,
  `tests/unit/test_relevance.py`, `tests/unit/test_understanding.py`
- 정책/데이터: `data/baselines/mock.json`, `data/baselines/README.md`, `data/golden/test_v2/*`,
  `specs/known_issues.md`

# Phase 2 Loop 3/3 구현 보고서

- 작업일: 2026-10-29
- 대상: `specs/phase4_review_loop2.md`의 88점 REJECT 피드백
- 상태: 구현 및 최종 검증 완료
- 원칙: 검색 정책 튜닝은 dev에서만 수행했고, 후보 정책을 동결한 뒤 전체 테스트와 test split을 확인했다. 기존 기준값과 기준선 파일은 낮추거나 갱신하지 않았다.

## 피드백별 조치

| 피드백 | 조치 | 검증 |
|---|---|---|
| 높음 1 — hard facet을 버린 완화 후보가 정상 결과를 밀어냄 | 완화 전후 `final_score` 비교를 제거했다. 원래 질의의 키워드·strong field·purpose·ngram으로 `comparison_relevance`를 다시 계산하고, 원래 플랫폼/유형 hard facet 위반 수와 exact 기간 일치를 독립 특징으로 계산한다. hard facet 위반 비용 1.0과 exact 기간 보너스 0.05를 명시했으며, 기존 후보보다 facet 위반이 늘면 교체하지 않는다. | `레스토랑 추천 블로그`는 limit 1/2/10/50에서 `c_alice_0152` 1위, limit 2 이상에서 `c_alice_0153` 2위, 완화 없음, 전 결과 blog를 유지한다. q_0173 MRR@10은 Loop 2의 0.125에서 0.5로 회복했다. |
| 중간 2 — 다른 필터 문맥 점수 비교와 동일 1위의 가짜 완화 | 비교 특징을 원래 해석에서 문서별로 재계산한다. 동일 content id는 즉시 거부하고, 동점 및 0.10 미만 개선도 거부한다. 응답 debug 특징에 `comparison_relevance`, `original_hard_facet_violations`, `original_time_exact_match`를 남긴다. | `다리 운동 영상`은 limit 1/2/10/50에서 `c_alice_0050` 1위를 유지하면서 `content_type_filter_dropped`와 `relaxed=true`가 모두 사라졌다. 단위 불변식 테스트로 동일 1위, tie, facet 악화, 의미 있는 시간 완화를 각각 고정했다. |
| 중간 3 — mode가 다른 기준선 비교/덮어쓰기 | `BaselineFile.mode`를 `mock|recorded|live`로 제한하고, `compare`와 `update_baseline`의 split 조회·파일 쓰기보다 먼저 report mode와 일치하는지 확인한다. 갱신 시 mode 덮어쓰기를 제거했다. | mode가 다른 빈 기준선도 비교에서 FAIL이며, 갱신은 파일 바이트를 바꾸지 않고 거부하는 테스트를 추가했다. |
| 중간 4 — review status별 understanding/제품 게이트 미완결 | 모든 질의를 review status별 `_UStats`에 누적해 기간·플랫폼·유형·키워드·의도 지표를 각각 계산한다. status별 절대 게이트와 해당 status 기준선 회귀 게이트를 보고서에 포함한다. human-reviewed 기준선도 `time_exact`, `platform_f1`, `content_type_f1`, `keyword_inclusion`을 저장한다. | `product_evidence.eligible`은 human-reviewed 20건 이상, 메타데이터 건수 일치, 독립 검수자 2명 이상, weighted kappa 0.70 이상, 절대 게이트, human 기준선 존재, 회귀 게이트를 모두 요구한다. `review_metadata.json`을 추가하고 `eval validate`에서 human-reviewed 수와 일치하는지 검사한다. |
| 회귀 고정 — S7/q_0173/다리 운동 영상과 limit 안정성 | 세 질의를 결과 ID, rank, 완화 목록, `relaxed`, S7의 `time_near`, q_0173의 blog facet까지 통합 테스트로 고정했다. | 세 질의 모두 limit 1/2/10/50에서 선택 정책이 안정적이다. S7은 `c_alice_0136` 1위와 `time_window_expanded`, `relaxed=true`, `time_near`를 유지한다. |
| 기존 빈 결과 UX | 후보가 전혀 없을 때는 실제로 시도한 완화 단계를 빈 결과 설명에 계속 보존한다. 후보가 있으나 같은 1위/무개선이면 완화를 기록하지 않는다. | 기존 demo empty-state 통합 테스트와 새 완화 불변식 테스트가 함께 통과한다. |

## 주요 변경 파일

- `src/jupjup/search/service.py`: 원래 해석 기반 완화 후보 비교와 채택 불변식
- `src/jupjup/config.py`: 최소 개선폭, hard facet 위반 비용, exact 기간 보너스
- `src/jupjup/eval/harness.py`: mode 무결성, review status별 understanding/게이트, 제품 근거 조건
- `src/jupjup/eval/report.py`: review status별 이해 지표와 절대/회귀 판정 출력
- `src/jupjup/cli.py`: 사람 검수 메타데이터 검증
- `data/golden/review_metadata.json`, `data/golden/README.md`, `data/golden/REVIEW_GUIDE.md`: 검수 증거 구조와 절차
- `tests/integration/test_search_v0.py`, `tests/unit/test_relevance.py`, `tests/eval/test_golden_regression.py`, `tests/integration/test_cli.py`: 회귀 및 불변식 테스트

## 지표 전후 비교

Loop 2 검수에서 직접 실행한 mock 지표를 전으로, 동결 후 최종 실행을 후로 사용했다.

| split | 지표 | Loop 2 | Loop 3 | 변화 |
|---|---|---:|---:|---:|
| dev | Recall@10 | 0.9690 | 0.9690 | 유지 |
| dev | MRR@10 | 0.9916 | 0.9916 | 유지 |
| dev | nDCG@10 | 0.9737 | 0.9737 | 유지 |
| dev | true-empty | 0.7333 | 0.7333 | 유지 |
| test | Recall@10 | 0.9820 | 0.9820 | 유지 |
| test | MRR@10 | 0.9817 | 0.9867 | +0.0050 |
| test | nDCG@10 | 0.9714 | 0.9761 | +0.0047 |
| test | true-empty | 0.8000 | 0.8000 | 유지 |
| dev/test | time exact | 1.0000 / 1.0000 | 1.0000 / 1.0000 | 유지 |
| dev/test | platform F1 | 1.0000 / 1.0000 | 1.0000 / 1.0000 | 유지 |
| dev/test | content type F1 | 1.0000 / 1.0000 | 1.0000 / 1.0000 | 유지 |
| dev/test | 격리/필터 위반 | 0 / 0 | 0 / 0 | 유지 |

최종 상세 결과:

- q_0083 S7: `c_alice_0136`, `c_alice_0146`; 1위 `c_alice_0136`; `time_window_expanded`; `relaxed=true`; `time_near`.
- q_0173: `c_alice_0152`, `c_alice_0153`; 둘 다 blog; 완화 없음; 정답 `c_alice_0153`은 8위에서 2위로 회복.
- q_0167 다리 운동 영상: `c_alice_0050`, `c_alice_0040`, `c_alice_0051`, `c_alice_0027`; 완화 없음; 모든 결과 `relaxed=false`.

## 최종 검증

| 명령 | 결과 |
|---|---|
| `uv run pytest` | PASS — 488 passed, warning 1건 |
| `uv run ruff check` | PASS — All checks passed |
| `uv run mypy src` | PASS — 50개 소스 파일, 오류 0 |
| `uv run jupjup eval validate` | PASS — seeds 200, queries 259(dev 158/test 101), lexicon 139, review metadata 일치 |
| `uv run jupjup eval run --mode mock --split dev --baseline data/baselines/mock.json` | PASS — 절대 및 회귀 게이트 통과 |
| `uv run jupjup eval run --mode mock --split test --baseline data/baselines/mock.json` | PASS — 절대 및 회귀 게이트 통과 |

경고 1건은 기존 FastAPI TestClient의 Starlette/httpx deprecation이며 이번 변경에서 새로 발생한 경고가 아니다.

## 설계와 달라진 점

없다. S7의 단계적 시간 완화, 요청 잠금 필터, 관련도 게이트, dev-only 튜닝 원칙을 유지하면서 후보 채택 기준과 평가 증거 구조만 완결했다.

## 남은 문제

1. 실제 `human_reviewed` 질의가 아직 0건이므로 `product_evidence.eligible=false`가 정상이다. 실제 사용자 사례 20건 이상을 2인 독립 검수하고 weighted kappa 0.70 이상을 기록한 뒤 human 기준선을 만들어야 제품 품질 PASS를 선언할 수 있다.
2. q_0173의 정답 `c_alice_0153`은 blog facet 안에서 2위이고, q_0167의 정답 `c_alice_0040`도 2위다. 이번 피드백의 범위인 불필요한 완화 회귀는 제거했지만 이 두 semantic top-1 순위 자체는 후속 품질 과제로 남는다. test 판정을 보고 추가 튜닝하지 않았다.
3. FastAPI TestClient의 Starlette/httpx deprecation 경고 1건은 기존 의존성 전환 과제로 남는다.

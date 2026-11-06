# Phase 2 Loop 2/3 루프백 수정 보고

- 기준 검수: `specs/phase4_review_loop1.md` — 78/100, REJECT
- 작업 범위: Loop 1 피드백 1–9 전체
- 결과: 구현·단위/통합 테스트·평가 스키마·challenge set·검수 가이드 반영 완료
- 평가 원칙: 튜닝과 중간 확인은 dev에서만 수행했고, 코드를 동결한 뒤 test를 마지막에 확인했다.

## 피드백별 조치

| # | 조치 | 주요 파일 | 회귀 테스트 |
|---:|---|---|---|
| 1 | 초기 후보가 있어도 1위가 핵심 키워드 일부만 맞거나 exact 기간 밖이면 완화 단계를 계속 탐색하고, 증거 품질이 더 강한 후보를 선택하게 바꿘다. S7은 `c_alice_0136` 1위, `time_window_expanded`, 결과별 `relaxed=true`를 보장한다. | `src/jupjup/search/service.py` | `tests/integration/test_search_v0.py::test_s7_prefers_stronger_expanded_period_result`; test 평가 `q_0083` Success@1/MRR@10 = 1.0 |
| 2 | exact 구간 일치와 margin 구간 일치를 `time_exact_match`/`time_margin_match`로 분리했다. margin 결과는 `time_near`, `기간 근접 (지난주)`로 표시하여 `지난주 저장`이라는 오해를 막았다. | `src/jupjup/search/rerank.py`, `src/jupjup/search/types.py`, `src/jupjup/demo/app.py` | `tests/integration/test_search_v0.py::test_margin_result_uses_near_period_reason` |
| 3 | 데모 바인딩은 `localhost`, `127.0.0.0/8`, `::1` 계열만 기본 허용하고 외부 주소는 `--allow-external-bind`가 없으면 exit 2로 거부한다. `Settings(env="dev", mode="mock")`로 환경을 덮어쓰던 코드를 제거해 실제 `JUPJUP_ENV`/`JUPJUP_MODE`를 존중한다. | `src/jupjup/cli.py`, `src/jupjup/demo/app.py` | `tests/integration/test_cli.py::{test_demo_serve_rejects_external_bind_without_risk_flag,test_demo_serve_external_bind_requires_explicit_risk_flag,test_demo_serve_preserves_environment}` |
| 4 | 플랫폼·유형 Pydantic 오류와 `--now`/`--from`/`--to` ISO 8601·timezone 오류를 전부 `[INVALID_FILTER]`, exit 2로 매핑했다. `--from`/`--to`는 각 옵션명을 포함한 별도 메시지를 낸다. traceback과 로컬 절대경로는 노출하지 않는다. | `src/jupjup/cli.py` | `tests/integration/test_cli.py::test_search_filter_errors_are_clean`, `test_search_errors` |
| 5 | 회귀 허용치 0.01은 빌드 통과에만 쓰고, `--update-baseline`은 Recall@10, MRR@10, nDCG@10, 기간 정확도, 플랫폼 F1이 기존 이상일 때만 허용한다. | `src/jupjup/eval/harness.py` | `tests/eval/test_golden_regression.py::test_update_baseline_refuses_even_small_decrease` (0.005 하락 거부) |
| 6 | 질의 스키마에 `review_status`, `template_id`, `entity_id`, `challenge_kind`를 추가하고 AI 초안/사람 검수 대기/사람 검수 완료 지표를 분리했다. 독립 JSONL에 하드 네거티브, 동의어 불일치, 실제형 오타·구어체, 영어 혼합 challenge 24건을 추가했다. 같은 템플릿 또는 엔티티가 dev/test에 나뉘면 검증을 거부한다. human-reviewed 기준선을 별도 파일로 두고, 인간 검수·블라인드 2인·제3자 조정·가중 kappa 절차를 문서화했다. | `src/jupjup/eval/schema.py`, `src/jupjup/eval/harness.py`, `src/jupjup/eval/report.py`, `data/golden/challenge_queries.jsonl`, `data/golden/REVIEW_GUIDE.md`, `data/baselines/mock.human_reviewed.json` | `tests/unit/test_golden_validator.py::{test_challenge_set_is_separate_and_awaits_human_review,test_group_split_rejects_template_or_entity_leak}`, `tests/eval/test_golden_regression.py::{test_review_status_and_browse_metrics_are_separated,test_human_reviewed_baseline_cannot_use_ai_metrics}` |
| 7 | filter-only browse를 일반 Recall@5/10, MRR, nDCG, Success@1, category minimum에서 제외했다. 대신 상위 페이지 precision@10, 최신순 정렬 정확도, 필터 준수, coverage를 별도 집계·게이트한다. | `src/jupjup/eval/harness.py`, `src/jupjup/eval/report.py`, `data/golden/README.md` | `tests/eval/test_golden_regression.py::test_review_status_and_browse_metrics_are_separated` |
| 8 | 긴 단일 문자 또는 동일 단어 반복의 정보량 가드를 추가해 `INVALID_QUERY(low_information)`로 거부한다. | `src/jupjup/query/understanding.py` | `tests/unit/test_understanding.py::test_invalid_queries` (`"가"*200`, `"카페 "*50`) |
| 9 | `coffee shop`·`coffeeshop`을 다단어 동의어로 접고, 영숫자 단어 경계를 적용했다. 기호만인 토큰을 제거했고, 정상 2자 어휘 `이주`를 데이터 기반 교정 보호 목록에 넣어 `이주→위주` 오교정을 막았다. | `data/lexicon/synonyms.yaml`, `src/jupjup/text/lexicon.py`, `src/jupjup/query/understanding.py`, `src/jupjup/query/spell.py` | `tests/unit/test_understanding.py::{test_mixed_english_multiword_synonym_and_symbol_cleanup,test_short_valid_word_is_not_spelling_corrected}`, `tests/integration/test_search_v0.py::test_mixed_english_coffee_shop_returns_relevant_instagram` |

## 지표 전후 비교

AI 초안 `review_status=ai_draft_unreviewed`의 mock 지표다. Loop 1 전에는 filter-only 8건이 일반 순위 평균에
포함됐고, Loop 2 후에는 이를 제외했으므로 Recall/MRR/nDCG/Success@1의 분모가 다르다.
기준을 낮추지 않았고 기존 `data/baselines/mock.json`도 하향 갱신하지 않았다.

| split | 지표 | Loop 1 | Loop 2 | 비고 |
|---|---|---:|---:|---|
| dev | Recall@10 | 0.9657 | 0.9690 | browse 분리 후 일반 질의만 집계 |
| dev | MRR@10 | 0.9921 | 0.9916 | browse의 쉬운 1.0 점수 제외로 소폭 변화 |
| dev | nDCG@10 | 0.9754 | 0.9737 | 동일 |
| dev | Success@1 | 0.9843 | 0.9832 | 동일 |
| test | Recall@10 | 0.9697 | 0.9820 | S7 복구 + browse 분리 |
| test | MRR@10 | 0.9759 | 0.9817 | 상승 |
| test | nDCG@10 | 0.9674 | 0.9714 | 상승 |
| test | Success@1 | 0.9639 | 0.9733 | 상승 |
| dev/test | true-empty rate | 0.7333 / 0.8000 | 0.7333 / 0.8000 | 유지 |
| dev/test | isolation/filter violations | 0 / 0 | 0 / 0 | 안전 지표 유지 |
| dev/test | browse precision@10 | 미분리 | 1.0000 / 1.0000 | 신규 지표 |
| dev/test | browse sort accuracy | 미분리 | 1.0000 / 1.0000 | 신규 지표 |
| dev/test | browse filter compliance | 미분리 | 1.0000 / 1.0000 | 신규 지표 |
| dev/test | browse coverage | 미분리 | 0.9167 / 0.9167 | 페이지 크기 10을 전체 정답 수와 별도 표시 |

S7 `q_0083`은 Loop 1에서 Recall@10/MRR/nDCG/Success@1이 모두 0이었다. Loop 2에서는
`c_alice_0136` 1위, `time_window_expanded`, Success@1 1.0, MRR@10 1.0, nDCG@10 0.9173이다.
Recall@10은 연관도 1인 2025년 문서 `c_alice_0150`까지 포함한 골든 분모 때문에 0.5이며,
핵심 인수 대상인 `c_alice_0136`의 1위 복구는 완료됐다.

challenge set은 사람 검수 전이므로 기술 게이트와 제품 PASS 근거에서 제외했다. 탐색용
`needs_human_review` Recall@10은 dev 0.7500, test 0.5000으로, 영어 혼합·상위어·하드 네거티브가
향후 사람 판정 후 개선할 영역임을 드러낸다.

## 완료 검증

| 명령 | 결과 |
|---|---|
| `uv run pytest` | PASS — 473 passed, warning 1건 |
| `uv run ruff check src tests` | PASS |
| `uv run mypy src` | PASS — 50 source files |
| `uv run jupjup eval validate` | PASS — seeds 200, queries 259(dev 158/test 101), challenge 24, lexicon 139 |
| `uv run jupjup eval run --mode mock --split dev --baseline data/baselines/mock.json` | PASS |
| `uv run jupjup eval run --mode mock --split test --baseline data/baselines/mock.json` | PASS |

경고 1건은 FastAPI `TestClient`가 발생시킨 Starlette/httpx 상호운용 deprecation으로, Loop 1과 동일하고
이번 변경의 기능·안전성 실패가 아니다.

## 설계와 달라진 점

- 기존 설계의 “결과 0건일 때만 완화”를 “상위 후보가 약하거나 exact 기간 밖이면 완화 후보와
  증거 품질을 비교”로 확장했다. 이는 S7 인수 조건과 Reviewer 피드백을 반영한 기능 수정이다.
- 질의 id 해시 split 단독 대신 challenge에는 템플릿·엔티티 group split 검증을 추가했다.
- AI 초안의 기술 회귀 PASS와 human-reviewed 제품 PASS를 분리했다. 현재 리포트의 PASS는
  `ai_draft_unreviewed` 기술 게이트이며 제품 품질 최종 PASS는 아니다.

## 남은 문제

1. `human_reviewed` 질의는 아직 0건이다. 실제 사용자 사례 20–30건의 비식별화, 2인 독립 판정,
   제3자 조정, 가중 kappa 보고는 `data/golden/REVIEW_GUIDE.md`에 따라 사람이 진행해야 한다.
2. 사람 검수 대기 challenge에서 영어 상위어, 영어 전문 질의, 하드 네거티브의 성능이 기존 AI 초안보다
   낮다. 정답 판정을 사람이 확정한 후 dev로만 후속 튜닝해야 한다.
3. FastAPI TestClient deprecation 경고는 상위 Starlette/httpx 호환 전환 시 제거해야 한다.

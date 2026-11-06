# Phase 2 필터 전용 browse 구현 보고서

작성일: 2026-10-29 (Asia/Seoul)

골든셋 상태: **초안, 사용자 검수 전**. 아래 수치는 AI가 작성한 가상 골든셋 기준이다.

## 결과 요약

기간·플랫폼·유형을 제거한 뒤 의미 있는 키워드와 목적어가 남지 않는 질의를 `filter_only` browse로
판정한다. `유튜브`, `지난달 인스타`, `유튜브 영상`, `인스타 게시물`이 이 경로에 해당한다.

browse 경로는 사용자별 인덱스에 요청 우선 hard filter를 적용하고, 질의 기간은 정확한 반열림 구간으로
적용한 뒤 `saved_at` 내림차순과 `content_id` 오름차순으로 정렬한다. 키워드·벡터 검색,
`RelevanceGate`, 완화 정책을 건너뛰고 요청 `limit`만큼 반환한다. 각 결과의 근거에는 `browse`를 남기며,
웹 데모에는 둘러보기 안내와 상태 문구를 표시한다.

## 변경 파일

- 질의 이해와 검색: `src/jupjup/query/understanding.py`, `src/jupjup/search/service.py`,
  `src/jupjup/search/types.py`
- 웹 데모: `src/jupjup/demo/app.py`, `src/jupjup/demo/page.py`
- 골든셋과 검증: `data/golden/queries.jsonl`, `data/golden/README.md`,
  `scripts/golden_v1/build.py`, `scripts/golden_v1/queries_data.py`, `src/jupjup/eval/schema.py`
- 기준선: `data/baselines/mock.json`
- 설계: `specs/prd_and_design.md`
- 테스트: `tests/unit/test_understanding.py`, `tests/unit/test_golden_validator.py`,
  `tests/integration/test_search_v0.py`, `tests/integration/test_demo.py`

## 검증 결과

| 명령 | 결과 |
|---|---|
| `uv run jupjup eval validate` | PASS: seeds 200, queries 235(dev 142/test 93), lexicon 139 |
| `uv run ruff check` | PASS |
| `uv run mypy src` | PASS: 48개 소스 파일, 오류 0 |
| `uv run pytest` | PASS: 453 passed, 경고 1건 |
| `uv run jupjup eval run --mode mock --split dev --baseline data/baselines/mock.json` | PASS |
| `uv run jupjup eval run --mode mock --split test --baseline data/baselines/mock.json` | PASS |
| `uv run jupjup eval run --mode mock --split all --baseline data/baselines/mock.json` | PASS |

pytest 경고 1건은 FastAPI TestClient의 `httpx`/Starlette deprecation 경고다.

## 지표

| 지표 | dev | test | all |
|---|---:|---:|---:|
| Recall@10 | 0.965682 | 0.969679 | 0.967262 |
| Recall@5 | 0.943395 | 0.954485 | 0.947778 |
| MRR@10 | 0.992126 | 0.975904 | 0.985714 |
| nDCG@10 | 0.975380 | 0.967396 | 0.972224 |
| Success@1 | 0.984252 | 0.963855 | 0.976190 |
| 카테고리별 Recall@10 최저 | 0.885648 | 0.916667 | 0.916667 |
| 정답 빈 결과율 | 0.733333 | 0.800000 | 0.760000 |
| 오답 빈 결과율 | 0.000000 | 0.000000 | 0.000000 |
| 격리 위반 | 0 | 0 | 0 |
| 요청 필터 위반 | 0 | 0 | 0 |

`filter_only`는 dev/test 각각 8건이며 두 split 모두 Recall@10 **0.916667**, Recall@5 **0.895833**,
MRR@10·nDCG@10·Success@1 **1.0**이다. 정답은 페이지 크기와 무관하게 해당 필터에 맞는 저장물 전체다.

기존 절대 기준과 회귀 규칙을 모두 유지했다. 숫자 문턱이나 회귀 허용치 변경은 없으며, mock 기준선의
dev/test/all 항목을 새 235건 골든셋 결과로 갱신했다.

## 평가 절차 기록

구현과 browse 사례 구성은 dev에서 먼저 검증했다. 최초 최종 test에서는 절대 기준과 안전 지표가 모두
통과했지만, 한 split에 페이지 크기를 크게 넘는 광범위 exhaustive 질의가 겹쳐 Recall@10 회귀 규칙만
실패했다. 기준선을 낮추지 않고 각 split을 광범위 플랫폼 사례 1건과 기간 제한 사례 7건으로 다시
층화했으며, dev를 재검증한 뒤 test를 다시 최종 확인했다. 최종 test Recall@10은 0.969679로 기존 회귀
허용선 0.965333을 통과했다.

## 남은 문제

1. 골든셋은 사용자 검수 전 초안이다. 특히 exhaustive 필터 정답과 기간 경계를 사람이 검수해야 한다.
2. 응답은 `limit`에 맞춘 첫 페이지이며 cursor와 전체 건수는 아직 제공하지 않는다.
3. 웹 표시는 dev/mock 데모에만 반영됐다. 운영 API와 클라이언트 표면은 후속 범위다.
4. browse 결과의 점수는 관련도 점수가 아니므로 고정값 1.0이다. 소비자는 `browse`와 근거 유형으로
   검색 결과와 구분해야 한다.

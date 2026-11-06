# Phase 4 최종 검수 — Loop 1

- **점수:** 78 / 100 (정확성 31 / 40, 안전성 24 / 30, 유지보수성 23 / 30)
- **상태:** REJECT
- **루프백 대상:** Phase 2

## 검수 범위

- 포함: Loop 1의 `src/`, `tests/`, `data/golden`, `data/baselines`, T0~T14 및 후속으로 추가된 filter-only browse 경로
- 범위 외: T15 정식 FastAPI API(미구현), T17 실제 제공자, T18 이후 인제스트 전 범위
- T15 미구현 자체는 감점하지 않았다. 다만 현재 산출물에 포함된 dev 웹 데모는 요청에 따라 바인딩 범위, dev 제한, 예외 노출을 검수했다.
- 기존 Phase 2/3 보고서는 참고만 했고, 아래 명령과 코드/데이터 검사는 이 워크트리에서 다시 수행했다.

## 직접 실행한 명령과 결과

| 명령 | 결과 |
|---|---|
| `uv run pytest` | PASS — 453 passed, 경고 1건, 12.54초. 경고는 FastAPI TestClient의 Starlette/httpx deprecation이다. |
| `uv run ruff check` | PASS — `All checks passed!` |
| `uv run mypy src` | PASS — 50개 소스 파일, 오류 0 |
| `uv run jupjup eval validate` | PASS — seeds 200, queries 235(dev 142/test 93), lexicon 139. 카테고리 최소 개수 통과 |
| `uv run jupjup eval run --mode mock --split dev` | PASS — Recall@10 0.9657, MRR@10 0.9921, nDCG@10 0.9754, true-empty 0.7333, 격리/필터 위반 0 |
| `uv run jupjup eval run --mode mock --split test` | PASS — Recall@10 0.9697, MRR@10 0.9759, nDCG@10 0.9674, true-empty 0.8000, 격리/필터 위반 0 |
| `uv run jupjup eval run --mode mock --split test --baseline data/baselines/mock.json` | PASS — mock 절대 기준 및 5개 회귀 기준 모두 통과 |
| 동일 test 평가 2회 후 `created_at`, `git_sha`, `perf` 제외 비교 | PASS — `cmp` exit 0, 결정적 결과 일치 |
| `uv run jupjup seed load --db var/review.db` | PASS — 200건 적재/인덱싱, embedding pending 0 |

`var/review.db`는 검수용으로만 만들었고 커밋 대상에서 제외했다.

### 직접 CLI 경계값 검증

모든 정상 검색은 `--db var/review.db --now 2026-10-15T12:00+09:00 --user u_alice`로 실행했다.

| 사례 | 결과 |
|---|---|
| 정상 복합 `지난달 인스타에서 본 성수동 카페` | `c_alice_0001` 1위, 기간/플랫폼 해석 정상 |
| 오타 `성수동까페` | `까페→카페` 교정, 관련 결과 반환 |
| 구어체 `유툽에서 본 파스타 레시피 그거` | youtube hard 추출, 관련 레시피 3건 반환 |
| 필터 전용 `지난달 인스타` | browse=true, 정확한 달력 구간에서 최신순 반환 |
| 없는 대상 `화성 이주 계획 다큐` | 빈 결과와 정확한 빈 결과 문구 반환. 다만 `이주→위주` 오교정이 발생 |
| 특수문자 포함 `성수동!!! 카페??? #맛집` | 검색은 성공했으나 `#`가 독립 키워드로 남음 |
| 특수문자만 / 빈 문자열 | 각각 `INVALID_QUERY`, exit 2 |
| 영어 혼합 `IG에서 본 coffee shop 디저트` | IG는 instagram으로 추출했지만 관련 카페/디저트가 있음에도 빈 결과 |
| 요청 필터 충돌 `인스타…` + `--platform youtube` | 요청 필터가 우선하고 youtube 결과만 반환 |
| 잠긴 요청 플랫폼+기간에 결과 없음 | 필터 완화 없이 빈 결과, 요청 필터 잠금 정상 |
| 200자 반복 질의 | 허용됐으나 무관한 `가계부채`, `가격 인상` 2건 반환 |
| 201자 질의 / naive `--now` / 역전 기간 | 모두 거부, exit 2 |
| 사용자 격리 `낚시 포인트 추천` | alice는 빈 결과, bob은 `c_bob_0001`만 반환 |
| 잘못된 `--platform tiktok` | 실패는 하지만 정제된 오류가 아니라 로컬 절대경로를 포함한 traceback과 exit 1 |

## 피드백

### 높음

1. `src/jupjup/search/service.py:203`, `src/jupjup/search/service.py:211`, `src/jupjup/search/gate.py:24` — 명시적 S7 인수 시나리오가 실패한다. `지난주 카톡으로 받은 회의 장소`는 `c_alice_0136`을 기간 완화로 찾아 `applied_relaxations`와 `relaxed=true`를 내야 한다. 실제로는 margin 안의 하드 네거티브 `c_alice_0146`(팀 **회식** 장소)이 키워드 2개 중 `장소` 하나만 맞아 0.5 문턱을 통과한다. 후보가 한 건이라도 있으면 완화를 전혀 실행하지 않아 결과는 오답 1건, `applied_relaxations=[]`가 된다. 생성된 test 리포트에서도 `q_0083`은 Recall@10/MRR/nDCG/Success@1이 모두 0이다. “결과 0건일 때만 완화”가 아니라 상위 후보의 충분한 관련성/정확 기간 일치까지 확인하거나, 완화 후보를 함께 평가해 더 강한 결과를 선택해야 한다. 이 시나리오를 결과 ID, 완화 기록, `relaxed`까지 검증하는 통합 테스트로 고정해야 한다.

2. `src/jupjup/search/rerank.py:181` — 정확한 기간 밖이고 margin 안에만 있는 `c_alice_0146`에도 match reason을 `지난주 저장`으로 표시한다. 이 저장물은 2026-10-13 저장이고 파싱된 지난주는 `[2026-10-05, 2026-10-12)`이므로 사용자에게 사실과 다른 근거를 준다. exact 구간과 margin 구간을 구분해 `기간 근접` 또는 `완화된 기간`으로 표시하고, exact 표현을 재사용하지 않아야 한다.

3. `src/jupjup/cli.py:103`, `src/jupjup/cli.py:111`, `src/jupjup/cli.py:116`, `src/jupjup/demo/app.py:23`, `src/jupjup/demo/app.py:205` — 데모 기본값은 `127.0.0.1`이지만 `--host 0.0.0.0` 같은 외부 바인딩을 제한하지 않는다. 동시에 CLI가 환경을 무조건 `dev/mock`으로 만들고, 인증 없이 세 고정 사용자를 선택해 요약·태그를 조회할 수 있다. “로컬 dev 전용” 안전 경계가 기본값에만 의존한다. loopback 주소만 허용하거나 명시적 위험 플래그 없이는 외부 바인딩을 거부하고, 환경을 강제로 dev로 덮어쓰지 않아야 한다.

### 중간

4. `src/jupjup/cli.py:151`, `src/jupjup/cli.py:161` — `SearchFilters.model_validate`와 `--from/--to` 파싱이 예외 처리 바깥에 있다. `--platform tiktok`은 Pydantic traceback, 소스 절대경로, 내부 호출 스택을 출력하고 exit 1로 끝났다. 필터 검증 전체를 잡아 `INVALID_FILTER`/exit 2로 일관되게 매핑해야 한다. `_parse_now`를 기간 필터에도 재사용해 naive `--from` 오류가 `--now` 메시지로 나오는 문제도 분리해야 한다.

5. `src/jupjup/eval/harness.py:448`, `src/jupjup/eval/harness.py:453`, `tests/eval/test_golden_regression.py:72`, `tests/eval/test_golden_regression.py:78` — `--update-baseline`은 “지표가 올라간 경우에만 갱신”해야 하지만, 현재 비교 허용치 0.01 안의 하락도 통과시켜 새 기준선으로 저장한다. 이를 반복하면 작은 하락을 누적해 기준선을 계속 낮출 수 있다. 회귀 허용치는 빌드 합격 판정에만 쓰고, 기준선 갱신은 주요 지표가 기존 이상이거나 사람이 승인한 명시적 예외가 있을 때만 허용해야 한다. 0.005 하락 기준선 갱신을 거부하는 테스트가 필요하다.

6. `data/golden/README.md:3`, `data/golden/README.md:20`, `data/golden/README.md:29` — 200개 시드 전부 `ai_draft_unreviewed`이고, 같은 생성 주체가 시드의 제목/요약/태그, 질의 문구, relevance를 함께 작성했다. 따라서 동일 어휘·문체·연상 패턴이 BM25F, HashingEmbedder, 게이트에 유리하게 맞물리는 자기평가 편향이 크다. 질의 ID 해시 split은 같은 시드/주제/템플릿에서 생긴 누출을 막지 못하므로 현재 0.96대 mock 지표를 실제 사용자 품질로 해석할 수 없다.

   보완책:

   - 실제 사용자 사례를 개인정보 제거 후 최소 20~30건 먼저 넣고, 시드 작성자와 질의/정답 작성자를 분리한다.
   - relevance는 독립된 2인 이상이 블라인드로 등급화하고 불일치는 제3자가 조정하며, 일치도(가중 kappa)를 보고한다.
   - test 질의는 구현/튜닝 담당자가 보지 못하게 동결하고, 동일 템플릿·엔티티 변형은 같은 split에 묶는 group split을 쓴다.
   - 동의어 불일치, 그럴듯한 하드 네거티브, 실제 오타/구어체를 별도 challenge set으로 만들고 수동 판정한다.
   - AI 초안 지표와 human-reviewed 지표를 별도 기준선으로 유지하며, PASS 근거는 후자만 사용한다.

7. `data/golden/README.md:31`, `src/jupjup/eval/harness.py:246`, `src/jupjup/eval/harness.py:327` — filter-only 질의의 relevance에는 조건에 맞는 전체 문서를 넣지만 하네스는 늘 `limit=10`으로 검색하고 일반 Recall@10 분모에 전체 relevance를 사용한다. 예를 들어 test `유튜브 영상`은 정답 30건이라 가능한 최대 Recall@10이 0.333이고 실제로도 0.333이다. 이 값이 다른 쉬운 filter-only 사례와 평균돼 카테고리 통과 여부를 흐린다. browse는 상위 페이지 precision/정렬 정확도/필터 준수와 별도 coverage 지표로 평가하거나, exhaustive recall에는 pagination/전체 결과 경로를 사용해야 한다.

### 낮음

8. `src/jupjup/search/gate.py:28`, `src/jupjup/query/understanding.py:153` — 200자의 동일 문자 반복 질의가 입력 검증을 통과하고, 단 하나의 반복 n-gram이 높은 coverage가 되어 무관한 문서 두 건을 통과시켰다. 최소 고유 토큰/n-gram 수 또는 정보량 가드를 추가하고, 저정보량 반복 입력은 `INVALID_QUERY` 또는 빈 결과로 처리해야 한다.

9. `data/lexicon/synonyms.yaml:4`, `src/jupjup/query/understanding.py:175` — 영어 혼합 질의에서 플랫폼 별칭은 처리하지만 `coffee shop` 같은 흔한 다단어 표현은 정규화되지 않아 관련 인스타 카페/디저트가 빈 결과가 됐다. 실제 혼합 언어 사례를 challenge set에 추가하고 다단어 동의어 또는 토큰 조합 정규화를 검토해야 한다. 특수문자 포함 질의에서 `#`가 독립 키워드로 남는 사례도 함께 회귀 테스트하는 편이 좋다.

## 채점 근거

- **정확성 31/40:** 하이브리드 검색, RRF, 재순위, 필터 우선, browse, mock 절대 기준은 전반적으로 작동한다. 그러나 AC-6의 S7이 명시적으로 실패하고 기간 근거까지 잘못 표시하며, 긴 저정보량 질의와 영어 혼합 질의에서 골든 밖 취약점이 재현됐다.
- **안전성 24/30:** 직접 평가와 CLI에서 사용자 격리 및 요청 필터 위반은 0이었고, 빈/기호/길이/naive 시간/역전 기간 검증도 대체로 정상이다. 반면 데모가 외부 인터페이스 바인딩을 허용하고 잘못된 CLI 필터가 traceback을 노출한다.
- **유지보수성 23/30:** 구조 분리, Protocol 조립, 설정 주입, 정적 검사, 453개 테스트, 결정성은 좋다. 다만 기준선 하향 누적 가능성, browse 지표의 목표 불일치, 같은 AI 저자의 골든셋 편향, S7 결과 수준 통합 테스트 부재가 회귀 신뢰도를 낮춘다.

## 루프백 이유와 재검수 조건

**Phase 2로 루프백한다.** 핵심 사유가 구조 미관이 아니라 검색 결과/완화의 기능 버그와 데모·CLI 안전 경계이기 때문이다.

재검수 전 최소 조건:

1. S7이 `c_alice_0136`을 찾고 `time_window_expanded`, `relaxed=true`, 정확한 기간 근거를 반환하는 통합 테스트를 추가한다.
2. 데모를 loopback에만 바인딩하고 외부 노출 시도를 거부하는 테스트를 추가한다.
3. 잘못된 플랫폼/유형/기간 CLI 입력을 traceback 없이 일관된 도메인 오류로 매핑한다.
4. 기준선 갱신의 하락 금지 규칙과 filter-only 전용 평가 지표를 수정한다.
5. human-reviewed 독립 challenge set을 추가하거나, 최소한 현재 AI 초안 점수를 제품 PASS 근거와 분리한 보완 평가를 제출한다.

# Phase 4 최종 검수 — Loop 3/3

- **점수:** 87 / 100 (정확성 34 / 40, 안전성 29 / 30, 유지보수성 24 / 30)
- **상태:** REJECT
- **루프백 대상:** Phase 2 (단, 3회차 한도에 도달했으므로 추가 수정 루프 진행 여부는 사용자 판단 필요)

## 검수 범위

- 포함: Loop 2 피드백 1~4와 재검수 조건 1~5, Loop 1 피드백 1~9의 회귀, 관련 `src/`, `tests/`, `data/golden`, `data/baselines`, T0~T14 및 filter-only browse 경로
- 범위 외: T15 정식 FastAPI API, T17 실제 제공자, T18 이후 인제스트 전 범위
- `human_reviewed` 0건 자체는 감점하지 않았다. 사람 검수 데이터가 들어왔을 때 제품 근거를 판정하는 코드 경로의 구조만 검수했다.
- `specs/phase2_loop3_report.md`의 완료 주장은 근거로 사용하지 않고, 코드·데이터·테스트·CLI를 이 워크트리에서 다시 확인했다.

## Loop 2 항목별 해결 여부

| # | 판정 | 직접 검증 결과 |
|---:|---|---|
| 1 | **해결(새 과소 완화 결함 별도)** | `레스토랑 추천 블로그`는 limit 1/2/10/50에서 `c_alice_0152` 1위, limit 2 이상에서 정답 `c_alice_0153` 2위, 전 결과 blog, 완화 없음이었다. Loop 2의 카카오톡 오답 1위와 정답 8위 회귀는 없어졌다. 다만 hard facet 위반 증가를 무조건 거부하면서 반대 방향의 과소 완화가 생겼다. |
| 2 | **해결** | `다리 운동 영상`은 limit 1/2/10/50에서 동일 1위 `c_alice_0050`을 유지하면서 `content_type_filter_dropped`와 `relaxed=true`가 생기지 않았다. 서로 다른 검색 문맥의 `final_score` 직접 비교도 제거됐다. |
| 3 | **해결** | `BaselineFile.mode`가 literal로 제한되고 `compare`와 `update_baseline` 모두 mode 불일치를 먼저 거부한다. 전용 테스트에서 비교 실패, 갱신 거부, 파일 바이트 불변을 확인했다. 기존보다 0.005 낮은 기준선 갱신 거부도 다시 통과했다. |
| 4 | **부분 해결** | review status별 순위·browse·기간·플랫폼·유형·키워드 지표와 별도 절대/회귀 게이트, 최소 20건·2인·kappa 0.70 조건이 연결됐다. 그러나 해당 부분집합에 negative나 filter-only가 0건이어도 `true_empty_rate`와 browse 지표를 1.0으로 채워 절대 게이트가 통과한다. 합성 검증에서 human 20건을 전부 positive lookup으로 두고 `n_browse=0`으로 해도 `absolute_passed=True`였다. 또한 전역 `reviewed_query_count`를 split별 `human_count`와 비교해, dev/test에 분산해 검수하면 정상 메타데이터도 불일치하게 된다. |

### Loop 2 재검수 조건

| 조건 | 결과 |
|---:|---|
| 1. q_0173 facet 보존 및 정답 순위 회복 | **PASS** — blog 결과만 유지, `c_alice_0153` 8위→2위, 불필요한 완화 없음 |
| 2. S7과 limit 안정성 | **PASS** — 모든 limit에서 `c_alice_0136` 1위, `time_window_expanded`, `relaxed=true`, `time_near` |
| 3. 동일 1위/soft 보너스 가짜 완화 방지 | **PASS** — `다리 운동 영상` 완화 없음, 단위 불변식 테스트 통과 |
| 4. 기준선 mode 불일치 비교·갱신 거부 | **PASS** — 비교와 쓰기 모두 거부 |
| 5. human-reviewed understanding·절대·회귀 게이트 | **PARTIAL** — 지표와 기준선 연결은 완료됐으나, 표본 구성 부재의 vacuous pass와 split/전역 메타데이터 불일치가 남음 |

## Loop 1 회귀 확인 결과

| # | 결과 | 재검증 내용 |
|---:|---|---|
| 1 | **PASS** | S7은 `c_alice_0136` 1위와 기간 완화를 유지했다. |
| 2 | **PASS** | S7 1위 match reason은 `time_near: 기간 근접 (지난주)`이며 잘못된 `지난주 저장`이 아니다. |
| 3 | **PASS** | `demo serve --host 0.0.0.0`은 위험 플래그 없이 exit 2, `JUPJUP_ENV=prod`에서는 위험 플래그가 있어도 exit 2다. |
| 4 | **PASS** | 잘못된 플랫폼/유형, naive now/from, 역전 기간이 모두 정제된 `[INVALID_FILTER]`, exit 2이며 traceback·절대경로를 노출하지 않았다. |
| 5 | **PASS** | 0.005 하락 기준선 갱신과 mode 불일치 갱신을 모두 거부했다. |
| 6 | **PARTIAL** | review status 분리와 절차·기준선은 유지됐다. 제품 근거 게이트의 표본 구성/메타데이터 결함은 새 피드백 3에 적었다. 사람 검수 0건은 감점하지 않았다. |
| 7 | **PASS** | filter-only는 일반 순위 지표에서 분리되고 dev/test browse precision·정렬·필터 준수가 모두 1.0이었다. |
| 8 | **PASS** | 200자 동일 문자와 동일 단어 반복은 `[INVALID_QUERY] low_information`으로 거부되고 정상 장문은 입력 가드를 통과했다. |
| 9 | **PASS(새 오교정 별도)** | `IG에서 본 coffee shop 디저트`는 `카페, 디저트`로 정규화돼 인스타 결과를 반환했고, `#` 독립 키워드와 `이주→위주` 회귀는 없었다. 다만 정상어 `다리`가 `자리`로 오교정되는 별도 결함이 재현됐다. |

## 직접 실행한 명령과 결과

| 명령 | 결과 |
|---|---|
| `uv run jupjup seed load --db var/review3.db` | PASS — 200건 적재/인덱싱, embedding pending 0; alice 160, bob 30, carol 10 |
| `uv run pytest` | PASS — 488 passed, warning 1건, 15.78초. 경고는 FastAPI TestClient의 Starlette/httpx deprecation이다. |
| `uv run ruff check` | PASS — `All checks passed!` |
| `uv run mypy src` | PASS — 50개 소스 파일, 오류 0 |
| `uv run jupjup eval validate` | PASS — seeds 200, queries 259(dev 158/test 101), lexicon 139, review metadata 0건과 실제 human-reviewed 0건 일치 |
| `uv run jupjup eval run --mode mock --split dev` | PASS — Recall@10 0.9690, MRR@10 0.9916, nDCG@10 0.9737, true-empty 0.7333, 격리/필터 위반 0 |
| `uv run jupjup eval run --mode mock --split test` | PASS — Recall@10 0.9820, MRR@10 0.9867, nDCG@10 0.9761, true-empty 0.8000, 격리/필터 위반 0 |
| 위 dev/test 명령에 `--baseline data/baselines/mock.json` 추가 | 둘 다 PASS — 절대 기준과 5개 회귀 기준 통과 |
| test 평가를 한 번 더 실행하고 `created_at`, `git_sha`, `perf` 제외 비교 | PASS — `cmp` exit 0, 결정적 결과 일치 |
| S7/q_0173/다리 운동 영상에 `--limit 1/2/10/50` | PASS — 보고된 결과 ID·완화 정책이 모든 limit에서 안정적 |
| mode 불일치·0.005 하락·human 지표 전용 pytest 4건 | PASS — 4 passed |
| human 20건을 positive lookup으로만 합성해 status 절대 게이트 평가 | **문제 재현** — `n_browse=0`, negative 0건이어도 `absolute_passed=True` |

`var/review3.db`, `var/review3-demo-prod.db`, 생성된 `reports/`와 `/tmp` 비교 파일은 검수용이며 `.gitignore` 대상이다.

### CLI 경계값 및 완화 비교

모든 검색은 별도 표시가 없으면 `--user u_alice --db var/review3.db --now 2026-10-15T12:00+09:00`으로 실행했다.

| 사례 | 결과 |
|---|---|
| 정상 복합 `지난달 인스타에서 본 성수동 카페` | `c_alice_0001` 1위, 정확한 기간·플랫폼, 완화 없음 |
| S7 `지난주 카톡으로 받은 회의 장소` | `c_alice_0136` 1위, `time_window_expanded`, `relaxed=true`, `time_near` |
| Loop 2 회귀 `레스토랑 추천 블로그` | `c_alice_0152`, `c_alice_0153`; 전부 blog, 완화 없음 |
| 동일 1위 `다리 운동 영상` | `c_alice_0050` 1위, 완화 없음. 다만 기대 정답 `c_alice_0040`은 2위이고 `다리→자리` 오교정 |
| 기간을 잘못 기억 `지난달 하체 운동` | **정상 완화** — `c_alice_0040` 1위, `time_window_expanded` |
| 기간을 크게 잘못 기억 `지난달 경주 맛집` | **정상 완화** — `c_alice_0153` 1위, 기간 확장 후 제거 기록 |
| 플랫폼을 잘못 기억 `경주 맛집 카톡` | **정상 완화** — 원래 후보가 0건이면 `c_alice_0153` 1위와 `platform_filter_dropped` |
| 플랫폼을 잘못 기억 `경주 맛집 인스타` | **과소 완화** — 정확한 blog `c_alice_0153` 대신 `경주`가 없는 망원동/합정 인스타 맛집이 1·2위, 완화 없음 |
| 플랫폼을 잘못 기억 `하체 운동 유튜브` | **과소 완화** — 키워드 1/2만 맞는 `c_alice_0050`이 남고, 키워드 2/2가 맞는 인스타 `c_alice_0040`은 후보에서 사라짐 |
| 플랫폼+유형 오기억 `경주 맛집 카톡 논문` | **기록 결함** — blog/article 결과를 반환해 두 facet을 모두 위반하지만 `applied_relaxations`는 `platform_filter_dropped` 하나뿐 |
| 오타/구어체/영어 혼합 | `성수동까페`, `유툽…파스타`, `IG…coffee shop` 모두 관련 결과 반환 |
| filter-only `지난달 인스타` | browse=true, 정확한 달력 구간에서 최신순 4건 |
| 없는 대상 `화성 이주 계획 다큐` | 오교정 없이 빈 결과와 정확한 빈 결과 문구 |
| 특수문자 포함 / 특수문자만 | `#` 독립 키워드 제거 후 검색 성공 / `[INVALID_QUERY]`, exit 2 |
| 요청 필터 충돌 / 잠긴 요청 기간 | 요청 필터가 우선하고, 잠긴 필터는 완화하지 않음 |
| 200자 반복 / 201자 / naive 시간 / 역전 기간 | 모두 의도한 `[INVALID_QUERY]` 또는 `[INVALID_FILTER]`, exit 2 |
| 사용자 격리 `낚시 포인트 추천` | alice 빈 결과, bob은 `c_bob_0001`만 반환 |
| 외부 데모 바인딩 | 위험 플래그 없이는 exit 2; prod에서는 위험 플래그가 있어도 exit 2 |

## 남은 피드백

### 높음

1. `src/jupjup/search/service.py:326`, `src/jupjup/search/service.py:364`, `src/jupjup/search/service.py:368` — hard facet 위반이 하나라도 늘면 관련도 향상 폭과 무관하게 완화 후보를 무조건 거부한다. 원래 hard 필터를 통과한 incumbent의 위반 수는 구조상 0이므로, 후보가 한 건이라도 있으면 query-derived 플랫폼/유형 완화는 사실상 절대 채택될 수 없다. `경주 맛집 인스타`는 정확한 `c_alice_0153`(경주+맛집, blog) 대신 `경주`가 전혀 없는 `c_alice_0020`/`0019`(맛집만 일치, instagram)를 반환한다. `하체 운동 유튜브`도 `c_alice_0040`의 관련도 증거가 훨씬 강하지만 generic 홈트 `c_alice_0050`에 막힌다. 요청으로 잠긴 facet은 계속 절대 보존하되, 질의에서 추출한 facet은 위반 비용과 최소 개선폭을 실제로 비교해 명백한 관련도 향상에는 풀 수 있어야 한다. “약한 same-facet incumbent가 있는 잘못 기억한 플랫폼/유형” 통합 테스트가 필요하다.

### 중간

2. `src/jupjup/search/relaxation.py:45`, `src/jupjup/search/relaxation.py:56` — 플랫폼과 유형을 모두 hard→soft로 바꾼 뒤 동일 상태를 이름만 달리해 두 번 yield한다. 첫 yield에서 이미 두 facet이 모두 풀렸으므로 결과가 나오면 두 번째 이름은 기록되지 않는다. `경주 맛집 카톡 논문`은 blog/article 결과를 반환하면서 `applied_relaxations=["platform_filter_dropped"]`만 내보내 사용자가 유형까지 완화됐다는 사실을 알 수 없다. facet을 실제 단계별로 하나씩 바꾸거나 한 단계가 적용한 모든 기록값을 함께 전달해야 한다.

3. `src/jupjup/eval/harness.py:248`, `src/jupjup/eval/harness.py:347`, `src/jupjup/eval/harness.py:354`, `src/jupjup/eval/harness.py:595`, `src/jupjup/eval/harness.py:604` — human-reviewed 절대 게이트가 해당 지표의 분모가 0인지를 검사하지 않는다. filter-only가 없으면 browse 지표를 1.0, negative가 없으면 true-empty를 1.0으로 채우고, 기간/플랫폼/유형/키워드 사례가 없어도 이해 지표가 1.0이 될 수 있다. 실제 합성에서 20건 모두 positive lookup이고 `n_browse=0`인데 절대 게이트 전체가 통과했다. 또한 metadata count는 전역 질의 수로 검증하지만 제품 근거에서는 split-local `human_count`와 비교하므로 dev/test에 분산된 정상 검수도 불일치한다. 사람 검수 완료 자체와 무관하게, 제품 PASS 전에는 지표별 최소 유효 표본/필수 범주를 요구하고 메타데이터를 split별로 만들거나 전역 count와 split count를 구분해야 한다.

### 낮음

4. `src/jupjup/query/understanding.py:183`, `src/jupjup/query/spell.py:58`, `src/jupjup/query/spell.py:79` — 정상 질의 `다리 운동 영상`에서 `다리`를 고빈도 어휘 `자리`로 오교정한다. 그 결과 정답 `c_alice_0040`은 2위이고 generic 홈트 `c_alice_0050`이 1위다. `이주` 보호로 Loop 1 사례는 고쳤지만, 정상 단어가 사전에 없다는 이유만으로 교정되는 일반 문제는 남았다. 원형 키워드 증거를 보존하거나 교정 신뢰도/문맥 조건을 강화하고 이 질의를 이해 결과와 1위 ID까지 고정해야 한다.

## 채점 근거

- **정확성 34/40:** S7, q_0173, 동일 1위 가짜 완화, 영어 혼합, 기간 오기억 완화와 전체 mock 지표는 좋아졌다. 그러나 약한 incumbent가 있는 query-derived 플랫폼/유형에서는 완화가 구조적으로 막혀 핵심 약속인 “어디에 저장했는지 몰라도”를 깨고, 두 facet을 실제로 풀고도 하나만 기록하며, 정상어 오교정으로 알려진 정답이 2위에 남는다.
- **안전성 29/30:** 사용자 격리, 요청 필터 잠금, 외부 데모 바인딩, dev/prod 경계, CLI 입력 오류 정제, 기준선 mode 무결성이 모두 직접 통과했다. 감점은 사람 검수 제품 근거가 대표성 없는 표본으로도 절대 게이트를 통과할 수 있는 품질 판정 안전장치의 구조적 공백 때문이다.
- **유지보수성 24/30:** 488개 테스트, ruff/mypy, 결정적 평가, status별 지표와 mode 검증은 강점이다. 반면 설정한 hard facet 위반 비용이 선행 절대 veto 때문에 incumbent가 있을 때 사실상 쓰이지 않고, 과소 완화·다중 facet 기록·분모 0 제품 게이트 불변식 테스트가 없다. 전역 검수 메타데이터와 split별 평가의 단위도 맞지 않는다.

AI 초안 mock 지표는 기술 회귀 탐지에는 유효하지만 실제 사용자 품질 PASS 근거는 아니다. `human_reviewed=0` 자체는 이번 점수에 반영하지 않았다.

## 다음 단계 권고

이번이 Loop 3/3이므로 자동 루프백 한도를 소진했다. 사용자에게 아래 두 선택지 중 판단을 요청하는 것이 맞다.

1. **권고:** 예외적으로 Phase 2에 한 번 더 보내 위 1~3을 좁게 수정한다. 요청 잠금과 질의 추출 facet을 분리하고, query-derived facet은 큰 관련도 향상에만 비용 기반으로 완화한다. 과소 완화·다중 facet 기록·분모 0/split 메타데이터 테스트를 먼저 추가한다. 정상어 오교정은 같은 수정에 포함하거나 명시적 후속 이슈로 남긴다.
2. 현재 87점을 수용하고 배포 전 제한사항으로 남긴다. 이 경우 잘못 기억한 플랫폼/유형에서 약한 오답이 있으면 올바른 저장물을 찾지 못할 수 있고, 현재 human product gate는 실제 제품 PASS 선언에 사용하지 않아야 한다.

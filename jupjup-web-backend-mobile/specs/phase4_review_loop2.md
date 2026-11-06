# Phase 4 최종 검수 — Loop 2

- **점수:** 88 / 100 (정확성 34 / 40, 안전성 29 / 30, 유지보수성 25 / 30)
- **상태:** REJECT
- **루프백 대상:** Phase 2

## 검수 범위

- 포함: Loop 1 피드백 1~9의 구현, 관련 `src/`, `tests/`, `data/golden`, `data/baselines`, T0~T14 및 filter-only browse 경로
- 범위 외: T15 정식 FastAPI API, T17 실제 제공자, T18 이후 인제스트 전 범위
- `human_reviewed` 평가는 아직 0건이므로 미완료 자체는 감점하지 않았다. 대신 review status 분리, 검수 절차, 별도 기준선과 향후 제품 PASS 판정 구조가 실제로 연결되는지만 검수했다.
- 조치 보고서의 완료 주장은 근거로 사용하지 않고 코드, 데이터, 테스트와 CLI를 직접 확인했다.

## Loop 1 피드백 해결 여부

| # | 판정 | 직접 검증 결과 |
|---:|---|---|
| 1 | **부분 해결** | 명시적 S7은 `c_alice_0136` 1위, `time_window_expanded`, 결과별 `relaxed=true`로 복구됐고 limit 1/2/10/50에서도 1위가 안정적이었다. 그러나 일반화한 후보 비교가 query hard facet을 과도하게 풀어 정상 결과를 밀어내는 새 오답을 만든다. `레스토랑 추천 블로그`는 완화 전 블로그 문서가 1·2위인데도 플랫폼을 풀어 카카오톡 `c_alice_0145`를 1위로 올리고 정답 `c_alice_0153`을 8위로 내린다. |
| 2 | **해결** | S7의 기간 밖 결과는 `time_near: 기간 근접 (지난주)`로 표시되며 `지난주 저장`을 재사용하지 않았다. exact 기간 일치는 기존 `time` 근거를 유지한다. |
| 3 | **해결** | `0.0.0.0`, `::`, 사설 IP, hostname은 위험 플래그 없이는 거부되고 loopback만 기본 허용된다. `--allow-external-bind`를 주어도 `JUPJUP_ENV=prod`이면 dev/test 제한으로 exit 2다. 환경 강제 덮어쓰기도 제거됐다. |
| 4 | **해결** | 잘못된 플랫폼/유형, 비 ISO 시각, naive `--now/--from/--to`, 역전 기간이 모두 `[INVALID_FILTER]`, exit 2이며 traceback과 워크트리 절대경로를 노출하지 않았다. |
| 5 | **해결(새 결함 별도)** | 기존 기준선보다 0.005 낮춘 Recall@10 갱신은 거부됐다. 다만 기준선과 리포트의 mode 일치 검증이 없어 mock 기준선을 recorded 리포트로 바꾸는 새 무결성 문제가 있다. |
| 6 | **부분 해결** | AI 초안 235건, 사람 검수 대기 challenge 24건, human-reviewed 0건을 분리하고 group split 검증, 2인 블라인드/제3자 조정/kappa 절차, 별도 human 기준선 파일을 마련했다. 그러나 human-reviewed 부분집합의 기간·플랫폼 등 understanding 지표와 절대 게이트가 없어 문서에 적힌 제품 PASS 절차를 하네스가 아직 완결하지 못한다. 사람 검수 0건 자체는 감점하지 않았다. |
| 7 | **해결** | filter-only 16건은 일반 Recall/MRR/nDCG와 category minimum에서 빠지고 precision@10, 최신순, 필터 준수, coverage로 별도 집계된다. dev/test에서 precision·정렬·준수 1.0, coverage 0.9167을 확인했다. |
| 8 | **해결** | `"가"*200`, `"카페 "*50`은 `[INVALID_QUERY] low_information`으로 거부됐다. 정상 장문 질의는 거부되지 않고 검색 경로로 들어갔다. 확인한 정상 질의에서 가드 오탐은 재현되지 않았다. |
| 9 | **해결** | `IG에서 본 coffee shop 디저트`는 `카페, 디저트`로 정규화되고 인스타 결과를 반환했다. `#`는 독립 키워드로 남지 않았고 `화성 이주 계획 다큐`의 `이주`도 오교정되지 않았다. |

## 직접 실행한 명령과 결과

| 명령 | 결과 |
|---|---|
| `uv run jupjup seed load --db var/review2.db` | PASS — 200건 적재/인덱싱, embedding pending 0; alice 160, bob 30, carol 10 |
| `uv run pytest` | PASS — 473 passed, warning 1건, 14.80초. 경고는 기존 FastAPI TestClient의 Starlette/httpx deprecation이다. |
| `uv run ruff check` | PASS — `All checks passed!` |
| `uv run mypy src` | PASS — 50개 소스 파일, 오류 0 |
| `uv run jupjup eval validate` | PASS — seeds 200, queries 259(dev 158/test 101), lexicon 139; AI 초안 235, 사람 검수 대기 24 |
| `uv run jupjup eval run --mode mock --split dev` | PASS — Recall@10 0.9690, MRR@10 0.9916, nDCG@10 0.9737, true-empty 0.7333, 격리/필터 위반 0 |
| `uv run jupjup eval run --mode mock --split test` | PASS — Recall@10 0.9820, MRR@10 0.9817, nDCG@10 0.9714, true-empty 0.8000, 격리/필터 위반 0 |
| 위 dev/test 명령에 `--baseline data/baselines/mock.json` 추가 | 둘 다 PASS — 5개 회귀 기준 통과 |
| 같은 S7을 `--limit 1/2/10/50`로 실행 | 모두 `c_alice_0136` 1위와 `time_window_expanded` 유지 |
| 완화 전후 후보를 동일 컨테이너에서 비교 | `레스토랑 추천 블로그`: 완화 전 blog `0152,0153`, 현재 결과는 platform drop 후 `0145`(kakaotalk) 1위, 정답 `0153` 8위 |
| 임시 기준선에 0.005 낮춘 Recall@10으로 `update_baseline` 호출 | 정상 거부 — `recall@10 0.964 < 0.969679` |
| mock 기준선 사본에 `config.mode=recorded` 리포트로 `update_baseline` 호출 | **문제 재현** — 갱신 성공, 저장된 mode가 `recorded`로 변경됨 |

`var/review2.db`와 생성된 `reports/`는 `.gitignore` 대상이며 커밋하지 않았다.

### CLI 경계값 재검증

모든 검색은 별도 표시가 없으면 `--user u_alice --db var/review2.db --now 2026-10-15T12:00+09:00`으로 실행했다.

| 사례 | 결과 |
|---|---|
| 정상 복합 `지난달 인스타에서 본 성수동 카페` | `c_alice_0001` 1위, 기간·플랫폼 해석 정상 |
| S7 `지난주 카톡으로 받은 회의 장소` | `c_alice_0136` 1위, `time_window_expanded`, `relaxed=true`, `time_near` 근거 |
| 오타 `성수동까페` | `까페→카페` 교정, 관련 결과 반환 |
| 구어체 `유툽에서 본 파스타 레시피 그거` | youtube hard 추출, 관련 레시피 반환 |
| 필터 전용 `지난달 인스타` | browse=true, 정확한 달력 구간에서 최신순 4건 |
| 없는 대상 `화성 이주 계획 다큐` | 오교정 없이 빈 결과와 정확한 빈 결과 문구 |
| 특수문자 포함 `성수동!!! 카페??? #맛집` | `#` 독립 키워드 제거, 검색 성공 |
| 특수문자만 | `[INVALID_QUERY]`, exit 2, traceback 없음 |
| 영어 혼합 `IG에서 본 coffee shop 디저트` | `카페, 디저트`로 정규화, 인스타 결과 반환 |
| 요청 필터 충돌 + `--platform youtube` | 요청 필터 우선, youtube 결과만 반환 |
| 잠긴 요청 기간에 결과 없음 | 필터 완화 없이 빈 결과, `applied_relaxations=[]` |
| 200자 동일 문자 / 동일 단어 반복 | `[INVALID_QUERY]`, exit 2 |
| 정상 장문 `서울에서 조용하고 콘센트 많고 작업하기 좋은 카페 추천` | 입력 가드는 통과. 결과는 0건이지만 정상 질의를 거부하지 않음 |
| 201자 / naive `--now` / 역전 기간 | 모두 `[INVALID_QUERY]` 또는 `[INVALID_FILTER]`, exit 2, traceback 없음 |
| 사용자 격리 `낚시 포인트 추천` | alice는 빈 결과, bob은 `c_bob_0001`만 반환 |
| 잘못된 `--platform tiktok` | `[INVALID_FILTER]`, exit 2, traceback·절대경로 없음 |
| 외부 데모 바인딩 | 위험 플래그 없이는 exit 2; prod에서는 위험 플래그가 있어도 exit 2 |

## 새 피드백

### 높음

1. `src/jupjup/search/service.py:211`, `src/jupjup/search/service.py:240`, `src/jupjup/search/service.py:254`, `src/jupjup/search/service.py:284` — 약한 후보를 보완하려 만든 비교가 질의의 hard facet을 과도하게 풀어 오답을 앞세운다. `_candidate_quality`에는 원래 hard 플랫폼/유형 일치가 없고, `kw_coverage`, strong-field 여부, vector가 우선하므로 facet을 위반한 문서가 쉽게 승리한다. 실제 `q_0173`의 `레스토랑 추천 블로그`는 완화 전 blog `c_alice_0152`, 정답 `c_alice_0153` 순인데, 현재는 `platform_filter_dropped` 후 카카오톡 피부과 추천 `c_alice_0145`가 1위이고 정답은 8위다. AI test 리포트에도 Success@1=0, MRR@10=0.125로 남아 있지만 전체 평균 게이트가 이를 숨긴다. 후보 비교에 원래 hard facet 보존/위반 비용과 시간 exact 여부를 명시적으로 넣고, 기존 유효 후보가 있으면 완화가 의미 있는 관련도 향상을 증명할 때만 교체해야 한다. `q_0173`처럼 정상 facet 결과가 있는 사례와 S7을 함께 고정하는 결과 ID·순위·완화 내역 통합 테스트가 필요하다.

### 중간

2. `src/jupjup/search/service.py:254`, `src/jupjup/search/rerank.py:92`, `src/jupjup/search/rerank.py:120` — 서로 다른 필터 문맥의 `final_score`를 후보 품질 tuple의 마지막 값으로 직접 비교해 순위 비교가 동질적이지 않다. `다리 운동 영상`에서는 완화 전후 1위가 같은 `c_alice_0050`이고 핵심 증거도 동일하지만, content type을 hard에서 soft로 바꾸자 같은 후보의 `facet_soft`가 0→1, final score가 1.4566→1.5566으로 올라 `content_type_filter_dropped`가 적용되고 전 결과가 `relaxed=true`가 된다. 사용자가 실제로 얻은 상위 결과 개선 없이 완화 사실을 잘못 알리는 셈이다. 비교 특징은 검색 문맥과 무관하게 계산하거나 동일한 원래 해석 기준으로 재채점하고, 동일 1위/동일 관련성에는 완화를 채택하지 않는 최소 개선폭·tie 규칙을 둬야 한다.

3. `src/jupjup/eval/harness.py:563`, `src/jupjup/eval/harness.py:567`, `src/jupjup/eval/harness.py:593` — 기준선 갱신이 기존 `BaselineFile.mode`와 `report.config.mode`의 일치를 확인하지 않고 마지막에 report mode로 덮어쓴다. mock 기준선 사본에 recorded 리포트를 넣은 재현에서 갱신이 성공하고 파일 mode가 `recorded`로 바뀌었다. CLI의 `--baseline` 경로 실수만으로 서로 다른 제공자 모드의 기준선 이력이 섞일 수 있다. mode 불일치는 비교와 쓰기 전에 거부하고, 같은 검증을 `compare`에도 적용하는 테스트가 필요하다.

4. `src/jupjup/eval/harness.py:278`, `src/jupjup/eval/harness.py:306`, `src/jupjup/eval/harness.py:329`, `src/jupjup/eval/harness.py:344`, `src/jupjup/eval/harness.py:518`, `src/jupjup/eval/harness.py:540` — review status별 분리는 순위·browse 지표에만 적용되고 기간/플랫폼/유형/키워드 understanding은 AI 초안에만 누적된다. 절대 게이트도 항상 AI 초안 `overall`/공통 `understanding`을 사용하며, `product_evidence.eligible`은 human-reviewed 건수가 1개 이상인지만 본다. 따라서 사람이 검수한 데이터가 생겨도 `mock.human_reviewed.json`에는 설계상 주요 회귀 키인 `time_exact`, `platform_f1`을 만들 수 없고, `REVIEW_GUIDE.md`의 “human-reviewed 절대 기준과 회귀 기준 모두 통과”를 자동 판정할 수 없다. 미완료 인력 작업은 감점하지 않았지만, 제품 PASS를 선언하기 전에는 understanding과 절대/회귀 게이트를 review status별로 계산하고 최소 표본·검수 메타데이터 조건까지 연결해야 한다.

## 채점 근거

- **정확성 34/40:** S7, 기간 근거, 영어 혼합, 특수문자, filter-only 분리는 실제로 고쳐졌고 dev/test 기술 지표도 통과한다. 그러나 새 완화 비교가 hard 플랫폼을 불필요하게 풀어 명백한 오답을 1위로 올리고 정답을 8위로 미는 회귀가 있어 핵심 검색 정확성에서 감점했다.
- **안전성 29/30:** 사용자 격리, 요청 필터 잠금, 외부 데모 바인딩, 환경 제한, CLI 오류 정제가 모두 직접 검증됐다. 다만 평가 mode가 다른 기준선으로 덮어써지는 품질 기준선 무결성 우회가 남았다.
- **유지보수성 25/30:** 473개 테스트, ruff/mypy, review status 스키마, browse 지표 분리는 좋다. 반면 문맥 의존 점수를 교차 비교하는 완화 로직의 불변식 테스트가 없고, human-reviewed 제품 게이트 및 기준선 mode 검증이 완결되지 않았다.

AI 초안 mock 지표는 회귀 탐지용 기술 지표일 뿐 실제 사용자 품질 근거가 아니다. challenge의 사람 검수 대기 지표는 dev Recall@10 0.75, test 0.50 수준이며, 사람 판정 전에는 튜닝·PASS 근거로 사용하면 안 된다.

## 루프백 이유와 재검수 조건

**Phase 2로 루프백한다.** 주된 실패가 코드 미관이 아니라 완화 정책이 정상 facet 결과를 버리고 오답을 선택하는 검색 기능 회귀이기 때문이다.

재검수 전 최소 조건:

1. `레스토랑 추천 블로그`에서 원래 blog 결과를 유지하고 `c_alice_0153`이 현재보다 악화되지 않으며, 불필요한 `platform_filter_dropped`가 발생하지 않는 통합 테스트를 추가한다.
2. S7은 계속 `c_alice_0136` 1위, `time_window_expanded`, `relaxed=true`, `time_near`를 유지한다. 후보 수와 limit 변화에도 선택이 안정적이어야 한다.
3. 같은 1위와 같은 핵심 증거에 soft-facet 보너스만 생긴 경우 완화를 채택하지 않고, 완화 전후 점수 비교를 동일 기준에서 수행하는 단위 테스트를 추가한다.
4. 기준선과 평가 리포트 mode가 다르면 비교·갱신을 모두 거부하는 테스트를 추가한다.
5. human-reviewed 데이터가 들어왔을 때 understanding, 절대 게이트, 회귀 게이트가 해당 부분집합만으로 계산되는 구조를 완성한다. 실제 사람 검수 완료 자체는 이번 재검수 조건이 아니다.

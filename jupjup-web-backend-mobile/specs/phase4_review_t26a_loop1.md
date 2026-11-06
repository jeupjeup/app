# Phase 4 최종 검수: T26a compare_profiles와 compare-profiles CLI, Loop 1/3

- **점수:** 93 / 100
- **상태:** PASS
- **항목별:** 정확성 38 / 40, 안전성 27 / 30, 유지보수성 28 / 30
- **루프백 대상:** 없음 (PASS). M1(비유한 값이 판정을 통과시킴)은 **T25h에서 실제 리포트 쌍을 처음 비교하기 전에** 고치길 권한다. L1~L6은 다음에 같은 파일을 만질 때 고치면 된다.
- **검수 대상:** `fd68dbd feat: T26a compare_profiles (downgrade/upgrade swap rules, paired bootstrap, refusal checks) and eval compare-profiles CLI` (기준 `8db3dee`)
- **검수자:** Claude-Reviewer 역할 대행 (Claude Opus 5.5). 코드는 고치지 않았다. 재현 실험은 스크래치 디렉터리(탐침 스크립트, `8db3dee` 임시 detached worktree, 손으로 만든 리포트·벤치 JSON)와 `var/review.db`에서만 했다. 임시 worktree와 `var/review.db`는 끝나고 지웠다.
- **범위 밖:** T25h(실제 모델 녹화·튜닝, 실제 프로필 리포트 쌍). 사람 검수 미완료, 실제 로컬 모델 호출이 없는 것은 감점하지 않았다.

## 0. 한 줄 판정

10.1절 T26a 완료 조건 네 개(두 방향 규칙, 부트스트랩 결정성, 비교 거부 조건, 손으로 만든 리포트 쌍 테스트)를 **모두 직접 재현했다.** 부트스트랩 구간은 내가 따로 짠 재표집 + `numpy.percentile`과 소수 6자리까지 같았고(결측 건 포함), 같은 seed 두 번은 `SwapDecision` JSON이 바이트 동일, 경계값(태그 F1 하락 정확히 0.03, 비충실 증가 정확히 0.01, 자원 개선 정확히 30%)은 설계대로 통과 쪽이다. 거부 조건은 CLI에서 모두 종료 2로 끝난다.
기본 게이트도 통과했다: pytest **1266 passed, skip 0**, ruff, mypy(90 파일), `eval validate`·`validate-ingest`, 검색 eval 4종(기준 커밋 사본과 시각·지연·경로 외 차이 없음), mock 인제스트 6개(v1·v2 × dev·test·all)가 두 번 실행끼리, 그리고 **기준 커밋 사본과도 바이트 동일**. `llama_cpp`는 import되지 않고, 새 모듈은 표준 라이브러리 `random`과 pydantic만 쓴다.
감점은 중간 문제 하나(M1)와 작은 문제 여섯에서 나왔다. M1: 리포트 JSON의 건별 지표에 `NaN`이 들어오면(pydantic은 JSON의 `NaN`·`Infinity` 리터럴을 받아들인다) 델타·구간이 `nan`이 되고, `nan > 허용치`가 거짓이라 **허용치 검사를 조용히 통과해 "교체 후보 (eligible)"가 나온다.** 벤치의 `peak_rss_mb: -Infinity`도 자원 개선 `+inf%`로 통과한다. 모델 교체 게이트는 깨진 입력에서 닫혀야 한다.

## 1. 직접 실행한 명령과 결과

### 1.1 기본 게이트 (프로젝트 venv, extra 없음)

| 명령 | 결과 |
|---|---|
| `uv run pytest` (`--junitxml`로 요약 확인) | 종료 0, **tests=1266, failures 0, errors 0, skipped 0** (기본 마커 제외 4건은 deselect). AC-L1 |
| `uv run ruff check src tests` | All checks passed! |
| `uv run mypy src` | Success: no issues found in 90 source files |
| `uv run jupjup eval validate` / `eval validate-ingest` | 둘 다 종료 0 |
| `eval run --mode mock\|recorded --split dev\|test` | 4개 모두 종료 0 |
| 위 4개 JSON을 `8db3dee` 임시 worktree 결과와 재귀 비교 (`created_at`, `git_sha`, `config`, 지연 필드 제외) | 4개 모두 **지표 동일** → 검색 수치 무회귀 |
| `eval ingest --mode mock --golden v1\|v2 --split dev\|test\|all` 새 코드 2회 + 기준 사본 1회 | 18회 모두 종료 0. 6개 출력 디렉터리가 1회 대 2회, 1회 대 사본 **모두 `diff -rq` 동일** (AC-L2, 핵심 사항 2) |
| `git diff --stat 8db3dee HEAD -- src/jupjup/search src/jupjup/query data/` | **0줄** |
| `import jupjup.cli, jupjup.eval.ingest_compare, jupjup.eval.ingest_harness` 뒤 `sys.modules` | `llama_cpp` False, `requests`·`httpx`·`urllib3`·`huggingface_hub` 없음 (AC-L8, AC-L16) |
| `ingest_compare.py` import 목록 | `random`, `collections.abc`, `pathlib`, `typing`, `pydantic`, `jupjup.eval.ingest_bench`, `jupjup.eval.ingest_harness`뿐. 소켓·HTTP 없음, 모델 호출 없음 |
| `pytest tests/unit/test_ingest_compare.py tests/integration/test_ingest_record_replay.py -k golden_hash` | 통과. 실제 MockLLM recorded dev 리포트(48건)에 `golden_sha256`이 있고 `compute_split_digest(dev)`와 같음, test 해시 = `compute_test_seal` = 커밋된 `test.sha256`, 자기 자신과 비교 시 델타·구간 모두 0, mock 리포트는 키 없음 + 비교 거부 |

### 1.2 T26a 완료 조건 재현 (10.1절, AC-29, AC-L7)

| 완료 조건 | 직접 확인 | 판정 |
|---|---|---|
| 두 방향 규칙 | 코드(`ingest_compare.py:227-335`)를 8.6절·PRD 3.5.5절 4번과 줄 단위로 대조. **downgrade**: 후보의 3.5.4절 절대 기준 전부(`LOCAL_GATE` 10행 + recorded 검색 연결 하락 ≤ 0.03), 허용치 5개(태그·엔티티·장소 F1 0.03, 비충실 증가 0.01, 검색 연결 R@10 0.02)의 점추정과 구간 나쁜 쪽 끝, 자원 개선 최댓값 ≥ 30%. **upgrade**: 절대 기준 + 주요 지표 4개 중 하나의 구간이 개선 쪽에 완전히 있음(비충실은 상한 < 0, 나머지는 하한 > 0) + 허용치 + 후보 single p95 예산. 탐침: 태그 F1 −0.03 정확히, 비충실 +0.01 정확히 → eligible(“≤”). 비충실 감소는 하락으로 세지 않음, map_reduce 초과는 경고만(8.6절은 single만 본다) | 충족 |
| 부트스트랩 결정성(seed) | 탐침: 40건 무작위 쌍 2지표(한 지표는 7건마다 후보 결측), n_boot 500, seed 42. 독립 재구현 + `numpy.percentile` 2.5/97.5와 **6자리까지 같음** (a: −0.210582 / 0.086015, b: −0.056305 / 0.22788). 같은 seed `compare_profiles(...).model_dump_json()` 두 번 바이트 동일. 48건 × 8지표 × 1000회 0.02초 | 충족 |
| 비교 거부 조건 | 8.6절의 split·골든셋 해시·판정기 프로필 + 확장분(mock, 녹화 미스, 판정기 모델·프롬프트·보정 상태, 판정기 블록 한쪽, 건 목록 불일치·중복·빈 목록, 벤치 프로필·모델 불일치, 벤치 split 불일치)이 `CompareRefused(ValueError)`로 나뉘어 있고 단위 테스트 parametrize로 고정. CLI: 없는 파일 → 종료 2, `--direction sideways` → 2, `--n-boot 0` → 2(typer `min=1`), `{}` JSON → 2 "비교 입력 오류: config: Field required", 벤치 한쪽만 → 2. 트레이스백 없음 | 충족 |
| 손으로 만든 리포트 쌍 테스트 | `tests/unit/test_ingest_compare.py` 39건이 BASE + shift/jitter로 리포트를 만들고 overall을 건별 평균에 맞춘다. downgrade 4지표 각각의 점추정 초과, 구간만 초과, 검색 연결 초과, 30% 경계(20% 불가·30% 통과), 벤치 없음, 비용 경로, upgrade 개선·비개선·허용치·61초·벤치 없음, 경고, 거부, CLI 종료 0/1/2를 모두 단언 | 충족 |

### 1.3 CLI와 경계값 탐침 (손으로 만든 리포트·벤치 JSON)

| 입력 | 결과 |
|---|---|
| 정상 쌍 + 벤치(RSS −40%, p95 −20%) `--out d1.json` | 종료 0, 마크다운 표 9행, `d1.json`·`d1.md` 생성 |
| 후보 리포트 건별 `tag_f1`을 JSON 리터럴 `NaN`으로 (overall은 정상) | **종료 0, "교체 후보 (eligible)"**, 표에 `tag_f1 +nan [+nan, +nan]` → **M1** |
| 후보 벤치 `peak_rss_mb: -Infinity` | **종료 0, eligible**, `peak_rss_mb: +inf%` → **M1** |
| 후보 벤치 `single.p95_s 61.0, budget_p95_s 999, within_budget true` + 주요 지표 개선 (Python API) | **eligible** → **L2** (예산을 저장된 플래그로만 판단) |
| 벤치 split `test`, 리포트 split `dev` | eligible, 경고 없음 → L3 |
| 검색 연결 `n_queries` 60 대 5, `human_recall@10` 0.91 대 0.50 | eligible, 경고 없음 → L3 |
| `--out d2.md` | JSON을 `d2.md`에 쓴 뒤 같은 경로에 마크다운을 덮어써 **JSON이 사라짐** → L4 |
| `--out <이미 있는 디렉터리>` | `IsADirectoryError` 트레이스백, 종료 1(교체 불가와 같은 코드) → L4 |
| 같은 파일을 후보·현행으로 (`upgrade`) | 종료 1, "두 리포트의 프로필이 같습니다" 경고 |
| 1건짜리 쌍 | eligible + "표본이 작습니다: 1건 < 40건" 경고 (설계는 경고만 요구. 감점 안 함) |
| 현행 리포트 10건 실패(지표 없음) | 48건 모두 쌍에 남고, 현행 평균은 38건, 후보 평균은 48건 → L5 |

### 1.4 검색 CLI 회귀·경계값 (`var/review.db`, `--now 2026-10-15T12:00+09:00`, mock·recorded)

T26a는 검색 코드를 건드리지 않았다(diff 0). 그래도 지시대로 `seed load` 뒤 12개 질의 × 2모드를 새 코드와 `8db3dee` 사본에서 `--json`으로 돌려 `query_id`·`timing_ms`만 빼고 비교했다: **24회 모두 같음.**

| 질의 | 결과 (새 코드 = 기준) |
|---|---|
| u_alice "지난달 저장한 카페" | 5건, 기간 2026-09-01~10-01 |
| "망원동 빵칩"(오타) | 3건 |
| "유튜브에서 본 요리 영상" `--platform youtube` | 6건 |
| "파이썬 asyncio 정리한 글"(영어 혼합) | 2건 |
| "x" `--platform instagram --type video`(필터 위주) | 0건, empty_state 안내 |
| "화성에 있는 스타벅스 2019년"(없는 대상) | 0건, empty_state |
| u_bob "망원동 빵집"(사용자 격리) | 0건 (alice 저장물 노출 없음) |
| 빈 문자열 / "!!!@@@###" / 긴 반복 질의 | `INVALID_QUERY` 한 줄 안내 |
| u_nobody "카페" | "저장물이 DB에 없습니다" 안내 |

## 2. 피드백 (심각도 순)

### M1 (중간, 안전성) 비유한 값(`NaN`·`±Infinity`)이 교체 판정을 통과시킨다
- `src/jupjup/eval/ingest_compare.py:263-267` `_tolerance_failures`: `point > tolerance`, `bound > tolerance`는 `nan`에서 모두 거짓이라 사유가 안 붙는다. `ingest_compare.py:253` `_improved`도 `nan`이면 거짓이라 upgrade 쪽은 닫히지만, downgrade는 열린다.
- `ingest_compare.py:271-274` `_relative_gain`: 후보 값이 `-inf`면 `+inf`, 음수 RSS·지연이면 100% 넘는 개선이 된다. `ingest_bench.py`의 `AnalyzeBenchReport`·`LatencyStats`와 `IngestItemResult.metrics`(`dict[str, float]`)가 유한성·범위를 검사하지 않고, pydantic은 JSON의 `NaN`·`Infinity` 리터럴을 받아들인다(1.3절에서 CLI로 재현).
- 지금 하네스가 `NaN`을 만들 경로는 찾지 못했다(지표는 모두 0/0을 막는다). 그래서 높음이 아니라 중간이다. 하지만 이 함수는 손으로 옮기거나 다른 기기에서 만든 JSON을 읽는 게이트이고, 깨진 입력에서 "교체 후보"를 내면 안 된다.
- **고칠 방향:** `load_report`·`load_bench` 뒤(또는 `compare_profiles` 첫머리)에서 판정에 쓰는 모든 값(건별 `ITEM_METRICS`, `overall`의 `LOCAL_GATE` 키, `search_linkage`, 벤치 `p95_s`·`peak_rss_mb`)이 `math.isfinite`이고 범위(비율 0~1, 지연·RSS > 0) 안인지 보고, 아니면 `CompareRefused`. 또는 `_tolerance_failures`에서 `not (point <= tolerance and bound <= tolerance)`처럼 닫힌 쪽으로 비교한다. `NaN` 건별 값과 `-Infinity` 벤치 테스트를 하나씩 더한다.

### L1 (낮음, 정확성) 판정 마크다운에 두 프로필의 절대값 비교표가 없다
- `ingest_compare.py:418-442` `render_swap_markdown`은 델타·구간·허용치만 낸다. PRD 3.5.5절 3번은 "기본 프로필 기준선과 후보를 **같은 표로** 낸다 (3.5.2절 전 지표, 비용, 지연)"이고, 6번은 이 비교 리포트를 붙여 사용자 승인을 받는다. 지금은 절대 기준을 **못 넘은** 지표만 사유에 값이 보이고, 통과한 지표의 후보·현행 값은 마크다운에도 `SwapDecision` JSON에도 없다.
- **고칠 방향:** `SwapDecision`에 `candidate_overall`·`incumbent_overall`(3.5.4절 키 + 검색 연결 + 벤치 p50/p95·RSS·토큰/초)을 넣고, 마크다운 표를 `지표 | 현행 | 후보 | 델타 | 95% 구간 | 허용치 | 절대 기준` 열로 바꾼다.

### L2 (낮음, 안전성) upgrade 지연 예산을 벤치 JSON의 `within_budget` 플래그로만 본다
- `ingest_compare.py:327-329`는 `single.within_budget is not True`만 본다. 벤치 파일의 `budget_p95_s`를 999로, `within_budget`를 true로 바꾸면 p95 61초 후보가 통과한다(1.3절). 8.6절 예산은 60초 고정이고 `SINGLE_P95_BUDGET_S`를 이미 import하고 있다.
- **고칠 방향:** `single.p95_s is not None and single.p95_s <= SINGLE_P95_BUDGET_S`로 다시 계산하고, 플래그와 다르면 경고하거나 거부한다.

### L3 (낮음, 정확성) 벤치·검색 연결 쪽 비교 가능성을 보지 않는다
- `ingest_compare.py:147-155` `_check_bench`는 두 벤치끼리 split만 맞춘다. 8.5절은 지연을 "`bench analyze --split dev`"로 판단하므로 dev가 아닌 벤치나, 리포트와 다른 벤치 split이면 최소한 경고가 필요하다.
- `ingest_compare.py:291-302` `_linkage_delta`는 두 리포트의 `n_queries`·`human_recall@10`이 같은지 보지 않는다. 골든셋 해시가 같으면 보통 같지만, 검색 설정이나 연결 녹화가 달라도 조용히 델타를 낸다(1.3절). `human_recall@10`이 다르면 두 R@10은 같은 기준으로 잰 값이 아니다.
- **고칠 방향:** `n_queries`·`human_recall@10` 불일치는 `CompareRefused`, 벤치 split이 `dev`가 아니면 경고.

### L4 (낮음, 안전성) `--out` 경로 처리
- `src/jupjup/cli.py:1041-1045`: `--out d.md`면 JSON을 쓰고 `with_suffix(".md")`가 같은 경로라 마크다운이 덮어써 JSON이 없어진다. `--out`이 디렉터리면 `IsADirectoryError` 트레이스백과 종료 1이 나와 "교체 불가"(1)와 구별되지 않는다. 파일 쓰기가 `try` 밖이다.
- **고칠 방향:** `out.suffix != ".json"`이면 종료 2로 안내(또는 `.json`을 붙임), 쓰기 `OSError`는 종료 2 한 줄 안내. 그리고 `cli.py:1037`의 접두어 "비교 거부:"는 파일 없음 같은 입력 오류에도 붙는다. `CompareRefused`와 `OSError`를 나눠 "비교 거부"/"입력 오류"로 다르게 쓰면 운영자가 덜 헷갈린다.

### L5 (낮음, 정확성) 현행 쪽 실패 건이 있으면 쌍이 비대칭이 된다
- `ingest_compare.py:159-168, 196-200`: 건별 값이 `None`인 건은 그쪽 평균에서만 빠진다. 후보 실패는 스키마 최종 준수율 절대 기준으로 막히지만, **현행** 실패 건은 후보 평균에는 들어가고 현행 평균에는 빠져, 델타가 서로 다른 건 집합의 평균 차가 된다(1.3절, 48건 대 38건). 리포트 `overall`과 같게 하려는 의도는 보고서 1절에 있지만 8.6절 "건 단위 쌍 재표집"과는 다르다. upgrade에서 현행이 어려운 건을 실패했다면 후보의 개선이 작게 잡히고, downgrade에서는 현행 평균이 부풀어 후보가 불리해진다(닫힌 쪽).
- **고칠 방향:** 두 쪽 다 값이 있는 건만 쌍으로 쓰고, 한쪽만 있는 건 수를 경고에 적는다. 또는 지금 방식을 유지하되 설계서 8.6절에 "현행 실패 건은 평균에서 뺀다"를 적고 경고를 낸다.

### L6 (낮음, 유지보수성) 런타임 `assert`와 판정 로직 중복
- `ingest_compare.py:118`, `:149`는 타입 좁히기용 런타임 `assert`다. T25a(L5)에서 `recording.py`·`validation.py`의 같은 패턴을 걷어냈다. `-O`에서 빠지는 검사이므로 `_check_comparable`이 해시를 지역 변수로 받아 돌려주거나, `runtime`이 있는 리포트 타입을 따로 좁혀 쓰면 된다.
- `ingest_compare.py:217-224` `_passes`는 `ingest_harness.py:481` `_check`의 비교 부분과 같은 로직이다. 게이트 비교 규칙이 두 곳에 있으면 한쪽만 바뀔 수 있다. `_check(...).passed`를 재사용하거나 작은 공용 함수로 뺀다.
- `ingest_harness.py` `IngestEvalHarness.compare_profiles`는 `n_boot`·`seed`를 넘기지 않는다. CLI는 쓰지 않는 경로라 문제는 없지만, 시그니처를 본체와 맞추거나 docstring에 기본값 고정이라고 적어 둔다.

## 3. 잘한 점

- 델타 부호를 "후보 − 현행"으로 하나로 고정하고 `_worsening`·`_improved` 두 함수에서만 지표 방향(비충실은 낮을수록 좋음)을 다뤄, 방향 실수가 들어갈 자리가 작다.
- 한 번 뽑은 재표집 인덱스를 모든 지표에 같이 쓰는 진짜 쌍 부트스트랩이고, numpy 없이 numpy 기본 백분위와 같은 값을 낸다.
- 골든셋 해시를 test 봉인과 같은 함수로 일반화하고(`compute_test_seal`이 그 함수의 test 분기), recorded/live에서만 채워 **mock 리포트가 바이트 그대로**다(직접 확인).
- 검색 연결 구간이 점추정인 것, 벤치가 없으면 자원·지연 판정을 "불가"로 닫는 것, 판정기 보정 상태가 다르면 거부하는 것 등 설계와 다른 점을 보고서 2절에 모두 이유와 함께 적었다. 확인해 보니 실제 동작과 일치했다.
- 보고서 4절의 수치(테스트 1266, mypy 90 파일, mock 바이트 동일, 검색 무회귀)는 모두 재현됐다.

## 4. 채점 근거

| 항목 | 점수 | 근거 |
|---|---|---|
| 정확성 | 38 / 40 | 완료 조건 4개와 AC-L7 충족, 부트스트랩·경계값·거부 조건 직접 재현, 검색·mock 무회귀. −1 L1(3.5.5절 3번 비교표의 절대값 누락), −1 L3·L5(검색 연결·벤치 비교 가능성 미확인, 현행 실패 건 비대칭) |
| 안전성 | 27 / 30 | 네트워크·모델 호출 없음, llama_cpp 미 import, 거부 조건은 모두 종료 2로 닫힘. −2 M1(비유한 값으로 eligible), −1 L2·L4(저장 플래그 신뢰, `--out` 덮어쓰기·트레이스백) |
| 유지보수성 | 28 / 30 | 모듈 하나에 판정 본체, 상수 표, 손계산 가능한 테스트 39건 + 통합 1건, 설계 차이 문서화. −1 런타임 `assert`(T25a에서 걷어낸 패턴), −1 게이트 비교 로직 중복·하네스 메서드 시그니처 불일치 (L6) |
| **합계** | **93 / 100** | **PASS** |

## 5. 다음 단계 권고

- PASS이므로 루프를 끝낸다. M1은 T25h에서 실제 리포트 쌍으로 `compare-profiles`를 처음 쓰기 전에 작은 후속 작업(입력 유한성 검사 + 테스트 2건)으로 고치길 권한다. L1(비교표 절대값)도 사용자 승인용 리포트를 만들기 전에 같이 하면 좋다.
- L2~L6은 다음에 `ingest_compare.py`·`cli.py`를 만질 때 같이 처리하면 된다.

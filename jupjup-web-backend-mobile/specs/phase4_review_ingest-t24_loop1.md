# Phase 4 최종 검수: 인제스트 T24(인제스트 평가 mock), Loop 1/3

- **점수:** 87 / 100
- **상태:** REJECT
- **항목별:** 정확성 34 / 40, 안전성 27 / 30, 유지보수성 26 / 30
- **루프백 대상:** Phase 2 (Codex-Primary). M1~M5가 기능·지표 정의 문제다. 낮음 항목(L*)은 같은 루프에서 함께 정리하기를 권한다.
- **검수 대상:** `phase-4-review-ingest-t24-loop1` HEAD `054b002` (`feat: add T24 ingest evaluation harness`), 기준 `d172e2c`
- **검수자:** Claude-Reviewer 역할 대행 (Claude). 코드는 고치지 않았다. 실험은 스크래치 디렉터리(골든셋 사본, monkeypatch 스크립트)와 `var/rv/`, `var/review.db`에서 했다.
- **범위 밖:** T25 실제 LLM 분석기·판정기, T26 소형 모델 비교(`compare_profiles`, `compare-profiles` CLI), live 실호출. 사람 검수 미완료(`ai_draft_unreviewed` 80건)는 감점하지 않았다.

## 0. 한 줄 판정

T24 완료 조건 다섯 가지(mock 게이트 충족, 두 번 실행 바이트 동일, 3.5.2절 지표 표와 "해당 없음" 표기, 지표 함수 손계산 일치, 골든셋 검증기 통과)는 **직접 재현해 모두 확인했다.** 네트워크 차단 상태에서도 돌고, 검색 코드 diff 0줄, 검색 eval 4종 수치도 직전 검수와 소수점 4자리까지 같다. 다만 직접 만든 입력으로 하네스를 흔들어 보니 **3.5.2절 지표 정의를 어기는 결함이 재현됐다.** (1) 잡이 끝내 실패하면 리포트가 나오지 않고 하네스 전체가 예외로 죽어 "스키마 최종 준수율"이 1.0 미만 값을 낼 수 없다. (2) 요약 비충실 문장 비율이 1을 넘는다(4.0 재현). `forbidden_claims`가 나와도 그 건이 "바로 비충실"로 처리되지 않는다. (3) 태그·엔티티·장소 채점에 동의어 사전이 연결되지 않았다. (4) 골든셋이 7개 템플릿의 번호 치환본이라 어려운 사례 라벨이 실제로 그 능력을 시험하지 못한다. (5) fixture 선택이 `key_facts[0]` 부분 문자열에 의존해, 검증기를 통과한 입력에서도 **조용히 다른 건의 응답이 매겨진 채 PASS**가 나온다. mock 게이트 자체는 통과하지만, 이 하네스는 T25에서 실제 분석기 합격 판정에 그대로 쓰일 코드라 이번 루프에서 바로잡아야 한다.

## 1. 직접 실행한 명령과 결과

### 1.1 기본 게이트

| 명령 | 결과 |
|---|---|
| `uv run pytest -o addopts="" -q -m "not live and not slow"` | **910 passed, 3 skipped**, 1 warning(기존 Starlette/httpx deprecation), 47.2s. 보고서의 910 passed와 같다 |
| `uv run ruff check src tests` | All checks passed! |
| `uv run mypy src` | Success: no issues found in 78 source files |
| `uv run ruff format --check` (T24 신규 src·test 15개) | 1개 불일치: `src/jupjup/eval/ingest_harness.py:240` (완료 조건 아님, L7) |
| `uv run jupjup eval validate` | 종료 0. 검색 골든셋 기존 수치 그대로 + `인제스트 골든셋: sources 80, annotations 80 (dev 48, test 32)`, 플랫폼군 blog_web 10, image 5, instagram 15, kakaotalk 10, news 15, paper 10, youtube 15 |
| `uv run python scripts/generate_ingest_golden.py` 후 `git status --porcelain` | 변경 0. 생성기가 결정적이고 커밋본과 같다 |

### 1.2 인제스트 평가 (T24 완료 조건 재현)

| 명령 | 결과 |
|---|---|
| `uv run jupjup eval ingest --mode mock --split dev --out var/rv/a` | PASS, 종료 0. schema_final 1.0, injection 1.0, 회귀 체크 2개 OK |
| `... --split test --out var/rv/a` | PASS, 종료 0. 동일 |
| `... --split all --out var/rv/a` | PASS, 종료 0. sources 80, injection_cases 3, retry_exercised 6 |
| 같은 세 명령을 `--out var/rv/b`로 다시 실행 후 `cmp` 6개 파일 | **6개 모두 바이트 동일.** 리포트에 타임스탬프 필드 자체가 없다 |
| `socket.socket.connect`, `socket.create_connection`을 예외로 바꾼 뒤 `IngestEvalHarness(split="all").run()` | 정상 완료, gate PASS. **외부 네트워크 접근 없음.** 신규 파일에 `httpx/requests/anthropic/urllib/socket` import 0건 |
| test 리포트 Markdown | 3.5.2절 22행 표, 품질 지표 13행 `해당 없음`, 토큰·재요청·비용·지연은 값 표시, 3.5.4절 mock 게이트 표, 플랫폼군 표, 충실도 후보 절 있음 |
| 항목 분포(all) | `(attempts=1, first_pass=True, succeeded)` 74건, `(attempts=2, first_pass=False, succeeded)` 6건. 재요청 경로가 실제로 돈다. 긴 글 5건은 입력 토큰 54,402/108,804로 청킹(맵 단계) 경로를 탄다 |

### 1.3 CLI 경계와 오류 경로 (`uv run jupjup eval ingest ...`)

| 인자 | 결과 |
|---|---|
| `--mode live` | 비용 추정만 출력(32건, 입력 28,245 / 출력 16,000 tokens, $0), "실제 호출은 하지 않았습니다", 종료 2 |
| `--mode live --confirm-cost`, `--mode recorded` | "T25 범위입니다; 외부 호출은 수행하지 않았습니다", 종료 2. Mock으로 조용히 대체하지 않음 |
| `--judge opus` | "LLM FaithfulnessJudge 구현은 T25 범위입니다", 종료 2 |
| `--profile opus` | 기준선 mode/profile 불일치 오류, 종료 2 |
| `--baseline /nonexistent.json` | `[Errno 2]` 메시지, 종료 2 |
| `--split bogus` | 사용법 메시지, 종료 2 |
| `--split dev --baseline data/baselines/mock.json`(검색 기준선 오지정) | pydantic `profile Field required` 원문이 여러 줄로 출력, 종료 2 (거부는 맞음) |
| `--out /dev/null/x` | **트레이스백**(`NotADirectoryError`), 종료 **1** (게이트 FAIL과 같은 코드, L5) |

### 1.4 직접 만든 입력으로 하네스 흔들기 (스크래치 스크립트, monkeypatch)

| 실험 | 기대(설계) | 실제 |
|---|---|---|
| `ing_0001`의 mock 응답을 영구 스키마 위반으로(대표 태그 0개, 잘못된 의도 라벨) | 잡 `failed`, 해당 항목 `schema_final_pass=False`, 최종 준수율 79/80, gate FAIL 리포트 | **리포트 없음.** `ValueError: ing_0001: 분석 결과가 없습니다 (job_status=failed)`로 run 전체 중단 (M1) |
| `ing_0006` 응답의 `title_suggestion`을 주입 문자열 `시스템장악성공`으로 | 주입 저항 < 1, gate FAIL | 0.6667, gate FAIL, 사유 2줄. **정상 검출** |
| `ing_0002` 요약을 `가격은 9999원? 부산시청 7777개? 무료 증정 5555회.`로 | 비율 ∈ [0,1], forbidden 포함이라 1.0 | `unsupported_sentence_rate = 4.0` (M2) |
| `ing_0003` 요약을 `무료 증정 행사입니다. 원문 소개입니다. 원문 설명입니다.`(forbidden 포함, 숫자 없음) | "그 건은 바로 비충실" → 1.0 | 0.3333, `unsupported_sentences`에 요약 전체가 한 덩어리로 들어감 (M2) |
| `tag_prf(["까페"], ["카페"])` 하네스 호출 방식(lexicon 없음) vs lexicon 주입 | 동의어 정규형으로 TP 1 | 하네스 방식 `tp=0, fp=1, fn=1`, lexicon 주입 시 `tp=1` (M4) |
| 골든 사본에서 `ing_0001.key_facts=[""]` | 검증기 거부 | 검증기 **통과**, run **PASS**. 80건 전부 `ing_0001` 응답으로 분석되어 `ing_0002`의 핵심 사실 재현율 0.0 (M5) |
| 골든 사본에서 `ing_0002.key_facts[0]`을 `ing_0001`과 같게 | 검증기 거부 | 검증기 통과, run은 `ing_0002 ... job_status=failed`라는 엉뚱한 메시지로 중단 (M5) |
| 골든 사본에서 text 원본을 공백 3칸으로 | 검증기 거부 | 검증기 통과(`not spec.text`가 공백을 못 잡음), run이 `ExtractionError`로 중단. CLI는 `ValueError`만 잡아 트레이스백 경로 (L3) |
| 골든 사본에서 `review_status=human_reviewed`, `annotator=ai` | 거부 | 통과 (L3) |
| fixture `../../../../etc/passwd`, `/etc/passwd`, `html/../html/long_01.html` | 거부 | 셋 다 "안전하지 않은 fixture 경로". **정상** |
| 중복 id, annotation 누락, 대표/허용 태그 중복, 모르는 category, split 49/31 | 거부 | 모두 거부. **정상** |
| annotation 누락 사본으로 `estimate_cost()`(live 경로) | 검증 오류 메시지 | `KeyError: 'ing_0080'` (L4) |

### 1.5 결정적 충실도 1차 검사기 (`judge.py`) 직접 시험

| 원문 / 요약 | 결과 | 평가 |
|---|---|---|
| `서울시는 2026년 10월 3일 예산 1200억원…` / 같은 문장 + `부산시는 예산 1500억원…` | 둘째 문장만 후보, missing에 `1500` | 단위 테스트와 일치. 정상 |
| `예산 120억원을 편성했다.` / `예산 12억원을 편성했다.` | **후보 없음** | 부분 문자열 비교라 `12`가 `120` 안에서 찾아짐. 거짓 음성 (L1) |
| `행사는 2026.10.3 열린다.` / `행사는 2026년 10월 3일 열린다.` | 후보로 표시 | 날짜 표기 차이로 거짓 양성. 1차 "후보"라 허용 범위 |
| `Apple released iPhone` / `Samsung released Galaxy.` | **후보 없음** | Kiwi가 영문을 `SL`로 태깅해 NNP 검사에서 빠짐. 영어 중심 5건에 효과 없음 (L1) |

### 1.6 지표 함수 손계산 (`ingest_metrics.py`)

| 입력 | 손계산 | 실제 |
|---|---|---|
| `tag_prf([카페, 디저트, 베이커리카페, 야경], [카페, 디저트, 성수동], [베이커리카페])` | TP 2, FP 1(야경), FN 1 → P=R=F1=2/3 | 일치 |
| `entity_prf` 타입 불일치 `(person, 서울시)` vs `(organization, 서울시)` | TP 2, FP 1, FN 1 | 일치 |
| `name_prf([성수동, 성수동], [성수동])` | 이분 매칭 TP 1, FP 1 | 일치 |
| `entity_prf([(place, 어니언 성수)], [(place, 어니연 성수)])` | 자모 거리 1 → TP 1 | 일치 |
| `latency_summary([10,20,30,40])` | p50 25, p95 = 30+(40-30)×0.85 = 38.5 | 일치 |
| `accuracy([T,F,T,T])` | 0.75 | 일치 |

### 1.7 검색 무회귀

- `git diff d172e2c HEAD --stat -- src/jupjup/search src/jupjup/query src/jupjup/ingest src/jupjup/index src/jupjup/api data/baselines/mock.json data/baselines/recorded.json data/recordings data/golden/seeds.jsonl data/golden/queries.jsonl data/lexicon` → **0줄**. `src/` 변경은 `cli.py`와 `eval/` 신규 4개 파일뿐이다.

| 모드 / split | 판정 | R@10 | MRR@10 | nDCG@10 |
|---|---|---|---|---|
| mock / dev | PASS, 종료 0 | 0.9620 | 0.9958 | 0.9795 |
| mock / test | PASS, 종료 0 | 0.9420 | 0.9867 | 0.9589 |
| recorded / dev | PASS, 종료 0 | 0.9712 | 1.0000 | 0.9860 |
| recorded / test | PASS, 종료 0 | 0.9720 | 0.9911 | 0.9801 |

직전 검수(`phase4_review_ingest-hardening_loop1.md` 1.2절)와 소수점 4자리까지 같다.

### 1.8 CLI 검색 경계값 (`uv run jupjup seed load --db var/review.db` → 200건, `search --db var/review.db --now 2026-10-15T12:00+09:00`, `JUPJUP_MODE=mock|recorded`)

| 질의 | mock | recorded | 비고 |
|---|---|---|---|
| `경주 맛집 인스타` | `c_alice_0153`, `platform_filter_dropped` | 같음 | 과소 완화 회귀 없음 |
| `하체 운동 유튜브` | 0040, 0050, 0051, `platform_filter_dropped` | 같음 | 같음 |
| `경주 맛집 카톡 논문` | 0153, 플랫폼·유형 둘 다 기록 | 같음 | 이중 완화 기록 유지 |
| `다리 운동 영상` | `c_alice_0040` 1위 | `c_alice_0040` 1위 | known_issues 4번 유지 |
| `카페 --platform youtube` | `c_alice_0046`(youtube) 1건, 완화 없음 | 같음 | 요청 잠금 유지 |
| `맛집 --platform instagram --type video` | 0건 | 녹화 캐시 미스(종료 2) | 과잉 완화 없음 |
| `성수동 카패`(오타) | 0151, 0132, 0046 | 녹화 캐시 미스 | recorded 캐시 미스는 기존 동작, T24 무관 |
| `""`, 600자 | `INVALID_QUERY 1~200자`, 종료 2 | 같음 | 정상 |
| `!!!@@@###` | `INVALID_QUERY 검색할 단어가 없어요`, 종료 2 | 같음 | 정상 |
| `seongsu cafe 디저트` | 0001, 0036 | 녹화 캐시 미스 | 기존 동작 |
| `작년 여름 인스타` | 0025, 0036, 0008 | 같음 | 정상 |
| `화성 탐사 로봇 레시피`(없는 대상) | 0건 | 녹화 캐시 미스 | 정상 |
| `u_carol` `경주 맛집`, `u_nobody` `카페` | 0건 | 0건 | 사용자 격리 유지 |

T24는 검색 코드를 건드리지 않았고, 위 결과는 이전 검수들과 같다.

## 2. 설계 대조 (3.5.6절 시그니처, 필드 단위)

| 설계 | 구현 | 판정 |
|---|---|---|
| `IngestEvalConfig.mode/split/sources_path/annotations_path/baseline_path/judge_profile/run_search_linkage/confirm_cost` | 모두 있음, 기본값 일치 | 일치 |
| `IngestEvalConfig.profile = "default"` | `"mock"` (`ingest_harness.py:261`) | 보고서 설계 차이 1번에 근거 명시. 수용 |
| (설계에 없음) | `regression_tolerance: float = 0.01` | 3.5.4절 회귀 규칙의 매개변수화. 수용 |
| `IngestItemResult.source_id/job_status/attempts/schema_first_pass/schema_final_pass/metrics/cost_usd/latency_ms/unsupported_sentences` | 모두 있음 | 일치. `platform_group/input_tokens/output_tokens` 추가는 확장 |
| `IngestEvalReport.config/overall/by_platform/search_linkage/items/gate` | 모두 있음. `overall`이 `dict[str, float \| None]` | "해당 없음" 표현을 위해 필요. 수용. `golden_status/counts` 추가 |
| `IngestEvalHarness.__init__(config, container_factory: Callable[..., AppContainer])` | `Callable[[IngestEvalConfig], AppContainer]`, 기본값 있음 | 호환 |
| `estimate_cost() -> CostEstimate` | 있음 | 일치. 다만 L4 |
| `run() -> IngestEvalReport` | 있음 | 일치. 다만 M1 |
| `compare_profiles(...) -> SwapDecision` | 반환형 `None`, `NotImplementedError` (`:469-471`) | T26 범위로 명시. 감점 없음 |
| CLI `jupjup eval ingest [--mode] [--profile] [--split] [--judge] [--baseline] [--confirm-cost]` | 모두 있음 + `--out` | 일치 |
| CLI `jupjup eval compare-profiles` | 없음 | T26 범위. 감점 없음 |
| `tests/eval/test_ingest_regression.py`가 mock 열을 단언 | 있음 (dev/test 게이트, 결정성, 해당 없음 표기) | 일치 |
| 4장 배치 `eval/ingest_metrics.py, ingest_harness.py, judge.py`, `data/baselines/ingest.mock.json` | 모두 있음 + `ingest_report.py` | 일치 |

## 3. 피드백 (심각도 순)

### M1. [중간·높음] 잡이 끝내 실패하면 하네스가 죽는다. "스키마 최종 준수율"이 1.0 미만을 낼 수 없다
- **위치:** `src/jupjup/eval/ingest_harness.py:418-421` (`analyzer.results.get(...)`이 없으면 `raise ValueError`), `:441` (`schema_final_pass=job.status == "succeeded"`는 False가 될 수 없는 죽은 분기), `src/jupjup/cli.py:797-799` (종료 2 "평가 오류")
- **재현:** 1.4절 첫 실험. 80건 중 1건만 영구 실패시켜도 리포트 없이 `ValueError: ing_0001: 분석 결과가 없습니다 (job_status=failed)`.
- **영향:** 3.5.2절은 "재요청까지 거친 뒤 통과한 비율. 끝내 실패하면 잡은 `failed`"로, 실패 건을 분모에 넣어 세는 지표다. 지금은 1.0 아니면 예외라서 지표가 사실상 계산되지 않고, 어느 건이 왜 실패했는지 리포트로 남지 않는다. 게이트가 막히긴 하지만(종료 2), "평가 오류"와 "게이트 FAIL"(종료 1)이 구분되지 않는다. T25에서 실제 LLM 한 건만 실패해도 32건 평가 전체가 날아간다.
- **개선:** 잡이 `failed`/`dead`로 끝나면 분석 결과 없이 `IngestItemResult(job_status=failed, schema_final_pass=False, attempts=<잡/분석 기록의 시도 수>, metrics={}, unsupported_sentences=[])`를 남기고 계속 진행한다. `overall.schema_final_pass_rate`가 79/80 같은 값을 내고 gate가 FAIL(종료 1)이 되어야 한다. 실패 원인(잡의 `last_error` 코드)을 항목에 남기면 좋다. 영구 실패 1건을 주입하는 회귀 테스트를 `tests/eval/test_ingest_regression.py`에 추가한다.

### M2. [중간] 요약 비충실 문장 비율이 1을 넘고, `forbidden_claims`가 나온 건이 "바로 비충실"로 처리되지 않는다
- **위치:** `src/jupjup/eval/ingest_harness.py:424-426` (요약 전체를 문장 목록에 덧붙임), `:566` (문장 수를 `.`/`!`로만 셈), `:580` (`len(unsupported) / sentence_count`), 비교 대상 `src/jupjup/eval/judge.py:14,78` (`?`, `。`, 줄바꿈까지 문장으로 나눔)
- **재현:** 1.4절. `가격은 9999원? 부산시청 7777개? 무료 증정 5555회.` → **4.0**. forbidden `무료 증정`이 들어간 세 문장 요약 → 0.3333.
- **영향:** 3.5.2절 정의("요약 문장 중 … 비율", "`forbidden_claims`가 나오면 그 건은 바로 비충실")와 다르다. 분자와 분모가 서로 다른 문장 분리기를 쓰고, 분자에 문장과 요약 전체가 중복으로 들어간다. mock에서는 overall이 `해당 없음`이라 게이트에 안 보이지만 항목 JSON에는 이 값이 그대로 나가고, T25 기본 분석기 열(≤ 0.03)이 이 코드를 그대로 쓴다.
- **개선:** 분자·분모 모두 `judge.split_sentences` 결과를 쓰고, 근거 없는 문장은 집합으로 센다. forbidden claim이 걸리면 항목 비율을 1.0으로 두거나 `forbidden_claim_hit: 1.0` 같은 별도 항목 지표로 분리하되, 어느 쪽이든 문서화하고 overall 집계 규칙(건 평균 또는 문장 합산)을 명시한다. `?` 구분 요약, forbidden 포함 요약, 중복 문장 요약 세 경우의 단위 테스트를 추가한다.

### M3. [중간] 골든셋이 7개 템플릿의 번호 치환본이라, 어려운 사례 라벨이 그 능력을 시험하지 못한다
- **위치:** `scripts/generate_ingest_golden.py:12-120` 근처(`GROUPS`, `GROUP_DATA`, 본문 템플릿), `data/golden/ingest/annotations.jsonl`
- **근거(직접 집계):** 80건의 대표 태그 집합 **7종**, 엔티티 집합 **7종**, 카테고리는 플랫폼군마다 1종, `forbidden_claims`는 80건 모두 `["무료 증정", "확정되지 않은 가격 정보"]`. `key_facts`는 `"어니언 성수가 카페 핵심 정보 2를 소개"`, `"줍줍 연구팀가 …"`, `"자료 6를 저장"`처럼 템플릿 문자열이고 조사도 틀렸다. `number_date_dense`(예: `ing_0036`)는 원문에 `2026년 10월 06일`, `1302억원`, `37곳`, `6.5%`가 있지만 `key_facts`와 `forbidden_claims` 어디에도 숫자가 없다. 그래서 3.5.1절이 이 사례를 넣은 목적(숫자·날짜 요약 충실도)을 채점할 수 없다. 영어 중심 사례도 `key_facts`가 한국어 템플릿 문장이다.
- **영향:** mock 배선 검증에는 충분하다. 그러나 이 골든셋이 T25 기본 분석기 열 판정의 입력이 되므로, 지금 구조로는 사람이 "검수"하는 수준이 아니라 다시 써야 한다. `REVIEW_GUIDE.md`의 검수 절차만으로는 바로잡히지 않는다. 사람 검수 미완료 자체는 감점하지 않았고, 이 항목은 **데이터 설계** 문제로 감점했다.
- **개선(이번 루프 최소 조건):** 어려운 사례 라벨이 붙은 건만이라도 그 능력을 겨냥한 gold를 둔다. `number_date_dense` 5건은 숫자·날짜가 든 `key_facts`와 틀리기 쉬운 숫자를 담은 `forbidden_claims`(예: `1320억원`), `mostly_english` 5건은 영어 고유명사가 든 `key_facts`, `ad_hashtag_heavy` 5건은 광고 문구를 `forbidden_claims`로 둔다. `forbidden_claims`가 건마다 같지 않게 하고 템플릿 조사 오류(`가/이`, `를/을`)를 고친다. 플랫폼군 안 다양성(태그·엔티티·카테고리)을 넓히는 일은 사람 검수 단계로 넘겨도 되지만, 그 사실을 `REVIEW_GUIDE.md`와 `specs/known_issues.md`에 "검수가 아니라 재작성이 필요"하다고 적는다.

### M4. [중간·낮음] 하네스가 태그·엔티티·장소 채점에 동의어 사전을 넘기지 않는다. 보고서 설명과 다르다
- **위치:** `src/jupjup/eval/ingest_harness.py:558, 561, 563` (`tag_prf`, `entity_prf`, `name_prf`를 `lexicon` 없이 호출). 함수 쪽 `ingest_metrics.py:38-41`은 lexicon을 받도록 되어 있다.
- **재현:** 1.4절. `까페`/`카페`가 하네스 방식으로는 FP 1 + FN 1, lexicon을 넘기면 TP 1.
- **영향:** 3.5.2절 "정규화(NFKC, 공백 제거, **동의어 정규형**)"와 "별칭 사전"이 하네스에서는 적용되지 않는다. 보고서 설계 차이 5번 "T24는 기존 `Lexicon` 동의어 정규화와 자모 거리 1을 사용했다"는 지표 함수에 대해서만 맞고 실제 평가 경로에는 맞지 않는다. 항목 metrics와 T25 품질 지표가 과소평가된다.
- **개선:** `_item_metrics`에 `container.lexicon`을 넘긴다. "하네스 경로에서 동의어가 TP로 잡힌다"는 테스트를 하나 둔다.

### M5. [중간·낮음] fixture 선택이 `key_facts[0]` 부분 문자열에 묶여 있고, 검증기가 그 전제를 지키지 않는다
- **위치:** `src/jupjup/eval/ingest_harness.py:336-339` (`next(case for case in cases if case.needle in text)`), `:396` (needle = `key_facts[0]`), `:217-224` (검증기에 needle 규칙 없음)
- **재현:** 1.4절. `key_facts=[""]` 한 건만 바꿔도 검증기 통과 → 80건 전부 `ing_0001` 응답으로 분석 → **gate PASS**. needle이 겹치면 엉뚱한 건에서 `job_status=failed`.
- **영향:** 현재 데이터에서는 80건 모두 자기 needle이 첫 매칭임을 직접 확인했다(오매칭 0건). 하지만 골든셋을 사람이 고치는 순간(M3, REVIEW_GUIDE 절차) 조용히 다른 건의 응답이 매겨질 수 있고, 게이트는 이를 잡지 못한다. 잡 생성 시 `content_id`를 알 수 있으므로 원문 매칭은 필요 없는 결합이다.
- **개선:** `service.submit`이 돌려준 `content_id` → `source_id` 대응을 analyzer에 먼저 등록하고, `inp.meta.source_id`(= content_id)로 fixture를 고른다. needle 방식을 유지한다면 검증기에서 `key_facts[0]`이 비어 있지 않고, 해당 원문(추출 후)에 들어 있고, 다른 건의 원문에는 없다는 것을 확인한다.

### L1. [낮음] 결정적 1차 검사의 거짓 음성: 숫자 부분 문자열, 영어 고유명사
- **위치:** `src/jupjup/eval/judge.py:60` (`normalize_text(term) not in source`), `:72-74` (`NNP`, `SN`만)
- **재현:** 1.5절. `12억` vs 원문 `120억` → 근거 있음 처리. `Samsung`, `Galaxy` → 검사 대상 아님.
- **개선:** 숫자·날짜는 원문에서도 같은 정규식으로 뽑은 토큰 집합과 비교한다(경계 일치). 영문은 `SL` 토큰 중 대문자 시작 단어를 고유명사 후보로 넣는다. 설계 문구(Kiwi NNP/SN)를 문자 그대로 따른 것이라 감점은 작다.

### L2. [낮음] mock에서 계산 가능한 "스키마 첫 시도 준수율"을 `해당 없음`으로 숨겼다
- **위치:** `src/jupjup/eval/ingest_harness.py:588`
- AC-28은 "mock에서 **계산 불가한** 항목"만 `해당 없음`으로 표시하라고 한다. 첫 시도 준수율은 실제로 계산된다(all 74/80 = 0.925). 3.5.4절 mock 게이트 열이 "해당 없음"인 것과 표의 값 표시는 별개다. 재요청 배선이 도는지 보여 주는 값이니 표에 내고, 비고에 "게이트 제외"로 적는 편이 맞다. 품질 지표(태그·엔티티 등)를 `해당 없음`으로 둔 판단은 fixture가 gold를 복사하는 구조라 수용한다.

### L3. [낮음] 골든셋 검증기의 빈틈
- **위치:** `src/jupjup/eval/ingest_harness.py:196` (`not spec.text`는 공백만 있는 원본을 통과시킴), `:217-219` (`human_reviewed`/`needs_human_review`인데 `annotator=ai`인 조합 허용), 플랫폼군과 `platform`/`content_type` 정합성 검사 없음
- **재현:** 1.4절. 공백 원본은 검증 통과 후 `ExtractionError`로 run 중단. `ExtractionError`는 `JupjupError` 계열이라 `cli.py:797`의 `except (OSError, ValidationError, ValueError)`에 걸리지 않는다.
- **개선:** `spec.text.strip()` 검사, `human_reviewed`면 `annotator=human`, `platform_group`별 허용 `platform` 집합 검사를 추가한다. CLI는 `JupjupError`도 잡아 종료 2로 낸다.

### L4. [낮음] `estimate_cost`가 골든셋을 검증하지 않고, 토큰 추정이 한국어에서 크게 낮다
- **위치:** `src/jupjup/eval/ingest_harness.py:366-379`, `:473-479`, 호출부 `src/jupjup/cli.py:788` (try 바깥)
- annotation이 빠진 사본에서 `KeyError: 'ing_0080'`(1.4절). `characters // 4`는 영어 기준이라, test 32건 추정 입력 28,245 tokens가 같은 32건 mock 측정값(건당 3,755.5 × 32 ≈ 120,177)의 약 1/4이다. live에서 `--confirm-cost` 판단 근거가 되는 숫자라, T25 전에 실제 토크나이저 또는 한국어 비율 보정으로 바꾸고, 검증을 run과 같은 경로로 돌린다.

### L5. [낮음] CLI 오류 경로 일관성
- **위치:** `src/jupjup/cli.py:800` (`write_ingest_report`가 try 바깥 → `--out` 쓰기 실패 시 트레이스백, 종료 1). 종료 1은 "게이트 FAIL"과 같은 코드라 CI가 둘을 구분하지 못한다. 잘못된 기준선 파일은 pydantic 원문이 여러 줄로 나온다. 리포트 쓰기도 try 안으로 넣고 종료 2, 기준선 오류는 한 줄 요약으로 낸다.

### L6. [낮음] mock 주입 저항 판정이 원문 앞 100자에 기대고 있다
- **위치:** `src/jupjup/eval/ingest_harness.py:535, 547` (`evidence_span = 원문 앞 100자`), `:429-431` (출력 직렬화 전체에서 주입 문자열 검색)
- 주입 문장이 원문 117~122자 위치에서 시작해 지금은 통과한다. 원문이 짧아지거나 주입 문장이 앞으로 오면 mock이 "원문을 인용했을 뿐"인데도 주입 실패로 판정된다. 또 test split의 주입 사례는 1건(`ing_0006`)뿐이라 test 게이트의 주입 저항은 n=1이다. evidence는 `key_facts[0]`이 들어 있는 원문 구절로 잡고, 3건 중 2건 이상이 test에 오도록 배치하거나 최소 test 건수를 검증기에 넣는다.

### L7. [낮음] 테스트 공백과 정리
- `tests/eval/test_ingest_regression.py`, `tests/unit/test_ingest_golden_validator.py`에 **부정 경로 테스트가 없다**: 영구 스키마 실패(M1), 주입 성공 시 gate FAIL(1.4절에서 동작은 확인), 기준선 대비 회귀 실패, 검증기 거부 사례(경로 이탈, 중복, split 불일치)가 모두 단언되지 않는다.
- `tests/unit/test_ingest_metrics.py:24-29`의 테스트 이름은 "allows one jamo edit"인데 입력이 모두 같은 이름이라 자모 거리 1 경로를 시험하지 않는다.
- `forbidden_claims` 경로, `unsupported_sentence_rate` 계산 테스트가 없다(M2).
- `ruff format --check`: `src/jupjup/eval/ingest_harness.py:240` 한 곳 불일치.
- 충실도 검사의 원문은 `_source_text`(`:481-491`)로 하네스가 따로 다시 추출한 텍스트다. 3.5.3절은 "원문(스냅샷 텍스트)"이다. 지금은 같은 추출기라 결과가 같지만, 저장된 스냅샷을 읽어 쓰면 파이프라인과 평가가 어긋날 여지가 없어진다.

## 4. 채점 근거

- **정확성 34 / 40:** T24 완료 조건 다섯 가지와 검색 무회귀는 직접 재현해 확인했다(+). 3.5.2절 지표 두 개(스키마 최종 준수율 M1 −2, 요약 비충실 비율 M2 −2)의 정의 위반을 재현했다. 동의어 정규형 미적용(M4 −1), 어려운 사례 gold가 목적을 시험하지 못함(M3 −1).
- **안전성 27 / 30:** 외부 네트워크 접근 없음(소켓 차단 실행으로 확인), live/recorded가 Mock으로 조용히 대체되지 않음, fixture 경로 이탈 차단, 비용 확인 없는 live 거부 모두 좋다. 감점: 실패 건에서 하네스 전체 중단(M1 −1), 검증기를 통과한 입력이 조용히 잘못된 채점으로 PASS(M5 −1), 검증기·CLI 예외 경로 빈틈(L3·L4·L5 −1).
- **유지보수성 26 / 30:** 모듈 배치와 순수 함수 분리, 결정적 리포트, 결정적 생성기는 좋다. 감점: 부정 경로 테스트 부재(L7 −2), 원문 부분 문자열로 응답을 고르는 결합(M5 −1), 보고서와 실제 동작 불일치·포맷 불일치(M4 설명, L7 −1).

## 5. 재검수 조건 (Loop 2 PASS 조건)

1. **M1:** 영구 스키마 실패 1건을 주입하면 리포트가 생성되고 `schema_final_pass_rate`가 (n−1)/n, 해당 항목 `job_status=failed`, `schema_final_pass=False`, gate FAIL, CLI 종료 1이 된다. 이를 단언하는 회귀 테스트가 있다.
2. **M2:** `unsupported_sentence_rate`가 항상 [0, 1]이고, 분자·분모가 같은 문장 분리기를 쓴다. forbidden claim 처리 규칙이 3.5.2절대로("그 건은 바로 비충실") 구현되고 문서화된다. `?` 구분, forbidden 포함, 중복 문장 단위 테스트가 있다.
3. **M3:** `number_date_dense`·`mostly_english`·`ad_hashtag_heavy` 건의 gold가 그 능력을 겨냥한다(숫자 든 key_facts·틀린 숫자 forbidden_claims, 영어 고유명사 key_facts, 광고 문구 forbidden_claims). `forbidden_claims`가 80건 모두 같지 않다. 템플릿 조사 오류가 없다. 나머지 다양성 부족은 `known_issues.md`와 `REVIEW_GUIDE.md`에 "재작성 필요"로 기록된다. 생성기 결정성과 `eval validate` 통과는 유지한다.
4. **M4:** 하네스가 lexicon을 지표 함수에 넘기고, 동의어가 TP로 잡히는 하네스 경로 테스트가 있다.
5. **M5:** fixture 선택이 content_id/source_id 대응으로 바뀌거나, 검증기가 needle(비어 있지 않음, 자기 원문에 있음, 다른 원문에 없음)을 강제한다. `key_facts=[""]` 사본이 검증 단계에서 거부된다.
6. 위 수정 뒤에도 `pytest`, `ruff check`, `mypy src`, `eval validate`, `eval ingest --mode mock --split dev|test|all` PASS와 두 번 실행 바이트 동일, 검색 eval 4종 수치 동일, `src/jupjup/search`·`src/jupjup/query` diff 0이 유지된다.
7. L1~L7은 권장이다. L2(첫 시도 준수율 표시), L3(CLI가 `JupjupError`를 잡음), L7(부정 경로 테스트)은 M1~M5와 같은 파일을 고치므로 같이 처리하기를 권한다.

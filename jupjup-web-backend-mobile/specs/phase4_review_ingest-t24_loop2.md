# Phase 4 최종 검수: 인제스트 T24(인제스트 평가 mock), Loop 2/3

- **점수:** 94 / 100
- **상태:** PASS
- **항목별:** 정확성 37 / 40, 안전성 29 / 30, 유지보수성 28 / 30
- **루프백 대상:** 없음 (PASS). 다만 N1(문장 분리기가 소수점에서 문장을 자름)은 T25가 이 코드를 그대로 기본 분석기 열(비충실 ≤ 0.03) 판정에 쓰므로 **T25 착수 전 또는 T25 첫 작업으로** 고쳐야 한다 (6절).
- **검수 대상:** `phase-4-review-ingest-t24-loop2` HEAD `4ef2df4` (`fix: harden T24 ingest evaluation loop 2`), 기준 `0d753a0` (Loop 1 검수 커밋)
- **검수자:** Claude-Reviewer 역할 대행 (Claude). 코드는 고치지 않았다. 실험은 스크래치 디렉터리(골든셋 임시 사본, monkeypatch 스크립트)와 `var/rv2/`, `var/review.db`에서 했다.
- **범위 밖:** T25 실제 LLM 분석기·판정기(Anthropic), T26 소형 모델 비교(`compare_profiles`, `compare-profiles` CLI), live 실호출. 사람 검수 미완료(`ai_draft_unreviewed` 80건)는 감점하지 않았다.

## 0. 한 줄 판정

Loop 1의 재검수 조건 M1~M5를 **모두 직접 만든 입력으로 재현해 해소를 확인했다.** 영구 스키마 실패 1건은 리포트에 `failed` 항목으로 남고 최종 준수율 47/48, gate FAIL, CLI 종료 1이 된다. 비충실 비율은 [0, 1]이고 forbidden claim은 그 건을 1.0으로 만든다. 동의어가 하네스 경로에서 TP로 잡히고, fixture 선택은 `content_id` 결합으로 바뀌어 needle 충돌 사본에서도 모든 건이 자기 응답으로 채점된다. 어려운 사례 15건의 gold는 그 능력을 겨냥하고 `forbidden_claims` 80건이 모두 다르다. T24 완료 조건 다섯 가지와 검색 무회귀(검색·질의 코드 diff 0줄, eval 4종 소수점 4자리 동일), 외부 네트워크 미접근도 다시 확인했다. 남은 결함은 **새로 드러난 중간 1건(N1)**: `judge.split_sentences`가 `6.5%`의 소수점을 문장 끝으로 잘라, M3로 새로 만든 숫자·날짜 사례 5건 전부가 gold를 그대로 복사한 충실한 요약인데도 항목 비충실 비율 0.667로 찍힌다. mock 게이트에는 영향이 없지만(overall이 `해당 없음`) T25 판정 경로의 버그라 6절 조건으로 넘긴다. 나머지는 낮음 항목이다.

## 1. 직접 실행한 명령과 결과

### 1.1 기본 게이트

| 명령 | 결과 |
|---|---|
| `uv run pytest -o addopts="" -q -m "not live and not slow"` | **928 passed, 3 skipped**, 1 warning(기존 Starlette/httpx deprecation), 52.7s. 보고서의 928 passed와 같다 (Loop 1 910 → +18) |
| `uv run ruff check src tests` | All checks passed! |
| `uv run mypy src` | Success: no issues found in 78 source files |
| `ruff format --check` (기준 대비 변경된 src·tests 10개) | 10 files already formatted (Loop 1 L7의 불일치 해소) |
| `uv run jupjup eval validate` | 종료 0. 검색 골든셋 기존 수치 그대로, `인제스트 골든셋: sources 80, annotations 80 (dev 48, test 32)`, 플랫폼군 blog_web 10, image 5, instagram 15, kakaotalk 10, news 15, paper 10, youtube 15 |
| `uv run python scripts/generate_ingest_golden.py` 후 `git status --porcelain` | 변경 0. 생성기 결정성 유지 |

### 1.2 인제스트 평가 (T24 완료 조건 재현)

| 명령 | 결과 |
|---|---|
| `uv run jupjup eval ingest --mode mock --split dev\|test\|all --out var/rv2/a` | 세 split 모두 PASS, 종료 0 |
| 같은 세 명령을 `--out var/rv2/b`로 다시 실행 후 `cmp` 6개 파일 | **6개 모두 바이트 동일.** 리포트에 타임스탬프 필드 없음(Markdown에 "생성 시각은 결정성 보장을 위해 기록하지 않음") |
| test 리포트 overall | `schema_first_pass_rate 0.96875`, `schema_final_pass_rate 1.0`, `average_retries 0.03125`, `injection_resistance 1.0`(n=2), 품질 지표 11개·검색 연결 2개 `null`, 토큰·비용·지연 값 표시 |
| test 리포트 Markdown | 3.5.2절 22행 표(품질 13행 `해당 없음`, 첫 시도 준수율은 값 + "계산 가능, mock 합격 게이트 제외"), 3.5.4절 mock 게이트 표 4행, 플랫폼군 표, 실행 건수, 충실도 1차 검사 절 |
| split별 첫 시도 / 재요청 | dev 0.895833, test 0.96875, all 0.925. retry_exercised dev 5, test 1, all 6 (보고서와 일치) |
| 소켓 차단(`socket.socket.connect`, `socket.create_connection`을 예외로 교체) 후 아래 1.4절 실험 전부 실행 | 모두 정상 완료. **외부 네트워크 접근 없음.** `src/jupjup/eval/*.py`, `cli.py`에 `httpx/requests/anthropic/urllib/socket/aiohttp` import 0건 |

### 1.3 CLI 경계와 오류 경로 (`uv run jupjup eval ingest ...`)

| 인자 | 결과 |
|---|---|
| `--mode live --split test` | 비용 추정만 출력(32건, 입력 **69,145** / 출력 16,000 tokens, $0), "실제 호출은 하지 않았습니다", 종료 2 |
| `--mode live --confirm-cost`, `--mode recorded` | "T25 범위입니다; 외부 호출은 수행하지 않았습니다", 종료 2. Mock으로 조용히 대체하지 않음 |
| `--judge opus` | "LLM FaithfulnessJudge 구현은 T25 범위입니다", 종료 2 |
| `--profile opus` | 기준선 mode/profile 불일치, 종료 2 |
| `--baseline /nonexistent.json` | `[Errno 2] ...` 한 줄, 종료 2 |
| `--split bogus` | 사용법 메시지, 종료 2 |
| `--split dev --baseline data/baselines/mock.json`(검색 기준선 오지정) | `인제스트 평가 오류: profile: Field required` **한 줄**, 종료 2 (Loop 1 L5 해소) |
| `--split test --out /dev/null/x` | `인제스트 평가 오류: [Errno 20] Not a directory` 한 줄, 종료 **2** (Loop 1에서는 트레이스백·종료 1. L5 해소) |

### 1.4 직접 만든 입력으로 하네스 흔들기 (골든 임시 사본 + monkeypatch, 소켓 차단 상태)

| 실험 | 기대(설계 / Loop 1 조건) | 실제 |
|---|---|---|
| E1. `ing_0001`(dev)에 `mock_failure=permanent_schema_failure` | 리포트 생성, (n−1)/n, `failed`, gate FAIL | `schema_final_pass_rate 0.979167`(47/48), 항목 `job_status=failed, attempts=3, schema_first_pass=False, schema_final_pass=False, error_code=ANALYSIS_SCHEMA_INVALID`, gate FAIL(사유 2줄: 절대 기준 + 회귀). **M1 해소** |
| E1b. 주입 사례 `ing_0071`(test)을 영구 실패로 | 최종 준수율·주입 저항 모두 하락 | 0.96875 / `injection_resistance 0.5` / gate FAIL. 실패한 주입 건을 "저항 실패"로 셈 (보수적, 타당) |
| E2. `ing_0003.key_facts[0]`을 `ing_0002`의 것으로 바꿔 needle 충돌 | 각 건이 자기 응답으로 채점 | `--split all` gate PASS, `failed` 0건. **M5 해소**(content_id 결합) |
| E3. `ing_0001.key_facts=[""]` | 검증 단계 거부 | `인제스트 골든셋 검증 실패: ing_0001: key_facts에는 빈 문자열을 둘 수 없습니다`. **M5 해소** |
| E4. 주입 3건의 `title_suggestion`에 `injection_target`을 넣음 | 주입 저항 < 1, gate FAIL | test `injection_resistance 0.0`, gate FAIL, 사유 2줄 |
| E5. `long_01.html` fixture를 빈 `<html><body></body></html>`로 | 검증 거부 또는 항목 실패 | 검증 통과 후 run 전 단계 `_source_text`에서 `ExtractionError: 추출된 본문이 비었습니다`로 중단. CLI에서는 `JupjupError`를 잡아 종료 2 (L-3) |

### 1.5 결정적 충실도 1차 검사기 (`judge.py`) 직접 시험

원문: `서울시가 2026년 10월 06일 교통 예산 1302억원을 발표. 참여 기관 37곳과 증감률 6.5%를 공개. Samsung Galaxy 출시.` forbidden: `참여 기관 76곳`.

| 요약 | 문장 분리 | 후보 / 비율 | 평가 |
|---|---|---|---|
| `증감률 6.5%를 공개했다.` (원문과 같은 수치) | `['증감률 6.', '5%를 공개했다.']` | 두 조각 모두 후보, missing `6`, `5%`, **비율 1.0** | **거짓 양성 (N1)** |
| `버전 3.14가 나왔다.` | `['버전 3.', '14가 나왔다.']` | 두 조각 모두 후보 | 같은 원인 (N1) |
| `예산 130억원 발표.` (원문 1302억원) | 1문장 | 후보, missing `130` | Loop 1 L1(부분 문자열 거짓 음성) 해소 |
| `Apple 출시. Samsung 출시.` | 2문장 | `Apple`만 후보, 0.5 | 영어 고유명사 검사 동작. L1 해소 |
| `This is fine. 서울시 발표.` | 2문장 | `This`가 고유명사 후보로 잡혀 0.5 | 문장 첫 대문자 단어 거짓 양성 (L-2) |
| `예산은 1302억원? 기관 99곳? 좋다.` | 3문장 | `기관 99곳?`만 후보, 0.333 | `?` 분리 정상. M2 해소 |
| `기관 99곳. 기관 99곳. 좋다.` | 3문장 | 후보 2개(같은 문장), 비율 **0.333** | 분자는 집합, 분모는 중복 포함 목록 (L-1) |
| `참여 기관 76곳이다. 좋다.` | 2문장 | forbidden → 전체 문장, 1.0 | 3.5.2절 "그 건은 바로 비충실" 일치. M2 해소 |
| `""` | 0문장 | 0.0 | 정상 |
| `2026년 10월 6일 발표.` (원문 `06일`) | 1문장 | 후보 | 표기 차이 거짓 양성. 1차 "후보"라 허용 |

**N1의 실제 영향 (정상 골든, mock all 리포트에서 확인):** `ing_0036`~`ing_0040` 5건의 mock 요약은 gold `key_facts`를 그대로 이어 붙인 것(원문에도 그대로 있음)인데 `unsupported_sentence_rate = 0.6667`, `unsupported_sentences = ['참여 기관 37곳과 증감률 6.', '5%를 공개입니다.']`. test 리포트 Markdown의 "결정적 충실도 1차 검사" 절에도 `ing_0036`, `ing_0038`, `ing_0040`이 그대로 나온다. 80건 중 비충실 후보가 나온 건은 이 5건뿐이고 모두 거짓 양성이다.

### 1.6 지표 함수 손계산 (`ingest_metrics.py`, container lexicon 주입)

| 입력 | 손계산 | 실제 |
|---|---|---|
| `tag_prf([카페, 디저트, 팡도르, 맛집], [카페, 디저트, 성수동], [팡도르])` | TP 2, FP 1(맛집), FN 1 | `PRF(tp=2, fp=1, fn=1)` 일치 |
| `tag_prf([까페], [카페])` + lexicon | 동의어 정규형 TP 1 | `PRF(tp=1, fp=0, fn=0)` 일치. **M4 해소**(하네스도 `container.lexicon` 전달, `ingest_harness.py:514, 648-653`) |
| `entity_prf([(place, 어니언 성수), (product, 팡도르), (place, 팡도르)], [(place, 어니언성수), (product, 팡도리)])` | 공백 정규화 TP, 자모 1 TP, 타입 불일치 FP → TP 2, FP 1, FN 0 | 일치 |
| `name_prf([성수동, 성수동], [성수동, 서울])` | 이분 매칭 TP 1, FP 1, FN 1 | 일치 |
| `accuracy([T,F,T,T])` | 0.75 | 일치 |
| `save_intent_correct([데이트],[방문예정],[데이트])` / `([구매예정],...)` / `([],...)` | True / False / False | 일치 |
| `latency_summary([10,20,30,40,50])` | p50 30, p95 = 40 + 10×0.8 = 48 | `(30, 48.0)` 일치 |

### 1.7 골든셋 데이터 (M3)

| 확인 | 결과 |
|---|---|
| `forbidden_claims` 서로 다른 집합 수 | **80 / 80** (Loop 1: 1종) |
| `number_date_dense` 5건 (`ing_0036`~`0040`, test 3 / dev 2) | key_facts에 `2026년 10월 06일`, `1302억원`, `37곳`, `6.5%`. forbidden에 틀리기 쉬운 수치 `1320억원`, `76곳`. 원문에 key_facts 수치가 그대로 있음 |
| `mostly_english` 5건 (`ing_0046`~`0050`) | key_facts에 `Orca Retrieval Lab`, `Benchmark N`, `Atlas Retrieval Dataset N`. forbidden `Samsung Galaxy Benchmark N`, `Tesla 연구팀 결과 N` |
| `ad_hashtag_heavy` 5건 (`ing_0001`~`0005`) | forbidden `선착순 무료 증정 N개`, `전 품목 9N% 할인`(원문에는 "광고 협찬 링크" + 해시태그 반복만 있음) |
| 프롬프트 주입 3건 | `ing_0006`(test), `ing_0024`(dev), `ing_0071`(test). test 2건, 검증기가 최소 2건 강제 (`ingest_harness.py:275-282`). L6 해소 |
| 조사 오류 | `ing_0047`, `ing_0049`, `ing_0050`의 `Benchmark 2을/4을/5을`(→ `를`) 3건 남음 (L-4) |
| 대표 태그 집합 종류 | 7종 그대로. `REVIEW_GUIDE.md` "재작성 완료 조건"과 `known_issues.md` 8번에 "검수가 아니라 재작성 필요"로 기록 (Loop 1 M3 조건대로) |

### 1.8 검색 무회귀

- `git diff --stat 0d753a0 HEAD -- src/jupjup/search src/jupjup/query data/baselines data/recordings data/lexicon data/golden/queries.jsonl data/golden/seeds.jsonl data/golden/challenge_queries.jsonl data/golden/test_v2` → **0줄**. `git diff 054b002^ HEAD -- src/jupjup/search src/jupjup/query`도 0줄.
- `src/` 변경은 `cli.py`(eval ingest 오류 처리, 무관한 줄바꿈 정리 1곳), `eval/ingest_harness.py`, `eval/ingest_report.py`, `eval/judge.py`, `ingest/jobs.py`(`SAFE_ERROR_DETAIL_KEYS`에 `attempts`, `repair_attempts` 추가)뿐이다.

| 모드 / split | 판정 | R@10 | R@5 | MRR@10 | nDCG@10 | cat min | true / false empty |
|---|---|---|---|---|---|---|---|
| mock / dev | PASS | 0.9620 | 0.9419 | 0.9958 | 0.9795 | 0.8838 | 1.0 / 0.0 |
| mock / test | PASS | 0.9420 | 0.9281 | 0.9867 | 0.9589 | 0.7812 | 1.0 / 0.012 |
| recorded / dev | PASS | 0.9712 | 0.9495 | 1.0000 | 0.9860 | 0.8894 | 1.0 / 0.0 |
| recorded / test | PASS | 0.9720 | 0.9541 | 0.9911 | 0.9801 | 0.8900 | 1.0 / 0.0 |

Loop 1 검수(1.7절)와 소수점 4자리까지 같다.

### 1.9 CLI 검색 경계값 (`uv run jupjup seed load --db var/review.db` → 200건 적재·인덱싱, `search --user U --db var/review.db --now 2026-10-15T12:00+09:00`, `JUPJUP_MODE=mock|recorded`)

| 질의 | mock | recorded | 비고 |
|---|---|---|---|
| `성수동 카페` (u_alice) | 블로그·이미지·유튜브 성수동 카페 5건 | 이미지·블로그·카톡 5건 | 정상 |
| `성수동 까페` (오타) | 오타 교정, 위와 같은 상위 3건 | 성수동 카페 후기 상위 | 정상 |
| `""`, `카페 ×200`(긴 질의) | `INVALID_QUERY 1~200자`, 종료 2 | 같음 | 정상 |
| `!!!@@@###` | `INVALID_QUERY 검색할 단어가 없어요`, 종료 2 | 같음 | 정상 |
| `seongsu cafe 디저트` (영어 혼합) | 성수 어니언 신메뉴, 애월 디저트 카페 | `EMBEDDING_CACHE_MISS` | 녹화본 밖 질의 캐시 미스는 기존 동작 |
| `지난주 저장한 영상` | 10/11 릴스, 10/10 쇼츠 2건 | 같음 | 시간 필터 정상 |
| `화성 우주정거장 맛집` (없는 대상) | 0건 | 캐시 미스 | 과잉 완화 없음 |
| `인스타 --platform youtube` (요청 잠금) | youtube만 5건 | 같음 | 요청 필터가 질의 플랫폼을 이김 |
| `유튜브 --platform youtube` (필터 전용) | `filter_only=True`, 30건 | — | 정상 |
| `유튜브에서 본 파스타 레시피`, `작년에 저장한 논문` | 파스타 영상 3건 / 2025년 논문 3건 | 같음 | 정상 |
| u_bob·u_carol `카페` (limit 50) | 결과 content_id가 각자 것뿐(2건 / 1건) | 같음 | 사용자 격리 유지 |
| u_nobody `카페` | 0건 | — | 격리 유지 |

T24는 검색 코드를 건드리지 않았고 결과는 이전 검수들과 같다.

## 2. Loop 1 재검수 조건 대조

| 조건 | 판정 | 근거 |
|---|---|---|
| 1. M1 영구 실패 → 리포트, (n−1)/n, `failed`, gate FAIL, CLI 종료 1, 회귀 테스트 | **충족** | 1.4절 E1. `ingest_harness.py:476-502`. 테스트 `tests/eval/test_ingest_regression.py:61-95`가 47/48, attempts 3, error_code, CLI 종료 1과 리포트 파일 생성을 단언 |
| 2. M2 비율 [0,1], 같은 분리기, forbidden 규칙 문서화, `?`·forbidden·중복 테스트 | **충족** (분리기 자체 결함은 N1로 별도) | `judge.py:87-99`, 리포트 Markdown 문구(`ingest_report.py:99-101`), `tests/unit/test_ingest_judge.py:45-66` |
| 3. M3 어려운 사례 gold, forbidden 80건 비동일, 조사 오류 없음, 재작성 필요 기록, 결정성·validate 유지 | **충족** (조사 오류 3건 잔존은 L-4로 감점 0.5) | 1.7절 |
| 4. M4 lexicon 전달 + 하네스 경로 테스트 | **충족** | `ingest_harness.py:514, 648-653`, `tests/unit/test_ingest_metrics.py:53` |
| 5. M5 content_id 결합 또는 needle 검증, `key_facts=[""]` 거부 | **충족** (두 가지 모두) | `ingest_harness.py:380-390, 473`, 1.4절 E2·E3 |
| 6. 게이트·결정성·검색 수치·검색 diff 0 유지 | **충족** | 1.1~1.2, 1.8절 |
| 7. L1~L7 (권장) | 대부분 충족 | L1 숫자 경계·영문 고유명사, L2 첫 시도 표시, L3 검증기(공백·review/annotator·platform group·빈 forbidden), L4 검증 선행·보수적 추정(28,245 → 69,145), L5 CLI 한 줄·종료 2, L6 evidence를 key fact 구절로·test 주입 2건, L7 부정 경로 테스트·자모 거리 1 입력·스냅샷 원문(`ingest_harness.py:504-508`)·포맷. 잔여는 4절 L-1~L-5 |

## 3. 설계 대조 (3.5.6절 시그니처, 필드 단위)

| 설계 | 구현 | 판정 |
|---|---|---|
| `IngestEvalConfig.mode/split/sources_path/annotations_path/baseline_path/judge_profile/run_search_linkage/confirm_cost` | 모두 있음 (`ingest_harness.py:302-312`) | 일치 |
| `IngestEvalConfig.profile = "default"` | `"mock"` | Loop 1에서 수용한 근거 유지 |
| (설계에 없음) `regression_tolerance = 0.01` | 있음 | 3.5.4절 회귀 규칙 매개변수화. 수용 |
| `IngestItemResult.source_id/job_status/attempts/schema_first_pass/schema_final_pass/metrics/cost_usd/latency_ms/unsupported_sentences` | 모두 있음 (`:315-328`) + `platform_group/input_tokens/output_tokens/error_code` | 일치(확장). `error_code`는 M1 개선 제안 반영 |
| `IngestEvalReport.config/overall/by_platform/search_linkage/items/gate` | 모두 있음 (`:331-339`) + `golden_status/counts` | 일치(확장) |
| `IngestEvalHarness.__init__(config, container_factory)` | `Callable[[IngestEvalConfig], AppContainer]`, 기본값 있음 | 호환 |
| `estimate_cost() -> CostEstimate` | 있음, run과 같은 골든 검증 선행 (`:420-435`) | 일치 |
| `run() -> IngestEvalReport` | 있음 | 일치 |
| `compare_profiles(...) -> SwapDecision` | `NotImplementedError` | T26 범위. 감점 없음 |
| CLI `jupjup eval ingest [--mode] [--profile] [--split] [--judge] [--baseline] [--confirm-cost]` | 모두 있음 + `--out` | 일치 |
| `tests/eval/test_ingest_regression.py`가 mock 열 단언 | 있음 + 부정 경로 4개 | 일치 |
| 4장 배치 `eval/ingest_metrics.py`, `ingest_harness.py`, `judge.py`, `data/baselines/ingest.mock.json` | 모두 있음, 기준선 변경 0 | 일치 |
| 3.5.2절 "끝내 실패하면 잡은 `failed`" | 실패 항목 `job_status=failed` | 일치 |
| 3.5.3절 "원문(스냅샷 텍스트)" | 저장된 스냅샷 `text + ocr_text` 사용 | 일치 |
| AC-28 "계산 불가한 항목은 해당 없음" | 첫 시도 준수율은 값 표시, 품질·검색 연결은 `해당 없음` | 일치 |

## 4. 피드백 (심각도 순)

### N1. [중간] 문장 분리기가 소수점에서 문장을 잘라, 충실한 숫자 요약을 비충실로 판정한다
- **위치:** `src/jupjup/eval/judge.py:14` (`_SENTENCE = r"[^.!?。！？\n]+(?:[.!?。！？]+|$)"`), 사용처 `judge.py:55`(`check`), `:93`(`unsupported_sentence_metrics`)
- **재현:** 1.5절. `증감률 6.5%를 공개했다.` → `['증감률 6.', '5%를 공개했다.']`, 조각마다 숫자 `6`, `5%`가 원문 숫자 집합(`6.5%`)에 없어 둘 다 후보, 비율 1.0. 정상 골든에서도 `ing_0036`~`ing_0040` 5건이 gold를 그대로 옮긴 요약인데 0.6667, test 리포트 Markdown 충실도 절에 3건이 거짓 후보로 나온다.
- **영향:** Loop 2에서 일부러 넣은 `number_date_dense` 사례가 바로 이 경로를 시험하는데, 검사기가 그 사례를 거꾸로 채점한다. mock 게이트는 overall `해당 없음`이라 영향이 없지만, 항목 JSON에는 값이 나가고, T25 기본 분석기 열(비충실 ≤ 0.03)과 판정기 2차 검사(문장 단위 판정)의 분모·분자가 이 분리기를 그대로 쓴다. 실제 LLM 요약에는 `3.5%`, `1.2배`, `v2.1`, `2026.10.06` 같은 표기가 흔하다. 보고서는 "모든 비율 [0, 1]"만 확인했고 리포트에 찍힌 `6. / 5%` 조각을 놓쳤다.
- **개선:** 마침표는 앞뒤가 모두 숫자면 문장 끝으로 보지 않는다(예: `(?<!\d)\.(?!\d)` 경계, 또는 Kiwi `split_into_sents` 사용). `6.5%`, `3.14`, `2026.10.06`, `v2.1` 요약이 1문장으로 남고 후보가 아니라는 단위 테스트와, 정상 골든 mock all에서 `unsupported_sentences`가 0건이라는 회귀 단언을 추가한다.

### L-1. [낮음] 중복 문장: 분자는 집합, 분모는 중복을 포함한 목록이라 비율이 낮게 나온다
- **위치:** `src/jupjup/eval/judge.py:96-98`, 테스트 `tests/unit/test_ingest_judge.py:61-66`
- 같은 근거 없는 문장이 두 번 나오는 2문장 요약은 모든 문장이 근거 없음인데 0.5다(테스트가 이 값을 단언한다). `기관 99곳. 기관 99곳. 좋다.`는 0.333. Loop 1 M2의 "집합으로 센다"는 같은 후보를 두 번 세지 말라는 뜻이었고 분모와 단위를 맞추는 것이 전제였다(검수 문구가 모호했던 점도 있어 감점은 작다). 분모도 고유 문장 수로 하거나, 분자를 문장 위치 기준으로 세어 둘을 맞추고 테스트 기대값을 고친다.

### L-2. [낮음] 영어 고유명사 검사가 문장 첫 대문자 단어를 모두 후보로 잡는다
- **위치:** `src/jupjup/eval/judge.py:18, 79`
- `This is fine.`의 `This`가 원문에 없으면 후보가 된다. 지금 영어 중심 사례의 mock 요약은 한국어라 드러나지 않지만, T25에서 영어 요약이 나오면 거짓 양성이 늘어난다. 문장 첫 단어는 원문 소문자 비교로 넘기거나 불용어(This, The, It, We…)를 빼는 정도로 충분하다.

### L-3. [낮음] 추출 결과가 빈 fixture는 검증을 통과한 뒤 run 전체를 멈춘다
- **위치:** `src/jupjup/eval/ingest_harness.py:449` (run 시작 시 모든 건의 `_source_text`를 미리 계산), `:568-578`
- 1.4절 E5. CLI에서는 종료 2 "평가 오류"로 깔끔하게 끝나므로 안전 문제는 아니고, 데이터 오류라 "평가 오류"로 보는 것도 방어 가능하다. 다만 M1과 같은 이유로, 파이프라인이 실제로 그 건을 `failed`로 끝내는 경로(추출 실패)를 하네스가 항목으로 기록하지 못한다. 검증기에서 fixture를 추출해 비어 있으면 거부하거나, mock fixture용 원문 계산을 항목 루프 안으로 옮겨 실패 항목으로 남긴다.

### L-4. [낮음] 템플릿 조사 오류 3건 잔존
- **위치:** `scripts/generate_ingest_golden.py`(영어 중심 key fact 템플릿), `data/golden/ingest/annotations.jsonl`·`sources.jsonl`의 `ing_0047`, `ing_0049`, `ing_0050` (`Benchmark 2을`, `4을`, `5을` → `를`)
- Loop 1 재검수 조건 3번 "템플릿 조사 오류가 없다"의 잔여다. 숫자 뒤 조사는 숫자 읽기(일·이·삼…)에 따라 고르거나, 템플릿을 `Benchmark N 결과를 공개한` 식으로 바꿔 숫자에 조사가 붙지 않게 한다.

### L-5. [낮음] 정리
- 리포트 JSON `config.sources_path/annotations_path/baseline_path`가 절대 경로라, 같은 커밋이라도 체크아웃 위치가 다르면 리포트 바이트가 달라진다(같은 머신 두 번 실행 동일성은 충족). 저장소 기준 상대 경로로 직렬화하면 기준 리포트를 커밋·비교하기 쉽다.
- `ingest_metrics.accuracy([])`가 1.0이라 split에 주입 사례가 0건이면 주입 저항 게이트가 공허하게 통과한다. 지금은 검증기가 test ≥ 2건을 강제하고 dev도 1건이라 실제 문제는 아니다. 0건이면 `None`(해당 없음)을 내고 게이트를 실패시키는 편이 안전하다.
- `ingest_report.py:99-101`의 Markdown 문장 끝에 공백이 붙어 있다(렌더링 영향 없음).
- live 비용 추정은 보수적 문자 기준(69,145)이 test mock 측정 입력 토큰(건당 3,690.6 × 32 ≈ 118,099)보다 여전히 작다. mock 측정값의 의미가 실제 청구 토큰과 같지 않으니 T25에서 실제 토크나이저로 바꿀 때 확인한다(보고서 5절에 명시돼 있어 감점 없음).

## 5. 채점 근거

- **정확성 37 / 40:** M1~M5와 T24 완료 조건 다섯 가지, 검색 무회귀를 직접 재현해 확인했다(+). 감점: N1 문장 분리기 소수점 결함으로 새 숫자·날짜 사례 5건이 거짓 비충실(−2), 중복 문장 분모 불일치(L-1)와 조사 오류 잔존(L-4) 합쳐 −1.
- **안전성 29 / 30:** 외부 네트워크 미접근(소켓 차단 실행), live/recorded가 Mock으로 대체되지 않음, 비용 확인 없는 live 거부, CLI 오류 경로 전부 한 줄·종료 2, 실패 건 항목화와 FAIL 종료 1 분리, content_id 결합으로 조용한 오채점 제거, 검증기 강화 모두 좋다. 감점: 추출 실패 fixture가 항목이 아니라 run 중단(L-3)과 빈 집합 정확도 1.0(L-5) 합쳐 −1.
- **유지보수성 28 / 30:** 테스트 18개 추가(영구 실패·주입 누출·기준선 회귀·검증기 거부 등 부정 경로 포함), 포맷 통과, 보고서와 실제 동작 일치, 실패 항목 Markdown 절 추가가 좋다. 감점: 리포트에 거짓 후보 `6. / 5%`가 찍혀 있는데 소수점 테스트가 없고 보고서가 놓침(N1 테스트 공백 −1), 중복 문장 테스트가 의미상 틀린 값을 고정(L-1) −1.

## 6. 후속 조건 (PASS이지만 T25 착수 전에 처리할 것)

1. **N1:** 소수점·버전·점 구분 날짜에서 문장을 자르지 않는다. 단위 테스트(`6.5%`, `3.14`, `2026.10.06`, `v2.1`)와 "정상 골든 mock all에서 `unsupported_sentences` 0건" 회귀 단언을 둔다.
2. **L-1:** 비충실 비율의 분자·분모 단위를 맞추고 `test_duplicate_unsupported_sentences_are_counted_as_a_set` 기대값을 고친다.
3. L-2~L-5는 권장. 특히 L-2(영어 문장 첫 단어)는 T25 영어 요약 판정 전에 같이 고치기를 권한다.
4. 위 수정 뒤에도 `pytest`, `ruff check`, `mypy src`, `eval validate`, `eval ingest --mode mock --split dev|test|all` PASS와 두 번 실행 바이트 동일, 검색 eval 4종 수치 동일, `src/jupjup/search`·`src/jupjup/query` diff 0을 유지한다.

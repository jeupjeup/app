# Phase 4 최종 검수: T25g 판정기와 보정 도구, Loop 1/3

- **점수:** 94 / 100
- **상태:** PASS
- **항목별:** 정확성 37 / 40, 안전성 29 / 30, 유지보수성 28 / 30
- **루프백 대상:** 없음 (PASS). M1은 **T25h에서 판정기를 live로 녹화하기 전에** 고치길 권한다. L1~L4는 다음에 같은 파일을 만질 때 고치면 된다.
- **검수 대상:** `4d63ec6 feat: T25g local faithfulness/key-fact judges, combined rule, deterministic key-fact matcher, kappa calibration tools` (기준 `3a49bc0`)
- **검수자:** Claude-Reviewer 역할 대행 (Claude Opus 5.5). 코드는 고치지 않았다. 재현 실험은 스크래치 디렉터리(탐침 스크립트 p1~p7, `git archive 3a49bc0` 사본과 그 venv, 소켓 차단 pytest 플러그인)와 `var/review.db`에서만 했다. 저장소 `data/`에는 아무것도 생기지 않았다.
- **범위 밖:** T26a(후보 비교), T25h(실제 모델 녹화, 실제 κ 보정). 사람 라벨이 아직 없는 것, 실제 판정 모델 호출이 없는 것은 감점하지 않았다.

## 0. 한 줄 판정

10.1절 T25g 완료 조건 다섯 개를 **모두 직접 재현했다.** κ는 내가 새로 만든 10쌍 예(3분류 0.53125, 이진 0.78261)와 교과서 2×2 예(0.4)에서 손계산과 같았다. 결합 규칙 12행 표 테스트가 설계 8.3절 규칙과 같다. 판정기 실패는 `judge_failed`로 따로 세지고 비충실에 더해지지 않는다. v1 mock all 160개, v2 mock all 298개 사실에서 결정적 매처가 부분 문자열 결과와 **건별로 모두 같았다.** 판정기 녹화·재생은 내가 만든 **적대적 가짜 판정기**(중복 번호, 없는 번호, 깨진 JSON, 제공자 오류를 섞음)로 live 녹화 → recorded 재생 두 번을 해서 바이트가 같은 것을 봤다.
기본 게이트도 통과했다: pytest 1226 passed(skip 0), ruff, mypy, `eval validate`, 검색 eval 4종(수치가 T25f 검수와 같고 기준 사본과 비교해 시각·지연·경로 외 차이 없음). mock 인제스트 6개(v1·v2 × dev·test·all)는 두 번 실행끼리, 그리고 **기준 커밋 사본과도 바이트가 같다.** 소켓을 막은 실행에서 네트워크 시도는 0건이었고, `llama_cpp`는 import되지 않았다.
감점은 한 가지 중간 문제(M1)와 작은 문제 넷에서 나왔다. M1: live에서 판정기 **제공자 오류·타임아웃은 `judge_failed`로 세지지만 녹화되지 않는다.** 그래서 같은 녹화를 recorded로 재생하면 그 요청이 미스가 되고 평가와 보정이 모두 종료 2로 끝난다. 실제 8B 판정기에서 타임아웃이 한 번만 나도 그 녹화는 재생할 수 없다.

## 1. 직접 실행한 명령과 결과

### 1.1 기본 게이트 (프로젝트 venv, extra 없음)

| 명령 | 결과 |
|---|---|
| `uv run pytest` (`-o addopts=""` + 기본 마커 제외로 요약 줄 확인) | **1226 passed, 4 deselected**, 경고 2건(기존 Starlette 1, 테스트가 의도한 `RuntimeWarning` 1). skip 0 (AC-L1) |
| `uv run ruff check src tests` | All checks passed! |
| `uv run mypy src` | Success: no issues found in 89 source files |
| `uv run jupjup eval validate` | 종료 0 (ingest 80 = dev 48 / test 32) |
| `eval run --mode mock --split dev` | 종료 0. R@10 0.9620, MRR 0.9958, nDCG 0.9795 |
| `eval run --mode mock --split test` | 종료 0. 0.9420 / 0.9867 / 0.9589 |
| `eval run --mode recorded --split dev` | 종료 0. 0.9712 / 1.0000 / 0.9860 |
| `eval run --mode recorded --split test` | 종료 0. 0.9720 / 0.9911 / 0.9801 (네 줄 모두 T25f 검수 값과 같음) |
| 위 4개 JSON을 `git archive 3a49bc0` 사본(별도 venv, `jupjup.__file__`이 사본 `src`인지 확인) 결과와 재귀 비교 | 차이는 `created_at`, `git_sha`, `perf.latency_*`, `config.*_path`뿐 → 검색 수치 무회귀 |
| `eval ingest --mode mock --golden v1\|v2 --split dev\|test\|all` 2회 + 사본에서 1회 | 18회 모두 종료 0. 6개 출력 디렉터리가 1회 대 2회, 1회 대 사본 **모두 바이트 동일** (AC-L2, 핵심 사항 2) |
| `git diff --stat 3a49bc0 HEAD -- src/jupjup/search src/jupjup/query data src/jupjup/providers src/jupjup/container.py src/jupjup/api` | **0줄** |
| `jupjup.cli`, `eval.judge`, `eval.judge_tools`, `eval.judge_calibration`, `eval.ingest_harness`, `eval.ingest_runtime` import 뒤 `sys.modules` | `llama_cpp` False, `jupjup.providers.llm_local` False |
| `grep -rn "import llama_cpp\|from llama_cpp" src` (`llm_local.py` 제외) | 0건. `ingest_runtime.py:263`의 `llm_local` 지연 import(기존)뿐 (AC-L16) |

### 1.2 T25g 완료 조건 재현 (10.1절)

| 완료 조건 | 직접 확인 | 판정 |
|---|---|---|
| κ 계산 손계산 일치 | 탐침 p3. 사람 `ssuupsusps` 대 판정 `suuussuspp`(s=supported, u=unsupported, p=partially): p_o 0.7, p_e (5·4+3·4+2·2)/100 = 0.36 → κ3 **0.53125**. 이진(unsupported 대 나머지) p_o 0.9, p_e (3·4+7·6)/100 = 0.54 → **0.782609**. `cohen_kappa` 결과 같음. 2×2 교과서 예(a=20, b=5, c=10, d=15) 0.4 같음. 한 범주뿐이면 `None` + "정의할 수 없음" 사유, 99쌍 완전 일치는 표본 부족으로 미통과, 100쌍 완전 일치는 통과. 보정 파일의 혼동표로 κ를 다시 계산해도 같은 값 | 충족 |
| 결합 규칙 표 테스트 | `tests/unit/test_judge_t25g.py:157-187` 12행(보정 × 1차 후보 × 판정 4종)이 8.3절 규칙과 같다: 보정 통과면 `unsupported` 또는 (후보 ∧ `≠ supported`), `partially`는 비충실 아님·따로 셈, 미보정이면 1차만, `judge_failed`는 1차를 따름. 실제 하네스에서도(p2) 보정 통과 파일을 주면 비충실 비율이 0.1125(1차) → 0.3375(결합)로 바뀌고, 프롬프트 sha256만 바꾼 보정 파일은 "보정 뒤 바뀜: 프롬프트 sha256"으로 미보정 처리됐다 | 충족 |
| 판정기 실패가 `judge_failed`로 따로 세짐 | p2: 적대적 판정기 123회 호출(제공자 오류 12, 중복 13, 깨진 JSON 18, 없는 번호 18). 리포트 판정 문장 64개 중 `judge_failed` 7, `partially` 17, `unsupported` 22, 핵심 사실 `judge_failed` 15, 재요청 36회. 미보정이므로 대표 비충실 비율 = 결정적 값(0.1125)이고 판정기 `unsupported`는 더해지지 않았다. 핵심 사실 `judge_failed`는 결정적 매처 값으로 센다(보고서 2절 4번과 일치) | 충족. 단 녹화·재생 쪽은 **M1** |
| v1 mock all에서 결정적 매처 = 기존 부분 문자열 | p1: v1 80건 160개, v2 80건 298개 사실을 건별로 `normalize_text(fact) in normalize_text(summary)`와 비교 → **불일치 0**. 통합 테스트도 같은 단언 | 충족 |
| 판정기 녹화·재생 | p2: 위 적대적 판정기로 live+record → recorded 2회. 재생 2회의 JSON·MD **바이트 동일**. 녹화 파일 `judge.<stem>.jsonl`에 `보안 규칙`·`<source_document>`·원문 낱말이 없다(AC-L9). 판정기 녹화 미스는 `misses`에 들어가고 CLI가 종료 2로 끝난다. 하지만 live와 recorded의 차이가 `config.mode`·`confirm_cost`·`recording` 외에 **제공자 오류가 난 10건의 판정기 지표 전부**에 있었다 → **M1** | 조건부 충족 |

### 1.3 보정 도구 (CLI)

| 명령 | 결과 |
|---|---|
| `eval judge-sample --candidates local-kanana-2b --mode recorded --recordings-dir <p2> --out <scratch>` | 종료 0. 문장 80개(40건 × 2), 핵심 사실 쌍 60개, 표본 부족 경고. 같은 seed 두 번 → 파일 바이트 동일, seed 7 → 다름. 행마다 요약 전체와 BM25 원문 발췌 5문장 |
| 라벨을 채운 파일로 같은 녹화 디렉터리에 `eval judge-calibrate` | **종료 2, 미스 10건.** 미스 request_hash가 평가 재생(p2)의 미스와 **정확히 같다** → 보정이 평가와 같은 요청을 만든다는 주장은 사실이다. 동시에 M1이 보정 경로도 막는다는 증거다 |
| 오류 없는 가짜 판정기로 `judge_calibrate(mode="live", record=True)`(Python API) → CLI `--mode recorded` | live κ = recorded κ (충실도 3분류 −0.0117, 이진 −0.0643 / 핵심 사실 0.0250, 0.0241). 종료 1(미달), 보정 파일 `labels_file`은 저장소 밖 경로라 파일 이름만 남는다(AC-L17) |
| 라벨 있는 파일에 `judge-sample` (`--force` 없음) | 종료 2 "이미 사람 라벨이 있습니다" |
| `judge-calibrate --mode live` (확인 플래그 없음) / `--mode bogus` / `--judge nope` | 셋 다 한 줄 안내와 종료 2, 트레이스백 없음 |
| `eval ingest --mode mock --judge …` / `--judge nope` / `--split test --judge …`(해시 없음) / 녹화 없는 recorded | 모두 한 줄 안내와 종료 2. test는 판정기 조립 전에 동결 검사로 거부 (AC-L12) |
| `eval ingest --mode live --judge judge-kanana-8b` (확인 플래그 없음) | 추정만 출력하고 실행 안 함. 추정에 판정기 시간이 빠져 있다 → **L1** |
| 준-사람 라벨(`human_labels=false`)로 통과한 보정 파일로 recorded 평가 (p7) | 판정기 절에 "사람 판정 아님"이 있지만, 머리말과 지표 표는 "보정 통과"로만 적는다 → **L2** |

### 1.4 결정적 매처 경계값 (p6, 실제 Kiwi 토크나이저와 lexicon)

| 사실 → 요약 | 결과 |
|---|---|
| "환불이 안 된다" → "환불이 된다고 안내했다." / 반대 방향 | 둘 다 False (부정 일치 검사) |
| "오후 2시에 시작한다" → "오후 12시에 시작한다." / "오후 2시부터 시작됩니다." | False / True |
| "참가비는 3만 원이다" → "참가비 3만 원을 내야 한다." / "30,000원" | True / False (표기 차이, 보고서 5절 3번에 적힘) |
| "가격이 올랐다" → "가격이 크게 내렸다. 수요는 올랐다." | False (문장 간 낱말 모으기 거부) |
| "The meeting is not on Monday" → "The meeting is on Monday." | True (영어 부정 미처리, 보고서 5절 3번에 적힘) |
| "A사가 B사를 인수했다" → "B사가 A사를 인수했다." | True (낱말 주머니 한계. 설계 8.4절 규칙 자체의 한계라 감점하지 않음) |
| 빈 사실 / 특수문자뿐 | False |

### 1.5 검색 CLI 회귀·경계값 (`seed load --db var/review.db`, `--now 2026-10-15T12:00+09:00`, 사본에도 같은 DB를 만들어 비교)

| 질의 (사용자) | mock | recorded | 사본(3a49bc0)과 비교 |
|---|---|---|---|
| 지난달 성수동 카페 (alice) | 6건 | 6건 | 같음 |
| 성수똥 카패 (오타) | 10건 | `EMBEDDING_CACHE_MISS` 종료 2 (골든 밖 질의, 기존 동작) | 같음 |
| 빈 문자열 / 공백 1칸 / 250자 | `INVALID_QUERY` 1~200자, 종료 2 | 같음 | 같음 |
| `!!!@@@###` | `INVALID_QUERY` 검색할 단어 없음 | 같음 | 같음 |
| 영어 혼합 `python asyncio 튜토리얼` / 없는 대상 `화성 식민지 부동산 투자` | 0건 | 캐시 미스 종료 2 (기존 동작) | 같음 |
| 필터 전용 `유튜브` / `어제 저장한 인스타` | browse 10건 / 0건 | 같음 | 같음 |
| 성수동 카페 (bob / carol / 없는 사용자) | 2건 / 1건 / 경고 + 0건 (사용자 격리) | 같음 | `query_id`·`timing_ms`만 다름 |

26건 모두 사본과 비교해 `query_id`와 `timing_ms`만 다르다. 이번 변경은 검색 경로를 건드리지 않았다.

### 1.6 안전성 확인

| 항목 | 확인 | 결과 |
|---|---|---|
| 네트워크 0 (AC-L8) | 소켓 차단 플러그인(`connect/connect_ex/create_connection/getaddrinfo`)으로 `test_judge_t25g.py`, `test_judge_record_replay.py`, `test_ingest_record_replay.py` 실행. 탐침 p2도 같은 방식으로 차단 | 전부 통과, **시도 0건** |
| 녹화 파일에 프롬프트 원문 없음 (AC-L9) | 판정기 녹화 행 키는 기존 v2 형식 그대로. 미스 목록·Markdown에는 해시와 파라미터만 있다 | 충족 |
| 프롬프트 주입 방어 (AC-L11) | 두 판정 프롬프트 모두 블록 안 지시를 따르지 않는다는 보안 규칙이 있고, 기존 `PromptTemplate.render`의 닫는 태그 탈출 방지를 그대로 쓴다. `retry_note`는 블록 밖에 들어가지만 번호와 고정 문구만 담는다. 분석기 프롬프트와 문구가 다르다(테스트) | 충족 |
| test 봉인 | `judge-sample`은 dev만 돌리고, `judge-calibrate`는 test 건 라벨을 거부한다(테스트 통과). `eval ingest --split test --judge`는 동결 검사가 먼저다 | 충족 |
| 로그·리포트에 원문 없음 (AC-L13) | 판정기 `evidence`(원문 인용)는 `SentenceJudgment.rationale`에만 있고 리포트로 나가지 않는다. 제공자 오류 메시지는 삼켜진다 | 충족 |
| mock 바이트 보존 | mock + `--judge`는 거부, mock 리포트에 `judge` 키 없음, 6개 파일이 사본과 바이트 동일 | 충족 |

## 2. 피드백 (심각도 순)

### M1. live에서 판정기 제공자 오류·타임아웃은 `judge_failed`로 세지만 녹화되지 않아, 그 녹화는 재생할 수 없다 (정확성 −2)
- 위치: `src/jupjup/eval/judge.py:389-392` (`except JupjupError: break`), `src/jupjup/providers/recording.py` `RecordingLLM.complete_json`(성공 응답만 녹화. 형식 v2는 바꾸지 않기로 했음), `src/jupjup/eval/ingest_harness.py:726`
- 현상: p2에서 live 녹화 때 제공자 오류 12회 → 해당 문장·사실은 `judge_failed`가 됐다. 같은 녹화를 recorded로 재생하면 그 요청은 `LLMCacheMiss` → 10건이 미스 목록에 들어가 **종료 2**이고, 그 건의 판정기 지표가 통째로 빠진다(live 리포트와 다름). 보정도 같은 요청을 쓰므로 `judge-calibrate`도 미스 10건으로 종료 2였다. 실제 8B 판정 모델에서 타임아웃이 한 번만 나도 녹화 전체를 다시 떠야 하고, `--append`로 다시 녹화해도 결정적 디코딩이면 같은 타임아웃이 반복될 수 있다. live 실행 때는 이 사실을 알리지 않는다.
- 관련: 분석기 경로(T25f)에도 같은 성질이 있지만, T25g는 "제공자 오류 → 재요청 없이 `judge_failed`"를 설계상 정상 결과로 만들었다. 그래서 live와 recorded가 서로 다른 결과를 내는 경로가 생겼다. 완료 조건 "판정기 녹화·재생"이 오류가 없는 경우에만 성립한다.
- 개선: (a) 판정기 녹화 경로에서 제공자 오류를 **별도 사이드카**(`judge.<stem>.failures.jsonl`: `request_hash`, 오류 코드만. 형식 v2 파일은 그대로)에 남기고, recorded 판정기 클라이언트가 그 해시를 `LLMProviderError`로 재생하게 한다. 또는 (b) live+record에서 판정기 제공자 오류가 하나라도 나면 리포트·CLI에 "재생 불가 요청 N건"을 경고하고 종료 코드를 2로 바꾼다. 어느 쪽이든 `test_judge_record_replay.py`에 "제공자 오류가 섞인 live 녹화 → recorded 재생이 같은 리포트" 테스트를 더한다. T25h에서 판정기를 live로 녹화하기 전에 고치길 권한다.

### L1. live `--judge` 실행 추정에 판정기 시간이 빠져 있다 (정확성 −1)
- 위치: `src/jupjup/eval/ingest_harness.py:587-594` (`estimate_run(setup.spec, …)`가 분석기 모델만 본다)
- 현상: `eval ingest --mode live --profile local-kanana-2b --judge judge-kanana-8b`가 "약 13.3분 (48건 × p50 16.6초)"만 출력한다. 판정기(8B, 건당 충실도 1회 이상 + 핵심 사실 1회 + 재요청)는 분석기보다 큰 모델이라 실제 시간은 훨씬 길다. AC-33 로컬판(실행 전 예상 소요 시간 안내)의 취지에 못 미친다. 판정 모델이 분석기와 함께 메모리에 올라간다는 점도 알리지 않는다.
- 개선: `--judge`가 있으면 판정 모델의 `measured_p50_s`(없으면 "측정값 없음")로 판정기 추정을 따로 한 줄 내고 합계를 보인다. `judge-calibrate --mode live`에도 같은 추정을 낸다.

### L2. 준-사람 라벨로 통과한 보정도 머리말과 지표 표에서는 그냥 "보정 통과"로 적힌다 (안전성 −1)
- 위치: `src/jupjup/eval/ingest_report.py:56`, `:60`, `:84`
- 현상: p7에서 `human_labels=false` 보정 파일로 평가하면 머리말이 "판정기 … 보정 통과: 비충실 문장 비율은 1차·2차 결합 값이다", 지표 표 비고가 "(보정 통과)"이다. "사람 판정 아님"은 아래 판정기 절의 한 줄에만 있다. Q-LA3 기본값은 준-사람 라벨을 쓰더라도 "κ 기준 통과를 PRD 의미의 보정으로 주장하지 않는다"이다. 게이트 판단에 쓰는 것은 허용되지만, 게이트를 읽는 사람이 보는 자리에 표시가 없다.
- 개선: `human_labels is False`이면 세 자리 모두 "보정 통과 (준-사람 라벨, 사람 판정 아님)"으로 적고, 게이트 행 이름에도 `(준-사람 보정)` 같은 꼬리를 붙인다. CLI 요약 줄에도 같은 표시를 낸다.

### L3. 보정 도구의 핵심 사실 미스 기록에 `source_id`가 `-`로 남는다 (유지보수성 −1)
- 위치: `src/jupjup/eval/judge_tools.py:171-176`
- 현상: `judge_keyfacts`가 `(summary, facts)`만 받아서 미스가 나면 `miss_record("-", exc)`로 남는다. 충실도 미스는 건 id가 있는데 핵심 사실 미스는 어느 건인지 미스 목록만으로 알 수 없다. 녹화를 이어 붙일 대상을 찾기 어렵다.
- 개선: `KeyFactJudgeFn`에 `source_id`를 넣는다(`judge_calibration.py:310`, `:367`).

### L4. 보정 도구가 원문을 얻으려고 mock 하네스 전체를 만든다 (유지보수성 −1)
- 위치: `src/jupjup/eval/judge_tools.py:147-162`, `src/jupjup/eval/ingest_harness.py:878-892`
- 현상: `judge_calibrate`가 원문 텍스트만 필요한데 `IngestEvalHarness(IngestEvalConfig(mode="mock", …))`를 만들어 `golden_source_text`를 부른다. 원문 추출(`_source_text`)이 하네스 메서드에 묶여 있어 보정 도구가 하네스 설정 모델에 기대게 됐다. 지금 동작은 맞다(p1에서 80건 모두 스냅샷 원문과 같음을 확인).
- 개선: `_source_text`를 모듈 함수 `golden_source_text(sources_path, source)`로 빼서 하네스와 보정 도구가 같이 쓴다.

### 참고 (감점 없음)
- T25f 검수 M1(recorded 연결 지표의 임베딩 미스), L1(연결 지표 미측정 표시), L2(동결 해시에 `n_ctx` 없음)는 이번 커밋에서 고쳐지지 않았다. T25g 완료 조건이 아니라서 감점하지 않았지만, **T25f M1은 T25h 채택 판단 전에 꼭 고쳐야 한다**는 이전 권고는 그대로다.
- 결정적 매처를 설계보다 엄격하게 한 것(문장 단위 비율, 서술어·부정 일치, 부분 문자열 우선)은 보고서 2절 1번에 이유가 있고, v1·v2 mock 결과를 바꾸지 않는 것을 확인했다. 설계 대비 강화이므로 받아들인다.
- `JudgeItem` 필드 순서(`index, evidence, verdict`)와 `judge_failed` 판정값 추가도 보고서에 이유가 있고 의미는 같다.
- 실제 판정 모델로 문법 제약 디코딩을 확인하지 않은 것, κ 실측이 없는 것은 T25h 범위이고 보고서 5절에 숨김없이 적혀 있다.

## 3. 채점

| 항목 | 점수 | 근거 |
|---|---|---|
| 정확성 | 37 / 40 | 완료 조건 5개, AC-L1·L2·L16·L17, 보정 요청 = 평가 요청(미스 해시 일치로 확인), seed 결정성, 결정적 매처 무회귀를 모두 재현했다. M1 −2 (제공자 오류가 난 live 녹화는 재생할 수 없고, live와 recorded 결과가 갈린다), L1 −1 (판정기 시간이 빠진 실행 추정) |
| 안전성 | 29 / 30 | 네트워크 0, `llama_cpp` 미import, 녹화에 프롬프트 원문 없음, 블록 탈출 방지·보안 규칙, test 봉인(dev 전용 라벨, 동결 검사 선행), live 확인 플래그, 라벨 덮어쓰기 방지, 입력 오류 모두 한 줄 안내와 종료 2. L2 −1 (준-사람 보정의 "보정 통과" 표시) |
| 유지보수성 | 28 / 30 | 판정기는 `LLMClient`만 쓰고 엔진을 모른다. 프롬프트는 버전 파일이고 sha256이 보정 파일과 리포트에 남는다. 판정기 녹화 파일을 분석 녹화와 나눴다. 테스트 49개가 규칙 표·재요청 4종·BM25 동점·스키마 상한·보정 CLI 가드까지 덮는다. L3 −1, L4 −1 |
| **합계** | **94 / 100** | **PASS** |

## 4. 다음 단계 권고

- PASS이므로 루프를 끝낸다. M1은 T25h에서 판정기 live 녹화(kanana-8b)를 하기 **전에** 고치는 것이 좋다. T25h 브리프에 "판정기 제공자 오류 재생" 항목을 넣길 권한다.
- L1~L4는 T26a나 T25h가 같은 파일(`ingest_harness.py`, `ingest_report.py`, `judge_tools.py`)을 만질 때 같이 고친다.
- T25f 검수 M1(연결 지표 임베딩 미스)은 여전히 열려 있다. T25h 채택 판단 전에 고쳐야 한다.

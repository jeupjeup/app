# Phase 2 T25g 보고서: 판정기와 보정 도구

- 작성: Codex-Primary 역할 (Claude가 실행)
- 기준일: 2026-11-02
- 설계: `specs/design_local_analyzer.md` 8.3·8.4절, 10.1절 T25g, 11절, 14절
- 기준 커밋: `3a49bc0` (PM)

## 1. 구현 범위

| 항목 | 파일 | 내용 |
|---|---|---|
| 판정 스키마 | `src/jupjup/eval/judge.py` | `JudgeItem`·`JudgeVerdicts`(문장, ≤8개), `KeyFactItem`·`KeyFactVerdicts`(핵심 사실, ≤8개). 둘 다 `strict`, `evidence` ≤120자 |
| 충실도 판정기 | `judge.py` `LocalFaithfulnessJudge` | `FaithfulnessJudge` 구현. 8문장씩 묶어 판정. 번호 누락·중복·없는 번호·JSON 깨짐이면 **1회** 재요청(재요청 프롬프트에 문제를 적음). 그래도 빠진 번호는 `judge_failed`. 제공자 오류·타임아웃은 재요청 없이 `judge_failed`. `LLMCacheMiss`는 판정기 실패가 아니라 녹화 미스로 그대로 올린다 |
| 긴 원문 | `judge.py` `bm25_top_sentences` | 입력이 `n_ctx - max_output_tokens - 256`을 넘으면 원문 문장마다 번호를 달고 요약 문장마다 BM25(문자 bigram, 결정적, 동점은 앞 문장) 상위 12문장만 넣어 한 문장씩 판정. `context="retrieved"`로 리포트에 남김 |
| 핵심 사실 판정기 | `judge.py` `LocalKeyFactJudge` | `covered | partial | missing`, `covered`만 포함. 같은 재요청·`judge_failed` 규칙 |
| 결합 규칙 | `judge.py` `CombinedFaithfulness` | 보정 통과면 비충실 = `unsupported` 또는 (1차 후보 ∧ `≠ supported`). `partially`는 따로 셈. 미보정·판정 없음이면 1차만. forbidden claim이면 1.0. `unsupported_sentences()`는 설계 시그니처 그대로, `evaluate()`는 세부 수치까지 |
| 결정적 핵심 사실 매처 | `judge.py` `keyfact_covered_deterministic` | 내용 형태소(Kiwi NNG·NNP·NR·SN·SL·SH·XR·VV·VA lemma, 가벼운 용언 제외, 동의어 정규형) 비율 ≥ 0.6 + 숫자·날짜 모두 있음. 하네스의 `summary_key_fact_recall`이 부분 문자열 대신 이 매처를 쓴다 |
| 판정 프롬프트 2종 | `src/jupjup/ingest/prompts/judge_faithfulness_v1.md`, `judge_keyfact_v1.md` | 분석기 프롬프트와 다른 문구. 블록 안 지시를 따르지 않는다는 보안 규칙, 블록 탈출 방지(기존 `PromptTemplate`) |
| κ·표집·보정 | `src/jupjup/eval/judge_calibration.py` (신규) | `cohen_kappa`, `binarize`, `agreement`, 라벨 행 모델(`SentenceLabelRow`, `KeyFactLabelRow`), `sample_for_labeling`(프로필별 seed 셔플 → 번갈아 뽑기), `calibrate`, `JudgeCalibration`, `calibration_status` |
| CLI 본체 | `src/jupjup/eval/judge_tools.py` (신규) | `collect_dev_summaries`, `judge_sample`, `judge_calibrate` |
| 판정기 조립 | `src/jupjup/eval/ingest_runtime.py` | `prepare_judge_setup`, `build_eval_judges`(recorded → `RecordedLLM`, live → 로컬 LLM, 녹화 시 `RecordingLLM`), `JudgeRuntime`. `_miss_record` → 공개 `miss_record` |
| 녹화 파일 | `src/jupjup/ingest/profiles.py` | `judge_recording_file` → `data/recordings/llm/judge.<recording_file_stem>.jsonl` (분석 녹화와 분리, 형식 v2 그대로) |
| 하네스 | `src/jupjup/eval/ingest_harness.py` | `--judge`(recorded/live 전용, mock이면 오류). 건별 판정 → 결합. 판정기를 쓴 실행만 `*_deterministic`, `summary_key_fact_recall_judge`, `judge_*` 수치와 리포트 `judge` 블록을 더한다. 판정기 녹화 미스는 `misses`에 들어가 CLI 종료 2 |
| 리포트 | `src/jupjup/eval/ingest_report.py` | 미보정이면 게이트 표의 `unsupported_sentence_rate`·`summary_key_fact_recall` 행에 "(판정기 미보정)" 표시. `## 판정기 (8.3·8.4절)` 절(결정적 대 판정기 값, partially, judge_failed, retrieved 건수, 재요청 수, κ, 준-사람 라벨 경고) |
| CLI | `src/jupjup/cli.py` | `jupjup eval judge-sample --candidates P1,P2 [--mode recorded|mock] [--out] [--sentences 100] [--keyfacts 60] [--seed] [--force]`, `jupjup eval judge-calibrate --judge J --labels L [--mode recorded|live --confirm-run] [--out]`, `eval ingest --judge-calibration` |

### 보정 흐름

1. `jupjup eval judge-sample --candidates local-qwen3-4b,local-kanana-2b` → `data/golden/ingest/judge_labels.dev.jsonl`.
   dev만 쓴다. 행마다 문장(또는 핵심 사실), 요약 전체, BM25 원문 발췌 5문장, 빈 `label`, `annotator`가 있다.
   사람 라벨이 이미 있는 파일은 `--force` 없이 덮어쓰지 않는다.
2. 사람이 `label`과 `annotator: "human"`을 적는다 (준-사람 라벨이면 다른 값 → 리포트에 "사람 판정 아님", Q-LA3).
3. `jupjup eval judge-calibrate --judge judge-kanana-8b` → `data/golden/ingest/judge_calibration.judge-kanana-8b.json`.
   판정기를 **평가 때와 같은 요청**(요약 전체 문장, 그 건의 핵심 사실 전체, 같은 원문 텍스트)으로 부르므로 평가 녹화와
   보정 녹화가 같은 행을 쓴다 (테스트로 확인). 3분류 κ와 이진 κ(문장: unsupported 대 나머지, 핵심 사실: covered 대 나머지)를 낸다.
   통과: 이진 κ ≥ 0.7 **이고** 비교 쌍 ≥ 100(문장)·≥ 60(핵심 사실). 종료 코드 0 통과 / 1 미달 / 2 오류·미스.
4. `eval ingest --judge judge-kanana-8b`가 보정 파일을 읽는다. 판정기 프로필, `recording_model_id`, 판정 프롬프트 sha256이
   모두 같고 그 과제가 통과일 때만 판정기 값을 쓴다. 프롬프트를 바꾸면 자동으로 미보정이 된다.

## 2. 설계 대비 차이 (이유)

1. **결정적 매처를 설계보다 엄격하게 했다.** 설계는 "사실의 내용 형태소 중 요약에 있는 비율 ≥ 0.6 + 숫자·날짜 모두"다.
   그대로 구현하면 v2 mock에서 `ing2_0051`의 "수업 참여는 플립드 러닝 반이 유의하게 높았다"가 요약의 두 문장
   ("…플립드 러닝 반 84명과…", "…유의한 차이는 아니었다")에서 낱말을 모아 포함으로 잡혔다 (실제로는 반대 주장). v2 mock
   기준선도 바뀐다. 그래서 (a) 비율과 숫자는 **요약 문장 하나** 안에서 재고, (b) 사실에 내용 용언(VV·VA)이 있으면 그중
   하나는 그 문장에 있어야 하고, (c) 부정 표현(VCN, 않·못하, 안·못) 유무가 같아야 한다. (d) 정규화 부분 문자열이면
   바로 포함(기존 결과의 상위 집합)도 넣었다. 결과: v1·v2 mock all 모두 건별로 부분 문자열 결과와 같다 (v1 160개, v2 298개 사실).
2. **`JudgeItem` 필드 순서**를 `index, evidence, verdict`로 했다 (설계 표기는 `index, verdict, evidence`). 문법 제약 디코딩이
   필드 순서대로 생성하므로 근거를 먼저 인용하게 했다 (분석기의 "근거 먼저" 정책과 같은 이유). 검증은 이름으로 하므로 의미는 같다.
3. **`SentenceJudgment.verdict`에 `judge_failed`를 더했다.** 실패를 판정 목록 안에서 위치별로 세기 위해서다.
   `KeyFactJudgment`(신규)도 같다.
4. **`judge_failed` 처리 세부**: 결합 규칙에서 `judge_failed` 문장은 판정이 없는 것으로 보아 1차 결과를 따른다 (규칙식에서
   자연히 그렇게 됨). 핵심 사실 판정기 값(`summary_key_fact_recall_judge`)에서도 `judge_failed` 사실은 결정적 매처 결과로 센다.
   κ 계산에서는 빼고 `judge_failed` 수를 따로 보고한다. 둘 다 "판정기 실패를 분석기 탓으로 돌리지 않는다"를 따른 선택이다.
5. **`LocalFaithfulnessJudge.__init__`에 `n_ctx`(기본 16384)와 `context_margin_tokens`(256) 키워드를 더했다.** 긴 원문 판단에
   필요하다. `count_tokens`가 `None`(MockLLM)이면 글자 수로 보수 추정한다.
6. **BM25는 문자 bigram**으로 했다. 형태소기에 묶이지 않고 결정적이다. 검색 순위 로직(`src/jupjup/search`)은 쓰지도 바꾸지도 않았다.
7. **게이트 "판정기 미보정" 표시는 Markdown 게이트 표 행 이름에** 붙였다. `GateCheck`는 검색 eval과 공유하는 모델이라
   필드를 더하면 검색 리포트가 바뀐다. JSON에서는 `judge.faithfulness_calibrated`·`keyfact_calibrated`로 알 수 있다.
8. **판정기 녹화 파일을 분석 녹화와 나눴다** (`judge.<id>.jsonl`). 판정 모델이 분석 후보로도 쓰이는 경우(kanana-8b) 섞이지 않게 했다.
9. `judge-sample --mode mock`을 배선 확인용으로 허용했다 (경고 출력). mock 요약은 골든 사실 복사라 라벨 가치가 없다.
10. 판정기는 분석기 동결 해시(`frozen_config_sha256`)에 넣지 않았다. 판정기 변경은 보정 파일의 프롬프트·모델 일치 검사로 막는다.
    T26a 비교 거부 조건(판정기 프로필 일치)은 리포트 `judge.profile`/`recording_model_id`로 확인할 수 있다.

## 3. 테스트 목록

`tests/unit/test_judge_t25g.py` (40개)
- κ 손계산: 3분류 10쌍(κ = 0.29/0.59), 같은 자료의 이진 κ(0.22/0.42), 교과서 2×2 예(κ = 0.4), 완전 일치 1.0, 완전 반대 −1.0,
  p_e = 1·빈 입력은 `None`, 길이·범주 오류
- `agreement`: judge_failed·미표기 제외, 최소 표본, 이진 κ 기준
- 결합 규칙 표 12행(보정 × 1차 후보 × 판정 4종) + forbidden claim, 판정 없음, 위치 기준 중복 문장, 문장 불일치 오류
- 판정기: 정상, 재요청 4종(누락·중복·JSON 깨짐·없는 번호) 회복, 재요청 뒤에도 실패 → `judge_failed`(호출 2회),
  제공자 오류 → 재요청 없이 `judge_failed`, `LLMCacheMiss` 전파, 8문장 묶음, 긴 원문 retrieved(12문장, 원문 순서), BM25 동점,
  핵심 사실 판정기 실패, 스키마 strict·상한·필드 순서, 프롬프트 자리 표시자·블록 탈출·분석기 프롬프트와 다름
- 결정적 매처 7사례(바꿔 쓰기, 숫자 불일치, 부정, 문장 간 낱말 모으기 거부, 빈 사실)
- 표집: seed 결정성·입력 순서 무관·후보별 균등, 라벨 파일 왕복·중복 거부·라벨 존재 감지, `calibrate` 요청 단위(요약 전체 1회),
  `calibration_status` 프로필·모델·프롬프트 불일치

`tests/integration/test_judge_record_replay.py` (9개)
- v1·v2 mock all: 결정적 매처 = 부분 문자열 (건별), mock 리포트에 `judge` 없음
- mock + `--judge` 거부
- live 녹화 → recorded 재생 리포트 동일, 두 번 재생 바이트 동일, 판정기 녹화에 프롬프트 원문 없음, 경로 상대
- judge_failed·재요청이 따로 세지고, 미보정이면 대표값 = 결정적 값, Markdown "(판정기 미보정)"
- 보정 통과 파일 → 결합 규칙·판정기 재현율 사용, 미달 파일 → 결정적 값
- 판정기 녹화 미스 → `misses`, CLI 종료 2
- judge-sample → judge-calibrate: live 녹화와 recorded 재생 κ 동일, 평가 녹화만으로도 보정 재생, CLI 종료 1(표본 부족)
- CLI 가드: 라벨 있는 파일 덮어쓰기 거부, live `--confirm-run` 필요, 잘못된 mode, test split 라벨 거부

수정: `tests/unit/test_ingest_metrics.py` — `_item_metrics`에 토크나이저 인자가 생겨 호출만 고쳤다 (기대값 그대로).

## 4. 직접 실행한 명령과 결과 (기본 설치, extra 없음)

| 명령 | 결과 |
|---|---|
| `uv run pytest` | **1226 passed, 4 deselected** (실패 0, skip 0. deselected는 `embed`·`rerank`·`local_llm` 마커, 기본 제외) |
| `uv run ruff check src tests` | All checks passed |
| `uv run mypy src` | Success: no issues found in 89 source files |
| `uv run jupjup eval validate` | 종료 0 |
| `uv run jupjup eval run --mode mock|recorded --split dev|test` | 4개 모두 종료 0. 기준 커밋 `3a49bc0` 워크트리 결과와 비교해 `created_at`, `latency_*`(리포트에 "비결정적" 표기), 절대 경로 외 전 필드 동일 → 검색 수치 무회귀 |
| `uv run jupjup eval ingest --mode mock --golden v1|v2 --split dev|test|all` | 6개 모두 종료 0(PASS). 두 번 실행 바이트 동일, 기준 커밋 결과와도 **바이트 동일** |
| `git diff 3a49bc0 -- data src/jupjup/search src/jupjup/query` | 빈 diff |
| `python -c "import jupjup.cli, jupjup.eval.judge_tools …; 'llama_cpp' in sys.modules"` | False |
| `uv run jupjup eval judge-sample --candidates mock --mode mock --out <scratch>` | 종료 0, 문장 96개·핵심 사실 60쌍 (mock은 dev 48건 × 2문장이라 100 미만 경고) |

## 5. 남은 문제 (숨기지 않음)

1. **실제 κ 보정은 아직 하지 않았다.** recorded 분석 녹화(T25h)와 사람 라벨(100문장 + 60쌍, Q-LA3)이 없다. 지금
   recorded 평가는 판정기를 붙여도 "보정 파일 없음 → 판정기 미보정"으로 결정적 값만 쓴다. 판정기 live 녹화도 하지 않았다
   (판정 모델 kanana-8b 실측 호출 없음). 이 작업들은 T25h 범위다.
2. **실제 판정 모델로 문법 제약 디코딩을 확인하지 않았다.** `JudgeVerdicts`·`KeyFactVerdicts`는 등록 정책이 없어 빈 정책(정본
   그대로)으로 문법이 만들어진다 (`providers/llm_local.py` 기존 동작). T25b 스파이크 방식으로 1회 live 확인을 권한다.
   kanana-8b GGUF는 T25b 보고대로 q8_0 중간본 재양자화본이라 판정기로 쓰기 전에 f16 경로 재변환을 권한다.
3. 결정적 매처의 부정·용언 규칙은 한국어 형태소 기준이다. 영어 사실("did not")의 부정은 보지 않는다. 숫자는 표기가 같아야
   한다("오후 2시" 대 "14시"는 불일치). 결정적 값은 판정기 보정 전의 보수적 대체값이라는 위치는 그대로다.
4. 긴 원문 판단은 판정 프롬프트 전체의 토큰 수로 한다. retrieved 모드에서도 12문장이 너무 길면 제공자 오류 → `judge_failed`가 된다.
5. `judge-calibrate`의 라벨은 dev 건만 받지만, 라벨 작업자가 test 원문을 보지 않는다는 보장은 라벨 파일에 dev만 들어간다는 것뿐이다
   (`judge-sample`은 dev만 돌린다).

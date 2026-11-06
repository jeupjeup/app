# Phase 4 최종 검수: T25r T25h dev 녹화, Loop 1/3

- **점수:** 98 / 100
- **상태:** PASS
- **항목별:** 정확성 40 / 40, 안전성 29 / 30, 유지보수성 29 / 30
- **루프백 대상:** 없음(PASS). 아래 낮음 2건은 T25h 후속 동결·test 단계 전에 정리할 것을 권고한다.
- **검수 대상:** `cb658cf feat: record T25h local analyzer dev data` (기준 `e925a17`, 현재 통합 HEAD `37111aa`)
- **검수자:** Claude-Reviewer 역할 대행. 구현 코드는 고치지 않았다. 출력은 `/tmp/t25r-review.uzsW85`만 사용했다.
- **범위 밖:** 프롬프트 튜닝, 실제 후보의 test split 실행, 기준선 변경, 사람 라벨 작성. 사람 검수 미완료 자체는 감점하지 않았다.

## 0. 판정 요약

이번 dev 녹화 산출물과 이어 녹화 수정은 검수 범위의 완료 조건을 충족한다. 두 후보의 같은 녹화본으로 `eval ingest --split dev --linkage recorded`를 각각 2회 실행한 결과 JSON·Markdown이 후보별로 바이트 동일했고 `misses=[]`였다. Kanana/Qwen의 품질 게이트 종료 1은 녹화 오류가 아니라 보고된 품질 미달이며, 수치도 구현 보고서와 일치한다.

판정 라벨은 커밋본을 recorded 출력에서 다시 생성한 파일과 `cmp`로 같았다. Pydantic 정본 스키마로 160행을 읽어 문장 100·핵심 사실 60, `sample_id` 160개 고유, 빈 `label`·`annotator` 160개, dev source만 사용했음을 확인했다. LLM 녹화 1,240행과 linkage 982행은 각 파일 안에서 키가 전부 고유했고, LLM 녹화에는 `system`·`user`·`prompt` 키가 없었다.

기본 설치에는 `llama_cpp`가 없고 import되지 않았으며 전체 테스트, ruff, mypy, 골든 검증, 검색 eval 4종이 통과했다. mock 인제스트 test를 실제 모델 팩토리가 호출되면 실패하는 탐침으로 실행해 호출 0과 `llama_cpp` 미로드를 확인했다. 로컬 제공자·서비스 관련 소켓 차단/비녹화 테스트 13개도 통과했다.

후보 품질 자체는 아직 채택 수준이 아니다. schema final은 0.7292/0.7708, recorded linkage Recall@10 하락은 0.059408/0.042770으로 둘 다 기준에 미달한다. 이는 보고서가 숨기지 않았고 이번 범위에서 튜닝·test 실행·기준 완화가 금지되어 있으므로 감점하지 않았다. 이 PASS는 **dev 녹화 작업에 대한 판정**이며 T25 기본 분석기 채택 판정이 아니다.

## 1. 직접 실행한 명령과 결과

### 1.1 기본 게이트와 골든 검증

| 명령 | 직접 결과 |
|---|---|
| `uv run pytest` | 종료 0, **1334 passed, 5 deselected**, 경고 2. 현재 통합 HEAD에 함께 들어온 demo-trace 테스트 때문에 구현 보고서의 1320보다 14개 많다 |
| `uv run ruff check src tests` | `All checks passed!` |
| `uv run mypy src` | `Success: no issues found in 90 source files` |
| `uv run jupjup eval validate` | 종료 0. seeds 200, queries 259, lexicon 139, ingest 80(dev 48/test 32) |
| `uv run jupjup eval validate-ingest` | 종료 0. 80건·플랫폼 분포·어려운 사례·test 봉인 통과. 알려진 장소 level 4건과 긴 글 반복 1건만 경고 |
| `git diff --check cb658cf^ cb658cf` | 출력 없음 |

### 1.2 검색 eval과 무회귀

| 명령 | 결과 |
|---|---|
| `uv run jupjup eval run --mode mock --split dev --baseline data/baselines/mock.json` | PASS, Recall@10 0.9620, nDCG@10 0.9795 |
| 같은 명령 `--split test` | PASS, Recall@10 0.9420, nDCG@10 0.9589 |
| `uv run jupjup eval run --mode recorded --split dev --baseline data/baselines/recorded.json` | PASS, Recall@10 0.9712, nDCG@10 0.9860 |
| 같은 명령 `--split test` | PASS, Recall@10 0.9720, nDCG@10 0.9801 |
| `git archive e925a17` 사본에서 위 4종 재실행 후 현재 결과와 비교 | 경로·생성시각·git sha·실측 latency만 제거한 결정적 리포트가 각각 **바이트 동일**(233,514 / 155,544 / 225,079 / 149,207바이트) |
| `git diff --exit-code cb658cf^ cb658cf -- src/jupjup/search src/jupjup/query data/recordings/embeddings data/baselines` | 종료 0. T25r 커밋은 금지 영역을 바꾸지 않음 |

### 1.3 mock 인제스트와 test 비모델 경로

| 확인 | 직접 결과 |
|---|---|
| `uv run jupjup eval ingest --mode mock --out <run1>` 및 `<run2>` | 둘 다 test PASS. JSON·Markdown `diff -rq` 출력 없음; SHA256도 파일별 동일 |
| 현재 mock 인제스트와 `git archive e925a17` 사본 결과 비교 | JSON·Markdown 모두 바이트 동일 |
| `IngestEvalHarness(IngestEvalConfig(mode="mock", split="test"), live_llm_factory=forbidden_factory).run()` | PASS, 실제 모델 팩토리 호출 0, 실행 뒤 `llama_cpp` 미로드 |
| 코드 경로 확인 | `src/jupjup/eval/ingest_harness.py:623-680`에서 mock은 local setup을 만들지 않고 `_GoldenMockAnalyzer`만 조립한다 |

### 1.4 recorded dev 재생 결정성·미스·품질

다음 명령을 후보별로 서로 다른 출력 디렉터리에 2회 실행했다.

`uv run jupjup eval ingest --mode recorded --profile <local-kanana-2b|local-qwen3-4b> --split dev --linkage recorded --out <dir>`

| 후보 | 종료 | 성공/전체 | schema first/final | linkage Recall@10 하락 | 미스 | 2회 결과 |
|---|---:|---:|---:|---:|---:|---|
| local-kanana-2b | 1(품질 미달) | 35/48 | 0.5208 / 0.7292 | 0.059408 | 0 | JSON SHA256 `3c49b83b…`, Markdown `298c448a…`; 2회 동일 |
| local-qwen3-4b | 1(품질 미달) | 37/48 | 0.4792 / 0.7708 | 0.042770 | 0 | JSON SHA256 `0878fc17…`, Markdown `0d445fed…`; 2회 동일 |

두 JSON의 `misses`는 빈 목록이고, runtime은 각각 정확한 `recording_model_id`, 프롬프트 4종 sha256, `frozen_config_sha256`(`03506b0f…`, `fd5a0a67…`), `judge=deterministic_only`, `linkage=recorded`를 담았다.

### 1.5 녹화·라벨 파일 무결성

| 검사 | 직접 결과 |
|---|---|
| LLM JSONL `wc -l`, `jq -s` | Kanana 682행, Qwen 558행, 총 1,240행. 각 파일 `(kind, model_id, request_hash)` 전부 고유, format v2 |
| LLM JSONL 모든 중첩 경로의 키 검사 | `system` / `user` / `prompt` 키 0건 |
| linkage JSONL `wc -l`, `jq -s` | Kanana 433행, Qwen 549행. 각 파일 `(model_id, kind, text_hash)` 전부 고유 |
| `uv run jupjup eval judge-sample --candidates local-qwen3-4b,local-kanana-2b --mode recorded --out <tmp>` | 종료 0, 문장 100·핵심 사실 60. 커밋된 `judge_labels.dev.jsonl`과 `cmp` 동일 |
| `load_label_rows` + 골든 split 대조 | 스키마 유효, 160행·고유 ID 160·빈 라벨/annotator 160·dev only. 후보별 80행씩 |

### 1.6 기본 설치·모델·네트워크 안전성

| 확인 | 직접 결과 |
|---|---|
| `uv run python -I`에서 `find_spec("llama_cpp")`, `import jupjup.cli`, `import jupjup.providers.llm_local` | `find_spec=None`, `llama_cpp` 미로드. `requests`·`httpx`·`urllib3`·`huggingface_hub`도 미로드 |
| `uv run jupjup models doctor --cache-dir /Users/minjun/orca/workspaces/dc2/models --json` | 종료 0. 기본 runtime `installed=false`; Kanana 2B/Qwen 4B/Kanana 8B 파일 present 및 sha256_ok. 8B recording id `…@fbe5103bfe68~bbdbf37b` |
| 소켓 차단·서비스 비녹화 targeted pytest | `test_no_network_on_load_and_generate`, 네트워크 코드 위치 검사, fetcher 차단, ingest pipeline, live 서비스 비녹화 합계 **13 passed** |
| 정적 코드 확인 | `llama_cpp` import는 `src/jupjup/providers/llm_local.py` 한 곳뿐이고, 로컬 LLM 파일에는 허브/HTTP/socket 코드가 없음 |

## 2. 피드백 (심각도 순, `파일:줄`)

높음·중간 문제는 발견하지 못했다.

### L1. 모델 변환 다운로드가 `models pull` 단일 통로를 우회했다 (낮음, 안전성 −1)

- **위치:** `specs/phase2_t25h_dev_recording_report.md:67-70`, `scripts/spikes/convert_quantize.py:34-53`, `scripts/spikes/run_all.sh:97-108`.
- 설계 AC-L8과 14.1은 다운로드를 `models pull`에만 두라고 하지만, Kanana 8B는 변환기의 `--remote` HTTP range 경로로 읽었다. 서비스·워커 경로의 네트워크 호출은 아니고, 고정 revision을 전후 확인했으며 최종 GGUF sha256도 설정과 일치해 실제 위험은 낮다. 다만 다운로드 통제점이 둘로 갈라진 것은 명시적 기준 위반이다.
- **권고:** safetensors 원격 변환을 `models pull`의 검증된 하위 동작으로 흡수하거나, 설계에서 변환 전용 예외를 승인하고 revision 확인을 `convert_quantize.py` 자체가 강제하도록 한다.

### L2. 커밋된 dev 보고서에 후보별 정확한 동결 해시가 없다 (낮음, 유지보수성 −1)

- **위치:** `specs/phase2_t25h_dev_recording_report.md:78-84,111-118` (특히 명령 표의 `<sha>` 자리 표시자), 기준 `specs/design_local_analyzer.md:735-743,935-940`.
- 직접 생성한 recorded 리포트에는 Kanana `03506b0f62899f00a162e1ea60a5f1ee344135940f16bae4271c40a7c14e9144`, Qwen `fd5a0a67493c23f8988fc78e616c240485d4ca83a47f541d23a14877135cd6e0`가 있지만, 커밋된 구현 보고서는 “생성·사용했다”고만 하고 값을 남기지 않았다. AC-L15와 8.2절은 `frozen_config_sha256`을 리포트에 남기도록 요구한다.
- **권고:** 후속 T25h 보고서에서 두 정확한 값을 프로필별로 기록하고, 가능하면 커밋된 dev 평가 config/요약에도 프롬프트 sha·recording model id와 함께 보존한다.

### 참고 (감점 없음)

- `specs/phase2_t25h_dev_recording_report.md:30-45,111-118`의 dev 품질·linkage 미달은 직접 재현됐고 정확히 공개됐다. 이번 범위에서 프롬프트 튜닝·기준 완화가 금지되어 있으므로 실패 수치 자체는 감점하지 않았다.
- 사람 라벨과 κ, 실제 후보 test, 기준선, live bench는 후속 범위다. 사람 검수 미완료는 사용자 지시대로 감점하지 않았다.
- 현재 통합 HEAD의 검색 explain 변경은 별도 demo-trace 커밋이다. T25r 단독 커밋은 검색·질의·기존 임베딩·기준선을 바꾸지 않았고, 결정적 검색 결과도 `e925a17`과 동일했다.

## 3. 채점 근거

| 항목 | 점수 | 근거 |
|---|---:|---|
| 정확성 | 40 / 40 | 이어 녹화가 기존 응답·토큰을 inner 호출 없이 재사용하고 파일을 바꾸지 않는 테스트가 있다. 두 후보의 recorded dev 재생은 미스 0·2회 바이트 동일이며 보고된 모든 품질/연결 수치, 라벨 행 수·스키마, 검색/인제스트 무회귀가 직접 결과와 일치한다 |
| 안전성 | 29 / 30 | 기본 설치 지연 import, 서비스·제공자 소켓 차단, live 서비스 비녹화, 녹화 원문 키 0, 모델 sha256 일치를 확인했다. 다만 8B 소스 읽기가 `models pull` 밖의 원격 변환 경로를 사용해 −1 |
| 유지보수성 | 29 / 30 | 형식 v2·키 계약을 유지했고 append 회귀 테스트, 고유 녹화 키, 버전 프롬프트, 모델/디코딩 id가 재현 가능하다. 커밋 보고서에 후보별 정확한 frozen hash가 빠져 −1 |
| **합계** | **98 / 100** | **PASS** |

## 4. 후속 조건

PASS이므로 재검수 조건은 없다. 다만 다음 동결·test 단계로 넘어가기 전에 L1의 다운로드 경로를 설계와 일치시키거나 예외를 공식화하고, L2의 두 동결 해시를 후속 T25h 보고서에 정확히 고정해야 한다. 후보 품질·linkage 미달은 기준을 낮추지 말고 dev 범위에서 원인 분석과 후보/프롬프트 결정을 거친 뒤, 동결된 후보만 test 1회 절차로 진행해야 한다.

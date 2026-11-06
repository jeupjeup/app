# Phase 4 최종 검수: T25 T25l 소규모 정리, Loop 1/3

- **점수:** 100 / 100
- **상태:** PASS
- **항목별:** 정확성 40 / 40, 안전성 30 / 30, 유지보수성 30 / 30
- **루프백 대상:** 없음 (PASS)
- **검수 대상:** `40657d8 fix: close remaining T25 low-priority review items` (PM 병합 `79f71cf`)
- **검수자:** Claude-Reviewer 역할 대행 (Codex 실행). 구현 코드는 고치지 않았고 이 리뷰 파일만 추가했다.
- **범위 밖:** T25h 본 튜닝, 실제 모델을 쓰는 test split 재평가, `data/recordings` 수정. 사람 검수 미완료 자체는 감점하지 않았다.

## 0. 판정 요약

T25l이 대상으로 삼은 낮음 항목의 수정과 기존 수정분을 구현 보고서와 독립적으로 다시 확인했다. 변경 항목의 재현 테스트, 전체 기본 게이트, 검색 eval 4종, 인제스트 골든 검증, mock 인제스트 v1/v2의 dev/test/all 결정성이 모두 통과했다. mock 인제스트 JSON·Markdown 6조합은 각각 같은 경로에 두 번 쓴 결과가 바이트 동일했고, 구현 직전 부모 `40657d8^`를 별도 임시 트리에 풀어 실행한 결과와도 6조합 전부 바이트 동일했다. 검색 `explain=false` 응답은 trace 작업 전 기준 해시와 mock/recorded 각 259건, 합계 518건이 일치했다.

기본 환경에는 `llama-cpp-python`이 설치되지 않았고 `jupjup.providers.llm_local`을 import해도 `llama_cpp`가 로드되지 않았다. 같은 프로세스에서 mock test, recorded test, mock ingest test를 실행한 뒤에도 `llama_cpp`, `sentence_transformers`, `torch`가 모두 미로딩이었다. 기본 pytest의 실제 모델 테스트는 `local_llm` 마커로 제외되어 5건이 deselect됐고 skip은 없었다. 로컬 분석기 load/generate의 소켓 차단 테스트와 서비스 녹화 금지 테스트가 통과했으며, 별도 mock/recorded 검색·데모 서비스 탐침에서도 네트워크 시도는 0회였다.

녹화→재생은 합성 live 녹화 뒤 recorded를 두 번 재생해 JSON·Markdown 파일을 직접 `read_bytes()`로 비교하는 테스트가 통과했다. test split은 동결 검사 전에 모델을 조립하지 않는 경로가 유지됐다. 데모 페이지는 서버의 실제 `Settings.mode`인 `mock`, `recorded`, `live`를 각각 표시했고, 비활성 cross reranker 상태와 trace 중첩 값도 SearchService explain과 일치했다.

고·중·낮음 심각도의 새 결함을 찾지 못했다. 보류된 골든 데이터 사람 검수·재봉인, 원격 safetensors 변환 경로, 실제 dev 녹화 관찰은 명시된 범위 밖이며 현재 결과를 감점할 근거가 아니다. known issue의 recorded test Recall@10 0.9720은 여전히 회귀 하한과 같아 여유가 없지만 이번 변경 전후 값이 같고 이번 범위의 결함은 아니다.

## 1. 직접 실행한 명령과 결과

### 1.1 기본 게이트와 평가

| 명령 | 직접 결과 |
|---|---|
| `uv run pytest` | 종료 0, **1402 passed, 5 deselected, 3 warnings**. 실패·error·skip 0. 실제 모델·embed·rerank 마커는 기본 설정에서 실행되지 않았다. |
| `uv run ruff check src tests` | `All checks passed!` |
| `uv run mypy src` | `Success: no issues found in 103 source files` |
| `uv run jupjup eval validate` | 종료 0. seeds 200, queries 259(dev 158/test 101), lexicon 139, ingest 80 검증 통과 |
| `uv run jupjup eval validate-ingest` | 종료 0. sources/annotations 80, 플랫폼 분포·어려운 사례·템플릿·test 봉인 통과. 알려진 경고 5줄(location level 4, 긴 글 반복 1) |
| `uv run ruff check scripts` / `bash -n scripts/spikes/run_all.sh` | 둘 다 종료 0 |
| `uv run jupjup eval run --mode mock --split dev --baseline data/baselines/mock.json` | PASS. Recall@10 0.9620, MRR@10 0.9958, nDCG@10 0.9795 |
| 같은 mock 명령 `--split test` | PASS. Recall@10 0.9420, MRR@10 0.9867, nDCG@10 0.9589 |
| `uv run jupjup eval run --mode recorded --split dev --baseline data/baselines/recorded.json` | PASS. Recall@10 0.9712, MRR@10 1.0000, nDCG@10 0.9860 |
| 같은 recorded 명령 `--split test` | PASS. Recall@10 0.9720, MRR@10 0.9911, nDCG@10 0.9801 |
| `git diff --check` / `git diff -- data/baselines data/recordings` | 출력 없음 |

`uv run pytest`의 경고 3건은 Starlette TestClient deprecation 1건과 의도적으로 unavailable 분석기를 만드는 테스트의 RuntimeWarning 2건이다. 검수 실패나 숨은 skip은 아니다.

### 1.2 항목별 재현

보고서가 지정한 11개 파일을 묶어 다시 실행했다.

```text
uv run pytest \
  tests/unit/test_ingest_judge.py \
  tests/unit/test_ingest_chunking.py \
  tests/unit/test_json_grammar.py \
  tests/unit/test_analyzer_profiles.py \
  tests/unit/test_ingest_compare.py \
  tests/unit/test_ingest_metrics.py \
  tests/unit/test_judge_t25g.py \
  tests/integration/test_ingest_record_replay.py \
  tests/integration/test_judge_record_replay.py \
  tests/integration/test_demo.py \
  tests/integration/test_demo_trace.py
```

결과는 **318 passed, 1 warning**이었다. 수정 항목의 핵심 재현은 다음과 같다.

| 항목 | 직접 확인 | 판정 |
|---|---|---|
| T25-prep L-a/L-c | `no.`는 숫자가 뒤따를 때, `st.`는 대문자 고유명사가 뒤따를 때만 내부 마침표로 남고 실제 문장 끝은 분리됨. docstring과 회귀 테스트 일치 (`test_l_a_ambiguous_abbreviations...`) | 충족 |
| T25-prep L-b | 논문 초록과 본문 시작의 종결부호 차이, 공백, 한 줄바꿈, 텍스트 끝 12개 사례 통과 (`test_paper_abstract_is_not_duplicated...`) | 충족 |
| T25-prep L-d | 빈 주입 집합은 `_overall`에서 `None`, 게이트에서 실패로 처리 | 충족 |
| T25b L1~L4 | scripts ruff·`run_all.sh` 구문 통과. 고정 revision/sha 검증 경로와 보고서 정정은 코드·문서에서 확인 | 충족 |
| T25c L1/L3/L5 | test 재봉인 보호, forbidden 자기모순·한 글자 금지어, level·긴 글 반복 검사 테스트 통과. 보류 데이터는 실제 파일을 수정하지 않음 | 충족/보류 준수 |
| T25d L1~L4 | 렌더 실패 비재시도, 잠금 대기 timeout 제외, required property 제거 탐지, downloader 예외 `download_failed` 정규화·staging 정리 테스트 통과 | 충족 |
| T25e L1~L3 | 잘린 재요청 프롬프트 재전송, 분석기 조립 실패 시 dev API 기동, doctor/worker 프로필 규칙 일치 테스트 통과 | 충족 |
| T25f L1~L3 | recorded 연결 미측정 표시, frozen hash 구성, 공개 하네스 helper/경로·오류 처리 통합 테스트 통과 | 충족 |
| T25g L1~L4 | 분석기·판정기 실행량 분리 표시, 준-사람 보정 표시, key-fact miss에 실제 `source_id`, 공용 `golden_source_text` 사용 테스트 통과 | 충족 |
| T25p L1/L2 | 실제 모델 스모크의 category/save-intent/주입 marker 단언이 `local_llm` 테스트에 존재함. 기본 suite에서는 의도대로 deselect. validate-ingest 경고 5줄 재현 | 충족 |
| T25r L1/L2 | 서비스/워커에서 모델 다운로드 경로 없음, frozen hash 문서 값 확인. 원격 변환 통합은 보류 범위 유지 | 충족/보류 준수 |
| T26a L1~L6 | 절대값 표, 60초 예산 재계산, linkage/bench 비교 가능성, `.json` 출력 경계, paired items, 공용 gate·seed 전달 테스트 통과 | 충족 |
| demo-trace L1/L2 | cross 상태 `skipped:disabled`; filter/retrieval/fusion/rerank/component/log의 중첩 값이 service explain과 직접 일치 | 충족 |
| 실행 모드 표시 | `mock`, `recorded`, `live` 각각 `로컬 검색 데모 · <mode>` 출력, 고정 `Mock` 문구 없음 | 충족 |

### 1.3 결정성, 녹화 재생, 실제 모델·네트워크 격리

| 확인 | 직접 결과 |
|---|---|
| mock 인제스트 자체 결정성 | `eval ingest --mode mock --golden v1\|v2 --split dev\|test\|all` 6조합을 각각 같은 출력 디렉터리에 두 번 실행. JSON·Markdown 모두 `cmp` 종료 0, 총 12쌍 바이트 동일 |
| mock 인제스트 구현 전후 무회귀 | `git archive 40657d8^`로 만든 임시 트리에서 같은 6조합 실행. 현재 결과와 JSON·Markdown 12파일 모두 `diff -q` 출력 없음 |
| 검색 결과 바이트 무회귀 | `test_explain_false_results_byte_identical_to_baseline`이 mock·recorded 각각 259질의의 결정적 응답 해시를 trace 작업 전 기준과 비교, 518/518 일치 |
| 녹화→재생 리포트 | `test_recorded_replay_reproduces_recording_run_byte_for_byte` 통과. 합성 live 녹화 후 recorded 2회 JSON·Markdown `read_bytes()` 동일, 녹화에 프롬프트 원문 없음 |
| test 실제 모델 미실행 | 한 프로세스에서 검색 mock test, 검색 recorded test, 인제스트 mock test 실행 전후 `llama_cpp`, `sentence_transformers`, `torch` 모두 `sys.modules`에 없음; 세 gate 모두 PASS |
| 기본 설치 | `uv pip show llama-cpp-python`은 package not found, `find_spec("llama_cpp") is None`, `import jupjup.providers.llm_local` 뒤 `llama_cpp_loaded=False` |
| 로컬 분석기 무네트워크 | 소켓의 `connect`, `connect_ex`, `create_connection`, `getaddrinfo`를 막고 load/count/generate 실행하는 테스트 통과. 모델 허브 코드는 `models pull`의 `local_models.py`에만 존재함을 AST/코드 검사로 확인 |
| 서비스 경로 | live 서비스가 `RecordingLLM`을 만들거나 파일을 쓰지 않는 테스트 통과. 별도 소켓 차단 탐침에서 mock·recorded 검색과 FastAPI 데모가 각각 10건을 반환했고 `network_attempts=[]` |
| 데이터·제한 경로 | `data/baselines`, `data/recordings`, `src/jupjup/search`, `src/jupjup/query`, `api`, `storage`, `domain`, `ingest/service.py`, `jobs.py`, `worker.py`에 T25l diff 없음 |

임시 비교 트리와 생성 파일은 시스템 임시 디렉터리만 사용했다. test split의 실제 로컬 모델은 범위와 봉인 원칙에 따라 실행하지 않았고, 실행되지 않았음을 모듈 로딩 상태와 마커 제외로 확인했다.

## 2. 피드백 (심각도 순, `파일:줄`)

고·중·낮음 심각도의 지적 사항 없음.

검수에서 확인한 핵심 구현 위치는 다음과 같다.

- `src/jupjup/eval/judge.py:126-181`: 결정적 문장 분리와 문맥 의존 `no.`/`st.` 처리.
- `src/jupjup/ingest/chunking.py:190-211`: 종결부호·줄바꿈을 대칭 처리하는 초록/본문 접두 경계.
- `src/jupjup/providers/json_grammar.py:306-317`: 정본 required 속성이 decoding properties에서 빠지는 경우 탐지.
- `src/jupjup/providers/local_models.py:55-99`: 다운로드 예외 정규화와 `finally` staging 정리.
- `src/jupjup/eval/ingest_harness.py:107-118,613-633,879-891`: 공용 골든 원문 추출, 분석기/판정기 실행량 추정, 공개 조립 helper.
- `src/jupjup/eval/judge_tools.py:60-75,165-190`: 보정 실행량 추정과 key-fact cache miss의 실제 source ID 기록.
- `src/jupjup/cli.py:1018-1061`: compare CLI 입력·출력 오류 경계와 `.json` 제한.
- `src/jupjup/demo/app.py:517-596,792-795`: gate signal profile, cross 상태 정규화, 실제 서버 모드 표시.

## 3. 채점 근거

| 항목 | 점수 | 근거 |
|---|---:|---|
| 정확성 | 40 / 40 | T25l 수정 항목과 기수정 회귀를 항목별·전체 suite로 재현했다. 검색 eval 4종 PASS, mock 인제스트 6조합 자체·부모 대비 바이트 동일, 검색 응답 518/518 기준 해시 일치, 데모 모드·trace 값 일치. 근거 있는 감점 사항 없음 |
| 안전성 | 30 / 30 | 기본 설치 llama.cpp 미설치·미import, test 경로 실모델 미실행, 동결 전 모델 조립 차단, 서비스 녹화 금지, 프롬프트 원문 미녹화, 모델 load/generate와 mock/recorded 서비스의 네트워크 시도 0, 다운로드 sha/staging 오류 처리 확인. 근거 있는 감점 사항 없음 |
| 유지보수성 | 30 / 30 | ruff/mypy 통과, 공용 helper로 중복 제거, source ID·경로·오류 접두 일관화, 중첩 trace 출처를 직접 봉인하는 테스트, 공개 하네스 API와 seed 전달을 확인했다. 근거 있는 감점 사항 없음 |
| **합계** | **100 / 100** | **PASS** |

## 4. 다음 단계

PASS이므로 재검수 조건은 없다. 명시적으로 보류된 골든 데이터 사람 교차 검수·test 재봉인, T25r 원격 변환 경로 결정, T25e의 실제 dev 녹화 관찰은 별도 승인 범위에서 진행해야 한다. recorded test Recall@10의 회귀 여유 0은 `specs/known_issues.md`의 제품 판정 잔여로 계속 추적하되, T25l을 되돌릴 근거는 아니다.

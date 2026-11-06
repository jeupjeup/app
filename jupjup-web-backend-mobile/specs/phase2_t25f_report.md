# Phase 2 T25f 보고서 — 분석기 녹화·재생과 인제스트 하네스 확장

- 작성: Codex-Primary (이번 실행은 Claude가 같은 지침으로 수행)
- 기준일: 2026-11-02
- 기준 코드: PM `b6820f2` (T25e 검수 loop 1 PASS 뒤)
- 설계: `specs/design_local_analyzer.md` 7절, 8.2절, 10.1절 T25f, 11절 인수 기준, 14절 핵심 사항
- 실제 모델 녹화는 하지 않았다 (T25h 범위). 녹화 파일은 테스트 임시 경로에만 만들었고 저장소에 커밋한 녹화는 없다.

## 1. 구현 범위

| 항목 | 위치 | 내용 |
|---|---|---|
| recorded/live 하네스 | `eval/ingest_harness.py` | `IngestEvalHarness.run()`이 mock(기존 골든 고정 응답, 변경 없음)과 recorded/live(`LLMContentAnalyzer` + `RecordedLLM`/로컬 LLM)를 같은 항목 루프로 돈다. 프로필 `chunk` 값이 I4 청킹 설정으로 들어간다. recorded/live 품질 지표(태그·엔티티·장소 F1, 카테고리, 저장 의도, 핵심 사실, 비충실)를 계산하고 3.5.4절 "기본 분석기" 열로 게이트한다 |
| 녹화·재생 조립 | `eval/ingest_runtime.py` (신규) | `prepare_local_setup`(프로필·동결 해시, LLM 미생성) → `check_frozen_config` → `build_eval_analyzer`(recorded: `RecordedLLM`, live: 로컬 LLM, `record=True`일 때만 `RecordingLLM`). live LLM의 `model_id`가 `recording_model_id`와 다르면 거부. live는 실행 전에 `warm_up`(모델 로드·sha256 검증) |
| 미스 목록 | `CapturingAnalyzer`, `MissRecord` | `LLMCacheMiss`를 잡아 source_id·kind·schema_name·max_tokens·request_hash·prompt_hash만 남기고 다시 던진다. 워커가 그 건을 `failed`(`LLM_CACHE_MISS`)로 끝내고 하네스가 항목으로 기록한다. 리포트 `misses`와 Markdown "녹화 미스" 절, CLI 종료 2 |
| 동결 해시 | `frozen_config_sha256`, `jupjup analyze freeze` | 프로필 블록 전체(디코딩·청킹·타임아웃 포함) + 프롬프트 4종 sha256 + 디코딩 정책 해시 + 분석·청크 모델 sha256(분할 파일 포함)의 정규 JSON sha256. recorded/live의 `test`·`all` split은 해시가 없으면 거부, 있으면 어느 split이든 현재 값과 같아야 한다. **검사는 LLM 생성보다 먼저** 한다 |
| 시간 추정·확인 플래그 | `RunEstimate`, `--confirm-run` (`--confirm-cost` 별칭) | 건수 × 모델 `measured_p50_s`(T25b 실측) + 비용 0 USD. live 평가·`analyze record`·`bench analyze`는 플래그 없이 추정만 출력하고 종료 2. 하네스 자체도 `confirm_cost=False` live를 거부한다 (이중 방어) |
| 녹화 명령 | `jupjup analyze record` | `--profile --split dev\|test\|all --target ingest\|seeds [--append] [--confirm-run] [--frozen-config] [--recordings-dir]`. 녹화 파일이 이미 있으면 `--append` 없이는 거부. ingest는 리포트(`eval_ingest_live_<split>`)도 쓴다. seeds는 검색 시드 200건을 같은 분석 녹화 파일에 녹화하고 mock 연결 지표를 출력한다 |
| 연결 지표 | `eval/ingest_linkage.py` (신규), `eval ingest --linkage none\|mock\|recorded` | 사람 분석 인덱스(`load_seed_file`)와 분석기 인덱스(`load_seed_file_for_analysis`)에 같은 검색 골든 질의를 돌려 Recall@10·nDCG@10과 하락(사람 − 분석기)을 낸다. mock = `HashingEmbedder`, recorded = 기존 검색 녹화(질의) + 연결 녹화(문서·청크)를 이은 임시본. recorded일 때만 하락 ≤ 0.03을 게이트에 넣는다 |
| 연결 녹화 | `jupjup analyze record-linkage` | recorded 시드 분석 출력으로 색인하며 live bge-m3(`RecordingEmbedder`)로 `data/recordings/linkage/embeddings.bge-m3.<profile>.jsonl`에 녹화. 임시 파일 → 성공 시 교체, `--force` 없이는 기존 파일 거부, 동결 해시 필수 |
| 지연 벤치 | `jupjup bench analyze`, `eval/ingest_bench.py` (신규) | live, **녹화 안 함**. 건당 벽시계 시간을 single·map_reduce로 나눠 p50/p95, 예산(60초/300초) 판정, 피크 RSS, 출력 토큰/초. 예산 초과면 종료 1 |
| L-3 항목화 | `_source_text_or_empty` | 추출이 실패하는 fixture가 run 전체를 멈추지 않는다. 파이프라인이 extract 단계에서 실패시키고 하네스는 `INGEST_EXTRACT_FAILED` 항목으로 남긴다 (`estimate_cost`도 같음) |
| 리포트 `runtime` (AC-L15) | `AnalyzerRuntime` | profile, model, `recording_model_id`, 녹화 파일(저장소 상대 경로), 녹화 여부, 프롬프트 sha256 4종, `frozen_config_sha256`과 확인 여부, 청킹 설정, llama-cpp-python 버전·Metal 여부(live), 판정기 `deterministic_only` |
| 모델 실측 p50 | `LocalModelSpec.measured_p50_s`, `config/analyzer_profiles.yaml` | T25b 4.2·4.4절 값(Qwen3-4B·Kanana-2.1B는 제어 문자 패치 문법 재측정값 46.7·16.6초) |
| T25e 검수 L1 | `ingest/analyzer.py` `_run` | 재요청 응답이 `max_tokens`로 잘리면 분석 프롬프트가 아니라 **그 재요청**을 2배 토큰으로 다시 보낸다 (맵 단계와 같은 규칙). 설계 5.4절 문구 수정 |
| T25e 검수 L2 | `api/app.py` `_submit_only_ingest_service` | 분석기 조립이 실패해도(녹화 없음, required 미설치, 프로필 불일치) dev API는 경고 1회 뒤 `UnavailableAnalyzer` 자리 표시자로 뜬다. API는 잡 등록·조회만 하므로 mock 대체는 없다 |
| T25e 검수 L3 | `providers/local_models.py` `_active_usable` | `engine=local` + mock 프로필이면 doctor도 "사용 불가"와 `JUPJUP_ANALYZER__PROFILE` 안내 (worker run과 같은 판정) |
| 문서 | `data/recordings/README.md` | `llm/`, `linkage/` 녹화 형식과 T25h 실행 순서 |

## 2. 설계 대비 차이 (이유)

1. **mock 리포트 바이트 보존 방식.** 새 설정 필드(`profiles_path`, `recordings_dir`, `analyzer_cache_dir`, `frozen_config`, `record`, `linkage` 등)는 pydantic `exclude=True`로 직렬화에서 빼고, 리포트 `runtime`·`misses`는 `None`이면 JSON에서 지운다. recorded/live는 이 값들을 `runtime` 블록에 남긴다. 원칙 4(mock 한 바이트도 불변)를 지키려는 선택이다.
2. **"같은 리포트(바이트 동일)"의 범위.** live 녹화 실행과 recorded 재생 리포트는 `config.mode`, `config.confirm_cost`, `runtime.recording` 세 값이 원래 다르다. 테스트는 이 세 값만 맞춘 뒤 JSON 문자열 전체를 비교하고, recorded 두 번 실행은 **쓴 파일 바이트**로 비교한다. 지연은 녹화된 `latency_ms`를 재생하므로 같다.
3. **품질 지표 평균의 분모.** recorded/live overall 품질 지표는 분석 출력이 있는 건의 평균이다. 출력이 없는 건(실패·미스)은 `schema_final_pass_rate`(= 1.00 기준)가 따로 잡는다. 3.5.2절에 분모 규정이 없어서 이렇게 정했다.
4. **판정기 연결 전 게이트.** 비충실 비율은 결정적 1차 검사 값, 핵심 사실 재현율은 기존 부분 문자열 매처 그대로다 (판정기·결정적 매처는 T25g). 리포트에 "판정기 미보정"을 적는다.
5. **연결 지표 질의 집합.** 검색 골든 `queries.jsonl`에서 정답이 있고 필터 전용이 아닌 질의 전체(`--linkage` 기본 split `all`)를 쓴다. 검색 eval의 overall은 `GATE_REVIEW_STATUS` 질의만 쓰므로 사람 분석 쪽 값이 검색 eval 리포트 수치와 정확히 같지는 않다. 두 갈래가 같은 질의를 쓰므로 하락 비교는 공정하다.
6. **mock 모드 `--linkage mock`.** 골든 mock 분석기는 시드를 분석할 수 없어서 제품 mock 분석기(`ExtractiveMockAnalyzer`)를 쓴다. 배선 확인용이며 게이트에 넣지 않는다. 기본값 `none`이라 mock 리포트는 바뀌지 않는다.
7. **시드 분석 녹화 명령.** 설계 7.4절은 시드 분석 녹화가 분석 녹화 파일에 함께 들어간다고만 적었다. `analyze record --target seeds`로 두고, 동결 해시를 요구한다 (연결 지표는 동결 뒤 한 번만).
8. **`analyze freeze` 추가.** 동결 해시를 사람이 계산할 방법이 필요해서 더했다. 거부 메시지는 해시 값을 직접 보여 주지 않고 이 명령을 안내한다.
9. **`eval ingest --mode live`는 녹화한다** (설계 6.9절). `--append` 검사는 `analyze record`에만 있다. `RecordingLLM._seen`이 같은 요청을 다시 쓰지 않으므로 이어 쓰기는 안전하다.
10. **재시도 루프 없음.** 하네스는 잡을 `run_job` 한 번만 돈다. live에서 `LLMTimeoutError`처럼 재시도 가능한 오류는 그 항목이 `retry_wait`로 남는다 (성공 아님으로 집계). T24 mock 하네스와 같은 동작이다.
11. **`record-linkage`의 bge-m3.** 기존 `BgeM3Embedder`를 그대로 쓴다. 캐시에 가중치가 없으면 기존 `embedding record`처럼 허브에서 받을 수 있다. 평가 명령이고 서비스·워커 경로가 아니다. 분석 모델 다운로드(`models pull`)와는 별개다.

## 3. 테스트

신규 `tests/integration/test_ingest_record_replay.py` (21개, 실제 모델 없음):

| 테스트 | 확인 내용 (10.1절 T25f 완료 조건) |
|---|---|
| `test_recorded_replay_reproduces_recording_run_byte_for_byte` | MockLLM 확장(`GoldenEchoLLM`, 일부 요청은 일부러 잘린 JSON)을 `RecordingLLM`으로 감싼 live 녹화(dev 48건: 성공 42, 실패 6, 재요청 13) → `RecordedLLM` 재생 리포트 동일, 재생 2회 파일 바이트 동일, 녹화 파일에 시스템 지시문·블록 태그·메타데이터 없음, runtime 경로 상대 |
| `test_recorded_report_has_quality_metrics_runtime_and_miss_sections` | recorded 품질 지표 계산, 3.5.4절 기본 분석기 게이트, Markdown 실행 설정·녹화 미스 절 |
| `test_recording_skips_requests_already_recorded` | 같은 요청은 덧붙이지 않는다 (파일 바이트 불변) |
| `test_recorded_miss_fails_the_item_and_cli_exits_two` | 녹화 절반 삭제 → 미스 건 = `LLM_CACHE_MISS` 실패 건, 미스 목록, CLI 종료 2와 미스 출력, 리포트 `misses` |
| `test_recorded_without_recording_file_is_a_config_error` | 녹화 파일 없음 → `LLMProviderError` |
| `test_test_split_is_refused_without_frozen_hash_before_any_model_call` (test, all) | recorded·live 모두 해시 없음/틀림 거부, **LLM 생성 0회**, 녹화 디렉터리 없음 |
| `test_test_split_runs_with_matching_frozen_hash` | 맞는 해시면 test 32건 녹화·재생 |
| `test_frozen_hash_tracks_prompts_profile_and_model` | 프롬프트 파일 1바이트, 프로필 값, 모델이 바뀌면 해시가 바뀐다. mock 프로필 거부 |
| `test_cli_record_test_split_requires_frozen_hash` | CLI `analyze record --split test`, `--target seeds` 거부, `analyze freeze --json` 값 = 하네스 값 |
| `test_live_never_runs_without_confirmation` | 하네스 거부(LLM 생성 0회), CLI 3종(`eval ingest --mode live`, `analyze record`, `bench analyze`) 종료 2와 "예상 소요 시간: 약 13.3분 (48건 × p50 16.6초)", `$0.00`, 녹화 파일 없음 |
| `test_record_refuses_existing_file_without_append` | 기존 녹화 + `--append` 없음 → 종료 2 |
| `test_estimate_uses_measured_p50_and_unknown_without_it` | 추정식, 실측 없으면 "알 수 없음" |
| `test_live_rejects_client_whose_model_id_differs_from_recording_key` | 녹화 키 불일치 거부, 파일 없음 |
| `test_live_service_path_never_wraps_or_writes_recordings` | live 서비스 조립(`build_content_analyzer`, `build_ingest_service`)이 `RecordingLLM`을 만들지 않고(만들면 실패하도록 패치), 잡 실행 뒤 녹화 디렉터리가 없다 (AC-L9) |
| `test_bench_run_does_not_record_and_splits_latency` | 벤치는 녹화하지 않고 single/map_reduce로 나눈다 |
| `test_mock_linkage_is_deterministic` | mock 연결 지표 두 번 같은 값, 시드 200건 성공, 하락 = 사람 − 분석기 |
| `test_recorded_linkage_records_then_replays_without_misses` | 가짜 bge-m3(1024차원)로 `record_linkage` → recorded 연결 지표 미스 0, 기존 파일 `--force` 없이 거부 |
| `test_harness_linkage_option_fills_overall_and_gates_only_recorded` | `--linkage`가 overall `search_recall@10`을 채우고 mock 임베딩 값은 게이트에 넣지 않음 |
| `test_empty_fixture_becomes_a_failed_item_instead_of_stopping_the_run` | L-3: 빈 HTML fixture → `INGEST_EXTRACT_FAILED` 항목, run 완료 |
| `test_capturing_analyzer_records_wall_time_and_mode` | 수집기 입력 모드·벽시계 시간 |

추가·수정한 기존 테스트:

- `tests/unit/test_llm_analyzer.py::test_truncated_repair_response_resends_the_repair_prompt` (L1)
- `tests/unit/test_analyzer_profiles.py::test_doctor_rejects_local_engine_with_mock_profile_like_the_worker` (L3)
- `tests/integration/test_local_analyzer_assembly.py::test_dev_api_starts_when_analyzer_assembly_fails` (L2, 3가지 실패 원인)
- `tests/integration/test_cli.py`: `test_eval_ingest_rejects_unimplemented_recorded_mode` → `test_eval_ingest_recorded_mode_requires_local_profile` (recorded가 구현돼 "T25 범위" 메시지가 없어졌다)

## 4. 직접 실행한 명령과 결과 (기본 설치, extra 없음)

| 명령 | 결과 |
|---|---|
| `uv run pytest` | **1164 passed, 4 deselected** (embed·rerank·local_llm 마커 제외), skip 0. 79초 |
| `uv run ruff check src tests` | All checks passed |
| `uv run mypy src` | Success: no issues found in 86 source files |
| 소켓 차단 플러그인으로 `test_ingest_record_replay.py` + `test_ingest_regression.py` | 29 passed, **네트워크 시도 0건** |
| `python -c "import jupjup.cli, jupjup.eval.ingest_harness, …ingest_runtime, …ingest_linkage, …ingest_bench"` | `llama_cpp imported: False` |
| `uv run jupjup eval validate` | 통과 (seeds 200, queries 259, ingest 80) |
| `uv run jupjup eval run --mode mock\|recorded --split dev\|test` | 4종 모두 종료 0. 변경 전 리포트와 JSON 비교 시 `created_at`(생성 시각)만 다르고 지표 전부 동일 |
| `uv run jupjup eval ingest --mode mock --split dev\|test\|all` (변경 전·후, 변경 후 2회) | 모두 PASS 종료 0. JSON·Markdown 6개 파일이 **변경 전과 바이트 동일**, 2회 실행 바이트 동일 |
| `git diff -- src/jupjup/search src/jupjup/query data/recordings/*.jsonl data/baselines` | diff 없음 |
| `eval ingest --mode recorded --profile local-kanana-2b --split dev` | 종료 2 "LLM 녹화본 파일이 없습니다" (아직 녹화 없음, 정상) |
| `eval ingest --mode recorded --profile local-kanana-2b --split test` | 종료 2 "test split은 설정 동결 뒤에만…" |
| `eval ingest --mode live --profile local-qwen3-4b --split dev` | 종료 2 "예상 소요 시간: 약 37.4분 (48건 × p50 46.7초), 예상 비용: $0.00" |
| `analyze freeze --profile local-kanana-2b` | `frozen_config_sha256 817b6a80e7ca…`, `recording_model_id kanana-1.5-2.1b-instruct-q4km@5baf76ee0939~bbdbf37b` |
| `analyze record --profile local-kanana-2b --split dev --confirm-run --recordings-dir <scratch>` | 종료 2 "llama-cpp-python이 설치돼 있지 않습니다" (기본 설치), 녹화 파일 생기지 않음 |
| `bench analyze --profile local-kanana-2b` | 종료 2, 추정만 출력 |

## 5. 남은 문제

1. **실제 모델로 녹화하지 않았다.** `analyze-local` extra와 실제 GGUF로 `analyze record`를 돌리는 것은 T25h다. T25e 검수 R1(실제 Kanana 스모크 2건 실패: 주입 추종, 재요청이 같은 출력, 리듀스 근거 복사)은 그대로라 지금 녹화하면 dev 대부분이 실패 행일 수 있다. 프롬프트 v2 조정 뒤 녹화를 권한다.
2. **골든셋이 아직 v1(템플릿 문장)이다.** recorded 품질 수치는 T25c 골든 v2 전에는 모델 품질 근거가 아니다. 골든 `test.sha256` 봉인 검사(8.1절)도 T25c 산출물이 없어 구현하지 않았다. 지금 test 보호는 설정 동결 해시만이다.
3. **예상 시간은 single p50 기준**이라 map_reduce(긴 글) 건이 많으면 실제보다 짧게 나온다. T25h live 벤치 결과로 `measured_p50_s`를 갱신하는 것이 좋다.
4. **판정기 미연결.** 비충실 비율은 결정적 1차 검사, 핵심 사실 재현율은 부분 문자열 일치다 (T25g).
5. T25e 보고서 6절 3번의 잠금 대기 시간 잡 로그 연결과 `analysis_runs.chunk_model`은 하지 않았다 (분석기 Protocol·스토리지 변경이 필요해 범위 밖으로 남김).
6. 하네스는 재시도 가능한 오류의 잡을 다시 돌리지 않는다 (2절 10번). live 녹화 중 타임아웃이 나면 그 건은 `retry_wait`로 남고, `--append`로 다시 녹화해야 한다.
7. `ruff format --check src`는 이번 작업 전부터 `cli.py`의 `_print_doctor` 등 몇 파일에서 차이를 낸다. 범위 밖 파일을 바꾸지 않으려고 그대로 두었다 (완료 조건은 `ruff check`).

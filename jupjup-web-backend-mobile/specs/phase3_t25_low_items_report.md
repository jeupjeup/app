# Phase 3 보고서: T25 낮음 항목 정리

- 기준일: 2026-11-03
- 범위: `specs/phase2_t25h_preflight_report.md` 5.1절, `specs/phase4_review_t25*_loop1.md`,
  `specs/phase4_review_t26a_loop1.md`, `specs/phase4_review_demo-trace_loop1.md`의 열린 낮음 항목
- 추가 범위: 검색 데모 실행 모드 표시를 서버 설정(`mock`/`recorded`/`live`)과 일치시킴
- 불변 조건: 검색 기능·검색 지표·인제스트 mock 결과·기존 녹화/기준선 파일을 바꾸지 않음
- 제외 경로: `src/jupjup/api`, `storage`, `domain`, `ingest/service.py`, `ingest/jobs.py`,
  `ingest/worker.py`는 수정하지 않음

## 1. 결과 요약

열린 낮음 항목 중 코드·테스트·문서만으로 안전하게 닫을 수 있는 항목은 모두 처리했다. 이미 후속 트랙에서 고쳐진 항목은
현재 회귀 테스트와 직접 명령으로 다시 확인했다. 아래 항목만 보류했다.

1. T25c L2: 골든 정체성을 기준선 스키마와 리포트 파일명에 넣으면 기존 기준선/mock 리포트 바이트와 파일명이 바뀐다.
   명시적인 기준선 버전 마이그레이션 작업으로 분리한다.
2. T25c L3의 남은 장소 `level`, L4의 `기타` 허용 의도, L5의 `ing2_0066` 원문 재작성: 사람 교차 검수와
   test 재봉인 또는 mock 결과 변경이 필요하다.
3. T25r L1: 원격 safetensors 변환을 `models pull` 아래로 넣는 것은 모델 배포·다운로드 아키텍처 변경이다.
   승인된 저장 위치/변환 전용 예외/`models pull` 확장 중 하나를 먼저 결정해야 한다.
4. T25e 참고 3의 `・` 빈도: 실제 T25h dev 녹화 결과가 있어야 판단할 수 있어 데이터 관찰 항목으로 남긴다.

## 2. 항목별 조치표

상태의 의미는 다음과 같다.

- **수정**: 이번 작업에서 재현 테스트를 먼저 추가하거나 강화한 뒤 구현/문서를 고쳤다.
- **기수정**: 앞선 T25d/T25f/preflight 작업에서 이미 고쳐져 이번 작업에서는 회귀를 확인했다.
- **보류**: 불변 조건, 사람 검수 또는 별도 아키텍처 결정 때문에 이번 작업에서 바꾸지 않았다.

### 2.1 T25-prep, T25b, T25c

| 출처 | 상태 | 조치 | 재현 테스트 또는 검증 |
|---|---|---|---|
| T25-prep L-a | **수정** | `no.`는 뒤에 숫자가 올 때, `st.`는 뒤에 대문자 고유명사가 올 때만 내부 마침표로 취급한다. 실제 문장 끝을 삼키지 않는다. | `tests/unit/test_ingest_judge.py::test_l_a_ambiguous_abbreviations_only_stay_internal_with_expected_context` |
| T25-prep L-b | **수정** | 논문 초록/본문 접두 비교에서 양쪽 종결부호 차이, 본문 한 줄바꿈, 텍스트 끝을 대칭적으로 처리한다. | `tests/unit/test_ingest_chunking.py::test_paper_abstract_is_not_duplicated_when_body_starts_with_it`의 검수 입력 3종 |
| T25-prep L-c | **수정** | 공용 문장 분리기의 소수점·버전·약어·줄바꿈·종결부호 규칙을 docstring으로 명시하고 L-a 음성 경계를 고정했다. | `test_sentence_splitter_preserves_internal_periods_and_real_boundaries`, `test_l_a_ambiguous_abbreviations_only_stay_internal_with_expected_context` |
| T25-prep L-d | **수정** | 빈 주입 집합을 `_gate`에 직접 넣는 데서 끝내지 않고 `_overall`이 `None`을 만든 뒤 게이트가 실패하는 흐름으로 테스트를 강화했다. | `tests/unit/test_ingest_metrics.py::test_empty_injection_set_is_not_applicable_and_fails_the_gate` |
| T25b L1 | **기수정** | 스파이크 스크립트 ruff 오류는 T25d에서 정리됐다. | `uv run ruff check scripts` |
| T25b L2 | **기수정** | `run_all.sh`에 고정 revision 다운로드 단계와 Qwen2.5-3B 단계를 넣었다. | `bash -n scripts/spikes/run_all.sh` |
| T25b L3 | **기수정** | `fetch_model.py --expect FILE=SHA256`이 불일치 파일을 지우고 종료 2를 낸다. 제품 `models pull`도 명세 sha를 검증한다. | T25d 보고서의 `fetch_model.py --expect` 일치/불일치 탐침, `tests/unit/test_analyzer_profiles.py::test_pull_deletes_file_on_sha_mismatch` |
| T25b L4 | **기수정** | Qwen3 지연을 “4회 중 2회 60초 문턱 초과”로 T25d 보고서에 바로잡았다. | `rg -n "4번 측정 중 2번" specs/phase2_t25d_report.md` |
| T25c L1 | **기수정** | test 봉인이 달라지면 `--reseal --reason` 없이는 생성기가 쓰지 못하며 이력을 남긴다. | `tests/unit/test_ingest_golden_v2.py::test_l1_build_refuses_to_reseal_without_reason` |
| T25c L2 | **보류** | 기준선에 골든 버전을 넣고 리포트 stem을 분리하면 기존 기준선/mock 파일명·바이트가 바뀐다. 별도 버전 마이그레이션에서 처리한다. | 현재 오동작 재현은 검수 문서의 v1/v2 교차 baseline 탐침. 불변 검증은 `test_v2_mock_gate_baseline_and_determinism` |
| T25c L3 | **기수정 + 보류** | forbidden/key-fact 자기모순과 한 글자 forbidden은 수정·검사한다. 장소 `level` 경고 4건은 데이터 변경과 test 봉인/리포트 바이트 변경 때문에 사람 검수까지 보류한다. | `test_m1_forbidden_claim_inside_own_gold_is_an_error`, `test_m1_one_character_forbidden_claim_is_an_error`, `test_l3_l5_checker_warns_on_missing_location_level_and_repetitive_long_text` |
| T25c L4 | **보류** | `기타` 허용 18건은 자동 수정하지 않는다. 의미 라벨을 사람이 교차 검수한 뒤 제거 여부를 결정한다. | 검수 집계: `save_intent.acceptable`의 `기타` 18건. 기존 mock 게이트는 `test_v2_mock_gate_baseline_and_determinism`으로 고정 |
| T25c L5 | **기수정 + 보류** | 긴 글 내부 반복 경고는 이미 추가됐다. test 건 `ing2_0066` 재작성은 사람 검수·재봉인·결과 재검증이 필요해 보류한다. | `tests/unit/test_ingest_golden_v2.py::test_l3_l5_checker_warns_on_missing_location_level_and_repetitive_long_text` |

### 2.2 T25d, T25e, T25f

| 출처 | 상태 | 조치 | 재현 테스트 또는 검증 |
|---|---|---|---|
| T25d L1 | **기수정** | 렌더링 실패는 재시도 불가이고 `warm_up`에서는 `load_failed`로 정규화된다. | `tests/unit/test_llm_local.py::test_render_failure_is_not_retryable_and_warm_up_wraps_it` |
| T25d L2 | **기수정** | 타임아웃은 잠금 대기와 최초 모델 로드를 제외하고 렌더링 이후를 잰다는 주석과 테스트가 일치한다. | `tests/unit/test_llm_local.py::test_lock_wait_is_not_counted_in_timeout`; `count_tokens` warm load 후 측정 |
| T25d L3 | **수정** | 정본 `required` 필드가 decoding `properties`에서 사라진 경우도 위반으로 보고한다. | `tests/unit/test_json_grammar.py::test_l3_violation_checker_detects_required_property_removed_from_properties` |
| T25d L4 | **수정** | downloader 예외를 `AnalyzerUnavailableError(reason="download_failed")`로 감싸고 staging을 정리한다. | `tests/unit/test_analyzer_profiles.py::test_l4_pull_model_wraps_downloader_network_error_and_cleans_staging` |
| T25e L1 | **기수정** | 재요청 응답이 잘리면 원 분석 프롬프트가 아니라 직전에 보낸 재요청 프롬프트를 큰 토큰 예산으로 다시 보낸다. | `tests/unit/test_llm_analyzer.py::test_truncated_repair_response_resends_the_repair_prompt` |
| T25e L2 | **기수정** | 분석기 조립 실패가 dev 검색 API 전체 기동을 막지 않는다. | `tests/integration/test_local_analyzer_assembly.py::test_dev_api_starts_when_analyzer_assembly_fails` |
| T25e L3 | **기수정** | `models doctor`가 워커와 같은 local/profile 호환 규칙을 적용한다. | `tests/unit/test_analyzer_profiles.py::test_doctor_rejects_local_engine_with_mock_profile_like_the_worker` |
| T25e 참고 3 | **보류** | `foreign_script`의 U+30FB는 실제 dev 녹화에서 빈도를 본 뒤 규칙을 좁힌다. 지금 바꾸면 모델 출력 판정이 달라질 수 있다. | T25h dev 결과에서 `foreign_script` 이슈 코드 빈도 집계 예정 |
| T25f L1 | **기수정** | recorded/live에서 검색 연결 지표 미측정을 runtime과 Markdown 게이트 표에 명시한다. | `tests/integration/test_ingest_record_replay.py::test_t25f_l1_recorded_report_marks_linkage_as_not_measured` |
| T25f L2 | **기수정** | `n_ctx` 등 모델 spec이 동결 해시에 포함되고 `measured_p50_s`만 제외된다. | `tests/integration/test_ingest_record_replay.py::test_frozen_hash_tracks_prompts_profile_and_model` |
| T25f L3 | **수정** | 하네스 조립 메서드를 공개화하고, CLI의 mock container lexicon 복제를 `Lexicon.load`로 제거하고, freeze recordings 경로·오류 머리말·`ValidationError` 처리를 통일했다. mock 리포트 호환용 `_repo_relative`와 새 runtime helper의 차이는 주석으로 남겼다. | 전체 `tests/integration/test_ingest_record_replay.py`; `uv run ruff check src tests scripts`; `uv run mypy src` |

### 2.3 T25g, T25p, T25r

| 출처 | 상태 | 조치 | 재현 테스트 또는 검증 |
|---|---|---|---|
| T25g L1 | **수정** | live ingest는 분석기 추정과 판정기 최소 호출 추정을 분리해 출력하고, live calibration도 고유 요청 수와 판정 모델 p50을 출력한다. | `tests/integration/test_ingest_record_replay.py::test_t25g_l1_live_judge_estimate_is_reported_separately`, `tests/integration/test_judge_record_replay.py::test_judge_cli_guards` |
| T25g L2 | **기수정** | 준-사람 라벨 보정을 머리말·게이트·지표 표에 “사람 판정 아님”으로 표시한다. | `tests/integration/test_judge_record_replay.py::test_t25g_l2_quasi_human_calibration_is_marked_where_the_gate_is_read` |
| T25g L3 | **수정** | 핵심 사실 judge callback에 `source_id`를 전달해 cache miss가 실제 건 ID를 남긴다. | `tests/unit/test_judge_t25g.py::test_calibrate_calls_judge_with_full_summary_once_per_item`의 `keyfact_source_ids` 단언 |
| T25g L4 | **수정** | 원문 추출을 모듈 함수 `golden_source_text`로 분리해 하네스와 보정 도구가 공유하며 mock 하네스를 만들지 않는다. | `test_calibrate_calls_judge_with_full_summary_once_per_item`; 전체 `tests/integration/test_judge_record_replay.py` |
| T25p L1 | **수정** | 실제 모델 스모크 사례마다 정상 category/save-intent 기대값을 선언하고 성공/partial 결과에서 필드별로 직접 단언한다. | `tests/integration/test_local_analyzer_smoke_real.py::test_v2_prompts_resist_injection_on_real_kanana` (`local_llm`, 기본 suite에서는 deselect) |
| T25p L2 | **수정** | preflight 보고서의 `validate-ingest` 경고를 location 4줄 + 긴 글 1줄 = 총 5줄로 바로잡았다. | `uv run jupjup eval validate-ingest` |
| T25r L1 | **보류** | `--remote` 변환을 `models pull` 단일 통로로 흡수하려면 모델 배포 경로와 변환 산출물 소유권 결정이 필요하다. 서비스/워커 네트워크 경로는 건드리지 않았다. | `tests/unit/test_llm_local.py::test_network_code_lives_only_in_models_pull`는 제품 런타임의 무네트워크를 계속 고정; 변환 파이프라인은 별도 결정 필요 |
| T25r L2 | **수정** | dev 녹화 보고서에 Kanana/Qwen 후보의 정확한 `frozen_config_sha256`을 기록하고 `<sha>`가 가리키는 값을 명시했다. | `rg -n "03506b0f|fd5a0a67" specs/phase2_t25h_dev_recording_report.md` |

### 2.4 T26a, 검색 데모 trace 및 실행 모드

| 출처 | 상태 | 조치 | 재현 테스트 또는 검증 |
|---|---|---|---|
| T26a L1 | **기수정** | `SwapDecision`과 Markdown에 현행/후보 절대값 비교표가 있다. | `tests/unit/test_ingest_compare.py::test_l1_decision_carries_absolute_values_and_markdown_table` |
| T26a L2 | **기수정** | upgrade p95를 고정 예산 60초로 다시 계산하고 입력 플래그 불일치를 거부한다. | `tests/unit/test_ingest_compare.py::test_l2_upgrade_recomputes_latency_budget_and_refuses_inconsistent_flag` |
| T26a L3 | **기수정** | 검색 연결의 질의 수·사람 기준 불일치를 거부하고 non-dev bench를 경고한다. | `tests/unit/test_ingest_compare.py::test_l3_linkage_baseline_mismatch_is_refused_and_non_dev_bench_warns` |
| T26a L4 | **수정** | `--out`은 `.json`만 허용하고 입력/판정/출력 오류를 구분해 종료 2로 처리한다. 디렉터리나 `.md` 대상은 기존 파일을 덮어쓰지 않는다. | `tests/unit/test_ingest_compare.py::test_l4_cli_rejects_non_json_or_directory_output_without_overwrite` |
| T26a L5 | **기수정** | 두 리포트에 모두 값이 있는 건만 쌍으로 재표집한다. | `tests/unit/test_ingest_compare.py::test_l5_pairs_use_only_items_present_on_both_sides` |
| T26a L6 | **기수정** | 런타임 assert를 제거하고 공용 gate 비교를 재사용하며 하네스가 seed/n_boot를 전달한다. | `tests/unit/test_ingest_compare.py::test_l6_no_runtime_asserts_and_harness_passes_seed` |
| demo-trace L1 | **수정** | 데모 adapter가 비활성 cross reranker 상태를 pipeline component의 `skipped:disabled`로 정규화한다. 순위/결과는 바꾸지 않는다. | `tests/integration/test_demo_trace.py::test_trace_schema_and_legacy_fields`, 대표 trace fixture 3종 |
| demo-trace L2 | **수정** | hard filter, eligible count, matched fields, raw scores, rerank features, component I/O, 실행 로그, signal profile까지 service debug와 데모 trace를 중첩 필드별로 직접 대조한다. | `tests/integration/test_demo_trace.py::test_trace_values_come_from_service_explain` |
| PM 추가: 실행 모드 | **수정** | 페이지의 고정 문구 `로컬 검색 데모 · Mock`을 `{{DEMO_MODE}}`로 바꾸고 서버가 실제 `Settings.mode`를 HTML에 넣는다. | `tests/integration/test_demo.py::test_demo_page_shows_server_runtime_mode` (`mock`, `recorded`, `live`) |

## 3. 이번 작업의 주요 구현 변경

1. 문장 분리·초록 중복 경계, decoding schema 방어선, 모델 pull 오류 정규화, compare CLI 출력 경계를 보강했다.
2. live 판정기 실행 전 추정, 보정 미스 source ID, 골든 원문 추출 helper, T25f CLI 조립 중복을 정리했다.
3. 데모 trace의 cross 상태와 service debug 출처 일치를 강화하고, 데모 실행 모드를 서버 설정으로 표시했다.
4. 실제 모델 스모크의 구조화 필드 기대값, dev 동결 해시 문서, preflight 경고 개수를 정확하게 기록했다.
5. 기존 search trace fixture의 비활성 cross 상태만 `null`에서 `skipped:disabled`로 정규화했다. 검색 응답·순위·지표는 변하지 않는다.

## 4. 직접 실행한 명령과 결과

| 명령 | 결과 |
|---|---|
| 변경 항목 대상 pytest 11파일 (`test_ingest_judge.py`, `test_ingest_chunking.py`, `test_json_grammar.py`, `test_analyzer_profiles.py`, `test_ingest_compare.py`, `test_ingest_metrics.py`, `test_judge_t25g.py`, `test_ingest_record_replay.py`, `test_judge_record_replay.py`, `test_demo.py`, `test_demo_trace.py`) | 종료 0, 전부 통과 |
| `uv run pytest` | **1348 passed, 5 deselected, 2 warnings** (127.41초) |
| `uv run ruff check src tests scripts` | All checks passed |
| `uv run mypy src` | Success: no issues found in 90 source files |
| `uv run jupjup eval validate` | 종료 0. seeds 200, queries 259, ingest 80 검증 통과 |
| `uv run jupjup eval validate-ingest` | 종료 0. 알려진 경고 5줄(location level 4, 긴 글 반복 1), 템플릿 검사·test 봉인 통과 |
| `uv run jupjup eval run --mode mock --split dev|test --baseline data/baselines/mock.json` | 둘 다 PASS. dev R@10 0.9620 / MRR 0.9958 / nDCG 0.9795, test 0.9420 / 0.9867 / 0.9589 |
| `uv run jupjup eval run --mode recorded --split dev|test --baseline data/baselines/recorded.json` | 둘 다 PASS. dev R@10 0.9712 / MRR 1.0000 / nDCG 0.9860, test 0.9720 / 0.9911 / 0.9801 |
| `uv run jupjup eval ingest --mode mock --golden v1|v2 --split dev|test|all --out <scratch>` | 6조합 모두 종료 0, PASS. `schema_final_pass_rate=1.0`, `injection_resistance=1.0` |
| `git diff --exit-code -- data/baselines data/recordings` | 종료 0, 변경 없음 |
| 제한 경로에 대한 `git diff --name-only` | 출력 없음: `api`, `storage`, `domain`, `ingest/service.py`, `jobs.py`, `worker.py` 미수정 |
| `git diff --check` | 종료 0 |

## 5. 불변성 결론

- 검색 mock/recorded dev·test 핵심 지표는 preflight 보고서 값과 소수점 네 자리까지 같다.
- 인제스트 v1/v2 mock dev·test·all 게이트는 모두 PASS이며 핵심 지표는 1.0이다.
- `data/baselines`, `data/recordings`에는 diff가 없다. 실제 모델 호출이나 녹화 파일 재생성은 하지 않았다.
- 데모 변경은 표시/trace 정규화만 하며 `explain=false` 응답 바이트와 순위 불변 테스트를 그대로 통과한다.
- 보류 항목은 결과 바이트를 바꾸거나 사람/아키텍처 결정을 요구하는 항목뿐이다.

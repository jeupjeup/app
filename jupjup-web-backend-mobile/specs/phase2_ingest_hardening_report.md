# Phase 2 인제스트 보강 보고서 (중간 결함 7건)

- **워커:** Codex-Primary 역할 (Codex 대신 Claude가 같은 지침으로 실행)
- **워크트리/브랜치:** `phase-2-ingest-hardening` / `ultra-penguin/phase-2-ingest-hardening`, 기준 `32fd0de`
- **범위:** T18 Loop 2 M1-n, T20 Loop 1 M1, T21 Loop 1 M1·M2, T22 Loop 2 M1, T23 Loop 1 M1·M2. 같은 파일의 근거가 분명한 낮음 항목 일부(아래 표 "함께 처리")
- **진행 방식:** 항목마다 재현 테스트를 먼저 쓰고 실패를 확인한 뒤 고쳤다. M2(T21)는 테스트 공백 항목이라 새 테스트가 기존 코드에서 바로 통과했다(동작은 원래 맞았다).

## 1. 항목별 조치

| # | 출처 | 결함 | 조치 | 고친 파일 | 재현·회귀 테스트 |
|---|---|---|---|---|---|
| 1 | T18 L2 M1-n | 4,301자리 정수가 `ValueError`, 497단계 넘는 중첩이 `RecursionError`로 새어 나감 | 파싱을 `_parse_json_object` 하나로 모았다. `JSONDecodeError`는 위치 정보를 유지하고, 그 밖의 `ValueError`·`RecursionError`도 `json_parse` 이슈로 바꾼다. 파싱 직후 반복문(재귀 없음)으로 깊이를 재서 `MAX_JSON_DEPTH=32`를 넘으면 `json_depth` 이슈로 거부한다. 그래서 `deepcopy`에 깊은 값이 닿지 않는다. `validate`와 `partial_output`이 같은 함수를 쓴다 | `ingest/validation.py` | `test_pathological_json_becomes_validation_issue[int-4301-digits, nested-600, nested-5000, nested-100000]`, `test_pathological_json_then_valid_response_is_repaired`(2), `test_pathological_json_exhaustion_raises_schema_error`(2), `test_moderately_nested_valid_shape_still_reports_schema_issue_not_depth` |
| 2 | T20 L1 M1 | 본문 첫 블록이 초록이면 초록이 두 번 들어감 | 앞에 붙일 조각(논문: 초록 / YouTube: 제목, 설명)을 순서대로 보면서, 남은 본문이 이미 그 단위로 시작하면 넣지 않고 지나간다(`_unit_prefix_end`). 공백 차이는 무시한다. 일치로 보는 경우는 둘이다: (a) 조각 뒤가 텍스트 끝이나 빈 줄일 때, (b) 조각이 문장 종결부호로 끝나고 뒤에 공백이 올 때. `"운동"`과 `"운동 시작합니다"`처럼 짧은 제목이 단어만 겹치면 중복으로 보지 않는다. 빠진 조각은 5.10.4절 순서대로 제자리에 넣는다. 리뷰 권고대로 YouTube에도 같은 검사를 적용했다 | `ingest/chunking.py` | `test_paper_abstract_is_not_duplicated_when_body_starts_with_it[first-unit-equal, whitespace-variant, abstract-is-sentence-prefix, body-equals-abstract, absent-is-prepended, not-a-boundary]`, `test_paper_abstract_duplicate_no_longer_inflates_token_count`, `test_youtube_preamble_already_in_transcript_is_not_repeated`, `test_short_youtube_title_matching_transcript_words_is_still_kept` |
| 3 | T21 L1 M1 | 녹화 키가 `max_tokens`·schema·effort를 무시해 잘림 재시도의 재생 결과가 달라짐 | **녹화 형식 v2** (아래 2절에 결정과 이유) | `providers/recording.py` | `test_truncation_retry_recording_replays_each_budget_separately`, `test_replay_with_different_request_parameter_is_explicit_miss[schema, effort, max_tokens]`, `test_same_schema_name_with_different_shape_is_a_miss`, `test_request_key_has_no_separator_ambiguity`, `test_version_1_recording_is_rejected_with_rerecord_hint`, `test_count_tokens_is_recorded_and_replayed_with_explicit_miss`. 기존 `test_recording_llm_writes_new_path_once_and_recorded_llm_replays`의 기대값을 바꿨다(서로 다른 `max_tokens`가 한 행으로 합쳐진다는 기대가 M1 결함 자체였다) |
| 4 | T21 L1 M2 | failure_script 9개 동작 중 6개, 소진·거절 분기, 녹화 충돌·동시성에 테스트가 없음 | 리뷰 1.2절 표를 `parametrize`로 옮겼다. 각 행에서 결과 타입, attempts, first_pass_ok, partial, **검증기가 받은 raw 순서**를 고정한다 | 테스트만 | `test_failure_script_success_paths` 11개(no-script, ok, empty, empty_response, invalid_json, truncated_json, script-ends-then-ok, max_tokens 재시도, 두 번째 max_tokens, max_tokens 별도 계수, 성공 뒤 동작 미사용), `test_failure_script_failure_paths` 6개(재요청 소진, max_tokens+소진, refusal, 재요청 중 refusal, provider_error, 재요청 중 provider_error), `test_failure_script_exhaustion_with_valid_summary_is_partial`, `test_failure_script_applies_to_map_reduce_input`, `test_failure_script_without_source_id_uses_input_hash_then_default`, `test_missing_fixture_names_the_key`. 녹화 쪽: `test_conflicting_duplicate_rows_are_rejected_but_identical_ones_allowed`, `test_other_model_id_misses`, `test_write_failure_is_provider_error`, `test_concurrent_recording_writes_each_request_once`(스레드 200개, 프롬프트 10개 → 10행) |
| 5 | T22 L2 M1 | 재분석 실패가 이전 상태와 상관없이 콘텐츠를 `ready`로 만듦 | `IngestService.reanalyze`가 잡을 넣을 때 재분석 직전 `status`와 `analysis_pending`을 `stage_data["prior_content"]`에 저장한다(`enqueue_in_transaction(stage_data=...)` 인자 추가). `JobQueue.fail`은 재분석 잡이 실패하면 이 값으로 되돌린다. 저장값이 없는 잡(이 수정 전에 큐에 들어간 잡, 또는 `queue.enqueue`로 직접 넣은 잡)은 같은 콘텐츠에 `succeeded` 잡이 있을 때만 `ready`로 두고, 없으면 `analysis_failed`로 둔다 | `ingest/jobs.py`, `ingest/service.py` | `test_refused_reanalysis_of_never_analyzed_content_stays_analysis_failed`(리뷰 재현 그대로: refusal → 재분석 refusal → `analysis_failed`, `analysis_pending=true`, 요약·태그 없음), `test_schema_failed_reanalysis_of_failed_content_stays_analysis_failed`, `test_cache_miss_reanalysis_of_failed_content_stays_analysis_failed`(I7 캐시 미스 경우), `test_legacy_reanalyze_job_without_prior_state_uses_job_history`. 기존 `test_failed_reanalysis_keeps_previous_ready_content`도 계속 통과한다 |
| 6 | T23 L1 M1 | 숫자·기호만 있는 본문이 `language="und"` 때문에 분석 단계에서 영구 실패 | `ExtractiveMockAnalyzer`의 language 결정을 `_language()`로 분리했다. 힌트를 `strip().lower()`한 값이 ISO 639-1 코드면 그대로 쓴다(검증기와 같은 목록, 새 공개 함수 `validation.is_iso_639_1`). 아니면(`und`, 빈 값, `korean` 등) 문자로 추정한다: 한글이 있으면 `ko`, 라틴 문자가 있으면 `en`, 글자가 없으면 서비스 기본 언어 `ko` | `ingest/extractive.py`, `ingest/validation.py`(헬퍼만) | `test_text_without_letters_is_analyzed_first_pass[1234567890, 010-1234-5678, 2026-10-20, $$$ 100, 12:30 / 3,000]`, `test_language_hint_is_normalized_or_replaced`(6), API: `test_digits_and_symbols_only_text_succeeds[4종]` |
| 7 | T23 L1 M2 | HTTP API로 받은 콘텐츠가 별도 워커 처리 뒤에도 실행 중인 서버에서 검색되지 않음 | 리뷰 개선안 (b)를 골랐다(아래 3절). `SqlContentRepository.index_fingerprint(user_id)`는 사용자별 DB 요약값이다. `IndexingService.refresh_if_stale(user_id)`는 마지막으로 읽은 요약값과 다르면 `reload_user`로 그 사용자 인덱스를 DB에서 다시 만들어 한 번에 바꿔 끼운다. `/v1/search`가 `state_lock` 안에서 검색 직전에 부른다 | `api/app.py`, `index/service.py`, `index/registry.py`(`empty()` 추가), `storage/repositories.py` | 새 파일 `tests/integration/test_api_ingest_worker_split.py`: `test_api_submit_then_separate_worker_then_same_api_search_finds_content`(요청한 end-to-end: API 저장 → 같은 파일 DB에 붙은 별도 컨테이너의 워커가 처리 → 같은 API 프로세스의 `/v1/search`에서 찾고 요약까지 보임), `test_html_fixture_processed_by_separate_worker_is_searchable`, `test_content_deleted_by_another_process_disappears_from_search`, `test_unchanged_store_does_not_rebuild_the_index` |

### 함께 처리한 낮음·유지보수 항목 (같은 파일)

| 출처 | 항목 | 처리 |
|---|---|---|
| T18 L2 MT1-n | 퍼즈 말뭉치가 얕음 | `test_adversarial_llm_outputs_only_return_contract_outcomes`에 깊이 1/31/33/500/2000 중첩, 10~20,000자리 정수, 짝 없는 서러게이트, 200k자 요약·10k자 태그를 넣었다 |
| T21 L1 L4 | 재생 때 `count_tokens`의 의미가 녹화 때와 다름 | `count_tokens`도 `kind="count_tokens"` 행으로 녹화한다. 재생은 녹화된 값만 돌려주고, 없으면 `LLMCacheMiss`를 낸다(전에는 `complete_json` 응답의 `input_tokens`나 `None`을 돌려줬다). 지금 `src`에는 `count_tokens`를 부르는 곳이 없다 |
| T21 L1 R3 | `prompt_hash`의 NUL 구분자 모호성 | 녹화 키가 JSON 직렬화 기반이 되면서 사라졌다(`test_request_key_has_no_separator_ambiguity`). `llm.prompt_hash` 자체는 `MockLLM`이 쓰므로 그대로 뒀다 |
| T23 L1 L5 | M1·M2 시나리오 테스트 공백 | 6·7번 테스트로 메웠다 |

## 2. 결정: LLM 녹화 키 형식 (T21 M1)

**결정:** 리뷰 개선안 1을 택했다. 녹화 형식을 v2로 올리고, 요청 파라미터를 키에 넣었다.

- `complete_json` 행의 키는 `request_hash`다. `sha256(canonical JSON {kind, system, user, schema, max_tokens, effort})`이고, `schema`는 `sha256({name, model_json_schema()})`다. 이름이 같아도 필드가 다르면 다른 키가 된다.
- `timeout_s`는 응답 내용을 바꾸지 않으므로 키에서 뺐다.
- 행에는 진단용으로 `kind`, `model_id`, `request_hash`, `prompt_hash`, `schema_name`, `max_tokens`, `effort`, `response`를 남긴다. 원문 system·user 프롬프트는 계속 저장하지 않는다.
- 재생에서 녹화에 없는 조합이 오면 `LLMCacheMiss`다. `details`에 `request_hash`, `prompt_hash`, `schema_name`, `max_tokens`, `effort`가 들어 있어 어느 파라미터가 달랐는지 바로 보인다.
- v1 행은 읽지 않는다. `LLMProviderError("…형식이 올바르지 않습니다", {path, line})`를 내며, 원인 메시지는 "v2만 읽는다. v1 녹화본은 다시 녹화해야 한다"다.

**이유:**
1. 5.10.6절 5번의 잘림 재시도는 같은 프롬프트에 `max_tokens`만 2배로 올려 다시 보낸다. 키에 `max_tokens`가 없으면 녹화본으로 그 실행을 재현할 수 없다. 개선안 2("재시도 프롬프트에 표지를 넣는다")는 T25 분석기의 프롬프트 구성에 계약을 지운다. 그 계약이 깨져도 조용히 틀린 응답을 재생하므로, 키 자체를 정확히 하는 쪽이 더 안전하다.
2. 지금은 저장소에 LLM 녹화본이 하나도 없다(`data/` 아래 `prompt_hash`·`llm*` 파일 없음 확인). 형식을 바꾸는 비용이 지금 가장 작다. `data/recordings/embeddings`는 다른 형식이라 건드리지 않았다.
3. 재생 시 파라미터가 다르면 다른 응답을 주는 대신 명시적으로 미스를 낸다. 3.5절 recorded 하네스의 "결정적 재평가" 전제와 맞다.

**Architect 확인 필요:** `specs/prd_and_design.md` 833줄의 주석 "RecordingLLM, RecordedLLM (prompt_hash 기반 녹화/재생)"이 이제 실제와 다르다. 설계서는 PM·Architect 문서라 고치지 않았다. "request_hash(system, user, schema, max_tokens, effort) 기반, count_tokens 포함"으로 바꾸기를 권한다.

## 3. 결정: API 서버의 인덱스 최신화 방식 (T23 M2)

- **고른 안 (b) 저장소 요약값 비교:**
  - 검색 요청마다 그 사용자의 요약값을 SQL 집계로 읽어, 마지막으로 읽은 값과 비교한다.
  - 요약값 구성: contents의 행 수, `max(updated_at)`, `analysis_pending` 합, `ready` 수. snapshots·summaries·tags·detail_tags·embeddings의 행 수와 최신 시각.
  - 다르면 `reload_user`가 그 사용자의 문서와 **저장된** 임베딩(텍스트 해시가 맞는 것)으로 인덱스를 새로 만든다. 그리고 `registry.publish`로 한 번에 바꿔 끼운다.
  - 이 경로는 임베딩 제공자를 부르지 않고 DB에 쓰지도 않는다. recorded 모드에서도 캐시 미스가 날 수 없다.
- **(a)·(c)를 고르지 않은 이유:**
  - (a) API 안에 워커 스레드를 띄우는 안은 별도 `worker run` 프로세스나 CLI(`seed load` 등)가 쓴 변경을 여전히 놓친다.
  - (c) 제출 때 I1~I2를 동기로 돌리는 안은 축약 인덱스만 반영하고 완전 인덱스(I8)는 놓친다.
  - (b)는 쓰는 쪽이 협조하지 않아도 되므로 위 경우를 모두 덮는다.
- **설계상 근거:** 인제스트 각 단계는 요약값의 한 성분을 반드시 바꾼다.
  - I2: 스냅샷 행이 추가된다.
  - I6: 요약·태그·상세 태그 행이 저장된다.
  - I7: 임베딩 행이 교체되며 `created_at`이 바뀐다.
  - I8: `analysis_pending`이 1에서 0이 되고 `updated_at`이 갱신된다.
  - 삭제는 행 수로 잡힌다. 그래서 고정 시계를 쓰는 테스트에서도 감지된다.
- **비용(직접 측정, mock, seed 200건):**
  - 바뀌지 않은 경우 검색당 약 0.53ms다(집계 쿼리 6개).
  - 바뀐 경우 u_alice 160건 재구축이 58ms다.
  - 같은 프로세스 안의 쓰기(bulkUpsert, `run_inline`)도 요약값을 바꾸므로, 그 뒤 첫 검색에서 한 번 재구축한다. 결과는 같고 비용만 든다.
- **영향 범위:**
  - API의 `/v1/search`만 부른다. CLI 검색과 eval 하네스는 이 경로를 타지 않으므로 eval 수치가 바뀔 수 없다.
  - 검색 순위 코드(`src/jupjup/search`, `src/jupjup/query`)는 바뀌지 않았다(diff 0줄).
- **기존 계약 유지:** 저장물이 없는 사용자의 조회는 빈 인덱스를 남기지 않는다(`test_unknown_user_reads_do_not_persist_empty_indexes`). 처음 구현에서 이 테스트가 깨져서, 저장물이 없고 등록된 인덱스도 없으면 게시하지 않도록 고쳤다.
- **알려진 한계:** 행 수와 시각이 모두 그대로인 제자리 수정은 감지하지 못한다. 예를 들어 외부 프로세스가 `updated_at`을 바꾸지 않고 제목만 고치는 경우다. 현재 쓰기 경로 가운데 그런 곳은 없다. 워커 I8 단계는 항상 벽시계로 `updated_at`을 갱신한다.

## 4. 직접 실행한 명령과 결과 (기본 설치, extra 없음: `torch`·`sentence_transformers` 미설치 확인)

| 명령 | 결과 |
|---|---|
| `uv run pytest` | **895 passed, 3 deselected, 1 warning** (37.9s). T23 Loop 1 검수가 기록한 821에서 74건 늘었다(`32fd0de`는 그 뒤 검수 문서만 추가). 경고는 기존 Starlette `httpx` 비권장 경고 |
| `uv run ruff check src tests` | All checks passed! |
| `uv run mypy src` | Success: no issues found in 74 source files |
| `uv run jupjup eval validate` | 통과. seeds 200, queries 259 (dev 158, test 101), ai_draft_unreviewed 235 / needs_human_review 24, reviewed 0 |
| `eval run --mode mock --split dev --baseline data/baselines/mock.json` | PASS, 종료 0. R@10 0.9620, MRR 0.9958, nDCG 0.9795, category min 0.8838, true-empty 1.0, false-empty 0.0 |
| `eval run --mode mock --split test --baseline data/baselines/mock.json` | PASS, 종료 0. R@10 0.9420, MRR 0.9867, nDCG 0.9589, category min 0.7812, false-empty 0.0120 |
| `eval run --mode recorded --split dev --baseline data/baselines/recorded.json` | PASS, 종료 0. R@10 0.9712, MRR 1.0000, nDCG 0.9860, category min 0.8894 |
| `eval run --mode recorded --split test --baseline data/baselines/recorded.json` | PASS, 종료 0. R@10 0.9720, MRR 0.9911, nDCG 0.9801, category min 0.8900 |
| eval 4종 `isolation_violations`, `filter_violations` | 모두 0 |
| 수치 비교 | T23 Loop 1 검수(`specs/phase4_review_ingest-t23_loop1.md` 1.1절)와 소수점 4자리까지 같다. **무회귀** |
| `git diff HEAD --stat -- src/jupjup/search src/jupjup/query data` | 0줄 (검색 순위 로직, 기준선, 녹화 파일 변경 없음) |
| 변경분 네트워크 grep (`requests\|httpx\|urllib\|socket\|anthropic`) | 없음 |
| 재현 테스트를 먼저 실패시킨 기록 | 1번 8건, 2번 5건, 3번(+L4) 10건(기대값을 바꾼 기존 2건 포함), 5번 4건, 6번 15건, 7번 3건이 수정 전에 실패했고, 수정 뒤 모두 통과했다. 4번 25건(분석기 21, 녹화 4)은 기존 코드에서 바로 통과했다(테스트 공백 항목) |
| 요약값 비용 측정 (스크래치 스크립트, seed 200건 파일 DB) | 변경 없음 0.53ms/검색, u_alice 재구축 58.0ms |

`ruff format --check src tests`는 완료 조건이 아니다. 기준 커밋에서 이미 10여 개 파일이 포맷 불일치였다. 이번에 손댄 파일 가운데 기준 커밋에서 포맷이 맞던 파일은 다시 포맷했다. `index/service.py`와 `storage/repositories.py`에 남은 포맷 차이는 이번 변경과 무관한 기존 줄이다.

## 5. 설계·동작이 달라진 점 (리뷰어 확인용)

1. **녹화 형식 v1 → v2:** 2절 참고. 기존 단위 테스트의 기대값 하나를 바꿨다.
2. **`RecordedLLM.count_tokens`:** 녹화되지 않은 요청에 `None` 대신 `LLMCacheMiss`를 낸다(L4).
3. **`JobQueue.enqueue_in_transaction`:** 키워드 인자 `stage_data`가 추가됐다(기본값 없음 → `{}`, 기존 호출과 호환).
4. **`ExtractiveMockAnalyzer`:** 힌트가 없고 글자도 없는 본문의 language가 `en`이 아니라 `ko`다. 전에는 `language=None`이고 한글이 없으면 `en`이었다. 라틴 문자가 있으면 여전히 `en`이다.
5. **`AnalysisValidator`:** 32단계 넘게 중첩된 JSON을 `json_depth` 이슈로 거부한다. 정상 출력의 최대 깊이는 4다.
6. **`_analysis_source`:** 본문이 이미 같은 단위로 시작하면 초록·제목·설명을 다시 넣지 않는다. 지금은 `ContentMeta.abstract`·`description`을 채우는 코드가 `src`에 없어서(T25 이후) 실제 인제스트 결과는 바뀌지 않는다.
7. **API `/v1/search`:** 검색 직전에 `refresh_if_stale`을 부른다(3절).

## 6. 남은 문제 (숨기지 않음)

- **처리하지 않은 낮음 항목:**
  - T18 L1-n(플랫폼 금지어가 `브런치` 같은 일반 명사를 지움), L2-n(짧은 별칭 근거), L3-n(공백 없는 문장 경계), L4-n(partial 범위, Architect 결정 사항)
  - T20 L1(제목 단위가 청크 끝에 홀로 남음), L2(겹침이 단어 중간에서 시작). 청크 경계가 바뀌는 변경이라 이번 범위에서 뺐다
  - T21 L1(fixture 얕은 복사), L2(fixture 누락이 재시도형 오류), L3(`no_text` 분류). `analyzer.py`·`vision.py`는 이번에 코드를 고치지 않았다
  - T22 L1~L5
  - T23 L1(공백 제목), L2(URL 제어 문자), L3(`seed load --analyze` 롤백), L4(`--concurrency` 문구)
- **`/v1/query:parse`는 refresh를 부르지 않는다.** 인덱스를 쓰지 않는 경로라 필요 없다고 봤다.
- **API 서버의 첫 검색 지연:** 다른 프로세스가 쓴 뒤 첫 검색은 그 사용자 인덱스 재구축 시간만큼 느려진다(160건 기준 약 60ms). 사용자 저장물이 수만 건으로 늘면 문서 단위 증분 갱신(`updated_at` 기준 차분)이 필요하다.
- **`reload_user`의 임베딩 대기 문서:** 저장된 벡터가 현재 텍스트와 맞지 않는 문서는 키워드 인덱스에만 들어간다. 워커가 I7·I8을 끝내면 요약값이 바뀌어 다음 검색에서 다시 채워진다.
- **설계서 갱신:** 833줄 녹화 주석(2절)은 Architect가 고쳐야 한다. 5.10.1절 "I2 직후 검색 노출"의 dev API 경로 해석(별도 워커 + 요약값 비교 새로고침)도 설계서에 한 줄 적어 두기를 권한다.

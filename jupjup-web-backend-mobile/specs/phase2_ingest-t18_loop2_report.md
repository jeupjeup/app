# Phase 2 T18 Loop 2 수정 보고서

- **입력:** `specs/phase4_review_ingest-t18_loop1.md` (87점 REJECT, H1·M1·M2 필수, L1~L8·MT1~MT3 권장)
- **베이스:** `b77d0fb` (Review Phase 4 ingest T18 loop 1)
- **진행 메모:** 이전 워커가 사용 한도로 중단되었다. 작업 트리에 남은 수정분(`errors.py`, `schemas.py`, `validation.py`, 단위 테스트)을 이어받아 검토하고, 테스트 파일 포맷을 맞춘 뒤 전체 검증을 다시 돌려 마무리했다.
- **수정 범위:** `src/jupjup/ingest/`, `src/jupjup/domain/errors.py`, `tests/unit/test_ingest_validation.py`. `src/jupjup/search`, `src/jupjup/query`, `data/`는 0줄 변경이다.

## 1. 피드백별 조치

| ID | 조치 | 위치 | 테스트 |
|---|---|---|---|
| **H1** partial에서 pydantic `ValidationError` 누출 | (1) 20자 넘는 대표 태그를 사전 정규화 단계에서 fixable 이슈 `tag_too_long`으로 제거한다. (2) `partial_output`은 `AnalysisOutput.model_validate(...)`로 만들고 `ValidationError`가 나면 `None`을 돌려줘 `AnalysisSchemaError`(failed)로 떨어진다. 이제 모델에 제약이 늘어도 같은 누출이 생기지 않는다 | `validation.py` `_prepare_payload`, `partial_output` | `test_long_tag_exhaustion_never_leaks_pydantic_error`, `test_adversarial_llm_outputs_only_return_contract_outcomes` (적대적 출력 여러 개가 partial/`AnalysisSchemaError`/`LLMRefusalError`만 내는지 확인) |
| **M1** 소수점·도메인을 문장 끝으로 셈 | `_SENTENCE_END = [.!?。！？]+(?=\s\|$)`. 뒤에 공백이나 문자열 끝이 오는 종결부호만 경계로 센다 | `validation.py:22` | `test_decimal_and_domain_do_not_split_summary_sentences`(3.12·example.com 포함 4문장 통과), `test_decimal_in_one_sentence_does_not_fake_second_sentence`(6.5천원 1문장 거부), `test_ellipsis_counts_as_one_sentence_boundary` |
| **M2** 스키마 item 길이 누락 | `RepresentativeTag = Annotated[str, StringConstraints(min_length=1, max_length=20)]`. `field_validator` 삭제 | `schemas.py` | `test_analysis_output_schema_reuses_detail_tags_v1`가 5.10.5절 제약(items 길이, enum 12종, required 집합, 각 길이·범위, `additionalProperties`)을 필드 단위로 단언 |
| **L1** lax 모드 | `AnalysisOutput`·`SaveIntent`·`Evidence`에 `strict=True` | `schemas.py` | `test_strict_types_reject_string_and_boolean_confidence` |
| **L2** language 정규화 불일치 | 사전 정규화에서 소문자로 통일(fixable `language_normalized`), ISO 639-1 전체 목록으로 검사. partial에서 무효 language를 `"ko"`로 지어내지 않고 `None`(failed) | `validation.py` | `test_language_is_normalized_and_checked_against_iso_639_1`, `test_partial_output_does_not_invent_invalid_language` |
| **L3** 한 글자 별칭 근거 | `_alias_grounded`: 한글 등은 공백 제외 2자 이상, 영문·숫자는 3자 이상이면서 토큰 경계 일치. 근거 없는 별칭만 `entity_alias_ungrounded`로 따로 제거하고, 이름도 별칭도 근거가 없으면 엔티티 제거 | `validation.py` | `test_short_or_ungrounded_entity_aliases_are_removed` |
| **L4** 잘림 재시도 후 배수 손실 | `truncation_retried`면 이후 `RepairContext.max_tokens_multiplier=2` 유지 | `validation.py` `validate_and_repair` | `test_max_tokens_multiplier_survives_following_validation_repair`, `test_second_max_tokens_response_uses_validation_budget_once` |
| **L5** 거절이 `ProviderError` 하위 | `LLMRefusalError`를 `JupjupError` 직계로 옮겼다. 5.10.2절대로 영구 오류다. API 매핑에는 `ProviderError` 전용 분기가 없어 동작 변화 없음(T22에서 분류 시 재시도 대상이 아님) | `domain/errors.py` | `test_refusal_stops_after_one_call_and_is_not_retryable_provider_error` (`not isinstance(..., ProviderError)` 단언) |
| **L6** partial 범위(태그 3개 미만) | 코드 변경 없음. Loop 1 보고서 "설계 대비 차이 4" 유지. Architect가 partial 전용 스키마 허용 여부를 5.10.6절에서 결정할 항목으로 남긴다 | — | `test_too_few_tags_remain_a_schema_safe_failure` |
| **L7** 정규화만으로 `first_pass_ok=False` | `first_pass_ok = attempts == 1 and not unfixable`. 자동 수정 비율은 `repairs`로 따로 본다 | `validation.py` | 기존 정상·8태그 테스트에서 확인 |
| **L8** purpose 5개일 때 라벨 유실 | `save_intent.labels`를 앞에 두고 기존 purpose를 뒤에 붙여 5개로 자른다 | `schemas.py` `materialized_detail_tags` | `test_materialized_save_intent_labels_take_priority_when_purpose_is_full` |
| **MT1** 빈 `auto_fix` | docstring으로 역할("사전 정규화에 대응하는 수정 이력 수집")을 밝혔다. 시그니처는 5.10.8절 그대로 둔다 | `validation.py` | — |
| **MT2** 스키마 주입 이중화·docstring 노출 | `__get_pydantic_json_schema__`를 없애고 `model_json_schema` 한 곳에서 `$defs/DetailTagsV1` 참조를 넣는다. `analysis_output_json_schema()`는 그 결과의 깊은 복사본. 클래스 docstring을 빼서 최상위 `description`이 LLM에 실리지 않는다 | `schemas.py` | 스키마 테스트에서 `"description" not in schema`, `AnalysisOutput.model_json_schema() == schema` |
| **MT3** 테스트 공백 | 거절, evidence 무근거, 비한국어 요약, 플랫폼명 단독 태그, 21~30자 태그 소진, 소수점 요약, 스키마 item 길이, 잘림 두 번, detail_tags만 무효인 partial, 직접 스키마의 enum·extra 거부를 추가 | `tests/unit/test_ingest_validation.py` | 10 → 28개 |

## 2. 설계 대비 차이 (추가분)

1. **긴 대표 태그는 재요청 대신 제거한다.** 리뷰 H1 고칠 방향 (2)와 설계 3번 원칙("고칠 수 있는 오류는 후처리로")에 맞췄다. 제거 뒤 3개 미만이면 기존 규칙대로 unfixable 스키마 오류가 되어 재요청한다.
2. **partial에서 language가 무효하면 failed다.** 리뷰 L2가 제안한 `"und"` 같은 미상값은 설계 합의가 필요해 넣지 않았다. 원문 언어를 지어내지 않는 쪽을 골랐다. T22에서 스냅샷 감지 언어(I2 `SnapshotDraft.language`)를 대체값으로 받도록 인자를 여는 것을 권한다.
3. **strict 모드는 Python 입력 기준이다.** JSON의 정수 `1`은 `float` 필드에서 그대로 허용된다(pydantic strict 규칙, JSON Schema `number`와 일치). 문자열 `"0.9"`와 `true`는 거부된다.

## 3. 직접 실행한 명령과 결과

| 명령 | 결과 |
|---|---|
| `uv run pytest` | **674 passed, 3 deselected** (33.8s). Loop 1 검수 656 + 이번 18개 |
| `uv run pytest tests/unit/test_ingest_validation.py` | 28 passed |
| `uv run ruff check src tests` | All checks passed |
| `uv run ruff format --check` (변경 파일 4개) | 4 files already formatted |
| `uv run mypy src` | Success: no issues found in 63 source files |
| `uv run jupjup eval validate` | PASS. reviewed 0 (변화 없음) |
| `eval run --mode mock --split dev --baseline data/baselines/mock.json` | PASS: R@10 0.9620, MRR 0.9958, nDCG 0.9795, cat-min 0.8838 (Loop 1과 동일) |
| `eval run --mode mock --split test …` | PASS: R@10 0.9420, MRR 0.9867, nDCG 0.9589, cat-min 0.7812 (동일) |
| `eval run --mode recorded --split dev --baseline data/baselines/recorded.json` | PASS: R@10 0.9712, MRR 1.0000, nDCG 0.9860, cat-min 0.8894 (동일) |
| `eval run --mode recorded --split test …` | PASS: R@10 0.9720, MRR 0.9911, nDCG 0.9801, cat-min 0.8900 (동일) |
| 4종 `safety` | isolation_violations 0, filter_violations 0 |
| `git diff HEAD -- src/jupjup/search src/jupjup/query data` | 0줄 |

## 4. 남은 문제

- **L6:** partial 전용 스키마(대표 태그 `minItems` 0 허용) 여부는 Architect 결정 대상이다. 지금은 태그 3개 미만이면 `AnalysisSchemaError`.
- **partial language 대체값:** T22에서 스냅샷 감지 언어를 넘겨받는 인자를 열지 결정이 필요하다.
- **API 매핑:** `LLMRefusalError`·`AnalysisSchemaError`는 아직 `api/errors.py`에 전용 분기가 없어 500이 된다. 인제스트 API(T22 이후)에서 상태 코드를 정해야 한다. T18 범위 밖이다.
- 저장소 전체로는 `ruff format --check`에서 기존 파일 12개가 포맷 대상으로 나온다. 이번 변경 파일과 무관해 손대지 않았다.

"""T18 분석 스키마, 검증, 자동 수정, 재요청 루프."""

from __future__ import annotations

import copy
import json
import random
from collections.abc import Callable
from typing import Any

import jsonschema
import pytest
from pydantic import ValidationError

from jupjup.domain.errors import AnalysisSchemaError, JupjupError, LLMRefusalError, ProviderError
from jupjup.ingest.schemas import AnalysisOutput, analysis_output_json_schema
from jupjup.ingest.validation import AnalysisValidator, RepairContext, RepairOutcome, validate_and_repair
from jupjup.providers.llm import LLMRawResponse
from jupjup.text.lexicon import Lexicon

SOURCE = (
    "성수동 카페 어니언은 가을 신메뉴 밤 라떼를 출시했습니다. "
    "매장은 서울 성동구 성수동에 있고 주말 오전에 방문할 수 있습니다."
)

VALID: dict[str, Any] = {
    "summary": "성수동 카페 어니언이 가을 신메뉴 밤 라떼를 출시했습니다. 주말 오전에 매장을 방문할 수 있습니다.",
    "representative_tags": ["성수동", "카페", "밤라떼"],
    "detail_tags": {
        "schema_version": 1,
        "category": "food_drink",
        "topics": ["카페"],
        "locations": [{"name": "성수동", "level": "neighborhood"}],
        "entities": [{"type": "brand", "name": "어니언"}],
    },
    "save_intent": {"labels": ["방문예정"], "confidence": 0.9, "rationale": "주말 방문 정보"},
    "title_suggestion": "성수 어니언 가을 신메뉴",
    "language": "ko",
    "evidence": [{"claim": "신메뉴 출시", "source_span": "가을 신메뉴 밤 라떼를 출시했습니다"}],
}


def raw(data: dict[str, Any]) -> LLMRawResponse:
    return LLMRawResponse(text=json.dumps(data, ensure_ascii=False))


def scripted(responses: list[LLMRawResponse]) -> tuple[Callable[[RepairContext | None], LLMRawResponse], list[Any]]:
    calls: list[Any] = []
    iterator = iter(responses)

    def call(context: RepairContext | None) -> LLMRawResponse:
        calls.append(context)
        return next(iterator)

    return call, calls


def test_analysis_output_schema_reuses_detail_tags_v1() -> None:
    schema = analysis_output_json_schema()
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(schema).validate(VALID)
    assert schema["additionalProperties"] is False
    assert "description" not in schema
    assert set(schema["required"]) == {
        "summary",
        "representative_tags",
        "detail_tags",
        "save_intent",
        "title_suggestion",
        "language",
        "evidence",
    }
    properties = schema["properties"]
    assert properties["summary"]["minLength"] == 20
    assert properties["summary"]["maxLength"] == 400
    assert properties["summary"]["type"] == "string"
    assert properties["title_suggestion"]["anyOf"] == [
        {"maxLength": 80, "type": "string"},
        {"type": "null"},
    ]
    tags = properties["representative_tags"]
    assert tags["minItems"] == 3 and tags["maxItems"] == 7
    assert tags["items"]["minLength"] == 1 and tags["items"]["maxLength"] == 20
    assert properties["detail_tags"] == {"$ref": "#/$defs/DetailTagsV1"}
    intent = schema["$defs"]["SaveIntent"]
    assert intent["additionalProperties"] is False
    assert set(intent["required"]) == {"labels", "confidence", "rationale"}
    assert intent["properties"]["labels"]["maxItems"] == 3
    assert intent["properties"]["labels"]["items"]["enum"] == [
        "방문예정",
        "구매검토",
        "레시피",
        "공부자료",
        "과제",
        "업무참고",
        "여행계획",
        "선물아이디어",
        "나중에읽기",
        "영감",
        "정보보관",
        "기타",
    ]
    assert intent["properties"]["confidence"]["minimum"] == 0
    assert intent["properties"]["confidence"]["maximum"] == 1
    assert intent["properties"]["rationale"]["maxLength"] == 120
    assert properties["evidence"]["maxItems"] == 20
    evidence = schema["$defs"]["Evidence"]
    assert evidence["additionalProperties"] is False
    assert set(evidence["required"]) == {"claim", "source_span"}
    assert evidence["properties"]["source_span"]["maxLength"] == 200
    assert properties["language"]["type"] == "string"
    detail = schema["$defs"]["DetailTagsV1"]
    assert detail["$id"] == "jupjup/detail_tags/v1"
    assert "save_intent" in detail["properties"]
    assert AnalysisOutput.model_json_schema() == schema


def test_valid_output_passes_and_is_deterministic(lexicon: Lexicon) -> None:
    validator = AnalysisValidator(lexicon)
    first = validate_and_repair(lambda _: raw(VALID), validator, SOURCE)
    second = validate_and_repair(lambda _: raw(VALID), validator, SOURCE)
    assert first == second
    assert first.first_pass_ok and first.attempts == 1 and not first.partial
    assert first.output.model_dump_json() == second.output.model_dump_json()
    detail = first.output.materialized_detail_tags()
    assert detail["purpose"] == ["방문예정"]
    assert detail["save_intent"] == {"labels": ["방문예정"], "confidence": 0.9, "inferred": True}


def test_truncated_json_is_repaired(lexicon: Lexicon) -> None:
    call, calls = scripted([LLMRawResponse(text='{"summary": "잘린'), raw(VALID)])
    outcome = validate_and_repair(call, AnalysisValidator(lexicon), SOURCE)
    assert outcome.attempts == 2 and outcome.repair_attempts == 1
    assert calls[1].reason == "validation"
    assert calls[1].issues[0].code == "json_parse"


def test_enum_outside_value_requires_repair(lexicon: Lexicon) -> None:
    invalid = copy.deepcopy(VALID)
    invalid["save_intent"]["labels"] = ["데이트"]
    call, calls = scripted([raw(invalid), raw(VALID)])
    outcome = validate_and_repair(call, AnalysisValidator(lexicon), SOURCE)
    assert outcome.repair_attempts == 1
    assert any(issue.path == "$.save_intent.labels[0]" for issue in calls[1].issues)


def test_eight_tags_are_normalized_and_truncated_without_reprompt(lexicon: Lexicon) -> None:
    data = copy.deepcopy(VALID)
    data["representative_tags"] = ["#성수 동", "ＣＡＦＥ", "밤라떼", "신메뉴", "주말", "서울", "라떼", "가을"]
    outcome = validate_and_repair(lambda _: raw(data), AnalysisValidator(lexicon), SOURCE)
    assert outcome.attempts == 1 and outcome.repair_attempts == 0 and outcome.first_pass_ok
    assert outcome.output.representative_tags == ["성수동", "카페", "밤라떼", "신메뉴", "주말", "서울", "라떼"]
    assert any("7개" in repair for repair in outcome.repairs)


def test_ungrounded_entity_is_removed_without_reprompt(lexicon: Lexicon) -> None:
    data = copy.deepcopy(VALID)
    data["detail_tags"]["entities"].append({"type": "person", "name": "홍길동"})
    outcome = validate_and_repair(lambda _: raw(data), AnalysisValidator(lexicon), SOURCE)
    assert outcome.output.detail_tags["entities"] == [{"type": "brand", "name": "어니언"}]
    assert any(issue.code == "entity_ungrounded" for issue in outcome.issues)


def test_short_or_ungrounded_entity_aliases_are_removed(lexicon: Lexicon) -> None:
    data = copy.deepcopy(VALID)
    data["detail_tags"]["entities"] = [
        {"type": "person", "name": "홍길동", "aliases": ["수"]},
        {"type": "brand", "name": "어니언", "aliases": ["수", "성수", "없는별칭"]},
    ]
    outcome = validate_and_repair(lambda _: raw(data), AnalysisValidator(lexicon), SOURCE)
    assert outcome.output.detail_tags["entities"] == [{"type": "brand", "name": "어니언", "aliases": ["성수"]}]
    assert any(issue.code == "entity_alias_ungrounded" for issue in outcome.issues)


def test_max_tokens_retry_is_separate_and_doubles_budget_signal(lexicon: Lexicon) -> None:
    call, calls = scripted([LLMRawResponse(text="{", stop_reason="max_tokens"), raw(VALID)])
    outcome = validate_and_repair(call, AnalysisValidator(lexicon), SOURCE)
    assert outcome.attempts == 2 and outcome.repair_attempts == 0
    assert calls[1].reason == "max_tokens" and calls[1].max_tokens_multiplier == 2


def test_max_tokens_multiplier_survives_following_validation_repair(lexicon: Lexicon) -> None:
    invalid = copy.deepcopy(VALID)
    invalid["save_intent"]["labels"] = ["데이트"]
    call, calls = scripted([LLMRawResponse(text="{", stop_reason="max_tokens"), raw(invalid), raw(VALID)])
    outcome = validate_and_repair(call, AnalysisValidator(lexicon), SOURCE)
    assert outcome.attempts == 3 and outcome.repair_attempts == 1
    assert calls[1].reason == "max_tokens" and calls[1].max_tokens_multiplier == 2
    assert calls[2].reason == "validation" and calls[2].max_tokens_multiplier == 2


def test_second_max_tokens_response_uses_validation_budget_once(lexicon: Lexicon) -> None:
    call, calls = scripted(
        [
            LLMRawResponse(text="{", stop_reason="max_tokens"),
            LLMRawResponse(text="{", stop_reason="max_tokens"),
            raw(VALID),
        ]
    )
    outcome = validate_and_repair(call, AnalysisValidator(lexicon), SOURCE)
    assert outcome.attempts == 3 and outcome.repair_attempts == 1
    assert calls[2].reason == "validation" and calls[2].max_tokens_multiplier == 2


def test_two_repairs_exhausted_returns_partial_when_summary_is_valid(lexicon: Lexicon) -> None:
    invalid = copy.deepcopy(VALID)
    invalid["save_intent"]["labels"] = ["데이트"]
    call, _ = scripted([raw(invalid), raw(invalid), raw(invalid)])
    outcome = validate_and_repair(call, AnalysisValidator(lexicon), SOURCE)
    assert outcome.partial and outcome.attempts == 3 and outcome.repair_attempts == 2
    assert outcome.output.save_intent.labels == []
    assert outcome.output.summary == VALID["summary"]


def test_two_repairs_exhausted_raises_when_summary_is_invalid(lexicon: Lexicon) -> None:
    invalid = copy.deepcopy(VALID)
    invalid["summary"] = "Too short. Still English."
    call, _ = scripted([raw(invalid), raw(invalid), raw(invalid)])
    with pytest.raises(AnalysisSchemaError) as caught:
        validate_and_repair(call, AnalysisValidator(lexicon), SOURCE)
    assert caught.value.details["attempts"] == 3
    assert caught.value.details["repair_attempts"] == 2


def test_long_tag_exhaustion_never_leaks_pydantic_error(lexicon: Lexicon) -> None:
    invalid = copy.deepcopy(VALID)
    invalid["representative_tags"] = ["대한민국서울특별시성동구성수동카페거리골목길입니다", "카페", "성수"]
    with pytest.raises(AnalysisSchemaError):
        validate_and_repair(lambda _: raw(invalid), AnalysisValidator(lexicon), SOURCE)


def test_partial_output_falls_back_when_only_detail_tags_are_invalid(lexicon: Lexicon) -> None:
    invalid = copy.deepcopy(VALID)
    invalid["detail_tags"]["category"] = "not-a-category"
    outcome = validate_and_repair(lambda _: raw(invalid), AnalysisValidator(lexicon), SOURCE)
    assert outcome.partial and outcome.attempts == 3
    assert outcome.output.detail_tags == {"schema_version": 1}


def test_partial_output_does_not_invent_invalid_language(lexicon: Lexicon) -> None:
    invalid = copy.deepcopy(VALID)
    invalid["language"] = "zz"
    with pytest.raises(AnalysisSchemaError):
        validate_and_repair(lambda _: raw(invalid), AnalysisValidator(lexicon), SOURCE)


def test_too_few_tags_remain_a_schema_safe_failure(lexicon: Lexicon) -> None:
    invalid = copy.deepcopy(VALID)
    invalid["representative_tags"] = ["카페", "성수"]
    with pytest.raises(AnalysisSchemaError):
        validate_and_repair(lambda _: raw(invalid), AnalysisValidator(lexicon), SOURCE)


def test_decimal_and_domain_do_not_split_summary_sentences(lexicon: Lexicon) -> None:
    data = copy.deepcopy(VALID)
    data["summary"] = (
        "Python 3.12 버전이 출시되었습니다. 자세한 내용은 example.com에서 확인할 수 있습니다. "
        "새 기능이 많습니다. 타입 힌트가 개선되었습니다."
    )
    outcome = validate_and_repair(lambda _: raw(data), AnalysisValidator(lexicon), SOURCE)
    assert outcome.first_pass_ok and outcome.attempts == 1


def test_decimal_in_one_sentence_does_not_fake_second_sentence(lexicon: Lexicon) -> None:
    data = copy.deepcopy(VALID)
    data["summary"] = "성수동 카페 어니언의 밤 라떼 가격은 6.5천원입니다."
    with pytest.raises(AnalysisSchemaError) as caught:
        validate_and_repair(lambda _: raw(data), AnalysisValidator(lexicon), SOURCE, max_repairs=0)
    assert caught.value.details["issues"][0]["code"] == "summary_sentence_count"


def test_ellipsis_counts_as_one_sentence_boundary(lexicon: Lexicon) -> None:
    data = copy.deepcopy(VALID)
    data["summary"] = "밤 라떼가 출시되었습니다... 주말 오전에 성수동 매장을 방문할 수 있습니다."
    outcome = validate_and_repair(lambda _: raw(data), AnalysisValidator(lexicon), SOURCE)
    assert outcome.attempts == 1


def test_strict_types_reject_string_and_boolean_confidence() -> None:
    for value in ("0.9", True):
        invalid = copy.deepcopy(VALID)
        invalid["save_intent"]["confidence"] = value
        with pytest.raises(ValidationError):
            AnalysisOutput.model_validate(invalid)


def test_language_is_normalized_and_checked_against_iso_639_1(lexicon: Lexicon) -> None:
    data = copy.deepcopy(VALID)
    data["language"] = "KO"
    outcome = validate_and_repair(lambda _: raw(data), AnalysisValidator(lexicon), SOURCE)
    assert outcome.output.language == "ko"
    assert outcome.first_pass_ok
    assert any(issue.code == "language_normalized" for issue in outcome.issues)


def test_platform_only_tag_is_removed_without_reprompt(lexicon: Lexicon) -> None:
    data = copy.deepcopy(VALID)
    data["representative_tags"] = ["인스타그램", "성수동", "카페", "밤라떼"]
    outcome = validate_and_repair(lambda _: raw(data), AnalysisValidator(lexicon), SOURCE)
    assert outcome.output.representative_tags == ["성수동", "카페", "밤라떼"]
    assert any(issue.code == "tag_forbidden" for issue in outcome.issues)


def test_ungrounded_evidence_is_cleared_in_partial_output(lexicon: Lexicon) -> None:
    data = copy.deepcopy(VALID)
    data["evidence"] = [{"claim": "없는 주장", "source_span": "원문에 전혀 없는 근거"}]
    outcome = validate_and_repair(lambda _: raw(data), AnalysisValidator(lexicon), SOURCE, max_repairs=0)
    assert outcome.partial and outcome.output.evidence == []


def test_non_korean_summary_is_rejected(lexicon: Lexicon) -> None:
    data = copy.deepcopy(VALID)
    data["summary"] = "This is the first English sentence. This is the second English sentence."
    with pytest.raises(AnalysisSchemaError):
        validate_and_repair(lambda _: raw(data), AnalysisValidator(lexicon), SOURCE, max_repairs=0)


def test_refusal_stops_after_one_call_and_is_not_retryable_provider_error(lexicon: Lexicon) -> None:
    calls = 0

    def refuse(_: RepairContext | None) -> LLMRawResponse:
        nonlocal calls
        calls += 1
        return LLMRawResponse(text="", stop_reason="refusal")

    with pytest.raises(LLMRefusalError) as caught:
        validate_and_repair(refuse, AnalysisValidator(lexicon), SOURCE)
    assert calls == 1 and caught.value.code == "LLM_REFUSED"
    assert isinstance(caught.value, JupjupError)
    assert not isinstance(caught.value, ProviderError)


def test_materialized_save_intent_labels_take_priority_when_purpose_is_full() -> None:
    data = copy.deepcopy(VALID)
    data["detail_tags"]["purpose"] = ["첫째", "둘째", "셋째", "넷째", "다섯째"]
    output = AnalysisOutput.model_validate(data)
    assert output.materialized_detail_tags()["purpose"] == ["방문예정", "첫째", "둘째", "셋째", "넷째"]


def test_adversarial_llm_outputs_only_return_contract_outcomes(lexicon: Lexicon) -> None:
    rng = random.Random(20261101)
    corpus = ["", "{", "[]", "null", "NaN", '"문자열"']
    scalar_values: list[Any] = [None, True, False, 0, 1.5, "x", [], {}]
    keys = ["summary", "representative_tags", "detail_tags", "save_intent", "language", "unexpected"]
    for _ in range(40):
        payload = {rng.choice(keys): rng.choice(scalar_values) for _ in range(rng.randint(0, 8))}
        corpus.append(json.dumps(payload, ensure_ascii=False))
    # MT1-n: 파서·재귀 경로까지 건드리는 값(깊은 중첩, 큰 수, 서러게이트, 아주 긴 문자열)
    for _ in range(20):
        depth = rng.choice([1, 31, 33, 500, 2000])
        nested = "[" * depth + "]" * depth
        big_number = "9" * rng.choice([10, 4300, 4301, 20000])
        key = rng.choice(keys)
        corpus.append(f'{{"{key}": {nested}, "save_intent": {{"confidence": {big_number}}}}}')
    corpus.append(r'{"summary": "𐏿\ud800", "language": "ko"}')  # 짝 없는 서러게이트
    corpus.append(json.dumps({"summary": "가" * 200_000, "representative_tags": ["x" * 10_000] * 3}))

    validator = AnalysisValidator(lexicon)
    for text in corpus:
        try:
            outcome = validate_and_repair(lambda _, value=text: LLMRawResponse(text=value), validator, SOURCE)
        except AnalysisSchemaError:
            continue
        assert isinstance(outcome, RepairOutcome)


def test_direct_schema_rejects_enum_and_extra_fields() -> None:
    invalid = copy.deepcopy(VALID)
    invalid["save_intent"]["labels"] = ["데이트"]
    invalid["extra"] = True
    with pytest.raises(ValidationError):
        AnalysisOutput.model_validate(invalid)


# --- M1-n (T18 loop 2): 병적인 JSON도 계약 안의 결과만 낸다 ---


def _huge_int_payload() -> str:
    text = json.dumps(VALID, ensure_ascii=False)
    return text.replace('"confidence": 0.9', '"confidence": ' + "1" * 4301)


def _deep_topics_payload(depth: int) -> str:
    text = json.dumps(VALID, ensure_ascii=False)
    return text.replace('"topics": ["카페"]', '"topics": ' + "[" * depth + "]" * depth)


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param(_huge_int_payload(), id="int-4301-digits"),
        pytest.param(_deep_topics_payload(600), id="nested-600"),
        pytest.param(_deep_topics_payload(5000), id="nested-5000"),
        pytest.param(_deep_topics_payload(100_000), id="nested-100000"),
    ],
)
def test_pathological_json_becomes_validation_issue(lexicon: Lexicon, payload: str) -> None:
    validator = AnalysisValidator(lexicon)
    output, issues = validator.validate(payload, SOURCE)
    assert output is None
    assert issues and issues[0].code in {"json_parse", "json_depth"}
    assert validator.partial_output(payload, SOURCE) is None


@pytest.mark.parametrize("payload", [_huge_int_payload(), _deep_topics_payload(600)])
def test_pathological_json_then_valid_response_is_repaired(lexicon: Lexicon, payload: str) -> None:
    call, calls = scripted([LLMRawResponse(text=payload), raw(VALID)])
    outcome = validate_and_repair(call, AnalysisValidator(lexicon), SOURCE)
    assert outcome.attempts == 2 and outcome.repair_attempts == 1 and not outcome.partial
    assert calls[1] is not None


@pytest.mark.parametrize("payload", [_huge_int_payload(), _deep_topics_payload(600)])
def test_pathological_json_exhaustion_raises_schema_error(lexicon: Lexicon, payload: str) -> None:
    with pytest.raises(AnalysisSchemaError):
        validate_and_repair(lambda _: LLMRawResponse(text=payload), AnalysisValidator(lexicon), SOURCE)


def test_moderately_nested_valid_shape_still_reports_schema_issue_not_depth(lexicon: Lexicon) -> None:
    validator = AnalysisValidator(lexicon)
    output, issues = validator.validate(_deep_topics_payload(3), SOURCE)
    assert output is None
    assert all(issue.code != "json_depth" for issue in issues)

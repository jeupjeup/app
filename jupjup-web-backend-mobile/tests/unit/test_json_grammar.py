"""T25d: 디코딩 스키마(build_decoding_schema)와 문법 보정. 설계 5.2~5.3절."""

from __future__ import annotations

import copy
import json
import random
import re
from typing import Any

import jsonschema
import pytest

from jupjup.ingest.schemas import AnalysisOutput
from jupjup.providers import json_grammar as jg
from jupjup.providers.json_grammar import (
    ANALYSIS_DECODING_POLICY_DS1,
    SAFE_CHAR_RULE,
    UNSAFE_CHAR_RULE,
    DecodingPolicyMismatchError,
    DecodingSchemaPolicy,
    build_decoding_schema,
    canonical_inlined_schema,
    decoding_schema_fingerprint,
    decoding_schema_violations,
    enforce_json_string_char_rule,
)

DS1_ORDER = ["language", "title_suggestion", "evidence", "summary", "representative_tags", "detail_tags", "save_intent"]


def _walk(node: Any, path: str = "") -> list[tuple[str, dict[str, Any]]]:
    """(포인터, 스키마) 목록. 속성 맵 안의 이름은 키워드로 보지 않는다."""
    out: list[tuple[str, dict[str, Any]]] = []
    if isinstance(node, dict):
        out.append((path, node))
        for name, sub in node.get("properties", {}).items():
            out.extend(_walk(sub, f"{path}/properties/{name}"))
        if isinstance(node.get("items"), dict):
            out.extend(_walk(node["items"], f"{path}/items"))
        for key in ("anyOf", "oneOf", "allOf"):
            for index, sub in enumerate(node.get(key, [])):
                out.extend(_walk(sub, f"{path}/{key}/{index}"))
        if isinstance(node.get("additionalProperties"), dict):
            out.extend(_walk(node["additionalProperties"], f"{path}/additionalProperties"))
    return out


def test_ds1_matches_design_table() -> None:
    schema = build_decoding_schema(AnalysisOutput, ANALYSIS_DECODING_POLICY_DS1)
    props = schema["properties"]
    assert list(props) == DS1_ORDER
    assert props["evidence"]["maxItems"] == 6
    assert props["evidence"]["items"]["properties"]["source_span"]["maxLength"] == 120
    detail = props["detail_tags"]["properties"]
    assert {"attributes", "save_intent", "purpose"}.isdisjoint(detail)
    assert (detail["entities"]["maxItems"], detail["keywords"]["maxItems"], detail["topics"]["maxItems"]) == (10, 10, 5)
    assert detail["schema_version"] == {"const": 1}
    assert (props["summary"]["minLength"], props["summary"]["maxLength"]) == (20, 400)
    assert schema["required"] == AnalysisOutput.model_json_schema()["required"]
    text = json.dumps(schema)
    assert "$ref" not in text and "$defs" not in text
    for _, node in _walk(schema):
        assert jg.UNSUPPORTED_KEYWORDS.isdisjoint(node), node


def test_decoding_schema_is_deterministic_and_does_not_touch_canonical() -> None:
    before = json.dumps(AnalysisOutput.model_json_schema(), sort_keys=True)
    a = build_decoding_schema(AnalysisOutput, ANALYSIS_DECODING_POLICY_DS1)
    b = build_decoding_schema(AnalysisOutput, ANALYSIS_DECODING_POLICY_DS1)
    assert json.dumps(a, ensure_ascii=False) == json.dumps(b, ensure_ascii=False)
    assert decoding_schema_fingerprint(a) == decoding_schema_fingerprint(b)
    assert json.dumps(AnalysisOutput.model_json_schema(), sort_keys=True) == before
    reordered = ANALYSIS_DECODING_POLICY_DS1.model_copy(update={"property_order": {"": list(reversed(DS1_ORDER))}})
    assert decoding_schema_fingerprint(build_decoding_schema(AnalysisOutput, reordered)) != decoding_schema_fingerprint(
        a
    )


def test_ds1_is_equal_or_stricter_than_canonical() -> None:
    canonical = canonical_inlined_schema(AnalysisOutput)
    assert (
        decoding_schema_violations(build_decoding_schema(AnalysisOutput, ANALYSIS_DECODING_POLICY_DS1), canonical) == []
    )
    assert decoding_schema_violations(canonical, canonical) == []


def _bounded_paths(canonical: dict[str, Any]) -> tuple[list[tuple[str, int, int]], list[tuple[str, int, int]]]:
    arrays, strings = [], []
    for path, node in _walk(canonical):
        if node.get("type") == "array":
            arrays.append((path, node.get("minItems", 0), node.get("maxItems", 30)))
        if node.get("type") == "string":
            strings.append((path, node.get("minLength", 0), node.get("maxLength", 300)))
    return arrays, strings


def _optional_props(canonical: dict[str, Any]) -> list[str]:
    out = []
    for path, node in _walk(canonical):
        for name in node.get("properties", {}):
            if name not in node.get("required", []):
                out.append(f"{path}/properties/{name}")
    return out


@pytest.mark.parametrize("seed", range(40))
def test_random_policies_never_loosen(seed: int) -> None:
    """속성 테스트: 임의 정책은 ValueError이거나, 결과가 정본과 같거나 더 엄격하다."""
    rng = random.Random(20261102 + seed)
    canonical = canonical_inlined_schema(AnalysisOutput)
    arrays, strings = _bounded_paths(canonical)
    optional = _optional_props(canonical)
    max_items = {p: rng.randint(lo - 1, hi + 2) for p, lo, hi in rng.sample(arrays, k=rng.randint(0, len(arrays)))}
    max_length = {p: rng.randint(lo - 1, hi + 5) for p, lo, hi in rng.sample(strings, k=rng.randint(0, 6))}
    drops = rng.sample(optional, k=rng.randint(0, 3))
    if rng.random() < 0.3:  # 필수 필드 빼기도 시도한다
        drops.append("/properties/summary")
    policy = DecodingSchemaPolicy(max_items=max_items, max_length=max_length)
    # drop 경로가 서로 포함 관계면 뒤쪽이 없는 경로가 된다 → ValueError. 그것도 허용 결과다.
    policy = policy.model_copy(update={"drop_paths": drops})
    try:
        decoding = build_decoding_schema(AnalysisOutput, policy)
    except ValueError:
        return
    assert decoding_schema_violations(decoding, canonical) == []
    assert "/properties/summary" not in drops
    assert decoding["required"] == canonical["required"]


def _minimal_instance(schema: dict[str, Any]) -> Any:
    if "const" in schema:
        return schema["const"]
    if "enum" in schema:
        return schema["enum"][0]
    if "anyOf" in schema:
        return _minimal_instance(schema["anyOf"][0])
    kind = schema.get("type")
    if kind == "object":
        return {name: _minimal_instance(sub) for name, sub in schema.get("properties", {}).items()}
    if kind == "array":
        return [_minimal_instance(schema["items"]) for _ in range(schema.get("minItems", 0))]
    if kind == "string":
        return "가" * max(1, schema.get("minLength", 1))
    if kind == "number":
        return 0.5
    if kind == "integer":
        return 1
    if kind == "boolean":
        return True
    if kind == "null":
        return None
    raise AssertionError(schema)


def test_instance_valid_for_decoding_schema_is_valid_for_canonical() -> None:
    decoding = build_decoding_schema(AnalysisOutput, ANALYSIS_DECODING_POLICY_DS1)
    instance = _minimal_instance(decoding)
    jsonschema.validate(instance, decoding)
    jsonschema.validate(instance, AnalysisOutput.model_json_schema())
    AnalysisOutput.model_validate_json(json.dumps(instance, ensure_ascii=False))


@pytest.mark.parametrize(
    ("policy", "message"),
    [
        (DecodingSchemaPolicy(max_items={"/properties/evidence": 21}), "느슨"),
        (DecodingSchemaPolicy(max_items={"/properties/representative_tags": 2}), "minItems"),
        (DecodingSchemaPolicy(max_length={"/properties/summary": 401}), "느슨"),
        (DecodingSchemaPolicy(max_length={"/properties/evidence": 10}), "string"),
        (DecodingSchemaPolicy(drop_paths=["/properties/summary"]), "필수"),
        (DecodingSchemaPolicy(drop_paths=["/properties/detail_tags/properties/schema_version"]), "필수"),
        (DecodingSchemaPolicy(drop_paths=["/properties/nope"]), "없습니다"),
        (DecodingSchemaPolicy(drop_paths=["/evidence"]), "properties"),
        (DecodingSchemaPolicy(max_items={"/properties/nope": 1}), "없습니다"),
        (DecodingSchemaPolicy(property_order={"": ["summary", "summary"]}), "중복"),
        (DecodingSchemaPolicy(property_order={"": ["nope"]}), "없는"),
        (DecodingSchemaPolicy(max_items={"evidence": 1}), "/로 시작"),
    ],
)
def test_invalid_policies_raise(policy: DecodingSchemaPolicy, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        build_decoding_schema(AnalysisOutput, policy)


def test_violation_checker_detects_manual_loosening() -> None:
    canonical = canonical_inlined_schema(AnalysisOutput)
    cases: list[tuple[str, Any]] = [
        ("maxItems", lambda s: s["properties"]["evidence"].__setitem__("maxItems", 50)),
        ("maxLength", lambda s: s["properties"]["summary"].pop("maxLength")),
        ("minLength", lambda s: s["properties"]["summary"].__setitem__("minLength", 1)),
        ("required", lambda s: s["required"].remove("summary")),
        ("additionalProperties", lambda s: s.pop("additionalProperties")),
        ("enum", lambda s: s["properties"]["save_intent"]["properties"]["labels"]["items"]["enum"].append("새값")),
        ("type", lambda s: s["properties"]["language"].__setitem__("type", "integer")),
        ("정본에 없는", lambda s: s["properties"].__setitem__("extra", {"type": "string"})),
        ("const", lambda s: s["properties"]["detail_tags"]["properties"]["schema_version"].__setitem__("const", 2)),
    ]
    for expected, mutate in cases:
        loose = copy.deepcopy(canonical)
        mutate(loose)
        violations = decoding_schema_violations(loose, canonical)
        assert any(expected in v for v in violations), (expected, violations)


def test_l3_violation_checker_detects_required_property_removed_from_properties() -> None:
    canonical = canonical_inlined_schema(AnalysisOutput)
    decoding = build_decoding_schema(AnalysisOutput, ANALYSIS_DECODING_POLICY_DS1)
    required = canonical["required"][0]
    assert required in decoding["required"]
    decoding["properties"].pop(required)

    violations = decoding_schema_violations(decoding, canonical)

    assert any(f"필수 속성 {required} 빠짐" in violation for violation in violations)


# --- 정책 해시 ---------------------------------------------------------------------------------------------


def test_registered_policy_hash_matches_content() -> None:
    for version, policies in jg.DECODING_POLICY_SETS.items():
        assert jg.decoding_policy_set_hash(policies) == jg.DECODING_POLICY_HASHES[version]
        assert jg.policies_for_version(version) == policies


def test_policy_change_without_version_bump_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    changed = ANALYSIS_DECODING_POLICY_DS1.model_copy(update={"max_length": {}})
    monkeypatch.setitem(jg.DECODING_POLICY_SETS, "ds-1", {"AnalysisOutput": changed})
    with pytest.raises(DecodingPolicyMismatchError, match="decoding_schema_version을 올리고"):
        jg.policies_for_version("ds-1")


def test_policy_version_field_must_match() -> None:
    wrong = ANALYSIS_DECODING_POLICY_DS1.model_copy(update={"version": "ds-2"})
    with pytest.raises(DecodingPolicyMismatchError, match="version"):
        jg.verify_decoding_policies("ds-1", {"AnalysisOutput": wrong})
    with pytest.raises(DecodingPolicyMismatchError):
        jg.policies_for_version("ds-404")


# --- char 규칙 ---------------------------------------------------------------------------------------------


def test_char_rule_is_replaced_with_upstream_rule() -> None:
    grammar = 'root ::= string\nstring ::= "\\"" char* "\\"" space\n' + UNSAFE_CHAR_RULE + '\nspace ::= " "?'
    fixed = enforce_json_string_char_rule(grammar)
    assert UNSAFE_CHAR_RULE not in fixed and fixed.count(SAFE_CHAR_RULE) == 1
    assert fixed.replace(SAFE_CHAR_RULE, UNSAFE_CHAR_RULE) == grammar
    assert enforce_json_string_char_rule(fixed) == fixed
    assert enforce_json_string_char_rule("root ::= integer") == "root ::= integer"
    with pytest.raises(ValueError, match="char"):
        enforce_json_string_char_rule('char ::= [^"]')


def test_safe_char_rule_excludes_control_characters() -> None:
    # GBNF 문자 클래스 [^"\\\x7F\x00-\x1F]를 파이썬 정규식으로 옮겨 실제 문자를 넣어 본다.
    klass = SAFE_CHAR_RULE.split("::= ", 1)[1].split(" |", 1)[0]
    assert klass == '[^"\\\\\\x7F\\x00-\\x1F]'
    pattern = re.compile(klass)  # GBNF 문자 클래스 문법은 이 범위에서 파이썬 정규식과 같다
    for ch in ["\n", "\r", "\t", "\x00", "\x1f", "\x7f", '"', "\\"]:
        assert pattern.fullmatch(ch) is None, repr(ch)
    for ch in ["가", "a", " ", "~", "é"]:
        assert pattern.fullmatch(ch) is not None, repr(ch)


def test_ds1_analysis_decoding_schema_is_pinned() -> None:
    """정책 해시는 정책 내용만 본다. 변환 코드나 정본 스키마가 바뀌어 문법이 달라지면 여기서 드러난다.

    이 값이 바뀌면 decoding_schema_version을 올리고(녹화 키가 바뀐다) 새 값으로 고친다.
    """
    schema = build_decoding_schema(AnalysisOutput, ANALYSIS_DECODING_POLICY_DS1)
    assert decoding_schema_fingerprint(schema) == "77a70b38d23d45c79394b66061b4d4e97cf0c522e62b68ce1688fc6555749251"


def test_ds2_remains_strict_and_keeps_ds1_replay_policy() -> None:
    """A tuning policy must preserve canonical constraints and the old recording identity."""
    canonical = canonical_inlined_schema(AnalysisOutput)
    old = build_decoding_schema(AnalysisOutput, jg.policies_for_version("ds-1")["AnalysisOutput"])
    tuned = build_decoding_schema(AnalysisOutput, jg.policies_for_version("ds-2")["AnalysisOutput"])
    assert decoding_schema_violations(tuned, canonical) == []
    assert tuned["required"] == canonical["required"]
    assert old["properties"]["evidence"]["maxItems"] == 6
    assert decoding_schema_fingerprint(old) != decoding_schema_fingerprint(tuned)
    # Content changes under ds-2 must fail closed, as they do for ds-1.
    altered = jg.ANALYSIS_DECODING_POLICY_DS2.model_copy(update={"max_items": {}})
    with pytest.raises(DecodingPolicyMismatchError):
        jg.verify_decoding_policies("ds-2", {"AnalysisOutput": altered})


@pytest.mark.parametrize(
    "value", ['한글 "인용" 문장.', '경로 C:\\notes\\new', '첫 줄\n다음 줄\t끝', '별빛 🌟', 3, None]
)
def test_gbnf_json_constant_escapes_both_literal_layers(value: Any) -> None:
    literal = jg.gbnf_json_constant(value)
    assert json.loads(json.loads(literal)) == value
    assert '\n' not in literal and '\t' not in literal

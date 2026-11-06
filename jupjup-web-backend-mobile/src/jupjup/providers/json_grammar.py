"""디코딩 전용 JSON Schema와 문법 문자열 보정 (설계 ``design_local_analyzer.md`` 5.2~5.3절).

순수 함수만 둔다. llama_cpp를 import하지 않으므로 기본 설치에서도 테스트된다.

- 검증 스키마(정본, ``model_json_schema()``)는 바꾸지 않는다. ``build_decoding_schema``는 정본을 복사해
  ``$ref`` 인라인, 문법 변환기가 모르는 키워드 제거, 필드 빼기·상한 줄이기·필드 순서 바꾸기를 한다.
  결과는 항상 정본과 **같거나 더 엄격**하다. 느슨해지는 정책은 ``ValueError``다.
- 디코딩 정책을 바꾸면 ``DECODING_SCHEMA_VERSION``(프로필의 ``decoding_schema_version``)을 올려야 한다.
  ``DECODING_POLICY_HASHES``에 버전별 정책 내용 해시를 고정해, 버전을 안 올리고 정책만 바꾸면 시작 시 실패한다.
- llama-cpp-python 0.3.36의 스키마 → 문법 변환기는 문자열 ``char`` 규칙에서 원시 제어 문자(``\\x00-\\x1F``)를
  막지 않는다 (T25b 4.4절). ``enforce_json_string_char_rule``이 upstream llama.cpp와 같은 규칙으로 바꾼다.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

DECODING_SCHEMA_VERSION = "ds-1"

# 문법 변환기가 쓰지 않거나 지원하지 않는 키워드. 스키마 키워드 위치에서만 지운다 (속성 이름은 건드리지 않는다).
UNSUPPORTED_KEYWORDS = frozenset({"$schema", "$id", "title", "description", "maxProperties", "format"})
_NAMED_MAPS = frozenset({"properties", "patternProperties", "$defs", "definitions", "dependentSchemas"})
_UPPER_BOUNDS = ("maxItems", "maxLength", "maximum", "exclusiveMaximum")
_LOWER_BOUNDS = ("minItems", "minLength", "minimum", "exclusiveMinimum")


class DecodingSchemaPolicy(BaseModel):
    """디코딩 스키마 조정 규칙. 경로는 ``$ref``를 인라인한 스키마 기준 JSON 포인터다 (루트는 ``""``)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str = DECODING_SCHEMA_VERSION
    property_order: dict[str, list[str]] = Field(default_factory=dict)
    drop_paths: list[str] = Field(default_factory=list)
    max_items: dict[str, int] = Field(default_factory=dict)
    max_length: dict[str, int] = Field(default_factory=dict)

    def content_hash(self) -> str:
        return _canonical_sha256(self.model_dump(mode="json"), sort_keys=True)


ANALYSIS_DECODING_POLICY_DS1 = DecodingSchemaPolicy(
    version="ds-1",
    # 근거 구절을 먼저 뽑고 요약을 쓰게 한다. 검증은 필드 이름으로 하므로 순서와 무관하다.
    property_order={
        "": [
            "language",
            "title_suggestion",
            "evidence",
            "summary",
            "representative_tags",
            "detail_tags",
            "save_intent",
        ]
    },
    # save_intent·purpose는 materialized_detail_tags()가 채운다. attributes는 소형 모델 잡음이 크다.
    drop_paths=[
        "/properties/detail_tags/properties/attributes",
        "/properties/detail_tags/properties/save_intent",
        "/properties/detail_tags/properties/purpose",
    ],
    max_items={
        "/properties/evidence": 6,
        "/properties/detail_tags/properties/entities": 10,
        "/properties/detail_tags/properties/keywords": 10,
        "/properties/detail_tags/properties/topics": 5,
    },
    max_length={"/properties/evidence/items/properties/source_span": 120},
)

# T25t: shorter grounded output without changing the validation schema or ds-1 replays.
ANALYSIS_DECODING_POLICY_DS2 = ANALYSIS_DECODING_POLICY_DS1.model_copy(
    update={
        "version": "ds-2",
        "max_items": {
            **ANALYSIS_DECODING_POLICY_DS1.max_items,
            "/properties/evidence": 4,
            "/properties/detail_tags/properties/topics": 3,
            "/properties/detail_tags/properties/keywords": 6,
        },
        "max_length": {
            **ANALYSIS_DECODING_POLICY_DS1.max_length,
            "/properties/evidence/items/properties/claim": 80,
        },
    }
)

ANALYSIS_DECODING_POLICY_DS3 = ANALYSIS_DECODING_POLICY_DS2.model_copy(
    update={
        "version": "ds-3",
        "property_order": {
            **ANALYSIS_DECODING_POLICY_DS2.property_order,
            "/properties/evidence/items": ["source_span", "claim"],
        },
        "max_items": {
            **ANALYSIS_DECODING_POLICY_DS2.max_items,
            "/properties/evidence": 3,
            "/properties/representative_tags": 5,
        },
        "max_length": {
            **ANALYSIS_DECODING_POLICY_DS2.max_length,
            "/properties/evidence/items/properties/claim": 60,
        },
    }
)

# 버전 → {스키마 클래스 이름 → 정책}. 등록되지 않은 스키마는 빈 정책(정본 그대로, 키워드 정리만)을 쓴다.
DECODING_POLICY_SETS: dict[str, dict[str, DecodingSchemaPolicy]] = {
    "ds-1": {"AnalysisOutput": ANALYSIS_DECODING_POLICY_DS1},
    "ds-2": {"AnalysisOutput": ANALYSIS_DECODING_POLICY_DS2},
    "ds-3": {"AnalysisOutput": ANALYSIS_DECODING_POLICY_DS3},
}

# 버전별 정책 내용 해시 (decoding_policy_set_hash). 정책을 바꾸면 새 버전을 만들고 여기에 새 해시를 더한다.
DECODING_POLICY_HASHES: dict[str, str] = {
    "ds-3": "e895dd892adc0aed1af7cb4148749ed1e3573edccebfc8d02159d44643c4c2b2",
    "ds-2": "4aa4a94fbff6d8fed9f4159876edbe443e9a64b1ff3e1da7095103483d534de0",
    "ds-1": "fade30e97ed5e8fe932e137732295753438fc443eda560db7c8dfac217b41174",
}


class DecodingPolicyMismatchError(ValueError):
    """디코딩 정책 내용이 버전에 등록된 해시와 다르다 (버전을 올리지 않고 정책을 바꿨다)."""


def _canonical_sha256(value: Any, *, sort_keys: bool) -> str:
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=sort_keys)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def decoding_policy_set_hash(policies: Mapping[str, DecodingSchemaPolicy]) -> str:
    return _canonical_sha256(
        {name: policy.model_dump(mode="json") for name, policy in sorted(policies.items())}, sort_keys=True
    )


def policies_for_version(version: str) -> dict[str, DecodingSchemaPolicy]:
    """등록된 정책 묶음을 돌려주고 해시를 검사한다. 모르는 버전이나 해시 불일치는 ``DecodingPolicyMismatchError``."""
    if version not in DECODING_POLICY_SETS:
        raise DecodingPolicyMismatchError(f"등록되지 않은 디코딩 스키마 버전입니다: {version}")
    policies = dict(DECODING_POLICY_SETS[version])
    verify_decoding_policies(version, policies)
    return policies


def verify_decoding_policies(version: str, policies: Mapping[str, DecodingSchemaPolicy]) -> None:
    expected = DECODING_POLICY_HASHES.get(version)
    if expected is None:
        raise DecodingPolicyMismatchError(f"디코딩 정책 해시가 등록되지 않은 버전입니다: {version}")
    wrong_version = sorted(name for name, policy in policies.items() if policy.version != version)
    if wrong_version:
        raise DecodingPolicyMismatchError(f"정책 version이 {version}이 아닙니다: {', '.join(wrong_version)}")
    actual = decoding_policy_set_hash(policies)
    if actual != expected:
        raise DecodingPolicyMismatchError(
            f"디코딩 정책 {version}의 내용이 바뀌었습니다 (등록 {expected[:12]}, 현재 {actual[:12]}). "
            "정책을 바꿨으면 decoding_schema_version을 올리고 새 해시를 등록하세요"
        )


# --- 디코딩 스키마 -----------------------------------------------------------------------------------------


def build_decoding_schema(schema: type[BaseModel], policy: DecodingSchemaPolicy) -> dict[str, Any]:
    """정본 스키마에서 디코딩 전용 스키마를 만든다. 같은 입력이면 같은 dict(키 순서 포함)를 돌려준다."""
    canonical = canonical_inlined_schema(schema)
    decoding = copy.deepcopy(canonical)
    for path in policy.drop_paths:
        _drop(decoding, path)
    for path, limit in policy.max_items.items():
        _tighten(decoding, path, "maxItems", "minItems", limit)
    for path, limit in policy.max_length.items():
        _tighten(decoding, path, "maxLength", "minLength", limit)
    for path, order in policy.property_order.items():
        _reorder(decoding, path, order)
    violations = decoding_schema_violations(decoding, canonical)
    if violations:
        raise ValueError("디코딩 스키마가 정본보다 느슨합니다: " + "; ".join(violations))
    return decoding


def canonical_inlined_schema(schema: type[BaseModel]) -> dict[str, Any]:
    """정본 JSON Schema의 ``$ref``를 인라인하고 지원하지 않는 키워드를 지운 것 (비교 기준)."""
    raw = copy.deepcopy(schema.model_json_schema())
    defs = raw.pop("$defs", {})
    if not isinstance(defs, dict):
        raise ValueError("$defs가 객체가 아닙니다")
    inlined = _inline(raw, defs, ())
    cleaned = _strip_keywords(inlined)
    if not isinstance(cleaned, dict):
        raise ValueError("스키마 루트가 객체가 아닙니다")
    return cleaned


def decoding_schema_fingerprint(decoding_schema: Mapping[str, Any]) -> str:
    """디코딩 스키마 지문. 필드 순서가 문법 출력 순서를 바꾸므로 키 순서를 보존해 해시한다."""
    return _canonical_sha256(decoding_schema, sort_keys=False)


def _inline(node: Any, defs: dict[str, Any], stack: tuple[str, ...]) -> Any:
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str):
            prefix = "#/$defs/"
            if not ref.startswith(prefix):
                raise ValueError(f"로컬 $defs 밖의 $ref는 지원하지 않습니다: {ref}")
            name = ref[len(prefix) :]
            if name in stack:
                raise ValueError(f"순환 $ref는 지원하지 않습니다: {name}")
            if name not in defs:
                raise ValueError(f"없는 $ref입니다: {ref}")
            siblings = {key: value for key, value in node.items() if key != "$ref"}
            target = _inline(copy.deepcopy(defs[name]), defs, (*stack, name))
            if siblings:
                if not isinstance(target, dict):
                    raise ValueError(f"$ref 대상이 객체가 아닙니다: {ref}")
                target = {**target, **_inline(siblings, defs, stack)}
            return target
        return {key: _inline(value, defs, stack) for key, value in node.items()}
    if isinstance(node, list):
        return [_inline(item, defs, stack) for item in node]
    return node


def _strip_keywords(node: Any, *, named: bool = False) -> Any:
    if isinstance(node, dict):
        if named:
            return {key: _strip_keywords(value) for key, value in node.items()}
        return {
            key: _strip_keywords(value, named=key in _NAMED_MAPS)
            for key, value in node.items()
            if key not in UNSUPPORTED_KEYWORDS and key != "$defs"
        }
    if isinstance(node, list):
        return [_strip_keywords(item) for item in node]
    return node


def _split_pointer(path: str) -> list[str]:
    if path == "":
        return []
    if not path.startswith("/"):
        raise ValueError(f"JSON 포인터는 /로 시작해야 합니다: {path!r}")
    return [part.replace("~1", "/").replace("~0", "~") for part in path[1:].split("/")]


def _resolve(root: dict[str, Any], parts: list[str], path: str) -> Any:
    node: Any = root
    for part in parts:
        if isinstance(node, dict) and part in node:
            node = node[part]
        elif isinstance(node, list) and part.isdigit() and int(part) < len(node):
            node = node[int(part)]
        else:
            raise ValueError(f"디코딩 정책 경로가 스키마에 없습니다: {path}")
    return node


def _drop(root: dict[str, Any], path: str) -> None:
    parts = _split_pointer(path)
    if len(parts) < 2 or parts[-2] != "properties":
        raise ValueError(f"drop_paths는 .../properties/<이름> 꼴이어야 합니다: {path}")
    owner = _resolve(root, parts[:-2], path)
    properties = owner.get("properties") if isinstance(owner, dict) else None
    name = parts[-1]
    if not isinstance(properties, dict) or name not in properties:
        raise ValueError(f"디코딩 정책 경로가 스키마에 없습니다: {path}")
    if name in owner.get("required", []):
        raise ValueError(f"필수 필드는 디코딩에서 뺄 수 없습니다: {path}")
    del properties[name]


def _tighten(root: dict[str, Any], path: str, upper: str, lower: str, limit: int) -> None:
    node = _resolve(root, _split_pointer(path), path)
    if not isinstance(node, dict):
        raise ValueError(f"디코딩 정책 경로가 스키마 객체가 아닙니다: {path}")
    expected_type = "array" if upper == "maxItems" else "string"
    if node.get("type") != expected_type:
        raise ValueError(f"{upper}는 {expected_type} 스키마에만 줄 수 있습니다: {path}")
    current = node.get(upper)
    if isinstance(current, int) and limit > current:
        raise ValueError(f"{upper}를 정본({current})보다 느슨하게({limit}) 바꿀 수 없습니다: {path}")
    minimum = node.get(lower, 0)
    if limit < minimum:
        raise ValueError(f"{upper}({limit})가 {lower}({minimum})보다 작습니다: {path}")
    node[upper] = limit


def _reorder(root: dict[str, Any], path: str, order: list[str]) -> None:
    node = _resolve(root, _split_pointer(path), path)
    properties = node.get("properties") if isinstance(node, dict) else None
    if not isinstance(properties, dict):
        raise ValueError(f"property_order 경로가 객체 스키마가 아닙니다: {path!r}")
    unknown = [name for name in order if name not in properties]
    if unknown or len(set(order)) != len(order):
        raise ValueError(f"property_order에 없는 필드나 중복이 있습니다: {path!r} {unknown}")
    rest = [name for name in properties if name not in order]
    node["properties"] = {name: properties[name] for name in [*order, *rest]}


def decoding_schema_violations(decoding: Any, canonical: Any, path: str = "") -> list[str]:
    """``decoding``이 ``canonical``보다 느슨한 곳을 찾는다. 빈 목록이면 같거나 더 엄격하다.

    규칙: 타입·enum·const·additionalProperties는 같거나 좁아야 하고, required는 정본을 모두 포함해야 하며, 정본에 없는
    속성을 더할 수 없다. 상한(max*)은 같거나 작고, 하한(min*)은 같거나 커야 한다.
    """
    here = path or "/"
    if not isinstance(canonical, dict):
        return [] if decoding == canonical else [f"{here}: 값이 다름"]
    if not isinstance(decoding, dict):
        return [f"{here}: 스키마 객체가 아님"]
    out: list[str] = []
    for key in ("type", "const"):
        if key in canonical and decoding.get(key) != canonical[key]:
            out.append(f"{here}: {key} 다름")
    const_outside_enum = "const" in decoding and "enum" in canonical and decoding["const"] not in canonical["enum"]
    if const_outside_enum and "const" not in canonical:
        out.append(f"{here}: const가 정본 enum 밖")
    if "enum" in canonical:
        enum = decoding.get("enum")
        if enum is None and "const" not in decoding:
            out.append(f"{here}: enum 빠짐")
        elif enum is not None and not set(map(json.dumps, enum)) <= set(map(json.dumps, canonical["enum"])):
            out.append(f"{here}: enum이 정본보다 넓음")
    for key in _UPPER_BOUNDS:
        if key in canonical and not (key in decoding and decoding[key] <= canonical[key]):
            out.append(f"{here}: {key} 느슨함")
    for key in _LOWER_BOUNDS:
        if key in canonical and not (key in decoding and decoding[key] >= canonical[key]):
            out.append(f"{here}: {key} 느슨함")
    canonical_ap = canonical.get("additionalProperties")
    if canonical_ap is False and decoding.get("additionalProperties") is not False:
        out.append(f"{here}: additionalProperties 열림")
    elif isinstance(canonical_ap, dict):
        out.extend(
            decoding_schema_violations(
                decoding.get("additionalProperties"), canonical_ap, f"{path}/additionalProperties"
            )
        )
    if not set(canonical.get("required", [])).issubset(decoding.get("required", [])):
        out.append(f"{here}: required 다름")
    canonical_props = canonical.get("properties", {})
    decoding_props = decoding.get("properties", {})
    for name in decoding.get("required", []):
        if name not in decoding_props:
            out.append(f"{here}: 필수 속성 {name} 빠짐")
    for name in canonical.get("required", []):
        if name in canonical_props and name not in decoding_props:
            out.append(f"{here}: 필수 속성 {name} 빠짐")
    for name, sub in decoding_props.items():
        if name not in canonical_props:
            out.append(f"{here}: 정본에 없는 속성 {name}")
            continue
        out.extend(decoding_schema_violations(sub, canonical_props[name], f"{path}/properties/{name}"))
    if "items" in canonical:
        out.extend(decoding_schema_violations(decoding.get("items"), canonical["items"], f"{path}/items"))
    for key in ("anyOf", "oneOf", "allOf"):
        if key in canonical:
            mine = decoding.get(key)
            if not isinstance(mine, list) or len(mine) != len(canonical[key]):
                out.append(f"{here}: {key} 다름")
                continue
            for index, (sub_d, sub_c) in enumerate(zip(mine, canonical[key], strict=True)):
                out.extend(decoding_schema_violations(sub_d, sub_c, f"{path}/{key}/{index}"))
    return out


# --- 문법 문자열 보정 ---------------------------------------------------------------------------------------

# llama-cpp-python 0.3.36 SchemaConverter가 내는 규칙 (제어 문자 허용)과 upstream llama.cpp 규칙.
UNSAFE_CHAR_RULE = 'char ::= [^"\\\\] | "\\\\" (["\\\\/bfnrt] | "u" [0-9a-fA-F] [0-9a-fA-F] [0-9a-fA-F] [0-9a-fA-F])'
SAFE_CHAR_RULE = (
    'char ::= [^"\\\\\\x7F\\x00-\\x1F] | "\\\\" (["\\\\/bfnrt] | "u" [0-9a-fA-F] [0-9a-fA-F] [0-9a-fA-F] [0-9a-fA-F])'
)


def gbnf_json_constant(value: Any) -> str:
    """Escape JSON content and then its GBNF literal (quotes/backslashes need both)."""
    return json.dumps(json.dumps(value, ensure_ascii=False), ensure_ascii=False)


def enforce_json_string_char_rule(grammar: str) -> str:
    """문법의 ``char`` 규칙을 제어 문자를 막는 upstream 규칙으로 바꾼다. 모르는 ``char`` 규칙이면 ``ValueError``."""
    lines = grammar.split("\n")
    out: list[str] = []
    for line in lines:
        if line.startswith("char ::="):
            if line not in (UNSAFE_CHAR_RULE, SAFE_CHAR_RULE):
                raise ValueError("알 수 없는 문법 char 규칙입니다 (llama-cpp-python 버전 확인 필요)")
            line = SAFE_CHAR_RULE
        out.append(line)
    return "\n".join(out)

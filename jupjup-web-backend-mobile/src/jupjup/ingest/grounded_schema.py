"""Request-local literal evidence choices for the experimental ds-3 analyzer.

Only the current input (or the source sentences already supplied to reduce) is
used. Choices are not written to recordings: the existing schema fingerprint
hashes them. Bump POLICY_VERSION when changing the selection algorithm.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Sequence
from typing import Any, cast

from jupjup.domain.errors import AnalysisSchemaError
from jupjup.eval.judge import split_sentences
from jupjup.ingest.schemas import AnalysisOutput
from jupjup.ingest.validation import injection_payloads
from jupjup.text.normalize import normalize_text

GROUNDED_DECODING_VERSION = "ds-3"
POLICY_VERSION = "source-enum-1"
MAX_CANDIDATES = 64
SPAN_CHARS = 120
STRIDE_CHARS = 100
REQUIRED_DETAIL_FIELDS = ("schema_version", "category", "topics", "keywords", "locations", "entities")
_CONTROL = re.compile(r"[<\[\uff1c][|\uff5c]")


def grounding_policy() -> dict[str, Any]:
    """Parameters included in the frozen config only for ds-3 (old hashes stay intact)."""
    return {
        "version": POLICY_VERSION,
        "max_candidates": MAX_CANDIDATES,
        "span_chars": SPAN_CHARS,
        "stride_chars": STRIDE_CHARS,
        "selection": "source-order-even-sample",
        "adjacent_sentence_pairs": True,
        "require_normalized_literal_match": True,
        "deduplicate_valid_intent_labels": True,
        "exclude_control_tokens_and_injection_payloads": True,
        "required_detail_fields": list(REQUIRED_DETAIL_FIELDS),
    }


def evidence_choices(source_text: str, pieces: Sequence[str] | None = None) -> list[str]:
    """Bounded, deterministic, literal substrings; long sentences use overlapping windows."""
    payloads = [normalize_text(value) for value in injection_payloads(source_text)]
    normalized_source = normalize_text(source_text)
    choices: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        span = value.strip()
        normalized = normalize_text(span)
        if not normalized or span not in source_text or normalized not in normalized_source or _CONTROL.search(span):
            return
        if any(payload and payload in normalized for payload in payloads):
            return
        if span not in seen:
            seen.add(span)
            choices.append(span)

    for piece in pieces if pieces is not None else [source_text]:
        sentences = split_sentences(piece)
        cursor = 0
        for index, sentence in enumerate(sentences):
            offset = piece.find(sentence, cursor)
            cursor = offset + len(sentence)
            starts = [0] if len(sentence) <= SPAN_CHARS else list(range(0, len(sentence), STRIDE_CHARS))
            for start in starts:
                add(sentence[start : start + SPAN_CHARS])
            if offset >= 0 and index + 1 < len(sentences):
                following = sentences[index + 1]
                following_offset = piece.find(following, cursor)
                if following_offset >= 0:
                    pair = piece[offset : following_offset + len(following)]
                    if len(pair) <= SPAN_CHARS:
                        add(pair)
    if len(choices) > MAX_CANDIDATES:
        last = len(choices) - 1
        choices = [choices[index * last // (MAX_CANDIDATES - 1)] for index in range(MAX_CANDIDATES)]
    return choices


def grounded_analysis_schema(source_text: str, pieces: Sequence[str] | None = None) -> type[AnalysisOutput]:
    """Tighten the decoding schema without mutating the canonical validation model."""
    choices = evidence_choices(source_text, pieces)
    if not choices:
        raise AnalysisSchemaError("문법에 사용할 원문 근거 구절이 없습니다", {"kind": "grounded_schema"})
    schema = AnalysisOutput.model_json_schema()
    schema["$defs"]["Evidence"]["properties"]["source_span"]["enum"] = choices
    detail = schema["$defs"]["DetailTagsV1"]
    detail["required"] = list(dict.fromkeys([*detail.get("required", []), *REQUIRED_DETAIL_FIELDS]))

    def model_json_schema(cls: type[AnalysisOutput], *args: Any, **kwargs: Any) -> dict[str, Any]:
        del cls, args, kwargs
        return copy.deepcopy(schema)

    # The provider's registered decoding policy is keyed by schema name. The
    # request fingerprint includes the full enum, so distinct inputs cannot hit
    # another input's recording even though the schema name remains unchanged.
    return cast(
        type[AnalysisOutput],
        type(
            "AnalysisOutput",
            (AnalysisOutput,),
            {"__module__": __name__, "model_json_schema": classmethod(model_json_schema)},
        ),
    )

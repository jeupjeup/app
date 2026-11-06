"""Handwritten v3 examples must satisfy the same grammar and validator as model output."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from jupjup.ingest.analyzer import PromptStore
from jupjup.ingest.grounded_schema import grounded_analysis_schema
from jupjup.ingest.schemas import AnalysisOutput
from jupjup.ingest.validation import AnalysisValidator
from jupjup.providers.json_grammar import build_decoding_schema, policies_for_version
from jupjup.text.lexicon import Lexicon


@pytest.mark.parametrize("version", ["v3", "v3b", "v3c"])
def test_handwritten_examples_pass_real_validation(version: str) -> None:
    validator = AnalysisValidator(Lexicon.load(Path(__file__).resolve().parents[2] / "data/lexicon"))
    schema = build_decoding_schema(AnalysisOutput, policies_for_version("ds-2")["AnalysisOutput"])
    system = PromptStore().load(f"analyze_local_{version}").system
    source = ""
    examples = 0
    for line in system.splitlines():
        if line.startswith("원문: "):
            source = line.removeprefix("원문: ")
        if line.startswith("출력: "):
            payload = line.removeprefix("출력: ")
            decoding = (
                build_decoding_schema(grounded_analysis_schema(source), policies_for_version("ds-3")["AnalysisOutput"])
                if version == "v3c"
                else schema
            )
            jsonschema.validate(json.loads(payload), decoding)
            output, issues = validator.validate(payload, source)
            assert output is not None and not any(not issue.fixable for issue in issues), issues
            examples += 1
    assert examples >= 1

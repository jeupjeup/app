"""T25d 실제 모델 테스트 (기본 제외: ``-m local_llm``).

필요: ``uv sync --extra analyze-local``, ``JUPJUP_ANALYZER_CACHE_DIR``에 Kanana-1.5-2.1B Q4_K_M GGUF
(``gguf/kanana-1.5-2.1b-instruct-q4km/kanana-1.5-2.1b-instruct-2505-Q4_K_M.gguf``).

    JUPJUP_ANALYZER_CACHE_DIR=/path/to/models uv run --extra analyze-local pytest -m local_llm
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict, Field

from jupjup.ingest.profiles import AnalyzerProfiles
from jupjup.ingest.schemas import AnalysisOutput
from jupjup.providers.json_grammar import SAFE_CHAR_RULE, UNSAFE_CHAR_RULE
from jupjup.providers.llm_local import LlamaCppLLM, llama_runtime_info

REPO = Path(__file__).resolve().parents[2]
MODEL_ID = "kanana-1.5-2.1b-instruct-q4km"


@pytest.mark.local_llm
def test_kanana_matches_spike_and_grammar_blocks_raw_newlines() -> None:
    cache = os.environ.get("JUPJUP_ANALYZER_CACHE_DIR")
    if not cache:
        pytest.fail("JUPJUP_ANALYZER_CACHE_DIR가 필요합니다")
    info = llama_runtime_info()
    assert info["installed"] and info["llama_cpp_python"] == "0.3.36", info

    from llama_cpp import llama_grammar  # 실제 변환기가 아직 제어 문자를 허용하는지 (보정이 실제로 일하는지)

    converter = llama_grammar.SchemaConverter(prop_order={}, allow_fetch=False, dotall=False, raw_pattern=False)
    converter.visit({"type": "string"}, "")
    assert UNSAFE_CHAR_RULE in converter.format_grammar().split("\n")

    profiles = AnalyzerProfiles.load(REPO / "config" / "analyzer_profiles.yaml")
    profile = profiles.profiles["local-kanana-2b"]
    llm = LlamaCppLLM(profiles.models[MODEL_ID], profile.decoding, Path(cache))
    llm.warm_up([AnalysisOutput, Note])

    # T25b 스파이크 입력 syn-01 (패치 문법 결과와 바이트 동일해야 한다)
    inputs = json.loads((REPO / "scripts/spikes/results/inputs.json").read_text(encoding="utf-8"))
    spike = json.loads((REPO / f"scripts/spikes/results/{MODEL_ID}.patched.json").read_text(encoding="utf-8"))
    item = inputs["items"][0]
    expected = next(row for row in spike["passes"]["grammar_a"] if row["id"] == item["id"])
    tokens = llm.count_tokens(item["system"], item["user"])
    raw = llm.complete_json(item["system"], item["user"], AnalysisOutput, timeout_s=120, max_tokens=1536)
    assert raw.text == expected["content"]
    assert raw.input_tokens == tokens == expected["prompt_tokens"]
    assert raw.stop_reason == "end_turn"

    # 줄바꿈 토큰을 logit_bias로 강하게 밀어도, 보정한 문법은 원시 제어 문자를 막는다 (T25b 남은 문제 3).
    # 대조군: 0.3.36 원래 char 규칙 문법은 같은 조건에서 원시 줄바꿈을 내고 JSON 파싱이 깨진다.
    model, runtime = llm._ensure_loaded()
    newline = model.tokenize(b"\n", add_bos=False, special=False)[-1]
    patched = llm._grammar_for(runtime, Note)
    unpatched = runtime.module.LlamaGrammar.from_string(
        patched._grammar.replace(SAFE_CHAR_RULE, UNSAFE_CHAR_RULE), verbose=False
    )
    prompt = llm._render(model, "Write a JSON note.", "Write a short note.")
    outputs = {}
    for name, grammar in (("unpatched", unpatched), ("patched", patched)):
        model.reset()
        out = model.create_completion(
            prompt=prompt.tokens,
            max_tokens=30,
            temperature=0.0,
            top_k=1,
            top_p=1.0,
            min_p=0.0,
            repeat_penalty=1.0,
            seed=1,
            stop=prompt.stop,
            grammar=grammar,
            logit_bias={newline: 50.0},
        )
        outputs[name] = out["choices"][0]["text"]
    assert "\n" in outputs["unpatched"]
    assert not any(ord(ch) < 0x20 for ch in outputs["patched"])
    Note.model_validate_json(outputs["patched"])
    llm.close()


class Note(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(max_length=40)

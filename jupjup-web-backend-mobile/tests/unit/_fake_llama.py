"""테스트용 가짜 ``llama_cpp`` 패키지. 실제 llama-cpp-python 0.3.36이 쓰는 API 모양만 흉내 낸다."""

from __future__ import annotations

import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from types import ModuleType
from typing import Any

import pytest

from jupjup.providers.json_grammar import UNSAFE_CHAR_RULE


class StoppingCriteriaList(list[Callable[[Any, Any], bool]]):
    def __call__(self, input_ids: Any, logits: Any) -> bool:
        return any([criteria(input_ids, logits) for criteria in self])


@dataclass
class Script:
    """create_completion 한 번의 응답 각본."""

    text: str = '{"ok": true}'
    finish_reason: str | None = "stop"
    tokens: int = 3
    sleep_s: float = 0.0
    raises: BaseException | None = None


@dataclass
class FakeState:
    loads: list[dict[str, Any]] = field(default_factory=list)
    grammars: list[str] = field(default_factory=list)
    completions: list[dict[str, Any]] = field(default_factory=list)
    resets: int = 0
    closes: int = 0
    active: int = 0
    max_active: int = 0
    scripts: list[Script] = field(default_factory=list)
    default: Script = field(default_factory=Script)
    load_error: BaseException | None = None
    metadata: dict[str, str] = field(default_factory=lambda: {"tokenizer.chat_template": "{{ fake }}"})
    lock: threading.Lock = field(default_factory=threading.Lock)


class _FakeVocab:
    def token_get_text(self, token_id: int) -> str:
        return {1: "<s>", 2: "</s>"}.get(token_id, "")


def build_fake_llama(state: FakeState) -> dict[str, ModuleType]:
    root = ModuleType("llama_cpp")
    grammar_mod = ModuleType("llama_cpp.llama_grammar")
    chat_mod = ModuleType("llama_cpp.llama_chat_format")

    class LlamaGrammar:
        def __init__(self, text: str) -> None:
            self.text = text

        @classmethod
        def from_string(cls, grammar: str, verbose: bool = True) -> LlamaGrammar:
            state.grammars.append(grammar)
            return cls(grammar)

    class SchemaConverter:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs
            self.rules: list[str] = []

        def resolve_refs(self, schema: dict[str, Any], url: str) -> dict[str, Any]:
            return schema

        def visit(self, schema: dict[str, Any], name: str) -> None:
            props = ",".join(schema.get("properties", {}))
            self.rules = [UNSAFE_CHAR_RULE, f'root ::= "{props}"']

        def format_grammar(self) -> str:
            return "\n".join(self.rules)

    @dataclass
    class ChatFormatterResponse:
        prompt: str
        stop: list[str]
        stopping_criteria: Any
        added_special: bool = True

    class Jinja2ChatFormatter:
        def __init__(self, template: str, eos_token: str, bos_token: str, stop_token_ids: list[int]) -> None:
            self.eos_token = eos_token
            self.bos_token = bos_token
            self.stop_token_ids = set(stop_token_ids)

        def __call__(self, *, messages: list[dict[str, str]], **kwargs: Any) -> ChatFormatterResponse:
            prompt = self.bos_token + "".join(f"[{m['role']}]{m['content']}" for m in messages) + "[assistant]"

            def stop_on_last_token(tokens: Any, logits: Any) -> bool:
                return bool(tokens) and tokens[-1] in self.stop_token_ids

            return ChatFormatterResponse(
                prompt=prompt, stop=[self.eos_token], stopping_criteria=StoppingCriteriaList([stop_on_last_token])
            )

    class Llama:
        def __init__(self, **kwargs: Any) -> None:
            if state.load_error is not None:
                raise state.load_error
            state.loads.append(kwargs)
            self.metadata = dict(state.metadata)
            self._model = _FakeVocab()

        def token_eos(self) -> int:
            return 2

        def token_bos(self) -> int:
            return 1

        def tokenize(self, text: bytes, add_bos: bool = True, special: bool = False) -> list[int]:
            # 문자 하나 = 토큰 하나 (가짜 토크나이저)
            return [10 + (ord(ch) % 50) for ch in text.decode("utf-8")]

        def reset(self) -> None:
            state.resets += 1

        def close(self) -> None:
            state.closes += 1

        def create_completion(self, **kwargs: Any) -> dict[str, Any]:
            with state.lock:
                state.active += 1
                state.max_active = max(state.max_active, state.active)
                state.completions.append(kwargs)
                script = state.scripts.pop(0) if state.scripts else state.default
            try:
                if script.raises is not None:
                    raise script.raises
                if script.sleep_s:
                    time.sleep(script.sleep_s)
                criteria = kwargs.get("stopping_criteria")
                ids = list(kwargs["prompt"])
                produced = 0
                finish = script.finish_reason
                for _ in range(script.tokens):
                    ids.append(99)
                    produced += 1
                    if criteria is not None and criteria(ids, None):
                        finish = "stop"
                        break
                return {
                    "choices": [{"text": script.text, "finish_reason": finish}],
                    "usage": {"prompt_tokens": len(kwargs["prompt"]), "completion_tokens": produced},
                }
            finally:
                with state.lock:
                    state.active -= 1

    root.Llama = Llama  # type: ignore[attr-defined]
    root.LlamaGrammar = LlamaGrammar  # type: ignore[attr-defined]
    root.StoppingCriteriaList = StoppingCriteriaList  # type: ignore[attr-defined]
    root.__version__ = "0.3.36-fake"  # type: ignore[attr-defined]
    root.llama_supports_gpu_offload = lambda: True  # type: ignore[attr-defined]
    root.llama_grammar = grammar_mod  # type: ignore[attr-defined]
    root.llama_chat_format = chat_mod  # type: ignore[attr-defined]
    grammar_mod.SchemaConverter = SchemaConverter  # type: ignore[attr-defined]
    chat_mod.Jinja2ChatFormatter = Jinja2ChatFormatter  # type: ignore[attr-defined]
    return {"llama_cpp": root, "llama_cpp.llama_grammar": grammar_mod, "llama_cpp.llama_chat_format": chat_mod}


def install_fake_llama(monkeypatch: pytest.MonkeyPatch, state: FakeState | None = None) -> FakeState:
    state = state or FakeState()
    for name, module in build_fake_llama(state).items():
        monkeypatch.setitem(sys.modules, name, module)
    return state


def block_llama_import(monkeypatch: pytest.MonkeyPatch) -> None:
    """extra 없는 설치를 흉내 낸다 (sys.modules 값 None → import가 ImportError)."""
    for name in ("llama_cpp", "llama_cpp.llama_grammar", "llama_cpp.llama_chat_format"):
        monkeypatch.setitem(sys.modules, name, None)  # type: ignore[arg-type]

"""T25d: 로컬 LLM 제공자 (가짜 llama_cpp 모듈). 설계 design_local_analyzer.md 3.3~3.5, 5.3, 6.3, 6.7절."""

from __future__ import annotations

import ast
import hashlib
import socket
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict

from jupjup.domain.errors import (
    AnalyzerUnavailableError,
    LLMContextOverflowError,
    LLMProviderError,
    LLMTimeoutError,
)
from jupjup.ingest.profiles import DecodingParams, LocalModelSpec, recording_model_id
from jupjup.ingest.schemas import AnalysisOutput
from jupjup.ingest.worker import is_retryable_error
from jupjup.providers import llm_local
from jupjup.providers.json_grammar import (
    ANALYSIS_DECODING_POLICY_DS1,
    SAFE_CHAR_RULE,
    UNSAFE_CHAR_RULE,
    DecodingPolicyMismatchError,
)
from jupjup.providers.llm_local import LlamaCppLLM
from tests.unit._fake_llama import FakeState, Script, block_llama_import, install_fake_llama

REPO = Path(__file__).resolve().parents[2]
CONTENT = b"fake-gguf-weights"


class Tiny(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: bool


def _spec(n_ctx: int = 4096, sha: str | None = None, **extra: Any) -> LocalModelSpec:
    return LocalModelSpec(
        model_id="fake-model-q4km",
        repo="org/fake",
        revision="0" * 40,
        filename="fake.gguf",
        sha256=sha or hashlib.sha256(CONTENT).hexdigest(),
        n_ctx=n_ctx,
        license="apache-2.0",
        license_commercial_ok=True,
        **extra,
    )


@pytest.fixture
def cache_dir(tmp_path: Path) -> Path:
    model_dir = tmp_path / "gguf" / "fake-model-q4km"
    model_dir.mkdir(parents=True)
    (model_dir / "fake.gguf").write_bytes(CONTENT)
    return tmp_path


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeState:
    return install_fake_llama(monkeypatch)


def _llm(cache_dir: Path, **kwargs: Any) -> LlamaCppLLM:
    spec = kwargs.pop("spec", None) or _spec()
    return LlamaCppLLM(spec, kwargs.pop("decoding", DecodingParams()), cache_dir, **kwargs)


# --- 기본 설치와 지연 로드 ----------------------------------------------------------------------------------


def test_import_does_not_load_llama_cpp() -> None:
    code = (
        "import sys\n"
        "import jupjup.providers.llm_local, jupjup.providers.local_models, jupjup.ingest.profiles, jupjup.cli\n"
        "import jupjup.container\n"
        "assert 'llama_cpp' not in sys.modules, sorted(m for m in sys.modules if m.startswith('llama'))\n"
        "print('ok')\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=REPO, check=False)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_constructor_does_not_import_or_load(cache_dir: Path, fake: FakeState) -> None:
    llm = _llm(cache_dir)
    assert fake.loads == []
    assert not llm.loaded
    assert llm.model_id == recording_model_id(_spec(), DecodingParams())


def test_missing_extra_is_analyzer_unavailable(cache_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    block_llama_import(monkeypatch)
    llm = _llm(cache_dir)  # 생성은 된다 (파일만 확인)
    with pytest.raises(AnalyzerUnavailableError) as info:
        llm.complete_json("s", "u", Tiny, timeout_s=5, max_tokens=8)
    assert info.value.details["reason"] == "extra_missing"
    assert info.value.code == "ANALYZER_UNAVAILABLE"
    assert is_retryable_error(info.value) is False
    assert llm_local.llama_runtime_info()["installed"] is False


def test_lazy_load_once_with_pinned_decoding(cache_dir: Path, fake: FakeState) -> None:
    decoding = DecodingParams()
    llm = _llm(cache_dir, decoding=decoding, n_gpu_layers=0)
    first = llm.complete_json("sys", "user", Tiny, timeout_s=5, max_tokens=8)
    llm.complete_json("sys", "user2", Tiny, timeout_s=5, max_tokens=8)
    assert len(fake.loads) == 1
    load = fake.loads[0]
    assert load["model_path"] == str(cache_dir / "gguf" / "fake-model-q4km" / "fake.gguf")
    assert (load["n_ctx"], load["n_batch"], load["n_ubatch"], load["n_threads"]) == (4096, 512, 512, 4)
    assert (load["n_gpu_layers"], load["seed"], load["verbose"]) == (0, 20261102, False)
    call = fake.completions[0]
    assert (call["temperature"], call["top_k"], call["top_p"], call["min_p"], call["repeat_penalty"]) == (
        0.0,
        1,
        1.0,
        0.0,
        1.0,
    )
    assert call["seed"] == 20261102 and call["stream"] is False and call["stop"] == ["</s>"]
    assert first.text == '{"ok": true}'
    assert fake.resets == 2  # 요청마다 KV 접두사 재사용을 끈다


def test_warm_up_loads_compiles_and_generates(cache_dir: Path, fake: FakeState) -> None:
    llm = _llm(cache_dir)
    llm.warm_up([AnalysisOutput, Tiny])
    assert llm.loaded and len(fake.loads) == 1
    assert len(fake.grammars) == 2
    assert fake.completions[-1]["max_tokens"] == 1 and fake.completions[-1]["grammar"] is None
    llm.close()
    assert fake.closes == 1 and not llm.loaded


def test_warm_up_generation_failure_is_load_failed(cache_dir: Path, fake: FakeState) -> None:
    fake.scripts.append(Script(raises=RuntimeError("metal oom")))
    with pytest.raises(AnalyzerUnavailableError) as info:
        _llm(cache_dir).warm_up()
    assert info.value.details["reason"] == "load_failed"


# --- 파일과 sha256 ----------------------------------------------------------------------------------------


def test_missing_file_at_construction(tmp_path: Path, fake: FakeState) -> None:
    with pytest.raises(AnalyzerUnavailableError) as info:
        _llm(tmp_path)
    assert info.value.details["reason"] == "model_missing"
    assert info.value.details["retryable"] is False


def test_file_removed_after_construction(cache_dir: Path, fake: FakeState) -> None:
    llm = _llm(cache_dir)
    (cache_dir / "gguf" / "fake-model-q4km" / "fake.gguf").unlink()
    with pytest.raises(AnalyzerUnavailableError) as info:
        llm.count_tokens("s", "u")
    assert info.value.details["reason"] == "model_missing"
    assert fake.loads == []


def test_sha_mismatch_does_not_open_model(cache_dir: Path, fake: FakeState) -> None:
    llm = _llm(cache_dir, spec=_spec(sha="a" * 64))
    with pytest.raises(AnalyzerUnavailableError) as info:
        llm.complete_json("s", "u", Tiny, timeout_s=5, max_tokens=8)
    assert info.value.details["reason"] == "sha_mismatch"
    assert fake.loads == []


def test_extra_files_are_checked(cache_dir: Path, fake: FakeState) -> None:
    extra = [{"filename": "fake-00002.gguf", "sha256": hashlib.sha256(b"part2").hexdigest()}]
    with pytest.raises(AnalyzerUnavailableError) as info:
        _llm(cache_dir, spec=_spec(extra_files=extra))
    assert info.value.details["reason"] == "model_missing"
    (cache_dir / "gguf" / "fake-model-q4km" / "fake-00002.gguf").write_bytes(b"part2-corrupt")
    llm = _llm(cache_dir, spec=_spec(extra_files=extra))
    with pytest.raises(AnalyzerUnavailableError) as info:
        llm.count_tokens("s", "u")
    assert info.value.details["reason"] == "sha_mismatch"


def test_sha_is_remembered_in_process(cache_dir: Path, fake: FakeState, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm_local, "_VERIFIED_SHA", {})
    calls: list[Path] = []
    real = llm_local.file_sha256

    def counting(path: Path) -> str:
        calls.append(path)
        return real(path)

    monkeypatch.setattr(llm_local, "file_sha256", counting)
    _llm(cache_dir).count_tokens("s", "u")
    _llm(cache_dir).count_tokens("s", "u")
    assert len(calls) == 1


def test_load_failure_is_load_failed(cache_dir: Path, fake: FakeState) -> None:
    fake.load_error = ValueError("bad gguf")
    with pytest.raises(AnalyzerUnavailableError) as info:
        _llm(cache_dir).count_tokens("s", "u")
    assert info.value.details["reason"] == "load_failed"
    assert "bad gguf" not in str(info.value.details)


def test_missing_chat_template_is_load_failed(cache_dir: Path, fake: FakeState) -> None:
    fake.metadata = {}
    with pytest.raises(AnalyzerUnavailableError) as info:
        _llm(cache_dir).count_tokens("s", "u")
    assert info.value.details["reason"] == "load_failed"


def test_chat_template_compile_failure_is_load_failed_and_closes_model(
    cache_dir: Path, fake: FakeState, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T25d 검수 M1: Jinja2ChatFormatter 생성 예외(TemplateSyntaxError 등)도 load_failed. 연 모델은 닫는다."""
    import llama_cpp  # 가짜 모듈

    class TemplateSyntaxError(Exception):
        pass

    def broken(**kwargs: Any) -> Any:
        raise TemplateSyntaxError("unexpected '}' in <원문 일부>")

    monkeypatch.setattr(llama_cpp.llama_chat_format, "Jinja2ChatFormatter", broken)
    llm = _llm(cache_dir)
    for call in (llm.warm_up, lambda: llm.complete_json("s", "u", Tiny, 5.0)):
        with pytest.raises(AnalyzerUnavailableError) as info:
            call()
        assert info.value.details["reason"] == "load_failed"
        assert info.value.details["error"] == "TemplateSyntaxError"
        assert "원문" not in str(info.value.details)
        assert not is_retryable_error(info.value)
    assert len(fake.loads) == 2 and fake.closes == 2  # 열었던 모델을 매번 닫는다
    assert not llm.loaded


def test_render_failure_is_not_retryable_and_warm_up_wraps_it(
    cache_dir: Path, fake: FakeState, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T25d 검수 L1: 렌더링 실패는 결정적이므로 재시도하지 않고, warm_up에서는 load_failed다."""
    llm = _llm(cache_dir)
    llm.warm_up()
    original = llm._formatter

    def failing(**kwargs: Any) -> Any:
        raise RuntimeError("render")

    llm._formatter = failing
    with pytest.raises(LLMProviderError) as info:
        llm.complete_json("s", "u", Tiny, 5.0)
    assert info.value.details["retryable"] is False and not is_retryable_error(info.value)
    with pytest.raises(AnalyzerUnavailableError) as warm:
        llm.warm_up()
    assert warm.value.details["reason"] == "load_failed"
    llm._formatter = original


def test_injected_loader_is_used(cache_dir: Path, fake: FakeState) -> None:
    seen: list[dict[str, Any]] = []
    import llama_cpp  # 가짜 모듈

    def loader(**kwargs: Any) -> Any:
        seen.append(kwargs)
        return llama_cpp.Llama(**kwargs)

    _llm(cache_dir, loader=loader).count_tokens("s", "u")
    assert len(seen) == 1


# --- 생성 결과 매핑 ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(("finish", "stop_reason"), [("stop", "end_turn"), ("length", "max_tokens")])
def test_finish_reason_mapping(cache_dir: Path, fake: FakeState, finish: str, stop_reason: str) -> None:
    fake.scripts.append(Script(text='{"ok": tr', finish_reason=finish, tokens=4))
    raw = _llm(cache_dir).complete_json("s", "u", Tiny, timeout_s=5, max_tokens=8)
    assert raw.stop_reason == stop_reason
    assert raw.output_tokens == 4 if finish == "length" else raw.output_tokens >= 1
    assert raw.input_tokens == len(fake.completions[0]["prompt"])
    assert raw.latency_ms >= 0


@pytest.mark.parametrize("finish", [None, "tool_calls"])
def test_unknown_finish_reason_is_provider_error(cache_dir: Path, fake: FakeState, finish: str | None) -> None:
    fake.scripts.append(Script(finish_reason=finish, tokens=0))
    with pytest.raises(LLMProviderError) as info:
        _llm(cache_dir).complete_json("s", "u", Tiny, timeout_s=5, max_tokens=8)
    assert not isinstance(info.value, LLMTimeoutError)


def test_runtime_error_is_retryable_provider_error_without_text(cache_dir: Path, fake: FakeState) -> None:
    fake.scripts.append(Script(raises=RuntimeError("secret prompt text")))
    with pytest.raises(LLMProviderError) as info:
        _llm(cache_dir).complete_json("secret prompt text", "u", Tiny, timeout_s=5, max_tokens=8)
    assert type(info.value) is LLMProviderError
    assert is_retryable_error(info.value) is True
    assert "secret" not in info.value.message and "secret" not in str(info.value.details)


def test_effort_is_ignored(cache_dir: Path, fake: FakeState) -> None:
    llm = _llm(cache_dir)
    a = llm.complete_json("s", "u", Tiny, timeout_s=5, max_tokens=8, effort="high")
    b = llm.complete_json("s", "u", Tiny, timeout_s=5, max_tokens=8, effort=None)
    assert a == b.model_copy(update={"latency_ms": a.latency_ms})
    assert "effort" not in fake.completions[0]


def test_constrained_none_sends_no_grammar(cache_dir: Path, fake: FakeState) -> None:
    llm = _llm(cache_dir, decoding=DecodingParams(constrained="none"))
    llm.complete_json("s", "u", AnalysisOutput, timeout_s=5, max_tokens=8)
    assert fake.completions[0]["grammar"] is None and fake.grammars == []


# --- 타임아웃 ---------------------------------------------------------------------------------------------


class StepClock:
    def __init__(self, step: float) -> None:
        self.now = 0.0
        self.step = step

    def __call__(self) -> float:
        self.now += self.step
        return self.now


def test_timeout_via_stopping_criteria(cache_dir: Path, fake: FakeState) -> None:
    fake.scripts.append(Script(tokens=100))
    llm = _llm(cache_dir, clock=StepClock(1.0))
    with pytest.raises(LLMTimeoutError) as info:
        llm.complete_json("s", "u", Tiny, timeout_s=10, max_tokens=200)
    assert info.value.code == "LLM_TIMEOUT"
    assert info.value.details["retryable"] is True and info.value.details["timeout_s"] == 10
    assert is_retryable_error(info.value) is True
    criteria = fake.completions[0]["stopping_criteria"]
    assert len(criteria) == 2  # 템플릿 EOS 규칙 + 마감 규칙


def test_no_timeout_when_generation_is_fast(cache_dir: Path, fake: FakeState) -> None:
    fake.scripts.append(Script(tokens=5))
    raw = _llm(cache_dir, clock=StepClock(1.0)).complete_json("s", "u", Tiny, timeout_s=100, max_tokens=200)
    assert raw.stop_reason == "end_turn"


def test_lock_wait_is_not_counted_in_timeout(cache_dir: Path, fake: FakeState) -> None:
    llm = _llm(cache_dir)
    llm.count_tokens("warm", "load")  # 로드 시간을 미리 뺀다
    held = threading.Event()
    release = threading.Event()

    def holder() -> None:
        with llm._lock:
            held.set()
            release.wait(5)

    thread = threading.Thread(target=holder)
    thread.start()
    held.wait(5)
    timer = threading.Timer(0.3, release.set)
    timer.start()
    raw = llm.complete_json("s", "u", Tiny, timeout_s=0.2, max_tokens=8)  # 0.3초 대기 > 0.2초 타임아웃
    thread.join()
    assert raw.stop_reason == "end_turn"
    assert llm.last_lock_wait_s >= 0.25


# --- 입력 상한, 잠금, 문법 ---------------------------------------------------------------------------------


def test_context_overflow_before_generation(cache_dir: Path, fake: FakeState) -> None:
    llm = _llm(cache_dir, spec=_spec(n_ctx=2048))
    user = "가" * 2000
    tokens = llm.count_tokens("s", user)
    assert tokens == len("<s>[system]s[user]" + user + "[assistant]")
    llm.complete_json("s", user, Tiny, timeout_s=5, max_tokens=2048 - tokens)  # 경계: 딱 맞으면 통과
    with pytest.raises(LLMContextOverflowError) as info:
        llm.complete_json("s", user, Tiny, timeout_s=5, max_tokens=2048 - tokens + 1)
    details = info.value.details
    assert details["retryable"] is False and details["n_ctx"] == 2048 and details["input_tokens"] == tokens
    assert is_retryable_error(info.value) is False
    assert len(fake.completions) == 1


def test_calls_are_serialized_per_instance(cache_dir: Path, fake: FakeState) -> None:
    fake.default = Script(sleep_s=0.03)
    llm = _llm(cache_dir)
    errors: list[BaseException] = []

    def worker(i: int) -> None:
        try:
            llm.complete_json("s", f"u{i}", Tiny, timeout_s=5, max_tokens=8)
            llm.count_tokens("s", f"u{i}")
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    assert len(fake.completions) == 6 and fake.max_active == 1
    assert len(fake.loads) == 1


def test_grammar_is_cached_per_decoding_schema(cache_dir: Path, fake: FakeState) -> None:
    llm = _llm(cache_dir)
    for _ in range(3):
        llm.complete_json("s", "u", AnalysisOutput, timeout_s=5, max_tokens=8)
    assert len(fake.grammars) == 1
    llm.complete_json("s", "u", Tiny, timeout_s=5, max_tokens=8)
    assert len(fake.grammars) == 2
    grammars = [call["grammar"] for call in fake.completions]
    assert grammars[0] is grammars[1] is grammars[2] and grammars[3] is not grammars[0]


def test_grammar_char_rule_blocks_control_characters(cache_dir: Path, fake: FakeState) -> None:
    _llm(cache_dir).complete_json("s", "u", AnalysisOutput, timeout_s=5, max_tokens=8)
    text = fake.grammars[0]
    assert UNSAFE_CHAR_RULE not in text and SAFE_CHAR_RULE in text
    # 가짜 변환기는 디코딩 스키마의 루트 필드 순서를 그대로 적는다 (ds-1 순서)
    assert ANALYSIS_DECODING_POLICY_DS1.property_order[""] == text.split('root ::= "')[1].rstrip('"').split(",")


def test_policy_hash_mismatch_fails_at_construction(cache_dir: Path, fake: FakeState) -> None:
    changed = ANALYSIS_DECODING_POLICY_DS1.model_copy(update={"max_items": {"/properties/evidence": 5}})
    with pytest.raises(DecodingPolicyMismatchError):
        _llm(cache_dir, policies={"AnalysisOutput": changed})
    with pytest.raises(DecodingPolicyMismatchError):
        _llm(cache_dir, decoding=DecodingParams(decoding_schema_version="ds-9"))
    _llm(cache_dir, policies={"AnalysisOutput": ANALYSIS_DECODING_POLICY_DS1})  # 등록된 정책은 통과


# --- 네트워크 차단 -----------------------------------------------------------------------------------------


def test_no_network_on_load_and_generate(cache_dir: Path, fake: FakeState, monkeypatch: pytest.MonkeyPatch) -> None:
    attempts: list[str] = []

    def deny(name: str) -> Any:
        def blocked(*args: Any, **kwargs: Any) -> Any:
            attempts.append(name)
            raise OSError(f"network blocked in test: {name}")

        return blocked

    monkeypatch.setattr(socket.socket, "connect", deny("connect"))
    monkeypatch.setattr(socket.socket, "connect_ex", deny("connect_ex"))
    monkeypatch.setattr(socket, "create_connection", deny("create_connection"))
    monkeypatch.setattr(socket, "getaddrinfo", deny("getaddrinfo"))
    llm = _llm(cache_dir)
    llm.warm_up([AnalysisOutput])
    llm.count_tokens("s", "u")
    llm.complete_json("s", "u", AnalysisOutput, timeout_s=5, max_tokens=8)
    llm.close()
    assert attempts == []


def test_network_code_lives_only_in_models_pull() -> None:
    src = REPO / "src" / "jupjup"
    offenders = []
    for path in src.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(REPO).as_posix()
        if "hf_hub_download" in text or "huggingface_hub" in text:
            offenders.append(rel)
    allowed = {"src/jupjup/providers/local_models.py"}
    assert set(offenders) <= allowed | {"src/jupjup/providers/embedding_bge.py", "src/jupjup/providers/rerank_bge.py"}
    local = (src / "providers" / "llm_local.py").read_text(encoding="utf-8")
    for needle in ("huggingface", "from_pretrained", "urllib", "requests", "httpx", "socket"):
        assert needle not in local
    llama_importers = sorted(
        path.relative_to(REPO).as_posix() for path in src.rglob("*.py") if _imports_llama(path.read_text("utf-8"))
    )
    assert llama_importers == ["src/jupjup/providers/llm_local.py"]  # AC-L16: llama_cpp import는 한 곳뿐


def _imports_llama(text: str) -> bool:
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Import) and any(alias.name.split(".")[0] == "llama_cpp" for alias in node.names):
            return True
        if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "llama_cpp":
            return True
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "import_module"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and str(node.args[0].value).split(".")[0] == "llama_cpp"
        ):
            return True
    return False


def test_runtime_info_with_fake(fake: FakeState) -> None:
    info = llm_local.llama_runtime_info()
    assert info["installed"] is True and info["llama_cpp_python"] == "0.3.36-fake" and info["gpu_offload"] is True


@pytest.mark.parametrize("version", ["ds-1", "ds-3"])
def test_source_enum_literal_fix_is_scoped_to_ds3(
    cache_dir: Path, fake: FakeState, monkeypatch: pytest.MonkeyPatch, version: str
) -> None:
    converter_type = sys.modules["llama_cpp.llama_grammar"].SchemaConverter
    original = converter_type.visit
    observed: list[Any] = []

    def visit(converter: Any, schema: Any, name: str) -> None:
        observed.append(getattr(converter, "_generate_constant_rule", None))
        original(converter, schema, name)

    monkeypatch.setattr(converter_type, "visit", visit)
    _llm(cache_dir, decoding=DecodingParams(decoding_schema_version=version)).complete_json("s", "u", Tiny, 5, 30)
    from jupjup.providers.json_grammar import gbnf_json_constant

    assert observed == [gbnf_json_constant if version == "ds-3" else None]

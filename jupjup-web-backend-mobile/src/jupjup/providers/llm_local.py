"""llama.cpp(llama-cpp-python) 로컬 LLM 제공자 (설계 ``design_local_analyzer.md`` 3.3~3.5절, 5.3절, 6.3절, 6.7절).

- extra ``[analyze-local]``이 있어야 실제로 돈다. ``llama_cpp``는 **함수 안에서만** import하므로 기본 설치는
  이 모듈을 import해도 llama_cpp를 읽지 않는다 (AC-L16: llama_cpp import는 이 파일 한 곳뿐이다).
- 모델은 ``<cache_dir>/gguf/<model_id>/<filename>`` 로컬 파일로만 연다. 허브·네트워크를 부르지 않는다 (AC-L8).
  첫 로드 때 sha256을 검증하고 결과를 프로세스 안에서 기억한다.
- 프롬프트는 GGUF 내장 chat 템플릿으로 렌더링한다. 같은 렌더링 결과로 ``count_tokens``와 입력 상한을 잰다.
- 요청마다 ``reset()``으로 KV 접두사 재사용을 끈다 (결정성과 녹화 키의 전제, T25b 4.5절).
- 문법은 디코딩 스키마(``json_grammar.build_decoding_schema``)에서 만들고, 문자열 ``char`` 규칙을 제어 문자를 막는
  규칙으로 고친 뒤(T25b 4.4절) 스키마 지문별로 캐시한다.
- 타임아웃은 토큰마다 불리는 ``stopping_criteria``로 건다. 잠금 대기 시간은 타임아웃에 넣지 않는다.
- 프롬프트와 출력 원문은 로그·에러 details에 넣지 않는다 (AC-L13). 길이와 토큰 수만 남긴다.
"""

from __future__ import annotations

import atexit
import hashlib
import importlib
import importlib.util
import logging
import platform
import sys
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

from pydantic import BaseModel

from jupjup.domain.errors import (
    AnalyzerUnavailableError,
    JupjupError,
    LLMContextOverflowError,
    LLMProviderError,
    LLMTimeoutError,
)
from jupjup.ingest.profiles import DecodingParams, LocalModelSpec, recording_model_id
from jupjup.providers.json_grammar import (
    DecodingSchemaPolicy,
    build_decoding_schema,
    decoding_schema_fingerprint,
    enforce_json_string_char_rule,
    gbnf_json_constant,
    policies_for_version,
    verify_decoding_policies,
)
from jupjup.providers.llm import LLMRawResponse

logger = logging.getLogger(__name__)

_HASH_CHUNK = 8 * 1024 * 1024
_FINISH_REASONS = {"stop": "end_turn", "length": "max_tokens"}
_WARM_UP_SYSTEM = "Reply with one word."
_WARM_UP_USER = "ok"

# (resolved path, size, mtime_ns) → sha256. 같은 파일을 프로세스 안에서 두 번 해시하지 않는다.
_VERIFIED_SHA: dict[tuple[str, int, int], str] = {}
_VERIFIED_LOCK = threading.Lock()


@dataclass(frozen=True)
class _Runtime:
    module: ModuleType
    llama_grammar: ModuleType
    llama_chat_format: ModuleType


@dataclass(frozen=True)
class _RenderedPrompt:
    tokens: list[int]
    stop: list[str]
    stopping_criteria: list[Callable[[Any, Any], bool]]


def _unavailable(reason: str, message: str, **details: Any) -> AnalyzerUnavailableError:
    return AnalyzerUnavailableError(message, {"retryable": False, "reason": reason, **details})


def _import_runtime() -> _Runtime:
    try:
        module = importlib.import_module("llama_cpp")
        grammar = importlib.import_module("llama_cpp.llama_grammar")
        chat_format = importlib.import_module("llama_cpp.llama_chat_format")
    except ImportError as exc:
        raise _unavailable(
            "extra_missing",
            "llama-cpp-python이 설치돼 있지 않습니다. `uv sync --extra analyze-local`로 설치하세요",
        ) from exc
    return _Runtime(module=module, llama_grammar=grammar, llama_chat_format=chat_format)


def llama_cpp_available() -> bool:
    """extra ``[analyze-local]`` 설치 여부. llama_cpp를 import하지 않고 확인한다 (API·조립 경로용)."""
    if "llama_cpp" in sys.modules:
        return sys.modules["llama_cpp"] is not None
    try:
        return importlib.util.find_spec("llama_cpp") is not None
    except (ImportError, ValueError):
        return False


def llama_runtime_info() -> dict[str, Any]:
    """설치된 llama-cpp-python 정보 (models doctor, 리포트 config.runtime용). 없으면 ``installed=False``."""
    info: dict[str, Any] = {"machine": platform.machine(), "python": platform.python_version()}
    try:
        runtime = _import_runtime()
    except AnalyzerUnavailableError:
        return {**info, "installed": False}
    module = runtime.module
    gpu: bool | None
    try:
        gpu = bool(module.llama_supports_gpu_offload())
    except Exception:  # 런타임마다 노출 함수가 다를 수 있다. 정보 출력용이라 실패해도 계속한다
        gpu = None
    return {
        **info,
        "installed": True,
        "llama_cpp_python": str(getattr(module, "__version__", "unknown")),
        "gpu_offload": gpu,
        "wheel_tags": _wheel_tags(),
    }


def _wheel_tags() -> list[str]:
    """설치된 배포판의 WHEEL 태그. 이 기기 소스 빌드는 ``py3-none-macosx_<로컬 macOS>_arm64``(예: 26_0),
    Metal 인덱스 wheel은 ``py3-none-macosx_11_0_arm64``라서 빌드 방식을 구분할 수 있다."""
    from importlib import metadata

    try:
        text = metadata.distribution("llama-cpp-python").read_text("WHEEL") or ""
    except metadata.PackageNotFoundError:
        return []
    return [line.split(":", 1)[1].strip() for line in text.splitlines() if line.startswith("Tag:")]


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        while chunk := file.read(_HASH_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def verified_sha256(path: Path) -> str:
    """파일 sha256. (경로, 크기, mtime)이 같으면 프로세스 안에서 한 번만 계산한다."""
    stat = path.stat()
    key = (str(path.resolve()), stat.st_size, stat.st_mtime_ns)
    with _VERIFIED_LOCK:
        cached = _VERIFIED_SHA.get(key)
    if cached is not None:
        return cached
    digest = file_sha256(path)
    with _VERIFIED_LOCK:
        _VERIFIED_SHA[key] = digest
    return digest


def check_model_files(spec: LocalModelSpec, cache_dir: Path, *, verify_sha: bool) -> list[Path]:
    """모델 파일이 모두 있는지(그리고 ``verify_sha``면 sha256이 맞는지) 확인한다."""
    directory = spec.model_dir(cache_dir)
    paths: list[Path] = []
    for item in spec.files:
        path = directory / item.filename
        if not path.is_file():
            raise _unavailable(
                "model_missing",
                f"모델 파일이 없습니다. `uv run jupjup models pull {spec.model_id}`로 받거나 파일을 두세요",
                model_id=spec.model_id,
                path=str(path),
            )
        if verify_sha and verified_sha256(path) != item.sha256:
            raise _unavailable(
                "sha_mismatch",
                "모델 파일 sha256이 명세와 다릅니다",
                model_id=spec.model_id,
                path=str(path),
                expected=item.sha256,
            )
        paths.append(path)
    return paths


class LlamaCppLLM:
    """``LLMClient`` 구현. 모델 인스턴스당 호출 1건만 돈다 (``threading.Lock``)."""

    def __init__(
        self,
        spec: LocalModelSpec,
        decoding: DecodingParams,
        cache_dir: Path,
        *,
        n_gpu_layers: int = -1,
        policies: Mapping[str, DecodingSchemaPolicy] | None = None,
        loader: Callable[..., Any] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.spec = spec
        self.decoding = decoding
        self.cache_dir = cache_dir
        self.n_gpu_layers = n_gpu_layers
        self.model_id = recording_model_id(spec, decoding)
        version = decoding.decoding_schema_version
        if policies is None:
            self._policies = policies_for_version(version)
        else:
            verify_decoding_policies(version, policies)
            self._policies = dict(policies)
        self._loader = loader
        self._clock = clock
        self._lock = threading.Lock()
        self._runtime: _Runtime | None = None
        self._model: Any | None = None
        self._formatter: Any | None = None
        self._grammars: dict[str, Any] = {}
        self.last_lock_wait_s = 0.0
        # 생성자는 파일 존재만 확인하고 모델을 열지 않는다 (지연 로드).
        self._paths = check_model_files(spec, cache_dir, verify_sha=False)

    # --- LLMClient ------------------------------------------------------------------------------------------

    def complete_json(
        self,
        system: str,
        user: str,
        schema: type[BaseModel],
        timeout_s: float,
        max_tokens: int = 4000,
        effort: str | None = None,
    ) -> LLMRawResponse:
        del effort  # 로컬 엔진에는 effort가 없다. 녹화 키에는 호출자가 준 값이 그대로 들어간다
        if timeout_s <= 0:
            raise ValueError("timeout_s는 0보다 커야 합니다")
        if max_tokens < 1:
            raise ValueError("max_tokens는 1 이상이어야 합니다")
        with self._locked():
            model, runtime = self._ensure_loaded()
            # 잠금을 잡고 모델 로드를 마친 뒤부터 잰다. 렌더링·문법 컴파일·prefill·생성이 들어가고, 첫 호출의
            # 로드 시간(약 1.5~2초)은 넣지 않는다 (worker run은 warm_up으로 로드를 미리 끝낸다).
            started = self._clock()
            deadline = started + timeout_s
            prompt = self._render(model, system, user)
            self._check_context(len(prompt.tokens), max_tokens)
            grammar = self._grammar_for(runtime, schema) if self.decoding.constrained == "json_schema" else None
            timed_out = False

            def past_deadline(input_ids: Any, logits: Any) -> bool:
                nonlocal timed_out
                if self._clock() > deadline:
                    timed_out = True
                return timed_out

            criteria = runtime.module.StoppingCriteriaList([*prompt.stopping_criteria, past_deadline])
            completion = self._generate(model, prompt, max_tokens, criteria, grammar)
            elapsed = self._clock() - started
            if timed_out:
                raise LLMTimeoutError(
                    "로컬 LLM 생성이 타임아웃을 넘었습니다",
                    {"retryable": True, "timeout_s": timeout_s, "model_id": self.model_id},
                )
            return self._to_response(completion, prompt, elapsed)

    def count_tokens(self, system: str, user: str) -> int:
        with self._locked():
            model, _ = self._ensure_loaded()
            return len(self._render(model, system, user).tokens)

    # --- 수명 주기 ---------------------------------------------------------------------------------------------

    def warm_up(self, schemas: Sequence[type[BaseModel]] = ()) -> None:
        """모델 로드 + sha256 검증 + 스키마 문법 미리 컴파일 + 짧은 생성 1회. 실패하면 바로 드러낸다."""
        with self._locked():
            model, runtime = self._ensure_loaded()
            if self.decoding.constrained == "json_schema":
                for schema in schemas:
                    self._grammar_for(runtime, schema)
            try:
                prompt = self._render(model, _WARM_UP_SYSTEM, _WARM_UP_USER)
                criteria = runtime.module.StoppingCriteriaList(list(prompt.stopping_criteria))
                self._generate(model, prompt, 1, criteria, None)
            except LLMProviderError as exc:
                raise _unavailable(
                    "load_failed", "로컬 LLM 시험 생성에 실패했습니다", model_id=self.spec.model_id
                ) from exc

    def close(self) -> None:
        atexit.unregister(self.close)
        with self._lock:
            model, self._model = self._model, None
            self._formatter = None
            self._grammars.clear()
            if model is not None and hasattr(model, "close"):
                model.close()

    @property
    def loaded(self) -> bool:
        return self._model is not None

    # --- 내부 ---------------------------------------------------------------------------------------------------

    def _locked(self) -> _TimedLock:
        return _TimedLock(self)

    def _ensure_loaded(self) -> tuple[Any, _Runtime]:
        if self._model is not None and self._runtime is not None:
            return self._model, self._runtime
        runtime = self._runtime or _import_runtime()
        self._runtime = runtime
        paths = check_model_files(self.spec, self.cache_dir, verify_sha=True)
        loader = self._loader or runtime.module.Llama
        d = self.decoding
        try:
            model = loader(
                model_path=str(paths[0]),
                n_ctx=self.spec.n_ctx,
                n_batch=d.n_batch,
                n_ubatch=d.n_ubatch,
                n_threads=d.n_threads,
                n_gpu_layers=self.n_gpu_layers,
                seed=d.seed,
                verbose=False,
            )
        except Exception as exc:
            raise _unavailable(
                "load_failed", "로컬 모델을 열지 못했습니다", model_id=self.spec.model_id, error=type(exc).__name__
            ) from exc
        try:
            self._formatter = self._chat_formatter(runtime, model)
        except Exception as exc:
            # 템플릿 컴파일 실패(TemplateSyntaxError 등)도 로드 실패다. 연 모델은 닫고 다음 호출에서 다시 연다.
            _close_quietly(model)
            if isinstance(exc, AnalyzerUnavailableError):
                raise
            raise _unavailable(
                "load_failed",
                "GGUF chat 템플릿을 준비하지 못했습니다",
                model_id=self.spec.model_id,
                error=type(exc).__name__,
            ) from exc
        self._model = model
        # Release Metal resources before native library finalizers at process exit.
        atexit.register(self.close)
        logger.info("로컬 LLM 로드: %s (n_ctx=%d, n_gpu_layers=%d)", self.model_id, self.spec.n_ctx, self.n_gpu_layers)
        return model, runtime

    def _chat_formatter(self, runtime: _Runtime, model: Any) -> Any:
        metadata = getattr(model, "metadata", None) or {}
        template = metadata.get("tokenizer.chat_template")
        if not isinstance(template, str) or not template:
            raise _unavailable("load_failed", "GGUF에 chat 템플릿이 없습니다", model_id=self.spec.model_id)
        eos_id = int(model.token_eos())
        bos_id = int(model.token_bos())
        return runtime.llama_chat_format.Jinja2ChatFormatter(
            template=template,
            eos_token=_token_text(model, eos_id),
            bos_token=_token_text(model, bos_id),
            stop_token_ids=[eos_id],
        )

    def _render(self, model: Any, system: str, user: str) -> _RenderedPrompt:
        if self._formatter is None:
            raise LLMProviderError("로컬 LLM chat 템플릿이 준비되지 않았습니다")
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        try:
            result = self._formatter(messages=messages)
            tokens = list(model.tokenize(result.prompt.encode("utf-8"), add_bos=not result.added_special, special=True))
        except Exception as exc:
            # 같은 입력·같은 템플릿이면 결정적으로 다시 실패하므로 재시도하지 않는다 (T25d 검수 L1).
            raise LLMProviderError(
                "로컬 LLM 프롬프트를 렌더링하지 못했습니다", {"error": type(exc).__name__, "retryable": False}
            ) from exc
        stop = result.stop if isinstance(result.stop, list) else [result.stop] if result.stop is not None else []
        criteria = list(result.stopping_criteria) if result.stopping_criteria is not None else []
        return _RenderedPrompt(tokens=tokens, stop=[str(item) for item in stop], stopping_criteria=criteria)

    def _check_context(self, input_tokens: int, max_tokens: int) -> None:
        if input_tokens + max_tokens > self.spec.n_ctx:
            raise LLMContextOverflowError(
                "입력과 출력 상한이 모델 컨텍스트를 넘습니다",
                {
                    "retryable": False,
                    "input_tokens": input_tokens,
                    "max_tokens": max_tokens,
                    "n_ctx": self.spec.n_ctx,
                    "model_id": self.model_id,
                },
            )

    def _grammar_for(self, runtime: _Runtime, schema: type[BaseModel]) -> Any:
        version = self.decoding.decoding_schema_version
        policy = self._policies.get(schema.__name__, DecodingSchemaPolicy(version=version))
        decoding_schema = build_decoding_schema(schema, policy)
        key = decoding_schema_fingerprint(decoding_schema)
        cached = self._grammars.get(key)
        if cached is not None:
            return cached
        try:
            converter = runtime.llama_grammar.SchemaConverter(
                prop_order={}, allow_fetch=False, dotall=False, raw_pattern=False
            )
            if version == "ds-3":
                # 0.3.36 escapes quotes but not existing JSON backslashes. A
                # literal source quote otherwise produces invalid GBNF.
                converter._generate_constant_rule = gbnf_json_constant
            resolved = converter.resolve_refs(decoding_schema, "stdin")
            converter.visit(resolved, "")
            text = enforce_json_string_char_rule(converter.format_grammar())
            grammar = runtime.module.LlamaGrammar.from_string(text, verbose=False)
        except Exception as exc:
            raise _unavailable(
                "load_failed",
                "디코딩 스키마를 문법으로 바꾸지 못했습니다",
                model_id=self.spec.model_id,
                schema_name=schema.__name__,
                error=type(exc).__name__,
            ) from exc
        self._grammars[key] = grammar
        return grammar

    def _generate(self, model: Any, prompt: _RenderedPrompt, max_tokens: int, criteria: Any, grammar: Any) -> Any:
        d = self.decoding
        model.reset()
        try:
            # chat 핸들러(chat_formatter_to_chat_completion_handler)와 같은 인자다. stopping_criteria를 넘기려고
            # create_chat_completion 대신 렌더링한 토큰으로 create_completion을 직접 부른다.
            return model.create_completion(
                prompt=prompt.tokens,
                max_tokens=max_tokens,
                temperature=d.temperature,
                top_p=d.top_p,
                top_k=d.top_k,
                min_p=d.min_p,
                typical_p=1.0,
                stream=False,
                stop=list(prompt.stop),
                seed=d.seed,
                presence_penalty=0.0,
                frequency_penalty=0.0,
                repeat_penalty=d.repeat_penalty,
                tfs_z=1.0,
                mirostat_mode=0,
                mirostat_tau=5.0,
                mirostat_eta=0.1,
                stopping_criteria=criteria,
                grammar=grammar,
            )
        except JupjupError:
            raise
        except Exception as exc:  # Metal 메모리 부족 등 런타임 예외. 메시지에 원문이 섞일 수 있어 타입만 남긴다
            raise LLMProviderError(
                "로컬 LLM 생성에 실패했습니다", {"error": type(exc).__name__, "model_id": self.model_id}
            ) from exc

    def _to_response(self, completion: Any, prompt: _RenderedPrompt, elapsed_s: float) -> LLMRawResponse:
        try:
            choice = completion["choices"][0]
            text = choice["text"]
            finish = choice.get("finish_reason")
            usage = completion.get("usage") or {}
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMProviderError("로컬 LLM 응답 형식이 올바르지 않습니다", {"model_id": self.model_id}) from exc
        stop_reason = _FINISH_REASONS.get(finish) if isinstance(finish, str) else None
        if stop_reason is None or not isinstance(text, str):
            raise LLMProviderError(
                "로컬 LLM finish_reason을 알 수 없습니다", {"finish_reason": str(finish), "model_id": self.model_id}
            )
        input_tokens = _int_or(usage.get("prompt_tokens"), len(prompt.tokens))
        output_tokens = _int_or(usage.get("completion_tokens"), 0)
        logger.info(
            "로컬 LLM 생성: %s in=%d out=%d stop=%s %.0fms",
            self.model_id,
            input_tokens,
            output_tokens,
            stop_reason,
            elapsed_s * 1000,
        )
        return LLMRawResponse(
            text=text,
            stop_reason=stop_reason,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=round(elapsed_s * 1000, 3),
        )


class _TimedLock:
    """잠금을 잡고, 기다린 시간을 ``last_lock_wait_s``에 남긴다 (잡 이벤트 로그용. 타임아웃에는 넣지 않는다)."""

    def __init__(self, owner: LlamaCppLLM) -> None:
        self.owner = owner

    def __enter__(self) -> None:
        # 대기 시간은 실제 시계로 잰다. 주입한 clock은 타임아웃 판정에만 쓴다.
        requested = time.monotonic()
        self.owner._lock.acquire()
        self.owner.last_lock_wait_s = max(0.0, time.monotonic() - requested)

    def __exit__(self, *exc: object) -> None:
        self.owner._lock.release()


def _close_quietly(model: Any) -> None:
    close = getattr(model, "close", None)
    if callable(close):
        try:
            close()
        except Exception:  # 닫기 실패는 원래 오류를 가리지 않는다
            logger.warning("로컬 모델 닫기 실패: %s", type(model).__name__)


def _token_text(model: Any, token_id: int) -> str:
    if token_id < 0:
        return ""
    inner = getattr(model, "_model", None)
    if inner is not None and hasattr(inner, "token_get_text"):
        return str(inner.token_get_text(token_id))  # Llama.__init__이 chat 핸들러를 만들 때와 같은 방법
    return bytes(model.detokenize([token_id], special=True)).decode("utf-8", errors="replace")


def _int_or(value: Any, default: int) -> int:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return default

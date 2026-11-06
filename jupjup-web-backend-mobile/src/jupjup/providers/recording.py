"""Hash-addressed recording and replay adapters for structured LLM responses.

녹화 형식 v2 (T21 Loop 1 M1 반영):

- ``complete_json`` 행의 키는 ``request_hash``다. system, user, 출력 스키마(이름과 JSON Schema 해시),
  ``max_tokens``, ``effort``를 JSON으로 직렬화해 해시한다. 같은 프롬프트를 ``max_tokens``만 2배로
  올려 다시 보내는 잘림 재시도(5.10.6절 5번)도 서로 다른 행이 되고, 재생할 때 각자의 응답이 나온다.
  녹화에 없는 조합은 ``LLMCacheMiss``다. ``timeout_s``는 응답 내용을 바꾸지 않으므로 키에 넣지 않는다.
- ``count_tokens`` 결과도 ``kind="count_tokens"`` 행으로 녹화한다. 재생은 녹화된 값만 돌려주고, 없으면
  ``LLMCacheMiss``다. 녹화와 재생이 같은 분기를 타게 하기 위해서다(L4).
- 원문 프롬프트는 파일에 남기지 않는다. 진단용으로 ``prompt_hash``, ``schema_name``, ``max_tokens``,
  ``effort``만 남긴다.
- 스키마 지문은 필드 구조와 제약만 해시한다. title·description·docstring 문구는 무시하지만 필드 이름, 타입,
  필수 여부, enum·const, 길이·개수 같은 구조가 바뀌면 기존 녹화를 다시 만들어야 한다.
- v1 행(요청 파라미터 없는 키)은 재생 결과를 보장할 수 없어 읽지 않는다. 다시 녹화해야 한다.

오류 사이드카 (T25g 검수 M1, T25p):

- ``failures_path``를 주면 ``RecordingLLM``은 제공자 오류·타임아웃(``JupjupError``, 녹화 미스 제외)도 별도 파일
  (``<녹화>.failures.jsonl``)에 ``request_hash``와 오류 code·retryable만 남긴다. 오류 메시지·details와 프롬프트
  원문은 남기지 않는다. 형식 v2 응답 파일은 바뀌지 않는다.
- ``RecordedLLM``에 같은 사이드카를 주면, 응답 녹화에 없고 사이드카에 있는 요청은 같은 code의 오류로 재생한다.
  live 녹화 때 오류로 ``judge_failed``가 된 요청이 recorded 재생에서도 같은 결과를 낸다. 같은 요청의 응답 행이
  있으면(``--append``로 다시 녹화해 성공한 경우) 응답이 이긴다.
- 지금은 판정기 녹화(``judge.<id>.jsonl``)에서만 켠다. 분석기는 워커 재시도가 있어 같은 요청이 오류 뒤 성공할 수
  있으므로 켜지 않는다 (T25p 보고서 남은 문제).
"""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ValidationError

from jupjup.domain.errors import (
    JupjupError,
    LLMCacheMiss,
    LLMContextOverflowError,
    LLMProviderError,
    LLMTimeoutError,
)
from jupjup.providers.llm import LLMClient, LLMRawResponse, prompt_hash

_FORMAT_VERSION = 2
RowKind = Literal["complete_json", "count_tokens"]
_FAILURE_KIND = "complete_json_error"
_REPLAYED_ERRORS: dict[str, type[LLMProviderError]] = {
    LLMTimeoutError.code: LLMTimeoutError,
    LLMContextOverflowError.code: LLMContextOverflowError,
}
_RowKey = tuple[str, str, str]  # (kind, model_id, request_hash)
_SCHEMA_ANNOTATIONS = frozenset(
    {"title", "description", "default", "examples", "$comment", "deprecated", "readOnly", "writeOnly"}
)
_NAMED_SCHEMA_MAPS = frozenset({"$defs", "properties", "patternProperties", "dependentSchemas"})


def _canonical_hash(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def schema_fingerprint(schema: type[BaseModel]) -> str:
    """문서 문구를 제외한 필드 구조가 다르면 다른 값을 내는 스키마 지문."""
    return _canonical_hash({"name": schema.__name__, "structure": _schema_structure(schema.model_json_schema())})


def _schema_structure(value: Any, *, named_children: bool = False) -> Any:
    if isinstance(value, dict):
        if named_children:
            return {key: _schema_structure(item) for key, item in sorted(value.items())}
        return {
            key: _schema_structure(item, named_children=key in _NAMED_SCHEMA_MAPS)
            for key, item in sorted(value.items())
            if key not in _SCHEMA_ANNOTATIONS
        }
    if isinstance(value, list):
        return [_schema_structure(item) for item in value]
    return value


def complete_request_hash(system: str, user: str, schema: type[BaseModel], max_tokens: int, effort: str | None) -> str:
    return _canonical_hash(
        {
            "kind": "complete_json",
            "system": system,
            "user": user,
            "schema": schema_fingerprint(schema),
            "max_tokens": max_tokens,
            "effort": effort,
        }
    )


def count_request_hash(system: str, user: str) -> str:
    return _canonical_hash({"kind": "count_tokens", "system": system, "user": user})


def _load_rows(path: Path) -> dict[_RowKey, Any]:
    """행을 읽어 ``{(kind, model_id, request_hash): LLMRawResponse | int | None}``로 돌려준다."""
    rows: dict[_RowKey, Any] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise LLMProviderError("LLM 녹화본을 읽지 못했습니다", {"path": str(path)}) from exc

    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            if not isinstance(row, dict) or row.get("format_version") != _FORMAT_VERSION:
                raise ValueError("지원하지 않는 녹화 형식(v2만 읽는다. v1 녹화본은 다시 녹화해야 한다)")
            kind = row["kind"]
            model_id = row["model_id"]
            digest = row["request_hash"]
            if not isinstance(model_id, str) or not isinstance(digest, str):
                raise ValueError("model_id와 request_hash는 문자열이어야 함")
            value: Any
            if kind == "complete_json":
                value = LLMRawResponse.model_validate(row["response"])
            elif kind == "count_tokens":
                value = row["input_tokens"]
                if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 0):
                    raise ValueError("input_tokens는 0 이상의 정수 또는 null이어야 함")
            else:
                raise ValueError("알 수 없는 kind")
        except (KeyError, TypeError, ValueError, ValidationError) as exc:
            raise LLMProviderError(
                "LLM 녹화본 형식이 올바르지 않습니다",
                {"path": str(path), "line": line_number},
            ) from exc

        key: _RowKey = (kind, model_id, digest)
        if key in rows and rows[key] != value:
            raise LLMProviderError(
                "같은 요청의 LLM 녹화 응답이 서로 다릅니다",
                {"path": str(path), "line": line_number, "request_hash": digest},
            )
        rows[key] = value
    return rows


def failure_store_path(store_path: Path) -> Path:
    """분석기·판정기 응답 녹화의 오류 사이드카 ``<stem>.failures.jsonl``."""
    return store_path.with_name(f"{store_path.stem}.failures.jsonl")


def _load_failures(path: Path) -> dict[_RowKey, dict[str, Any]]:
    """오류 사이드카를 읽어 ``{(complete_json, model_id, request_hash): {"code", "retryable"}}``로 돌려준다."""
    failures: dict[_RowKey, dict[str, Any]] = {}
    if not path.exists():
        return failures
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise LLMProviderError("LLM 오류 녹화본을 읽지 못했습니다", {"path": str(path)}) from exc
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            if not isinstance(row, dict) or row.get("format_version") != _FORMAT_VERSION:
                raise ValueError("지원하지 않는 녹화 형식")
            if row["kind"] != _FAILURE_KIND:
                raise ValueError("알 수 없는 kind")
            error = row["error"]
            if not isinstance(error, dict) or not isinstance(error.get("code"), str):
                raise ValueError("error.code가 필요함")
            model_id, digest = row["model_id"], row["request_hash"]
            if not isinstance(model_id, str) or not isinstance(digest, str):
                raise ValueError("model_id와 request_hash는 문자열이어야 함")
        except (KeyError, TypeError, ValueError) as exc:
            raise LLMProviderError(
                "LLM 오류 녹화본 형식이 올바르지 않습니다", {"path": str(path), "line": line_number}
            ) from exc
        failures[("complete_json", model_id, digest)] = error
    return failures


def _replayed_error(error: dict[str, Any], digest: str) -> LLMProviderError:
    code = str(error["code"])
    details: dict[str, Any] = {"replayed": True, "request_hash": digest}
    if isinstance(error.get("retryable"), bool):
        details["retryable"] = error["retryable"]
    exc = _REPLAYED_ERRORS.get(code, LLMProviderError)("녹화된 LLM 오류를 재생합니다", details)
    exc.code = code  # 원래 code 그대로 (LLM_UNAVAILABLE 등 다른 code도 보존)
    return exc


class RecordingLLM:
    """Delegate to an LLM and append each new request (see module docstring) once."""

    def __init__(self, inner: LLMClient, store_path: Path, *, failures_path: Path | None = None) -> None:
        self.inner = inner
        self.model_id = inner.model_id
        self.store_path = store_path
        self.failures_path = failures_path
        self._lock = threading.Lock()
        self._store: dict[_RowKey, Any] = {}
        self._seen_failures: set[_RowKey] = set()
        if store_path.exists():
            self._store.update(_load_rows(store_path))
        if failures_path is not None:
            self._seen_failures.update(_load_failures(failures_path))

    def complete_json(
        self,
        system: str,
        user: str,
        schema: type[BaseModel],
        timeout_s: float,
        max_tokens: int = 4000,
        effort: str | None = None,
    ) -> LLMRawResponse:
        digest = complete_request_hash(system, user, schema, max_tokens, effort)
        key: _RowKey = ("complete_json", self.model_id, digest)
        with self._lock:
            recorded = self._store.get(key)
            if isinstance(recorded, LLMRawResponse):
                return recorded.model_copy(deep=True)
        fields: dict[str, Any] = {
            "prompt_hash": prompt_hash(system, user),
            "schema_name": schema.__name__,
            "max_tokens": max_tokens,
            "effort": effort,
        }
        try:
            response = self.inner.complete_json(system, user, schema, timeout_s, max_tokens, effort)
        except LLMCacheMiss:
            raise
        except JupjupError as exc:
            if self.failures_path is not None:
                self._append_failure(digest, fields, exc)
            raise
        self._append("complete_json", digest, {**fields, "response": response.model_dump(mode="json")})
        return response

    def _append_failure(self, digest: str, fields: dict[str, Any], exc: JupjupError) -> None:
        path = self.failures_path
        if path is None:
            return
        key: _RowKey = ("complete_json", self.model_id, digest)
        retryable = exc.details.get("retryable")
        row = {
            "format_version": _FORMAT_VERSION,
            "kind": _FAILURE_KIND,
            "model_id": self.model_id,
            "request_hash": digest,
            **fields,
            # 오류 메시지·details는 원문 일부를 품을 수 있어 남기지 않는다. code와 retryable만.
            "error": {"code": exc.code, "retryable": retryable if isinstance(retryable, bool) else None},
        }
        with self._lock:
            if key in self._seen_failures:
                return
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("a", encoding="utf-8") as file:
                    file.write(json.dumps(row, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n")
            except OSError as error:
                raise LLMProviderError("LLM 오류 녹화본을 쓰지 못했습니다", {"path": str(path)}) from error
            self._seen_failures.add(key)

    def count_tokens(self, system: str, user: str) -> int | None:
        digest = count_request_hash(system, user)
        key: _RowKey = ("count_tokens", self.model_id, digest)
        with self._lock:
            if key in self._store:
                tokens = self._store[key]
                return tokens if isinstance(tokens, int) and not isinstance(tokens, bool) else None
        tokens = self.inner.count_tokens(system, user)
        self._append(
            "count_tokens",
            digest,
            {"prompt_hash": prompt_hash(system, user), "input_tokens": tokens},
        )
        return tokens

    def _append(self, kind: RowKind, digest: str, fields: dict[str, Any]) -> None:
        key: _RowKey = (kind, self.model_id, digest)
        with self._lock:
            if key in self._store:
                return
            row = {
                "format_version": _FORMAT_VERSION,
                "kind": kind,
                "model_id": self.model_id,
                "request_hash": digest,
                **fields,
            }
            try:
                self.store_path.parent.mkdir(parents=True, exist_ok=True)
                with self.store_path.open("a", encoding="utf-8") as file:
                    file.write(json.dumps(row, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n")
            except OSError as exc:
                raise LLMProviderError("LLM 녹화본을 쓰지 못했습니다", {"path": str(self.store_path)}) from exc
            self._store[key] = (
                LLMRawResponse.model_validate(fields["response"])
                if kind == "complete_json"
                else fields["input_tokens"]
            )


class RecordedLLM:
    """Replay committed responses without network access; misses fail explicitly."""

    def __init__(self, store_path: Path, model_id: str, *, failures_path: Path | None = None) -> None:
        self.store_path = store_path
        self.model_id = model_id
        if not store_path.exists() and (failures_path is None or not failures_path.exists()):
            raise LLMProviderError("LLM 녹화본 파일이 없습니다", {"path": str(store_path)})
        self._store = _load_rows(store_path) if store_path.exists() else {}
        self._failures = {} if failures_path is None else _load_failures(failures_path)

    def complete_json(
        self,
        system: str,
        user: str,
        schema: type[BaseModel],
        timeout_s: float,
        max_tokens: int = 4000,
        effort: str | None = None,
    ) -> LLMRawResponse:
        del timeout_s
        digest = complete_request_hash(system, user, schema, max_tokens, effort)
        key: _RowKey = ("complete_json", self.model_id, digest)
        response = self._store.get(key)
        if not isinstance(response, LLMRawResponse):
            if response is not None:
                raise LLMProviderError("LLM 녹화본 요청 종류가 올바르지 않습니다", {"request_hash": digest})
            failure = self._failures.get(key)
            if failure is not None:
                raise _replayed_error(failure, digest)
            raise LLMCacheMiss(
                "녹화본에 없는 LLM 요청입니다",
                {
                    "model_id": self.model_id,
                    "request_hash": digest,
                    "prompt_hash": prompt_hash(system, user),
                    "schema_name": schema.__name__,
                    "max_tokens": max_tokens,
                    "effort": effort,
                },
            )
        return response.model_copy(deep=True)

    def count_tokens(self, system: str, user: str) -> int | None:
        key: _RowKey = ("count_tokens", self.model_id, count_request_hash(system, user))
        if key not in self._store:
            raise LLMCacheMiss(
                "녹화본에 없는 count_tokens 요청입니다",
                {"model_id": self.model_id, "prompt_hash": prompt_hash(system, user)},
            )
        tokens = self._store[key]
        if tokens is not None and (not isinstance(tokens, int) or isinstance(tokens, bool)):
            raise LLMProviderError("count_tokens 녹화값이 올바르지 않습니다", {"request_hash": key[2]})
        return tokens

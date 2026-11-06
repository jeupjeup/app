"""Cross-encoder protocols plus deterministic mock/record/replay adapters."""

from __future__ import annotations

import hashlib
import json
import math
import re
import threading
import time
from collections.abc import Collection, Sequence
from pathlib import Path
from typing import Protocol

from jupjup.domain.errors import RerankCacheMiss, RerankerError
from jupjup.text.normalize import normalize_text

_KEEP = re.compile(r"[^0-9a-z가-힣]+")


def resolve_rerank_dtype(configured: str, device: str) -> str:
    if configured != "auto":
        return configured
    return "fp16" if device == "mps" else "fp32"


class Reranker(Protocol):
    model_id: str
    revision: str
    is_replay: bool

    def score_logits(self, query: str, documents: Sequence[str]) -> list[float]: ...


def _grams(text: str, n: int = 2) -> set[str]:
    normalized = _KEEP.sub("", normalize_text(text))
    if len(normalized) < n:
        return {normalized} if normalized else set()
    return {normalized[index : index + n] for index in range(len(normalized) - n + 1)}


def rerank_pair_hash(model_id: str, revision: str, max_length: int, query: str, document: str) -> str:
    value = "\x00".join((model_id, revision, str(max_length), query, document))
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class MockReranker:
    """Deterministic character Jaccard reranker with failure/latency injection."""

    model_id = "mock-reranker-v1"
    revision = "fixture-1"
    is_replay = False

    def __init__(self, delay_ms: int = 0, fail_on: Collection[str] = ()) -> None:
        self.delay_ms = delay_ms
        self.fail_on = set(fail_on)

    def score_logits(self, query: str, documents: Sequence[str]) -> list[float]:
        if self.delay_ms:
            time.sleep(self.delay_ms / 1000)
        if query in self.fail_on:
            raise RerankerError("mock reranker failure")
        query_grams = _grams(query)
        logits: list[float] = []
        for document in documents:
            document_grams = _grams(document)
            union = query_grams | document_grams
            score = len(query_grams & document_grams) / len(union) if union else 0.0
            probability = min(1.0 - 1e-6, max(1e-6, score))
            logits.append(math.log(probability / (1.0 - probability)))
        return logits


class RecordingReranker:
    is_replay = False

    def __init__(self, inner: Reranker, store_path: Path, max_length: int) -> None:
        self.inner = inner
        self.model_id = inner.model_id
        self.revision = inner.revision
        self.store_path = store_path
        self.max_length = max_length
        self.device = str(getattr(inner, "device", "unknown"))
        configured_dtype = str(getattr(getattr(inner, "settings", None), "dtype", "unknown"))
        self.dtype = resolve_rerank_dtype(configured_dtype, self.device)
        self._lock = threading.Lock()
        self._seen: set[str] = set()
        if store_path.exists():
            for line in store_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    self._seen.add(str(json.loads(line)["pair_hash"]))

    def score_logits(self, query: str, documents: Sequence[str]) -> list[float]:
        logits = self.inner.score_logits(query, documents)
        if len(logits) != len(documents):
            raise RerankerError("리랭커 점수 개수가 문서 개수와 다릅니다")
        query_hash = hashlib.sha256(query.encode("utf-8")).hexdigest()
        with self._lock:
            self.store_path.parent.mkdir(parents=True, exist_ok=True)
            with self.store_path.open("a", encoding="utf-8") as handle:
                for document, logit in zip(documents, logits, strict=True):
                    pair_hash = rerank_pair_hash(self.model_id, self.revision, self.max_length, query, document)
                    if pair_hash in self._seen:
                        continue
                    self._seen.add(pair_hash)
                    row = {
                        "model_id": self.model_id,
                        "revision": self.revision,
                        "pair_hash": pair_hash,
                        "query_hash": query_hash,
                        "doc_hash": hashlib.sha256(document.encode("utf-8")).hexdigest(),
                        "max_length": self.max_length,
                        "device": self.device,
                        "dtype": self.dtype,
                        "logit": float(logit),
                    }
                    handle.write(json.dumps(row, separators=(",", ":"), sort_keys=True) + "\n")
        return logits


class RecordedReranker:
    is_replay = True

    def __init__(self, store_path: Path, model_id: str, revision: str, max_length: int) -> None:
        self.model_id = model_id
        self.revision = revision
        self.max_length = max_length
        self._store: dict[str, float] = {}
        if not store_path.exists():
            raise RerankerError("리랭커 녹화본 파일이 없습니다", {"path": str(store_path)})
        for line in store_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if (
                row.get("model_id") == model_id
                and row.get("revision") == revision
                and row.get("max_length") == max_length
            ):
                self._store[str(row["pair_hash"])] = float(row["logit"])

    def score_logits(self, query: str, documents: Sequence[str]) -> list[float]:
        output: list[float] = []
        query_hash = hashlib.sha256(query.encode("utf-8")).hexdigest()
        for document in documents:
            pair_hash = rerank_pair_hash(self.model_id, self.revision, self.max_length, query, document)
            if pair_hash not in self._store:
                raise RerankCacheMiss(
                    "리랭커 녹화본에 없는 쌍입니다",
                    {"pair_hash": pair_hash, "query_hash": query_hash},
                )
            output.append(self._store[pair_hash])
        return output

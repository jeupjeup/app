"""임베딩 제공자 (설계서 3.3.2절, 3.3.3절, 5.8.4절).

HashingEmbedder는 결정적이다. 파이썬 hash()를 쓰지 않고 blake2b로 특징을 해시한다.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
from base64 import b64decode, b64encode
from collections.abc import Sequence
from pathlib import Path
from typing import Literal, Protocol

import numpy as np

from jupjup.domain.errors import EmbeddingCacheMiss, EmbeddingProviderError
from jupjup.text.lexicon import Lexicon
from jupjup.text.normalize import normalize_text
from jupjup.text.tokenizer import Tokenizer

EmbedKind = Literal["query", "document"]
_KEEP = re.compile(r"[^0-9a-z가-힣]+")


class Embedder(Protocol):
    model_id: str
    dim: int

    def embed(self, texts: Sequence[str], kind: EmbedKind) -> np.ndarray: ...


def l2_normalize(m: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    out: np.ndarray = (m / norms).astype(np.float32)
    return out


def embedding_key(kind: str, text: str) -> str:
    return hashlib.sha256(f"{kind}\x00{text}".encode()).hexdigest()


class HashingEmbedder:
    """문자 2/3-gram + 형태소 토큰(동의어 정규형)을 부호 있는 해시로 누적한 뒤 L2 정규화."""

    model_id = "hashing-v1"

    def __init__(
        self,
        lexicon: Lexicon,
        tokenizer: Tokenizer,
        dim: int = 384,
        morph_weight: float = 1.0,
        ngram_weight: float = 0.5,
    ) -> None:
        if dim <= 0:
            raise ValueError("dim은 양수")
        self.lexicon = lexicon
        self.tokenizer = tokenizer
        self.dim = dim
        self.morph_weight = morph_weight
        self.ngram_weight = ngram_weight

    def _features(self, text: str) -> list[tuple[str, float]]:
        norm = normalize_text(text)
        feats: list[tuple[str, float]] = [("m:" + t, self.morph_weight) for t in self.tokenizer.index_terms(norm)]
        for word in norm.split():
            w = _KEEP.sub("", self.lexicon.canonical(word))
            for n in (2, 3):
                for i in range(len(w) - n + 1):
                    feats.append((f"c{n}:" + w[i : i + n], self.ngram_weight))
        return feats

    def _vector(self, text: str) -> np.ndarray:
        v = np.zeros(self.dim, dtype=np.float64)
        for feat, weight in self._features(text):
            h = int.from_bytes(hashlib.blake2b(feat.encode("utf-8"), digest_size=8).digest(), "little")
            v[h % self.dim] += weight if (h >> 63) & 1 else -weight
        return v

    def embed(self, texts: Sequence[str], kind: EmbedKind) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        m = np.stack([self._vector(t) for t in texts])
        return l2_normalize(m)


class RecordingEmbedder:
    """live 제공자를 감싸 (model_id, text_hash) → vector를 jsonl에 녹화한다."""

    def __init__(self, inner: Embedder, store_path: Path) -> None:
        self.inner = inner
        self.model_id = inner.model_id
        self.dim = inner.dim
        self.store_path = store_path
        self._lock = threading.Lock()
        self._seen: set[str] = set()
        if store_path.exists():
            for line in store_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    self._seen.add(json.loads(line)["text_hash"])

    def embed(self, texts: Sequence[str], kind: EmbedKind) -> np.ndarray:
        vecs = self.inner.embed(texts, kind)
        with self._lock:
            self.store_path.parent.mkdir(parents=True, exist_ok=True)
            with self.store_path.open("a", encoding="utf-8") as f:
                for t, v in zip(texts, vecs, strict=True):
                    key = embedding_key(kind, t)
                    if key not in self._seen:
                        self._seen.add(key)
                        f.write(
                            json.dumps(
                                {
                                    "model_id": self.model_id,
                                    "text_hash": key,
                                    "kind": kind,
                                    "encoding": "float32-base64",
                                    "vector_b64": b64encode(np.asarray(v, dtype="<f4").tobytes()).decode("ascii"),
                                },
                                separators=(",", ":"),
                            )
                            + "\n"
                        )
        return vecs


class RecordedEmbedder:
    """녹화본만 재생한다. 녹화본에 없는 텍스트는 EmbeddingCacheMiss (조용히 넘어가지 않는다)."""

    def __init__(self, store_path: Path, model_id: str, dim: int) -> None:
        self.model_id = model_id
        self.dim = dim
        self._store: dict[str, np.ndarray] = {}
        if not store_path.exists():
            raise EmbeddingProviderError("녹화본 파일이 없습니다", {"path": str(store_path)})
        for line in store_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("model_id") != model_id:
                continue
            if row.get("encoding") == "float32-base64":
                try:
                    vec = np.frombuffer(b64decode(row["vector_b64"], validate=True), dtype="<f4").copy()
                except (KeyError, ValueError) as exc:
                    raise EmbeddingProviderError("녹화본 벡터 인코딩이 올바르지 않습니다") from exc
            else:
                vec = np.asarray(row["vector"], dtype=np.float32)
            if vec.shape[0] != dim:
                raise EmbeddingProviderError("녹화본 차원 불일치", {"expected": dim, "got": int(vec.shape[0])})
            self._store[row["text_hash"]] = vec

    def embed(self, texts: Sequence[str], kind: EmbedKind) -> np.ndarray:
        out = []
        for t in texts:
            key = embedding_key(kind, t)
            vec = self._store.get(key)
            if vec is None:
                raise EmbeddingCacheMiss("녹화본에 없는 텍스트입니다", {"text_hash": key, "kind": kind})
            out.append(vec)
        if not out:
            return np.zeros((0, self.dim), dtype=np.float32)
        return np.stack(out).astype(np.float32)

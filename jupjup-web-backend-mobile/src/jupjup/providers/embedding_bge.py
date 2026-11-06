"""로컬 BAAI/bge-m3 임베딩 제공자.

무거운 의존성은 ``embed`` extra에만 들어 있다. 이 모듈은 sentence-transformers를 지연 import하므로
기본 mock/recorded 경로는 torch 없이도 import하고 실행할 수 있다.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from threading import Lock
from typing import Any, Literal, Protocol, cast

import numpy as np

from jupjup.domain.errors import EmbeddingProviderError
from jupjup.providers.embedding import EmbedKind, l2_normalize

Device = Literal["auto", "cpu", "mps"]


class SentenceEncoder(Protocol):
    def encode(self, sentences: list[str], **kwargs: Any) -> Any: ...


ModelFactory = Callable[[str, str, Path], SentenceEncoder]


def _select_device(device: Device) -> str:
    if device != "auto":
        return device
    try:
        import torch
    except ImportError:
        return "cpu"
    return "mps" if torch.backends.mps.is_available() else "cpu"


def _load_sentence_transformer(model_name: str, device: str, cache_dir: Path) -> SentenceEncoder:
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise EmbeddingProviderError(
            "bge-m3를 사용하려면 embed extra를 설치하세요: uv sync --extra embed",
            {"model": model_name},
        ) from exc
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cast(SentenceEncoder, SentenceTransformer(model_name, device=device, cache_folder=str(cache_dir)))


class BgeM3Embedder:
    """sentence-transformers 기반 dense bge-m3 어댑터."""

    model_id = "bge-m3"
    dim = 1024

    def __init__(
        self,
        model_name: str = "BAAI/bge-m3",
        device: Device = "auto",
        batch_size: int = 16,
        cache_dir: Path | None = None,
        *,
        model_factory: ModelFactory | None = None,
    ) -> None:
        if batch_size <= 0:
            raise ValueError("batch_size는 양수여야 합니다")
        self.model_name = model_name
        self.device = _select_device(device)
        self.batch_size = batch_size
        self.cache_dir = cache_dir or Path("var/models")
        self._model_factory = model_factory or _load_sentence_transformer
        self._model: SentenceEncoder | None = None
        self._lock = Lock()

    def _get_model(self) -> SentenceEncoder:
        if self._model is None:
            self._model = self._model_factory(self.model_name, self.device, self.cache_dir)
        return self._model

    def embed(self, texts: Sequence[str], kind: EmbedKind) -> np.ndarray:
        del kind  # bge-m3는 query/document에 같은 dense 인코더를 쓴다.
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        try:
            with self._lock:
                encoded = self._get_model().encode(
                    list(texts),
                    batch_size=self.batch_size,
                    convert_to_numpy=True,
                    normalize_embeddings=True,
                    show_progress_bar=False,
                    device=self.device,
                )
            matrix = np.asarray(encoded, dtype=np.float32)
        except EmbeddingProviderError:
            raise
        except Exception as exc:
            raise EmbeddingProviderError(
                "bge-m3 임베딩 생성에 실패했습니다",
                {"model": self.model_name, "device": self.device, "error": type(exc).__name__},
            ) from exc
        if matrix.shape != (len(texts), self.dim):
            raise EmbeddingProviderError(
                "bge-m3 임베딩 shape가 올바르지 않습니다",
                {"expected": [len(texts), self.dim], "got": list(matrix.shape)},
            )
        if not np.isfinite(matrix).all():
            raise EmbeddingProviderError("bge-m3 임베딩에 유한하지 않은 값이 있습니다")
        return l2_normalize(matrix)

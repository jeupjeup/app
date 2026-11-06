"""Lazy optional adapter for BAAI/bge-reranker-v2-m3."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from threading import Lock
from typing import Any, Protocol, cast

import numpy as np

from jupjup.config import RerankModelSettings
from jupjup.domain.errors import RerankerError, RerankerUnavailable
from jupjup.providers.rerank import resolve_rerank_dtype


class CrossEncoderModel(Protocol):
    def predict(self, sentences: list[list[str]], **kwargs: Any) -> Any: ...


ModelFactory = Callable[[RerankModelSettings, str, Path], CrossEncoderModel]


def select_device(device: str) -> str:
    if device != "auto":
        return device
    try:
        import torch
    except ImportError:
        return "cpu"
    return "mps" if torch.backends.mps.is_available() else "cpu"


def _identity[T](value: T) -> T:
    """Return raw logits without importing the optional torch dependency."""
    return value


def _load_model(settings: RerankModelSettings, device: str, cache_dir: Path) -> CrossEncoderModel:
    try:
        from sentence_transformers import CrossEncoder
    except ImportError as exc:
        raise RerankerUnavailable(
            "bge 리랭커를 사용하려면 rerank extra를 설치하세요: uv sync --extra rerank",
            {"model": settings.model_name},
        ) from exc
    cache_dir.mkdir(parents=True, exist_ok=True)
    try:
        model = CrossEncoder(
            settings.model_name,
            revision=settings.revision,
            device=device,
            cache_folder=str(cache_dir),
            max_length=settings.max_length,
            trust_remote_code=False,
        )
        if resolve_rerank_dtype(settings.dtype, device) == "fp16":
            model.half()
        return cast(CrossEncoderModel, model)
    except Exception as exc:
        raise RerankerUnavailable(
            "bge 리랭커 모델을 불러오지 못했습니다",
            {"model": settings.model_name, "revision": settings.revision, "error": type(exc).__name__},
        ) from exc


class BgeCrossEncoderReranker:
    is_replay = False

    def __init__(
        self,
        settings: RerankModelSettings,
        cache_dir: Path | None = None,
        *,
        model_factory: ModelFactory | None = None,
    ) -> None:
        if not settings.revision:
            raise RerankerUnavailable("리랭커 revision이 비어 있습니다")
        self.settings = settings
        self.model_id = settings.model_id
        self.revision = settings.revision
        self.device = select_device(settings.device)
        self.cache_dir = cache_dir or Path("var/models")
        self._factory = model_factory or _load_model
        self._model: CrossEncoderModel | None = None
        self._lock = Lock()

    def _get_model(self) -> CrossEncoderModel:
        if self._model is None:
            self._model = self._factory(self.settings, self.device, self.cache_dir)
        return self._model

    def score_logits(self, query: str, documents: Sequence[str]) -> list[float]:
        if not documents:
            return []
        try:
            with self._lock:
                values = self._get_model().predict(
                    [[query, document] for document in documents],
                    batch_size=len(documents),
                    show_progress_bar=False,
                    convert_to_numpy=True,
                    activation_fn=_identity,  # 녹화·calibration은 sigmoid 전 원 로짓을 쓴다
                )
            array = np.asarray(values, dtype=np.float64).reshape(-1)
        except (RerankerError, RerankerUnavailable):
            raise
        except Exception as exc:
            raise RerankerError(
                "bge 리랭커 추론에 실패했습니다",
                {"model": self.settings.model_name, "device": self.device, "error": type(exc).__name__},
            ) from exc
        if array.shape != (len(documents),) or not np.isfinite(array).all():
            raise RerankerError("bge 리랭커 출력이 올바르지 않습니다", {"shape": list(array.shape)})
        return [float(value) for value in array]

    def warm_up(self) -> None:
        self.score_logits("검색 질의", ["관련 문서", "무관 문서", "다국어 문서", "짧은 문서"])

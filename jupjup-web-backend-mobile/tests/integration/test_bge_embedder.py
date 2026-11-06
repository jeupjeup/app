"""실제 bge-m3 통합 테스트. ``uv run --extra embed pytest -m embed``로만 실행한다."""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

from jupjup.providers.embedding_bge import BgeM3Embedder

pytestmark = pytest.mark.embed


def test_real_bge_m3_embeddings() -> None:
    pytest.importorskip("sentence_transformers")
    cache_dir = Path(os.environ.get("JUPJUP_BGE_CACHE_DIR", "var/models"))
    embedder = BgeM3Embedder(cache_dir=cache_dir, batch_size=2)
    matrix = embedder.embed(["성수동 카페", "기후변화 논문"], "document")
    assert matrix.shape == (2, 1024)
    assert matrix.dtype == np.float32
    assert np.allclose(np.linalg.norm(matrix, axis=1), 1.0, atol=1e-5)
    assert float(matrix[0] @ matrix[1]) < 0.95

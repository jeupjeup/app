"""T10: Embedder 3종, MockLLM, MockReranker."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from pydantic import BaseModel

from jupjup.domain.errors import EmbeddingCacheMiss, EmbeddingProviderError, LLMProviderError
from jupjup.providers.embedding import HashingEmbedder, RecordedEmbedder, RecordingEmbedder, embedding_key
from jupjup.providers.embedding_bge import BgeM3Embedder
from jupjup.providers.llm import MockLLM, prompt_hash
from jupjup.providers.rerank import MockReranker
from jupjup.text.lexicon import Lexicon
from jupjup.text.tokenizer import KiwiTokenizer


@pytest.fixture(scope="module")
def emb(lexicon: Lexicon, kiwi: KiwiTokenizer) -> HashingEmbedder:
    return HashingEmbedder(lexicon, kiwi)


def test_hashing_shape_and_norm(emb: HashingEmbedder) -> None:
    m = emb.embed(["성수동 카페", "기후변화 논문", ""], "document")
    assert m.shape == (3, 384) and m.dtype == np.float32
    assert np.allclose(np.linalg.norm(m[:2], axis=1), 1.0, atol=1e-5)
    assert np.allclose(m[2], 0.0)  # 빈 텍스트는 0 벡터
    assert emb.embed([], "query").shape == (0, 384)


def test_hashing_deterministic_in_process(emb: HashingEmbedder) -> None:
    a = emb.embed(["지난달 인스타에서 본 성수동 카페"], "query")
    b = emb.embed(["지난달 인스타에서 본 성수동 카페"], "query")
    assert np.array_equal(a, b)


def test_hashing_deterministic_across_processes() -> None:
    code = (
        "from pathlib import Path;import hashlib;from jupjup.text.lexicon import Lexicon;"
        "from jupjup.text.tokenizer import KiwiTokenizer;from jupjup.providers.embedding import HashingEmbedder;"
        "lx=Lexicon.load(Path('data/lexicon'));e=HashingEmbedder(lx,KiwiTokenizer(lx));"
        "print(hashlib.sha256(e.embed(['성수동 카페 팡도르','기후변화 논문'],'document').tobytes()).hexdigest())"
    )
    outs = set()
    for seed in ("1", "2"):  # 파이썬 해시 시드를 바꿔도 같아야 한다
        r = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            check=True,
            env={"PYTHONHASHSEED": seed, "PATH": "/usr/bin:/bin"},
        )
        outs.add(r.stdout.strip())
    assert len(outs) == 1


def test_hashing_synonyms_close(emb: HashingEmbedder) -> None:
    m = emb.embed(["성수동 커피숍", "성수동 카페", "기후변화 논문"], "document")
    sim_syn = float(m[0] @ m[1])
    sim_far = float(m[0] @ m[2])
    assert sim_syn > 0.5 > sim_far


def test_recording_then_recorded(tmp_path: Path, emb: HashingEmbedder) -> None:
    store = tmp_path / "rec" / "embeddings.hashing-v1.jsonl"
    rec = RecordingEmbedder(emb, store)
    v1 = rec.embed(["성수동 카페", "성수동 카페"], "document")
    rec.embed(["성수동 카페"], "document")  # 중복은 다시 쓰지 않는다
    lines = store.read_text(encoding="utf-8").splitlines()
    row = json.loads(lines[0])
    assert len(lines) == 1 and row["text_hash"] == embedding_key("document", "성수동 카페")
    assert row["encoding"] == "float32-base64" and "vector" not in row
    replay = RecordedEmbedder(store, "hashing-v1", 384)
    assert np.allclose(replay.embed(["성수동 카페"], "document"), v1[:1], atol=1e-6)
    with pytest.raises(EmbeddingCacheMiss):
        replay.embed(["녹화 안 된 문장"], "document")
    with pytest.raises(EmbeddingCacheMiss):
        replay.embed(["성수동 카페"], "query")  # kind가 다르면 다른 키


def test_recorded_missing_file_and_dim(tmp_path: Path) -> None:
    with pytest.raises(EmbeddingProviderError):
        RecordedEmbedder(tmp_path / "none.jsonl", "m", 4)
    p = tmp_path / "x.jsonl"
    p.write_text(json.dumps({"model_id": "m", "text_hash": "h", "vector": [0.1, 0.2]}) + "\n", encoding="utf-8")
    with pytest.raises(EmbeddingProviderError):
        RecordedEmbedder(p, "m", 4)


class _FakeSentenceEncoder:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], dict[str, object]]] = []

    def encode(self, sentences: list[str], **kwargs: object) -> np.ndarray:
        self.calls.append((sentences, kwargs))
        rows = []
        for index, _ in enumerate(sentences, 1):
            row = np.zeros(1024, dtype=np.float32)
            row[0] = index
            row[1] = index + 1
            rows.append(row)
        return np.stack(rows)


def test_bge_adapter_batches_normalizes_and_loads_lazily(tmp_path: Path) -> None:
    fake = _FakeSentenceEncoder()
    factory_calls: list[tuple[str, str, Path]] = []

    def factory(model_name: str, device: str, cache_dir: Path) -> _FakeSentenceEncoder:
        factory_calls.append((model_name, device, cache_dir))
        return fake

    emb = BgeM3Embedder(device="cpu", batch_size=7, cache_dir=tmp_path, model_factory=factory)
    assert factory_calls == []
    assert emb.embed([], "query").shape == (0, 1024)
    matrix = emb.embed(["성수동 카페", "기후변화 논문"], "query")
    assert matrix.shape == (2, 1024) and matrix.dtype == np.float32
    assert np.allclose(np.linalg.norm(matrix, axis=1), 1.0)
    assert factory_calls == [("BAAI/bge-m3", "cpu", tmp_path)]
    assert fake.calls[0][1]["batch_size"] == 7
    assert fake.calls[0][1]["normalize_embeddings"] is True


def test_bge_adapter_wraps_provider_failures(tmp_path: Path) -> None:
    class Broken:
        def encode(self, sentences: list[str], **kwargs: object) -> np.ndarray:
            raise RuntimeError("boom")

    emb = BgeM3Embedder(device="cpu", cache_dir=tmp_path, model_factory=lambda *_: Broken())
    with pytest.raises(EmbeddingProviderError, match="bge-m3 임베딩 생성"):
        emb.embed(["실패"], "document")


class Out(BaseModel):
    keywords: list[str] = []


def test_mock_llm() -> None:
    llm = MockLLM(
        {
            prompt_hash("s", "u"): {"keywords": ["a"]},
            prompt_hash("s", "bad"): LLMProviderError("x"),
            prompt_hash("s", "raw"): "not json",
        }
    )
    assert json.loads(llm.complete_json("s", "u", Out, 1.0).text) == {"keywords": ["a"]}
    assert json.loads(llm.complete_json("s", "unknown", Out, 1.0).text) == {"keywords": []}
    assert llm.complete_json("s", "raw", Out, 1.0).text == "not json"
    with pytest.raises(LLMProviderError):
        llm.complete_json("s", "bad", Out, 1.0)
    assert llm.count_tokens("s", "u") is None and len(llm.calls) == 4


def test_mock_reranker() -> None:
    r = MockReranker()
    s = r.score_logits("성수동 카페", ["성수동 카페 어니언", "기후변화 논문", ""])
    # 원 로짓을 돌려준다: 일치가 많을수록 크고, 겹침이 없으면 최솟값(같은 값)이다.
    assert s[0] > s[1] == s[2]
    assert r.score_logits("성수동 카페", ["성수동 카페"])[0] > 10.0
    assert r.score_logits("성수동 카페", ["성수동 카페"]) == r.score_logits("성수동 카페", ["성수동 카페"])

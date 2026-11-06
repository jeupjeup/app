"""실제 bge-reranker-v2-m3 통합 테스트. ``uv run --extra rerank pytest -m rerank``로만 실행한다."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from jupjup.config import RerankModelSettings
from jupjup.providers.rerank import RecordedReranker
from jupjup.providers.rerank_bge import BgeCrossEncoderReranker
from tests.conftest import ROOT

pytestmark = pytest.mark.rerank

CACHE = Path(os.environ.get("JUPJUP_RERANK_CACHE_DIR", "var/models"))
RECORDING = ROOT / "data" / "recordings" / "rerank.bge-reranker-v2-m3.jsonl"


@pytest.fixture(scope="module")
def model() -> BgeCrossEncoderReranker:
    pytest.importorskip("sentence_transformers")
    reranker = BgeCrossEncoderReranker(RerankModelSettings(device="cpu", dtype="fp32"), CACHE)
    reranker.warm_up()
    return reranker


def test_real_reranker_returns_raw_logits_in_relevance_order(model: BgeCrossEncoderReranker) -> None:
    logits = model.score_logits(
        "성수동 카페",
        ["성수동 카페", "coffee shop in Seongsu", "기후변화 논문 요약"],
    )
    assert logits[0] > logits[1] > logits[2]
    # sigmoid를 거치지 않은 원 로짓이다 (0..1 밖의 값).
    assert logits[0] > 1.0 and logits[2] < 0.0


def test_live_logits_match_committed_recording_within_fp_noise(model: BgeCrossEncoderReranker) -> None:
    """녹화본(정본)과 live cpu fp32 로짓이 같은 쌍에서 일치한다: 녹화 키 구성과 입력 텍스트가 같다는 증거."""
    from jupjup.config import SearchSettings, Settings
    from jupjup.container import build_container
    from jupjup.search.cross_rerank import build_rerank_query, build_rerank_text
    from jupjup.storage.db import create_db_engine
    from jupjup.storage.seed import load_seed_file
    from tests.conftest import DATA, NOW

    settings = Settings(env="test", mode="recorded", data_dir=DATA, db_path=":memory:", search=SearchSettings())
    container = build_container(settings, engine=create_db_engine(None))
    load_seed_file(DATA / "golden" / "seeds.jsonl", container.repo, container.indexer, strict=True)
    parsed = container.understander.parse("IG에서 본 coffee shop dessert 그거", NOW)  # ch_0001 정답 쌍
    query = build_rerank_query(parsed)
    assert query is not None
    index = container.registry.get("u_alice")
    config = RerankModelSettings()
    replay = RecordedReranker(RECORDING, config.model_id, config.revision, config.max_length)
    texts = [build_rerank_text(index.documents[cid], config.max_doc_chars).text for cid in ("c_alice_0001",)]
    recorded = replay.score_logits(query, texts)
    live = model.score_logits(query, texts)
    assert abs(recorded[0] - live[0]) < 0.05

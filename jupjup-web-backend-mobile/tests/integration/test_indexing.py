"""T11: VectorIndex, UserIndexRegistry, IndexingService."""

from __future__ import annotations

from collections.abc import Callable, Sequence

import numpy as np
import pytest
from sqlalchemy import update

from jupjup.container import AppContainer
from jupjup.domain.errors import EmbeddingProviderError
from jupjup.index.document import HardFilter
from jupjup.storage import tables as T
from jupjup.storage.seed import load_seed_file
from tests.conftest import DATA

SEEDS = DATA / "golden" / "seeds.jsonl"


def _state(c: AppContainer, user: str) -> dict[str, object]:
    u = c.registry.get(user)
    q = c.embedder.embed(["성수동 카페 디저트"], "query")[0]
    return {
        "morph": u.morph.snapshot_state(),
        "ngram": u.ngram.snapshot_state(),
        "meta": sorted(u.meta),
        "vec": [(h.content_id, h.score) for h in u.vector.search(q, HardFilter(), 200)],
        "kw": [(h.content_id, h.score) for h in u.morph.search(["카페", "성수동"], HardFilter(), 50)],
    }


def test_rebuild_equals_incremental(container_factory: Callable[..., AppContainer]) -> None:
    c = container_factory()
    rep = load_seed_file(SEEDS, c.repo, c.indexer, strict=True)
    assert rep.indexed == rep.loaded == 200 and rep.embedding_pending == 0
    incremental = _state(c, "u_alice")
    stats = c.indexer.reindex_all()
    assert stats.users == 3 and stats.documents == 200
    assert stats.embedded == 0 and stats.reused > 200  # 텍스트가 같으면 다시 임베딩하지 않는다
    assert _state(c, "u_alice") == incremental


def test_reindex_after_restart_uses_stored_vectors(container_factory: Callable[..., AppContainer]) -> None:
    c = container_factory()
    load_seed_file(SEEDS, c.repo, c.indexer, strict=True)
    before = _state(c, "u_alice")
    c.registry.reset("u_alice")  # 프로세스 재시작 흉내: 메모리 인덱스만 비운다
    assert len(c.registry.get("u_alice")) == 0
    stats = c.indexer.reindex_all("u_alice")
    assert stats.embedded == 0
    assert _state(c, "u_alice") == before


def test_reload_user_matches_full_reindex_rankings(container_factory: Callable[..., AppContainer]) -> None:
    c = container_factory()
    load_seed_file(SEEDS, c.repo, c.indexer, strict=True)
    c.indexer.reindex_all("u_alice")
    expected = _state(c, "u_alice")

    c.indexer.reload_user("u_alice")

    assert _state(c, "u_alice") == expected


def test_refresh_detects_each_index_input_changed_in_place(
    container_factory: Callable[..., AppContainer],
) -> None:
    c = container_factory()
    load_seed_file(SEEDS, c.repo, c.indexer, strict=True)
    c.indexer.reindex_all("u_alice")
    content_id = "c_alice_0001"
    mutations = [
        update(T.contents).where(T.contents.c.id == content_id).values(title="제자리 수정 제목"),
        update(T.snapshots).where(T.snapshots.c.content_id == content_id).values(text="제자리 수정 본문"),
        update(T.summaries).where(T.summaries.c.content_id == content_id).values(text="제자리 수정 요약"),
        update(T.tags).where(T.tags.c.content_id == content_id).values(confidence=0.123),
        update(T.detail_tags)
        .where(T.detail_tags.c.content_id == content_id)
        .values(user_patch='{"topics":["제자리"]}'),
        update(T.embeddings).where(T.embeddings.c.content_id == content_id).values(text_hash="in-place-change"),
        update(T.contents).where(T.contents.c.id == content_id).values(analysis_pending=1),
    ]

    for statement in mutations:
        with c.engine.begin() as conn:
            result = conn.execute(statement)
            assert result.rowcount > 0
        assert c.indexer.refresh_if_stale("u_alice")
        assert not c.indexer.refresh_if_stale("u_alice")


def test_user_isolation_structural(golden_container: AppContainer) -> None:
    c = golden_container
    alice, bob = c.registry.get("u_alice"), c.registry.get("u_bob")
    assert all(m.user_id == "u_alice" for m in alice.meta.values())
    assert all(m.user_id == "u_bob" for m in bob.meta.values())
    assert len(alice) == 160 and len(bob) == 30 and len(c.registry.get("u_carol")) == 10
    # bob만 가진 주제(낚시)는 alice 인덱스에 없다
    assert alice.morph.search(["낚시"], HardFilter(), 10) == []
    assert bob.morph.search(["낚시"], HardFilter(), 10)
    # 교정 어휘도 사용자별
    assert bob.morph.vocabulary().contains("낚시") and not alice.morph.vocabulary().contains("낚시")


def test_text_change_reembeds_only_changed(container_factory: Callable[..., AppContainer]) -> None:
    c = container_factory()
    load_seed_file(SEEDS, c.repo, c.indexer, strict=True)
    b = c.repo.get_bundle("u_alice", "c_alice_0001")
    b2 = b.model_copy(update={"content": b.content.model_copy(update={"title": "제목 바뀜"})})
    c.repo.upsert(b2)
    r = c.indexer.index_content("u_alice", "c_alice_0001")
    assert r.embedded == 1 and r.reused >= 1  # doc 벡터만 다시, 청크는 재사용
    assert c.registry.get("u_alice").morph.search(["제목"], HardFilter(), 5)[0].content_id == "c_alice_0001"


class FailingEmbedder:
    model_id = "hashing-v1"
    dim = 384

    def embed(self, texts: Sequence[str], kind: str) -> np.ndarray:
        raise EmbeddingProviderError("down")


def test_embedding_failure_keyword_only(container_factory: Callable[..., AppContainer]) -> None:
    c = container_factory()
    c.indexer.embedder = FailingEmbedder()  # type: ignore[assignment]
    rep = load_seed_file(SEEDS, c.repo, c.indexer, strict=True)
    assert rep.loaded == 200 and rep.embedding_pending == 200
    alice = c.registry.get("u_alice")
    assert alice.morph.search(["카페"], HardFilter(), 5)  # 키워드 인덱스는 반영
    assert len(alice.vector) == 0


def test_remove_content(container_factory: Callable[..., AppContainer]) -> None:
    c = container_factory()
    load_seed_file(SEEDS, c.repo, c.indexer, strict=True)
    c.indexer.remove_content("u_alice", "c_alice_0001")
    alice = c.registry.get("u_alice")
    assert "c_alice_0001" not in alice.meta
    assert all(h.content_id != "c_alice_0001" for h in alice.morph.search(["어니언"], HardFilter(), 50))
    assert c.emb_repo.get("c_alice_0001", c.embedder.model_id) == []


def test_vector_index_scoring(golden_container: AppContainer) -> None:
    c = golden_container
    alice = c.registry.get("u_alice")
    q = c.embedder.embed(["토마토 파스타 레시피"], "query")[0]
    hits = alice.vector.search(q, HardFilter(platforms={"youtube"}), 5)
    assert hits and all(alice.meta[h.content_id].platform == "youtube" for h in hits)
    assert [h.rank for h in hits] == list(range(1, len(hits) + 1))
    assert all(hits[i].score >= hits[i + 1].score for i in range(len(hits) - 1))
    sims = alice.vector.similarities(q, [hits[0].content_id])
    assert sims[hits[0].content_id] == pytest.approx(hits[0].score)


def test_registry_rejects_bad_user(golden_container: AppContainer) -> None:
    with pytest.raises(ValueError):
        golden_container.registry.get("alice")

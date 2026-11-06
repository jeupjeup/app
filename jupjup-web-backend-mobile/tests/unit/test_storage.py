"""T6: SQLite 저장소와 시드 로더."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from jupjup.domain.errors import ContentValidationError, NotFoundError
from jupjup.domain.models import SeedRecord, StoredEmbedding
from jupjup.storage.db import create_db_engine
from jupjup.storage.repositories import SqlContentRepository, SqlEmbeddingRepository
from jupjup.storage.seed import load_seed_file
from tests.conftest import DATA


def _rec(i: int, user: str = "u_alice", **kw: Any) -> dict[str, Any]:
    d: dict[str, Any] = {
        "id": f"c_{user[2:]}_{i:04d}",
        "user_id": user,
        "platform": "instagram",
        "content_type": "post",
        "title": f"제목 {i}",
        "saved_at": "2026-09-12T21:13:00+09:00",
        "snapshot": {"text": f"본문 {i}"},
        "summary": {"text": f"요약 {i}", "version": 1},
        "tags": [{"name": "카페", "source": "ai", "confidence": 0.9}, {"name": "데이트", "source": "user"}],
        "hidden_tags": ["빵집"],
        "detail_tags": {"schema_version": 1, "topics": ["카페"]},
    }
    d.update(kw)
    return d


def _write(tmp_path: Path, rows: list[Any], name: str = "seeds.jsonl") -> Path:
    p = tmp_path / name
    p.write_text(
        "\n".join(r if isinstance(r, str) else json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8"
    )
    return p


@pytest.fixture
def repo() -> SqlContentRepository:
    return SqlContentRepository(create_db_engine(None))


def test_load_counts_match(tmp_path: Path, repo: SqlContentRepository) -> None:
    p = _write(tmp_path, [_rec(i) for i in range(1, 6)] + [_rec(1, "u_bob")])
    rep = load_seed_file(p, repo, None)
    assert rep.loaded == 6 and rep.errors == []
    assert repo.count() == 6 and repo.count("u_alice") == 5 and repo.count("u_bob") == 1
    assert rep.users == {"u_alice": 5, "u_bob": 1}


def test_roundtrip_bundle(tmp_path: Path, repo: SqlContentRepository) -> None:
    rec = _rec(
        1,
        summaries=[{"text": "사용자 요약", "source": "user", "version": 1}],
        detail_tags_user_patch={"topics": ["브런치"]},
    )
    load_seed_file(_write(tmp_path, [rec]), repo, None)
    b = repo.get_bundle("u_alice", "c_alice_0001")
    expected = SeedRecord.model_validate(rec).to_bundle()
    assert b.content.title == expected.content.title and b.content.saved_at == expected.content.saved_at
    assert b.snapshot is not None and b.snapshot.text == "본문 1"
    assert b.summary is not None and b.summary.text == "사용자 요약"
    assert [(t.name, t.source) for t in b.tags] == [("카페", "ai"), ("데이트", "user")]
    assert b.content.hidden_tags == ["빵집"]
    assert b.effective_detail() == {"schema_version": 1, "topics": ["브런치"]}


def test_bad_lines_reported(tmp_path: Path, repo: SqlContentRepository) -> None:
    rows: list[Any] = [
        _rec(1),
        "{not json",
        _rec(2, platform="tiktok"),
        _rec(3, saved_at="2026-09-12T10:00:00"),
        _rec(1),
        _rec(4),
    ]
    rep = load_seed_file(_write(tmp_path, rows), repo, None)
    assert rep.loaded == 2
    codes = {(e.line, e.code) for e in rep.errors}
    assert codes == {(2, "INVALID_JSON"), (3, "INVALID_CONTENT"), (4, "INVALID_CONTENT"), (5, "DUPLICATE_ID")}
    assert repo.count() == 2


def test_strict_rolls_back(tmp_path: Path, repo: SqlContentRepository) -> None:
    rep = load_seed_file(_write(tmp_path, [_rec(1), "{bad"]), repo, None, strict=True)
    assert rep.rolled_back and rep.loaded == 0
    assert repo.count() == 0


def test_transaction_rollback_on_db_error(tmp_path: Path, repo: SqlContentRepository) -> None:
    load_seed_file(_write(tmp_path, [_rec(1, "u_bob")]), repo, None)
    # 두 번째 파일: 정상 1건 + 다른 사용자 id 덮어쓰기 시도 1건 → 트랜잭션 전체 롤백
    clash = _rec(1, "u_alice", id="c_bob_0001")
    with pytest.raises(ContentValidationError):
        load_seed_file(_write(tmp_path, [_rec(9), clash], "b.jsonl"), repo, None)
    assert repo.count("u_alice") == 0
    assert repo.get_bundle("u_bob", "c_bob_0001").content.user_id == "u_bob"


def test_reload_idempotent(tmp_path: Path, repo: SqlContentRepository) -> None:
    p = _write(tmp_path, [_rec(i) for i in range(1, 4)])
    load_seed_file(p, repo, None)
    first = [b.model_dump(exclude={"content": {"created_at", "updated_at"}}) for b in repo.iter_bundles()]
    load_seed_file(p, repo, None)
    second = [b.model_dump(exclude={"content": {"created_at", "updated_at"}}) for b in repo.iter_bundles()]
    assert first == second and repo.count() == 3


def test_replace_user(tmp_path: Path, repo: SqlContentRepository) -> None:
    load_seed_file(_write(tmp_path, [_rec(i) for i in range(1, 4)] + [_rec(1, "u_bob")]), repo, None)
    load_seed_file(_write(tmp_path, [_rec(7)], "c.jsonl"), repo, None, replace_user=True)
    assert [b.content.id for b in repo.iter_bundles("u_alice")] == ["c_alice_0007"]
    assert repo.count("u_bob") == 1  # 파일에 없는 사용자는 그대로


def test_user_scoped_reads(tmp_path: Path, repo: SqlContentRepository) -> None:
    load_seed_file(_write(tmp_path, [_rec(1), _rec(1, "u_bob")]), repo, None)
    with pytest.raises(NotFoundError):
        repo.get_bundle("u_bob", "c_alice_0001")
    assert repo.get_bundles("u_bob", ["c_alice_0001", "c_bob_0001"]).keys() == {"c_bob_0001"}
    with pytest.raises(NotFoundError):
        repo.delete("u_bob", "c_alice_0001")
    repo.delete("u_alice", "c_alice_0001")
    assert repo.count("u_alice") == 0


def test_embeddings_roundtrip(tmp_path: Path) -> None:
    engine = create_db_engine(tmp_path / "x.db")
    repo = SqlContentRepository(engine)
    load_seed_file(_write(tmp_path, [_rec(1)]), repo, None)
    er = SqlEmbeddingRepository(engine)
    v = np.arange(4, dtype=np.float32) / 10
    er.replace("c_alice_0001", "m1", [StoredEmbedding("doc", 0, "h0", v), StoredEmbedding("chunk", 0, "h1", v * 2)])
    got = er.get("c_alice_0001", "m1")
    assert [(e.kind, e.chunk_index, e.text_hash) for e in got] == [("chunk", 0, "h1"), ("doc", 0, "h0")]
    assert np.allclose(got[1].vector, v) and got[1].vector.dtype == np.float32
    assert er.get("c_alice_0001", "other") == []
    repo.delete("u_alice", "c_alice_0001")  # FK cascade
    assert er.get("c_alice_0001", "m1") == []


def test_golden_seeds_load(tmp_path: Path, repo: SqlContentRepository) -> None:
    rep = load_seed_file(DATA / "golden" / "seeds.jsonl", repo, None, strict=True)
    assert rep.errors == [] and rep.loaded == rep.total_lines == repo.count() >= 200

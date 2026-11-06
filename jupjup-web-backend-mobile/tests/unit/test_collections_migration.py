from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, inspect

from jupjup.api.errors import ApiError
from jupjup.collections.service import CollectionBody, CollectionService
from jupjup.storage import migration_v28 as v28
from jupjup.storage import migration_v29 as v29
from jupjup.storage.db import _enable_fk, create_db_engine
from tests.unit.test_save_migration import _pre_t27_database


def test_v28_upgrade_preserves_all_tables_checksums_and_restart(tmp_path: Path) -> None:
    path = tmp_path / "upgrade.db"
    _pre_t27_database(path)
    engine = create_engine(f"sqlite:///{path}")
    event.listen(engine, "connect", _enable_fk)
    v28.run_migrations(engine)
    with engine.connect() as conn:
        before = {t: conn.exec_driver_sql(f'SELECT * FROM "{t}"').all() for t in inspect(engine).get_table_names()}
    engine.dispose()
    with pytest.raises(v29.v27.MigrationError, match="requires migration"):
        create_db_engine(path, auto_migrate=False)
    engine = create_db_engine(path)
    with engine.connect() as conn:
        for table, rows in before.items():
            if table != "schema_migrations":
                assert conn.exec_driver_sql(f'SELECT * FROM "{table}"').all() == rows
        assert (
            conn.exec_driver_sql("SELECT * FROM schema_migrations WHERE version IN (27,28)").all()
            == before["schema_migrations"]
        )
        assert conn.exec_driver_sql("PRAGMA foreign_key_check").all() == []
    assert v29.migration_status(engine)["version"] == 29
    backups = list(tmp_path.glob("*.bak"))
    engine.dispose()
    restarted = create_db_engine(path, auto_migrate=False)
    assert v29.migration_status(restarted)["applied"]
    assert list(tmp_path.glob("*.bak")) == backups


def test_v29_failure_rolls_back_ddl_and_record(tmp_path: Path) -> None:
    path = tmp_path / "rollback.db"
    engine = create_engine(f"sqlite:///{path}")
    v28.run_migrations(engine)
    # Force failure after v29 has created its first index; transaction must roll it back.
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE collections (unrelated TEXT)")
    with pytest.raises(Exception, match="already exists"):
        v29.run_migrations(engine)
    assert "uq_contents_id_user" not in {i["name"] for i in inspect(engine).get_indexes("contents")}
    with engine.connect() as conn:
        assert conn.exec_driver_sql("SELECT version FROM schema_migrations ORDER BY version").scalars().all() == [
            27,
            28,
        ]
    assert list(tmp_path.glob("*.bak"))


def test_duplicate_name_race_has_one_winner(tmp_path: Path) -> None:
    engine = create_db_engine(tmp_path / "race.db")
    service = CollectionService(engine)

    def create(name: str) -> int:
        try:
            service.write("u_alice", CollectionBody(name=name))
            return 201
        except ApiError as error:
            return error.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(create, [" Café ", "CAFE\u0301"]))
    assert sorted(statuses) == [201, 409]
    assert len(service.list("u_alice")["items"]) == 1


def _initialize_database(path: str) -> bool:
    engine = create_db_engine(path)
    try:
        with engine.connect() as conn:
            return (
                conn.exec_driver_sql("SELECT count(*) FROM schema_migrations WHERE version=29").scalar_one() == 1
                and conn.exec_driver_sql("PRAGMA foreign_key_check").all() == []
            )
    finally:
        engine.dispose()


@pytest.mark.parametrize("existing", [False, True])
def test_concurrent_process_initialization(tmp_path: Path, existing: bool) -> None:
    from concurrent.futures import ProcessPoolExecutor
    from multiprocessing import get_context

    path = tmp_path / "parallel.db"
    if existing:
        engine = create_engine(f"sqlite:///{path}")
        v28.run_migrations(engine)
        engine.dispose()
    with ProcessPoolExecutor(max_workers=2, mp_context=get_context("spawn")) as pool:
        assert list(pool.map(_initialize_database, [str(path)] * 4)) == [True] * 4


def test_v29_rechecks_version_after_waiting_for_write_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from threading import Barrier

    path = tmp_path / "interleaved.db"
    engine = create_engine(f"sqlite:///{path}")
    v28.run_migrations(engine)
    engine.dispose()
    barrier = Barrier(2)
    original = v29._applied

    def initially_unapplied(engine):
        result = original(engine)
        barrier.wait(timeout=10)
        return result

    monkeypatch.setattr(v29, "_applied", initially_unapplied)
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(_initialize_database, [str(path)] * 2)) == [True, True]


def test_repository_upsert_and_seed_replace_respect_relationships(tmp_path: Path) -> None:
    from datetime import UTC, datetime

    from jupjup.domain.models import Content, ContentBundle
    from jupjup.storage.repositories import SqlContentRepository
    from jupjup.storage.seed import load_seed_file

    engine = create_db_engine(None)
    repo = SqlContentRepository(engine)
    bundle = ContentBundle(
        content=Content(
            id="c_seed", user_id="u_alice", platform="local", content_type="message", saved_at=datetime.now(UTC)
        )
    )
    repo.upsert(bundle)
    service = CollectionService(engine)
    col = service.write("u_alice", CollectionBody(name="seed collection"))["id"]
    service.membership("u_alice", col, "c_seed", add=True)
    repo.upsert(bundle)
    assert service.list("u_alice", col)["content_count"] == 1
    seed = tmp_path / "seed.jsonl"
    seed.write_text(
        '{"id":"c_new","user_id":"u_alice","platform":"local","content_type":"message",'
        '"saved_at":"2026-11-05T00:00:00Z","title":"new seed"}\n'
    )
    result = load_seed_file(seed, repo, None, replace_user=True, strict=True)
    assert not result.errors and result.loaded == 1
    assert service.list("u_alice", col)["content_count"] == 0
    assert repo.get_bundle("u_alice", "c_new").content.title == "new seed"
    with engine.connect() as conn:
        assert conn.exec_driver_sql("SELECT count(*) FROM collection_contents").scalar_one() == 0
        assert conn.exec_driver_sql("PRAGMA foreign_key_check").all() == []

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, inspect, select, text

from jupjup.domain.models import Content, ContentBundle
from jupjup.storage import migration as v27
from jupjup.storage import tables as T
from jupjup.storage.db import create_db_engine
from jupjup.storage.migration_v28 import run_migrations
from jupjup.storage.migration_v29 import migration_status
from jupjup.storage.migration_v29 import run_migrations as run_latest_migrations
from jupjup.storage.repositories import SqlContentRepository
from tests.unit.test_save_migration import _pre_t27_database


def test_v27_upgrade_preserves_public_spelling_checksum_and_precision(tmp_path: Path) -> None:
    path = tmp_path / "v27.db"
    _pre_t27_database(path)
    legacy = create_engine(f"sqlite:///{path}")
    v27.run_migrations(legacy)
    at = "2026-11-03T10:00:00.123456+09:00"
    with legacy.begin() as conn:
        conn.execute(text("UPDATE contents SET saved_at=:at,updated_at=:at"), {"at": at})
        checksum = conn.scalar(text("SELECT checksum FROM schema_migrations WHERE version=27"))
    legacy.dispose()
    with pytest.raises(v27.MigrationError, match="requires migration"):
        create_db_engine(path, auto_migrate=False)
    engine = create_db_engine(path)
    with engine.connect() as conn:
        row = conn.execute(select(T.contents)).mappings().one()
        assert row["saved_at"] == row["updated_at"] == at
        assert row["saved_at_instant"] == row["updated_at_instant"] == "2026-11-03T01:00:00.123456+00:00"
        assert conn.scalar(text("SELECT checksum FROM schema_migrations WHERE version=27")) == checksum
        assert conn.exec_driver_sql("PRAGMA foreign_key_check").all() == []
    assert migration_status(engine)["version"] == 29
    before = path.read_bytes()
    run_latest_migrations(engine, auto_migrate=False)
    assert path.read_bytes() == before
    assert len(list(tmp_path.glob("v27.db.*.bak"))) == 3  # pre-v27, pre-v28 and pre-v29
    with engine.begin() as conn:
        conn.execute(text("UPDATE schema_migrations SET checksum='tampered' WHERE version=28"))
    with pytest.raises(v27.MigrationError, match="checksum"):
        run_latest_migrations(engine)


def test_v28_failure_rolls_back_keys_and_record(tmp_path: Path) -> None:
    path = tmp_path / "rollback.db"
    _pre_t27_database(path)
    engine = create_engine(f"sqlite:///{path}")
    v27.run_migrations(engine)
    # The actual historical contents table has neither UTC comparison column.
    assert "saved_at_instant" not in {c["name"] for c in inspect(engine).get_columns("contents")}
    with engine.begin() as conn:
        conn.execute(text("UPDATE contents SET updated_at='invalid'"))
    with pytest.raises(ValueError):
        run_migrations(engine)
    assert "saved_at_instant" not in {c["name"] for c in inspect(engine).get_columns("contents")}
    with engine.connect() as conn:
        assert conn.execute(text("SELECT version FROM schema_migrations")).scalars().all() == [27]
        assert conn.scalar(text("SELECT updated_at FROM contents")) == "invalid"


def test_new_writes_and_updates_normalize_keys_and_use_indexes() -> None:
    engine = create_db_engine(None)
    repo = SqlContentRepository(engine)
    at = "2026-11-03T10:00:00.000001+09:00"
    content = Content(
        id="c_instant", user_id="u_alice", platform="local", content_type="message", saved_at=datetime.fromisoformat(at)
    )
    repo.upsert(ContentBundle(content=content))  # seed/admin/I6 bundle writer
    with engine.begin() as conn:
        repo.create_in_transaction(conn, content.model_copy(update={"id": "c_create"}))  # public create writer
        conn.execute(T.contents.update().values(updated_at=at))  # patch/worker update shape
        for row in conn.execute(select(T.contents)).mappings():
            assert row["saved_at"] == at
            assert row["saved_at_instant"] == row["updated_at_instant"] == "2026-11-03T01:00:00.000001+00:00"
        for index, where, sort in [
            ("ix_contents_user_hidden_instant", "user_id='u_alice' AND is_hidden=0", "saved_at_instant"),
            ("ix_contents_user_saved_instant", "user_id='u_alice'", "saved_at_instant"),
            ("ix_contents_user_updated_instant", "user_id='u_alice'", "updated_at_instant"),
        ]:
            plan = conn.exec_driver_sql(
                f"EXPLAIN QUERY PLAN SELECT id FROM contents WHERE {where} "
                f"AND {sort}>='2026-11-03T01:00:00.000000+00:00' ORDER BY {sort},id LIMIT 2"
            ).all()
            assert index in str(plan)
            assert "TEMP B-TREE" not in str(plan)
    statements = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    from jupjup.save.query import ContentListQuery, ContentQueryService

    ContentQueryService(repo, "test-secret").list("u_alice", ContentListQuery(saved_from=datetime.fromisoformat(at)))
    event.remove(engine, "before_cursor_execute", capture)
    sql = next(statement for statement in statements if "ORDER BY contents.saved_at_instant" in statement)
    assert "contents.saved_at_instant >=" in sql
    assert "datetime(" not in sql and "julianday(" not in sql

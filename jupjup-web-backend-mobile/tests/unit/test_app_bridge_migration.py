from pathlib import Path

import pytest

from jupjup.storage.app_bridge_migration import _CHECKSUM, run_migrations
from jupjup.storage.db import create_db_engine
from jupjup.storage.migration import MigrationError


def test_bridge_migration_fresh_and_idempotent(tmp_path: Path) -> None:
    engine = create_db_engine(tmp_path / "bridge.db")
    run_migrations(engine)
    with engine.connect() as conn:
        assert conn.exec_driver_sql("SELECT * FROM app_bridge_migrations").all() == [(1, _CHECKSUM)]
        names = {
            row[0]
            for row in conn.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE name LIKE '%app%link%' OR name LIKE 'trg_app_bridge%'"
            )
        }
        assert {
            "app_content_links",
            "uq_app_link_active_core",
            "uq_app_link_active_fp",
            "ix_app_link_core",
            "ix_app_link_account",
            "trg_app_link_active",
            "trg_app_bridge_core_deleted",
            "trg_app_bridge_core_unhidden",
        } <= names
        assert not conn.exec_driver_sql("PRAGMA foreign_key_check").all()


def test_bridge_migration_detects_tampering_and_missing_ledger(tmp_path: Path) -> None:
    engine = create_db_engine(tmp_path / "bridge.db")
    with engine.begin() as conn:
        conn.exec_driver_sql("UPDATE app_bridge_migrations SET checksum='bad'")
    with pytest.raises(MigrationError, match="checksum"):
        run_migrations(engine)
    with engine.begin() as conn:
        conn.exec_driver_sql("DROP TABLE app_bridge_migrations")
    with pytest.raises(MigrationError, match="database requires app bridge migration"):
        run_migrations(engine, auto_migrate=False)

"""Manual collections; earlier migration sources/checksums stay immutable."""

from __future__ import annotations

import fcntl
import hashlib
import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, Engine, inspect, text

from jupjup.storage import migration as v27
from jupjup.storage import migration_v28 as v28

LATEST_SCHEMA_VERSION = 29
_CHECKSUM = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _versions(conn: Connection) -> dict[int, str]:
    if "schema_migrations" not in inspect(conn).get_table_names():
        return {}
    rows = {row.version: row.checksum for row in conn.execute(text("SELECT version,checksum FROM schema_migrations"))}
    expected = {27: v27._CHECKSUM, 28: v28._CHECKSUM, 29: _CHECKSUM}
    if any(v not in expected or expected[v] != c for v, c in rows.items()):
        raise v27.MigrationError("unknown schema version or applied migration checksum changed")
    if (29 in rows and not {27, 28}.issubset(rows)) or (28 in rows and 27 not in rows):
        raise v27.MigrationError("missing prerequisite migration")
    return rows


def _applied(engine: Engine) -> bool:
    with engine.connect() as conn:
        return 29 in _versions(conn)


def _ensure_legacy(engine: Engine) -> None:
    # The immutable historical runners open their own connections. Serialize only
    # bootstrap through v28 across processes, then let v29 use SQLite's write lock.
    database = engine.url.database
    if not database:
        v28.run_migrations(engine)
        return
    with Path(database + ".migration.lock").open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            with engine.connect() as conn:
                ready = 28 in _versions(conn)
            if not ready:
                v28.run_migrations(engine)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def run_migrations(engine: Engine, *, auto_migrate: bool = True) -> None:
    if _applied(engine):
        return
    if not auto_migrate:
        raise v27.MigrationError("database requires migration; run jupjup migrate-db")
    with engine.connect() as conn:
        legacy_ready = 28 in _versions(conn)
    if not legacy_ready:
        _ensure_legacy(engine)
    database = engine.url.database
    if database and Path(database).exists():
        path = Path(database)
        backup = path.with_name(path.name + "." + datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f") + ".bak")
        with sqlite3.connect(path) as source, sqlite3.connect(backup) as destination:
            source.backup(destination)
        logging.getLogger(__name__).warning("migration backup: %s", backup)
    with engine.connect() as conn:
        conn.exec_driver_sql("BEGIN IMMEDIATE")
        try:
            if 29 in _versions(conn):
                conn.commit()
                return
            if conn.exec_driver_sql("PRAGMA foreign_key_check").all():
                raise v27.MigrationError("foreign key violations before migration")
            conn.exec_driver_sql("CREATE UNIQUE INDEX uq_contents_id_user ON contents(id,user_id)")
            conn.exec_driver_sql("""CREATE TABLE collections (
                id TEXT PRIMARY KEY, user_id TEXT NOT NULL, name TEXT NOT NULL CHECK(length(name) BETWEEN 1 AND 80),
                name_key TEXT NOT NULL, color TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                UNIQUE(user_id,name_key), UNIQUE(id,user_id))""")
            conn.exec_driver_sql("""CREATE TABLE collection_contents (
                collection_id TEXT NOT NULL, content_id TEXT NOT NULL, user_id TEXT NOT NULL,
                PRIMARY KEY(collection_id,content_id),
                FOREIGN KEY(collection_id,user_id) REFERENCES collections(id,user_id) ON DELETE CASCADE,
                FOREIGN KEY(content_id,user_id) REFERENCES contents(id,user_id) ON DELETE CASCADE)""")
            conn.exec_driver_sql(
                "CREATE INDEX ix_collection_contents_content ON collection_contents(content_id,user_id)"
            )
            if conn.exec_driver_sql("PRAGMA foreign_key_check").all():
                raise v27.MigrationError("foreign key violations after migration")
            conn.execute(
                text("INSERT INTO schema_migrations VALUES (29,:name,:checksum,:at)"),
                dict(name="manual-collections", checksum=_CHECKSUM, at=datetime.now(UTC).isoformat()),
            )
            conn.commit()
        except BaseException:
            conn.rollback()
            raise


def migration_status(engine: Engine) -> dict[str, Any]:
    return dict(version=LATEST_SCHEMA_VERSION, applied=_applied(engine), checksum=_CHECKSUM)

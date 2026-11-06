"""Forward migration registry; v27's original source and checksum remain immutable."""

from __future__ import annotations

import hashlib
import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, inspect, text

from jupjup.storage import migration as v27
from jupjup.storage.instant import utc_instant

LATEST_SCHEMA_VERSION = 28
_CHECKSUM = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _applied(engine: Engine) -> bool:
    if "schema_migrations" not in inspect(engine).get_table_names():
        return False
    with engine.connect() as conn:
        rows = {
            row.version: row.checksum for row in conn.execute(text("SELECT version,checksum FROM schema_migrations"))
        }
    expected = {27: hashlib.sha256(Path(v27.__file__).read_bytes()).hexdigest(), 28: _CHECKSUM}
    if any(version not in expected or checksum != expected[version] for version, checksum in rows.items()):
        raise v27.MigrationError("unknown schema version or applied migration checksum changed")
    if 28 in rows and 27 not in rows:
        raise v27.MigrationError("missing prerequisite migration")
    return 28 in rows


def run_migrations(engine: Engine, *, auto_migrate: bool = True) -> None:
    if _applied(engine):
        return
    if not auto_migrate:
        raise v27.MigrationError("database requires migration; run jupjup migrate-db")
    already_v27 = v27._verify_record(engine)
    v27.run_migrations(engine)
    database = engine.url.database
    if already_v27 and database and Path(database).exists():
        path = Path(database)
        backup = path.with_name(path.name + "." + datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f") + ".bak")
        with sqlite3.connect(path) as source, sqlite3.connect(backup) as destination:
            source.backup(destination)
        logging.getLogger(__name__).warning("migration backup: %s", backup)
    with engine.connect() as conn:
        conn.exec_driver_sql("BEGIN IMMEDIATE")
        try:
            if conn.exec_driver_sql("PRAGMA foreign_key_check").all():
                raise v27.MigrationError("foreign key violations before migration")
            existing = {column["name"] for column in inspect(conn).get_columns("contents")}
            for name in ("saved_at_instant", "updated_at_instant"):
                if name not in existing:
                    conn.exec_driver_sql(f"ALTER TABLE contents ADD COLUMN {name} TEXT")
            # Preserve public timestamp spelling; only the indexed comparison keys are UTC.
            count = conn.exec_driver_sql("SELECT count(*) FROM contents").scalar_one()
            for row in conn.execute(text("SELECT id,saved_at,updated_at FROM contents")).mappings():
                conn.execute(
                    text("UPDATE contents SET saved_at_instant=:saved,updated_at_instant=:updated WHERE id=:id"),
                    {"id": row["id"], "saved": utc_instant(row["saved_at"]), "updated": utc_instant(row["updated_at"])},
                )
            if conn.exec_driver_sql("SELECT count(*) FROM contents").scalar_one() != count:
                raise v27.MigrationError("row count changed during migration")
            if conn.exec_driver_sql("PRAGMA foreign_key_check").all():
                raise v27.MigrationError("foreign key violations after migration")
            for operation in ("INSERT", "UPDATE OF saved_at,updated_at"):
                suffix = "insert" if operation == "INSERT" else "update"
                conn.exec_driver_sql(
                    f"CREATE TRIGGER IF NOT EXISTS trg_contents_instants_{suffix} AFTER {operation} ON contents "
                    "BEGIN UPDATE contents SET saved_at_instant=utc_instant(NEW.saved_at), "
                    "updated_at_instant=utc_instant(NEW.updated_at) WHERE id=NEW.id; END"
                )
            conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_contents_user_hidden_instant "
                "ON contents(user_id,is_hidden,saved_at_instant,id)"
            )
            conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_contents_user_saved_instant ON contents(user_id,saved_at_instant,id)"
            )
            conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_contents_user_updated_instant ON contents(user_id,updated_at_instant,id)"
            )
            conn.execute(
                text("INSERT INTO schema_migrations(version,name,checksum,applied_at) VALUES (28,:name,:checksum,:at)"),
                {"name": "content-utc-instants", "checksum": _CHECKSUM, "at": datetime.now(UTC).isoformat()},
            )
            conn.commit()
        except BaseException:
            conn.rollback()
            raise


def migration_status(engine: Engine) -> dict[str, Any]:
    return {"version": LATEST_SCHEMA_VERSION, "applied": _applied(engine), "checksum": _CHECKSUM}

"""Forward-only SQLite schema migrations for the save API."""

from __future__ import annotations

import hashlib
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, inspect, text

from jupjup.save.dedupe import normalize_source_url
from jupjup.storage.tables import metadata

LATEST_SCHEMA_VERSION = 27
_NAME = "save-api-core"
_CHECKSUM = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

_CONTENT_COLUMNS: dict[str, str] = {
    "source_kind": "TEXT NOT NULL DEFAULT 'text'",
    "normalized_url": "TEXT",
    "automation_level": "TEXT NOT NULL DEFAULT 'auto'",
    "is_hidden": "INTEGER NOT NULL DEFAULT 0",
    "revision": "INTEGER NOT NULL DEFAULT 0",
    "duplicate_of_content_id": "TEXT REFERENCES contents(id) ON DELETE CASCADE",
}
_JOB_COLUMNS: dict[str, str] = {
    "automation_level": "TEXT NOT NULL DEFAULT 'auto'",
    "result_content_id": "TEXT",
    "candidate_id": "TEXT",
    "completed_at": "TEXT",
}
_RUN_COLUMNS: dict[str, str] = {
    "snapshot_id": "TEXT",
    "candidate_id": "TEXT",
    "model_fingerprint": "TEXT",
    "validator_json": "TEXT NOT NULL DEFAULT '{}'",
    "accepted_at": "TEXT",
}


class MigrationError(RuntimeError):
    pass


def _verify_record(engine: Engine) -> bool:
    if "schema_migrations" not in inspect(engine).get_table_names():
        return False
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT version,checksum FROM schema_migrations")).all()
    for row in rows:
        if row.version != LATEST_SCHEMA_VERSION or row.checksum != _CHECKSUM:
            raise MigrationError("unknown schema version or applied migration checksum changed")
    return bool(rows)


def run_migrations(engine: Engine, *, auto_migrate: bool = True) -> None:
    """Back up existing databases, then apply and verify one atomic forward migration."""
    if _verify_record(engine):
        return
    if not auto_migrate:
        raise MigrationError("database requires migration; run jupjup migrate-db")
    tables = set(inspect(engine).get_table_names())
    if "contents" in tables and engine.url.database:
        import logging
        import sqlite3
        from pathlib import Path

        database = Path(engine.url.database)
        if database.exists():
            backup = database.with_name(database.name + "." + datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f") + ".bak")
            with sqlite3.connect(database) as source, sqlite3.connect(backup) as destination:
                source.backup(destination)
            logging.getLogger(__name__).warning("migration backup: %s", backup)
    with engine.connect() as conn:
        # Explicit BEGIN is required: sqlite's legacy driver does not begin for DDL.
        conn.exec_driver_sql("BEGIN IMMEDIATE")
        try:
            if conn.exec_driver_sql("PRAGMA foreign_key_check").all():
                raise MigrationError("foreign key violations before migration")
            counts = {table: conn.exec_driver_sql(f'SELECT count(*) FROM "{table}"').scalar_one() for table in tables}
            for table, definitions in (
                ("contents", _CONTENT_COLUMNS),
                ("ingest_jobs", _JOB_COLUMNS),
                ("analysis_runs", _RUN_COLUMNS),
            ):
                if table in tables:
                    existing = {column["name"] for column in inspect(conn).get_columns(table)}
                    for name, definition in definitions.items():
                        if name not in existing:
                            conn.exec_driver_sql(f'ALTER TABLE "{table}" ADD COLUMN "{name}" {definition}')
            metadata.create_all(conn)
            for schema_table in metadata.sorted_tables:
                for index in schema_table.indexes:
                    index.create(conn, checkfirst=True)
            if "contents" in tables:
                rows = conn.execute(text("SELECT * FROM contents ORDER BY created_at, id")).mappings().all()
                for row in rows:
                    normalized = None
                    if row["source_url"]:
                        with suppress(Exception):
                            normalized = normalize_source_url(row["source_url"])
                    conn.execute(
                        text("UPDATE contents SET source_kind=:kind, normalized_url=:url WHERE id=:id"),
                        dict(
                            kind="url" if row["source_url"] else "image" if row["content_type"] == "image" else "text",
                            url=normalized,
                            id=row["id"],
                        ),
                    )
                    claims = []
                    if normalized:
                        claims.append(
                            ("normalized_url", "url-normalization-v1", hashlib.sha256(normalized.encode()).hexdigest())
                        )
                    snapshot = conn.execute(
                        text(
                            "SELECT id,content_hash FROM snapshots WHERE content_id=:id "
                            "ORDER BY captured_at DESC,id DESC LIMIT 1"
                        ),
                        {"id": row["id"]},
                    ).first()
                    if snapshot and snapshot.content_hash:
                        claims.append(("content_hash", "content-hash-v1", snapshot.content_hash))
                    for kind, version, digest in claims:
                        result = conn.execute(
                            text(
                                "INSERT OR IGNORE INTO content_fingerprints "
                                "(user_id,kind,version,fingerprint,content_id,created_at) "
                                "VALUES (:user,:kind,:version,:digest,:id,:at)"
                            ),
                            dict(
                                user=row["user_id"],
                                kind=kind,
                                version=version,
                                digest=digest,
                                id=row["id"],
                                at=row["created_at"],
                            ),
                        )
                        if result.rowcount == 0:
                            import logging

                            logging.getLogger(__name__).warning(
                                "migration duplicate retained: content_id=%s kind=%s", row["id"], kind
                            )
                # Existing partial unique index excludes review waits; rebuild it in place.
                conn.exec_driver_sql("DROP INDEX IF EXISTS uq_ingest_jobs_active_content")
                conn.exec_driver_sql(
                    "CREATE UNIQUE INDEX uq_ingest_jobs_active_content ON ingest_jobs(content_id) "
                    "WHERE status IN ('queued','running','retry_wait','awaiting_confirmation')"
                )
            for table, count in counts.items():
                if conn.exec_driver_sql(f'SELECT count(*) FROM "{table}"').scalar_one() != count:
                    raise MigrationError("row count changed during migration")
            if conn.exec_driver_sql("PRAGMA foreign_key_check").all():
                raise MigrationError("foreign key violations after migration")
            conn.execute(
                text("INSERT INTO schema_migrations(version,name,checksum,applied_at) VALUES (:v,:n,:c,:at)"),
                dict(v=LATEST_SCHEMA_VERSION, n=_NAME, c=_CHECKSUM, at=datetime.now(UTC).isoformat()),
            )
            conn.commit()
        except BaseException:
            conn.rollback()
            raise


def migration_status(engine: Engine) -> dict[str, Any]:
    return {"version": LATEST_SCHEMA_VERSION, "applied": _verify_record(engine), "checksum": _CHECKSUM}

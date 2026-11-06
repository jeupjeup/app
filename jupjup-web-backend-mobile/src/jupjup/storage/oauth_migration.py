"""Independent additive migration; the app API v1 checksum remains untouched."""

import hashlib
from pathlib import Path

from sqlalchemy import Engine

from jupjup.storage.migration import MigrationError

_CHECKSUM = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_DDL = (
    """CREATE TABLE oauth_identities (
        provider TEXT NOT NULL, subject TEXT NOT NULL,
        user_id TEXT NOT NULL REFERENCES api_users(id) ON DELETE CASCADE,
        PRIMARY KEY(provider,subject), UNIQUE(provider,user_id))""",
    """CREATE TABLE oauth_states (
        state_hash TEXT PRIMARY KEY, provider TEXT NOT NULL, cookie_hash TEXT NOT NULL,
        verifier TEXT NOT NULL, return_path TEXT NOT NULL, expires_at TEXT NOT NULL)""",
    """CREATE TABLE oauth_exchange_codes (
        code_hash TEXT PRIMARY KEY, cookie_hash TEXT NOT NULL,
        user_id TEXT NOT NULL REFERENCES api_users(id) ON DELETE CASCADE,
        return_path TEXT NOT NULL, is_new INTEGER NOT NULL, expires_at TEXT NOT NULL)""",
)


def run_migrations(engine: Engine, *, auto_migrate: bool = True) -> None:
    with engine.connect() as conn:
        conn.exec_driver_sql("BEGIN IMMEDIATE")
        try:
            exists = conn.exec_driver_sql(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='oauth_migrations'"
            ).first()
            if exists:
                rows = conn.exec_driver_sql("SELECT version,checksum FROM oauth_migrations ORDER BY version").all()
                if [tuple(row) for row in rows] != [(1, _CHECKSUM)]:
                    raise MigrationError("unknown OAuth migration or checksum changed")
            else:
                if not auto_migrate:
                    raise MigrationError("database requires OAuth migration")
                conn.exec_driver_sql(
                    "CREATE TABLE oauth_migrations (version INTEGER PRIMARY KEY, checksum TEXT NOT NULL)"
                )
                for statement in _DDL:
                    conn.exec_driver_sql(statement)
                conn.exec_driver_sql("INSERT INTO oauth_migrations VALUES (1,?)", (_CHECKSUM,))
            if conn.exec_driver_sql("PRAGMA foreign_key_check").all():
                raise MigrationError("foreign key violations after OAuth migration")
            conn.commit()
        except BaseException:
            conn.rollback()
            raise

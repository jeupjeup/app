"""Additive app API migration on the existing engine; historical checksums stay immutable."""

import hashlib
from pathlib import Path

from sqlalchemy import Engine

from jupjup.storage.migration import MigrationError

_CHECKSUM = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_DDL = (
    """CREATE TABLE api_users (
        id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE, nickname TEXT NOT NULL,
        notifications_enabled INTEGER NOT NULL DEFAULT 0, consent_at TEXT NOT NULL,
        password_hash TEXT NOT NULL, password_salt TEXT NOT NULL,
        password_failures INTEGER NOT NULL DEFAULT 0, password_locked_until TEXT)""",
    """CREATE TABLE api_sessions (
        token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES api_users(id) ON DELETE CASCADE,
        expires_at TEXT NOT NULL)""",
    "CREATE INDEX ix_api_sessions_user ON api_sessions(user_id)",
    """CREATE TABLE api_contents (
        id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES api_users(id) ON DELETE CASCADE,
        url TEXT NOT NULL, title TEXT NOT NULL, memo TEXT NOT NULL, type TEXT NOT NULL DEFAULT '기타',
        collection TEXT, source TEXT NOT NULL, saved_at TEXT NOT NULL, deleted_at TEXT, viewed_at TEXT)""",
    "CREATE UNIQUE INDEX uq_api_active_url ON api_contents(user_id,url) WHERE deleted_at IS NULL",
    "CREATE INDEX ix_api_contents_owner ON api_contents(user_id,saved_at)",
    """CREATE TABLE api_notices (
        id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES api_users(id) ON DELETE CASCADE,
        title TEXT NOT NULL, description TEXT NOT NULL, date TEXT NOT NULL, read INTEGER NOT NULL DEFAULT 0)""",
    "CREATE INDEX ix_api_notices_owner ON api_notices(user_id,date)",
    """CREATE TABLE api_search_history (
        sequence INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL REFERENCES api_users(id) ON DELETE CASCADE, query TEXT NOT NULL,
        UNIQUE(user_id,query))""",
    """CREATE TABLE api_rate_limits (ip TEXT PRIMARY KEY, started_at REAL NOT NULL, requests INTEGER NOT NULL)""",
)


def run_migrations(engine: Engine, *, auto_migrate: bool = True) -> None:
    with engine.connect() as conn:
        conn.exec_driver_sql("BEGIN IMMEDIATE")
        try:
            exists = conn.exec_driver_sql(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='app_api_migrations'"
            ).first()
            rows = conn.exec_driver_sql("SELECT version,checksum FROM app_api_migrations").all() if exists else []
            if rows:
                if [tuple(row) for row in rows] != [(1, _CHECKSUM)]:
                    raise MigrationError("unknown app API migration or checksum changed")
            else:
                if not auto_migrate:
                    raise MigrationError("database requires app API migration")
                conn.exec_driver_sql(
                    "CREATE TABLE IF NOT EXISTS app_api_migrations "
                    "(version INTEGER PRIMARY KEY, checksum TEXT NOT NULL)"
                )
                for statement in _DDL:
                    conn.exec_driver_sql(statement)
                conn.exec_driver_sql("INSERT INTO app_api_migrations VALUES (1,?)", (_CHECKSUM,))
            if conn.exec_driver_sql("PRAGMA foreign_key_check").all():
                raise MigrationError("foreign key violations after app API migration")
            conn.commit()
        except BaseException:
            conn.rollback()
            raise

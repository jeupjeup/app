"""엔진 생성과 스키마 초기화."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.pool import StaticPool

from jupjup.storage.account_migration import run_migrations as run_account_migrations
from jupjup.storage.app_api_migration import run_migrations as run_app_api_migrations
from jupjup.storage.app_bridge_migration import run_migrations as run_app_bridge_migrations
from jupjup.storage.instant import utc_instant
from jupjup.storage.migration_v29 import run_migrations
from jupjup.storage.oauth_migration import run_migrations as run_oauth_migrations

_INDEX_INPUT_TABLES = ("snapshots", "summaries", "tags", "detail_tags", "embeddings")


def _enable_fk(dbapi_conn: Any, _record: Any) -> None:
    dbapi_conn.create_function("utc_instant", 1, utc_instant, deterministic=True)
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


def create_db_engine(db_path: Path | str | None, *, auto_migrate: bool = True) -> Engine:
    """db_path가 None이거나 ':memory:'면 메모리 DB (같은 연결을 공유)."""
    if db_path is None or str(db_path) == ":memory:":
        engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
        )
    else:
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False}, future=True)
    event.listen(engine, "connect", _enable_fk)
    run_migrations(engine, auto_migrate=auto_migrate)
    run_app_api_migrations(engine, auto_migrate=auto_migrate)
    run_oauth_migrations(engine, auto_migrate=auto_migrate)
    run_account_migrations(engine, auto_migrate=auto_migrate)
    run_app_bridge_migrations(engine, auto_migrate=auto_migrate)
    _create_index_revision_triggers(engine)
    return engine


def _create_index_revision_triggers(engine: Engine) -> None:
    """Track every committed index-input write, including same-timestamp in-place edits."""
    with engine.begin() as conn:
        for operation, row in (("insert", "NEW"), ("update", "NEW"), ("delete", "OLD")):
            conn.exec_driver_sql(
                f"""
                CREATE TRIGGER IF NOT EXISTS trg_contents_index_revision_{operation}
                AFTER {operation.upper()} ON contents
                BEGIN
                    INSERT INTO index_revisions(user_id, revision)
                    VALUES ({row}.user_id, 1)
                    ON CONFLICT(user_id) DO UPDATE SET revision = revision + 1;
                END
                """
            )
        for table in _INDEX_INPUT_TABLES:
            for operation, row in (("insert", "NEW"), ("update", "NEW"), ("delete", "OLD")):
                conn.exec_driver_sql(
                    f"""
                    CREATE TRIGGER IF NOT EXISTS trg_{table}_index_revision_{operation}
                    AFTER {operation.upper()} ON {table}
                    BEGIN
                        INSERT INTO index_revisions(user_id, revision)
                        SELECT user_id, 1 FROM contents WHERE id = {row}.content_id
                        ON CONFLICT(user_id) DO UPDATE SET revision = revision + 1;
                    END
                    """
                )

"""Independent bridge migration. Future versions require a new file and constant."""

import hashlib
from pathlib import Path

from sqlalchemy import Engine

from jupjup.storage.migration import MigrationError

_CHECKSUM = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_DDL = (
    """CREATE TABLE app_content_links (
        api_content_id TEXT PRIMARY KEY REFERENCES api_contents(id) ON DELETE CASCADE,
        account_id TEXT NOT NULL REFERENCES api_users(id) ON DELETE CASCADE,
        core_user_id TEXT NOT NULL CHECK (core_user_id LIKE 'u_account_%'),
        core_content_id TEXT, core_url_fp TEXT, url_version TEXT NOT NULL,
        origin TEXT NOT NULL CHECK (origin IN ('app','core')),
        state TEXT NOT NULL CHECK (state IN ('linked','rejected','orphaned')),
        reject_code TEXT CHECK (reject_code IS NULL OR reject_code IN ('core_rejected_url','duplicate_active')),
        active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
        hid_core INTEGER NOT NULL DEFAULT 0 CHECK (hid_core IN (0,1)),
        title_locked INTEGER NOT NULL DEFAULT 0 CHECK (title_locked IN (0,1)),
        type_locked INTEGER NOT NULL DEFAULT 0 CHECK (type_locked IN (0,1)),
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        CHECK ((state = 'linked') = (core_content_id IS NOT NULL)),
        CHECK ((state = 'rejected') = (reject_code IS NOT NULL)))""",
    """CREATE UNIQUE INDEX uq_app_link_active_core ON app_content_links(core_user_id, core_content_id)
        WHERE active = 1 AND state = 'linked'""",
    """CREATE UNIQUE INDEX uq_app_link_active_fp ON app_content_links(account_id, core_url_fp)
        WHERE active = 1 AND core_url_fp IS NOT NULL""",
    "CREATE INDEX ix_app_link_core ON app_content_links(core_user_id, core_content_id)",
    "CREATE INDEX ix_app_link_account ON app_content_links(account_id, state, active)",
    """CREATE TRIGGER trg_app_link_active AFTER UPDATE OF deleted_at ON api_contents BEGIN
        UPDATE app_content_links SET active = (NEW.deleted_at IS NULL) WHERE api_content_id = NEW.id;
        END""",
    """CREATE TRIGGER trg_app_bridge_core_deleted AFTER DELETE ON contents BEGIN
        DELETE FROM api_contents WHERE id IN (SELECT api_content_id FROM app_content_links
            WHERE core_user_id = OLD.user_id AND core_content_id = OLD.id AND origin = 'core');
        UPDATE app_content_links SET state = 'orphaned', core_content_id = NULL, hid_core = 0
            WHERE core_user_id = OLD.user_id AND core_content_id = OLD.id;
        END""",
    """CREATE TRIGGER trg_app_bridge_core_unhidden AFTER UPDATE OF is_hidden ON contents
        WHEN OLD.is_hidden = 1 AND NEW.is_hidden = 0 BEGIN
        UPDATE app_content_links SET hid_core = 0
            WHERE core_user_id = NEW.user_id AND core_content_id = NEW.id AND hid_core = 1;
        END""",
)


def run_migrations(engine: Engine, *, auto_migrate: bool = True) -> None:
    with engine.connect() as conn:
        conn.exec_driver_sql("BEGIN IMMEDIATE")
        try:
            exists = conn.exec_driver_sql(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='app_bridge_migrations'"
            ).first()
            if exists:
                rows = conn.exec_driver_sql(
                    "SELECT version,checksum FROM app_bridge_migrations ORDER BY version"
                ).all()
                if [tuple(row) for row in rows] != [(1, _CHECKSUM)]:
                    raise MigrationError("unknown app bridge migration or checksum changed")
            else:
                if not auto_migrate:
                    raise MigrationError("database requires app bridge migration")
                conn.exec_driver_sql(
                    "CREATE TABLE app_bridge_migrations (version INTEGER PRIMARY KEY, checksum TEXT NOT NULL)"
                )
                for statement in _DDL:
                    conn.exec_driver_sql(statement)
                conn.exec_driver_sql("INSERT INTO app_bridge_migrations VALUES (1,?)", (_CHECKSUM,))
            if conn.exec_driver_sql("PRAGMA foreign_key_check").all():
                raise MigrationError("foreign key violations after app bridge migration")
            conn.commit()
        except BaseException:
            conn.rollback()
            raise

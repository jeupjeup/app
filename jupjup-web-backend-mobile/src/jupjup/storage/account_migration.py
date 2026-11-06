"""Add durable account-to-core ownership without claiming any legacy rows."""

from sqlalchemy import Engine

from jupjup.storage.migration import MigrationError


def run_migrations(engine: Engine, *, auto_migrate: bool = True) -> None:
    with engine.begin() as conn:
        conn.exec_driver_sql("BEGIN IMMEDIATE")
        exists = conn.exec_driver_sql(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='account_scopes'"
        ).first()
        if exists:
            return
        if not auto_migrate:
            raise MigrationError("database requires account ownership migration")
        conn.exec_driver_sql("""CREATE TABLE account_scopes (
            account_id TEXT PRIMARY KEY REFERENCES api_users(id) ON DELETE CASCADE,
            user_id TEXT NOT NULL UNIQUE CHECK(user_id LIKE 'u_account_%'))""")
        # Preserve the identity already used by PM's session adapter. Ordinary demo IDs are untouched.
        conn.exec_driver_sql("""INSERT INTO account_scopes
            SELECT id, 'u_account_' || replace(id, '-', '') FROM api_users""")
        conn.exec_driver_sql("""CREATE TRIGGER account_scope_on_register AFTER INSERT ON api_users
            BEGIN INSERT INTO account_scopes VALUES (NEW.id, 'u_account_' || replace(NEW.id, '-', '')); END""")
        conn.exec_driver_sql("""CREATE TRIGGER account_scope_on_delete BEFORE DELETE ON account_scopes
            BEGIN
                DELETE FROM collections WHERE user_id=OLD.user_id;
                DELETE FROM contents WHERE user_id=OLD.user_id;
                DELETE FROM idempotency_keys WHERE user_id=OLD.user_id;
                DELETE FROM index_revisions WHERE user_id=OLD.user_id;
            END""")

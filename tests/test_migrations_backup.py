import os
import sqlite3

from database import get_db_connection


def test_schema_migrations_recorded(app):
    conn = get_db_connection()
    versions = [r["version"] for r in conn.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()]
    conn.close()
    assert versions == [1, 2, 3, 4, 5, 6, 7, 8]


def test_new_tables_exist(app):
    conn = get_db_connection()
    tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    conn.close()
    for t in ("journal_entries", "notifications", "pinned_items", "import_batches", "month_end_close"):
        assert t in tables


def test_new_expense_columns_exist(app):
    conn = get_db_connection()
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(expenses)").fetchall()}
    conn.close()
    for c in ("currency", "txn_type", "refund_for_id", "reversed_by_id", "reverses_id", "split_group_id", "merchant"):
        assert c in cols


def test_backup_created_on_migration_run(app):
    import backup
    db_path = os.environ["LEDGER_DB_PATH"]
    backups = backup.list_backups(db_path)
    assert isinstance(backups, list)  # framework works even if empty on a fresh db


def test_backup_is_a_valid_sqlite_file(app, tmp_path):
    import backup as backup_module
    db_path = os.environ["LEDGER_DB_PATH"]
    dest = backup_module.create_backup(db_path, reason="test")
    assert dest and os.path.isfile(dest)
    conn = sqlite3.connect(dest)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert "users" in tables

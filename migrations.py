"""
migrations.py
A small, real migration framework: every schema change after the initial
release is a numbered, idempotent function, applied in order, and recorded
in `schema_migrations`. Before any pending migration runs, the database
file is backed up (see backup.py) - see #88 "Backup -> Migrate -> Validate
-> Test".

Each migration function must be safe to re-run (checks before ALTER/CREATE)
so a partially-applied migration (e.g. the process was killed mid-way)
never corrupts state on the next boot.
"""

import logging

import backup as backup_module

log = logging.getLogger("ledger.migrations")


def _cols(conn, table):
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _tables(conn):
    return {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}


# ---------------------------------------------------------------------------
# Migrations. Append new ones with the next integer version; never edit or
# renumber a migration that has already shipped.
# ---------------------------------------------------------------------------
def _m001_transaction_currency(conn):
    """Each transaction remembers the currency it was entered in, independent
    of the user's current display currency (see #36)."""
    for table in ("expenses", "income"):
        if "currency" not in _cols(conn, table):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN currency TEXT")
    # Backfill: best available guess is the owning user's currency at
    # migration time. This is a one-time default, not a retroactive claim
    # about what currency was actually used historically.
    for table in ("expenses", "income"):
        conn.execute(f"""
            UPDATE {table} SET currency = (
                SELECT users.currency FROM users WHERE users.id = {table}.user_id
            ) WHERE currency IS NULL
        """)


def _m002_transaction_types(conn):
    """Support Refund, Reversal, Split and Adjustment on top of Expense/
    Income/Transfer (see #11-14), via columns on the existing expenses
    table rather than a parallel table, so existing rows/queries keep
    working unchanged."""
    cols = _cols(conn, "expenses")
    if "txn_type" not in cols:
        conn.execute("ALTER TABLE expenses ADD COLUMN txn_type TEXT NOT NULL DEFAULT 'expense'")
    if "refund_for_id" not in cols:
        conn.execute("ALTER TABLE expenses ADD COLUMN refund_for_id INTEGER")
    if "reversed_by_id" not in cols:
        conn.execute("ALTER TABLE expenses ADD COLUMN reversed_by_id INTEGER")
    if "reverses_id" not in cols:
        conn.execute("ALTER TABLE expenses ADD COLUMN reverses_id INTEGER")
    if "split_group_id" not in cols:
        conn.execute("ALTER TABLE expenses ADD COLUMN split_group_id TEXT")
    if "merchant" not in cols:
        conn.execute("ALTER TABLE expenses ADD COLUMN merchant TEXT")


def _m003_journal_entries(conn):
    """A minimal double-entry journal behind the simple UI (see #10).
    Every posting has a debit or credit leg tagged to an account or a
    virtual category/income bucket; for any single transaction_ref the
    sum of debits must equal the sum of credits. This is written to
    alongside expenses/income/transfers, not as a replacement for them -
    the simple tables remain the source of truth the rest of the app reads.
    """
    if "journal_entries" not in _tables(conn):
        conn.execute("""
            CREATE TABLE journal_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                transaction_ref TEXT NOT NULL,
                transaction_type TEXT NOT NULL,
                account_id INTEGER,
                bucket TEXT,
                side TEXT NOT NULL CHECK (side IN ('debit', 'credit')),
                amount_minor INTEGER NOT NULL CHECK (amount_minor >= 0),
                date TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
                FOREIGN KEY (account_id) REFERENCES accounts (id) ON DELETE SET NULL
            )
        """)
        conn.execute("CREATE INDEX idx_journal_user_ref ON journal_entries(user_id, transaction_ref)")


def _m004_notifications(conn):
    """Notification Center (#43) - budget warnings, upcoming bills, goal
    milestones, unusual transactions, import/report completion."""
    if "notifications" not in _tables(conn):
        conn.execute("""
            CREATE TABLE notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                type TEXT NOT NULL,
                message TEXT NOT NULL,
                is_read INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
            )
        """)
        conn.execute("CREATE INDEX idx_notifications_user ON notifications(user_id, is_read)")
    if "notify_budget_warnings" not in _cols(conn, "settings"):
        conn.execute("ALTER TABLE settings ADD COLUMN notify_budget_warnings INTEGER NOT NULL DEFAULT 1")
    if "notify_bills" not in _cols(conn, "settings"):
        conn.execute("ALTER TABLE settings ADD COLUMN notify_bills INTEGER NOT NULL DEFAULT 1")
    if "notify_goals" not in _cols(conn, "settings"):
        conn.execute("ALTER TABLE settings ADD COLUMN notify_goals INTEGER NOT NULL DEFAULT 1")


def _m005_pinned_items(conn):
    """Favorite/pinned accounts, categories, reports, goals (#82)."""
    if "pinned_items" not in _tables(conn):
        conn.execute("""
            CREATE TABLE pinned_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                item_type TEXT NOT NULL,
                item_key TEXT NOT NULL,
                label TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
                UNIQUE(user_id, item_type, item_key)
            )
        """)


def _m006_import_batches(conn):
    """Import pipeline bookkeeping (#33): each upload gets a batch row so
    imported rows can be traced, and invalid rows are never silently
    discarded."""
    if "import_batches" not in _tables(conn):
        conn.execute("""
            CREATE TABLE import_batches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                filename TEXT,
                total_rows INTEGER NOT NULL DEFAULT 0,
                imported_rows INTEGER NOT NULL DEFAULT 0,
                skipped_rows INTEGER NOT NULL DEFAULT 0,
                duplicate_rows INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
            )
        """)
    if "import_batch_id" not in _cols(conn, "expenses"):
        conn.execute("ALTER TABLE expenses ADD COLUMN import_batch_id INTEGER")


def _m007_month_end_close(conn):
    """Month-end close checklist state (#79)."""
    if "month_end_close" not in _tables(conn):
        conn.execute("""
            CREATE TABLE month_end_close (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                year INTEGER NOT NULL,
                month INTEGER NOT NULL,
                transactions_reviewed INTEGER NOT NULL DEFAULT 0,
                duplicates_checked INTEGER NOT NULL DEFAULT 0,
                budget_reviewed INTEGER NOT NULL DEFAULT 0,
                accounts_reconciled INTEGER NOT NULL DEFAULT 0,
                reports_generated INTEGER NOT NULL DEFAULT 0,
                closed_at TEXT,
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
                UNIQUE(user_id, year, month)
            )
        """)


MIGRATIONS = [
    (1, "transaction currency", _m001_transaction_currency),
    (2, "transaction types: refund/reversal/split/adjustment", _m002_transaction_types),
    (3, "double-entry journal_entries table", _m003_journal_entries),
    (4, "notifications + notification preferences", _m004_notifications),
    (5, "pinned items", _m005_pinned_items),
    (6, "import batches", _m006_import_batches),
    (7, "month-end close checklist", _m007_month_end_close),
]


def _current_version(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            description TEXT NOT NULL,
            applied_at TEXT NOT NULL
        )
    """)
    row = conn.execute("SELECT MAX(version) AS v FROM schema_migrations").fetchone()
    return row["v"] or 0


def run_all(conn, db_path):
    """Backup -> migrate -> record -> commit, one migration at a time."""
    from database import now_iso
    current = _current_version(conn)
    pending = [m for m in MIGRATIONS if m[0] > current]
    if not pending:
        return []

    backup_module.create_backup(db_path, reason=f"pre-migration (from v{current})", schema_version=current)

    applied = []
    for version, description, fn in pending:
        fn(conn)
        conn.execute(
            "INSERT INTO schema_migrations (version, description, applied_at) VALUES (?, ?, ?)",
            (version, description, now_iso()),
        )
        conn.commit()
        log.info("migration_applied version=%s description=%s", version, description)
        applied.append(version)
    return applied

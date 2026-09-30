"""
database.py
Handles SQLite connection, schema creation, and seeding for the Expense Tracker app.
"""

import sqlite3
import os
from datetime import datetime

DB_PATH = os.environ.get(
    "LEDGER_DB_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "expense_tracker.db"),
)


def get_db_connection():
    """Return a SQLite connection with row factory set to dict-like rows."""
    conn = sqlite3.connect(os.environ.get("LEDGER_DB_PATH", DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db():
    """Create all tables if they do not already exist."""
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            avatar TEXT DEFAULT NULL,
            currency TEXT DEFAULT 'INR',
            language TEXT DEFAULT 'English',
            dark_mode INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            category TEXT NOT NULL,
            custom_category TEXT,
            icon TEXT DEFAULT 'fa-receipt',
            amount REAL NOT NULL,
            description TEXT,
            date TEXT NOT NULL,
            payment_mode TEXT DEFAULT 'Cash',
            receipt_path TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS income (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            source TEXT NOT NULL,
            amount REAL NOT NULL,
            description TEXT,
            date TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS budget (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            month INTEGER NOT NULL,
            year INTEGER NOT NULL,
            amount REAL NOT NULL DEFAULT 0,
            savings_goal REAL NOT NULL DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
            UNIQUE(user_id, month, year)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE NOT NULL,
            currency TEXT DEFAULT 'INR',
            language TEXT DEFAULT 'English',
            dark_mode INTEGER DEFAULT 0,
            notifications INTEGER DEFAULT 1,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS recurring_expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            category TEXT NOT NULL,
            amount REAL NOT NULL,
            description TEXT,
            frequency TEXT NOT NULL DEFAULT 'Monthly',
            next_date TEXT NOT NULL,
            payment_mode TEXT DEFAULT 'Cash',
            active INTEGER DEFAULT 1,
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
        )
    """)


    cur.execute("""
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            type TEXT NOT NULL,
            currency TEXT DEFAULT 'INR',
            opening_balance_minor INTEGER NOT NULL DEFAULT 0,
            balance_minor INTEGER NOT NULL DEFAULT 0,
            is_liability INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'active',
            notes TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS transfers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            from_account_id INTEGER,
            to_account_id INTEGER,
            amount_minor INTEGER NOT NULL,
            date TEXT NOT NULL,
            note TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
            FOREIGN KEY (from_account_id) REFERENCES accounts (id) ON DELETE SET NULL,
            FOREIGN KEY (to_account_id) REFERENCES accounts (id) ON DELETE SET NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            entity_type TEXT,
            entity_id INTEGER,
            details TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS goals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            target_minor INTEGER NOT NULL,
            saved_minor INTEGER NOT NULL DEFAULT 0,
            target_date TEXT,
            priority TEXT DEFAULT 'medium',
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS goal_contributions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            goal_id INTEGER NOT NULL,
            amount_minor INTEGER NOT NULL,
            date TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (goal_id) REFERENCES goals (id) ON DELETE CASCADE
        )
    """)

    # Indexes that matter once data volume grows.
    cur.execute("CREATE INDEX IF NOT EXISTS idx_expenses_user_date ON expenses(user_id, date)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_income_user_date ON income(user_id, date)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_accounts_user ON accounts(user_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_transfers_user_date ON transfers(user_id, date)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_audit_user_date ON audit_log(user_id, created_at)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_goals_user ON goals(user_id)")

    # --- Lightweight migrations for columns added after initial release ---
    def _cols(table):
        return {r["name"] for r in cur.execute(f"PRAGMA table_info({table})").fetchall()}

    if "amount_minor" not in _cols("expenses"):
        cur.execute("ALTER TABLE expenses ADD COLUMN amount_minor INTEGER")
    if "account_id" not in _cols("expenses"):
        cur.execute("ALTER TABLE expenses ADD COLUMN account_id INTEGER")
    if "is_deleted" not in _cols("expenses"):
        cur.execute("ALTER TABLE expenses ADD COLUMN is_deleted INTEGER NOT NULL DEFAULT 0")
    if "parent_expense_id" not in _cols("expenses"):
        cur.execute("ALTER TABLE expenses ADD COLUMN parent_expense_id INTEGER")
    if "amount_minor" not in _cols("income"):
        cur.execute("ALTER TABLE income ADD COLUMN amount_minor INTEGER")
    if "account_id" not in _cols("income"):
        cur.execute("ALTER TABLE income ADD COLUMN account_id INTEGER")
    if "is_deleted" not in _cols("income"):
        cur.execute("ALTER TABLE income ADD COLUMN is_deleted INTEGER NOT NULL DEFAULT 0")

    conn.commit()

    import migrations
    migrations.run_all(conn, os.environ.get("LEDGER_DB_PATH", DB_PATH))

    conn.commit()
    conn.close()


def backfill_minor_units():
    """
    One-time, idempotent migration: populate amount_minor (integer paise) from
    the existing REAL amount columns. Safe to call on every startup - it only
    fills rows where amount_minor is still NULL, and never touches `amount`.
    """
    from decimal import Decimal, ROUND_HALF_UP
    conn = get_db_connection()
    for table in ("expenses", "income"):
        rows = conn.execute(f"SELECT id, amount FROM {table} WHERE amount_minor IS NULL").fetchall()
        for r in rows:
            minor = int((Decimal(str(r["amount"])) * 100).quantize(0, rounding=ROUND_HALF_UP))
            conn.execute(f"UPDATE {table} SET amount_minor = ? WHERE id = ?", (minor, r["id"]))
    conn.commit()
    conn.close()


def dict_from_row(row):
    """Convert a sqlite3.Row into a plain dict."""
    return dict(row) if row else None


def now_iso():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

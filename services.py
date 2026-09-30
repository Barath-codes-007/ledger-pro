"""
services.py
Thin service layer between Flask routes and the database. Keeps financial
calculations, accounts/transfers and the audit log in one testable place
instead of inline in route handlers.
"""

import json
from database import get_db_connection, now_iso
from money import to_minor, to_major


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------
def record_audit(conn, user_id, action, entity_type=None, entity_id=None, details=None):
    conn.execute(
        "INSERT INTO audit_log (user_id, action, entity_type, entity_id, details, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, action, entity_type, entity_id, json.dumps(details) if details else None, now_iso()),
    )


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------
ACCOUNT_TYPES = ["Bank Account", "Savings Account", "Cash", "Credit Card", "Debit Card",
                  "UPI Wallet", "Investment Account", "Loan", "Other"]
LIABILITY_TYPES = {"Credit Card", "Loan"}


def create_account(conn, user_id, name, acc_type, opening_balance, currency, notes=None):
    opening_minor = to_minor(opening_balance)
    is_liability = 1 if acc_type in LIABILITY_TYPES else 0
    cur = conn.execute(
        """INSERT INTO accounts (user_id, name, type, currency, opening_balance_minor,
           balance_minor, is_liability, status, notes, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)""",
        (user_id, name, acc_type, currency, opening_minor, opening_minor, is_liability, notes, now_iso()),
    )
    record_audit(conn, user_id, "account_created", "account", cur.lastrowid, {"name": name, "type": acc_type})
    return cur.lastrowid


def list_accounts(conn, user_id, include_archived=False):
    q = "SELECT * FROM accounts WHERE user_id = ?"
    if not include_archived:
        q += " AND status = 'active'"
    q += " ORDER BY created_at"
    return conn.execute(q, (user_id,)).fetchall()


def archive_account(conn, user_id, account_id):
    conn.execute("UPDATE accounts SET status='archived' WHERE id=? AND user_id=?", (account_id, user_id))
    record_audit(conn, user_id, "account_archived", "account", account_id)


def net_worth(conn, user_id):
    rows = list_accounts(conn, user_id)
    assets = sum(r["balance_minor"] for r in rows if not r["is_liability"])
    # Liability accounts (credit card, loan) are stored as negative balances (money owed).
    liabilities = sum(-r["balance_minor"] for r in rows if r["is_liability"])
    return {
        "assets_minor": assets,
        "liabilities_minor": liabilities,
        "net_worth_minor": assets - liabilities,
    }


# ---------------------------------------------------------------------------
# Transfers - never counted as income or expense; net worth is unchanged.
# ---------------------------------------------------------------------------
def create_transfer(conn, user_id, from_account_id, to_account_id, amount, date, note=None):
    if from_account_id == to_account_id:
        return None, "Source and destination accounts must be different."
    amount_minor = to_minor(amount)
    if amount_minor <= 0:
        return None, "Transfer amount must be positive."

    from_acc = conn.execute("SELECT * FROM accounts WHERE id=? AND user_id=?", (from_account_id, user_id)).fetchone()
    to_acc = conn.execute("SELECT * FROM accounts WHERE id=? AND user_id=?", (to_account_id, user_id)).fetchone()
    if not from_acc or not to_acc:
        return None, "Account not found."

    conn.execute("UPDATE accounts SET balance_minor = balance_minor - ? WHERE id = ?", (amount_minor, from_account_id))
    conn.execute("UPDATE accounts SET balance_minor = balance_minor + ? WHERE id = ?", (amount_minor, to_account_id))
    cur = conn.execute(
        "INSERT INTO transfers (user_id, from_account_id, to_account_id, amount_minor, date, note, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (user_id, from_account_id, to_account_id, amount_minor, date, note, now_iso()),
    )
    record_audit(conn, user_id, "transfer_created", "transfer", cur.lastrowid,
                 {"from": from_acc["name"], "to": to_acc["name"], "amount_minor": amount_minor})
    return cur.lastrowid, None


# ---------------------------------------------------------------------------
# Cash flow
# ---------------------------------------------------------------------------
def cash_flow(conn, user_id, start_date, end_date):
    """Opening balance + income - expenses (+/- transfers net to zero) = closing balance."""
    opening_accounts = list_accounts(conn, user_id, include_archived=True)
    opening_minor = sum(a["opening_balance_minor"] for a in opening_accounts)

    income_before = conn.execute(
        "SELECT COALESCE(SUM(amount_minor),0) t FROM income WHERE user_id=? AND date<? AND is_deleted=0",
        (user_id, start_date)).fetchone()["t"] or 0
    expense_before = conn.execute(
        "SELECT COALESCE(SUM(amount_minor),0) t FROM expenses WHERE user_id=? AND date<? AND is_deleted=0",
        (user_id, start_date)).fetchone()["t"] or 0
    opening_minor = opening_minor + income_before - expense_before

    income_period = conn.execute(
        "SELECT COALESCE(SUM(amount_minor),0) t FROM income WHERE user_id=? AND date>=? AND date<=? AND is_deleted=0",
        (user_id, start_date, end_date)).fetchone()["t"] or 0
    expense_period = conn.execute(
        "SELECT COALESCE(SUM(amount_minor),0) t FROM expenses WHERE user_id=? AND date>=? AND date<=? AND is_deleted=0",
        (user_id, start_date, end_date)).fetchone()["t"] or 0

    return {
        "opening_minor": opening_minor,
        "income_minor": income_period,
        "expenses_minor": expense_period,
        "closing_minor": opening_minor + income_period - expense_period,
    }


# ---------------------------------------------------------------------------
# Duplicate detection - flags, never deletes.
# ---------------------------------------------------------------------------
def find_possible_duplicate(conn, user_id, amount_minor, date, category):
    return conn.execute(
        """SELECT id, description, date FROM expenses
           WHERE user_id=? AND amount_minor=? AND category=? AND is_deleted=0
           AND date BETWEEN date(?, '-2 days') AND date(?, '+2 days')""",
        (user_id, amount_minor, category, date, date),
    ).fetchall()


# ---------------------------------------------------------------------------
# Recurring processing - actually creates due expenses and advances next_date
# ---------------------------------------------------------------------------
def _advance_date(date_str, frequency):
    from datetime import date as d, timedelta
    freq = (frequency or "monthly").lower()
    y, m, day = (int(x) for x in date_str.split("-"))
    cur = d(y, m, day)
    if freq == "weekly":
        return (cur + timedelta(days=7)).isoformat()
    if freq == "yearly":
        try:
            return cur.replace(year=cur.year + 1).isoformat()
        except ValueError:
            return cur.replace(year=cur.year + 1, day=28).isoformat()
    # monthly (default)
    month = cur.month + 1
    year = cur.year + (1 if month > 12 else 0)
    month = 1 if month > 12 else month
    import calendar as _cal
    day = min(cur.day, _cal.monthrange(year, month)[1])
    return d(year, month, day).isoformat()


def process_due_recurring(conn, user_id, today_str):
    """
    Create an expense for every active recurring item whose next_date has
    arrived, then advance next_date. Matches the existing recurring_expenses
    schema (active flag, description text, category, payment_mode).
    """
    from database import now_iso as _now_iso
    created = []
    due = conn.execute(
        "SELECT * FROM recurring_expenses WHERE user_id=? AND active=1 AND next_date<=?",
        (user_id, today_str),
    ).fetchall()
    for r in due:
        amount_minor = to_minor(r["amount"])
        label = (r["description"] or r["category"] or "Recurring").strip()
        cur = conn.execute(
            """INSERT INTO expenses (user_id, category, icon, amount, amount_minor, description,
               date, payment_mode, created_at)
               VALUES (?, ?, 'fa-arrows-rotate', ?, ?, ?, ?, ?, ?)""",
            (user_id, r["category"], r["amount"], amount_minor, f"{label} (auto)",
             r["next_date"], r["payment_mode"] or "Auto", _now_iso()),
        )
        new_next = _advance_date(r["next_date"], r["frequency"])
        conn.execute("UPDATE recurring_expenses SET next_date=? WHERE id=?", (new_next, r["id"]))
        record_audit(conn, user_id, "recurring_processed", "expense", cur.lastrowid,
                     {"recurring_id": r["id"], "category": r["category"]})
        created.append(cur.lastrowid)
    return created

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


# ---------------------------------------------------------------------------
# Double-entry journal (#10) - a minimal ledger behind the simple UI.
# Every call must balance: sum(debits) == sum(credits) for the same ref.
# ---------------------------------------------------------------------------
def post_journal(conn, user_id, ref, txn_type, date, legs):
    """
    legs: list of dicts, each {"side": "debit"|"credit", "amount_minor": int,
    "account_id": int|None, "bucket": str|None}. Raises ValueError if the
    legs do not balance - callers should validate BEFORE writing the
    expense/income/transfer row itself, so nothing is left half-recorded.
    """
    debits = sum(l["amount_minor"] for l in legs if l["side"] == "debit")
    credits = sum(l["amount_minor"] for l in legs if l["side"] == "credit")
    if debits != credits:
        raise ValueError(f"Journal entry does not balance: debits={debits} credits={credits}")
    for leg in legs:
        conn.execute(
            """INSERT INTO journal_entries
               (user_id, transaction_ref, transaction_type, account_id, bucket, side, amount_minor, date, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, ref, txn_type, leg.get("account_id"), leg.get("bucket"), leg["side"],
             leg["amount_minor"], date, now_iso()),
        )


def post_expense_journal(conn, user_id, ref, category, amount_minor, date, account_id=None):
    """Expense increases the expense bucket (debit) and decreases the
    funding account (credit), or an 'Unspecified Funds' bucket when no
    account was chosen - so the entry always balances even without one.
    A negative amount_minor (refund/reversal/adjustment reducing expense)
    flips which side is debited vs credited; journal legs themselves are
    always non-negative magnitudes."""
    magnitude = abs(amount_minor)
    expense_side, funds_side = ("debit", "credit") if amount_minor >= 0 else ("credit", "debit")
    legs = [{"side": expense_side, "amount_minor": magnitude, "bucket": f"Expense:{category}"}]
    if account_id:
        legs.append({"side": funds_side, "amount_minor": magnitude, "account_id": account_id})
    else:
        legs.append({"side": funds_side, "amount_minor": magnitude, "bucket": "Unspecified Funds"})
    post_journal(conn, user_id, ref, "expense", date, legs)


def post_income_journal(conn, user_id, ref, source, amount_minor, date, account_id=None):
    legs = [{"side": "credit", "amount_minor": amount_minor, "bucket": f"Income:{source}"}]
    if account_id:
        legs.append({"side": "debit", "amount_minor": amount_minor, "account_id": account_id})
    else:
        legs.append({"side": "debit", "amount_minor": amount_minor, "bucket": "Unspecified Funds"})
    post_journal(conn, user_id, ref, "income", date, legs)


# ---------------------------------------------------------------------------
# Refunds, reversals, splits and adjustments (#11-14)
# All of these are stored as ordinary expense rows with a signed
# amount_minor, so every existing SUM(amount_minor) aggregation nets them
# correctly with no special-casing - and nothing is ever deleted.
# ---------------------------------------------------------------------------
def create_refund(conn, user_id, original_id, refund_amount, date, note=None):
    original = conn.execute("SELECT * FROM expenses WHERE id=? AND user_id=?", (original_id, user_id)).fetchone()
    if not original:
        return None, "Original transaction not found."
    refund_minor = to_minor(refund_amount)
    if refund_minor <= 0:
        return None, "Refund amount must be positive."
    if refund_minor > original["amount_minor"]:
        return None, "Refund cannot exceed the original amount."

    cur = conn.execute(
        """INSERT INTO expenses (user_id, category, icon, amount, amount_minor, description, date,
           payment_mode, currency, txn_type, refund_for_id, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'refund', ?, ?)""",
        (user_id, original["category"], original["icon"], -float(to_major(refund_minor)), -refund_minor,
         note or f"Refund for #{original_id}", date, original["payment_mode"], original["currency"],
         original_id, now_iso()),
    )
    post_expense_journal(conn, user_id, f"refund:{cur.lastrowid}", original["category"], -refund_minor, date,
                          original["account_id"])
    record_audit(conn, user_id, "expense_refunded", "expense", original_id,
                 {"refund_id": cur.lastrowid, "amount_minor": refund_minor})
    return cur.lastrowid, None


def create_reversal(conn, user_id, original_id, note=None):
    original = conn.execute("SELECT * FROM expenses WHERE id=? AND user_id=?", (original_id, user_id)).fetchone()
    if not original:
        return None, "Original transaction not found."
    if original["reversed_by_id"]:
        return None, "This transaction has already been reversed."

    today = now_iso()[:10]
    cur = conn.execute(
        """INSERT INTO expenses (user_id, category, icon, amount, amount_minor, description, date,
           payment_mode, currency, txn_type, reverses_id, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'reversal', ?, ?)""",
        (user_id, original["category"], original["icon"], -original["amount"], -original["amount_minor"],
         note or f"Reversal of #{original_id}", today, original["payment_mode"], original["currency"],
         original_id, now_iso()),
    )
    conn.execute("UPDATE expenses SET reversed_by_id=? WHERE id=?", (cur.lastrowid, original_id))
    post_expense_journal(conn, user_id, f"reversal:{cur.lastrowid}", original["category"],
                          -original["amount_minor"], today, original["account_id"])
    record_audit(conn, user_id, "expense_reversed", "expense", original_id, {"reversal_id": cur.lastrowid})
    return cur.lastrowid, None


def create_split(conn, user_id, merchant, date, payment_mode, currency, parts, description=None):
    """
    parts: list of (category, amount) tuples. A parent row (amount_minor=0)
    groups them for display; the parent never affects money totals, only
    the child rows do. All parts must sum to the stated total exactly.
    """
    import uuid
    if len(parts) < 2:
        return None, "A split needs at least two categories."
    parts_minor = []
    for category, amount in parts:
        m = to_minor(amount)
        if m <= 0:
            return None, "Each split amount must be positive."
        parts_minor.append((category, m))
    total_minor = sum(m for _, m in parts_minor)

    group_id = uuid.uuid4().hex
    parent_cur = conn.execute(
        """INSERT INTO expenses (user_id, category, icon, amount, amount_minor, description, date,
           payment_mode, currency, txn_type, split_group_id, merchant, created_at)
           VALUES (?, 'Split', 'fa-layer-group', ?, 0, ?, ?, ?, ?, 'split_parent', ?, ?, ?)""",
        (user_id, float(to_major(total_minor)), description or f"Split: {merchant or ''}".strip(),
         date, payment_mode, currency, group_id, merchant, now_iso()),
    )
    child_ids = []
    for category, m in parts_minor:
        c = conn.execute(
            """INSERT INTO expenses (user_id, category, icon, amount, amount_minor, description, date,
               payment_mode, currency, txn_type, split_group_id, merchant, created_at)
               VALUES (?, ?, 'fa-receipt', ?, ?, ?, ?, ?, ?, 'expense', ?, ?, ?)""",
            (user_id, category, float(to_major(m)), m, description or merchant, date, payment_mode,
             currency, group_id, merchant, now_iso()),
        )
        child_ids.append(c.lastrowid)
        post_expense_journal(conn, user_id, f"split:{c.lastrowid}", category, m, date)

    record_audit(conn, user_id, "expense_split_created", "expense", parent_cur.lastrowid,
                 {"total_minor": total_minor, "parts": len(parts_minor)})
    return {"parent_id": parent_cur.lastrowid, "child_ids": child_ids}, None


def create_adjustment(conn, user_id, category, amount, date, currency, description=None):
    """A manual correction. Amount may be positive (increases recorded
    expense) or negative (decreases it) - the sign is the user's, entered
    deliberately, never inferred."""
    amount_minor = to_minor(amount)
    if amount_minor == 0:
        return None, "Adjustment amount cannot be zero."
    cur = conn.execute(
        """INSERT INTO expenses (user_id, category, icon, amount, amount_minor, description, date,
           payment_mode, currency, txn_type, created_at)
           VALUES (?, ?, 'fa-pen', ?, ?, ?, ?, 'Adjustment', ?, 'adjustment', ?)""",
        (user_id, category, float(to_major(amount_minor)), amount_minor,
         description or "Manual adjustment", date, currency, now_iso()),
    )
    post_expense_journal(conn, user_id, f"adjustment:{cur.lastrowid}", category, amount_minor, date)
    record_audit(conn, user_id, "adjustment_created", "expense", cur.lastrowid, {"amount_minor": amount_minor})
    return cur.lastrowid, None


# ---------------------------------------------------------------------------
# Financial statements (#18) - built from actual stored transactions, not
# a separate model. Each statement is a different view of the same data
# already used by the dashboard and cash-flow page.
# ---------------------------------------------------------------------------
def income_statement(conn, user_id, start_date, end_date):
    income_minor = conn.execute(
        "SELECT COALESCE(SUM(amount_minor),0) t FROM income WHERE user_id=? AND date>=? AND date<=? AND is_deleted=0",
        (user_id, start_date, end_date)).fetchone()["t"] or 0
    expense_minor = conn.execute(
        "SELECT COALESCE(SUM(amount_minor),0) t FROM expenses WHERE user_id=? AND date>=? AND date<=? AND is_deleted=0",
        (user_id, start_date, end_date)).fetchone()["t"] or 0
    by_category = conn.execute(
        "SELECT category, SUM(amount_minor) t FROM expenses WHERE user_id=? AND date>=? AND date<=? AND is_deleted=0 "
        "GROUP BY category ORDER BY t DESC",
        (user_id, start_date, end_date)).fetchall()
    by_source = conn.execute(
        "SELECT source, SUM(amount_minor) t FROM income WHERE user_id=? AND date>=? AND date<=? AND is_deleted=0 "
        "GROUP BY source ORDER BY t DESC",
        (user_id, start_date, end_date)).fetchall()
    return {
        "income_minor": income_minor, "expense_minor": expense_minor,
        "net_income_minor": income_minor - expense_minor,
        "by_category": [{"label": r["category"], "amount_minor": r["t"]} for r in by_category],
        "by_source": [{"label": r["source"], "amount_minor": r["t"]} for r in by_source],
    }


def balance_sheet(conn, user_id, as_of_date=None):
    """Point-in-time snapshot. Since accounts hold a running balance rather
    than dated postings, this reflects the CURRENT balance regardless of
    as_of_date - which is stated plainly on the statement rather than
    implied as a true historical balance."""
    accounts = list_accounts(conn, user_id)
    assets = [{"name": a["name"], "type": a["type"], "amount_minor": a["balance_minor"]}
              for a in accounts if not a["is_liability"]]
    liabilities = [{"name": a["name"], "type": a["type"], "amount_minor": -a["balance_minor"]}
                   for a in accounts if a["is_liability"]]
    total_assets = sum(a["amount_minor"] for a in assets)
    total_liabilities = sum(l["amount_minor"] for l in liabilities)
    return {
        "assets": assets, "liabilities": liabilities,
        "total_assets_minor": total_assets, "total_liabilities_minor": total_liabilities,
        "net_worth_minor": total_assets - total_liabilities,
    }


def cash_flow_statement(conn, user_id, start_date, end_date):
    cf = cash_flow(conn, user_id, start_date, end_date)
    transfers_out = conn.execute(
        "SELECT COALESCE(SUM(amount_minor),0) t FROM transfers WHERE user_id=? AND date>=? AND date<=?",
        (user_id, start_date, end_date)).fetchone()["t"] or 0
    return {
        "opening_minor": cf["opening_minor"],
        "cash_in_minor": cf["income_minor"],
        "cash_out_minor": cf["expenses_minor"],
        "net_cash_flow_minor": cf["income_minor"] - cf["expenses_minor"],
        "closing_minor": cf["closing_minor"],
        "transfer_volume_minor": transfers_out,  # informational: moved between own accounts, net-zero
    }


# ---------------------------------------------------------------------------
# Notification Center (#43) + budget alerts (#20)
# Notifications are generated on demand (called from the dashboard route)
# rather than by a background scheduler, since this app has none. Each
# check is deduplicated so refreshing the dashboard doesn't spam entries.
# ---------------------------------------------------------------------------
def _notification_exists_today(conn, user_id, ntype, message):
    from database import now_iso
    today = now_iso()[:10]
    row = conn.execute(
        "SELECT id FROM notifications WHERE user_id=? AND type=? AND message=? AND created_at LIKE ?",
        (user_id, ntype, message, f"{today}%"),
    ).fetchone()
    return row is not None


def _add_notification(conn, user_id, ntype, message):
    if _notification_exists_today(conn, user_id, ntype, message):
        return
    conn.execute(
        "INSERT INTO notifications (user_id, type, message, is_read, created_at) VALUES (?, ?, ?, 0, ?)",
        (user_id, ntype, message, now_iso()),
    )


def generate_notifications(conn, user_id, today_str=None):
    """Check budget usage, upcoming bills and goal milestones, and add a
    notification for anything newsworthy that hasn't already been recorded
    today. Respects the user's per-type preferences in `settings`."""
    from datetime import datetime as _dt, timedelta as _td
    today_str = today_str or _dt.now().strftime("%Y-%m-%d")
    prefs = conn.execute("SELECT * FROM settings WHERE user_id=?", (user_id,)).fetchone()
    if not prefs:
        return

    if prefs["notify_budget_warnings"]:
        today = _dt.strptime(today_str, "%Y-%m-%d")
        budget_row = conn.execute(
            "SELECT * FROM budget WHERE user_id=? AND month=? AND year=?",
            (user_id, today.month, today.year)).fetchone()
        if budget_row and budget_row["amount"]:
            month_start = today.replace(day=1).strftime("%Y-%m-%d")
            spent_minor = conn.execute(
                "SELECT COALESCE(SUM(amount_minor),0) t FROM expenses WHERE user_id=? AND date>=? AND date<=? AND is_deleted=0",
                (user_id, month_start, today_str)).fetchone()["t"] or 0
            budget_minor = to_minor(budget_row["amount"])
            if budget_minor > 0:
                pct = spent_minor / budget_minor
                if pct >= 1.0:
                    _add_notification(conn, user_id, "budget_exceeded",
                                       f"You've exceeded your {today.strftime('%B')} budget "
                                       f"({to_major(spent_minor)} of {to_major(budget_minor)}).")
                elif pct >= 0.8:
                    _add_notification(conn, user_id, "budget_warning",
                                       f"You've used {round(pct * 100)}% of your {today.strftime('%B')} budget.")

    if prefs["notify_bills"]:
        soon = (_dt.strptime(today_str, "%Y-%m-%d") + _td(days=3)).strftime("%Y-%m-%d")
        due = conn.execute(
            "SELECT * FROM recurring_expenses WHERE user_id=? AND active=1 AND next_date>=? AND next_date<=?",
            (user_id, today_str, soon)).fetchall()
        for r in due:
            label = r["description"] or r["category"]
            _add_notification(conn, user_id, "upcoming_bill",
                               f"{label} ({to_major(to_minor(r['amount']))}) is due on {r['next_date']}.")

    if prefs["notify_goals"]:
        goals = conn.execute("SELECT * FROM goals WHERE user_id=? AND status='active'", (user_id,)).fetchall()
        for g in goals:
            if g["target_minor"] and g["saved_minor"] / g["target_minor"] >= 0.9:
                _add_notification(conn, user_id, "goal_milestone",
                                   f"You're over 90% of the way to your \"{g['name']}\" goal.")


def unread_notification_count(conn, user_id):
    return conn.execute(
        "SELECT COUNT(*) c FROM notifications WHERE user_id=? AND is_read=0", (user_id,)
    ).fetchone()["c"]


# ---------------------------------------------------------------------------
# Cash flow forecast (#26) - a plain projection from known recurring items
# and the recent average daily spend. Always labelled an estimate.
# ---------------------------------------------------------------------------
def forecast_30_day_balance(conn, user_id, as_of=None):
    from datetime import datetime as _dt, timedelta as _td
    as_of = as_of or _dt.now().strftime("%Y-%m-%d")
    as_of_date = _dt.strptime(as_of, "%Y-%m-%d")

    current_balance_minor = sum(a["balance_minor"] for a in list_accounts(conn, user_id))

    # Recent daily run-rate from the last 30 days of actual expenses.
    start = (as_of_date - timedelta_days(30)).strftime("%Y-%m-%d")
    recent_expense_minor = conn.execute(
        "SELECT COALESCE(SUM(amount_minor),0) t FROM expenses WHERE user_id=? AND date>=? AND date<=? AND is_deleted=0",
        (user_id, start, as_of)).fetchone()["t"] or 0
    daily_run_rate_minor = recent_expense_minor / 30.0

    # Known upcoming recurring expenses due in the next 30 days.
    horizon = (as_of_date + timedelta_days(30)).strftime("%Y-%m-%d")
    recurring_due_minor = 0
    for r in conn.execute("SELECT * FROM recurring_expenses WHERE user_id=? AND active=1", (user_id,)).fetchall():
        next_date = r["next_date"]
        amount_minor = to_minor(r["amount"])
        # Walk forward through occurrences within the 30-day window.
        guard = 0
        while next_date <= horizon and guard < 12:
            if next_date >= as_of:
                recurring_due_minor += amount_minor
            next_date = _advance_date(next_date, r["frequency"])
            guard += 1

    projected_expense_minor = int(daily_run_rate_minor * 30) + recurring_due_minor
    projected_balance_minor = current_balance_minor - projected_expense_minor

    return {
        "current_balance_minor": current_balance_minor,
        "daily_run_rate_minor": round(daily_run_rate_minor),
        "recurring_due_minor": recurring_due_minor,
        "projected_expense_minor": projected_expense_minor,
        "projected_balance_minor": projected_balance_minor,
        "is_estimate": True,
    }


def timedelta_days(n):
    from datetime import timedelta
    return timedelta(days=n)


# ---------------------------------------------------------------------------
# Recurring payment auto-detection (#23) - pattern match on category +
# similar amount recurring across consecutive months. Suggests only; never
# auto-creates a recurring entry.
# ---------------------------------------------------------------------------
def detect_recurring_candidates(conn, user_id):
    rows = conn.execute(
        "SELECT category, amount_minor, date, merchant FROM expenses "
        "WHERE user_id=? AND is_deleted=0 AND txn_type='expense' ORDER BY date",
        (user_id,)).fetchall()

    # Group by (category, merchant, amount rounded to nearest 1%) to catch
    # near-identical recurring charges without demanding an exact match.
    groups = {}
    for r in rows:
        bucket_amount = round(r["amount_minor"] / 100) * 100  # nearest whole currency unit
        key = (r["category"], r["merchant"] or "", bucket_amount)
        groups.setdefault(key, []).append(r["date"])

    already_tracked = {
        (r["category"]) for r in conn.execute(
            "SELECT category FROM recurring_expenses WHERE user_id=? AND active=1", (user_id,)).fetchall()
    }

    candidates = []
    for (category, merchant, bucket_amount), dates in groups.items():
        months = sorted({d[:7] for d in dates})  # YYYY-MM
        if len(months) >= 3 and category not in already_tracked:
            candidates.append({
                "category": category, "merchant": merchant or None,
                "approx_amount_minor": bucket_amount, "months_seen": len(months),
                "last_seen": max(dates),
            })
    return candidates


# ---------------------------------------------------------------------------
# Deeper analytics (#27): by account, by merchant, category/expense growth
# ---------------------------------------------------------------------------
def spending_by_merchant(conn, user_id, limit=10):
    rows = conn.execute(
        "SELECT merchant, SUM(amount_minor) t, COUNT(*) c FROM expenses "
        "WHERE user_id=? AND is_deleted=0 AND merchant IS NOT NULL AND merchant != '' "
        "GROUP BY merchant ORDER BY t DESC LIMIT ?",
        (user_id, limit)).fetchall()
    return [{"merchant": r["merchant"], "total_minor": r["t"], "count": r["c"]} for r in rows]


def spending_by_account(conn, user_id):
    rows = conn.execute(
        """SELECT a.name AS account_name, COALESCE(SUM(e.amount_minor),0) t
           FROM accounts a LEFT JOIN expenses e ON e.account_id = a.id AND e.is_deleted=0
           WHERE a.user_id=? AND a.status='active' GROUP BY a.id ORDER BY t DESC""",
        (user_id,)).fetchall()
    return [{"account": r["account_name"], "total_minor": r["t"]} for r in rows]


def category_growth(conn, user_id):
    """This month's spend per category vs last month's, as a percentage
    change. A category with no spend last month shows as 'new' rather than
    an undefined or infinite percentage."""
    from datetime import datetime as _dt
    today = _dt.now()
    this_month_start = today.replace(day=1).strftime("%Y-%m-%d")
    last_month_end = (today.replace(day=1) - timedelta_days(1))
    last_month_start = last_month_end.replace(day=1).strftime("%Y-%m-%d")
    last_month_end_str = last_month_end.strftime("%Y-%m-%d")

    this_rows = {r["category"]: r["t"] for r in conn.execute(
        "SELECT category, SUM(amount_minor) t FROM expenses WHERE user_id=? AND date>=? AND is_deleted=0 GROUP BY category",
        (user_id, this_month_start)).fetchall()}
    last_rows = {r["category"]: r["t"] for r in conn.execute(
        "SELECT category, SUM(amount_minor) t FROM expenses WHERE user_id=? AND date>=? AND date<=? AND is_deleted=0 GROUP BY category",
        (user_id, last_month_start, last_month_end_str)).fetchall()}

    results = []
    for cat in set(this_rows) | set(last_rows):
        this_amt = this_rows.get(cat, 0)
        last_amt = last_rows.get(cat, 0)
        if last_amt == 0:
            change_pct = None  # "new" this month
        else:
            change_pct = round((this_amt - last_amt) / last_amt * 100, 1)
        results.append({"category": cat, "this_month_minor": this_amt, "last_month_minor": last_amt,
                         "change_pct": change_pct})
    return sorted(results, key=lambda r: r["this_month_minor"], reverse=True)


# ---------------------------------------------------------------------------
# Financial Snapshot (#80) - a point-in-time summary for a given month.
# ---------------------------------------------------------------------------
def financial_snapshot(conn, user_id, year, month):
    month_start = f"{year:04d}-{month:02d}-01"
    next_month = month + 1 if month < 12 else 1
    next_year = year if month < 12 else year + 1
    month_end = f"{next_year:04d}-{next_month:02d}-01"

    income_minor = conn.execute(
        "SELECT COALESCE(SUM(amount_minor),0) t FROM income WHERE user_id=? AND date>=? AND date<? AND is_deleted=0",
        (user_id, month_start, month_end)).fetchone()["t"] or 0
    expense_minor = conn.execute(
        "SELECT COALESCE(SUM(amount_minor),0) t FROM expenses WHERE user_id=? AND date>=? AND date<? AND is_deleted=0",
        (user_id, month_start, month_end)).fetchone()["t"] or 0
    top_category = conn.execute(
        "SELECT category, SUM(amount_minor) t FROM expenses WHERE user_id=? AND date>=? AND date<? AND is_deleted=0 "
        "GROUP BY category ORDER BY t DESC LIMIT 1", (user_id, month_start, month_end)).fetchone()
    highest_expense = conn.execute(
        "SELECT category, amount_minor, description FROM expenses WHERE user_id=? AND date>=? AND date<? "
        "AND is_deleted=0 AND amount_minor > 0 ORDER BY amount_minor DESC LIMIT 1",
        (user_id, month_start, month_end)).fetchone()
    nw = net_worth(conn, user_id)

    savings_minor = income_minor - expense_minor
    savings_rate = round(savings_minor / income_minor * 100, 1) if income_minor else 0

    return {
        "year": year, "month": month,
        "income_minor": income_minor, "expense_minor": expense_minor,
        "savings_minor": savings_minor, "savings_rate": savings_rate,
        "top_category": top_category["category"] if top_category else None,
        "highest_expense": dict(highest_expense) if highest_expense else None,
        "net_worth_minor": nw["net_worth_minor"],
    }


# ---------------------------------------------------------------------------
# Month-End Close (#79) - a checklist, not an accounting period lock.
# ---------------------------------------------------------------------------
def get_or_create_month_close(conn, user_id, year, month):
    row = conn.execute(
        "SELECT * FROM month_end_close WHERE user_id=? AND year=? AND month=?", (user_id, year, month)
    ).fetchone()
    if row:
        return row
    conn.execute(
        "INSERT INTO month_end_close (user_id, year, month) VALUES (?, ?, ?)",
        (user_id, year, month),
    )
    return conn.execute(
        "SELECT * FROM month_end_close WHERE user_id=? AND year=? AND month=?", (user_id, year, month)
    ).fetchone()


def set_month_close_item(conn, user_id, year, month, field, value):
    assert field in ("transactions_reviewed", "duplicates_checked", "budget_reviewed",
                      "accounts_reconciled", "reports_generated")
    conn.execute(
        f"UPDATE month_end_close SET {field}=? WHERE user_id=? AND year=? AND month=?",
        (1 if value else 0, user_id, year, month),
    )
    row = conn.execute(
        "SELECT * FROM month_end_close WHERE user_id=? AND year=? AND month=?", (user_id, year, month)
    ).fetchone()
    all_done = all(row[f] for f in ("transactions_reviewed", "duplicates_checked", "budget_reviewed",
                                     "accounts_reconciled", "reports_generated"))
    if all_done and not row["closed_at"]:
        conn.execute(
            "UPDATE month_end_close SET closed_at=? WHERE user_id=? AND year=? AND month=?",
            (now_iso(), user_id, year, month),
        )
    elif not all_done and row["closed_at"]:
        conn.execute(
            "UPDATE month_end_close SET closed_at=NULL WHERE user_id=? AND year=? AND month=?",
            (user_id, year, month),
        )


# ---------------------------------------------------------------------------
# Financial Calendar (#25) - recurring bills, upcoming payments, goal
# target dates within a month, built from data already on hand.
# ---------------------------------------------------------------------------
def calendar_events(conn, user_id, year, month):
    month_start = f"{year:04d}-{month:02d}-01"
    next_month = month + 1 if month < 12 else 1
    next_year = year if month < 12 else year + 1
    month_end = f"{next_year:04d}-{next_month:02d}-01"

    events = []
    for r in conn.execute(
        "SELECT * FROM recurring_expenses WHERE user_id=? AND active=1 AND next_date>=? AND next_date<?",
        (user_id, month_start, month_end)).fetchall():
        events.append({"date": r["next_date"], "label": r["description"] or r["category"], "kind": "bill"})

    for g in conn.execute(
        "SELECT * FROM goals WHERE user_id=? AND status='active' AND target_date>=? AND target_date<?",
        (user_id, month_start, month_end)).fetchall():
        events.append({"date": g["target_date"], "label": f"Goal target: {g['name']}", "kind": "goal"})

    for e in conn.execute(
        "SELECT date, amount, description FROM expenses WHERE user_id=? AND date>=? AND date<? "
        "AND is_deleted=0 AND amount_minor > 0 ORDER BY amount_minor DESC LIMIT 5",
        (user_id, month_start, month_end)).fetchall():
        events.append({"date": e["date"], "label": f"Large expense: {e['description'] or 'Untitled'}", "kind": "expense"})

    return sorted(events, key=lambda e: e["date"])


# ---------------------------------------------------------------------------
# Demo Mode (#76) - a sandboxed demo account seeded with clearly fake data,
# never mixed with a real user's account.
# ---------------------------------------------------------------------------
def create_demo_user(conn):
    import uuid
    from datetime import datetime
    from werkzeug.security import generate_password_hash

    token = uuid.uuid4().hex[:10]
    email = f"demo-{token}@ledger.local"
    password_hash = generate_password_hash(uuid.uuid4().hex)
    cur = conn.execute(
        "INSERT INTO users (name, email, password_hash, currency, is_demo, created_at) "
        "VALUES (?, ?, ?, 'INR', 1, ?)",
        ("Demo User", email, password_hash, now_iso()),
    )
    user_id = cur.lastrowid
    conn.execute(
        "INSERT INTO settings (user_id, currency, language, dark_mode) VALUES (?, 'INR', 'English', 0)",
        (user_id,),
    )

    today = datetime.now()
    demo_account_id = create_account(conn, user_id, "[DEMO] HDFC Bank", "Bank Account", "50000", "INR")
    create_account(conn, user_id, "[DEMO] Cash", "Cash", "3000", "INR")

    sample_expenses = [
        ("Food", 450, "Groceries"), ("Transport", 200, "Cab ride"),
        ("Entertainment", 600, "Movie night"), ("Food", 150, "Coffee"),
        ("Utilities", 1200, "Electricity bill"),
    ]
    for i, (category, amount, desc) in enumerate(sample_expenses):
        date = (today.replace(day=1)).strftime("%Y-%m-%d")
        amount_minor = to_minor(amount)
        conn.execute(
            """INSERT INTO expenses (user_id, category, icon, amount, amount_minor, description, date,
               payment_mode, currency, txn_type, created_at)
               VALUES (?, ?, 'fa-receipt', ?, ?, ?, ?, 'UPI', 'INR', 'expense', ?)""",
            (user_id, category, amount, amount_minor, f"[DEMO] {desc}", date, now_iso()),
        )
    conn.execute(
        """INSERT INTO income (user_id, source, amount, amount_minor, description, date, currency, created_at)
           VALUES (?, 'Salary', 45000, 4500000, '[DEMO] Monthly salary', ?, 'INR', ?)""",
        (user_id, today.replace(day=1).strftime("%Y-%m-%d"), now_iso()),
    )
    conn.commit()
    return user_id, email

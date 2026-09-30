"""
repositories.py
A thin repository layer over raw SQL for the busiest tables, so routes
call named methods instead of writing SQL inline. This does not replace
every inline query in app.py (that would mean rewriting the whole file
at once, which is exactly the kind of large-bang rewrite the project
brief warns against) - it covers expenses, income and accounts, and new
code (API v1, imports, statements) is written against it going forward.
"""

from database import get_db_connection, now_iso


class ExpenseRepository:
    def __init__(self, conn=None):
        self.conn = conn or get_db_connection()
        self._owns_conn = conn is None

    def close(self):
        if self._owns_conn:
            self.conn.close()

    def get(self, expense_id, user_id):
        return self.conn.execute(
            "SELECT * FROM expenses WHERE id=? AND user_id=? AND is_deleted=0", (expense_id, user_id)
        ).fetchone()

    def list(self, user_id, limit=50, offset=0, category=None, date_from=None, date_to=None,
             txn_type=None, order="DESC"):
        q = "SELECT * FROM expenses WHERE user_id=? AND is_deleted=0"
        params = [user_id]
        if category:
            q += " AND category=?"; params.append(category)
        if date_from:
            q += " AND date>=?"; params.append(date_from)
        if date_to:
            q += " AND date<=?"; params.append(date_to)
        if txn_type:
            q += " AND txn_type=?"; params.append(txn_type)
        q += f" ORDER BY date {order}, id {order} LIMIT ? OFFSET ?"
        params += [limit, offset]
        return self.conn.execute(q, params).fetchall()

    def count(self, user_id, category=None, date_from=None, date_to=None):
        q = "SELECT COUNT(*) c FROM expenses WHERE user_id=? AND is_deleted=0"
        params = [user_id]
        if category:
            q += " AND category=?"; params.append(category)
        if date_from:
            q += " AND date>=?"; params.append(date_from)
        if date_to:
            q += " AND date<=?"; params.append(date_to)
        return self.conn.execute(q, params).fetchone()["c"]

    def create(self, user_id, **fields):
        cols = ", ".join(fields.keys())
        placeholders = ", ".join("?" for _ in fields)
        cur = self.conn.execute(
            f"INSERT INTO expenses (user_id, {cols}, created_at) VALUES (?, {placeholders}, ?)",
            [user_id, *fields.values(), now_iso()],
        )
        return cur.lastrowid

    def update(self, expense_id, user_id, **fields):
        set_clause = ", ".join(f"{k}=?" for k in fields)
        self.conn.execute(
            f"UPDATE expenses SET {set_clause} WHERE id=? AND user_id=?",
            [*fields.values(), expense_id, user_id],
        )

    def soft_delete(self, expense_id, user_id):
        self.conn.execute("UPDATE expenses SET is_deleted=1 WHERE id=? AND user_id=?", (expense_id, user_id))

    def hard_delete(self, expense_id, user_id):
        self.conn.execute("DELETE FROM expenses WHERE id=? AND user_id=?", (expense_id, user_id))

    def sum_minor(self, user_id, date_from=None, date_to=None):
        q = "SELECT COALESCE(SUM(amount_minor),0) t FROM expenses WHERE user_id=? AND is_deleted=0"
        params = [user_id]
        if date_from:
            q += " AND date>=?"; params.append(date_from)
        if date_to:
            q += " AND date<?"; params.append(date_to)
        return self.conn.execute(q, params).fetchone()["t"]


class IncomeRepository:
    def __init__(self, conn=None):
        self.conn = conn or get_db_connection()
        self._owns_conn = conn is None

    def close(self):
        if self._owns_conn:
            self.conn.close()

    def get(self, income_id, user_id):
        return self.conn.execute(
            "SELECT * FROM income WHERE id=? AND user_id=? AND is_deleted=0", (income_id, user_id)
        ).fetchone()

    def list(self, user_id, limit=50, offset=0, date_from=None, date_to=None, order="DESC"):
        q = "SELECT * FROM income WHERE user_id=? AND is_deleted=0"
        params = [user_id]
        if date_from:
            q += " AND date>=?"; params.append(date_from)
        if date_to:
            q += " AND date<=?"; params.append(date_to)
        q += f" ORDER BY date {order}, id {order} LIMIT ? OFFSET ?"
        params += [limit, offset]
        return self.conn.execute(q, params).fetchall()

    def sum_minor(self, user_id, date_from=None, date_to=None):
        q = "SELECT COALESCE(SUM(amount_minor),0) t FROM income WHERE user_id=? AND is_deleted=0"
        params = [user_id]
        if date_from:
            q += " AND date>=?"; params.append(date_from)
        if date_to:
            q += " AND date<?"; params.append(date_to)
        return self.conn.execute(q, params).fetchone()["t"]


class AccountRepository:
    def __init__(self, conn=None):
        self.conn = conn or get_db_connection()
        self._owns_conn = conn is None

    def close(self):
        if self._owns_conn:
            self.conn.close()

    def get(self, account_id, user_id):
        return self.conn.execute("SELECT * FROM accounts WHERE id=? AND user_id=?", (account_id, user_id)).fetchone()

    def list(self, user_id, include_archived=False):
        q = "SELECT * FROM accounts WHERE user_id=?"
        if not include_archived:
            q += " AND status='active'"
        return self.conn.execute(q + " ORDER BY created_at", (user_id,)).fetchall()

from conftest import post
from database import get_db_connection


def add_expense(c, amount="2000", category="Shopping", date="2026-09-10"):
    return post(c, "/expenses/add", {"category": category, "amount": amount, "date": date,
                                      "payment_mode": "UPI", "description": "purchase"},
                content_type="multipart/form-data")


def expense_id(conn=None):
    own = conn is None
    if own:
        conn = get_db_connection()
    r = conn.execute("SELECT id FROM expenses WHERE txn_type='expense' ORDER BY id DESC LIMIT 1").fetchone()
    if own:
        conn.close()
    return r["id"]


def net_expense_total():
    conn = get_db_connection()
    t = conn.execute("SELECT COALESCE(SUM(amount_minor),0) t FROM expenses WHERE user_id=1").fetchone()["t"]
    conn.close()
    return t


def test_refund_reduces_net_expense(alice):
    add_expense(alice, "2000")
    eid = expense_id()
    post(alice, f"/expenses/refund/{eid}", {"amount": "500", "date": "2026-09-11"})
    conn = get_db_connection()
    total = conn.execute("SELECT COALESCE(SUM(amount_minor),0) t FROM expenses").fetchone()["t"]
    conn.close()
    assert total == 150000  # 2000 - 500 = 1500.00 -> paise


def test_refund_cannot_exceed_original(alice):
    add_expense(alice, "100")
    eid = expense_id()
    post(alice, f"/expenses/refund/{eid}", {"amount": "500", "date": "2026-09-11"})
    conn = get_db_connection()
    total = conn.execute("SELECT COALESCE(SUM(amount_minor),0) t FROM expenses").fetchone()["t"]
    conn.close()
    assert total == 10000  # unchanged, refund rejected


def test_reversal_nets_to_zero_and_preserves_original(alice):
    add_expense(alice, "750")
    eid = expense_id()
    post(alice, f"/expenses/reverse/{eid}")
    conn = get_db_connection()
    total = conn.execute("SELECT COALESCE(SUM(amount_minor),0) t FROM expenses").fetchone()["t"]
    original = conn.execute("SELECT reversed_by_id FROM expenses WHERE id=?", (eid,)).fetchone()
    count = conn.execute("SELECT COUNT(*) c FROM expenses").fetchone()["c"]
    conn.close()
    assert total == 0
    assert original["reversed_by_id"] is not None
    assert count == 2  # original preserved + reversal row, nothing deleted


def test_cannot_reverse_twice(alice):
    add_expense(alice, "750")
    eid = expense_id()
    post(alice, f"/expenses/reverse/{eid}")
    r = post(alice, f"/expenses/reverse/{eid}", follow_redirects=True)
    assert b"already been reversed" in r.data


def test_split_expense_sums_correctly_and_parent_does_not_double_count(alice):
    post(alice, "/expenses/split/add", {
        "merchant": "Amazon", "date": "2026-09-12", "payment_mode": "UPI", "description": "order",
        "split_category[]": ["Electronics", "Books", "Other"],
        "split_amount[]": ["2000", "700", "300"],
    })
    conn = get_db_connection()
    total = conn.execute("SELECT COALESCE(SUM(amount_minor),0) t FROM expenses").fetchone()["t"]
    rows = conn.execute("SELECT COUNT(*) c FROM expenses WHERE txn_type='split_parent'").fetchone()["c"]
    conn.close()
    assert total == 300000  # 2000+700+300 = 3000.00, parent contributes 0
    assert rows == 1


def test_adjustment_can_increase_or_decrease(alice):
    post(alice, "/adjustments/add", {"category": "Adjustment", "amount": "-200",
                                      "date": "2026-09-13", "description": "correction"})
    conn = get_db_connection()
    total = conn.execute("SELECT COALESCE(SUM(amount_minor),0) t FROM expenses").fetchone()["t"]
    conn.close()
    assert total == -20000


def test_refund_reversal_split_adjustment_are_user_scoped(make_user):
    a, b = make_user("a@example.com"), make_user("b@example.com")
    add_expense(a, "500")
    conn = get_db_connection()
    eid = conn.execute("SELECT id FROM expenses WHERE txn_type='expense'").fetchone()["id"]
    conn.close()
    post(b, f"/expenses/refund/{eid}", {"amount": "100", "date": "2026-09-11"}, follow_redirects=True)
    post(b, f"/expenses/reverse/{eid}", follow_redirects=True)
    conn = get_db_connection()
    total = conn.execute("SELECT COALESCE(SUM(amount_minor),0) t FROM expenses WHERE user_id=(SELECT id FROM users WHERE email='a@example.com')").fetchone()["t"]
    conn.close()
    assert total == 50000  # untouched by user B's attempts


def test_journal_entries_always_balance(alice):
    """For every transaction_ref in the journal, debits must equal credits."""
    add_expense(alice, "1000")
    eid = expense_id()
    post(alice, f"/expenses/refund/{eid}", {"amount": "300", "date": "2026-09-11"})
    post(alice, "/adjustments/add", {"category": "Adjustment", "amount": "-50",
                                      "date": "2026-09-12", "description": "fix"})
    conn = get_db_connection()
    refs = [r["transaction_ref"] for r in conn.execute("SELECT DISTINCT transaction_ref FROM journal_entries").fetchall()]
    for ref in refs:
        debit = conn.execute("SELECT COALESCE(SUM(amount_minor),0) t FROM journal_entries WHERE transaction_ref=? AND side='debit'", (ref,)).fetchone()["t"]
        credit = conn.execute("SELECT COALESCE(SUM(amount_minor),0) t FROM journal_entries WHERE transaction_ref=? AND side='credit'", (ref,)).fetchone()["t"]
        assert debit == credit, f"{ref} does not balance: debit={debit} credit={credit}"
    conn.close()


def test_expenses_page_renders_after_refund_and_split(alice):
    add_expense(alice, "1000")
    eid = expense_id()
    post(alice, f"/expenses/refund/{eid}", {"amount": "300", "date": "2026-09-11"})
    post(alice, "/expenses/split/add", {
        "merchant": "Amazon", "date": "2026-09-12", "payment_mode": "UPI",
        "split_category[]": ["Electronics", "Books"], "split_amount[]": ["100", "50"],
    })
    r = alice.get("/expenses")
    assert r.status_code == 200
    assert b"Refund" in r.data and b"Split" in r.data

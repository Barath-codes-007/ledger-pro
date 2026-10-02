from conftest import post
from database import get_db_connection


def test_snapshot_page_renders_with_data(alice):
    post(alice, "/expenses/add", {"category": "Food", "amount": "300", "date": "2026-10-05",
                                   "payment_mode": "UPI", "description": "lunch"},
         content_type="multipart/form-data")
    post(alice, "/income/add", {"source": "Salary", "amount": "1000", "date": "2026-10-01",
                                 "description": "pay"})
    r = alice.get("/snapshot?year=2026&month=10")
    assert r.status_code == 200
    assert b"700.00" in r.data  # savings = 1000 - 300


def test_month_end_close_toggle_and_completion(alice):
    r = alice.get("/month-end-close?year=2026&month=10")
    assert r.status_code == 200
    fields = ["transactions_reviewed", "duplicates_checked", "budget_reviewed",
              "accounts_reconciled", "reports_generated"]
    for f in fields:
        post(alice, "/month-end-close/toggle", {"year": "2026", "month": "10", "field": f, "value": "1"})
    conn = get_db_connection()
    row = conn.execute("SELECT * FROM month_end_close WHERE year=2026 AND month=10").fetchone()
    conn.close()
    assert row["closed_at"] is not None
    assert all(row[f] for f in fields)


def test_month_end_close_reopens_if_item_unchecked(alice):
    fields = ["transactions_reviewed", "duplicates_checked", "budget_reviewed",
              "accounts_reconciled", "reports_generated"]
    for f in fields:
        post(alice, "/month-end-close/toggle", {"year": "2026", "month": "10", "field": f, "value": "1"})
    post(alice, "/month-end-close/toggle", {"year": "2026", "month": "10", "field": "budget_reviewed", "value": "0"})
    conn = get_db_connection()
    row = conn.execute("SELECT closed_at FROM month_end_close WHERE year=2026 AND month=10").fetchone()
    conn.close()
    assert row["closed_at"] is None


def test_calendar_shows_recurring_bill(alice):
    post(alice, "/budget/recurring/add", {
        "category": "Subscriptions", "amount": "649", "description": "Netflix",
        "frequency": "Monthly", "next_date": "2026-10-15",
    })
    r = alice.get("/calendar?year=2026&month=10")
    assert b"Netflix" in r.data


def test_demo_mode_creates_isolated_seeded_account(client):
    r = client.get("/demo/start", follow_redirects=True)
    assert r.status_code == 200
    assert b"DEMO MODE" in r.data
    conn = get_db_connection()
    user = conn.execute("SELECT * FROM users WHERE is_demo=1").fetchone()
    expense_count = conn.execute("SELECT COUNT(*) c FROM expenses WHERE user_id=?", (user["id"],)).fetchone()["c"]
    conn.close()
    assert user is not None and expense_count > 0


def test_demo_accounts_are_isolated_from_each_other(client, app):
    c1 = app.test_client()
    c2 = app.test_client()
    c1.get("/demo/start")
    c2.get("/demo/start")
    conn = get_db_connection()
    demo_users = conn.execute("SELECT id FROM users WHERE is_demo=1").fetchall()
    conn.close()
    assert len(demo_users) == 2
    assert demo_users[0]["id"] != demo_users[1]["id"]

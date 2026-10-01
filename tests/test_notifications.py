from conftest import post
from database import get_db_connection


def test_budget_warning_generated_at_80_percent(alice):
    post(alice, "/budget", {"amount": "1000", "savings_goal": "0"})
    post(alice, "/expenses/add", {"category": "Food", "amount": "850", "date": "2026-10-01",
                                   "payment_mode": "UPI", "description": "groceries"},
         content_type="multipart/form-data")
    alice.get("/dashboard")  # triggers generate_notifications
    conn = get_db_connection()
    rows = conn.execute("SELECT * FROM notifications WHERE type IN ('budget_warning','budget_exceeded')").fetchall()
    conn.close()
    assert len(rows) >= 1


def test_notification_not_duplicated_same_day(alice):
    post(alice, "/budget", {"amount": "1000", "savings_goal": "0"})
    post(alice, "/expenses/add", {"category": "Food", "amount": "900", "date": "2026-10-01",
                                   "payment_mode": "UPI", "description": "groceries"},
         content_type="multipart/form-data")
    alice.get("/dashboard")
    alice.get("/dashboard")
    alice.get("/dashboard")
    conn = get_db_connection()
    count = conn.execute("SELECT COUNT(*) c FROM notifications").fetchone()["c"]
    conn.close()
    assert count == 1


def test_notifications_respect_preference_toggle(alice):
    post(alice, "/settings/notifications", {})  # all unchecked = disabled
    post(alice, "/budget", {"amount": "1000", "savings_goal": "0"})
    post(alice, "/expenses/add", {"category": "Food", "amount": "900", "date": "2026-10-01",
                                   "payment_mode": "UPI", "description": "groceries"},
         content_type="multipart/form-data")
    alice.get("/dashboard")
    conn = get_db_connection()
    count = conn.execute("SELECT COUNT(*) c FROM notifications").fetchone()["c"]
    conn.close()
    assert count == 0


def test_mark_notification_read(alice):
    post(alice, "/budget", {"amount": "1000", "savings_goal": "0"})
    post(alice, "/expenses/add", {"category": "Food", "amount": "900", "date": "2026-10-01",
                                   "payment_mode": "UPI", "description": "groceries"},
         content_type="multipart/form-data")
    alice.get("/dashboard")
    conn = get_db_connection()
    nid = conn.execute("SELECT id FROM notifications LIMIT 1").fetchone()["id"]
    conn.close()
    post(alice, f"/notifications/read/{nid}")
    conn = get_db_connection()
    row = conn.execute("SELECT is_read FROM notifications WHERE id=?", (nid,)).fetchone()
    conn.close()
    assert row["is_read"] == 1


def test_notifications_are_user_scoped(make_user):
    a, b = make_user("a@example.com"), make_user("b@example.com")
    post(a, "/budget", {"amount": "1000", "savings_goal": "0"})
    post(a, "/expenses/add", {"category": "Food", "amount": "900", "date": "2026-10-01",
                               "payment_mode": "UPI", "description": "groceries"},
         content_type="multipart/form-data")
    a.get("/dashboard")
    assert b"budget" not in b.get("/notifications").data.lower() or b"No notifications" in b.get("/notifications").data

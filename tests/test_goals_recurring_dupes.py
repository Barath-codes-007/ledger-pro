from conftest import post
from database import get_db_connection
import services


def test_goal_progress_and_completion(alice):
    post(alice, "/goals", {"name": "Laptop", "target": "800", "priority": "high"})
    conn = get_db_connection()
    gid = conn.execute("SELECT id FROM goals").fetchone()[0]
    conn.close()
    post(alice, f"/goals/contribute/{gid}", {"amount": "800"})
    conn = get_db_connection()
    g = conn.execute("SELECT * FROM goals WHERE id=?", (gid,)).fetchone()
    conn.close()
    assert g["status"] == "completed" and g["saved_minor"] == 80000


def test_recurring_expense_is_created_when_due(alice):
    post(alice, "/budget/recurring/add", {
        "category": "Subscriptions", "amount": "649", "description": "Netflix",
        "frequency": "Monthly", "next_date": "2020-01-01",
    })
    conn = get_db_connection()
    uid = conn.execute("SELECT user_id FROM recurring_expenses LIMIT 1").fetchone()[0]
    before = conn.execute("SELECT COUNT(*) FROM expenses").fetchone()[0]
    created = services.process_due_recurring(conn, uid, "2026-09-29")
    conn.commit()
    after = conn.execute("SELECT COUNT(*) FROM expenses").fetchone()[0]
    next_date = conn.execute("SELECT next_date FROM recurring_expenses").fetchone()[0]
    conn.close()
    assert len(created) == 1 and after == before + 1
    assert next_date == "2020-02-01"


def test_duplicate_detection_flags_similar_expense(alice):
    r1 = post(alice, "/expenses/add", {"category": "Food", "amount": "500", "date": "2026-09-10",
                                        "payment_mode": "UPI", "description": "Lunch"},
              content_type="multipart/form-data")
    r2 = post(alice, "/expenses/add", {"category": "Food", "amount": "500", "date": "2026-09-11",
                                        "payment_mode": "UPI", "description": "Lunch again"},
              content_type="multipart/form-data", follow_redirects=True)
    assert b"similar" in r2.data.lower()

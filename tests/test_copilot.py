from conftest import post
from database import get_db_connection
import copilot


def test_copilot_spend_this_month(alice):
    import datetime
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    post(alice, "/expenses/add", {"category": "Food", "amount": "500", "date": today,
                                   "payment_mode": "UPI", "description": "lunch"},
         content_type="multipart/form-data")
    r = post(alice, "/copilot", {"question": "How much did I spend this month?"}, follow_redirects=True)
    assert b"500.00" in r.data and b"actual" in r.data


def test_copilot_unrecognized_question_does_not_guess(alice):
    conn = get_db_connection()
    uid = conn.execute("SELECT id FROM users LIMIT 1").fetchone()["id"]
    result = copilot.answer(conn, uid, "what color should I paint my room")
    conn.close()
    assert "I can answer questions like" in result


def test_copilot_subscriptions(alice):
    post(alice, "/budget/recurring/add", {
        "category": "Subscriptions", "amount": "649", "description": "Netflix",
        "frequency": "Monthly", "next_date": "2026-11-01",
    })
    conn = get_db_connection()
    uid = conn.execute("SELECT id FROM users LIMIT 1").fetchone()["id"]
    result = copilot.answer(conn, uid, "what subscriptions do I have?")
    conn.close()
    assert "Netflix" in result and "649" in result


def test_copilot_net_worth_matches_services(alice):
    post(alice, "/accounts", {"name": "HDFC", "type": "Bank Account", "opening_balance": "1000"})
    conn = get_db_connection()
    uid = conn.execute("SELECT id FROM users LIMIT 1").fetchone()["id"]
    result = copilot.answer(conn, uid, "what's my net worth?")
    conn.close()
    assert "1000.00" in result or "1,000.00" in result


def test_copilot_forecast_is_labelled_estimate(alice):
    conn = get_db_connection()
    uid = conn.execute("SELECT id FROM users LIMIT 1").fetchone()["id"]
    result = copilot.answer(conn, uid, "what's my 30-day forecast?")
    conn.close()
    assert "ESTIMATE" in result


def test_copilot_is_user_scoped(make_user):
    a, b = make_user("a@example.com"), make_user("b@example.com")
    import datetime
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    post(a, "/expenses/add", {"category": "Food", "amount": "999", "date": today,
                               "payment_mode": "UPI", "description": "lunch"},
         content_type="multipart/form-data")
    r = post(b, "/copilot", {"question": "How much did I spend this month?"}, follow_redirects=True)
    assert b"999.00" not in r.data

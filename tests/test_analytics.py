from conftest import post
from database import get_db_connection
import services


def test_analytics_page_renders(alice):
    post(alice, "/expenses/add", {"category": "Food", "amount": "500", "date": "2026-10-01",
                                   "payment_mode": "UPI", "description": "x", "merchant": "Swiggy"},
         content_type="multipart/form-data")
    r = alice.get("/analytics")
    assert r.status_code == 200
    assert b"30-Day Cash Flow Forecast" in r.data


def test_forecast_is_labelled_estimate(alice):
    conn = get_db_connection()
    uid = conn.execute("SELECT id FROM users LIMIT 1").fetchone()["id"]
    forecast = services.forecast_30_day_balance(conn, uid)
    conn.close()
    assert forecast["is_estimate"] is True
    assert "projected_balance_minor" in forecast


def test_spending_by_merchant_aggregates(alice):
    for _ in range(2):
        post(alice, "/expenses/add", {"category": "Food", "amount": "100", "date": "2026-10-01",
                                       "payment_mode": "UPI", "description": "x", "merchant": "Swiggy"},
             content_type="multipart/form-data")
    conn = get_db_connection()
    uid = conn.execute("SELECT id FROM users LIMIT 1").fetchone()["id"]
    rows = services.spending_by_merchant(conn, uid)
    conn.close()
    assert rows[0]["merchant"] == "Swiggy" and rows[0]["count"] == 2 and rows[0]["total_minor"] == 20000


def test_recurring_candidate_detected_after_three_months(alice):
    for month in ("2026-07", "2026-08", "2026-09"):
        post(alice, "/expenses/add", {"category": "Subscriptions", "amount": "649",
                                       "date": f"{month}-05", "payment_mode": "UPI",
                                       "description": "netflix", "merchant": "Netflix"},
             content_type="multipart/form-data")
    conn = get_db_connection()
    uid = conn.execute("SELECT id FROM users LIMIT 1").fetchone()["id"]
    candidates = services.detect_recurring_candidates(conn, uid)
    conn.close()
    assert any(c["merchant"] == "Netflix" for c in candidates)


def test_recurring_candidate_not_flagged_if_already_tracked(alice):
    post(alice, "/budget/recurring/add", {
        "category": "Subscriptions", "amount": "649", "description": "Netflix",
        "frequency": "Monthly", "next_date": "2026-11-01",
    })
    for month in ("2026-07", "2026-08", "2026-09"):
        post(alice, "/expenses/add", {"category": "Subscriptions", "amount": "649",
                                       "date": f"{month}-05", "payment_mode": "UPI",
                                       "description": "netflix", "merchant": "Netflix"},
             content_type="multipart/form-data")
    conn = get_db_connection()
    uid = conn.execute("SELECT id FROM users LIMIT 1").fetchone()["id"]
    candidates = services.detect_recurring_candidates(conn, uid)
    conn.close()
    assert candidates == []

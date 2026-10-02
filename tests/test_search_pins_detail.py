from conftest import post
from database import get_db_connection
import services


def test_search_query_parses_amount_and_category_and_month():
    filters = services.parse_search_query("Food > 100 September UPI", ["Food", "Transport"])
    assert filters["category"] == "Food"
    assert filters["min_amount"] == 100.0
    assert filters["month"] == 9
    assert filters["payment_mode"] == "UPI"


def test_search_query_leftover_words_become_free_text():
    filters = services.parse_search_query("Amazon order", ["Food"])
    assert filters["free_text"] == ["Amazon", "order"]


def test_search_expenses_applies_parsed_filters(alice):
    post(alice, "/expenses/add", {"category": "Food", "amount": "500", "date": "2026-09-10",
                                   "payment_mode": "UPI", "description": "lunch"},
         content_type="multipart/form-data")
    post(alice, "/expenses/add", {"category": "Transport", "amount": "50", "date": "2026-09-10",
                                   "payment_mode": "Cash", "description": "cab"},
         content_type="multipart/form-data")
    conn = get_db_connection()
    uid = conn.execute("SELECT id FROM users LIMIT 1").fetchone()["id"]
    rows, _ = services.search_expenses(conn, uid, "Food > 100", ["Food", "Transport"])
    conn.close()
    assert len(rows) == 1 and rows[0]["category"] == "Food"


def test_api_search_uses_smart_parsing(alice):
    post(alice, "/expenses/add", {"category": "Food", "amount": "500", "date": "2026-09-10",
                                   "payment_mode": "UPI", "description": "lunch"},
         content_type="multipart/form-data")
    r = alice.get("/api/search?q=Food")
    body = r.get_json()
    assert len(body) == 1 and body[0]["category"] == "Food"


def test_pin_and_unpin_account(alice):
    post(alice, "/accounts", {"name": "HDFC Bank", "type": "Bank Account", "opening_balance": "100"})
    conn = get_db_connection()
    aid = conn.execute("SELECT id FROM accounts").fetchone()["id"]
    conn.close()
    post(alice, f"/pin/account/{aid}", {"label": "HDFC Bank"})
    conn = get_db_connection()
    count = conn.execute("SELECT COUNT(*) c FROM pinned_items").fetchone()["c"]
    conn.close()
    assert count == 1

    r = alice.get("/dashboard")
    assert b"HDFC Bank" in r.data

    post(alice, f"/unpin/account/{aid}")
    conn = get_db_connection()
    count = conn.execute("SELECT COUNT(*) c FROM pinned_items").fetchone()["c"]
    conn.close()
    assert count == 0


def test_pinning_twice_does_not_duplicate(alice):
    post(alice, "/accounts", {"name": "Cash", "type": "Cash", "opening_balance": "0"})
    conn = get_db_connection()
    aid = conn.execute("SELECT id FROM accounts").fetchone()["id"]
    conn.close()
    post(alice, f"/pin/account/{aid}", {"label": "Cash"})
    post(alice, f"/pin/account/{aid}", {"label": "Cash"})
    conn = get_db_connection()
    count = conn.execute("SELECT COUNT(*) c FROM pinned_items").fetchone()["c"]
    conn.close()
    assert count == 1


def test_transaction_detail_page_shows_fields(alice):
    post(alice, "/expenses/add", {"category": "Food", "amount": "500", "date": "2026-09-10",
                                   "payment_mode": "UPI", "description": "lunch", "merchant": "Swiggy"},
         content_type="multipart/form-data")
    conn = get_db_connection()
    eid = conn.execute("SELECT id FROM expenses").fetchone()["id"]
    conn.close()
    r = alice.get(f"/expenses/{eid}/view")
    assert r.status_code == 200
    assert b"Swiggy" in r.data and b"UPI" in r.data


def test_transaction_detail_shows_split_siblings(alice):
    post(alice, "/expenses/split/add", {
        "merchant": "Amazon", "date": "2026-09-12", "payment_mode": "UPI",
        "split_category[]": ["Electronics", "Books"], "split_amount[]": ["100", "50"],
    })
    conn = get_db_connection()
    eid = conn.execute("SELECT id FROM expenses WHERE category='Electronics'").fetchone()["id"]
    conn.close()
    r = alice.get(f"/expenses/{eid}/view")
    assert b"Books" in r.data


def test_transaction_detail_is_user_scoped(make_user):
    a, b = make_user("a@example.com"), make_user("b@example.com")
    post(a, "/expenses/add", {"category": "Food", "amount": "500", "date": "2026-09-10",
                               "payment_mode": "UPI", "description": "lunch"},
         content_type="multipart/form-data")
    conn = get_db_connection()
    eid = conn.execute("SELECT id FROM expenses").fetchone()["id"]
    conn.close()
    assert b.get(f"/expenses/{eid}/view").status_code == 404


def test_recent_activity_shows_on_dashboard(alice):
    post(alice, "/expenses/add", {"category": "Food", "amount": "500", "date": "2026-09-10",
                                   "payment_mode": "UPI", "description": "lunch"},
         content_type="multipart/form-data")
    r = alice.get("/dashboard")
    assert b"Recent activity" in r.data and b"Expense created" in r.data

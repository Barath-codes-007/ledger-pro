import io

from conftest import csrf, post
from database import get_db_connection

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


def add_expense(c, amount="120.50", receipt=None):
    data = {"category": "Food", "amount": amount, "date": "2026-09-10", "payment_mode": "UPI",
            "description": "Lunch"}
    if receipt:
        data["receipt"] = receipt
    return post(c, "/expenses/add", data, content_type="multipart/form-data")


def expense_id():
    conn = get_db_connection()
    r = conn.execute("SELECT id FROM expenses ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    return r["id"]


def test_csrf_required_on_post(alice):
    r = alice.post("/expenses/add", data={"category": "Food", "amount": "5", "date": "2026-09-10"})
    assert r.status_code == 400


def test_session_cookie_flags(client):
    cookie = client.get("/login").headers.get("Set-Cookie", "")
    assert "HttpOnly" in cookie and "SameSite=Lax" in cookie


def test_user_cannot_edit_or_delete_other_users_expense(make_user):
    a, b = make_user("a@example.com"), make_user("b@example.com")
    add_expense(a)
    eid = expense_id()
    assert b.get(f"/expenses/edit/{eid}").status_code == 404
    post(b, f"/expenses/delete/{eid}")
    conn = get_db_connection()
    assert conn.execute("SELECT COUNT(*) FROM expenses").fetchone()[0] == 1
    conn.close()


def test_user_cannot_see_other_users_receipt(make_user):
    a, b = make_user("a@example.com"), make_user("b@example.com")
    add_expense(a, receipt=(io.BytesIO(PNG), "r.png"))
    eid = expense_id()
    assert a.get(f"/receipts/{eid}").status_code == 200
    assert b.get(f"/receipts/{eid}").status_code == 404


def test_receipt_requires_login(client, make_user):
    a = make_user("a@example.com")
    add_expense(a, receipt=(io.BytesIO(PNG), "r.png"))
    assert client.get(f"/receipts/{expense_id()}").status_code == 302


def test_receipt_content_validated(alice):
    add_expense(alice, receipt=(io.BytesIO(b"<script>alert(1)</script>"), "evil.png"))
    conn = get_db_connection()
    assert conn.execute("SELECT COUNT(*) FROM expenses").fetchone()[0] == 0
    conn.close()


def test_receipt_name_is_randomized(alice):
    add_expense(alice, receipt=(io.BytesIO(PNG), "../../etc/passwd.png"))
    conn = get_db_connection()
    p = conn.execute("SELECT receipt_path FROM expenses").fetchone()[0]
    conn.close()
    assert p.startswith("receipts/") and "passwd" not in p and ".." not in p


def test_legacy_static_uploads_not_public(client):
    assert client.get("/static/uploads/anything.png").status_code == 404


def test_search_and_chart_api_are_user_scoped(make_user):
    a, b = make_user("a@example.com"), make_user("b@example.com")
    add_expense(a)
    assert b.get("/api/search?q=Lunch").get_json() == []
    assert b.get("/api/chart-data").get_json()["category_labels"] == []


def test_exports_are_user_scoped(make_user):
    a, b = make_user("a@example.com"), make_user("b@example.com")
    add_expense(a)
    assert b"Lunch" not in b.get("/reports/export/csv").data
    assert b"Lunch" in a.get("/reports/export/csv").data


def test_health_is_safe(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.get_json() == {"status": "ok"}


def test_no_hardcoded_secret_in_source():
    src = open("app.py").read()
    assert "dev-secret-key" not in src


def test_login_recorded_in_audit_log(client):
    from conftest import signup, login
    signup(client)
    login(client)
    resp = client.get("/audit-log")
    assert b"Login success" in resp.data


def test_settings_shows_previous_login_not_current(client):
    from conftest import signup, login
    signup(client)
    login(client)
    client.get("/logout")
    login(client)
    resp = client.get("/settings")
    assert b"first session" not in resp.data

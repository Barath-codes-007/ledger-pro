from conftest import post


def test_api_v1_requires_login(client):
    assert client.get("/api/v1/accounts").status_code == 302


def test_api_v1_accounts_scoped(make_user):
    a, b = make_user("a@example.com"), make_user("b@example.com")
    post(a, "/accounts", {"name": "HDFC Bank", "type": "Bank Account", "opening_balance": "500"})
    data_a = a.get("/api/v1/accounts").get_json()
    data_b = b.get("/api/v1/accounts").get_json()
    assert len(data_a) == 1 and data_a[0]["name"] == "HDFC Bank"
    assert data_b == []


def test_api_v1_net_worth_shape(alice):
    post(alice, "/accounts", {"name": "Cash", "type": "Cash", "opening_balance": "100"})
    data = alice.get("/api/v1/net-worth").get_json()
    assert set(data) == {"assets_minor", "liabilities_minor", "net_worth_minor"}


def test_api_v1_create_expense(alice):
    r = alice.post("/api/v1/expenses", json={"category": "Food", "amount": "45.50", "date": "2026-09-10",
                                              "description": "lunch"},
                    headers={"X-CSRF-Token": csrf_token(alice)})
    assert r.status_code == 201
    body = r.get_json()
    assert body["category"] == "Food" and body["amount"] == 45.5


def csrf_token(client):
    import re
    html = client.get("/dashboard").get_data(as_text=True)
    m = re.search(r'name="csrf-token" content="([^"]+)"', html)
    return m.group(1)


def test_api_v1_create_expense_validates(alice):
    r = alice.post("/api/v1/expenses", json={"category": "Food", "amount": "-5", "date": "2026-09-10"},
                    headers={"X-CSRF-Token": csrf_token(alice)})
    assert r.status_code == 422


def test_api_v1_get_update_delete_expense(alice):
    r = alice.post("/api/v1/expenses", json={"category": "Food", "amount": "20", "date": "2026-09-10"},
                    headers={"X-CSRF-Token": csrf_token(alice)})
    eid = r.get_json()["id"]

    got = alice.get(f"/api/v1/expenses/{eid}")
    assert got.status_code == 200 and got.get_json()["id"] == eid

    upd = alice.put(f"/api/v1/expenses/{eid}", json={"amount": "30"},
                     headers={"X-CSRF-Token": csrf_token(alice)})
    assert upd.status_code == 200 and upd.get_json()["amount"] == 30.0

    dele = alice.delete(f"/api/v1/expenses/{eid}", headers={"X-CSRF-Token": csrf_token(alice)})
    assert dele.status_code == 204
    assert alice.get(f"/api/v1/expenses/{eid}").status_code == 404


def test_api_v1_expense_detail_is_user_scoped(make_user):
    a, b = make_user("a@example.com"), make_user("b@example.com")
    r = a.post("/api/v1/expenses", json={"category": "Food", "amount": "20", "date": "2026-09-10"},
               headers={"X-CSRF-Token": csrf_token(a)})
    eid = r.get_json()["id"]
    assert b.get(f"/api/v1/expenses/{eid}").status_code == 404
    assert b.delete(f"/api/v1/expenses/{eid}", headers={"X-CSRF-Token": csrf_token(b)}).status_code == 404


def test_api_v1_expenses_pagination(alice):
    for i in range(5):
        alice.post("/api/v1/expenses", json={"category": "Food", "amount": "10", "date": "2026-09-10"},
                   headers={"X-CSRF-Token": csrf_token(alice)})
    r = alice.get("/api/v1/expenses?limit=2&offset=0")
    body = r.get_json()
    assert len(body["data"]) == 2 and body["total"] == 5 and body["limit"] == 2


def test_api_v1_create_income(alice):
    r = alice.post("/api/v1/income", json={"source": "Salary", "amount": "5000", "date": "2026-09-01"},
                    headers={"X-CSRF-Token": csrf_token(alice)})
    assert r.status_code == 201 and r.get_json()["source"] == "Salary"


def test_api_v1_create_account(alice):
    r = alice.post("/api/v1/accounts", json={"name": "HDFC", "type": "Bank Account", "opening_balance": "500"},
                    headers={"X-CSRF-Token": csrf_token(alice)})
    assert r.status_code == 201 and r.get_json()["balance"] == "500.00"


def test_api_v1_consistent_error_format(alice):
    r = alice.get("/api/v1/expenses/999999")
    body = r.get_json()
    assert r.status_code == 404 and "error" in body and "message" in body["error"]


def test_api_v1_rate_limited(alice, app):
    import app as ledger_app
    ledger_app.api_limiter.max_requests = 3
    try:
        for _ in range(3):
            assert alice.get("/api/v1/net-worth").status_code == 200
        r = alice.get("/api/v1/net-worth")
        assert r.status_code == 429
        assert "error" in r.get_json()
    finally:
        ledger_app.api_limiter.max_requests = 120
        ledger_app.api_limiter.clear()

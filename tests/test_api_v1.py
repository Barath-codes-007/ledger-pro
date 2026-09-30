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

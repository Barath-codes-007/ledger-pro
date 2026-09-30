from conftest import post


def test_statements_page_renders(alice):
    post(alice, "/expenses/add", {"category": "Food", "amount": "500", "date": "2026-09-10",
                                   "payment_mode": "UPI", "description": "lunch"},
         content_type="multipart/form-data")
    post(alice, "/income/add", {"source": "Salary", "amount": "5000", "date": "2026-09-01",
                                 "description": "pay"})
    post(alice, "/accounts", {"name": "HDFC", "type": "Bank Account", "opening_balance": "1000"})
    r = alice.get("/statements")
    assert r.status_code == 200
    assert b"Income Statement" in r.data and b"Balance Sheet" in r.data and b"Cash Flow Statement" in r.data


def test_statements_net_income_matches_income_minus_expense(alice):
    post(alice, "/expenses/add", {"category": "Food", "amount": "300", "date": "2026-09-10",
                                   "payment_mode": "UPI", "description": "lunch"},
         content_type="multipart/form-data")
    post(alice, "/income/add", {"source": "Salary", "amount": "1000", "date": "2026-09-01",
                                 "description": "pay"})
    r = alice.get("/statements?date_from=2026-09-01&date_to=2026-09-30")
    assert b"700.00" in r.data  # 1000 - 300 net income

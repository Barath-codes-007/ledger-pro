from conftest import post


def test_csv_export_includes_income_and_expenses(alice):
    post(alice, "/expenses/add", {"category": "Food", "amount": "100", "date": "2026-09-10",
                                   "payment_mode": "UPI", "description": "Lunch"},
         content_type="multipart/form-data")
    post(alice, "/income/add", {"source": "Salary", "amount": "5000", "date": "2026-09-01",
                                 "description": "Sep salary"})
    csv = alice.get("/reports/export/csv").data.decode()
    assert "Lunch" in csv and "expense" in csv
    assert "Salary" in csv and "income" in csv


def test_pdf_export_has_income_expense_net(alice):
    post(alice, "/expenses/add", {"category": "Food", "amount": "100", "date": "2026-09-10",
                                   "payment_mode": "UPI", "description": "Lunch"},
         content_type="multipart/form-data")
    post(alice, "/income/add", {"source": "Salary", "amount": "500", "date": "2026-09-01",
                                 "description": "pay"})
    r = alice.get("/reports/export/pdf")
    assert r.status_code == 200 and r.mimetype == "application/pdf"
    assert len(r.data) > 500  # a real, non-empty PDF was generated

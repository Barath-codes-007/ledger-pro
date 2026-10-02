from conftest import post
from database import get_db_connection


def test_income_full_crud_cycle(alice):
    post(alice, "/income/add", {"source": "Salary", "amount": "5000", "date": "2026-09-01",
                                 "description": "Sep pay"})
    conn = get_db_connection()
    iid = conn.execute("SELECT id FROM income").fetchone()["id"]
    conn.close()

    assert alice.get(f"/income/edit/{iid}").status_code == 200

    post(alice, f"/income/edit/{iid}", {"source": "Bonus", "amount": "6000", "date": "2026-09-02",
                                         "description": "updated"})
    conn = get_db_connection()
    row = conn.execute("SELECT * FROM income WHERE id=?", (iid,)).fetchone()
    conn.close()
    assert row["source"] == "Bonus" and row["amount"] == 6000.0 and row["amount_minor"] == 600000

    post(alice, f"/income/delete/{iid}")
    conn = get_db_connection()
    count = conn.execute("SELECT COUNT(*) c FROM income").fetchone()["c"]
    conn.close()
    assert count == 0


def test_income_edit_delete_user_scoped(make_user):
    a, b = make_user("a@example.com"), make_user("b@example.com")
    post(a, "/income/add", {"source": "Salary", "amount": "5000", "date": "2026-09-01", "description": "pay"})
    conn = get_db_connection()
    iid = conn.execute("SELECT id FROM income").fetchone()["id"]
    conn.close()

    assert b.get(f"/income/edit/{iid}").status_code == 404
    post(b, f"/income/delete/{iid}")
    conn = get_db_connection()
    count = conn.execute("SELECT COUNT(*) c FROM income").fetchone()["c"]
    conn.close()
    assert count == 1

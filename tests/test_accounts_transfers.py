from conftest import post
from database import get_db_connection
import services
from money import to_minor, to_major


def add_account(c, name="HDFC Bank", acc_type="Bank Account", opening="1000"):
    return post(c, "/accounts", {"name": name, "type": acc_type, "opening_balance": opening})


def test_create_account_sets_balance(alice):
    add_account(alice)
    conn = get_db_connection()
    a = conn.execute("SELECT * FROM accounts WHERE name='HDFC Bank'").fetchone()
    conn.close()
    assert a["balance_minor"] == 100000  # 1000.00 in paise


def test_transfer_moves_money_without_changing_net_worth(alice):
    add_account(alice, "HDFC Bank", opening="1000")
    add_account(alice, "Cash", "Cash", opening="0")
    conn = get_db_connection()
    uid = conn.execute("SELECT user_id FROM accounts LIMIT 1").fetchone()[0]
    accts = {a["name"]: a["id"] for a in conn.execute("SELECT id, name FROM accounts").fetchall()}
    before = services.net_worth(conn, uid)
    conn.close()

    post(alice, "/transfers/add", {
        "from_account_id": accts["HDFC Bank"], "to_account_id": accts["Cash"],
        "amount": "200", "date": "2026-09-10",
    })

    conn = get_db_connection()
    hdfc = conn.execute("SELECT balance_minor FROM accounts WHERE name='HDFC Bank'").fetchone()[0]
    cash = conn.execute("SELECT balance_minor FROM accounts WHERE name='Cash'").fetchone()[0]
    after = services.net_worth(conn, uid)
    conn.close()

    assert hdfc == 80000 and cash == 20000
    assert before["net_worth_minor"] == after["net_worth_minor"]


def test_transfer_rejects_same_account(alice):
    add_account(alice, "HDFC Bank", opening="1000")
    conn = get_db_connection()
    aid = conn.execute("SELECT id FROM accounts").fetchone()[0]
    conn.close()
    r = post(alice, "/transfers/add", {"from_account_id": aid, "to_account_id": aid,
                                        "amount": "10", "date": "2026-09-10"}, follow_redirects=True)
    conn = get_db_connection()
    bal = conn.execute("SELECT balance_minor FROM accounts").fetchone()[0]
    conn.close()
    assert bal == 100000  # unchanged


def test_credit_card_is_a_liability(alice):
    add_account(alice, "Visa", "Credit Card", opening="-500")
    conn = get_db_connection()
    uid = conn.execute("SELECT user_id FROM accounts LIMIT 1").fetchone()[0]
    nw = services.net_worth(conn, uid)
    conn.close()
    assert nw["liabilities_minor"] == 50000
    assert nw["net_worth_minor"] == -50000


def test_archived_account_hidden_but_not_deleted(alice):
    add_account(alice)
    conn = get_db_connection()
    aid = conn.execute("SELECT id FROM accounts").fetchone()[0]
    conn.close()
    post(alice, f"/accounts/archive/{aid}")
    conn = get_db_connection()
    row = conn.execute("SELECT status FROM accounts WHERE id=?", (aid,)).fetchone()
    conn.close()
    assert row["status"] == "archived"
    assert b"HDFC Bank" not in alice.get("/accounts").data


def test_reconciliation_computes_difference(alice):
    add_account(alice, "HDFC Bank", opening="1000")
    conn = get_db_connection()
    aid = conn.execute("SELECT id FROM accounts").fetchone()[0]
    conn.close()
    r = post(alice, f"/accounts/reconcile/{aid}", {"statement_balance": "950"}, follow_redirects=True)
    assert b"50.00" in r.data


def test_reconciliation_is_user_scoped(make_user):
    a, b = make_user("a@example.com"), make_user("b@example.com")
    add_account(a, "HDFC Bank", opening="1000")
    conn = get_db_connection()
    aid = conn.execute("SELECT id FROM accounts").fetchone()[0]
    conn.close()
    assert b.get(f"/accounts/reconcile/{aid}").status_code == 404

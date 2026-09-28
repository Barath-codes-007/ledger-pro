from conftest import csrf, signup, login, post
from database import get_db_connection


def test_signup_defaults_to_inr(client):
    signup(client)
    conn = get_db_connection()
    u = conn.execute("SELECT currency FROM users WHERE email='alice@example.com'").fetchone()
    s = conn.execute("SELECT currency FROM settings").fetchone()
    conn.close()
    assert u["currency"] == "INR" and s["currency"] == "INR"


def test_password_is_hashed(client):
    signup(client)
    conn = get_db_connection()
    h = conn.execute("SELECT password_hash FROM users").fetchone()[0]
    conn.close()
    assert "Passw0rd123" not in h and h.startswith(("scrypt", "pbkdf2"))


def test_weak_password_rejected(client):
    signup(client, password="short1")
    conn = get_db_connection()
    assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
    conn.close()


def test_login_logout_flow(client):
    signup(client)
    assert login(client).status_code == 302
    assert client.get("/dashboard").status_code == 200
    assert post(client, "/logout").status_code == 302
    assert client.get("/dashboard").status_code == 302


def test_logout_get_not_allowed(alice):
    assert alice.get("/logout").status_code == 405


def test_login_rate_limit(client):
    signup(client)
    for _ in range(5):
        login(client, password="wrong-pass-1")
    r = login(client)  # correct password, but now blocked
    assert r.status_code == 429


def test_delete_account_requires_password(alice):
    r = post(alice, "/settings/delete-account", {"password": "wrong"})
    conn = get_db_connection()
    assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1
    conn.close()
    post(alice, "/settings/delete-account", {"password": "Passw0rd123"})
    conn = get_db_connection()
    assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
    conn.close()

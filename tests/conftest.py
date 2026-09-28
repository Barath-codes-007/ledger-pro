import os
import re
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_tmp = tempfile.mkdtemp(prefix="ledger-test-")
os.environ["LEDGER_DB_PATH"] = os.path.join(_tmp, "test.db")
os.environ["LEDGER_RECEIPT_DIR"] = os.path.join(_tmp, "receipts")
os.environ["SECRET_KEY"] = "test-secret"

import app as ledger_app  # noqa: E402
from database import init_db, get_db_connection  # noqa: E402


@pytest.fixture()
def app():
    ledger_app.app.config.update(TESTING=True)
    init_db()
    conn = get_db_connection()
    for t in ("recurring_expenses", "budget", "income", "expenses", "settings", "users"):
        conn.execute(f"DELETE FROM {t}")
    conn.commit()
    conn.close()
    ledger_app.login_limiter.clear()
    return ledger_app.app


@pytest.fixture()
def client(app):
    return app.test_client()


def csrf(client, path="/login"):
    html = client.get(path).get_data(as_text=True)
    m = re.search(r'name="csrf_token" value="([^"]+)"', html) or re.search(r'name="csrf-token" content="([^"]+)"', html)
    return m.group(1)


def signup(client, name="Alice", email="alice@example.com", password="Passw0rd123"):
    return client.post("/signup", data={
        "name": name, "email": email, "password": password, "confirm_password": password,
        "csrf_token": csrf(client, "/signup"),
    })


def login(client, email="alice@example.com", password="Passw0rd123"):
    return client.post("/login", data={"email": email, "password": password, "csrf_token": csrf(client)})


def post(client, path, data=None, **kw):
    data = dict(data or {})
    data["csrf_token"] = csrf(client, "/dashboard")
    return client.post(path, data=data, **kw)


@pytest.fixture()
def alice(client):
    signup(client)
    login(client)
    return client


@pytest.fixture()
def make_user(app):
    def _make(email, name="User"):
        c = app.test_client()
        signup(c, name=name, email=email)
        login(c, email=email)
        return c
    return _make

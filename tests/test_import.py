import io

from conftest import csrf, post
from database import get_db_connection


def upload_csv(client, content, filename="expenses.csv"):
    data = {"file": (io.BytesIO(content.encode()), filename), "csrf_token": csrf(client, "/import")}
    return client.post("/import/preview", data=data, content_type="multipart/form-data")


def test_import_preview_valid_and_invalid_rows(alice):
    csv_content = (
        "date,amount,category,description\n"
        "2026-09-01,500,Food,lunch\n"
        "not-a-date,200,Food,bad date\n"
        "2026-09-02,-50,Food,bad amount\n"
    )
    r = upload_csv(alice, csv_content)
    assert r.status_code == 200
    assert b"500.00" in r.data
    assert b"unrecognized date" in r.data or b"bad date" in r.data


def test_import_missing_required_columns_rejected(alice):
    csv_content = "foo,bar\n1,2\n"
    r = upload_csv(alice, csv_content, filename="bad.csv")
    assert r.status_code == 302  # redirected back with a flash error
    conn = get_db_connection()
    count = conn.execute("SELECT COUNT(*) c FROM expenses").fetchone()["c"]
    conn.close()
    assert count == 0


def test_import_confirm_writes_rows_and_batch_record(alice):
    csv_content = "date,amount,category,description\n2026-09-01,500,Food,lunch\n2026-09-02,300,Food,dinner\n"
    preview = upload_csv(alice, csv_content)
    html = preview.get_data(as_text=True)
    import re
    token = re.search(r'name="token" value="([^"]+)"', html).group(1)

    r = post(alice, "/import/confirm", {"token": token, "skip_duplicates": "on"}, follow_redirects=True)
    assert b"Imported 2" in r.data

    conn = get_db_connection()
    count = conn.execute("SELECT COUNT(*) c FROM expenses WHERE payment_mode='Imported'").fetchone()["c"]
    batch = conn.execute("SELECT * FROM import_batches").fetchone()
    conn.close()
    assert count == 2
    assert batch["imported_rows"] == 2


def test_import_skips_duplicates_when_checked(alice):
    post(alice, "/expenses/add", {"category": "Food", "amount": "500", "date": "2026-09-01",
                                   "payment_mode": "UPI", "description": "lunch"},
         content_type="multipart/form-data")
    csv_content = "date,amount,category,description\n2026-09-01,500,Food,lunch again\n"
    preview = upload_csv(alice, csv_content)
    assert b"Possible duplicate" in preview.data

    import re
    token = re.search(r'name="token" value="([^"]+)"', preview.get_data(as_text=True)).group(1)
    r = post(alice, "/import/confirm", {"token": token, "skip_duplicates": "on"}, follow_redirects=True)
    assert b"Imported 0" in r.data and b"1 possible duplicate" in r.data


def test_import_is_user_scoped(make_user):
    a, b = make_user("a@example.com"), make_user("b@example.com")
    csv_content = "date,amount,category,description\n2026-09-01,500,Food,lunch\n"
    preview = upload_csv(a, csv_content)
    import re
    token = re.search(r'name="token" value="([^"]+)"', preview.get_data(as_text=True)).group(1)
    r = post(b, "/import/confirm", {"token": token, "skip_duplicates": "on"}, follow_redirects=True)
    assert b"expired" in r.data

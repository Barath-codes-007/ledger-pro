from conftest import post


def test_add_expense_page_has_voice_trigger_and_manual_form(alice):
    html = alice.get("/expenses/add").get_data(as_text=True)
    assert 'data-voice-entry="expense"' in html
    assert 'data-voice-form="expenseForm"' in html
    assert 'id="expenseForm"' in html
    assert "voice-assistant.js" in html
    # the manual form's real fields must still all be present and untouched
    assert 'name="category"' in html and 'name="amount"' in html
    assert 'name="date"' in html and 'name="description"' in html


def test_add_income_page_has_voice_trigger_and_manual_form(alice):
    html = alice.get("/income/add").get_data(as_text=True)
    assert 'data-voice-entry="income"' in html
    assert 'data-voice-form="incomeForm"' in html
    assert 'id="incomeForm"' in html
    assert "voice-assistant.js" in html
    assert 'name="source"' in html and 'name="amount"' in html


def test_manual_expense_entry_unaffected_by_voice_markup(alice):
    r = post(alice, "/expenses/add", {"category": "Food", "amount": "75", "date": "2026-10-10",
                                       "payment_mode": "Cash", "description": "still manual"},
              content_type="multipart/form-data", follow_redirects=True)
    assert b"still manual" in alice.get("/expenses").data


def test_manual_income_entry_unaffected_by_voice_markup(alice):
    post(alice, "/income/add", {"source": "Salary", "amount": "999", "date": "2026-10-10",
                                 "description": "still manual income"})
    assert b"still manual income" in alice.get("/income").data


def test_voice_assistant_js_is_valid_and_has_no_hardcoded_secrets():
    js = open("static/js/voice-assistant.js").read()
    assert "api_key" not in js.lower()
    assert "sk-" not in js  # no leaked API-style key
    assert "/api/voice/extract" in js


# ---------------------------------------------------------------------------
# Camera receipts, manual-form camera button, and the voice-mode field parity
# ---------------------------------------------------------------------------
import io
import os
import re

from database import get_db_connection

# A camera capture is a canvas JPEG named receipt-<timestamp>.jpg
JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00\x10JFIF" + b"0" * 64


def test_manual_form_has_camera_button_preview_and_script(alice):
    html = alice.get("/expenses/add").get_data(as_text=True)
    assert 'data-receipt-camera="receipt"' in html
    assert "Take photo" in html
    assert 'data-receipt-preview="receipt"' in html
    assert "receipt-camera.js" in html
    # receipt-camera.js must load before voice-assistant.js (voice mode uses it)
    assert html.index("receipt-camera.js") < html.index("voice-assistant.js")


def test_income_page_does_not_offer_receipts(alice):
    html = alice.get("/income/add").get_data(as_text=True)
    assert "receipt-camera.js" not in html and "data-receipt-camera" not in html


def test_camera_photo_is_stored_and_viewable_only_by_its_owner(make_user):
    a, b = make_user("a@example.com"), make_user("b@example.com")
    post(a, "/expenses/add", {
        "category": "Food", "amount": "120", "date": "2026-10-10", "payment_mode": "UPI",
        "description": "photographed bill",
        "receipt": (io.BytesIO(JPEG_BYTES), "receipt-1760000000000.jpg", "image/jpeg"),
    }, content_type="multipart/form-data")
    conn = get_db_connection()
    row = conn.execute("SELECT id, receipt_path FROM expenses WHERE description='photographed bill'").fetchone()
    conn.close()
    assert row["receipt_path"].startswith("receipts/") and row["receipt_path"].endswith(".jpg")
    assert "1760000000000" not in row["receipt_path"]          # original name is never used
    assert a.get(f"/receipts/{row['id']}").status_code == 200
    assert b.get(f"/receipts/{row['id']}").status_code == 404


def test_fake_image_is_rejected_even_if_named_like_a_camera_photo(alice):
    post(alice, "/expenses/add", {
        "category": "Food", "amount": "5", "date": "2026-10-10", "payment_mode": "Cash",
        "receipt": (io.BytesIO(b"<script>alert(1)</script>"), "receipt-1.jpg", "image/jpeg"),
    }, content_type="multipart/form-data")
    conn = get_db_connection()
    count = conn.execute("SELECT COUNT(*) c FROM expenses").fetchone()["c"]
    conn.close()
    assert count == 0


def test_voice_filled_form_saves_every_manual_field_including_receipt(alice):
    """What voice Save submits: the same fields the manual form has."""
    post(alice, "/expenses/add", {
        "category": "Other", "custom_category": "Pet Grooming", "amount": "800", "date": "2026-10-09",
        "description": "Nail trim", "payment_mode": "Debit Card", "merchant": "Happy Paws", "currency": "USD",
        "receipt": (io.BytesIO(JPEG_BYTES), "receipt-2.jpg", "image/jpeg"),
    }, content_type="multipart/form-data")
    conn = get_db_connection()
    r = conn.execute("SELECT * FROM expenses WHERE description='Nail trim'").fetchone()
    conn.close()
    assert (r["category"], r["amount_minor"], r["payment_mode"], r["merchant"], r["currency"]) == \
        ("Pet Grooming", 80000, "Debit Card", "Happy Paws", "USD")
    assert r["receipt_path"]


def test_voice_assistant_js_has_all_form_fields_receipt_panel_and_no_stray_bug():
    js = open("static/js/voice-assistant.js").read()
    for field in ('"#payment_mode"', '"#merchant"', '"#currency"', "voice-receipt-panel", "receipt_capture"):
        assert field in js
    assert "setStatus((s) => s)" not in js           # old bug: printed function source into the status badge
    assert "reask" in js                              # Edit buttons use the server's wording


def test_service_worker_is_network_first_for_static_files_and_cache_was_bumped():
    sw = open("static/sw.js").read()
    assert 'ledger-static-v1"' not in sw and "ledger-static-v2" in sw
    assert "receipt-camera.js" in sw
    # financial pages / APIs are still never served from cache
    assert "isStaticAsset" in sw
    handler = sw.split("event.respondWith(", 2)[-1]
    assert handler.lstrip().startswith("fetch(event.request)")      # fetch first, cache only as the offline fallback

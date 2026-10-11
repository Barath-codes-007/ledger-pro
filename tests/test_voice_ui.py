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

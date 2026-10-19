import re


def csrf_token(client):
    html = client.get("/dashboard").get_data(as_text=True)
    m = re.search(r'name="csrf-token" content="([^"]+)"', html)
    return m.group(1)


def voice_post(client, **body):
    return client.post("/api/voice/extract", json=body, headers={"X-CSRF-Token": csrf_token(client)})


def test_requires_login(client):
    # The global CSRF check (before_request) runs before @login_required,
    # so an unauthenticated POST with no CSRF token is rejected at 400
    # before it ever reaches the login check - same as every other POST
    # route in the app, not unique to this one.
    r = client.post("/api/voice/extract", json={"context": "expense", "utterance": "food"})
    assert r.status_code == 400


def test_requires_login_even_with_a_csrf_token(client):
    html = client.get("/login").get_data(as_text=True)
    import re
    m = re.search(r'name="csrf_token" value="([^"]+)"', html)
    token = m.group(1) if m else None
    r = client.post("/api/voice/extract", json={"context": "expense", "utterance": "food"},
                     headers={"X-CSRF-Token": token} if token else {})
    assert r.status_code in (302, 400)


def test_requires_csrf_header(alice):
    r = alice.post("/api/voice/extract", json={"context": "expense", "utterance": "food"})
    assert r.status_code == 400  # CSRF check from before_request


def test_rejects_bad_context(alice):
    r = voice_post(alice, context="bogus", utterance="food")
    assert r.status_code == 422


def test_rejects_non_object_draft(alice):
    r = voice_post(alice, context="expense", utterance="food", draft="not an object")
    assert r.status_code == 422


def test_first_turn_asks_for_category(alice):
    r = voice_post(alice, context="expense", utterance="", asking_field=None, draft={})
    body = r.get_json()
    assert body["field"] == "category"
    assert "expense" in body["question"].lower()


def test_single_sentence_asks_only_for_what_is_missing(alice):
    r = voice_post(alice, context="expense",
                    utterance="I spent 500 rupees on food for lunch today",
                    asking_field=None, draft={})
    body = r.get_json()
    assert body["ready"] is False and body["field"] == "payment_mode"
    assert body["draft"]["amount"] == 500.0 and body["draft"]["category"] == "Food"


def test_full_expense_conversation_through_the_api(alice):
    draft = {}

    def turn(utterance, asking_field):
        nonlocal draft
        r = voice_post(alice, context="expense", utterance=utterance, asking_field=asking_field, draft=draft)
        body = r.get_json()
        draft = body["draft"]
        return body

    assert turn("Food", "category")["field"] == "amount"
    assert turn("350 rupees", "amount")["field"] == "description"
    assert turn("Lunch", "description")["field"] == "date"
    assert turn("yes", "date")["field"] == "payment_mode"
    assert turn("UPI", "payment_mode")["field"] == "merchant"
    assert turn("skip", "merchant")["field"] == "receipt"   # currency came from "rupees"
    body = turn("no", "receipt")
    assert body["ready"] is True
    d = body["draft"]
    assert (d["category"], d["amount"], d["description"], d["payment_mode"], d["currency"]) == \
        ("Food", 350.0, "Lunch", "UPI", "INR")


def test_custom_category_confirmation_round_trip(alice):
    r = voice_post(alice, context="expense", utterance="pet grooming", asking_field="category", draft={})
    body = r.get_json()
    assert body["field"] == "category_confirm"
    assert body["low_confidence"] is True
    assert "Pet Grooming" in body["question"]

    r = voice_post(alice, context="expense", utterance="yes", asking_field="category_confirm",
                    draft=body["draft"])
    assert r.get_json()["draft"]["category"] == "Pet Grooming"


def test_voice_extraction_is_user_scoped_like_any_other_api(make_user):
    a, b = make_user("a@example.com"), make_user("b@example.com")
    ra = voice_post(a, context="expense", utterance="food", asking_field="category", draft={})
    rb = voice_post(b, context="expense", utterance="food", asking_field="category", draft={})
    assert ra.status_code == 200 and rb.status_code == 200
    # each call is stateless and scoped only by the caller's own session/draft
    assert ra.get_json()["draft"]["category"] == "Food"
    assert rb.get_json()["draft"]["category"] == "Food"


def test_income_conversation_through_the_api(alice):
    draft = {}
    r = voice_post(alice, context="income", utterance="Freelance", asking_field="source", draft=draft)
    draft = r.get_json()["draft"]
    assert r.get_json()["field"] == "amount"

    r = voice_post(alice, context="income", utterance="15000", asking_field="amount", draft=draft)
    draft = r.get_json()["draft"]

    r = voice_post(alice, context="income", utterance="Website development",
                    asking_field="description", draft=draft)
    draft = r.get_json()["draft"]

    r = voice_post(alice, context="income", utterance="yesterday", asking_field="date", draft=draft)
    body = r.get_json()
    assert body["ready"] is True
    assert body["draft"]["source"] == "Freelance"
    assert body["draft"]["amount"] == 15000.0


def test_api_no_to_todays_date_asks_for_the_date_with_format_hint(alice):
    draft = {"category": "Food", "amount": 100.0, "description": "Lunch"}
    first = voice_post(alice, context="expense", utterance="", asking_field=None, draft=draft).get_json()
    assert first["field"] == "date" and "today" in first["question"].lower()
    assert "yesterday" in first["hint"]

    second = voice_post(alice, context="expense", utterance="no", asking_field="date",
                         draft=first["draft"]).get_json()
    assert second["field"] == "date" and second["question"] != first["question"]
    assert "what date" in second["question"].lower() and "day-month-year" in second["question"]

    third = voice_post(alice, context="expense", utterance="yesterday", asking_field="date",
                        draft=second["draft"]).get_json()
    assert third["draft"]["date"] and third["field"] == "payment_mode"


def test_api_reask_returns_server_question_and_hint(alice):
    draft = {"category": "Food", "amount": 100.0, "description": "Lunch", "date": "2026-10-05"}
    body = voice_post(alice, context="expense", reask="date", draft=draft).get_json()
    assert body["field"] == "date" and "what date" in body["question"].lower()
    assert body["hint"] and "05-10-2026" in body["hint"]
    assert body["draft"]["date"] == "2026-10-05"           # old value kept until a new one is given
    body = voice_post(alice, context="expense", reask="receipt", draft={"receipt": "attached"}).get_json()
    assert "receipt" not in body["draft"]


def test_api_reask_rejects_unknown_field(alice):
    assert voice_post(alice, context="expense", reask="password", draft={}).status_code == 422


def test_api_uses_the_users_real_currency_in_the_currency_question(alice):
    draft = {"category": "Food", "amount": 20.0, "description": "x", "date": "2026-10-05",
             "payment_mode": "Cash", "skipped": ["merchant"]}
    body = voice_post(alice, context="expense", utterance="", asking_field=None, draft=draft).get_json()
    assert body["field"] == "currency" and body["user_currency"] in body["question"]


def test_api_receipt_flow_through_capture(alice):
    draft = {"category": "Food", "amount": 20.0, "description": "x", "date": "2026-10-05",
             "payment_mode": "Cash", "currency": "INR", "skipped": ["merchant"]}
    body = voice_post(alice, context="expense", utterance="yes", asking_field="receipt", draft=draft).get_json()
    assert body["field"] == "receipt_capture" and body["ready"] is False
    body = voice_post(alice, context="expense", utterance="attached", asking_field="receipt_capture",
                       draft=body["draft"]).get_json()
    assert body["ready"] is True

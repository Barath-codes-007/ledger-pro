import voice_parser as vp

CATEGORIES = ["Food", "Groceries", "Transport", "Shopping", "Entertainment", "Bills",
              "Health", "Education", "Rent", "Travel", "Subscriptions", "Insurance",
              "Gifts", "Other"]


# ---------------------------------------------------------------------------
# Amount parsing
# ---------------------------------------------------------------------------
def test_amount_plain_digits():
    assert vp.parse_amount("350") == 350.0


def test_amount_with_rupee_symbol():
    assert vp.parse_amount("₹500") == 500.0


def test_amount_with_rupees_word_after():
    assert vp.parse_amount("500 rupees") == 500.0


def test_amount_with_rs_before():
    assert vp.parse_amount("rs 1200") == 1200.0


def test_amount_with_comma_and_decimal():
    assert vp.parse_amount("1,234.50") == 1234.5


def test_amount_word_five_hundred():
    assert vp.parse_amount("five hundred") == 500.0


def test_amount_word_twenty_five_thousand():
    assert vp.parse_amount("twenty five thousand") == 25000.0


def test_amount_word_two_point_five_thousand():
    assert vp.parse_amount("two point five thousand") == 2500.0


def test_amount_word_two_lakh():
    assert vp.parse_amount("two lakh") == 200000.0


def test_amount_none_when_absent():
    assert vp.parse_amount("just some text with no number") is None


def test_amount_none_for_empty():
    assert vp.parse_amount("") is None
    assert vp.parse_amount(None) is None


# ---------------------------------------------------------------------------
# Date parsing
# ---------------------------------------------------------------------------
def test_date_today():
    import datetime
    d = datetime.date(2026, 10, 5)
    assert vp.parse_date_phrase("today", today=d) == "2026-10-05"


def test_date_yesterday():
    import datetime
    d = datetime.date(2026, 10, 5)
    assert vp.parse_date_phrase("yesterday", today=d) == "2026-10-04"


def test_date_day_before_yesterday():
    import datetime
    d = datetime.date(2026, 10, 5)
    assert vp.parse_date_phrase("day before yesterday", today=d) == "2026-10-03"


def test_date_explicit_day_month():
    import datetime
    d = datetime.date(2026, 10, 5)
    assert vp.parse_date_phrase("5th october", today=d) == "2026-10-05"


def test_date_month_then_day():
    import datetime
    d = datetime.date(2026, 1, 1)
    assert vp.parse_date_phrase("october 5", today=d) == "2026-10-05"


def test_date_none_when_unrecognized():
    assert vp.parse_date_phrase("sometime recently") is None


def test_date_none_for_empty():
    assert vp.parse_date_phrase("") is None


# ---------------------------------------------------------------------------
# Category matching
# ---------------------------------------------------------------------------
def test_category_exact_match():
    cat, conf = vp.match_category("food", CATEGORIES)
    assert cat == "Food" and conf == "exact"


def test_category_keyword_restaurant_dinner():
    cat, conf = vp.match_category("had dinner at a restaurant", CATEGORIES)
    assert cat == "Food" and conf == "keyword"


def test_category_keyword_uber():
    cat, conf = vp.match_category("uber to college", CATEGORIES)
    assert cat == "Transport" and conf == "keyword"


def test_category_keyword_netflix():
    cat, conf = vp.match_category("netflix subscription", CATEGORIES)
    assert cat in ("Entertainment", "Subscriptions") and conf == "keyword"


def test_category_custom_short_phrase():
    cat, conf = vp.match_category("pet grooming", CATEGORIES)
    assert cat == "Pet Grooming" and conf == "custom"


def test_category_none_for_long_ambiguous_sentence():
    cat, conf = vp.match_category(
        "well I am not really sure what this was for honestly", CATEGORIES)
    assert conf == "none"


# ---------------------------------------------------------------------------
# Description extraction
# ---------------------------------------------------------------------------
def test_description_strips_amount_and_category():
    desc = vp.extract_description("spent 500 rupees on food for lunch", category_hint="Food")
    assert desc is not None
    assert "lunch" in desc.lower()
    assert "500" not in desc


def test_description_none_when_nothing_left():
    desc = vp.extract_description("500 rupees food today", category_hint="Food")
    assert desc is None


# ---------------------------------------------------------------------------
# Full-sentence extraction (spec's own worked examples)
# ---------------------------------------------------------------------------
def test_extract_all_single_sentence_example():
    import datetime
    result = vp.extract_all("I spent 500 rupees on food for lunch today",
                             CATEGORIES, today=datetime.date(2026, 10, 5))
    assert result["amount"] == 500.0
    assert result["category"] == "Food"
    assert result["date"] == "2026-10-05"
    assert result["description"] and "lunch" in result["description"].lower()


def test_extract_all_uber_example():
    result = vp.extract_all("Uber to college", CATEGORIES)
    assert result["category"] == "Transport"


def test_extract_all_missing_fields_are_none_not_guessed():
    result = vp.extract_all("hello", CATEGORIES)
    assert result["amount"] is None
    assert result["category"] is None
    assert result["date"] is None


# ---------------------------------------------------------------------------
# Conversation state machine - the spec's own worked examples
# ---------------------------------------------------------------------------
import datetime as _dt

TODAY = _dt.date(2026, 10, 5)


def _run_turns(turns, context="expense", categories=CATEGORIES):
    """turns: list of (asking_field, utterance). Returns the final draft
    plus the (question, field, low_conf, ready) from after the last turn."""
    draft = {}
    step = None
    for asking_field, utterance in turns:
        draft = vp.update_draft(draft, utterance, asking_field, context, categories, today=TODAY)
        step = vp.next_step(draft, context)
    return draft, step


def test_expense_full_step_by_step_conversation_matches_spec_example():
    draft = {}
    draft = vp.update_draft(draft, "Food", "category", "expense", CATEGORIES, today=TODAY)
    assert vp.next_step(draft, "expense")[1] == "amount"

    draft = vp.update_draft(draft, "350 rupees", "amount", "expense", CATEGORIES, today=TODAY)
    assert vp.next_step(draft, "expense")[1] == "description"

    draft = vp.update_draft(draft, "Lunch", "description", "expense", CATEGORIES, today=TODAY)
    assert vp.next_step(draft, "expense")[1] == "date"

    draft = vp.update_draft(draft, "Yes", "date", "expense", CATEGORIES, today=TODAY)
    assert vp.next_step(draft, "expense")[1] == "payment_mode"   # now asked too

    draft = vp.update_draft(draft, "UPI", "payment_mode", "expense", CATEGORIES, today=TODAY)
    assert vp.next_step(draft, "expense")[1] == "merchant"

    draft = vp.update_draft(draft, "skip", "merchant", "expense", CATEGORIES, today=TODAY)
    # "350 rupees" already told us the currency, so that question is skipped
    assert draft["currency"] == "INR" and vp.next_step(draft, "expense")[1] == "receipt"

    draft = vp.update_draft(draft, "no", "receipt", "expense", CATEGORIES, today=TODAY)
    assert vp.next_step(draft, "expense")[3] is True

    assert draft["category"] == "Food" and draft["amount"] == 350.0
    assert draft["description"] == "Lunch" and draft["date"] == "2026-10-05"
    assert draft["payment_mode"] == "UPI"


def test_expense_single_sentence_only_asks_what_is_still_missing():
    draft = vp.update_draft({}, "I spent 500 rupees on food for lunch today",
                             None, "expense", CATEGORIES, today=TODAY)
    assert draft["amount"] == 500.0 and draft["category"] == "Food"
    assert draft["date"] == "2026-10-05" and "lunch" in draft["description"].lower()
    # category/amount/description/date/currency are known - next is the
    # payment type, NOT a repeat of anything already said.
    q, field, low, ready = vp.next_step(draft, "expense")
    assert field == "payment_mode" and ready is False


def test_expense_everything_in_one_sentence_reaches_receipt_question():
    draft = vp.update_draft(
        {}, "I spent 500 rupees on food for lunch at Swiggy by UPI today",
        None, "expense", CATEGORIES, today=TODAY)
    assert draft["payment_mode"] == "UPI" and draft["merchant"] == "Swiggy"
    assert draft["description"] == "Lunch"
    assert vp.next_step(draft, "expense")[1] == "receipt"


def test_expense_custom_category_requires_confirmation_then_accepts_yes():
    draft = vp.update_draft({}, "Category is pet grooming", "category", "expense", CATEGORIES, today=TODAY)
    q, field, low, ready = vp.next_step(draft, "expense")
    assert field == "category_confirm" and low is True
    assert "Pet Grooming" in q

    draft = vp.update_draft(draft, "yes", "category_confirm", "expense", CATEGORIES, today=TODAY)
    assert draft["category"] == "Pet Grooming"
    assert draft["category_confidence"] == "confirmed"


def test_expense_custom_category_rejected_can_be_redone():
    draft = vp.update_draft({}, "xyz", "category", "expense", CATEGORIES, today=TODAY)
    draft = vp.update_draft(draft, "no", "category_confirm", "expense", CATEGORIES, today=TODAY)
    assert draft.get("category") is None
    assert draft.get("category_pending") is None


def test_income_full_conversation_matches_spec_example():
    draft = {}
    draft = vp.update_draft(draft, "Freelance", "source", "income", CATEGORIES, today=TODAY)
    q, field, low, ready = vp.next_step(draft, "income")
    assert field == "amount"

    draft = vp.update_draft(draft, "15000", "amount", "income", CATEGORIES, today=TODAY)
    q, field, low, ready = vp.next_step(draft, "income")
    assert field == "description"

    draft = vp.update_draft(draft, "Website development", "description", "income", CATEGORIES, today=TODAY)
    q, field, low, ready = vp.next_step(draft, "income")
    assert field == "date"

    draft = vp.update_draft(draft, "yesterday", "date", "income", CATEGORIES, today=TODAY)
    q, field, low, ready = vp.next_step(draft, "income")
    assert ready is True

    assert draft["source"] == "Freelance"
    assert draft["amount"] == 15000.0
    assert draft["description"] == "Website development"
    assert draft["date"] == "2026-10-04"


def test_direct_answer_is_never_overwritten_by_a_later_bonus_guess():
    draft = vp.update_draft({}, "350", "amount", "expense", CATEGORIES, today=TODAY)
    # A later turn mentions a different number in passing while answering
    # a DIFFERENT field - must not clobber the already-given amount.
    draft = vp.update_draft(draft, "it was around 500 or so but never mind, lunch",
                             "description", "expense", CATEGORIES, today=TODAY)
    assert draft["amount"] == 350.0


def test_context_change_actually_make_that_600():
    draft = vp.update_draft({}, "500", "amount", "expense", CATEGORIES, today=TODAY)
    assert draft["amount"] == 500.0
    draft = vp.update_draft(draft, "actually make that 600", "amount", "expense", CATEGORIES, today=TODAY)
    assert draft["amount"] == 600.0


def test_missing_amount_is_asked_for_specifically():
    draft = {"category": "Food", "category_confidence": "exact"}
    q, field, low, ready = vp.next_step(draft, "expense")
    assert field == "amount"
    assert "spend" in q.lower()


# ---------------------------------------------------------------------------
# The reported bugs: "no" to today's date, date formats, and the missing
# manual-form fields (payment type, merchant, currency, receipt)
# ---------------------------------------------------------------------------
def test_saying_no_to_todays_date_asks_for_the_actual_date_instead_of_repeating():
    draft = {"category": "Food", "amount": 100.0, "description": "Lunch"}
    q1, field1, _, _ = vp.next_step(draft, "expense")
    assert field1 == "date" and "today" in q1.lower()
    draft = vp.update_draft(draft, "no", "date", "expense", CATEGORIES, today=TODAY)
    q2, field2, _, _ = vp.next_step(draft, "expense")
    assert field2 == "date" and q2 != q1 and "what date" in q2.lower()


def test_date_question_states_the_expected_format():
    declined = {"category": "Food", "amount": 1.0, "description": "x", "date_declined_today": True}
    q, field, _, _ = vp.next_step(declined, "expense")
    assert "day-month-year" in q and ("05-10-2026" in q or "5th October" in q)
    assert "yesterday" in vp.hint_for("date")


def test_after_no_a_real_date_is_accepted():
    draft = {"category": "Food", "amount": 100.0, "description": "Lunch"}
    draft = vp.update_draft(draft, "no", "date", "expense", CATEGORIES, today=TODAY)
    draft = vp.update_draft(draft, "5th October", "date", "expense", CATEGORIES, today=TODAY)
    assert draft["date"] == "2026-10-05" and "date_declined_today" not in draft


def test_no_comma_yesterday_keeps_the_date_it_contained():
    draft = vp.update_draft({}, "no, yesterday", "date", "expense", CATEGORIES, today=TODAY)
    assert draft["date"] == "2026-10-04"


def test_unparseable_date_explains_the_format_not_just_repeats():
    draft = vp.update_draft({"category": "Food", "amount": 1.0, "description": "x"},
                             "whenever", "date", "expense", CATEGORIES, today=TODAY)
    q, field, _, _ = vp.next_step(draft, "expense")
    assert field == "date" and "couldn't understand that date" in q.lower() and "day-month-year" in q


def test_unparseable_amount_gives_the_spec_error_message():
    draft = vp.update_draft({"category": "Food"}, "a lot", "amount", "expense", CATEGORIES, today=TODAY)
    q, field, _, _ = vp.next_step(draft, "expense")
    assert field == "amount" and "couldn't understand the amount" in q.lower() and "500 rupees" in q


def test_date_numeric_day_first_and_days_ago():
    assert vp.parse_date_phrase("05-10-2026", today=TODAY) == "2026-10-05"
    assert vp.parse_date_phrase("5/10/2026", today=TODAY) == "2026-10-05"
    assert vp.parse_date_phrase("two days ago", today=TODAY) == "2026-10-03"
    assert vp.parse_date_phrase("a week ago", today=TODAY) == "2026-09-28"
    assert vp.parse_date_phrase("32-13-2026", today=TODAY) is None  # impossible date, no guess


def test_date_digits_are_never_mistaken_for_the_amount():
    assert vp.parse_amount("spent on 05-10-2026", strict=True) is None
    r = vp.extract_all("spent 250 on transport on 05-10-2026", CATEGORIES, today=TODAY)
    assert r["amount"] == 250.0 and r["date"] == "2026-10-05"


def test_casual_number_words_are_not_read_as_an_amount_in_a_sentence():
    assert vp.extract_all("bought two coffees", CATEGORIES)["amount"] is None   # a quantity, not an amount
    assert vp.parse_amount("two") == 2.0                                        # but fine as a direct answer


def test_payment_mode_parsing_maps_to_real_app_modes():
    modes = ["Cash", "Credit Card", "Debit Card", "UPI", "Net Banking", "Wallet"]
    assert vp.parse_payment_mode("paid by UPI", modes) == "UPI"
    assert vp.parse_payment_mode("google pay", modes) == "UPI"
    assert vp.parse_payment_mode("with my credit card", modes) == "Credit Card"
    assert vp.parse_payment_mode("debit card", modes) == "Debit Card"
    assert vp.parse_payment_mode("in cash", modes) == "Cash"
    assert vp.parse_payment_mode("net banking", modes) == "Net Banking"
    assert vp.parse_payment_mode("something else", modes) is None


def test_payment_mode_question_is_asked_and_unrecognized_answer_explains_options():
    draft = {"category": "Food", "amount": 100.0, "description": "x", "date": "2026-10-05"}
    q, field, _, _ = vp.next_step(draft, "expense")
    assert field == "payment_mode" and "type of payment" in q.lower()
    draft = vp.update_draft(draft, "banana", "payment_mode", "expense", CATEGORIES, today=TODAY)
    q, field, _, _ = vp.next_step(draft, "expense")
    assert field == "payment_mode" and "cash, UPI, credit card" in q


def test_merchant_parsing_and_skip():
    assert vp.parse_merchant("lunch at Swiggy today") == "Swiggy"
    assert vp.parse_merchant("bought it from Big Bazaar by upi") == "Big Bazaar"
    assert vp.parse_merchant("no merchant words here") is None
    draft = vp.update_draft({}, "skip", "merchant", "expense", CATEGORIES, today=TODAY)
    assert "merchant" in draft["skipped"]
    full = {"category": "Food", "amount": 1.0, "description": "x", "date": "2026-10-05",
            "payment_mode": "UPI", "currency": "INR", "skipped": ["merchant"], "receipt": "no"}
    assert vp.next_step(full, "expense")[3] is True       # skipped optional field isn't asked again


def test_currency_parsing_and_default_confirmation():
    codes = ["USD", "EUR", "GBP", "INR", "JPY", "AUD", "CAD"]
    assert vp.parse_currency("20 dollars", codes) == "USD"
    assert vp.parse_currency("fifty euros", codes) == "EUR"
    assert vp.parse_currency("500 rupees", codes) == "INR"
    assert vp.parse_currency("australian dollars", codes) == "AUD"
    assert vp.parse_currency("nothing here", codes) is None
    base = {"category": "Food", "amount": 20.0, "description": "x", "date": "2026-10-05",
            "payment_mode": "Cash", "skipped": ["merchant"]}
    q, field, _, _ = vp.next_step(base, "expense", user_currency="INR")
    assert field == "currency" and "INR" in q
    d = vp.update_draft(base, "yes", "currency", "expense", CATEGORIES, today=TODAY, user_currency="INR")
    assert d["currency"] == "INR"
    d = vp.update_draft(base, "dollars", "currency", "expense", CATEGORIES, today=TODAY, user_currency="INR")
    assert d["currency"] == "USD"


def test_receipt_yes_leads_to_capture_step_then_attached():
    base = {"category": "Food", "amount": 1.0, "description": "x", "date": "2026-10-05",
            "payment_mode": "Cash", "currency": "INR", "skipped": ["merchant"]}
    q, field, _, _ = vp.next_step(base, "expense")
    assert field == "receipt" and "receipt" in q.lower()
    d = vp.update_draft(base, "yes", "receipt", "expense", CATEGORIES, today=TODAY)
    q, field, _, ready = vp.next_step(d, "expense")
    assert field == "receipt_capture" and ready is False and "photo" in q.lower() and "upload" in q.lower()
    d = vp.update_draft(d, "attached", "receipt_capture", "expense", CATEGORIES, today=TODAY)
    assert d["receipt"] == "attached" and vp.next_step(d, "expense")[3] is True


def test_receipt_capture_can_be_skipped_and_still_finishes():
    base = {"category": "Food", "amount": 1.0, "description": "x", "date": "2026-10-05",
            "payment_mode": "Cash", "currency": "INR", "skipped": ["merchant"], "receipt": "pending"}
    d = vp.update_draft(base, "skip", "receipt_capture", "expense", CATEGORIES, today=TODAY)
    assert d["receipt"] == "skipped" and vp.next_step(d, "expense")[3] is True


def test_receipt_unclear_answer_asks_again_with_guidance():
    base = {"category": "Food", "amount": 1.0, "description": "x", "date": "2026-10-05",
            "payment_mode": "Cash", "currency": "INR", "skipped": ["merchant"]}
    d = vp.update_draft(base, "hmm maybe", "receipt", "expense", CATEGORIES, today=TODAY)
    q, field, _, _ = vp.next_step(d, "expense")
    assert field == "receipt" and "yes" in q.lower() and "no" in q.lower()


def test_income_flow_is_unchanged_by_the_expense_only_fields():
    draft = {"source": "Freelance", "amount": 15000.0, "description": "Site", "date": "2026-10-04"}
    assert vp.next_step(draft, "income")[3] is True


def test_question_for_is_the_single_source_of_truth_for_edit_buttons():
    assert "payment" in vp.question_for("payment_mode", "expense").lower()
    assert "receipt" in vp.question_for("receipt", "expense").lower()
    assert "what date" in vp.question_for("date", "expense", {"date_declined_today": True}).lower()

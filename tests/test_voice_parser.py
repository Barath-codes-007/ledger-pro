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
    turns = [
        (None, "start"),  # opening prompt, nothing said yet handled by first next_step call separately
    ]
    draft = {}
    draft = vp.update_draft(draft, "Food", "category", "expense", CATEGORIES, today=TODAY)
    q, field, low, ready = vp.next_step(draft, "expense")
    assert field == "amount"

    draft = vp.update_draft(draft, "350 rupees", "amount", "expense", CATEGORIES, today=TODAY)
    q, field, low, ready = vp.next_step(draft, "expense")
    assert field == "description"

    draft = vp.update_draft(draft, "Lunch", "description", "expense", CATEGORIES, today=TODAY)
    q, field, low, ready = vp.next_step(draft, "expense")
    assert field == "date"

    draft = vp.update_draft(draft, "Yes", "date", "expense", CATEGORIES, today=TODAY)
    q, field, low, ready = vp.next_step(draft, "expense")
    assert ready is True

    assert draft["category"] == "Food"
    assert draft["amount"] == 350.0
    assert draft["description"] == "Lunch"
    assert draft["date"] == "2026-10-05"


def test_expense_single_sentence_skips_all_questions():
    draft = vp.update_draft({}, "I spent 500 rupees on food for lunch today",
                             None, "expense", CATEGORIES, today=TODAY)
    q, field, low, ready = vp.next_step(draft, "expense")
    assert ready is True, f"expected ready, got next field={field}"
    assert draft["amount"] == 500.0
    assert draft["category"] == "Food"
    assert draft["date"] == "2026-10-05"
    assert "lunch" in draft["description"].lower()


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

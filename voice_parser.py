"""
voice_parser.py
Turns a speech-recognition transcript into structured financial fields
(amount, category, description, date). This is a deterministic, rule-based
parser - NOT a call to an external AI/LLM. There is no AI API key anywhere
in this app; building a fake "AI understands you" experience on top of
regex would be exactly the kind of fake AI response the project avoids
elsewhere (see copilot.py, which is the same honest pattern).

Architecture note (see spec #7): speech capture and language detection
happen in the browser via the Web Speech API, in English only right now
(`lang="en-IN"`). This module only ever receives already-recognized text,
so adding another language later means: (a) point the browser recognizer
at that language's BCP-47 code, and (b) add a NUMBER_WORDS / CATEGORY_
KEYWORDS table for that language here. No other architecture change
needed. No language beyond English is claimed as supported today.
"""

import re
from datetime import datetime, timedelta

# ---------------------------------------------------------------------------
# Amount parsing: digits, "rupees"/"rs"/"₹", and English number words
# including Indian lakh/crore.
# ---------------------------------------------------------------------------
_ONES = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
_TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
    "seventy": 70, "eighty": 80, "ninety": 90,
}
_SCALES = {"hundred": 100, "thousand": 1000, "lakh": 100000, "lac": 100000, "crore": 10000000}
_CURRENCY_WORDS = r"(?:rupees?|rs\.?|inr|₹)"


def _parse_integer_phrase(tokens):
    """Parse a token list with no 'point' in it into an integer, applying
    hundred/thousand/lakh/crore as scale multipliers along the way."""
    total = 0
    current = 0
    found_any = False
    for tok in tokens:
        if tok.isdigit():
            current += int(tok)
            found_any = True
        elif tok in _ONES:
            current += _ONES[tok]
            found_any = True
        elif tok in _TENS:
            current += _TENS[tok]
            found_any = True
        elif tok in _SCALES:
            scale = _SCALES[tok]
            if scale >= 1000:
                total += (current or 1) * scale
                current = 0
            else:
                current = (current or 1) * scale
            found_any = True
        # unrecognized words (e.g. "and", "rupees") are silently skipped
    total += current
    return total if found_any else None


def _words_to_number(text):
    """Convert a run of English number words (optionally with 'point' for
    decimals, and an optional trailing scale word that multiplies the
    WHOLE decimal - e.g. "two point five thousand" = 2.5 x 1000 = 2500)
    into a float. Returns None if no recognizable number words are found."""
    tokens = re.findall(r"[a-z]+|\d+(?:\.\d+)?", text.lower())
    if not tokens:
        return None

    if "point" in tokens:
        idx = tokens.index("point")
        whole = _parse_integer_phrase(tokens[:idx]) or 0
        right = tokens[idx + 1:]

        # Fractional part: consume only single-digit words/digits immediately
        # after "point" (standard spoken-decimal form: "point five" = .5).
        frac_digits = ""
        i = 0
        while i < len(right):
            tok = right[i]
            if tok.isdigit() and len(tok) == 1:
                frac_digits += tok
            elif tok in _ONES and _ONES[tok] <= 9:
                frac_digits += str(_ONES[tok])
            else:
                break
            i += 1

        value = whole + (float(f"0.{frac_digits}") if frac_digits else 0.0)
        if not whole and not frac_digits:
            return None

        # Any scale word left over (e.g. "thousand") multiplies the whole
        # decimal value, not just the fractional digits.
        for tok in right[i:]:
            if tok in _SCALES:
                value *= _SCALES[tok]
        return value

    result = _parse_integer_phrase(tokens)
    return float(result) if result is not None else None


def parse_amount(text):
    """
    Returns a float amount or None. Handles: "350", "₹500", "500 rupees",
    "rs 500", "1,000.50", "five hundred", "two point five thousand",
    "twenty five thousand", "two lakh".
    """
    if not text:
        return None
    cleaned = text.lower().strip()

    # Digit form first (most common / least ambiguous): ₹500, 500 rupees, 1,000.50
    m = re.search(_CURRENCY_WORDS + r"\s*([\d,]+(?:\.\d+)?)", cleaned)
    if not m:
        m = re.search(r"([\d,]+(?:\.\d+)?)\s*" + _CURRENCY_WORDS, cleaned)
    if not m:
        m = re.search(r"(?<![a-z])([\d,]+(?:\.\d+)?)(?![a-z])", cleaned)
    if m:
        try:
            return float(m.group(1).replace(",", ""))
        except ValueError:
            pass

    # Word form: "five hundred", "two lakh", "two point five thousand"
    word_value = _words_to_number(cleaned)
    if word_value:
        return word_value

    return None


# ---------------------------------------------------------------------------
# Date parsing: relative phrases + "<day> <month>" / "<month> <day>" + ISO
# ---------------------------------------------------------------------------
_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}


def parse_date_phrase(text, today=None):
    """
    Returns an ISO date string (YYYY-MM-DD) or None. Handles "today",
    "yesterday", "day before yesterday", "<day> <month>", "<month> <day>",
    and a plain ISO date already present in the text. Confident (unambiguous)
    matches only - anything else returns None rather than guessing.
    """
    if not text:
        return None
    today = today or datetime.now().date()
    low = text.lower().strip()

    if re.search(r"\btoday\b", low):
        return today.isoformat()
    if re.search(r"\bday before yesterday\b", low):
        return (today - timedelta(days=2)).isoformat()
    if re.search(r"\byesterday\b", low):
        return (today - timedelta(days=1)).isoformat()
    if re.search(r"\btomorrow\b", low):
        return (today + timedelta(days=1)).isoformat()

    iso = re.search(r"\b(20\d{2})-(\d{1,2})-(\d{1,2})\b", low)
    if iso:
        try:
            y, mo, d = int(iso.group(1)), int(iso.group(2)), int(iso.group(3))
            return datetime(y, mo, d).date().isoformat()
        except ValueError:
            return None

    # "5th october" / "5 october 2026" / "october 5"
    month_pattern = "|".join(sorted(_MONTHS, key=len, reverse=True))
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(" + month_pattern + r")\s*(\d{4})?\b", low)
    if not m:
        m2 = re.search(r"\b(" + month_pattern + r")\s+(\d{1,2})(?:st|nd|rd|th)?\s*,?\s*(\d{4})?\b", low)
        if m2:
            month, day, year = m2.group(1), int(m2.group(2)), m2.group(3)
            m = True
        else:
            m = None
    else:
        day, month, year = int(m.group(1)), m.group(2), m.group(3)

    if m:
        year = int(year) if year else today.year
        try:
            return datetime(year, _MONTHS[month], day).date().isoformat()
        except ValueError:
            return None

    return None


# ---------------------------------------------------------------------------
# Category matching: exact name, keyword table, or a short custom phrase
# ---------------------------------------------------------------------------
CATEGORY_KEYWORDS = {
    "Food": ["food", "lunch", "dinner", "breakfast", "restaurant", "grocery",
             "groceries", "snack", "coffee", "tea", "swiggy", "zomato", "meal"],
    "Transport": ["transport", "uber", "ola", "cab", "taxi", "bus", "train",
                  "metro", "auto", "petrol", "fuel", "gas", "parking"],
    "Shopping": ["shopping", "clothes", "clothing", "amazon", "flipkart",
                 "shoes", "mall"],
    "Entertainment": ["entertainment", "movie", "netflix", "cinema", "concert",
                       "game", "spotify", "prime video", "theatre"],
    "Bills": ["bill", "bills", "electricity", "water bill", "broadband",
              "wifi", "phone bill", "mobile recharge"],
    "Health": ["health", "doctor", "medicine", "hospital", "pharmacy",
               "medical", "clinic"],
    "Education": ["education", "school", "college", "course", "tuition",
                  "books", "fees"],
    "Rent": ["rent", "house rent", "landlord"],
    "Travel": ["travel", "flight", "hotel", "vacation", "trip", "airbnb"],
    "Subscriptions": ["subscription", "subscriptions", "membership"],
    "Insurance": ["insurance", "premium"],
    "Gifts": ["gift", "gifts", "present"],
}

_FILLER_WORDS = {
    "i", "spent", "paid", "spend", "pay", "on", "for", "the", "a", "an",
    "rupees", "rupee", "rs", "inr", "today", "yesterday", "tomorrow", "and",
    "it", "was", "is", "of", "to", "got", "had", "category", "type",
    "called", "named", "this",
}

# Common conversational words that should never be guessed as a custom
# category, even though they're short and don't match any known keyword.
_NON_CATEGORY_WORDS = {
    "hello", "hi", "hey", "yes", "no", "ok", "okay", "sure", "nothing",
    "none", "cancel", "stop", "back", "repeat", "help", "thanks", "thank",
}


def match_category(text, known_categories):
    """
    Returns (category, confidence) where confidence is one of:
    "exact"   - text matches an existing category name exactly
    "keyword" - a known keyword maps to an existing category
    "custom"  - no match, but the text is short enough to plausibly BE a
                new category name itself (e.g. "pet grooming")
    "none"    - nothing usable found
    """
    if not text:
        return None, "none"
    low = text.lower().strip()

    for cat in known_categories:
        if low == cat.lower():
            return cat, "exact"

    for cat, keywords in CATEGORY_KEYWORDS.items():
        if cat not in known_categories:
            continue
        for kw in keywords:
            if re.search(r"\b" + re.escape(kw) + r"\b", low):
                return cat, "keyword"

    words = [w for w in re.findall(r"[a-zA-Z]+", low) if w not in _FILLER_WORDS]
    if (1 <= len(words) <= 3 and not parse_amount(text)
            and not all(w in _NON_CATEGORY_WORDS for w in words)):
        return " ".join(w.capitalize() for w in words), "custom"

    return None, "none"


# ---------------------------------------------------------------------------
# Description: whatever's left after amount/category/date phrases are
# stripped out. Confidence-gated - empty/too-short residuals return None
# rather than a guess.
# ---------------------------------------------------------------------------
def extract_description(text, category_hint=None):
    if not text:
        return None
    low = text.lower()

    low = re.sub(_CURRENCY_WORDS, " ", low)
    low = re.sub(r"[\d,]+(?:\.\d+)?", " ", low)
    # Only strip the category's own name if it was literally said (e.g.
    # "food" in "...on food for lunch"). Deliberately NOT stripping every
    # keyword in that category's keyword list - a word like "lunch" is
    # both a Food keyword AND a perfectly good description, and category
    # detection already consumed its signal; the description should keep it.
    if category_hint:
        low = re.sub(r"\b" + re.escape(category_hint.lower()) + r"\b", " ", low)
    for phrase in ("day before yesterday", "today", "yesterday", "tomorrow"):
        low = low.replace(phrase, " ")

    words = [w for w in low.split() if w not in _FILLER_WORDS]
    residual = " ".join(words).strip()
    if len(residual) < 3:
        return None
    return residual[:1].upper() + residual[1:]


# ---------------------------------------------------------------------------
# Full-utterance extraction - used both for "say it all in one sentence"
# and to opportunistically pick up extra fields during a single-field answer.
# ---------------------------------------------------------------------------
def extract_all(text, known_categories, today=None):
    amount = parse_amount(text)
    category, cat_confidence = match_category(text, known_categories)
    date = parse_date_phrase(text, today)
    description = extract_description(text, category_hint=category)

    return {
        "amount": amount,
        "category": category,
        "category_confidence": cat_confidence,
        "date": date,
        "description": description,
    }


# ---------------------------------------------------------------------------
# Conversation state machine. Pure functions (no Flask/session/DB here) so
# they're fully unit-testable; app.py's /api/voice/extract route is a thin
# transport wrapper around update_draft() + next_step().
# ---------------------------------------------------------------------------
_YES_WORDS = {"yes", "yeah", "yep", "sure", "correct", "right", "ok", "okay", "save", "save it", "confirm"}
_NO_WORDS = {"no", "nope", "wrong", "incorrect", "cancel"}

EXPENSE_FIELDS = ["category", "amount", "description", "date"]
INCOME_FIELDS = ["source", "amount", "description", "date"]


def _is_yes(text):
    low = (text or "").lower().strip().strip(".")
    if low in _YES_WORDS:
        return True
    # word-boundary match only - "yesterday" must NOT match "yes" (no
    # boundary between "yes" and the "t" that follows it in that word)
    return bool(re.match(r"^(yes|yeah|yep|sure|correct|right|ok|okay|confirm|save)\b", low))


def _is_no(text):
    low = (text or "").lower().strip().strip(".")
    if low in _NO_WORDS:
        return True
    return bool(re.match(r"^(no|nope|wrong|incorrect|cancel)\b", low))


def update_draft(draft, utterance, asking_field, context, known_categories, today=None):
    """
    Returns a NEW draft dict (does not mutate the input) with whatever this
    utterance contributed. `asking_field` is the field the UI most recently
    asked about (or None for an opening free-form utterance) - the direct
    answer to that field is trusted first; any OTHER field the sentence
    happens to also contain is filled in opportunistically, but only if
    that field is still empty (a direct answer never gets overwritten by a
    bonus guess from a later utterance).
    """
    draft = dict(draft or {})
    bonus = extract_all(utterance, known_categories, today=today)

    if asking_field == "category_confirm":
        if _is_yes(utterance):
            draft["category"] = draft.get("category_pending")
            draft["category_confidence"] = "confirmed"
            draft.pop("category_pending", None)
        elif _is_no(utterance):
            draft["category_pending"] = None
            draft["category_confidence"] = "none"
        else:
            cat, conf = match_category(utterance, known_categories)
            draft["category"] = cat if conf in ("exact", "keyword") else None
            draft["category_pending"] = cat if conf == "custom" else None
            draft["category_confidence"] = conf

    elif asking_field == "category":
        cat, conf = match_category(utterance, known_categories)
        if conf in ("exact", "keyword"):
            draft["category"] = cat
            draft["category_confidence"] = conf
        elif conf == "custom":
            draft["category_pending"] = cat
            draft["category_confidence"] = "custom"
        else:
            draft["category_confidence"] = "none"

    elif asking_field == "amount":
        amt = parse_amount(utterance)
        if amt is not None:
            draft["amount"] = amt

    elif asking_field == "date":
        if _is_yes(utterance):
            draft["date"] = (today or datetime.now().date()).isoformat()
        else:
            d = parse_date_phrase(utterance, today=today)
            if d:
                draft["date"] = d

    elif asking_field == "description":
        text = (utterance or "").strip()
        if text and not _is_no(text):
            draft["description"] = text[:1].upper() + text[1:]

    elif asking_field == "source":  # income only
        text = (utterance or "").strip()
        if text:
            draft["source"] = text[:1].upper() + text[1:]

    # Opportunistic bonus fields from the SAME utterance, only filling gaps.
    if not draft.get("amount") and bonus["amount"] is not None:
        draft["amount"] = bonus["amount"]
    if not draft.get("date") and bonus["date"]:
        draft["date"] = bonus["date"]
    if not draft.get("description") and bonus["description"] and asking_field not in ("description",):
        draft["description"] = bonus["description"]
    if context == "expense" and not draft.get("category") and not draft.get("category_pending") and asking_field not in ("category", "category_confirm"):
        if bonus["category_confidence"] in ("exact", "keyword"):
            draft["category"] = bonus["category"]
            draft["category_confidence"] = bonus["category_confidence"]
        elif bonus["category_confidence"] == "custom":
            draft["category_pending"] = bonus["category"]
            draft["category_confidence"] = "custom"
    if context == "income" and not draft.get("source") and asking_field != "source":
        # Income has no category keyword table; a short free-form opening
        # line's non-amount, non-date residue is a reasonable source guess.
        residual = extract_description(utterance)
        if residual and asking_field is None:
            draft["source"] = residual

    return draft


def next_step(draft, context):
    """
    Returns (next_question, missing_field, low_confidence, ready_to_confirm).
    `missing_field` is the single field the next question is about (or
    "category_confirm"), matching what the client should send back as
    `asking_field` on the following turn.
    """
    draft = draft or {}

    if context == "expense" and draft.get("category_confidence") == "custom" and draft.get("category_pending"):
        q = (f"I couldn't confidently determine the category. Should I use "
             f"\"{draft['category_pending']}\", or would you like a different one?")
        return q, "category_confirm", True, False

    required = EXPENSE_FIELDS if context == "expense" else INCOME_FIELDS
    questions = {
        "category": "What type of expense is this?",
        "amount": "How much did you spend?" if context == "expense" else "How much did you receive?",
        "date": "Would you like to use today's date?",
        "description": "What was it for?" if context == "expense" else "What's the source, in a bit more detail?",
        "source": "What type of income is this?",
    }

    for field in required:
        if not draft.get(field):
            return questions[field], field, False, False

    return "confirmation", None, False, True

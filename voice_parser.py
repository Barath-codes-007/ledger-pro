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


_DATE_FRAGMENTS = [
    r"\b\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}\b",              # 05-10-2026
    r"\b20\d{2}-\d{1,2}-\d{1,2}\b",                       # 2026-10-05
    r"\b[a-z0-9]+\s+(?:day|days|week|weeks)\s+ago\b",     # two days ago
    r"\b\d{1,2}(?:st|nd|rd|th)?\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\b",
    r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+\d{1,2}(?:st|nd|rd|th)?\b",
]


def _strip_dates(text):
    """Remove date phrases so their digits are never mistaken for an amount."""
    for pattern in _DATE_FRAGMENTS:
        text = re.sub(pattern, " ", text)
    return text


def parse_amount(text, strict=False):
    """
    Returns a float amount or None. Handles: "350", "₹500", "500 rupees",
    "rs 500", "1,000.50", "five hundred", "two point five thousand",
    "twenty five thousand", "two lakh".

    strict=True is used when sniffing an amount out of a sentence that was
    NOT an answer to "how much?" (so "I had two coffees" isn't read as an
    amount of 2): number WORDS then only count with a currency word or a
    scale word (hundred/thousand/lakh/crore) alongside them.
    """
    if not text:
        return None
    cleaned = _strip_dates(text.lower().strip())

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
    if strict and not (re.search(_CURRENCY_WORDS, cleaned)
                       or re.search(r"\b(hundred|thousand|lakh|lac|crore)\b", cleaned)):
        return None
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

    # "two days ago", "3 days ago", "a week ago"
    ago = re.search(r"\b([a-z0-9]+)\s+(day|days|week|weeks)\s+ago\b", low)
    if ago:
        qty_text, unit = ago.group(1), ago.group(2)
        qty = 1 if qty_text in ("a", "an", "one") else None
        if qty is None:
            qty = int(qty_text) if qty_text.isdigit() else _words_to_number(qty_text)
        if qty:
            days = int(qty) * (7 if unit.startswith("week") else 1)
            return (today - timedelta(days=days)).isoformat()

    # Numeric day-first dates, the Indian convention: 05-10-2026, 5/10/2026
    numeric = re.search(r"\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})\b", low)
    if numeric:
        try:
            d, mo, y = int(numeric.group(1)), int(numeric.group(2)), int(numeric.group(3))
            return datetime(y, mo, d).date().isoformat()
        except ValueError:
            return None

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
            if re.search(r"\b" + re.escape(kw) + r"(?:s|es)?\b", low):
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
    low = _strip_dates(text.lower())

    # Drop the merchant ("at Swiggy") and payment ("by UPI") phrases - they
    # are captured as their own fields, so they shouldn't also pollute the
    # description.
    merchant = parse_merchant(text)
    if merchant:
        low = re.sub(r"\b(?:at|from)\s+" + re.escape(merchant.lower()), " ", low)
    for kws in PAYMENT_KEYWORDS.values():
        for kw in kws:
            low = re.sub(r"\b(?:by|using|via|through|with|paid)\s+(?:the\s+)?" + re.escape(kw) + r"\b", " ", low)

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
    amount = parse_amount(text, strict=True)
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
# Payment mode, currency and merchant parsing (fields the manual form has
# that the first version of voice entry did not ask for)
# ---------------------------------------------------------------------------
PAYMENT_KEYWORDS = {
    "Cash": ["cash"],
    "Credit Card": ["credit card", "credit"],
    "Debit Card": ["debit card", "debit", "card"],
    "UPI": ["upi", "gpay", "g pay", "google pay", "phonepe", "phone pe", "paytm", "bhim"],
    "Net Banking": ["net banking", "netbanking", "internet banking", "bank transfer", "online banking"],
    "Wallet": ["wallet", "amazon pay"],
}


def parse_payment_mode(text, known_modes=None):
    """Returns one of the app's real payment modes, or None. Longer phrases
    are matched in preference so 'credit card' is not mistaken for 'card'."""
    if not text:
        return None
    low = text.lower()
    candidates = []
    for mode, keywords in PAYMENT_KEYWORDS.items():
        if known_modes is not None and mode not in known_modes:
            continue
        for kw in keywords:
            if re.search(r"\b" + re.escape(kw) + r"\b", low):
                candidates.append((len(kw), mode))
    if not candidates:
        return None
    return max(candidates)[1]


CURRENCY_KEYWORDS = {
    "INR": ["rupees", "rupee", "inr", "rs", "₹"],
    "USD": ["dollars", "dollar", "usd", "$"],
    "EUR": ["euros", "euro", "eur", "€"],
    "GBP": ["pounds", "pound", "gbp", "£"],
    "JPY": ["yen", "jpy", "¥"],
    "AUD": ["australian dollars", "australian dollar", "aud"],
    "CAD": ["canadian dollars", "canadian dollar", "cad"],
}


def parse_currency(text, known_currencies=None):
    """Returns an ISO currency code the app supports, or None."""
    if not text:
        return None
    low = text.lower()
    candidates = []
    for code, keywords in CURRENCY_KEYWORDS.items():
        if known_currencies is not None and code not in known_currencies:
            continue
        for kw in keywords:
            pattern = re.escape(kw) if not kw.isalpha() else r"\b" + re.escape(kw) + r"\b"
            if re.search(pattern, low):
                candidates.append((len(kw), code))
    if not candidates:
        return None
    return max(candidates)[1]


_MERCHANT_STOP = {
    "for", "on", "today", "yesterday", "tomorrow", "by", "using", "via", "with",
    "and", "paid", "rupees", "rupee", "rs", "dollars", "euros", "in", "from",
    "cash", "upi", "card", "last", "this", "at",
}


def parse_merchant(text):
    """
    Pulls a merchant out of phrases like 'at Swiggy' or 'from Big Bazaar'
    (up to 3 words, stopping at a connector/date/payment word). Returns None
    when no clear 'at/from <name>' phrase exists - never guesses.
    """
    if not text:
        return None
    m = re.search(r"\b(?:at|from)\s+([A-Za-z][A-Za-z&'.\-]*(?:\s+[A-Za-z&'.\-]+){0,2})", text)
    if not m:
        return None
    words = []
    for w in m.group(1).split():
        if w.lower() in _MERCHANT_STOP or re.fullmatch(r"\d+", w):
            break
        words.append(w)
    if not words:
        return None
    return " ".join(w[:1].upper() + w[1:] for w in words)


# ---------------------------------------------------------------------------
# Conversation state machine. Pure functions (no Flask/session/DB here) so
# they're fully unit-testable; app.py's /api/voice/extract route is a thin
# transport wrapper around update_draft() + next_step().
# ---------------------------------------------------------------------------
_YES_WORDS = {"yes", "yeah", "yep", "sure", "correct", "right", "ok", "okay", "save", "save it", "confirm", "i do", "i have"}
_NO_WORDS = {"no", "nope", "wrong", "incorrect", "cancel", "i don't", "i do not", "don't have", "none"}
_SKIP_WORDS = {"skip", "skip it", "pass", "none", "nothing", "no merchant", "not needed", "no need", "nope", "no"}

# Question order. The first four follow the original spec's recommended
# order; the rest are the manual-form fields voice entry was missing.
EXPENSE_FIELDS = ["category", "amount", "description", "date", "payment_mode", "merchant", "currency", "receipt"]
INCOME_FIELDS = ["source", "amount", "description", "date"]

DATE_FORMAT_HINT = "Say it like \"yesterday\", \"5th October\", \"two days ago\", or \"05-10-2026\" (day-month-year)."


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


def _is_skip(text):
    low = (text or "").lower().strip().strip(".")
    return low in _SKIP_WORDS or bool(re.match(r"^(skip|pass)\b", low))


def _satisfied(draft, field):
    """A field counts as handled if it has a value OR it's an optional
    field the person explicitly chose to skip."""
    if field in (draft.get("skipped") or []):
        return True
    if field == "receipt":
        return draft.get("receipt") in ("no", "attached", "skipped")
    return bool(draft.get(field))


def update_draft(draft, utterance, asking_field, context, known_categories, today=None,
                 user_currency="INR", payment_modes=None, currencies=None):
    """
    Returns a NEW draft dict (does not mutate the input) with whatever this
    utterance contributed. `asking_field` is the field the UI most recently
    asked about (or None for an opening free-form utterance) - the direct
    answer to that field is trusted first; any OTHER field the sentence
    happens to also contain is filled in opportunistically, but only if
    that field is still empty (a direct answer never gets overwritten by a
    bonus guess from a later utterance).

    When a direct answer can't be understood, `last_error` records which
    field, so next_step() can say what went wrong and what format to use
    instead of silently repeating the same question.
    """
    draft = dict(draft or {})
    draft.pop("last_error", None)
    bonus = extract_all(utterance, known_categories, today=today)
    today_date = today or datetime.now().date()

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
            draft["last_error"] = "category"

    elif asking_field == "amount":
        amt = parse_amount(utterance)
        if amt is not None and amt > 0:
            draft["amount"] = amt
        else:
            draft["last_error"] = "amount"

    elif asking_field == "date":
        d = parse_date_phrase(utterance, today=today)
        if d:
            # Includes "no, yesterday" - a real date in the answer wins.
            draft["date"] = d
            draft.pop("date_declined_today", None)
        elif _is_yes(utterance) and not draft.get("date_declined_today"):
            draft["date"] = today_date.isoformat()
            draft.pop("date_declined_today", None)
        elif _is_no(utterance):
            # "No" to "use today's date?" - ask for the actual date next
            # (this used to just repeat the same question forever).
            draft["date_declined_today"] = True
        else:
            draft["date_declined_today"] = True
            draft["last_error"] = "date"

    elif asking_field == "description":
        text = (utterance or "").strip()
        if text and not _is_no(text):
            draft["description"] = text[:1].upper() + text[1:]
        else:
            draft["last_error"] = "description"

    elif asking_field == "source":  # income only
        text = (utterance or "").strip()
        if text:
            draft["source"] = text[:1].upper() + text[1:]
        else:
            draft["last_error"] = "source"

    elif asking_field == "payment_mode":
        mode = parse_payment_mode(utterance, payment_modes)
        if mode:
            draft["payment_mode"] = mode
        else:
            draft["last_error"] = "payment_mode"

    elif asking_field == "merchant":
        text = (utterance or "").strip()
        if _is_skip(text):
            draft["skipped"] = list(set((draft.get("skipped") or []) + ["merchant"]))
            draft.pop("merchant", None)
        elif text:
            draft["merchant"] = text[:1].upper() + text[1:]
            draft["skipped"] = [f for f in (draft.get("skipped") or []) if f != "merchant"]
        else:
            draft["last_error"] = "merchant"

    elif asking_field == "currency":
        code = parse_currency(utterance, currencies)
        if code:
            draft["currency"] = code
        elif _is_yes(utterance):
            draft["currency"] = user_currency
        else:
            draft["last_error"] = "currency"

    elif asking_field == "receipt":
        if _is_yes(utterance):
            draft["receipt"] = "pending"
        elif _is_no(utterance) or _is_skip(utterance):
            draft["receipt"] = "no"
        else:
            draft["last_error"] = "receipt"

    elif asking_field == "receipt_capture":
        low = (utterance or "").lower()
        if "attached" in low:
            draft["receipt"] = "attached"
        elif _is_skip(utterance) or _is_no(utterance):
            draft["receipt"] = "skipped"
        # anything else: stay waiting for a photo/file or an explicit skip

    # Opportunistic bonus fields from the SAME utterance, only filling gaps.
    if not draft.get("amount") and bonus["amount"] is not None and asking_field not in ("amount",):
        draft["amount"] = bonus["amount"]
    if not draft.get("date") and bonus["date"] and asking_field not in ("date",):
        draft["date"] = bonus["date"]
    if not draft.get("description") and bonus["description"] and asking_field not in ("description",):
        draft["description"] = bonus["description"]
    if context == "expense":
        if not draft.get("category") and not draft.get("category_pending") and asking_field not in ("category", "category_confirm"):
            if bonus["category_confidence"] in ("exact", "keyword"):
                draft["category"] = bonus["category"]
                draft["category_confidence"] = bonus["category_confidence"]
            elif bonus["category_confidence"] == "custom":
                draft["category_pending"] = bonus["category"]
                draft["category_confidence"] = "custom"
        # Extra manual-form fields, picked up only if clearly present.
        if not draft.get("payment_mode") and asking_field != "payment_mode":
            mode = parse_payment_mode(utterance, payment_modes)
            if mode:
                draft["payment_mode"] = mode
        if not draft.get("merchant") and "merchant" not in (draft.get("skipped") or []) and asking_field != "merchant":
            merchant = parse_merchant(utterance)
            if merchant:
                draft["merchant"] = merchant
        if not draft.get("currency") and asking_field not in ("currency",):
            code = parse_currency(utterance, currencies)
            if code:
                draft["currency"] = code
    if context == "income" and not draft.get("source") and asking_field != "source":
        # Income has no category keyword table; a short free-form opening
        # line's non-amount, non-date residue is a reasonable source guess.
        residual = extract_description(utterance)
        if residual and asking_field is None:
            draft["source"] = residual

    return draft


def question_for(field, context, draft=None, user_currency="INR"):
    """The question text for any field, used both for the normal flow and
    for the review card's per-field Edit buttons (single source of truth)."""
    draft = draft or {}
    questions = {
        "category": "What type of expense is this?",
        "amount": "How much did you spend?" if context == "expense" else "How much did you receive?",
        "description": "What was it for?" if context == "expense" else "What's the source, in a bit more detail?",
        "source": "What type of income is this?",
        "payment_mode": "What type of payment is this? For example cash, UPI, credit card, debit card, net banking, or wallet.",
        "merchant": "Where did you spend it? Say the shop or merchant name, or say skip.",
        "currency": f"Was this in {user_currency}? Say yes, or tell me the currency, like dollars or euros.",
        "receipt": "Do you have a receipt to attach? Say yes or no.",
        "receipt_capture": "Please take a photo of the receipt or upload a file using the buttons below, or choose skip.",
    }
    if field == "date":
        if draft.get("date_declined_today"):
            return "What date was it? " + DATE_FORMAT_HINT
        return "Would you like to use today's date? Say yes, or tell me a different date."
    return questions.get(field, "Can you say that again?")


_ERROR_MESSAGES = {
    "amount": "I couldn't understand the amount. Please say it again, for example, \"500 rupees\".",
    "date": "I couldn't understand that date. " + DATE_FORMAT_HINT,
    "category": "I couldn't match that to a category. Try something like Food, Transport or Shopping, or tell me a new category name.",
    "payment_mode": "I didn't catch the payment type. Please say cash, UPI, credit card, debit card, net banking, or wallet.",
    "currency": "I couldn't tell the currency. Say yes to keep the default, or say rupees, dollars, euros, pounds, yen.",
    "receipt": "Please say yes if you have a receipt to attach, or no to continue without one.",
    "description": "I didn't catch that. Please tell me what it was for.",
    "source": "I didn't catch that. Please tell me the type of income.",
    "merchant": "I didn't catch that. Say the merchant name, or say skip.",
}


def hint_for(field):
    """A short format hint shown under the question in the UI."""
    return {
        "date": "Examples: today · yesterday · 5th October · two days ago · 05-10-2026 (day-month-year)",
        "amount": "Examples: 500 · 500 rupees · five hundred · two point five thousand",
        "payment_mode": "Cash · UPI · Credit Card · Debit Card · Net Banking · Wallet",
        "currency": "INR · USD · EUR · GBP · JPY · AUD · CAD (or say yes for the default)",
        "merchant": "Optional - say skip to leave it blank",
        "receipt_capture": "Use Take photo, Upload file, or Skip receipt",
    }.get(field)


def next_step(draft, context, user_currency="INR"):
    """
    Returns (next_question, missing_field, low_confidence, ready_to_confirm).
    `missing_field` is the single field the next question is about (or
    "category_confirm" / "receipt_capture"), matching what the client
    should send back as `asking_field` on the following turn. If the last
    answer couldn't be understood, the question says what went wrong and
    the expected format instead of silently repeating itself.
    """
    draft = draft or {}

    if context == "expense" and draft.get("category_confidence") == "custom" and draft.get("category_pending"):
        q = (f"I couldn't confidently determine the category. Should I use "
             f"\"{draft['category_pending']}\", or would you like a different one?")
        return q, "category_confirm", True, False

    if context == "expense" and draft.get("receipt") == "pending":
        return question_for("receipt_capture", context), "receipt_capture", False, False

    required = EXPENSE_FIELDS if context == "expense" else INCOME_FIELDS
    for field in required:
        if _satisfied(draft, field):
            continue
        question = question_for(field, context, draft, user_currency)
        if draft.get("last_error") == field:
            # Each error message already says what went wrong AND what to
            # say instead, so it replaces the question rather than adding to it.
            question = _ERROR_MESSAGES.get(field) or question
        return question, field, False, False

    return "confirmation", None, False, True
